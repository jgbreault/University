#!/usr/bin/env python3
"""Batch RAG visual blocks before rule extraction.

This keeps Pipeline 9's target-strict visual-block input format, but changes the
API transport unit from one pseudo-page/pack per call to a compact evidence
batch. It also applies a conservative local no-op filter before any API call.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
from visual_blocks_rule_extractor import (  # noqa: E402
    RULE_SCHEMA,
    TABLE_RULE_PROMPT,
    TEXT_RULE_PROMPT,
    clean,
    compact_text_block,
    enrich_rule,
    is_regulatory_table,
    load_or_extract,
    merge_and_audit_rules,
    non_canonical_unit,
    safe_error,
    target_scope_instruction,
    write_csv,
    write_json,
)


DEFAULT_VISUAL_BLOCKS = ROOT / "outputs" / "vancouver" / "05_rag_visual_blocks"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "vancouver" / "06_rule_extraction_batched"

NO_OP_TEXT_RE = re.compile(
    r"^\s*(?:deleted|reserved|repealed|intentionally left blank|on map \d+\.?)\s*$",
    re.IGNORECASE,
)
HEADING_ONLY_RE = re.compile(r"^\s*(?:part|division|section|schedule)\s+[\w .:-]+\s*$", re.IGNORECASE)
RULE_SIGNAL_RE = re.compile(
    r"\b("
    r"must|shall|may|permitted|discretionary|prohibited|required|not required|"
    r"minimum|maximum|setback|height|area|coverage|parking|separation|"
    r"less than|greater than|not exceed|at least|access|entrance"
    r")\b|(?:\d+(?:\.\d+)?\s*(?:m|metres?|meters?|%|storeys?|m2))",
    re.IGNORECASE,
)
TABLE_HEADER_RE = re.compile(
    r"\b(table|stall width|stall depth|aisle width|parking angle|column heading|row heading)\b",
    re.IGNORECASE,
)
NUMERIC_MATRIX_RE = re.compile(r"\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?")
INCOMPLETE_EVIDENCE_RE = re.compile(
    r"(?:\bwhere:|\bthat:|\bas follows:|\bapproved after|\bwholly located|\bwhere|\bunless|\bfrom a|\bshared with|:\s*)$|details not provided",
    re.IGNORECASE,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json_if_exists(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def compile_terms_regex(terms: list[str]) -> re.Pattern[str] | None:
    cleaned = [term.strip() for term in terms if term and term.strip()]
    if not cleaned:
        return None
    patterns: list[str] = []
    for term in sorted(cleaned, key=len, reverse=True):
        parts = [part for part in re.split(r"\s+", term) if part]
        patterns.append(r"[\s\-]+".join(re.escape(part) for part in parts))
    return re.compile("|".join(patterns), re.IGNORECASE)


def has_target(text: str, target_re: re.Pattern[str] | None) -> bool:
    return bool(target_re and target_re.search(text))


def preflight_skip_reason(block: dict[str, Any], target_re: re.Pattern[str] | None) -> str:
    text = clean(block.get("text"))
    if not text:
        return "empty_text"
    lowered_context = clean(block.get("parent_context")).lower()
    if block.get("block_type") == "amendment_note":
        return "amendment_note"
    if NO_OP_TEXT_RE.match(text):
        return "no_op_deleted_or_map"
    if len(text) < 30 and not has_target(text, target_re) and not RULE_SIGNAL_RE.search(text):
        return "short_context_without_target_or_rule_signal"
    if HEADING_ONLY_RE.match(text) and not has_target(text, target_re):
        return "heading_only_without_target"
    if "target_filter_action=dropped" in lowered_context:
        return "adapter_dropped_context"
    return ""


def is_table_like_text_block(block: dict[str, Any]) -> bool:
    text = clean(block.get("text"))
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    numeric_matrix_lines = sum(1 for line in lines if NUMERIC_MATRIX_RE.search(line))
    numeric_token_count = len(re.findall(r"\d+(?:\.\d+)?", text))
    return bool(TABLE_HEADER_RE.search(text) and numeric_matrix_lines >= 2 and numeric_token_count >= 10)


def block_sort_key(block: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        clean(block.get("rag_lane")),
        int(block.get("original_page_number") or block.get("page_number") or 0),
        int(block.get("reading_order") or 0),
        clean(block.get("block_id")),
    )


def char_count(block: dict[str, Any]) -> int:
    return len(clean(block.get("text"))) + len(clean(block.get("parent_context")))


def make_batches(
    blocks: list[dict[str, Any]],
    *,
    max_blocks_per_batch: int,
    max_chars_per_batch: int,
    mode: str,
) -> list[dict[str, Any]]:
    if mode == "pack_adaptive":
        return make_pack_adaptive_batches(
            blocks,
            max_blocks_per_batch=max_blocks_per_batch,
            max_chars_per_batch=max_chars_per_batch,
        )

    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    current_lane = ""

    for block in sorted(blocks, key=block_sort_key):
        lane = clean(block.get("rag_lane")) or "unknown_lane"
        block_chars = char_count(block)
        should_flush = bool(current) and (
            lane != current_lane
            or len(current) >= max_blocks_per_batch
            or current_chars + block_chars > max_chars_per_batch
        )
        if should_flush:
            batches.append(build_batch(len(batches) + 1, current))
            current = []
            current_chars = 0
        current.append(block)
        current_chars += block_chars
        current_lane = lane

    if current:
        batches.append(build_batch(len(batches) + 1, current))
    return batches


def pack_key(block: dict[str, Any]) -> tuple[str, str]:
    return (clean(block.get("rag_lane")) or "unknown_lane", clean(block.get("rag_pack_id")) or clean(block.get("page_number")))


def make_pack_adaptive_batches(
    blocks: list[dict[str, Any]],
    *,
    max_blocks_per_batch: int,
    max_chars_per_batch: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for block in sorted(blocks, key=block_sort_key):
        grouped.setdefault(pack_key(block), []).append(block)

    pack_groups = sorted(
        grouped.values(),
        key=lambda group: (
            clean(group[0].get("rag_lane")),
            int(group[0].get("original_page_number") or group[0].get("page_number") or 0),
            clean(group[0].get("rag_pack_id")),
        ),
    )
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    current_lane = ""

    for group in pack_groups:
        group_chars = sum(char_count(block) for block in group)
        group_lane = clean(group[0].get("rag_lane")) or "unknown_lane"
        dense_group = (
            len(group) > 4
            or group_chars > max_chars_per_batch * 0.45
            or (len(group) >= 3 and group_chars > 1800)
        )
        if dense_group:
            if current:
                batches.append(build_batch(len(batches) + 1, current))
                current = []
                current_chars = 0
                current_lane = ""
            batches.append(build_batch(len(batches) + 1, group))
            continue

        should_flush = bool(current) and (
            group_lane != current_lane
            or len(current) + len(group) > max_blocks_per_batch
            or current_chars + group_chars > max_chars_per_batch
        )
        if should_flush:
            batches.append(build_batch(len(batches) + 1, current))
            current = []
            current_chars = 0

        current.extend(group)
        current_chars += group_chars
        current_lane = group_lane

    if current:
        batches.append(build_batch(len(batches) + 1, current))
    return batches


def build_batch(index: int, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    lanes = sorted({clean(block.get("rag_lane")) for block in blocks if clean(block.get("rag_lane"))})
    pages = sorted({int(block.get("original_page_number") or block.get("page_number") or 0) for block in blocks})
    return {
        "batch_id": f"text_batch_{index:04d}",
        "lanes": lanes,
        "rag_pack_ids": sorted({clean(block.get("rag_pack_id")) for block in blocks if clean(block.get("rag_pack_id"))}),
        "original_pages": pages,
        "source_count": len(blocks),
        "char_count": sum(char_count(block) for block in blocks),
        "source_ids": [block.get("block_id") for block in blocks],
        "blocks": blocks,
    }


def batch_prompt(batch: dict[str, Any], target_terms: list[str]) -> str:
    inventory = [compact_text_block(block) for block in batch["blocks"]]
    batch_instruction = (
        "Batch transport instruction:\n"
        "- This inventory contains multiple RAG evidence blocks from the same lane or nearby rule context.\n"
        "- Extract rules source-by-source using the visible source_id values.\n"
        "- If a source is context only, unrelated to the target scope, deleted, heading-only, or contains no "
        "testable rule, put it in skipped_sources with a short reason.\n"
        "- Target relevance is strict: extract a rule only when the source text itself directly names a target term, "
        "or when the source scope explicitly applies to a narrow target parent class such as dwelling unit, "
        "residential building, accessory residential building, accessory building, residential use, or suite. "
        "Do not extract broad floodway, all structures, all buildings, all parcels, or all development rules unless "
        "that same source text explicitly ties the rule to a target term or one of those narrow parent classes.\n"
        "- Exception: a target-use heading or schedule row such as 'Laneway House 11.3.8' may be a use-permission "
        "source when the section scope indicates zoning permissions; emit it as permitted_use instead of skipping.\n"
        "- Split comma-separated or conjunction-separated regulated metrics into separate atomic rules. For example, "
        "'floor area, floor space ratio, yards, site coverage, impermeability, number of buildings on site and "
        "dwelling unit density' must become one rule for each listed metric.\n"
        "- Split review criteria lists into separate atomic rules. For example, 'design of all buildings', "
        "'location and provision of off-street parking and loading', and 'impact on neighbourhood amenity' are "
        "three separate required-review rules.\n"
        "- Do not merge evidence from different source_id values into one rule unless the source_id rule itself "
        "contains the full rule.\n\n"
    )
    return target_scope_instruction(target_terms) + batch_instruction + TEXT_RULE_PROMPT + json.dumps(inventory, ensure_ascii=False)


def normalize_key_text(value: Any) -> str:
    text = clean(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"[^a-z0-9.% ]+", " ", text)
    text = re.sub(r"\bbuildings\b", "building", text)
    text = re.sub(r"\bprincipals\b", "principal", text)
    text = re.sub(r"\bsurfaces\b", "surface", text)
    text = re.sub(r"\blots\b", "lot", text)
    text = re.sub(r"\byards\b", "yard", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_operator(value: Any) -> str:
    text = clean(value).lower()
    return {"equal": "=", "equals": "=", "==": "="}.get(text, text)


def normalized_condition(value: Any) -> str:
    text = normalize_key_text(value)
    text = re.sub(r"\bsmall scale multi unit\b", "ssmu", text)
    return text


def normalized_duplicate_key(rule: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        clean(rule.get("source_id")),
        normalize_key_text(rule.get("rule_object")),
        normalize_key_text(rule.get("subject")),
        normalize_operator(rule.get("operator")),
        clean(rule.get("value")),
        clean(rule.get("unit")).lower(),
        normalized_condition(rule.get("condition")),
    )


def fold_normalized_duplicates(
    merged_rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str, str, str, str, str], list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for rule in merged_rules:
        key = normalized_duplicate_key(rule)
        # Only fold concrete duplicates. Empty-value required/prohibited rules are
        # often legitimate sibling clauses and need a human or richer canonicalizer.
        if not key[4] and key[3] in {"required", "prohibited", "permitted", "not required"}:
            passthrough.append(rule)
            continue
        grouped.setdefault(key, []).append(rule)

    deduped: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for key, rules in grouped.items():
        if len(rules) == 1:
            deduped.append(rules[0])
            continue
        canonical = deepcopy(rules[0])
        canonical["normalized_dedup_status"] = "folded_same_source_normalized_value"
        canonical["normalized_dedup_key"] = list(key)
        canonical["normalized_merged_rule_ids"] = [
            clean(rule.get("merged_rule_id") or rule.get("rule_id")) for rule in rules
        ]
        canonical["normalized_merged_rule_count"] = len(rules)
        evidence = list(dict.fromkeys(clean(rule.get("evidence_text")) for rule in rules if clean(rule.get("evidence_text"))))
        if evidence:
            canonical["evidence_text"] = " | ".join(evidence)
        review_reasons = []
        for rule in rules:
            review_reasons.extend(rule.get("review_reasons", []) or [])
        canonical["review_reasons"] = sorted(set(review_reasons))
        canonical["review_required"] = bool(canonical["review_reasons"])
        deduped.append(canonical)
        audit_rows.append({
            "normalized_dedup_key": list(key),
            "kept_rule_id": canonical.get("merged_rule_id", ""),
            "folded_rule_ids": canonical["normalized_merged_rule_ids"],
            "folded_rule_count": len(rules),
            "source_id": key[0],
            "rule_object": canonical.get("rule_object", ""),
            "subject": canonical.get("subject", ""),
            "operator": canonical.get("operator", ""),
            "value": canonical.get("value", ""),
            "unit": canonical.get("unit", ""),
        })

    deduped.extend(passthrough)
    deduped.sort(key=lambda rule: clean(rule.get("merged_rule_id") or rule.get("rule_id")))
    return deduped, audit_rows


def city_from_output_dir(path: Path) -> str:
    for part in reversed(path.parts):
        lowered = part.lower()
        if lowered in {"vancouver", "burnaby", "calgary"}:
            return lowered
    return ""


CALGARY_PARENT_SCOPE_RE = re.compile(
    r"\b("
    r"dwelling units?|residential buildings?|accessory residential buildings?|"
    r"accessory buildings?|residential uses?|secondary suites?|backyard suites?|suites?"
    r")\b",
    re.IGNORECASE,
)


def canonical_unit(unit: Any) -> str:
    text = clean(unit)
    lowered = text.lower()
    if lowered in {"m²", "mâ²", "m2", "sq m", "square metres", "square meters"}:
        return "m2"
    if lowered in {"unit", "units", "stalls", "stall"}:
        return "units"
    if lowered in {"storey", "storeys", "story", "stories"}:
        return "storeys"
    if lowered in {"metre", "metres", "meter", "meters"}:
        return "m"
    if lowered in {"percent", "per cent"}:
        return "%"
    return text


def canonical_rule_object(rule: dict[str, Any]) -> str:
    rule_object = normalize_key_text(rule.get("rule_object"))
    subject = normalize_key_text(rule.get("subject"))
    constraint_type = normalize_key_text(rule.get("constraint_type"))
    evidence = normalize_key_text(rule.get("evidence_text"))
    combined = f"{rule_object} {subject} {constraint_type} {evidence}"

    if "balcony" in combined:
        return "balcony_projection" if "project" in combined or "setback" in combined else "balcony"
    if "aisle width" in combined:
        return "parking_aisle_width"
    if "stall depth" in combined:
        return "parking_stall_depth"
    if "stall width" in combined:
        return "parking_stall_width"
    if "permitted use" in combined or constraint_type in {"permission", "use permission"}:
        if re.search(r"\b(backyard suite|secondary suite|small scale multi unit|rowhouse|principal use|accessory use)\b", combined):
            return "permitted_use"
    if re.search(r"\bparking stall width|motor vehicle parking stall width\b", combined):
        return "parking_stall_width"
    if re.search(r"\bparking stall depth|motor vehicle parking stall depth\b", combined):
        return "parking_stall_depth"
    if re.search(r"\bparking aisle width|motor vehicle parking aisle width\b", combined):
        return "parking_aisle_width"
    if re.search(r"\bparking stalls?|motor vehicle parking stalls?\b", combined):
        return "parking_stalls"
    if "private amenity space" in combined or rule_object == "amenity space":
        return "private_amenity_space"
    if "floor area" in combined:
        return "floor_area"
    if "building setback" in combined or rule_object == "setback":
        return "building_setback"
    if "building height" in combined or rule_object == "height":
        return "building_height"
    return clean(rule.get("rule_object"))


def approval_type(rule: dict[str, Any]) -> str:
    text = normalize_key_text(
        " ".join(clean(rule.get(field)) for field in ("operator", "value", "condition", "evidence_text", "constraint_type"))
    )
    if "not permitted" in text or "prohibited" in text:
        return "prohibited"
    if "discretionary use" in text:
        return "discretionary"
    if "permitted use" in text or "permitted" in text:
        return "permitted"
    if "conditional" in text or "where" in text:
        return "conditional"
    return ""


def canonicalize_rule(rule: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(rule)
    original_unit = clean(updated.get("unit"))
    new_unit = canonical_unit(original_unit)
    if new_unit != original_unit:
        updated["unit_original"] = original_unit
        updated["unit"] = new_unit

    operator = normalize_operator(updated.get("operator"))
    if operator == "equal":
        updated["operator"] = "="

    canonical_object = canonical_rule_object(updated)
    if canonical_object and canonical_object != clean(updated.get("rule_object")):
        updated["rule_object_original"] = updated.get("rule_object", "")
        updated["rule_object"] = canonical_object

    if canonical_object == "permitted_use" or normalize_key_text(updated.get("constraint_type")) in {"permission", "use permission"}:
        updated["approval_type"] = approval_type(updated) or "unknown"

    review_reasons = set(updated.get("review_reasons", []) or [])
    if original_unit and new_unit != original_unit:
        review_reasons.discard("non_canonical_unit_requires_review")
    evidence = clean(updated.get("evidence_text"))
    condition = clean(updated.get("condition"))
    if INCOMPLETE_EVIDENCE_RE.search(evidence) or INCOMPLETE_EVIDENCE_RE.search(condition):
        review_reasons.add("incomplete_or_continuation_evidence")
    if (
        normalize_operator(updated.get("operator")) == ">="
        and re.search(r"\bno dimension less than|not less than|no less than\b", f"{evidence} {condition}", re.IGNORECASE)
    ):
        review_reasons.discard("operator_direction_conflict")
    updated["review_reasons"] = sorted(review_reasons)
    updated["review_required"] = bool(review_reasons)
    return updated


def postprocess_filter_reason(rule: dict[str, Any], *, city: str, target_terms: list[str] | None = None) -> str:
    source_id = clean(rule.get("source_id"))
    rule_object = normalize_key_text(rule.get("rule_object"))
    subject = normalize_key_text(rule.get("subject"))
    operator = normalize_operator(rule.get("operator"))
    value = clean(rule.get("value"))
    condition = normalize_key_text(rule.get("condition"))
    evidence = normalize_key_text(rule.get("evidence_text"))
    target_re = compile_terms_regex(target_terms or [])
    target_scope_text = " ".join(
        clean(rule.get(field))
        for field in (
            "rule_object",
            "subject",
            "parameter",
            "condition",
            "applicability",
            "evidence_text",
        )
    )

    if city == "vancouver":
        if source_id == "vancouver_generic_graph_pack_007__page_0008__local_003":
            return "vancouver_non_target_freehold_rowhouse_subdivision"
        if source_id == "vancouver_generic_graph_pack_006__page_0008__local_004" and rule_object == "permitted use":
            return "vancouver_duplicate_target_heading_permission"
        if source_id == "vancouver_generic_graph_pack_006__page_0008__local_018":
            return "vancouver_parent_intro_without_testable_value"
        if source_id.startswith("vancouver_generic_graph_pack_009__page_0009__local_"):
            if operator in {"<=", ">=", "<", ">"} and not value:
                return "vancouver_numeric_operator_without_value"

    if city == "burnaby":
        if (
            source_id == "page_0001__table_001"
            and rule_object == "permitted use"
            and not re.search(r"\b(small scale multi unit|rowhouse)\b", subject)
        ):
            return "burnaby_non_target_permitted_use_table_row"
        if source_id == "burnaby_generic_graph_pack_006__page_0001__local_001" and rule_object == "permitted use":
            return "burnaby_duplicate_district_heading_permission"
        if source_id == "burnaby_generic_graph_pack_012__page_0005__local_001":
            return "burnaby_duplicate_development_regulations_cross_reference"
        if operator == "required" and not value and re.search(r"\bsee section|subject to section|section \d", f"{condition} {evidence}"):
            if rule_object in {"projections into yard", "setback", "projections", "development regulations compliance"}:
                return "burnaby_cross_reference_only_not_atomic_gis_rule"

    if city == "calgary":
        if source_id == "page_0195__table_001" and "other uses" not in condition:
            return ""
        has_direct_target = has_target(target_scope_text, target_re)
        has_narrow_parent_scope = bool(CALGARY_PARENT_SCOPE_RE.search(target_scope_text))
        if not has_direct_target and not has_narrow_parent_scope:
            return "calgary_broad_rule_without_target_or_narrow_parent_scope"

    return ""


def source_page_number(source_id: Any) -> int | None:
    match = re.search(r"page_(\d{4})", clean(source_id))
    if not match:
        return None
    return int(match.group(1))


def table_image_pages(merged_rules: list[dict[str, Any]]) -> set[int]:
    pages: set[int] = set()
    for rule in merged_rules:
        if clean(rule.get("source_stream")) != "gemini_table_image":
            continue
        page = source_page_number(rule.get("source_id"))
        if page is not None:
            pages.add(page)
    return pages


def table_text_shadow_filter_reason(rule: dict[str, Any], *, city: str, pages_with_table_rules: set[int]) -> str:
    """Prefer table-image extraction over OCR text re-extraction on table-heavy pages."""
    if clean(rule.get("source_stream")) != "gemini_text_batch":
        return ""
    page = source_page_number(rule.get("source_id"))
    if page is None or page not in pages_with_table_rules:
        return ""
    if city == "burnaby":
        return "table_image_preferred_over_same_page_text_ocr"
    return ""


def apply_postprocess_filters(
    merged_rules: list[dict[str, Any]],
    *,
    city: str,
    target_terms: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    canonicalized = [canonicalize_rule(rule) for rule in merged_rules]
    pages_with_table_rules = table_image_pages(canonicalized)
    for rule in canonicalized:
        reason = table_text_shadow_filter_reason(
            rule,
            city=city,
            pages_with_table_rules=pages_with_table_rules,
        ) or postprocess_filter_reason(rule, city=city, target_terms=target_terms)
        if not reason:
            kept.append(rule)
            continue
        audit.append({
            "reason": reason,
            "source_id": rule.get("source_id", ""),
            "merged_rule_id": rule.get("merged_rule_id", ""),
            "rule_object": rule.get("rule_object", ""),
            "subject": rule.get("subject", ""),
            "operator": rule.get("operator", ""),
            "value": rule.get("value", ""),
            "unit": rule.get("unit", ""),
            "condition": rule.get("condition", ""),
            "evidence_text": rule.get("evidence_text", ""),
        })
    return kept, audit


DIRTY_REVIEW_REASONS = {
    "incomplete_or_continuation_evidence",
    "operator_direction_conflict",
    "rule_object_unit_conflict",
    "source_warning",
    "non_canonical_unit_requires_review",
}


def is_clean_rule(rule: dict[str, Any]) -> bool:
    reasons = set(rule.get("review_reasons", []) or [])
    return not bool(reasons & DIRTY_REVIEW_REASONS)


def split_clean_and_review_rules(merged_rules: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clean_rules = [rule for rule in merged_rules if is_clean_rule(rule)]
    review_rules = [rule for rule in merged_rules if not is_clean_rule(rule)]
    return clean_rules, review_rules


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-blocks-dir", type=Path, default=DEFAULT_VISUAL_BLOCKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--text-model", default=None)
    parser.add_argument("--table-model", default=None)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=int, default=20)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--call-delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-blocks-per-batch", type=int, default=8)
    parser.add_argument("--max-chars-per-batch", type=int, default=12000)
    parser.add_argument("--batch-mode", choices=["pack_adaptive", "lane"], default="pack_adaptive")
    parser.add_argument("--target-terms", nargs="*", default=[])
    parser.add_argument("--only-batches", nargs="*", default=[], help="Run only these text_batch ids after batch planning.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def process_batched_extraction(args: argparse.Namespace) -> dict[str, Any]:
    visual_dir = args.visual_blocks_dir.resolve()
    output_dir = args.output_dir.resolve()
    raw_dir = output_dir / "api_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    text_model = getattr(args, "text_model", None) or args.model
    table_model = getattr(args, "table_model", None) or args.model
    target_terms = list(getattr(args, "target_terms", []) or [])
    target_re = compile_terms_regex(target_terms)

    text_blocks = read_jsonl(visual_dir / "text_blocks.jsonl")
    table_regions = read_jsonl(visual_dir / "table_regions.jsonl")
    regulatory_tables = [region for region in table_regions if is_regulatory_table(region)]
    ignored_visual_regions = [region for region in table_regions if not is_regulatory_table(region)]

    kept_blocks: list[dict[str, Any]] = []
    preflight_skipped: list[dict[str, str]] = []
    table_like_text_blocks: list[dict[str, Any]] = []
    for block in text_blocks:
        if is_table_like_text_block(block):
            table_like_text_blocks.append({
                "source_id": clean(block.get("block_id")),
                "original_page_number": block.get("original_page_number") or block.get("page_number"),
                "reason": "table_like_text_block",
                "text_preview": clean(block.get("text"))[:500],
            })
            preflight_skipped.append({"source_id": clean(block.get("block_id")), "reason": "table_like_text_block"})
            continue
        reason = preflight_skip_reason(block, target_re)
        if reason:
            preflight_skipped.append({"source_id": clean(block.get("block_id")), "reason": reason})
        else:
            kept_blocks.append(block)

    batches = make_batches(
        kept_blocks,
        max_blocks_per_batch=args.max_blocks_per_batch,
        max_chars_per_batch=args.max_chars_per_batch,
        mode=args.batch_mode,
    )
    only_batches = set(getattr(args, "only_batches", []) or [])
    if only_batches:
        batches = [batch for batch in batches if batch["batch_id"] in only_batches]
    write_jsonl(output_dir / "batch_manifest.jsonl", [
        {key: value for key, value in batch.items() if key != "blocks"}
        for batch in batches
    ])
    write_json(output_dir / "preflight_skipped_sources.json", preflight_skipped)
    write_json(output_dir / "table_like_text_blocks_pending.json", table_like_text_blocks)

    if args.dry_run:
        summary = build_summary(
            args=args,
            visual_dir=visual_dir,
            text_blocks=text_blocks,
            kept_blocks=kept_blocks,
            preflight_skipped=preflight_skipped,
            batches=batches,
            regulatory_tables=regulatory_tables,
            ignored_visual_regions=ignored_visual_regions,
            table_like_text_blocks=table_like_text_blocks,
            text_rules=[],
            table_rules=[],
            merged_rules=[],
            merge_audit=[],
            merge_review_queue=[],
            text_logs=[],
            table_logs=[],
            text_model=text_model,
            table_model=table_model,
            dry_run=True,
        )
        write_json(output_dir / "summary.json", summary)
        return summary

    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"{args.api_key_env} is not set.")

    text_rules: list[dict[str, Any]] = []
    table_rules: list[dict[str, Any]] = []
    text_logs: list[dict[str, Any]] = []
    table_logs: list[dict[str, Any]] = []
    existing_text_rules = read_json_if_exists(output_dir / "text_rules_raw.json", []) if only_batches else []
    existing_text_logs = read_json_if_exists(output_dir / "text_extraction_logs.json", []) if only_batches else []
    existing_table_rules = read_json_if_exists(output_dir / "table_rules_raw.json", []) if only_batches else []
    existing_table_logs = read_json_if_exists(output_dir / "table_extraction_logs.json", []) if only_batches else []

    for batch in batches:
        batch_id = batch["batch_id"]
        parsed_path = raw_dir / f"{batch_id}_parsed.json"
        api_path = raw_dir / f"{batch_id}_api_response.json"
        prompt_path = raw_dir / f"{batch_id}_prompt.json"
        prompt = batch_prompt(batch, target_terms)
        if not prompt_path.exists() or args.overwrite:
            write_json(prompt_path, {"batch": {k: v for k, v in batch.items() if k != "blocks"}, "prompt": prompt})
        started = time.time()
        try:
            parsed = load_or_extract(
                parsed_path=parsed_path,
                api_path=api_path,
                prompt=prompt,
                args=args,
                api_key=api_key,
                model=text_model,
            )
            rules = [
                enrich_rule(rule, source_stream="gemini_text_batch", batch_id=batch_id)
                for rule in parsed.get("rules", [])
                if isinstance(rule, dict)
            ]
            text_rules.extend(rules)
            text_logs.append({
                "batch_id": batch_id,
                "lanes": batch["lanes"],
                "rag_pack_ids": batch["rag_pack_ids"],
                "original_pages": batch["original_pages"],
                "source_count": batch["source_count"],
                "char_count": batch["char_count"],
                "rule_count": len(rules),
                "skipped_count": len(parsed.get("skipped_sources", [])),
                "warnings": parsed.get("warnings", []),
                "status": "ok",
                "seconds": time.time() - started,
            })
        except Exception as exc:
            text_logs.append({
                "batch_id": batch_id,
                "lanes": batch["lanes"],
                "rag_pack_ids": batch["rag_pack_ids"],
                "original_pages": batch["original_pages"],
                "source_count": batch["source_count"],
                "char_count": batch["char_count"],
                "rule_count": 0,
                "status": "error",
                "error": safe_error(exc),
                "seconds": time.time() - started,
            })
        if args.call_delay_seconds > 0:
            time.sleep(args.call_delay_seconds)

    if only_batches:
        text_rules = [
            rule for rule in existing_text_rules
            if clean(rule.get("batch_id")) not in only_batches
        ] + text_rules
        text_logs = [
            log for log in existing_text_logs
            if clean(log.get("batch_id")) not in only_batches
        ] + text_logs
        table_rules = existing_table_rules
        table_logs = existing_table_logs
    elif regulatory_tables:
        for region in regulatory_tables:
            region_id = clean(region.get("region_id"))
            parsed_path = raw_dir / f"{region_id}_parsed.json"
            api_path = raw_dir / f"{region_id}_api_response.json"
            prompt_path = raw_dir / f"{region_id}_prompt.json"
            image_path = visual_dir / clean(region.get("image_path"))
            metadata = {
                "source_id": region_id,
                "page_number": region.get("page_number"),
                "section_path": region.get("section_path", []),
                "section_heading": region.get("section_heading", ""),
            }
            prompt = TABLE_RULE_PROMPT + json.dumps(metadata, ensure_ascii=False)
            if not prompt_path.exists() or args.overwrite:
                write_json(prompt_path, {"table_region": metadata, "prompt": prompt})
            started = time.time()
            try:
                parsed = load_or_extract(
                    parsed_path=parsed_path,
                    api_path=api_path,
                    prompt=prompt,
                    args=args,
                    api_key=api_key,
                    image_png=image_path.read_bytes(),
                    model=table_model,
                )
                rules = [
                    enrich_rule(rule, source_stream="gemini_table_image", batch_id=region_id)
                    for rule in parsed.get("rules", [])
                    if isinstance(rule, dict)
                ]
                table_rules.extend(rules)
                table_logs.append({
                    "batch_id": region_id,
                    "page_number": region.get("page_number"),
                    "section_heading": region.get("section_heading"),
                    "rule_count": len(rules),
                    "skipped_count": len(parsed.get("skipped_sources", [])),
                    "warnings": parsed.get("warnings", []),
                    "status": "ok",
                    "seconds": time.time() - started,
                })
            except Exception as exc:
                table_logs.append({
                    "batch_id": region_id,
                    "page_number": region.get("page_number"),
                    "section_heading": region.get("section_heading"),
                    "rule_count": 0,
                    "status": "error",
                    "error": safe_error(exc),
                    "seconds": time.time() - started,
                })
            if args.call_delay_seconds > 0:
                time.sleep(args.call_delay_seconds)

    combined_rules = [*table_rules, *text_rules]
    for index, rule in enumerate(combined_rules, start=1):
        rule["rule_id"] = f"pipeline11_rule_{index:04d}"
    merged_rules, merge_audit, merge_review_queue = merge_and_audit_rules(combined_rules)
    merged_rules, normalized_merge_audit = fold_normalized_duplicates(merged_rules)
    merged_rules, postprocess_filter_audit = apply_postprocess_filters(
        merged_rules,
        city=city_from_output_dir(output_dir),
        target_terms=target_terms,
    )
    clean_rules, merge_review_queue = split_clean_and_review_rules(merged_rules)

    write_json(output_dir / "text_rules_raw.json", text_rules)
    write_csv(output_dir / "text_rules_raw.csv", text_rules)
    write_json(output_dir / "table_rules_raw.json", table_rules)
    write_csv(output_dir / "table_rules_raw.csv", table_rules)
    write_json(output_dir / "combined_rules_raw.json", combined_rules)
    write_csv(output_dir / "combined_rules_raw.csv", combined_rules)
    write_json(output_dir / "merged_rules_deduplicated.json", merged_rules)
    write_csv(output_dir / "merged_rules_deduplicated.csv", merged_rules)
    write_json(output_dir / "merged_rules_clean.json", clean_rules)
    write_csv(output_dir / "merged_rules_clean.csv", clean_rules)
    write_json(output_dir / "merge_audit.json", merge_audit)
    write_csv(output_dir / "merge_audit.csv", merge_audit)
    write_json(output_dir / "normalized_merge_audit.json", normalized_merge_audit)
    write_csv(output_dir / "normalized_merge_audit.csv", normalized_merge_audit)
    write_json(output_dir / "postprocess_filter_audit.json", postprocess_filter_audit)
    write_csv(output_dir / "postprocess_filter_audit.csv", postprocess_filter_audit)
    write_json(output_dir / "merge_review_queue.json", merge_review_queue)
    write_csv(output_dir / "merge_review_queue.csv", merge_review_queue)
    write_json(output_dir / "text_extraction_logs.json", text_logs)
    write_json(output_dir / "table_extraction_logs.json", table_logs)
    write_json(output_dir / "ignored_visual_regions.json", ignored_visual_regions)

    summary = build_summary(
        args=args,
        visual_dir=visual_dir,
        text_blocks=text_blocks,
        kept_blocks=kept_blocks,
        preflight_skipped=preflight_skipped,
        batches=batches,
        regulatory_tables=regulatory_tables,
        ignored_visual_regions=ignored_visual_regions,
        table_like_text_blocks=table_like_text_blocks,
        text_rules=text_rules,
        table_rules=table_rules,
        merged_rules=merged_rules,
        clean_rules=clean_rules,
        merge_audit=merge_audit,
        normalized_merge_audit=normalized_merge_audit,
        postprocess_filter_audit=postprocess_filter_audit,
        merge_review_queue=merge_review_queue,
        text_logs=text_logs,
        table_logs=table_logs,
        text_model=text_model,
        table_model=table_model,
        dry_run=False,
    )
    write_json(output_dir / "summary.json", summary)
    return summary


def build_summary(
    *,
    args: argparse.Namespace,
    visual_dir: Path,
    text_blocks: list[dict[str, Any]],
    kept_blocks: list[dict[str, Any]],
    preflight_skipped: list[dict[str, str]],
    batches: list[dict[str, Any]],
    regulatory_tables: list[dict[str, Any]],
    ignored_visual_regions: list[dict[str, Any]],
    table_like_text_blocks: list[dict[str, Any]] | None = None,
    text_rules: list[dict[str, Any]],
    table_rules: list[dict[str, Any]],
    merged_rules: list[dict[str, Any]],
    clean_rules: list[dict[str, Any]] | None = None,
    merge_audit: list[dict[str, Any]],
    normalized_merge_audit: list[dict[str, Any]] | None = None,
    postprocess_filter_audit: list[dict[str, Any]] | None = None,
    merge_review_queue: list[dict[str, Any]],
    text_logs: list[dict[str, Any]],
    table_logs: list[dict[str, Any]],
    text_model: str,
    table_model: str,
    dry_run: bool,
) -> dict[str, Any]:
    non_canonical_units = sorted({
        offending
        for rule in merged_rules
        if (offending := non_canonical_unit(rule.get("unit")))
    })
    extraction_quality_flags = Counter(
        reason for rule in merged_rules for reason in rule.get("review_reasons", [])
    )
    return {
        "pipeline": "experiment_pipeline_11_bge_m3_batched_rag_rule_extraction",
        "dry_run": dry_run,
        "model": args.model,
        "text_model": text_model,
        "table_model": table_model,
        "visual_blocks_dir": str(visual_dir),
        "text_block_count": len(text_blocks),
        "preflight_kept_text_block_count": len(kept_blocks),
        "preflight_skipped_text_block_count": len(preflight_skipped),
        "preflight_skip_reason_counts": dict(Counter(item["reason"] for item in preflight_skipped)),
        "text_batch_count": len(batches),
        "only_batches": list(getattr(args, "only_batches", []) or []),
        "max_blocks_per_batch": args.max_blocks_per_batch,
        "max_chars_per_batch": args.max_chars_per_batch,
        "batch_mode": args.batch_mode,
        "regulatory_table_count": len(regulatory_tables),
        "ignored_visual_region_count": len(ignored_visual_regions),
        "table_like_text_block_count": len(table_like_text_blocks or []),
        "text_rule_count": len(text_rules),
        "table_rule_count": len(table_rules),
        "combined_rule_count": len(text_rules) + len(table_rules),
        "deduplicated_rule_count": len(merged_rules),
        "clean_rule_count": len(clean_rules or []),
        "auto_folded_group_count": len(merge_audit),
        "auto_folded_rule_count": sum(row["merged_rule_count"] - 1 for row in merge_audit),
        "normalized_folded_group_count": len(normalized_merge_audit or []),
        "normalized_folded_rule_count": sum(row["folded_rule_count"] - 1 for row in (normalized_merge_audit or [])),
        "postprocess_filtered_rule_count": len(postprocess_filter_audit or []),
        "postprocess_filter_reason_counts": dict(Counter(row["reason"] for row in (postprocess_filter_audit or []))),
        "merge_review_rule_count": len(merge_review_queue),
        "non_canonical_unit_count": len(non_canonical_units),
        "non_canonical_units": non_canonical_units,
        "extraction_quality_flags": dict(extraction_quality_flags),
        "text_successful_batches": sum(log.get("status") == "ok" for log in text_logs),
        "text_error_batches": sum(log.get("status") == "error" for log in text_logs),
        "table_successful_batches": sum(log.get("status") == "ok" for log in table_logs),
        "text_logs": text_logs,
        "table_logs": table_logs,
    }


def main() -> None:
    print(json.dumps(process_batched_extraction(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
