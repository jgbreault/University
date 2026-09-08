"""Candidate normalization before deterministic verification.

Normalization translates extraction wording into the verifier's canonical rule
schema.  It can rewrite stable representations such as ranges into upper bounds,
but it must not prove or promote a rule.  Verification still happens later from
cited evidence and support gaps.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import (
    PLAIN_ONLY_RULE_OBJECT_PATTERNS,
    RULE_OBJECT_ALIASES,
    TEXT_RULE_OBJECT_PATTERNS,
    normalized_name,
    plain_text,
    to_float,
    unit_key,
)
from .normalization_rules import (
    applies_to_hint,
    condition_default,
    get_normalization,
    parse_distance_rewrite,
    range_upper_bound_rewrite,
    scope_hint,
    unit_rewrite,
)


def normalize_candidate(
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a cleaned copy of the candidate before support checks run."""
    normalized = dict(candidate)
    normalized["rule_object"] = _canonical_rule_object(candidate.get("rule_object"), candidate, evidence)
    normalized["constraint_type"] = _canonical_constraint_type(
        candidate.get("constraint_type"), candidate.get("operator")
    )
    _refine_normalized_candidate(normalized, candidate, evidence, config)
    _fill_operator_from_family_direction(normalized, config)
    return normalized


def _fill_operator_from_family_direction(
    normalized: dict[str, Any], config: dict[str, Any] | None
) -> None:
    """Default a missing operator from the rule family's fixed direction.

    The extractor sometimes tags a dimensional clause without a direction
    (``constraint_type='dimensional'``, ``operator=''``) even when the clause
    plainly states "minimum"/"maximum" (e.g. R-CG setbacks). The family
    direction in ``verification.rule_family_direction`` (setbacks are minimums,
    heights are maximums) supplies the operator. This does NOT loosen any gate:
    the downstream ``operator_supported`` and family-direction checks still
    validate the filled operator against the evidence wording, so a clause that
    does not actually state that direction still fails. Only fills when blank.
    """
    if str(normalized.get("operator") or "").strip():
        return
    direction = (
        ((config or {}).get("verification") or {})
        .get("rule_family_direction", {})
        .get(normalized.get("rule_object"))
    )
    if direction == "min":
        normalized["operator"] = ">="
        normalized["operator_filled_from_family_direction"] = True
        if not str(normalized.get("constraint_type") or "").strip() or normalized.get(
            "constraint_type"
        ) == "dimensional":
            normalized["constraint_type"] = "minimum"
    elif direction == "max":
        normalized["operator"] = "<="
        normalized["operator_filled_from_family_direction"] = True
        if not str(normalized.get("constraint_type") or "").strip() or normalized.get(
            "constraint_type"
        ) == "dimensional":
            normalized["constraint_type"] = "maximum"


