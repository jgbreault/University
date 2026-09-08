"""Tri-state proposal checks against verified zoning rules.

The compliance layer is intentionally conservative: it can approve only when a
proposal field is covered by a verified rule and the value passes that rule.
Missing or review-only rules return needs_review, not approval.
"""

from __future__ import annotations

import re
from typing import Any


APPROVED = "approved"
REJECTED = "rejected"
NEEDS_REVIEW = "needs_review"

# These fields help choose a rule but are not themselves zoning measurements.
# Unknown measurement fields must go to review instead of being silently ignored.
CONTEXT_FIELDS = {"roof_type", "is_heritage_lot"}

RULE_OBJECT_ALIASES = {
    "building_height": "height",
    "height": "height",
    "lot_coverage": "lot_coverage",
    "impervious_surfaces": "impervious_surface",
    "impervious_surface": "impervious_surface",
    "lot_area": "lot_area",
    "permitted_dwelling_units": "dwelling_units",
    "dwelling_units": "dwelling_units",
    "setback": "setback",
    "building_separation": "building_separation",
    "automatic_sprinkler": "automatic_sprinkler",
    "fire_access_corridor": "fire_access_corridor",
}


CHECK_SPECS: dict[str, dict[str, Any]] = {
    "rear_principal_height_m": {
        "label": "Rear principal building height",
        "rule_object": "height",
        "terms": ["rear", "principal"],
        "applies_to_terms": ["rear", "principal"],
        "unit": "m",
        "roof_type_sensitive": True,
    },
    "front_rear_principal_separation_m": {
        "label": "Front/rear principal building separation",
        "rule_object": "building_separation",
        "terms": ["front", "rear", "principal"],
        "unit": "m",
    },
    "rear_rear_principal_separation_m": {
        "label": "Rear/rear principal building separation",
        "rule_object": "building_separation",
        "terms": ["rear", "principal"],
        "forbidden_terms": ["front"],
        "unit": "m",
    },
    "accessory_rear_yard_setback_m": {
        "label": "Accessory building interior rear-yard setback",
        "rule_object": "setback",
        "terms": ["accessory", "interior", "rear", "yard"],
        "applies_to_terms": ["accessory"],
        "unit": "m",
    },
    "rear_principal_rear_yard_setback_m": {
        "label": "Rear principal building interior rear-yard setback",
        "rule_object": "setback",
        "terms": ["rear", "principal", "interior", "rear", "yard"],
        "applies_to_terms": ["rear", "principal"],
        "forbidden_terms": ["accessory"],
        "unit": "m",
    },
    "lane_yard_setback_m": {
        "label": "Lane-yard setback",
        "rule_object": "setback",
        "terms": ["lane", "yard"],
        "unit": "m",
    },
    "street_front_yard_setback_m": {
        "label": "Front street-yard setback",
        "rule_object": "setback",
        "terms": ["street", "yard", "front"],
        "unit": "m",
    },
    "street_flanking_yard_setback_m": {
        "label": "Flanking street-yard setback",
        "rule_object": "setback",
        "terms": ["street", "yard", "flanking"],
        "unit": "m",
    },
    "lot_coverage_percent": {
        "label": "Lot coverage",
        "rule_object": "lot_coverage",
        "terms": ["lot", "coverage"],
        "unit": "%",
        "heritage_sensitive": True,
    },
    "impervious_surface_percent": {
        "label": "Impervious surface coverage",
        "rule_object": "impervious_surface",
        "terms": ["impervious", "surface"],
        "unit": "%",
        "heritage_sensitive": True,
    },
    "fire_access_corridor_width_m": {
        "label": "Fire access corridor width",
        "rule_object": "fire_access_corridor",
        "terms": ["fire", "access", "corridor", "width"],
        "unit": "m",
    },
    "fire_access_corridor_clearance_m": {
        "label": "Fire access corridor vertical clearance",
        "rule_object": "fire_access_corridor",
        "terms": ["fire", "access", "corridor", "clearance"],
        "unit": "m",
    },
}


def evaluate_cases(
    proposal_cases: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        evaluate_case(case, verified_rules, review_rules or [])
        for case in proposal_cases
    ]


def evaluate_case(
    proposal_case: dict[str, Any],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    proposal = proposal_case.get("proposal", {})
    review_rules = review_rules or []
    passed_checks: list[dict[str, Any]] = []
    failed_checks: list[dict[str, Any]] = []
    review_checks: list[dict[str, Any]] = []

    for field, actual_value in proposal.items():
        if field not in CHECK_SPECS:
            if field not in CONTEXT_FIELDS:
                review_checks.append(
                    {
                        "field": field,
                        "label": "Unsupported proposal field",
                        "actual_value": actual_value,
                        "reason": "unsupported_proposal_field",
                        "review_rule_id": None,
                        "message": "No compliance check is defined for this proposal field.",
                    }
                )
            continue
        spec = CHECK_SPECS[field]
        verified_rule = _find_best_rule(spec, verified_rules, proposal)
        if verified_rule:
            passed, message = _passes_rule(actual_value, verified_rule)
            detail = _check_detail(field, spec, actual_value, verified_rule, message)
            if passed:
                passed_checks.append(detail)
            else:
                failed_checks.append(detail)
            continue

        review_rule = _find_best_rule(spec, review_rules, proposal)
        review_checks.append(
            {
                "field": field,
                "label": spec["label"],
                "actual_value": actual_value,
                "reason": "rule_not_verified",
                "review_rule_id": review_rule.get("rule_id") if review_rule else None,
                "message": "No verified rule covers this proposal field.",
            }
        )

    if not passed_checks and not failed_checks and not review_checks:
        # A proposal with only context fields (or no fields) has not actually
        # been checked against any zoning constraint, so it cannot be approved.
        review_checks.append(
            {
                "field": "proposal",
                "label": "No checkable proposal fields",
                "actual_value": None,
                "reason": "no_checkable_proposal_fields",
                "review_rule_id": None,
                "message": "No checkable zoning measurement was provided.",
            }
        )

    if failed_checks:
        decision = REJECTED
    elif review_checks:
        decision = NEEDS_REVIEW
    else:
        decision = APPROVED

    actual_failed_fields = _check_fields(failed_checks)
    actual_review_fields = _check_fields(review_checks)
    expected_failed_fields = sorted(proposal_case.get("expected_failed_checks", actual_failed_fields))
    expected_review_fields = sorted(proposal_case.get("expected_review_checks", actual_review_fields))
    decision_matches = decision == proposal_case.get("expected_decision")
    failed_checks_match = actual_failed_fields == expected_failed_fields
    review_checks_match = actual_review_fields == expected_review_fields

    return {
        "case_id": proposal_case.get("case_id"),
        "description": proposal_case.get("description"),
        "decision": decision,
        "expected_decision": proposal_case.get("expected_decision"),
        # A correct final decision is not enough for the benchmark. We also
        # compare field-level failed/review checks so a hidden matching bug cannot
        # pass by returning the right broad tri-state label for the wrong reason.
        "matches_expected": decision_matches and failed_checks_match and review_checks_match,
        "decision_matches_expected": decision_matches,
        "actual_failed_checks": actual_failed_fields,
        "expected_failed_checks": expected_failed_fields,
        "failed_checks_match_expected": failed_checks_match,
        "actual_review_checks": actual_review_fields,
        "expected_review_checks": expected_review_fields,
        "review_checks_match_expected": review_checks_match,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "review_checks": review_checks,
    }


def summarize_case_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    decision_correct = sum(1 for result in results if result.get("decision_matches_expected", result["matches_expected"]))
    fully_correct = sum(1 for result in results if result["matches_expected"])
    false_approvals = [
        result["case_id"]
        for result in results
        if result["decision"] == APPROVED and result.get("expected_decision") != APPROVED
    ]
    false_rejections = [
        result["case_id"]
        for result in results
        if result["decision"] == REJECTED and result.get("expected_decision") == APPROVED
    ]
    field_mismatches = [
        result["case_id"]
        for result in results
        if not result.get("failed_checks_match_expected", True)
        or not result.get("review_checks_match_expected", True)
    ]
    return {
        "proposal_case_count": total,
        "proposal_decision_accuracy": decision_correct / total if total else 0.0,
        "proposal_case_accuracy": fully_correct / total if total else 0.0,
        "false_approval_count": len(false_approvals),
        "false_approval_cases": false_approvals,
        "false_rejection_count": len(false_rejections),
        "false_rejection_cases": false_rejections,
        "field_expectation_mismatch_count": len(field_mismatches),
        "field_expectation_mismatch_cases": field_mismatches,
        "needs_review_count": sum(1 for result in results if result["decision"] == NEEDS_REVIEW),
    }


def _find_best_rule(
    spec: dict[str, Any],
    rules: list[dict[str, Any]],
    proposal: dict[str, Any],
) -> dict[str, Any] | None:
    """Pick the verified rule a proposal must be checked against.

    This selection underwrites false_approval=0, so the filters are hard, not
    best-effort: family and unit must match exactly, every required term must
    be present, and conditional rule variants are filtered SYMMETRICALLY — a
    heritage-conditioned (usually more permissive) rule is only eligible when
    the proposal states the heritage context, and vice versa. Without the
    symmetric side, a proposal that omitted the context could win the more
    permissive conditional limit and be wrongly approved at the boundary.
    """
    scored: list[tuple[int, dict[str, Any]]] = []
    for rule in rules:
        if _normalize_name(rule.get("rule_object")) != _normalize_name(spec["rule_object"]):
            continue
        if spec.get("unit") and _normalize_unit(rule.get("unit")) != _normalize_unit(spec["unit"]):
            continue
        if spec.get("heritage_sensitive"):
            is_heritage_rule = "heritage" in _rule_words(rule)
            if proposal.get("is_heritage_lot") and not is_heritage_rule:
                continue
            if not proposal.get("is_heritage_lot") and is_heritage_rule:
                continue
        if spec.get("roof_type_sensitive"):
            roof_type = str(proposal.get("roof_type") or "").lower()
            condition_text = str(rule.get("condition") or "").lower()
            if roof_type and roof_type not in condition_text:
                continue
            if not roof_type and any(word in condition_text for word in ("sloping", "flat")):
                # Proposal does not state its roof type: a roof-conditioned
                # limit must not be applied blind — fail toward review.
                continue
        applies_to_terms = {_normalize_token(term) for term in spec.get("applies_to_terms", [])}
        if applies_to_terms and not applies_to_terms <= _rule_words(rule):
            continue

        words = _rule_words(rule)
        required_terms = {_normalize_token(term) for term in spec.get("terms", [])}
        forbidden_terms = {_normalize_token(term) for term in spec.get("forbidden_terms", [])}
        if forbidden_terms & words:
            continue
        matched_terms = required_terms & words
        if len(matched_terms) < len(required_terms):
            continue
        score = 10 + len(matched_terms)
        if all(term in words for term in required_terms):
            score += 5
        # Disambiguate adjacent table rows (e.g. front vs flanking street yard):
        # prefer the rule whose *structured* constraint_scope carries the spec's
        # distinctive terms, instead of relying on the noisy shared evidence_text.
        scope_words = _words(rule.get("constraint_scope"))
        score += 3 * len(required_terms & scope_words)
        scored.append((score, rule))
    if not scored:
        return None
    # Deterministic tie-break: equal scores must not depend on input list
    # order, or two runs over differently-sorted rules could approve against
    # different rule variants.
    scored.sort(key=lambda item: (-item[0], str(item[1].get("rule_id") or "")))
    return scored[0][1]


def _passes_rule(actual_value: Any, rule: dict[str, Any]) -> tuple[bool, str]:
    actual = _to_float(actual_value)
    target = _to_float(rule.get("value"))
    if actual is None or target is None:
        return False, "Cannot compare proposal value with rule value."
    operator = _canonical_operator(rule.get("operator"), rule.get("constraint_type"))
    if operator == "max":
        return actual <= target, f"{actual} must be <= {target}."
    if operator == "min":
        return actual >= target, f"{actual} must be >= {target}."
    if operator == "gt":
        return actual > target, f"{actual} must be > {target}."
    if operator == "lt":
        return actual < target, f"{actual} must be < {target}."
    return actual == target, f"{actual} must equal {target}."


def _check_detail(
    field: str,
    spec: dict[str, Any],
    actual_value: Any,
    rule: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    return {
        "field": field,
        "label": spec["label"],
        "actual_value": actual_value,
        "rule_id": rule.get("rule_id"),
        "rule_value": rule.get("value"),
        "rule_unit": rule.get("unit"),
        "operator": rule.get("operator"),
        "message": message,
    }


def _check_fields(checks: list[dict[str, Any]]) -> list[str]:
    """Return stable field names from failed/review check details."""
    return sorted(str(check.get("field")) for check in checks if check.get("field"))


def _canonical_operator(operator: Any, constraint_type: Any = None) -> str:
    text = f"{operator or ''} {constraint_type or ''}".lower()
    # '<=' must be classified before bare '<': a strict less-than rule is NOT
    # a non-strict maximum — evaluating '<' as 'max' would approve a proposal
    # sitting exactly at the limit the bylaw says to stay strictly under.
    if any(token in text for token in ["<=", "maximum", "max", "not_exceed", "not exceed", "≤"]):
        return "max"
    if any(token in text for token in [">=", "minimum", "min", "at_least", "at least", "≥"]):
        return "min"
    if ">" in text:
        return "gt"
    if "<" in text:
        return "lt"
    return "eq"


def _normalize_name(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return RULE_OBJECT_ALIASES.get(normalized, normalized)


def _normalize_unit(value: Any) -> str:
    text = str(value or "").lower().strip()
    if text in {"m2", "m 2", "m^2", "m²", "square metre", "square meter", "square metres", "square meters"}:
        return "m2"
    if text in {"percent", "percentage"}:
        return "%"
    return text


def _normalize_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _rule_text(rule: dict[str, Any]) -> str:
    parts = [
        rule.get("rule_object"),
        rule.get("constraint_type"),
        rule.get("constraint_scope"),
        rule.get("applies_to"),
        rule.get("condition"),
        rule.get("exception"),
        rule.get("source", {}).get("evidence_text") if isinstance(rule.get("source"), dict) else None,
    ]
    return " ".join(str(part) for part in parts if part is not None).lower()


def _rule_words(rule: dict[str, Any]) -> set[str]:
    return {_normalize_token(token) for token in re.findall(r"[a-z0-9]+", _rule_text(rule))}


def _words(value: Any) -> set[str]:
    return {_normalize_token(token) for token in re.findall(r"[a-z0-9]+", str(value or "").lower())}


from .domain_schema import to_float as _to_float
