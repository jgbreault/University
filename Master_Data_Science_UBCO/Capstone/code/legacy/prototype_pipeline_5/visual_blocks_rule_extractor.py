#!/usr/bin/env python3
"""Extract traceable zoning rules from visual text blocks and table-image crops."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tqdm.auto import tqdm


DEFAULT_MODEL = "gemini-3.1-pro-preview"

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "rule_key": {"type": "string"},
                    "rule_object": {"type": "string"},
                    "constraint_type": {"type": "string"},
                    "subject": {"type": "string"},
                    "operator": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "condition": {"type": "string"},
                    "exception": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "source_id",
                    "rule_key",
                    "rule_object",
                    "constraint_type",
                    "subject",
                    "operator",
                    "value",
                    "unit",
                    "condition",
                    "exception",
                    "evidence_text",
                    "warnings",
                ],
            },
        },
        "skipped_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["source_id", "reason"],
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rules", "skipped_sources", "warnings"],
}

TEXT_RULE_PROMPT = """Extract atomic zoning rules from hierarchical legal-text blocks.

This is a general zoning-rule extraction task. Use only the supplied source inventory.

Instructions:
1. Return one atomic rule per independently testable constraint, permission, prohibition,
   exception, measurement rule, or cross-reference.
2. Every rule must cite exactly one visible source_id from the inventory.
3. Preserve inherited scope from section_path and parent_context in condition when needed.
4. If one source contains multiple values or sub-rules, emit multiple atomic rules.
5. Preserve discretionary language, exceptions, approvals, and external references.
6. Do not extract headings, amendment notes, or pure context as standalone rules.
7. Use empty strings for absent scalar fields. Do not invent missing values.
8. For the unit field, use ASCII canonical tokens only: m (metres), m2 (square
   metres), % (percent), storeys, units. Write square metres as m2, never m²,
   "sq m", or "square metres". Leave unit empty for non-numeric rules.
9. value holds only a measured quantity or enumerated value. Never put a bylaw
   section number or cross-reference (e.g. "101.5.1", "6.8", "6.8A") in value;
   if a source only points to other regulations, record that reference in
   condition and leave value empty.
10. For numeric or measurement rules, value must be digits only (e.g. "3", "7.5").
    Put any measurement-method or definitional wording in condition, not in value.
11. Set operator strictly from the GOVERNING WORD, never flipping direction, and
    NEVER default to "=" when a minimum/maximum word is present:
      minimum / at least / not less than / no less than            -> ">="
      maximum / up to / not more than / no more than / not exceed   -> "<="
      exactly / must be / shall be (a fixed quantity, no min/max)   -> "="
      permitted / allowed / may be                                  -> "permitted"
      prohibited / not permitted / shall not                        -> "prohibited"
    Use "=" ONLY for a fixed exact quantity. If the source says minimum, at least,
    maximum, up to, or not more than, the operator MUST be ">=" or "<=" — using "="
    there is an error. Always output one of: ">=", "<=", "=", "permitted",
    "prohibited" (or "required"/"not required" for a mandated/exempted feature).
12. For a use permission or prohibition, set rule_object to "permitted_use", put
    the use name in subject, set operator to "permitted" or "prohibited", and
    leave value and unit empty. For a mandated feature/action with no numeric value
    ("must comply with", "shall be provided", "is required"), use operator
    "required" (or "not required" when explicitly exempted). NEVER leave operator
    empty: every rule must carry exactly one of ">=", "<=", "=", "permitted",
    "prohibited", "required", "not required". A bare cross-reference that states no
    constraint should be skipped, not emitted with an empty operator.
13. Distinguish a building or structure height limit from a clearance, headroom,
    or projection limit (e.g. "clear to a height of 2.5 m"). The latter is not a
    building-height rule: set rule_object to the feature being measured (e.g.
    "fire_access_corridor") and reserve "height" for building/structure height.
14. evidence_text must be a faithful excerpt from the cited source text.

