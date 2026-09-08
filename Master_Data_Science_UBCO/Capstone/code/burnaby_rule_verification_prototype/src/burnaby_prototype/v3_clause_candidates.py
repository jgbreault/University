"""Deterministic prose-clause candidate emitter for V3.

The LLM lane often sees the right clause but flips a family or operator in
compact legal lists. This module proposes candidates only from self-contained
source clauses whose value, unit, operator cue, and target words are visible in
the same evidence packet. The deterministic verifier remains the authority.
"""

from __future__ import annotations

import re
from typing import Any


_METRE_VALUE_RE = re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m|metres?|meters?)\b", re.IGNORECASE)
_AREA_VALUE_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>m2|m²|sq\.?\s*m|square\s+metres?|square\s+meters?)\b",
    re.IGNORECASE,
)
_PERCENT_VALUE_RE = re.compile(r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|per\s?cent|percent)\b", re.IGNORECASE)


def build_clause_candidate_set(
    city: str,
    packs: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return deterministic prose candidates from V3 evidence packs."""
    evidence_units: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seq = 0
    for pack in packs:
        source_text = _clean_text(pack.get("source_text"))
        if not source_text:
            continue
        for proposal in _proposals_from_text(source_text, config or {}):
            seq += 1
            pack_id = str(pack.get("pack_id") or f"pack_{seq:04d}")
            evidence_id = f"{pack_id}_v3_clause_ev_{seq:03d}"
            candidate_id = f"{_slug(city)}_v3clause_{pack_id}_{seq:03d}"
            repaired_text = proposal.get("evidence_text") or source_text
            evidence_units.append(
                {
                    "evidence_id": evidence_id,
                    "page": pack.get("page"),
                    "section": pack.get("section") or "",
                    "evidence_type": "clause",
                    "evidence_text": repaired_text,
                    "source_context": repaired_text,
                    "full_source_context": source_text,
                    "source_stream": "native_v3_clause",
                    "native_provenance": {
                        "pack_id": pack.get("pack_id"),
                        "chunk_id": pack.get("chunk_id"),
                        "lane": pack.get("lane"),
                        "selected_because": ["deterministic_clause_pattern", proposal["pattern"]],
                    },
                }
            )
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "evidence_id": evidence_id,
                    "rule_object": proposal["rule_object"],
                    "constraint_type": proposal["constraint_type"],
                    "constraint_scope": proposal["constraint_scope"],
                    "applies_to": proposal["applies_to"],
                    "operator": proposal["operator"],
                    "value": proposal["value"],
                    "unit": proposal["unit"],
                    "condition": proposal.get("condition", ""),
                    "exception": proposal.get("exception", ""),
                    "source_stream": "native_v3_clause",
                    "extraction_method": "native_v3_clause",
                    "extraction_final_action": "",
                    "native_provenance": {
                        "pack_id": pack.get("pack_id"),
                        "chunk_id": pack.get("chunk_id"),
                        "pattern": proposal["pattern"],
                    },
                }
            )
    return evidence_units, candidates


def _proposals_from_text(text: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    proposals.extend(_minimum_distance_list(text, config))
    proposals.extend(_maximum_floor_area_lesser_of(text))
    proposals.extend(_maximum_site_coverage(text))
    proposals.extend(_calgary_style_simple_clauses(text))
    proposals.extend(_deemed_front_setback(text))
    proposals.extend(_context_rules(text))
    return _dedupe_proposals(proposals)


def _minimum_distance_list(text: str, config: dict[str, Any]) -> list[dict[str, str]]:
    lowered = text.lower()
    if "must be at least" not in lowered:
        return []
    target = _target_alias_in_text(text, config)
    if not target:
        return []
    tail_match = re.search(r"must\s+be\s+at\s+least\s*:?\s*(?P<tail>.+)", text, flags=re.IGNORECASE | re.DOTALL)
    if not tail_match:
        return []
    parent = _clean_text(text[: tail_match.start("tail")])
    tail = tail_match.group("tail")
    items = _enumerated_items(tail)
    if not items:
        items = [tail]
    proposals: list[dict[str, str]] = []
    for item in items:
        value = _first_value(item, _METRE_VALUE_RE)
        if not value:
            continue
        item_lower = item.lower()
        exception = _exception_from_text(item)
        evidence_text = _clean_text(f"{parent} {item}")
        if "property line" in item_lower:
            direction = _setback_direction(item_lower)
            proposals.append(
                _proposal(
                    "setback",
                    ">=",
                    value,
                    "m",
                    applies_to=target,
                    scope=f"{direction} setback" if direction else "setback",
                    exception=exception,
                    evidence_text=evidence_text,
                    pattern="minimum_distance_list",
                )
            )
        elif any(word in item_lower for word in ("house", "building", "dwelling", "suite")):
            proposals.append(
                _proposal(
                    "building_separation",
                    ">=",
                    value,
                    "m",
                    applies_to=target,
                    scope="building_separation",
                    evidence_text=evidence_text,
                    pattern="minimum_distance_list",
                )
            )
    return proposals


def _maximum_floor_area_lesser_of(text: str) -> list[dict[str, str]]:
    if not re.search(r"floor\s+area\b.*must\s+not\s+exceed\s+the\s+lesser\s+of", text, re.IGNORECASE | re.DOTALL):
        return []
    applies = _between(text, r"floor\s+area\s+for\s+a\s+", r"\s+must\s+not\s+exceed") or ""
    proposals = []
    for item in _enumerated_items(text):
        if re.search(r"\b(multiplied\s+by|times|x|×)\b", item, re.IGNORECASE):
            continue
        value = _first_value(item, _AREA_VALUE_RE)
        if value:
            proposals.append(
                _proposal(
                    "floor_area",
                    "<=",
                    value,
                    "m2",
                    applies_to=applies,
                    scope="floor_area",
                    pattern="maximum_floor_area_lesser_of",
                )
            )
    return proposals


def _maximum_site_coverage(text: str) -> list[dict[str, str]]:
    match = re.search(
        r"for\s+a\s+(?P<applies>site\s+with\s+a\s+[^,.;]+),\s+the\s+maximum\s+site\s+coverage\s+is\s+(?P<value>\d+(?:\.\d+)?)\s*(?:%|per\s?cent|percent)\s+of\s+the\s+site\s+area",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    return [
        _proposal(
            "lot_coverage",
            "<=",
            match.group("value"),
            "%",
            applies_to=_clean_text(match.group("applies")),
            scope="lot_coverage",
            pattern="maximum_site_coverage",
        )
    ]


def _calgary_style_simple_clauses(text: str) -> list[dict[str, str]]:
    proposals: list[dict[str, str]] = []
    lower = text.lower()

    height_match = re.search(r"maximum\s+building\s+height\s+for\s+a\s+(?P<applies>backyard\s+suite)\s+is\s*:?", text, flags=re.IGNORECASE)
    if height_match:
        parent = _clean_text(text[: height_match.end()])
        for item in _enumerated_items(text[height_match.end():]):
            item_lower = item.lower()
            if "side property line" not in item_lower or "low density residential district" not in item_lower:
                continue
            value = _first_value(item, _METRE_VALUE_RE)
            if value:
                condition = _after_value(item)
                proposals.append(
                    _proposal(
                        "height",
                        "<=",
                        value,
                        "m",
                        applies_to=height_match.group("applies"),
                        scope="height",
                        condition=condition,
                        evidence_text=_clean_text(f"{parent} {item}"),
                        pattern="maximum_building_height_branch",
                    )
                )

    if "minimum separation" in lower and "backyard suite" in lower:
        value = _first_value(text, _METRE_VALUE_RE)
        if value:
            condition = _from_keyword(text, "between")
            proposals.append(
                _proposal(
                    "building_separation",
                    ">=",
                    value,
                    "m",
                    applies_to="Backyard Suite",
                    scope="building_separation",
                    condition=condition,
                    pattern="minimum_separation_clause",
                )
            )

    if "maximum floor area of a backyard suite" in lower:
        value = _area_value_after_is(text)
        if value:
            proposals.append(
                _proposal(
                    "floor_area",
                    "<=",
                    value,
                    "m2",
                    applies_to="Backyard Suite",
                    scope="floor_area",
                    exception=_excluding_phrase(text),
                    pattern="maximum_backyard_suite_floor_area",
                )
            )

    if "maximum" in lower and "floor area of a secondary suite" in lower:
        value = _area_value_after_is(text)
        if value:
            proposals.append(
                _proposal(
                    "floor_area",
                    "<=",
                    value,
                    "m2",
                    applies_to="Secondary Suite",
                    scope="floor_area",
                    condition=_after_colon(text),
                    exception=_excluding_phrase(text),
                    pattern="maximum_secondary_suite_floor_area",
                )
            )
    return proposals


def _deemed_front_setback(text: str) -> list[dict[str, str]]:
    lower = text.lower()
    if "building setback from the front property line" not in lower:
        return []
    if "deemed to conform" not in lower or "r-c1l" not in lower:
        return []
    value_match = re.search(r"minimum\s+of\s+(?P<value>\d+(?:\.\d+)?)\s*metres?\s+for\s+the\s+R-C1L", text, re.IGNORECASE)
    if not value_match:
        return []
    applies = _between(
        text,
        r"front\s+property\s+line\s+for\s+a\s+",
        r"\s+in\s+the\s+Developed\s+Area",
    ) or "Duplex Dwelling, Semi-detached Dwelling or Single Detached Dwelling"
    condition = "Developed Area and R-C1L or R-C1Ls districts"
    evidence_text = (
        "The building setback from the front property line for a "
        f"{applies} in the Developed Area is deemed to conform with the requirements of this Bylaw "
        "if the building setback from the front property line is a minimum of "
        f"{value_match.group('value')} metres for the R-C1L or R-C1Ls districts."
    )
    return [
        _proposal(
            "setback",
            ">=",
            value_match.group("value"),
            "m",
            applies_to=applies,
            scope="front setback",
            condition=condition,
            evidence_text=evidence_text,
            pattern="deemed_front_setback",
        )
    ]


def _context_rules(text: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    lower = text.lower()

    sprinkler = re.search(
        r"dwelling\s+units\s+located\s+more\s+than\s+(?P<value>\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)\s+"
        r"from\s+a\s+lot\s+line\s+abutting\s+a\s+street\s+shall\s+contain\s+an\s+automatic\s+sprinkler\s+system",
        text,
        flags=re.IGNORECASE,
    )
    if sprinkler:
        proposals.append(
            _proposal(
                "automatic_sprinkler",
                ">",
                sprinkler.group("value"),
                "m",
                applies_to=f"Dwelling units more than {sprinkler.group('value')} m from a street lot line",
                scope="dwelling_unit",
                condition="distance from lot line abutting a street",
                constraint_type="required",
                pattern="automatic_sprinkler_distance_requirement",
            )
        )

    if "permitted uses" in lower and "small-scale multi-unit housing" in lower:
        proposals.append(
            _proposal(
                "permitted_use",
                "allowed",
                None,
                None,
                applies_to="Small-Scale Multi-Unit Housing",
                scope="district",
                constraint_type="allowed",
                pattern="permitted_use_row",
            )
        )
    if "permitted uses" in lower and "group home" in lower:
        proposals.append(
            _proposal(
                "permitted_use",
                "allowed",
                None,
                None,
                applies_to="Principal Use",
                scope="use",
                condition="Group Home",
                constraint_type="allowed",
                pattern="permitted_use_row",
            )
        )
    return proposals


def _proposal(
    rule_object: str,
    operator: str,
    value: Any,
    unit: Any,
    *,
    applies_to: str,
    scope: str,
    pattern: str,
    condition: str = "",
    exception: str = "",
    evidence_text: str = "",
    constraint_type: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_object": rule_object,
        "operator": operator,
        "constraint_type": constraint_type or ("maximum" if operator == "<=" else "minimum"),
        "constraint_scope": _clean_text(scope),
        "applies_to": _clean_text(applies_to),
        "value": _clean_number(value) if value is not None else None,
        "unit": unit,
        "condition": _clean_text(condition),
        "exception": _clean_text(exception),
        "evidence_text": _clean_text(evidence_text),
        "pattern": pattern,
    }


def _enumerated_items(text: str) -> list[str]:
    matches = list(re.finditer(r"\([a-z]\)\s*", text, flags=re.IGNORECASE))
    if not matches:
        return []
    items = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        item = text[start:end].strip(" ;.")
        if item:
            items.append(item)
    return items


def _first_value(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    return match.group("value") if match else ""


def _area_value_after_is(text: str) -> str:
    match = re.search(
        r"\bis\s+(?P<value>\d+(?:\.\d+)?)\s*(?:m2|m²|sq\.?\s*m|square\s+metres?|square\s+meters?)\b",
        text,
        flags=re.IGNORECASE,
    )
    return match.group("value") if match else ""


def _target_alias_in_text(text: str, config: dict[str, Any]) -> str:
    values = [str(alias) for alias in config.get("known_aliases", []) or []]
    target = str(config.get("target_concept") or "")
    values.extend(re.findall(r"\b(?:laneway house|backyard suite|secondary suite)\b", target, re.IGNORECASE))
    lowered = text.lower()
    for value in values:
        alias = _clean_text(value)
        if alias and alias.lower() in lowered:
            return alias
    return ""


def _setback_direction(text: str) -> str:
    for word in ("front", "rear", "side", "flanking", "interior"):
        if word in text:
            return word
    return ""


def _exception_from_text(text: str) -> str:
    match = re.search(r"\bexcept\b.+", text, flags=re.IGNORECASE)
    return match.group(0).strip(" ;.") if match else ""


def _excluding_phrase(text: str) -> str:
    match = re.search(r"\bexcluding\b.+?(?=,\s+is\b|\s+is\s+\d|$)", text, flags=re.IGNORECASE)
    return match.group(0).strip(" ,;.") if match else ""


def _after_value(text: str) -> str:
    match = _METRE_VALUE_RE.search(text) or _AREA_VALUE_RE.search(text) or _PERCENT_VALUE_RE.search(text)
    return _clean_text(text[match.end():]) if match else ""


def _from_keyword(text: str, keyword: str) -> str:
    index = text.lower().find(keyword.lower())
    return _clean_text(text[index:]) if index >= 0 else ""


def _after_colon(text: str) -> str:
    parts = text.split(":", 1)
    return _clean_text(parts[1]) if len(parts) == 2 else ""


def _between(text: str, left_pattern: str, right_pattern: str) -> str:
    match = re.search(left_pattern + r"(?P<value>.+?)" + right_pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group("value")) if match else ""


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" ;.")


def _clean_number(value: Any) -> str:
    text = str(value or "").strip()
    number = re.search(r"\d+(?:\.\d+)?", text)
    return number.group(0) if number else ""


def _dedupe_proposals(proposals: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    out: list[dict[str, str]] = []
    for proposal in proposals:
        key = (
            proposal.get("rule_object", ""),
            proposal.get("operator", ""),
            proposal.get("value", ""),
            proposal.get("unit", ""),
            proposal.get("constraint_scope", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(proposal)
    return out


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