def normalization_trace(
    original: dict[str, Any],
    normalized: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Explain field changes made before verification checks."""
    trace: list[dict[str, Any]] = []
    for field in (
        "rule_object",
        "constraint_type",
        "constraint_scope",
        "applies_to",
        "operator",
        "value",
        "unit",
        "condition",
    ):
        before = original.get(field)
        after = normalized.get(field)
        if str(before or "") == str(after or ""):
            continue
        trace.append(
            {
                "field": field,
                "before": before,
                "after": after,
                "reason": _normalization_reason(field, original, normalized, evidence),
            }
        )
    return trace


def _canonical_rule_object(
    value: Any,
    candidate: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> str | None:
    """Map extracted rule wording into the canonical rule family."""
    if value in (None, "") and not candidate and not evidence:
        return None
    candidate_for_text = candidate or {"rule_object": value}
    text = _combined_candidate_text(candidate_for_text, evidence)
    focused_text = _focused_candidate_text(candidate_for_text, evidence)
    combined = f"{plain_text(value)} {text}"
    unit = unit_key((candidate or {}).get("unit"))

    if "automatic_sprinkler" in focused_text or "sprinkler" in focused_text:
        return "automatic_sprinkler"
    if "fire_access_corridor" in focused_text or "fire access corridor" in focused_text:
        return "fire_access_corridor"
    if "impervious" in focused_text:
        return "impervious_surface"
    if "lot_coverage" in focused_text or "lot coverage" in focused_text:
        return "lot_coverage"

    normalized = normalized_name(value)
    if normalized in RULE_OBJECT_ALIASES:
        alias = RULE_OBJECT_ALIASES[normalized]
        if alias == "storeys" and unit == "m" and "height" in combined:
            return "height"
        if alias == "dwelling_units":
            if "automatic_sprinkler" in combined or "sprinkler" in combined:
                return "automatic_sprinkler"
            if "fire_access_corridor" in combined or "fire access corridor" in combined:
                return "fire_access_corridor"
        return alias

    plain_value = plain_text(value)
    plain_match = _rule_object_from_patterns(plain_value, [*PLAIN_ONLY_RULE_OBJECT_PATTERNS, *TEXT_RULE_OBJECT_PATTERNS])
    if plain_match:
        return plain_match
    if plain_value.startswith("between"):
        return "building_separation"

    context_match = _rule_object_from_patterns(combined, TEXT_RULE_OBJECT_PATTERNS)
    if context_match == "storeys":
        if unit == "storeys":
            return "storeys"
        if "height" not in combined:
            return "storeys"
        return "height"
    if context_match:
        return context_match
    if "permitted_use" in normalized:
        return "permitted_use"
    if "height" in combined:
        return "height"
    return normalized


def _canonical_constraint_type(value: Any, operator: Any) -> Any:
    """Normalize operator wording into a broad constraint type."""
    text = f"{value or ''} {operator or ''}".lower()
    if any(token in text for token in ["<=", "≤", "maximum", "max"]):
        return "maximum"
    if any(token in text for token in [">=", "≥", "minimum", "min"]):
        return "minimum"
    if any(token in text for token in ["allowed", "permitted"]):
        return "allowed"
    if "required" in text:
        return "required"
    return value


def _normalization_reason(
    field: str,
    original: dict[str, Any],
    normalized: dict[str, Any],
    evidence: dict[str, Any] | None,
) -> str:
    focused_text = _focused_candidate_text(original, evidence)
    if field == "rule_object":
        if "sprinkler" in focused_text:
            return "Pipeline 5 subject/rule_key indicates automatic sprinkler rule"
        if "fire_access_corridor" in focused_text or "fire access corridor" in focused_text:
            return "Pipeline 5 subject/rule_key indicates fire access corridor rule"
        if "impervious" in focused_text:
            return "Pipeline 5 subject/rule_key indicates impervious surface rule"
        if "lot_coverage" in focused_text or "lot coverage" in focused_text:
            return "Pipeline 5 subject/rule_key indicates lot coverage rule"
        if str(normalized.get("rule_object")) in {"height", "storeys"}:
            return "height/storeys split inferred from unit and maximum-height context"
        return "canonical rule-object alias or text cue"
    if field in {"value", "unit", "operator", "constraint_type"} and normalized.get("rule_object") == "automatic_sprinkler":
        return "distance threshold parsed from sprinkler requirement text"
    if field == "applies_to":
        return "applies_to refined from Pipeline 5 subject/rule_key/evidence context"
    if field == "constraint_scope":
        return "constraint scope refined from rule family and Pipeline 5 context"
    return "canonical field normalization"


def _refine_normalized_candidate(
    normalized: dict[str, Any],
    original: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """Apply deterministic zoning-specific cleanups after canonicalization."""
    norm = get_normalization(config)
    text = _combined_candidate_text(normalized, evidence)
    focused_text = _focused_candidate_text(normalized, evidence)
    rule_object = normalized.get("rule_object")

    if rule_object == "storeys" and unit_key(normalized.get("unit")) == "m" and "height" in focused_text:
        normalized["rule_object"] = "height"
        rule_object = "height"
    elif rule_object == "height" and unit_key(normalized.get("unit")) == "storeys":
        normalized["rule_object"] = "storeys"
        rule_object = "storeys"

    # Per-city unit rewrite (capability knob, e.g. mapping a verbatim phrasing
    # like "multiplied by the site area" to the dimensionless 'fsr' unit and
    # optionally re-typing the family). Runs BEFORE verification, so a wrong
    # rewrite cannot verify — the rewritten unit must still pass contains_unit
    # and unit-compatibility against the cited evidence.
    rewrite_hit = unit_rewrite(
        rule_object,
        str(normalized.get("unit") or ""),
        focused_text,
        norm.get("unit_rewrites", []),
    )
    if rewrite_hit:
        normalized["unit"] = rewrite_hit["unit"]
        if rewrite_hit.get("rule_object"):
            normalized["rule_object"] = rewrite_hit["rule_object"]
            rule_object = rewrite_hit["rule_object"]

    dwelling_unit_source = " ".join(
        str(part or "")
        for part in [
            original.get("value"),
            evidence.get("cell_value") if evidence else None,
            evidence.get("evidence_text") if evidence else None,
        ]
    )
    original_operator_text = f"{original.get('operator') or ''} {original.get('constraint_type') or ''}".lower()
    claims_dwelling_upper_bound = (
        str(original.get("operator") or "").lower() == "range"
        or any(token in original_operator_text for token in ("<=", "≤", "maximum", "max"))
    )
    if rule_object == "dwelling_units" and claims_dwelling_upper_bound:
        rewrite = range_upper_bound_rewrite(rule_object, dwelling_unit_source, norm.get("range_rewrites", []))
        if rewrite and rewrite.get("value") is not None:
            normalized["value"] = rewrite["value"]
            normalized["operator"] = rewrite["operator"]
            normalized["constraint_type"] = rewrite["constraint_type"]
            normalized["unit"] = rewrite["unit"]
            normalized["constraint_scope"] = rewrite["constraint_scope"]
            normalized["applies_to"] = rewrite["applies_to"]

    if rule_object == "storeys":
        normalized["unit"] = "storeys"

    applies_to_hints = norm.get("applies_to_hints", [])

    if rule_object in {"height", "storeys"}:
        label = applies_to_hint(rule_object, focused_text, applies_to_hints)
        if label is not None:
            normalized["applies_to"] = label

    if rule_object == "setback":
        label = applies_to_hint(rule_object, focused_text, applies_to_hints)
        if label is not None:
            normalized["applies_to"] = label
        existing_scope = str(normalized.get("constraint_scope") or "").lower()
        condition_text = str(normalized.get("condition") or original.get("condition") or "").lower()
        hit = scope_hint(rule_object, f"{existing_scope} {condition_text}", focused_text, norm.get("scope_hints", []))
        if hit is not None:
            if hit.get("constraint_scope"):
                normalized["constraint_scope"] = hit["constraint_scope"]
            if "condition" in hit:
                normalized["condition"] = normalized.get("condition") or hit["condition"]
            if "applies_to" in hit:
                normalized["applies_to"] = hit["applies_to"]

    if rule_object == "building_separation":
        label = applies_to_hint(rule_object, focused_text, applies_to_hints)
        if label is not None:
            normalized["applies_to"] = label

    if rule_object == "automatic_sprinkler" and "sprinkler" in text:
        rewrite = parse_distance_rewrite(rule_object, text, norm.get("distance_rewrites", []))
        if rewrite:
            normalized["value"] = rewrite["value"]
            normalized["unit"] = rewrite["unit"]
            normalized["operator"] = rewrite["operator"]
            normalized["constraint_type"] = rewrite["constraint_type"]
            if "applies_to" in rewrite:
                normalized["applies_to"] = rewrite["applies_to"]
            if "condition" in rewrite:
                normalized["condition"] = normalized.get("condition") or rewrite["condition"]

    if rule_object == "fire_access_corridor" and "fire access corridor" in text:
        existing_scope = str(normalized.get("constraint_scope") or "").lower()
        corridor = condition_default(rule_object, text, norm.get("condition_defaults", []))
        if corridor is not None:
            if (not existing_scope or existing_scope in {"lot", "dwelling_unit", "fire_access_corridor"}) and corridor.get("constraint_scope"):
                normalized["constraint_scope"] = corridor["constraint_scope"]
            if "dwelling unit" in text:
                normalized["applies_to"] = "All dwelling units"
            if "condition" in corridor:
                normalized["condition"] = normalized.get("condition") or corridor["condition"]

    if rule_object == "fire_access_corridor" and any(term in text for term in ["projection", "obstruction", "clearance"]):
        normalized["constraint_scope"] = normalized.get("constraint_scope") or "vertical_clearance"
        if "dwelling unit" in text:
            normalized["applies_to"] = "All dwelling units"
        normalized["condition"] = normalized.get("condition") or "clear of projections or obstructions"

    if rule_object in {"lot_coverage", "impervious_surface", "setback"}:
        heritage = condition_default(rule_object, text, norm.get("condition_defaults", []))
        if heritage is not None and "condition" in heritage:
            normalized["condition"] = normalized.get("condition") or heritage["condition"]


def _combined_candidate_text(
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    *,
    include_source_context: bool = True,
) -> str:
    """Join candidate and evidence fields into one text blob for cue matching."""
    candidate_parts = [
        candidate.get("rule_object"),
        candidate.get("constraint_type"),
        candidate.get("constraint_scope"),
        candidate.get("applies_to"),
        candidate.get("rule_key"),
        candidate.get("subject"),
        candidate.get("condition"),
        candidate.get("exception"),
        candidate.get("value"),
        candidate.get("unit"),
    ]
    evidence_parts: list[Any] = []
    if evidence:
        evidence_parts = [
            evidence.get("evidence_text"),
            evidence.get("table_title"),
            evidence.get("row_header"),
            evidence.get("column_header"),
            evidence.get("cell_value"),
            evidence.get("heading"),
            evidence.get("section"),
        ]
        if include_source_context:
            evidence_parts.append(evidence.get("source_context"))
    return " ".join(str(part) for part in [*candidate_parts, *evidence_parts] if part is not None).lower()


def _focused_candidate_text(
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> str:
    """Return high-signal fields for deciding the intended rule family."""
    parts: list[Any] = [
        candidate.get("rule_object"),
        candidate.get("rule_key"),
        candidate.get("subject"),
        candidate.get("constraint_type"),
        candidate.get("constraint_scope"),
        candidate.get("applies_to"),
        candidate.get("condition"),
        candidate.get("value"),
        candidate.get("unit"),
    ]
    if evidence:
        parts.extend(
            [
                evidence.get("table_title"),
                evidence.get("row_header"),
                evidence.get("column_header"),
                evidence.get("cell_value"),
            ]
        )
    return " ".join(str(part) for part in parts if part is not None).lower().replace("-", "_")


def _phrase_match(text: str, phrase_groups: tuple[tuple[str, ...], ...]) -> bool:
    return any(all(phrase in text for phrase in group) for group in phrase_groups)


def _rule_object_from_patterns(text: str, patterns: list[tuple[str, tuple[tuple[str, ...], ...]]]) -> str | None:
    for rule_object, phrase_groups in patterns:
        if _phrase_match(text, phrase_groups):
            return rule_object
    return None
