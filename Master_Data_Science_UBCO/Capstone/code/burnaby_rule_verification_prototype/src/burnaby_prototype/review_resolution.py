"""Final review-resolution labels for remaining review rules.

The verifier already decides ``verified`` / ``review_needed`` / ``rejected`` /
``not_used``. This module does not change those buckets. It turns the remaining
review queue into a smaller set of operational resolutions so a reviewer knows
what kind of work is left.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .review_text import candidate_sentence, counter_rows, evidence_sentence


def build_review_resolution(
    review_rules: list[dict[str, Any]],
    *,
    review_router_report: dict[str, Any],
    evidence_bundle_rerun_report: dict[str, Any],
) -> dict[str, Any]:
    """Return one resolution row for every remaining review rule."""
    router_by_id = {
        str(item.get("rule_id") or ""): item
        for item in review_router_report.get("items", [])
    }
    bundle_by_id = {
        str(item.get("original_rule_id") or ""): item
        for item in evidence_bundle_rerun_report.get("attempts", [])
    }
    items = [
        _resolution_item(
            rule,
            router_by_id.get(str(rule.get("rule_id") or ""), {}),
            bundle_by_id.get(str(rule.get("rule_id") or ""), {}),
        )
        for rule in review_rules
    ]
    resolution_counts = Counter(item["resolution"] for item in items)
    next_step_counts = Counter(item["next_step_type"] for item in items)
    return {
        "purpose": "Reviewer-facing resolution labels. Advisory only; does not promote rules.",
        "review_rule_count": len(items),
        "items": items,
        "summary": {
            "resolution_counts": counter_rows(resolution_counts),
            "next_step_type_counts": counter_rows(next_step_counts),
            # Invariant: always 0 — see the promotable_now field comment.
            "promotable_now_count": sum(1 for item in items if item["promotable_now"]),
            "can_promote_after_evidence_fix_count": sum(
                1 for item in items if item["can_promote_after_evidence_fix"]
            ),
            "duplicate_or_degraded_count": resolution_counts.get("duplicate_or_degraded_extraction", 0),
            "recommendations": _recommendations(resolution_counts, next_step_counts),
        },
    }


def review_resolution_markdown(report: dict[str, Any], *, limit: int = 25) -> str:
    """Render a compact markdown review-resolution report."""
    lines = [
        "# Review Resolution",
        "",
        "This report labels what remains in `review_needed.json`. It does not verify rules.",
        "",
        "## Summary",
        "",
        f"- Review rules: {report.get('review_rule_count', 0)}",
        f"- Promotable now: {report.get('summary', {}).get('promotable_now_count', 0)}",
        f"- Can promote after evidence fix: {report.get('summary', {}).get('can_promote_after_evidence_fix_count', 0)}",
        "",
        "### Resolutions",
        "",
        *[
            f"- `{item['name']}`: {item['count']}"
            for item in report.get("summary", {}).get("resolution_counts", [])
        ],
        "",
        f"## Top {limit}",
        "",
    ]
    for item in report.get("items", [])[:limit]:
        lines.append(
            f"- `{item['rule_id']}` -> `{item['resolution']}`: {item['human_next_step']}"
        )
    return "\n".join(lines) + "\n"


def _resolution_item(
    rule: dict[str, Any],
    router_item: dict[str, Any],
    bundle_attempt: dict[str, Any],
) -> dict[str, Any]:
    gaps = set(rule.get("support_gaps", []))
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    action = str(router_item.get("action_bucket") or rule.get("review_action_bucket") or "")
    resolution, next_step_type, human_next_step = _resolution(gaps, action, router_item, bundle_attempt)
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "candidate_id": str(rule.get("candidate", {}).get("candidate_id") or ""),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "condition": rule.get("condition"),
        "support_gaps": list(rule.get("support_gaps", [])),
        "source_page": source.get("page"),
        "source_evidence_id": source.get("evidence_id"),
        "resolution": resolution,
        "next_step_type": next_step_type,
        "human_next_step": human_next_step,
        "candidate_sentence": router_item.get("candidate_sentence") or candidate_sentence(rule),
        "evidence_sentence": router_item.get("evidence_sentence") or evidence_sentence(source),
        # Always False by construction: apply_bundle_promotions already moved
        # every guard-approved rule out of this queue before resolution runs.
        "promotable_now": False,
        "can_promote_after_evidence_fix": _can_promote_after_evidence_fix(gaps, router_item, bundle_attempt),
        "semantic_verified_rule_id": router_item.get("semantic_verified_rule_id"),
        "semantic_score": router_item.get("semantic_score"),
        "semantic_guardrail_blockers": list(router_item.get("semantic_guardrail_blockers", [])),
        "bundle_rerun_decision": bundle_attempt.get("retry_decision"),
        "bundle_rerun_gaps": list(bundle_attempt.get("retry_support_gaps", [])),
        "bundle_rerun_promotion_ready": bool(bundle_attempt.get("promotion_ready")),
        "where_to_find_it": router_item.get("where_to_find_it"),
    }


def _resolution(
    gaps: set[str],
    action: str,
    router_item: dict[str, Any],
    bundle_attempt: dict[str, Any],
) -> tuple[str, str, str]:
    if action == "semantic_duplicate_review":
        return (
            "duplicate_or_degraded_extraction",
            "close_as_duplicate_or_keep_out_of_contract",
            "Compare against the semantic verified match. If it adds no new legal rule, keep it out of GIS instead of tuning the verifier.",
        )
    if action == "semantic_guardrail_review":
        return (
            "close_match_but_guardrail_blocked",
            "manual_guardrail_check",
            "The meaning is close, but a core legal field differs. Do not promote unless the mismatch is resolved from source text.",
        )
    if "unresolved_exception_cue" in gaps or action == "human_legal_review":
        return (
            "human_legal_review",
            "legal_exception_or_override_review",
            "Resolve exception, covenant, approval, or notwithstanding language manually.",
        )
    if "cross_family_value_collision" in gaps:
        return (
            "conflict_review",
            "choose_correct_rule_family",
            "Compare sibling rule families and decide which family owns the value.",
        )
    if gaps & {"rule_object_not_supported", "rule_object_not_canonical", "table_rule_object_not_supported"}:
        return (
            "upstream_extraction_issue",
            "fix_candidate_rule_family",
            "Send this back to extraction/normalization; the cited evidence does not prove the selected rule family.",
        )
    if gaps & {"operator_not_supported", "rule_family_direction_mismatch", "table_operator_refuted"}:
        return (
            "operator_or_direction_issue",
            "confirm_operator_direction",
            "Confirm whether the bylaw says minimum, maximum, required, permitted, or an exception to those.",
        )
    if gaps & {"text_condition_not_supported", "table_condition_not_supported"}:
        return (
            "condition_evidence_needed",
            "find_condition_span",
            "Find evidence that explicitly carries the material condition, not only the numeric value.",
        )
    if gaps & {"applies_to_not_supported", "constraint_scope_not_supported", "table_applies_to_not_supported", "table_column_not_target_scope"}:
        return (
            "scope_or_applies_to_evidence_needed",
            "find_scope_context",
            "Find row/header/local prose proving the affected building, lot type, or scope.",
        )
    if gaps == {"text_candidate_requires_review"}:
        return (
            "needs_second_source_consensus",
            "find_independent_corroboration",
            "Find table-backed or independent text evidence for the same text candidate before promotion.",
        )
    if bundle_attempt.get("promotion_ready"):
        # This rule is STILL in the review queue even though its bundle rerun
        # reported promotion_ready: apply_bundle_promotions has already removed
        # every guard-approved attempt, so a remaining one was explicitly
        # rejected by the promotion guard. Labelling it "promotion ready" here
        # would invite a reviewer to promote something the guard refused.
        return (
            "promotion_rejected_by_guard",
            "manual_guard_blocker_review",
            "Bundle rerun verified, but the promotion guard rejected it. Inspect the guard blockers in bundle_promotion_report.json; do not promote manually.",
        )
    return (
        "low_priority_defer",
        "defer_until_more_evidence",
        "Keep in review until more evidence or a broader benchmark justifies a general verifier change.",
    )


def _can_promote_after_evidence_fix(
    gaps: set[str],
    router_item: dict[str, Any],
    bundle_attempt: dict[str, Any],
) -> bool:
    """Flag only review items that have a plausible deterministic repair path.

    This deliberately excludes semantic-duplicate and guardrail cases. Semantic
    similarity can reduce reviewer effort, but it cannot be an evidence fix.
    """
    if bundle_attempt.get("promotion_ready"):
        # The bundle rerun verified but the rule is still here, which means the
        # promotion guard explicitly rejected it. A guard rejection is not an
        # evidence problem — no amount of better evidence retrieval fixes it.
        return False
    if bundle_attempt.get("promotion_risk_flags"):
        return False
    if router_item.get("semantic_guardrail_blockers"):
        return False
    if router_item.get("action_bucket") in {"semantic_duplicate_review", "semantic_guardrail_review"}:
        return False
    # Only CONTEXT gaps count as evidence-fixable: consensus/table-gate review
    # markers and missing condition/scope/applies_to spans are exactly the gaps
    # a better evidence packet (a table header, a neighbouring clause) can
    # close, after which the unchanged deterministic verifier re-decides.
    # Operator, value, and unit gaps are deliberately EXCLUDED: those fields
    # define the legal claim itself, so "fixing" them with retrieved evidence
    # would mean searching the bylaw for text that agrees with the candidate —
    # confirmation bias as a repair strategy. Those go back to extraction or to
    # a human instead.
    if gaps <= {
        "text_candidate_requires_review",
        "text_condition_not_supported",
        "table_condition_not_supported",
        "applies_to_not_supported",
        "constraint_scope_not_supported",
        "table_applies_to_not_supported",
        "table_column_not_target_scope",
        "table_cell_candidate_requires_review",
        "table_evidence_candidate_requires_review",
        "table_fallback_candidate_requires_review",
    }:
        return True
    return False


def _recommendations(resolution_counts: Counter[str], next_step_counts: Counter[str]) -> list[str]:
    """Return short, dashboard-ready operating recommendations."""
    recommendations: list[str] = []
    if resolution_counts.get("promotion_rejected_by_guard", 0):
        recommendations.append("Inspect guard blockers for rules whose bundle rerun verified but was rejected by the promotion guard; do not promote them manually.")
    if resolution_counts.get("condition_evidence_needed", 0):
        recommendations.append("Prioritize finding condition spans; these are often close to verified but missing legal qualifiers.")
    if resolution_counts.get("scope_or_applies_to_evidence_needed", 0):
        recommendations.append("Prioritize table headers, row labels, and nearby prose for scope/applies_to gaps.")
    if resolution_counts.get("duplicate_or_degraded_extraction", 0):
        recommendations.append("Close semantic duplicates as extraction noise unless they add a distinct legal rule.")
    if next_step_counts.get("legal_exception_or_override_review", 0):
        recommendations.append("Keep exception, covenant, and notwithstanding language in human legal review.")
    return recommendations or ["No immediate resolution action dominates the queue."]
