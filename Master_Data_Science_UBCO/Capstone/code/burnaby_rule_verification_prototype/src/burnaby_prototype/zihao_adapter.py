"""Adapters for external extraction outputs.

Role: legacy Pipeline-3 adapter; not the product path. It only translates an
earlier prototype's extraction artifacts into the standard candidate/evidence
contract; the M7 product pipeline does not depend on it.

The slim verifier accepts candidate/evidence JSON. This module converts Zihao's
prototype extraction artifacts into that contract without trusting any upstream
confidence or verification labels.

Think of this file as a translator, not a verifier:

Zihao output names/fields -> our standard candidate/evidence contract.

Nothing here is allowed to decide that a rule is legally correct. That decision
belongs to verification.py.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import RULE_OBJECT_ALIASES, gis_relevance_for_rule_object, unit_key
from .normalization_rules import applies_to_hint, get_normalization


def adapt_zihao_outputs(
    evidence_records: list[dict[str, Any]] | None,
    rule_records: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Convert Zihao handoff records into verifier-ready records.

    Zihao's Pipeline 3 usually gives both evidence_units.json and
    rule_candidates.json. If a candidate points to evidence that is missing from
    the evidence file, this adapter creates a minimal evidence unit from the
    candidate's own source text so the verifier can still judge it explicitly.
    """
    evidence_units = [_adapt_evidence_unit(record) for record in evidence_records or []]
    evidence_by_id = {unit["evidence_id"]: unit for unit in evidence_units}

    candidates: list[dict[str, Any]] = []
    for index, record in enumerate(rule_records, start=1):
        evidence_id = _record_evidence_id(record)
        if evidence_id and evidence_id not in evidence_by_id:
            evidence = _evidence_from_rule_record(record)
            evidence_units.append(evidence)
            evidence_by_id[evidence["evidence_id"]] = evidence
        elif not evidence_id:
            evidence = _evidence_from_rule_record(record, fallback_index=index)
            evidence_units.append(evidence)
            evidence_by_id[evidence["evidence_id"]] = evidence
            evidence_id = evidence["evidence_id"]

        candidates.append(_adapt_candidate(record, evidence_id, index, config))

    return {
        "evidence_units": _dedupe_evidence(evidence_units),
        "rule_candidates": _dedupe_candidates(candidates),
    }