Worked operator examples (map the governing word, not the value):
  "minimum lot width 5 m"                         -> operator ">=",  value "5",   unit "m"
  "All dwelling units shall have a minimum 1.0 m" -> operator ">=",  value "1.0", unit "m"
  "minimum panhandle width 4.5 m"                 -> operator ">=",  value "4.5", unit "m"
  "maximum lot coverage 60%"                      -> operator "<=",  value "60",  unit "%"
  "impervious surface area up to 70%"             -> operator "<=",  value "70",  unit "%"
  "building height shall not exceed 11 m"         -> operator "<=",  value "11",  unit "m"
  "Small-Scale Multi-Unit Housing is permitted"   -> operator "permitted",  value "", unit ""
  "panhandle lots are not permitted"              -> operator "prohibited", value "", unit ""
  "child care facilities must comply with 101.5"  -> operator "required",   value "", unit ""
  "interior side yard setbacks are not required"  -> operator "not required", value "", unit ""

Source inventory JSON:
"""

TABLE_RULE_PROMPT = """Extract atomic zoning rules from this regulatory-table image.

This is a general zoning-rule extraction task. Use only content visibly present in the image.
The image crop includes its section heading or nearest visible table title.

Instructions:
1. Return one atomic rule per meaningful value-bearing table constraint.
2. Every rule must cite the supplied source_id.
3. Preserve row hierarchy, column hierarchy, units, conditions, exceptions, ranges, and
   footnote markers when visible.
4. Split compound cells into atomic rules when they contain multiple values or alternatives.
5. Do not infer omitted values, normalize source wording, or use outside knowledge.
6. Use empty strings for absent scalar fields.
7. For the unit field only, use ASCII canonical tokens: m (metres), m2 (square
   metres), % (percent), storeys, units. Write square metres as m2, never m².
   This applies to the unit field alone; evidence_text must stay literal.
8. value holds only a measured quantity or enumerated value, never a bylaw
   section number or cross-reference (e.g. "101.5.1", "6.8"). For a cell that
   only cites other regulations (e.g. "Use-Specific Regulations: 6.8"), leave
   value empty and record the reference in condition.
9. For a use-permission row (Permitted / Not Permitted), set rule_object to
   "permitted_use", put the use name in subject, set operator to "permitted" or
   "prohibited", and leave value and unit empty.
10. Set operator strictly from the governing word, never flipping direction:
    minimum / at least -> ">="; maximum / up to / not more than -> "<=".
11. evidence_text must faithfully transcribe the visible row/column context supporting the rule.

Table metadata JSON:
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("visual_blocks_dir", type=Path, help="Output directory from gemini_visual_block_extractor.py.")
    parser.add_argument("output_dir", type=Path, help="Directory for rule-extraction artifacts.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name.")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY", help="Environment variable holding the API key.")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP request timeout in seconds.")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries for transient API errors.")
    parser.add_argument("--retry-base-seconds", type=int, default=20, help="Linear retry backoff base.")
    parser.add_argument("--target-terms", nargs="*", default=[], help="Optional target uses/building types to restrict extraction.")
    parser.add_argument("--overwrite", action="store_true", help="Call Gemini again even when cached parsed JSON exists.")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_error(exc: Exception) -> str:
    return re.sub(r"([?&]key=)[^&'\")\s]+", r"\1<redacted>", repr(exc))


def target_scope_instruction(target_terms: list[str] | None) -> str:
    terms = [clean(term) for term in (target_terms or []) if clean(term)]
    if not terms:
        return ""
    return (
        "Target extraction scope:\n"
        f"- Target building/use terms: {', '.join(terms)}.\n"
        "- Extract only rules that directly mention a target term, or rules that clearly apply to the target through "
        "phrases such as all uses, all buildings, all development, all districts, general rules, floodway rules, "
        "district dimensional standards, parking standards, or development permit rules.\n"
        "- Also extract upper-level semantic rules when the source scope clearly includes the target, such as "
        "all dwelling units, all residential buildings, all accessory residential buildings, all residential uses, "
        "all parcels, all developments, all developments containing the target, all buildings containing the target, "
        "or all uses in the relevant district. Preserve that inherited applicability in condition.\n"
        "- For mixed use lists, skip unrelated list items even when they share the same source page. Do not extract "
        "rules for other named uses unless the same source text explicitly makes them apply to the target terms.\n\n"
    )


def compact_text_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": block.get("block_id"),
        "page_number": block.get("page_number"),
        "reading_order": block.get("reading_order"),
        "block_type": block.get("block_type"),
        "section_path": block.get("section_path", []),
        "parent_context": block.get("parent_context", ""),
        "text": block.get("text", ""),
        "continues_from_previous_page": block.get("continues_from_previous_page", False),
        "continues_on_next_page": block.get("continues_on_next_page", False),
    }


def is_regulatory_table(region: dict[str, Any]) -> bool:
    heading = clean(region.get("section_heading")).lower()
    section_path = " ".join(str(part) for part in region.get("section_path", []))
    if heading.startswith("diagram:") or "diagram:" in section_path.lower():
        return False
    return bool(re.search(r"\d", section_path))


def call_gemini(
    *,
    prompt: str,
    api_key: str,
    model: str,
    timeout: int,
    max_retries: int,
    retry_base_seconds: int,
    image_png: bytes | None = None,
    response_schema: dict[str, Any] = RULE_SCHEMA,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if image_png is not None:
        parts.append({
            "inlineData": {
                "mimeType": "image/png",
                "data": base64.b64encode(image_png).decode("ascii"),
            }
        })
    parts.append({"text": prompt})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 32000,
            "responseMimeType": "application/json",
            "responseJsonSchema": response_schema,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        if attempt:
            time.sleep(retry_base_seconds * attempt)
        try:
            response = requests.post(url, params={"key": api_key}, json=payload, timeout=timeout)
            response.raise_for_status()
            raw_response = response.json()
            response_parts = raw_response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in response_parts)
            return json.loads(text), raw_response
        except requests.HTTPError as exc:
            last_error = exc
            status = getattr(exc.response, "status_code", None)
            if status not in {429, 500, 502, 503, 504}:
                raise
        except (requests.Timeout, requests.ConnectionError, json.JSONDecodeError) as exc:
            last_error = exc
    if last_error is None:
        raise RuntimeError("Gemini request failed without an error.")
    raise last_error


def load_or_extract(
    *,
    parsed_path: Path,
    api_path: Path,
    prompt: str,
    args: argparse.Namespace,
    api_key: str,
    image_png: bytes | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    if parsed_path.exists() and not args.overwrite:
        return json.loads(parsed_path.read_text(encoding="utf-8"))
    parsed, raw_response = call_gemini(
        prompt=prompt,
        api_key=api_key,
        model=model or args.model,
        timeout=args.timeout,
        max_retries=args.max_retries,
        retry_base_seconds=args.retry_base_seconds,
        image_png=image_png,
    )
    write_json(parsed_path, parsed)
    write_json(api_path, raw_response)
    return parsed


def normalize_not_required_distance(rule: dict[str, Any]) -> dict[str, Any]:
    """Encode a "not required" distance/setback as the numeric minimum 0 m.

    A bylaw clause like "interior side yard setbacks are not required ..." waives a
    distance requirement, i.e. the minimum becomes 0 m (build to the line). Models
    encode this inconsistently — some emit operator "not required" with no value,
    others "permitted 0 m". Normalizing distance-family "not required" rules to
    ">= 0 m" aligns them with table-derived setback rules and lets a numeric
    verifier consume them. Only fires for a metre-family rule_object with no
    explicit value; non-distance exemptions ("parking not required") stay literal.
    """
    if clean(rule.get("operator")).lower() != "not required":
        return rule
    if clean(rule.get("value")):
        return rule
    # Only a genuine distance waiver (setback / yard / separation) means "0 m".
    # A feature exemption that happens to map to a metre family ("sprinkler not
    # required") must stay literal, so check the rule_object words directly rather
    # than the broader metre-family map.
    obj_words = re.sub(r"[^a-z]+", " ", str(rule.get("rule_object") or "").lower())
    if not any(word in obj_words for word in ("setback", "yard", "separation")):
        return rule
    normalized = dict(rule)
    normalized["operator"] = ">="
    normalized["value"] = "0"
    normalized["unit"] = "m"
    return normalized


def enrich_rule(rule: dict[str, Any], *, source_stream: str, batch_id: str) -> dict[str, Any]:
    enriched = dict(rule)
    enriched["source_stream"] = source_stream
    enriched["batch_id"] = batch_id
    return normalize_not_required_distance(enriched)


# Canonical ASCII unit tokens shared with the downstream GIS verifier contract.
# Square metres must be "m2" (ASCII), never "m²" (U+00B2): the verifier keys its
# unit-alias table on "m2" and silently rejects the superscript form, which had
# been causing every lot_area rule to fail verification.
CANONICAL_UNITS = {"", "m", "m2", "%", "storeys", "units"}

UNIT_ALIASES = {
    "m": "m", "metre": "m", "meter": "m", "metres": "m", "meters": "m",
    "m2": "m2", "m²": "m2", "m^2": "m2", "m 2": "m2",
    "sq. m": "m2", "sq m": "m2", "sqm": "m2",
    "square metre": "m2", "square meter": "m2",
    "square metres": "m2", "square meters": "m2",
    "%": "%", "percent": "%", "percentage": "%",
    "storey": "storeys", "storeys": "storeys", "stories": "storeys", "story": "storeys",
    "unit": "units", "units": "units",
}


def normalized_unit(value: Any) -> str:
    """Map any unit spelling to a canonical ASCII token (see CANONICAL_UNITS).

    Square metres collapse to "m2", not "m²": the downstream verifier keys its
    unit-alias table on the ASCII form and silently rejects the superscript.
    """
    unit = clean(value)
    return UNIT_ALIASES.get(unit.lower(), unit)


def non_canonical_unit(value: Any) -> str:
    """Return the offending unit if it is not canonical after normalization, else "".

    Post-extraction coding guard: any unit that survives normalization without
    landing in CANONICAL_UNITS is surfaced for review, so a new/unmapped spelling
    can never reach the registry unnoticed the way "m²" did.
    """
    normalized = normalized_unit(value)
    return "" if normalized in CANONICAL_UNITS else normalized


# A bylaw section number / cross-reference such as "101.5.1", "6.8", "6.8A", or a
# comma list of them ("101.5.5, 6.6"). These point to other regulations and must
# never sit in the value field, where they masquerade as a numeric quantity.
CLAUSE_REFERENCE_RE = re.compile(
    r"^\s*\d+(?:\.\d+)+[A-Za-z]?(?:\s*,\s*\d+(?:\.\d+)*[A-Za-z]?)*\s*$"
)

# General (city-agnostic) measurement families keyed by a distinctive word in the
# rule_object, mapped to the canonical units that can legally express them. This
# mirrors the downstream GIS verifier so a misclassified rule_object (e.g. an area
# in m2 tagged as dwelling_units) is caught at extraction time.
RULE_OBJECT_FAMILY_UNITS = {
    # Building/structure height is legitimately expressed in metres OR storeys
    # (e.g. "maximum height ... 3 storeys"). Allowing both prevents a false
    # rule_object_unit_conflict on storeys-measured height limits.
    "height": {"m", "storeys"},
    "setback": {"m"},
    "separation": {"m"},
    "sprinkler": {"m"},
    "corridor": {"m"},
    "area": {"m2"},
    "coverage": {"%"},
    "impervious": {"%"},
    "storey": {"storeys"},
    "dwelling": {"units"},
}

# Direction cues used to catch an operator that contradicts the governing word.
MIN_CUES = ("minimum", "at least", "not less", "no less")
MAX_CUES = ("maximum", "up to", "not more", "no more", "not exceed", "less than")

# Cues that mark a rule as a ratio / exclusion / proportion. For these a "%" value
# is legitimate even on a metre/area family (e.g. "exclude 10% of floor area"), so
# the unit-conflict guard must not flag it.
RATIO_EXCLUSION_CUES = ("exclusion", "exclude", "ratio", "proportion", "percent")


def looks_like_clause_reference(rule: dict[str, Any]) -> bool:
    """True when the value is a bylaw section number / cross-reference, not a quantity.

    A single decimal like "7.5" is ambiguous with a measurement, so it is treated
    as a reference only when it is unitless and the surrounding text points to
    another regulation. Multi-level ("101.5.1"), letter-suffixed ("6.8A"), or
    comma-listed references are unambiguous.
    """
    text = clean(rule.get("value"))
    if not text or not CLAUSE_REFERENCE_RE.match(text):
        return False
    if re.search(r"\d+\.\d+\.\d+", text) or re.search(r"\d[A-Za-z]", text) or "," in text:
        return True
    if clean(rule.get("unit")):
        return False
    context = " ".join(
        clean(rule.get(key)).lower()
        for key in ("rule_key", "condition", "evidence_text")
    )
    reference_cues = ("regulation", "subsection", "section", "pursuant", "accordance", "see ")
    return any(cue in context for cue in reference_cues)


def expected_units_for(rule_object: Any) -> set[str]:
    """Map a free-text rule_object to its canonical units via keyword family, or {}."""
    text = re.sub(r"[^a-z]+", " ", str(rule_object or "").lower())
    for keyword, units in RULE_OBJECT_FAMILY_UNITS.items():
        if keyword in text:
            return units
    return set()


def rule_object_unit_conflict(rule: dict[str, Any]) -> bool:
    """True when a canonical unit is incompatible with the rule_object's family.

    Only fires when both sides are known: a recognised measurement family and a
    canonical unit. Empty/non-canonical units are handled by non_canonical_unit.
    """
    expected = expected_units_for(rule.get("rule_object"))
    if not expected:
        return False
    unit = normalized_unit(rule.get("unit"))
    if unit not in CANONICAL_UNITS or unit == "":
        return False
    # A "%" expresses a ratio/exclusion/proportion, which is valid even on an
    # area or metre family (e.g. "exclude 10% of floor area"). Only treat it as a
    # conflict when the rule is not a ratio/exclusion-style rule.
    if unit == "%" and _is_ratio_or_exclusion(rule):
        return False
    return unit not in expected


def _is_ratio_or_exclusion(rule: dict[str, Any]) -> bool:
    """True when the rule expresses a ratio/exclusion/proportion (so % is valid)."""
    text = " ".join(
        clean(rule.get(key)).lower()
        for key in ("rule_object", "subject", "constraint_type", "condition")
    )
    return any(cue in text for cue in RATIO_EXCLUSION_CUES)


def non_numeric_measurement_value(rule: dict[str, Any]) -> bool:
    """True when a measurement-unit rule carries a value that has no digit."""
    unit = normalized_unit(rule.get("unit"))
    value = clean(rule.get("value"))
    return unit in (CANONICAL_UNITS - {""}) and bool(value) and not re.search(r"\d", value)


def operator_direction_conflict(rule: dict[str, Any]) -> bool:
    """True when the operator direction contradicts—or fails to capture—the
    governing min/max wording.

    Two failure modes, both routed to review:
    1. Flipped direction: "<=" used where the text says minimum (or vice versa).
    2. Collapsed direction: a non-directional operator ("=", "==", or empty) on a
       numeric rule whose evidence has a clear single-direction min/max word. This
       is the dominant degradation seen when a cheaper model flattens ">="/"<=" to
       "=", which the flip check above cannot catch.
    """
    operator = clean(rule.get("operator")).lower()
    text = " ".join(
        clean(rule.get(key)).lower()
        for key in ("constraint_type", "rule_key", "condition", "evidence_text")
    )
    has_min = any(cue in text for cue in MIN_CUES)
    has_max = any(cue in text for cue in MAX_CUES)
    is_min = operator in {">=", "min", "minimum", "at_least"}
    is_max = operator in {"<=", "max", "maximum", "not_exceed"}
    if is_max and has_min and not has_max:
        return True
    if is_min and has_max and not has_min:
        return True
    # Collapsed direction: non-directional operator but a clear single-direction
    # governing word AND a numeric value. (Both min and max words present is
    # ambiguous and left for the reviewer's normal range handling.)
    non_directional = operator in {"=", "==", ""}
    has_numeric_value = bool(re.search(r"\d", clean(rule.get("value"))))
    if non_directional and has_numeric_value and (has_min ^ has_max):
        return True
    return False


def shared_condition(conditions: list[str]) -> str:
    if not conditions:
        return ""
    segment_lists = [
        [segment.strip() for segment in condition.split(";") if segment.strip()]
        for condition in conditions
    ]
    if not segment_lists:
        return ""
    shared = [
        segment
        for segment in segment_lists[0]
        if all(segment in segments for segments in segment_lists[1:])
    ]
    return "; ".join(shared)


def review_reasons(rule: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    value = clean(rule.get("value"))
    exception = clean(rule.get("exception"))
    warnings = rule.get("warnings", [])
    if re.search(r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\b", value, flags=re.IGNORECASE):
        reasons.append("range_value_requires_endpoint_split")
    if exception:
        reasons.append("exception_requires_atomic_review")
    if looks_like_clause_reference(rule):
        reasons.append("value_is_cross_reference")
    if non_numeric_measurement_value(rule):
        reasons.append("non_numeric_measurement_value")
    if rule_object_unit_conflict(rule):
        reasons.append("rule_object_unit_conflict")
    if operator_direction_conflict(rule):
        reasons.append("operator_direction_conflict")
    if not clean(rule.get("operator")) and clean(rule.get("subject")):
        # A real rule (has a subject) with no operator is under-specified — a
        # cheaper model sometimes drops the operator on use/requirement rules.
        reasons.append("missing_operator")
    if non_canonical_unit(rule.get("unit")):
        reasons.append("non_canonical_unit_requires_review")
    if warnings:
        reasons.append("source_warning")
    return reasons


def apply_scope_summary(rule: dict[str, Any], source_scopes: list[dict[str, str]]) -> None:
    """Expose merged visual-column scope without inheriting the first column label."""
    applies_to_objects = list(dict.fromkeys(
        scope["rule_object"]
        for scope in source_scopes
        if scope["rule_object"]
    ))
    rule["applies_to_objects"] = applies_to_objects
    rule["scope_count"] = len(applies_to_objects)
    if len(applies_to_objects) > 1:
        rule["rule_object"] = "Multiple explicit scopes; see applies_to_objects"
        rule["scope_mode"] = "multiple_explicit_scopes"
    else:
        rule["scope_mode"] = "single_scope"


def merge_and_audit_rules(
    combined_rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Conservatively fold duplicate rules while preserving every source scope."""
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for rule in combined_rules:
        normalized = dict(rule)
        normalized["unit"] = normalized_unit(rule.get("unit"))
        signature = (
            clean(normalized.get("source_stream")),
            clean(normalized.get("batch_id")),
            clean(normalized.get("rule_key")),
            clean(normalized.get("subject")),
            clean(normalized.get("operator")),
            clean(normalized.get("value")),
            clean(normalized.get("unit")),
            clean(normalized.get("exception")),
            clean(normalized.get("evidence_text")),
        )
        grouped.setdefault(signature, []).append(normalized)

    merged_rules: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for group_number, rules in enumerate(grouped.values(), start=1):
        canonical = dict(rules[0])
        source_scopes = [
            {
                "rule_id": rule.get("rule_id", ""),
                "rule_object": clean(rule.get("rule_object")),
                "condition": clean(rule.get("condition")),
            }
            for rule in rules
        ]
        canonical["condition"] = shared_condition([scope["condition"] for scope in source_scopes])
        canonical["applies_to"] = source_scopes
        apply_scope_summary(canonical, source_scopes)
        canonical["merged_rule_ids"] = [clean(rule.get("rule_id")) for rule in rules]
        canonical["merged_rule_count"] = len(rules)
        canonical["dedup_status"] = "auto_folded_same_table_evidence" if len(rules) > 1 else "kept"
        canonical["review_reasons"] = review_reasons(canonical)
        canonical["review_required"] = bool(canonical["review_reasons"])
        canonical["merged_rule_id"] = f"pipeline5_merged_rule_{group_number:04d}"
        merged_rules.append(canonical)

        if len(rules) > 1:
            audit_rows.append({
                "merged_rule_id": canonical["merged_rule_id"],
                "dedup_status": canonical["dedup_status"],
                "source_stream": canonical.get("source_stream", ""),
                "batch_id": canonical.get("batch_id", ""),
                "rule_key": canonical.get("rule_key", ""),
                "subject": canonical.get("subject", ""),
                "operator": canonical.get("operator", ""),
                "value": canonical.get("value", ""),
                "unit": canonical.get("unit", ""),
                "exception": canonical.get("exception", ""),
                "evidence_text": canonical.get("evidence_text", ""),
                "merged_rule_count": canonical["merged_rule_count"],
                "merged_rule_ids": canonical["merged_rule_ids"],
                "applies_to": canonical["applies_to"],
            })

    review_queue = [rule for rule in merged_rules if rule["review_required"]]
    return merged_rules, audit_rows, review_queue


def _map_batches(items, work, *, max_workers, desc, unit):
    """Run ``work(item)`` over ``items``, returning results in input order.

    ``max_workers <= 1`` runs the original sequential loop, so callers that do
    not opt in are byte-for-byte unchanged. Otherwise the independent per-item
    API calls (I/O-bound HTTP) run on a bounded thread pool and results are
    reassembled in the original order, keeping output determinism. ``work`` is
    expected to swallow its own per-item errors and return a result either way,
    matching the existing per-batch try/except behaviour.
    """
    items = list(items)
    if not items:
        return []
    if max_workers is None or max_workers <= 1 or len(items) == 1:
        return [work(item) for item in tqdm(items, desc=desc, unit=unit)]
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[Any] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(work, item): index for index, item in enumerate(items)}
        for future in tqdm(as_completed(futures), total=len(items), desc=desc, unit=unit):
            results[futures[future]] = future.result()
    return results


def process_extraction(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"{args.api_key_env} is not set.")

    visual_dir = args.visual_blocks_dir.resolve()
    output_dir = args.output_dir.resolve()
    raw_dir = output_dir / "api_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Per-stream model overrides (default to args.model, so existing callers are
    # unchanged). Lets a caller run cheap text extraction while keeping the
    # quality-critical table-image reading on a stronger model.
    text_model = getattr(args, "text_model", None) or args.model
    table_model = getattr(args, "table_model", None) or args.model

    text_blocks = read_jsonl(visual_dir / "text_blocks.jsonl")
    table_regions = read_jsonl(visual_dir / "table_regions.jsonl")
    regulatory_tables = [region for region in table_regions if is_regulatory_table(region)]
    ignored_visual_regions = [region for region in table_regions if not is_regulatory_table(region)]

    text_rules: list[dict[str, Any]] = []
    table_rules: list[dict[str, Any]] = []
    text_logs: list[dict[str, Any]] = []
    table_logs: list[dict[str, Any]] = []

    pages: dict[int, list[dict[str, Any]]] = {}
    for block in text_blocks:
        if block.get("block_type") == "amendment_note":
            continue
        pages.setdefault(int(block.get("page_number", 0)), []).append(block)

    # Independent per-page / per-table API calls. They run sequentially by
    # default (max_workers=1) and concurrently when a caller opts in; results
    # are reassembled in the original order so output stays deterministic.
    max_workers = getattr(args, "max_workers", 1)
    target_terms = list(getattr(args, "target_terms", []) or [])

    def _extract_text_page(item: tuple[int, list[dict[str, Any]]]) -> dict[str, Any]:
        page_number, page_blocks = item
        batch_id = f"text_page_{page_number:04d}"
        parsed_path = raw_dir / f"{batch_id}_parsed.json"
        api_path = raw_dir / f"{batch_id}_api_response.json"
        inventory = [compact_text_block(block) for block in page_blocks]
        prompt = target_scope_instruction(target_terms) + TEXT_RULE_PROMPT + json.dumps(inventory, ensure_ascii=False)
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
                enrich_rule(rule, source_stream="gemini_text_block", batch_id=batch_id)
                for rule in parsed.get("rules", [])
                if isinstance(rule, dict)
            ]
            return {"rules": rules, "log": {
                "batch_id": batch_id,
                "page_number": page_number,
                "source_count": len(inventory),
                "rule_count": len(rules),
                "skipped_count": len(parsed.get("skipped_sources", [])),
                "warnings": parsed.get("warnings", []),
                "status": "ok",
                "seconds": time.time() - started,
            }}
        except Exception as exc:
            return {"rules": [], "log": {
                "batch_id": batch_id,
                "page_number": page_number,
                "source_count": len(inventory),
                "rule_count": 0,
                "status": "error",
                "error": safe_error(exc),
                "seconds": time.time() - started,
            }}

    for result in _map_batches(
        sorted(pages.items()), _extract_text_page,
        max_workers=max_workers, desc="Rule extraction: text pages", unit="page",
    ):
        text_rules.extend(result["rules"])
        text_logs.append(result["log"])

    def _extract_table(region: dict[str, Any]) -> dict[str, Any]:
        region_id = clean(region.get("region_id"))
        parsed_path = raw_dir / f"{region_id}_parsed.json"
        api_path = raw_dir / f"{region_id}_api_response.json"
        image_path = visual_dir / clean(region.get("image_path"))
        metadata = {
            "source_id": region_id,
            "page_number": region.get("page_number"),
            "section_path": region.get("section_path", []),
            "section_heading": region.get("section_heading", ""),
        }
        prompt = TABLE_RULE_PROMPT + json.dumps(metadata, ensure_ascii=False)
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
            return {"rules": rules, "log": {
                "batch_id": region_id,
                "page_number": region.get("page_number"),
                "section_heading": region.get("section_heading"),
                "rule_count": len(rules),
                "skipped_count": len(parsed.get("skipped_sources", [])),
                "warnings": parsed.get("warnings", []),
                "status": "ok",
                "seconds": time.time() - started,
            }}
        except Exception as exc:
            return {"rules": [], "log": {
                "batch_id": region_id,
                "page_number": region.get("page_number"),
                "section_heading": region.get("section_heading"),
                "rule_count": 0,
                "status": "error",
                "error": safe_error(exc),
                "seconds": time.time() - started,
            }}

    for result in _map_batches(
        regulatory_tables, _extract_table,
        max_workers=max_workers, desc="Rule extraction: tables", unit="table",
    ):
        table_rules.extend(result["rules"])
        table_logs.append(result["log"])

    combined_rules = [*table_rules, *text_rules]
    for index, rule in enumerate(combined_rules, start=1):
        rule["rule_id"] = f"pipeline5_rule_{index:04d}"
    merged_rules, merge_audit, merge_review_queue = merge_and_audit_rules(combined_rules)
    non_canonical_units = sorted({
        offending
        for rule in merged_rules
        if (offending := non_canonical_unit(rule.get("unit")))
    })
    extraction_quality_flags = Counter(
        reason for rule in merged_rules for reason in rule.get("review_reasons", [])
    )

    write_json(output_dir / "text_rules_raw.json", text_rules)
    write_csv(output_dir / "text_rules_raw.csv", text_rules)
    write_json(output_dir / "table_rules_raw.json", table_rules)
    write_csv(output_dir / "table_rules_raw.csv", table_rules)
    write_json(output_dir / "combined_rules_raw.json", combined_rules)
    write_csv(output_dir / "combined_rules_raw.csv", combined_rules)
    write_json(output_dir / "merged_rules_deduplicated.json", merged_rules)
    write_csv(output_dir / "merged_rules_deduplicated.csv", merged_rules)
    write_json(output_dir / "merge_audit.json", merge_audit)
    write_csv(output_dir / "merge_audit.csv", merge_audit)
    write_json(output_dir / "merge_review_queue.json", merge_review_queue)
    write_csv(output_dir / "merge_review_queue.csv", merge_review_queue)
    write_json(output_dir / "text_extraction_logs.json", text_logs)
    write_json(output_dir / "table_extraction_logs.json", table_logs)
    write_json(output_dir / "ignored_visual_regions.json", ignored_visual_regions)

    summary = {
        "model": args.model,
        "text_model": text_model,
        "table_model": table_model,
        "visual_blocks_dir": str(visual_dir),
        "text_block_count": len(text_blocks),
        "text_page_batch_count": len(pages),
        "regulatory_table_count": len(regulatory_tables),
        "ignored_visual_region_count": len(ignored_visual_regions),
        "text_rule_count": len(text_rules),
        "table_rule_count": len(table_rules),
        "combined_rule_count": len(combined_rules),
        "deduplicated_rule_count": len(merged_rules),
        "auto_folded_group_count": len(merge_audit),
        "auto_folded_rule_count": sum(row["merged_rule_count"] - 1 for row in merge_audit),
        "merge_review_rule_count": len(merge_review_queue),
        "non_canonical_unit_count": len(non_canonical_units),
        "non_canonical_units": non_canonical_units,
        "extraction_quality_flags": dict(extraction_quality_flags),
        "text_successful_batches": sum(log.get("status") == "ok" for log in text_logs),
        "table_successful_batches": sum(log.get("status") == "ok" for log in table_logs),
        "text_logs": text_logs,
        "table_logs": table_logs,
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    args = parse_args()
    summary = process_extraction(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