def adapt_pipeline5_registry(
    registry: dict[str, Any] | list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Convert Pipeline 5 final_rule_registry.json into verifier inputs.

    Pipeline 5 does not use the old handoff folder. Its final deliverable is a
    single JSON file with a top-level ``rules`` array. We convert those rules
    into the same candidate/evidence contract used by Pipeline 3 so verification
    stays unchanged.
    """
    rules = registry.get("rules", []) if isinstance(registry, dict) else registry
    adapted_records = [_pipeline5_rule_to_record(rule) for rule in rules]
    return adapt_zihao_outputs(None, adapted_records, config)


def _pipeline5_rule_to_record(rule: dict[str, Any]) -> dict[str, Any]:
    """Map one Pipeline 5 registry rule into the adapter's common record shape."""
    record = dict(rule)
    record["candidate_id"] = rule.get("merged_rule_id") or rule.get("rule_id")
    record["evidence_id"] = rule.get("merged_rule_id") or rule.get("rule_id")
    record["source_evidence_id"] = record["evidence_id"]
    record["source_evidence_text"] = rule.get("evidence_text")
    record["source_context"] = rule.get("evidence_text")
    record["page"] = rule.get("page") or _page_from_source_id(rule.get("source_id"))
    record["evidence_type"] = "table_cell" if rule.get("source_stream") == "gemini_table_image" else "clause"
    record["table_parser"] = "pipeline5_visual_blocks"
    record["extraction_method"] = "pipeline5_final_registry"
    record["extraction_source"] = "zihao_pipeline5"
    record["extraction_final_action"] = "REVIEW" if rule.get("review_required") else "ACCEPT"
    record["extraction_review_reasons"] = rule.get("review_reasons")
    if rule.get("source_stream") == "gemini_table_image":
        record.setdefault("table_title", _table_title_from_text(str(rule.get("evidence_text") or "")))
        row_header, column_header, cell_value = _table_context_from_record(record, str(rule.get("evidence_text") or ""))
        record["row_header"] = row_header
        record["column_header"] = column_header
        record["cell_value"] = cell_value
    return record


def _adapt_evidence_unit(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize one evidence record into the fields verification.py expects."""
    text = _first_present(
        record,
        "evidence_text",
        "text",
        "source_evidence_text",
        "original_excerpt",
        "requirement_text",
    )
    row_header, column_header, cell_value = _table_context_from_record(record, text)
    evidence_type = _evidence_type(record, text)
    table_title = record.get("table_title") or record.get("group_title") or record.get("heading_path") or _table_title_from_text(text)
    # For table cells, keep row/column/cell context together in evidence_text.
    # This makes downstream verification easier to audit.
    if evidence_type == "table_cell":
        text = _combined_table_text(table_title, row_header, column_header, cell_value, text)
    return {
        "evidence_id": _record_evidence_id(record),
        "block_id": str(record.get("block_id") or record.get("source_block_id") or ""),
        "page": record.get("page") or record.get("page_number") or _first_page(record.get("pages")),
        "evidence_type": evidence_type,
        "rule_family": record.get("rule_family") or record.get("block_topic") or record.get("rule_type") or "",
        "applies_to_hint": record.get("applies_to_hint") or record.get("applies_to") or record.get("building_type") or "",
        "evidence_text": text,
        "source_context": record.get("source_context") or record.get("original_excerpt") or text,
        "section": record.get("section") or record.get("bylaw_section"),
        "heading": record.get("heading") or record.get("heading_path"),
        "relevance": record.get("relevance") or record.get("relevance_category") or "external",
        "notes": "adapted from Zihao output",
        "table_title": table_title,
        "row_header": row_header,
        "column_header": column_header,
        "cell_value": cell_value,
        "unit": record.get("unit"),
        "bbox": record.get("bbox"),
        "table_parser": record.get("table_parser") or "zihao_adapter",
        "adapter_source": "zihao",
    }


def _evidence_from_rule_record(record: dict[str, Any], fallback_index: int | None = None) -> dict[str, Any]:
    """Build evidence from a rule record when the separate evidence file lacks it."""
    evidence_id = str(
        record.get("evidence_id")
        or record.get("source_evidence_id")
        or record.get("evidence_sentence_id")
        or record.get("rule_id")
        or record.get("candidate_id")
        or f"zihao_ev_{fallback_index:03d}"
    )
    evidence_text = _first_present(
        record,
        "evidence_text",
        "source_evidence_text",
        "evidence_sentence",
        "original_excerpt",
        "requirement_text",
    )
    return _adapt_evidence_unit(
        {
            **record,
            "evidence_id": evidence_id,
            "evidence_text": evidence_text,
            "source_context": record.get("original_excerpt") or evidence_text,
        }
    )


def _adapt_candidate(
    record: dict[str, Any], evidence_id: str, index: int, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Normalize one extracted rule into our standard candidate contract."""
    rule_object = _normalize_rule_object(record.get("rule_object") or record.get("rule_type"), record)
    constraint_type = _normalize_constraint_type(record.get("constraint_type"), record.get("operator"))
    operator = _normalize_operator(record.get("operator"), constraint_type, record.get("value"))
    value = record.get("value")
    unit = record.get("unit")
    condition = record.get("condition")
    # The ONE place this translator overwrites upstream value/operator/unit:
    # upstream encodes the sprinkler trigger's value field as something other
    # than the distance threshold, so we re-derive it from the rule's own
    # wording ("more than X m"). Safe because the verifier re-checks the
    # rewritten value/unit/operator against the cited evidence afterwards — a
    # wrong rewrite cannot verify, it can only fail support checks.
    if rule_object == "automatic_sprinkler":
        match = re.search(r"more than\s+(\d+(?:\.\d+)?)\s*m", _candidate_semantic_text(record.get("rule_object"), record))
        if match:
            number = float(match.group(1))
            value = int(number) if number.is_integer() else number
            unit = "m"
            operator = ">"
            constraint_type = "required"
            condition = condition or "distance from lot line abutting a street"
    applies_to = (
        _coerce_applies_to(record.get("applies_to"))
        or _applies_to_from_record(record, rule_object, config)
        or _subject_as_applies_to(record, rule_object)
    )
    return {
        "candidate_id": str(record.get("candidate_id") or record.get("rule_id") or f"zihao_cand_{index:03d}"),
        "evidence_id": evidence_id,
        "rule_object": rule_object,
        "constraint_type": constraint_type,
        "constraint_scope": record.get("constraint_scope") or _constraint_scope_from_record(record, rule_object),
        "applies_to": applies_to,
        "operator": operator,
        "value": value,
        "unit": unit,
        "condition": condition,
        "exception": record.get("exception"),
        "gis_relevance": record.get("gis_relevance") or _gis_relevance(record),
        "notes": record.get("notes") or "adapted external candidate",
        "extraction_method": record.get("extraction_method") or "zihao_adapter",
        "extraction_source": "zihao",
        "source_stream": record.get("source_stream"),
        "rule_key": record.get("rule_key"),
        "subject": record.get("subject"),
        "relevance_category": record.get("relevance_category"),
        # Preserve Zihao's metadata for audit only. The verifier may use REVIEW
        # as a conservative signal, but ACCEPT cannot override missing proof.
        "extraction_final_action": record.get("extraction_final_action"),
        "extraction_support_gaps": record.get("extraction_support_gaps"),
        "extraction_review_reasons": record.get("extraction_review_reasons"),
        "original_rule_id": record.get("rule_id"),
        "original_excerpt": record.get("original_excerpt")
        or record.get("evidence_text")
        or record.get("source_evidence_text"),
        "sentence_match_score": record.get("sentence_match_score"),
        "possible_missing_numeric_values": record.get("possible_missing_numeric_values"),
        "zihao_verification_status": record.get("verification_status"),
        "zihao_confidence": record.get("confidence"),
        "zihao_needs_review": record.get("needs_review"),
    }


def _first_present(record: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty field from a list of possible upstream names."""
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _record_evidence_id(record: dict[str, Any]) -> str:
    """Read the evidence ID no matter which upstream field name was used."""
    return str(
        record.get("evidence_id")
        or record.get("source_evidence_id")
        or record.get("evidence_sentence_id")
        or ""
    )


def _first_page(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _page_from_source_id(value: Any) -> int | None:
    """Parse Pipeline 5 source IDs such as page_0002__table_001."""
    match = re.search(r"page_(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _cell_value_from_record(record: dict[str, Any]) -> Any:
    """Recover the cell value from Zihao's possible table/value fields."""
    if record.get("cell_value") not in (None, ""):
        return record.get("cell_value")
    if record.get("cell_text") not in (None, ""):
        return record.get("cell_text")
    value = record.get("value")
    unit = record.get("unit")
    if value not in (None, "") and unit not in (None, ""):
        return f"{value} {unit}"
    return value


def _evidence_type(record: dict[str, Any], text: str) -> str:
    """Infer whether evidence behaves like a table cell or plain evidence."""
    evidence_type = str(record.get("evidence_type") or "")
    if evidence_type:
        return evidence_type
    if "|" in text and re.search(r"\d", text):
        return "table_cell"
    return "external_evidence"


def _table_context_from_record(record: dict[str, Any], text: str) -> tuple[Any, Any, Any]:
    """Recover row header, column header, and cell value.

    This is a slightly tricky fallback: if structured table fields are missing,
    we try to split a pipe-delimited evidence string such as
    "Minimum Setbacks | Lane Yard | 1.5 m".
    """
    row_header = record.get("row_header") or record.get("row_label") or record.get("subject")
    column_header = record.get("column_header") or record.get("column_name")
    # _cell_value_from_record already tries cell_value, then cell_text, then a
    # value+unit composite — no need to repeat its first two checks here.
    cell_value = _cell_value_from_record(record)

    parts = [part.strip(" /") for part in text.split("|")]
    parts = [part for part in parts if part and not re.fullmatch(r"row\d+", part.lower())]
    value = str(record.get("value") or "").strip()
    # Digit-boundary lookarounds: value '5' must not anchor on the '5' inside
    # '1.5' or '50'. The part immediately BEFORE the matched value cell is
    # assumed to be the row header and everything AFTER it the column header,
    # matching how upstream serializes 'Title | Row | Value' fragments.
    value_index = next(
        (
            index
            for index, part in enumerate(parts)
            if value and re.search(rf"(?<!\d){re.escape(value)}(?!\d)", part)
        ),
        None,
    )
    if value_index is None:
        value_index = next((index for index, part in enumerate(parts) if _contains_value(part)), None)
    if value_index is None:
        return row_header, column_header, cell_value
    cell_value = cell_value or parts[value_index]
    if not row_header and value_index > 0:
        row_header = parts[value_index - 1]
    if not column_header and value_index + 1 < len(parts):
        column_header = " ".join(parts[value_index + 1 :]).strip()
    if not column_header and value_index > 1:
        column_header = parts[value_index - 1]
    return row_header, column_header, cell_value


def _combined_table_text(*parts: Any) -> str:
    """Join table context without repeating the same phrase several times."""
    seen: set[str] = set()
    output: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return " | ".join(output)


def _table_title_from_text(text: str) -> str | None:
    """Infer a table title from common zoning table headings."""
    lower = text.lower()
    for title in [
        "permitted uses",
        "principal use",
        "subdivision regulations",
        "permitted dwelling units",
        "minimum lot area",
        "maximum lot area",
        "maximum lot coverage",
        "impervious surfaces",
        "maximum height",
        "minimum lot line setbacks",
        "minimum separation of buildings",
        "access and fire safety",
    ]:
        if title in lower:
            return title.title()
    return None


def _contains_value(text: str) -> bool:
    """Return True when text contains a zoning-like numeric value."""
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:m2|m²|m|%|storeys?|units?)?\b", text, flags=re.IGNORECASE))


def _normalize_rule_object(value: Any, record: dict[str, Any] | None = None) -> Any:
    """Map Zihao's rule names into our canonical verifier rule objects."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    text = _candidate_semantic_text(value, record)
    focused_text = _candidate_focused_text(value, record)
    unit = unit_key(record.get("unit") if record else None)

    # Prefer Pipeline 5's focused semantic fields before broad evidence text.
    # The full evidence often contains neighbouring clauses, e.g. "lot coverage
    # ... 60% and impervious surface ... 70%"; subject/rule_key identify which
    # part the candidate is trying to claim.
    if "automatic_sprinkler" in focused_text or "sprinkler" in focused_text:
        return "automatic_sprinkler"
    if "fire_access_corridor" in focused_text or "fire access corridor" in focused_text:
        return "fire_access_corridor"
    if "lot_coverage" in focused_text or "lot coverage" in focused_text:
        return "lot_coverage"
    if "impervious" in focused_text:
        return "impervious_surface"

    if normalized in RULE_OBJECT_ALIASES:
        alias = RULE_OBJECT_ALIASES[normalized]
        # Zoning tables label one combined "building height" block in BOTH
        # metres and storeys; the upstream label is ambiguous, so the UNIT is
        # what identifies which row this number actually came from.
        if alias == "storeys" and unit == "m" and "height" in text:
            return "height"
        if alias == "dwelling_units":
            if "automatic_sprinkler" in text or "sprinkler" in text:
                return "automatic_sprinkler"
            if "fire_access_corridor" in text or "fire access corridor" in text:
                return "fire_access_corridor"
        return alias

    if "automatic_sprinkler" in text or "sprinkler" in text:
        return "automatic_sprinkler"
    if "fire_access_corridor" in text or "fire access corridor" in text:
        return "fire_access_corridor"
    if "lot_coverage" in text or "lot coverage" in text:
        return "lot_coverage"
    if "impervious" in text:
        return "impervious_surface"
    if "lot_area" in text or "lot area" in text:
        return "lot_area"
    if "dwelling_units" in text or "dwelling units" in text or "permitted dwelling units" in text:
        return "dwelling_units"
    if unit == "storeys" and any(token in text for token in ("storeys", "storey", "stories", "story")):
        return "storeys"
    if "height" in text and (unit == "m" or "storey" not in text):
        return "height"
    if "storeys" in text or "storey" in text or "stories" in text or "story" in text:
        return "storeys"
    if "separation" in text or "between_rear_principals" in text or "between_front_and_rear" in text:
        return "building_separation"
    if any(token in text for token in ["setback", "yard", "lot_line", "lane_yard", "street_yard"]):
        return "setback"
    if "permitted_use" in text or "permitted uses" in text or "principal use" in text or "use-specific" in text:
        return "permitted_use"
    return value


def _candidate_semantic_text(value: Any, record: dict[str, Any] | None) -> str:
    """Collect candidate fields used only for deterministic keyword mapping."""
    if not record:
        return re.sub(r"[_-]+", " ", str(value or "").lower())
    parts = [
        value,
        record.get("rule_key"),
        record.get("rule_type"),
        record.get("rule_object"),
        record.get("constraint_type"),
        record.get("subject"),
        record.get("evidence_text"),
        record.get("unit"),
        record.get("condition"),
    ]
    return " ".join(str(part or "") for part in parts).lower().replace("-", "_")


def _candidate_focused_text(value: Any, record: dict[str, Any] | None) -> str:
    """Return high-signal fields that name the candidate's intended rule."""
    if not record:
        return re.sub(r"[_-]+", " ", str(value or "").lower())
    parts = [
        value,
        record.get("rule_key"),
        record.get("rule_type"),
        record.get("rule_object"),
        record.get("subject"),
        record.get("unit"),
        record.get("condition"),
    ]
    return " ".join(str(part or "") for part in parts).lower().replace("-", "_")


def _constraint_scope_from_record(record: dict[str, Any], rule_object: Any) -> str | None:
    """Infer a useful constraint scope from rule_key/rule_object/condition."""
    text = " ".join(
        str(part or "")
        for part in [
            record.get("rule_key"),
            record.get("rule_object"),
            record.get("condition"),
        ]
    ).lower().replace("-", "_")
    if rule_object in {"height", "storeys"}:
        return "building"
    if rule_object == "dwelling_units":
        return "lot"
    if rule_object in {"lot_area", "lot_coverage", "impervious_surface"}:
        return "lot"
    if rule_object == "building_separation":
        return "building_separation"
    if rule_object == "fire_access_corridor":
        if "clear" in text or "height" in text:
            return "vertical_clearance"
        return "corridor_width"
    if rule_object == "automatic_sprinkler":
        return "dwelling_unit"
    if rule_object == "setback":
        for token in [
            "street_yard_front",
            "street_yard_flanking",
            "street_yard",
            "lane_yard",
            "interior_rear_yard",
            "interior_side_yard",
        ]:
            if token in text:
                return token
        if "lane" in text:
            return "lane_yard"
        if "front" in text:
            return "street_yard_front"
        if "flanking" in text:
            return "street_yard_flanking"
        if "rear" in text:
            return "interior_rear_yard"
        if "side" in text:
            return "interior_side_yard"
    if rule_object == "permitted_use":
        return "use"
    return record.get("rule_key")


def _applies_to_from_record(
    record: dict[str, Any], rule_object: Any, config: dict[str, Any] | None = None
) -> str | None:
    """Infer applies_to when Zihao did not provide it directly.

    The building-type / heritage labels below are Burnaby-specific. When a city
    supplies its OWN ``normalization.applies_to_hints`` (config-driven), use those
    instead, so we never stamp a Burnaby label (e.g. "Rear Principal Buildings")
    onto another city's rule. Burnaby has no ``normalization`` block (it runs on
    the default), so its path is unchanged. The verifier's config-driven
    ``_refine_normalized_candidate`` remains the authority and re-derives this for
    the families it covers; this inference is only a fallback.
    """
    text = " ".join(
        str(part or "")
        for part in [
            record.get("rule_key"),
            record.get("rule_object"),
            record.get("condition"),
            record.get("evidence_text"),
        ]
    ).lower()
    if rule_object == "automatic_sprinkler" and "dwelling unit" in text:
        match = re.search(r"more than\s+(\d+(?:\.\d+)?)\s*m", text)
        if match:
            return f"Dwelling units more than {match.group(1)} m from a street lot line"
        return "Dwelling units"
    if rule_object == "fire_access_corridor" and "dwelling unit" in text:
        return "All dwelling units"
    if config is not None and config.get("normalization"):
        # A city with its own normalization block drives applies_to from its
        # hints (or gets None and falls through to subject), never a Burnaby label.
        return applies_to_hint(rule_object, text, get_normalization(config).get("applies_to_hints", []))
    if "rear principal" in text:
        return "Rear Principal Buildings"
    if "front principal" in text:
        return "Front Principal Buildings"
    if "accessory" in text:
        return "Accessory Buildings"
    if rule_object in {"setback", "height", "storeys"} and "all building" in text:
        return "All Buildings"
    if "heritage" in text:
        return "Community Heritage Register lots"
    return None


def _subject_as_applies_to(record: dict[str, Any], rule_object: Any) -> str | None:
    """Use subject as applies_to only when it names the target, not the rule."""
    subject = str(record.get("subject") or "").strip()
    if not subject:
        return None
    subject_text = subject.lower()
    rule_self_terms = {
        "automatic_sprinkler": ("sprinkler",),
        "fire_access_corridor": ("fire access corridor", "corridor width", "vertical clearance"),
        "lot_coverage": ("lot coverage",),
        "impervious_surface": ("impervious",),
        "lot_area": ("lot area",),
        "dwelling_units": ("dwelling unit", "dwelling units"),
    }
    if any(term in subject_text for term in rule_self_terms.get(str(rule_object or ""), ())):
        return None
    return subject


def _normalize_constraint_type(value: Any, operator: Any) -> Any:
    """Normalize min/max/allowed/required wording."""
    text = f"{value or ''} {operator or ''}".lower()
    if any(token in text for token in ["min", "minimum", ">=", "at least"]):
        return "minimum"
    if any(token in text for token in ["max", "maximum", "<=", "not exceed"]):
        return "maximum"
    if any(token in text for token in ["allowed", "permitted"]):
        return "allowed"
    if "required" in text:
        return "required"
    return value


def _normalize_operator(operator: Any, constraint_type: Any, value: Any) -> Any:
    """Fill a missing operator from constraint_type when possible."""
    if str(operator or "").strip() == "==":
        if str(value or "").lower() in {"permitted", "allowed", "-"}:
            return "allowed"
        return "="
    if operator not in (None, ""):
        return operator
    text = str(constraint_type or "").lower()
    if text == "minimum":
        return ">="
    if text == "maximum":
        return "<="
    if text in {"allowed", "permitted"}:
        return "allowed"
    if text == "required":
        return "required"
    if value not in (None, "") and re.search(r"\d+\s+to\s+\d+", str(value)):
        return "range"
    return operator


def _gis_relevance(record: dict[str, Any]) -> str:
    """Mark geometry-facing rules as direct; everything else is context.

    Delegates to the shared, source-agnostic classifier so the legacy
    pipeline-5 lane and the native lane label the GIS contract identically.
    """
    rule_object = _normalize_rule_object(record.get("rule_object") or record.get("rule_type"), record)
    return gis_relevance_for_rule_object(rule_object)


def _coerce_applies_to(value: Any) -> Any:
    """Turn Pipeline 5 applies_to arrays into a readable string."""
    if isinstance(value, list):
        labels = []
        for item in value:
            if isinstance(item, dict):
                labels.append(str(item.get("rule_object") or item.get("subject") or item.get("condition") or ""))
            else:
                labels.append(str(item))
        labels = [label for label in labels if label]
        return "; ".join(labels) if labels else None
    return value


def _dedupe_evidence(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate evidence records after adaptation."""
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for unit in units:
        key = (
            str(unit.get("evidence_id") or ""),
            str(unit.get("evidence_text") or "").lower(),
            str(unit.get("cell_value") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(unit)
    return deduped


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove repeated candidate rules so the verifier sees each claim once.

    The key includes constraint_scope and operator: two genuinely different
    claims can share one evidence unit and the same value (a side-yard vs
    rear-yard setback both at 1.5 m, or a minimum and a maximum stating the
    same number). Dropping one of those BEFORE verification would hide it from
    the consensus and conflict guards — dedupe must only collapse true repeats.
    """
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str, str]] = set()
    for candidate in candidates:
        key = (
            str(candidate.get("evidence_id") or ""),
            str(candidate.get("rule_object") or "").lower(),
            str(candidate.get("constraint_scope") or "").lower(),
            str(candidate.get("applies_to") or "").lower(),
            str(candidate.get("operator") or "").lower(),
            str(candidate.get("value") or "").lower(),
            str(candidate.get("condition") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped
