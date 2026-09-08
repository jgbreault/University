"""Claim-level proof helpers for the slim verifier.

This module keeps the new proof-carrying layer small. The deterministic verifier
still decides verified/review/rejected from support gaps; these helpers explain
that decision and compute a Bayesian-lite review triage score.
"""

from __future__ import annotations

import re
from typing import Any


SUPPORTED = "supported"
REFUTED = "refuted"
NOT_ENOUGH_INFO = "not_enough_info"

# These are the pieces of a zoning rule we care about proving. A candidate can
# have other metadata, but these are the fields that make the legal/GIS claim.
CRITICAL_CLAIMS = (
    "rule_object",
    "constraint_scope",
    "applies_to",
    "operator",
    "value",
    "unit",
    "condition",
    "exception",
)


def proof(
    label: str,
    *,
    evidence_field: str = "",
    evidence_quote: Any = "",
    reason: str = "",
) -> dict[str, Any]:
    """Create one standardized claim proof object."""
    # Every proof object uses the same shape so JSON outputs are easy to inspect
    # and benchmark. A missing quote is okay for optional claims.
    return {
        "label": label,
        "evidence_field": evidence_field,
        "evidence_quote": "" if evidence_quote is None else str(evidence_quote),
        "reason": reason,
    }


def canonical_rule_key(rule: dict[str, Any]) -> str:
    """Build a stable key for comparing/reporting a verified candidate.

    The key intentionally excludes source IDs. Two extraction systems can cite
    different evidence and still be talking about the same zoning rule.

    ``exception`` is also deliberately excluded: exception wording is free-form
    prose that slugs unstably, so including it would split keys that describe
    the same rule. The cost is that an exception-bearing variant shares a key
    with its base rule in the advisory reuse counters — acceptable because the
    key is never used to make a verification decision.
    """
    parts = [
        # Use normalized rule content, not evidence IDs. This lets us compare
        # two candidates that cite different sources but claim the same rule.
        rule.get("rule_object"),
        rule.get("constraint_scope"),
        rule.get("applies_to"),
        rule.get("condition"),
        rule.get("operator"),
        rule.get("value"),
        rule.get("unit"),
    ]
    return "__".join(_slug(part) for part in parts if part not in (None, ""))


def verification_label_from_gaps(support_gaps: list[str]) -> str:
    """Map support gaps to a proof-style label.

    A missing critical value/unit/source is treated as refuted because the cited
    evidence fails the exact support check. Scope/table uncertainty is usually
    not_enough_info because it may be repairable by a better evidence packet.
    """
    refuting_gaps = {
        # These gaps mean the cited evidence actively fails a critical check.
        # They are stronger than "we need more context".
        "source_evidence_id_not_found",
        "value_not_found_in_evidence",
        "unit_not_found_in_evidence",
        "rule_object_unit_not_compatible",
        "table_operator_refuted",
        "non_numeric_value_for_numeric_rule",
    }
    if not support_gaps:
        return SUPPORTED
    if refuting_gaps & set(support_gaps):
        return REFUTED
    return NOT_ENOUGH_INFO


def merge_proof_traces(*traces: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Merge proof traces, keeping the strongest label per claim.

    Table natural logic can support claims that text checks marked as uncertain.
    Refuted remains strongest, then supported, then not_enough_info.
    """
    strength = {REFUTED: 3, SUPPORTED: 2, NOT_ENOUGH_INFO: 1}
    merged: dict[str, dict[str, Any]] = {}
    for trace in traces:
        for claim, item in trace.items():
            if (
                claim in {"condition", "exception"}
                and item.get("label") == NOT_ENOUGH_INFO
                and merged.get(claim, {}).get("label") == SUPPORTED
            ):
                # Conditions and exceptions can change legal meaning. If any
                # proof layer sees unresolved condition/exception wording, keep
                # that uncertainty visible instead of hiding it behind a weaker
                # optional-text support.
                merged[claim] = item
                continue
            if (
                claim in {"condition", "exception"}
                and item.get("label") == SUPPORTED
                and merged.get(claim, {}).get("label") == NOT_ENOUGH_INFO
            ):
                # Symmetric branch: a later SUPPORTED must not overwrite an
                # earlier NOT_ENOUGH_INFO either, or the stickiness above would
                # silently depend on the order traces are passed in (the
                # docstring promises order independence).
                continue
            # Keep the strongest explanation for each claim. If table logic says
            # a value is refuted, do not hide that behind a weaker text result.
            if claim not in merged or strength.get(item.get("label"), 0) > strength.get(merged[claim].get("label"), 0):
                merged[claim] = item
    return merged


def evidence_strength(
    proof_trace: dict[str, dict[str, Any]],
    support_checks: dict[str, bool],
    support_gaps: list[str],
    verification_decision: str,
) -> float:
    """Bayesian-lite evidence strength score for review triage.

    This is not a trained model. It is a Beta-style prior updated by deterministic
    support signals. It helps rank review_needed rules, but it never changes the
    verifier's final decision.
    """
    # Think of alpha as "evidence in favour" and beta as "evidence against or
    # uncertainty". Starting at 2/2 gives a neutral 0.5 prior.
    alpha = 2.0
    beta = 2.0

    for item in proof_trace.values():
        label = item.get("label")
        if label == SUPPORTED:
            # Supported claims increase confidence that the rule is repairable
            # or already well-grounded.
            alpha += 1.0
        elif label == REFUTED:
            # Refuted claims are heavier than missing claims because they often
            # indicate a real extraction error.
            beta += 2.0
        elif label == NOT_ENOUGH_INFO:
            beta += 0.6

    for passed in support_checks.values():
        # Reuse the old deterministic support checks as model features. This is
        # why we call it Bayesian-lite rather than a black-box ML model.
        if passed:
            alpha += 0.35
        else:
            beta += 0.8

    critical_gaps = {
        "source_evidence_id_not_found",
        "value_not_found_in_evidence",
        "unit_not_found_in_evidence",
        "rule_object_not_supported",
        "rule_object_unit_not_compatible",
    }
    # Critical gaps should pull the score down more strongly than ordinary
    # review gaps like "scope unclear".
    beta += 1.5 * len(critical_gaps & set(support_gaps))

    if verification_decision == "verified":
        # Verified rules get a small boost for triage display, but this boost is
        # applied after the deterministic gate has already passed.
        alpha += 2.0
    elif verification_decision == "rejected":
        beta += 2.0

    return round(alpha / (alpha + beta), 3)


def review_priority(verification_decision: str, strength: float, support_gaps: list[str]) -> str:
    """Convert evidence strength into a human-review priority."""
    # Review priority is for humans only. It never changes verified/rejected.
    if verification_decision == "verified":
        return "verified"
    if verification_decision == "not_used":
        return "not_used"
    if verification_decision == "rejected":
        return "low"

    gaps = set(support_gaps)
    low_quality_gaps = {
        "source_evidence_id_not_found",
        "value_not_found_in_evidence",
        "unit_not_found_in_evidence",
        "rule_object_unit_not_compatible",
        "non_numeric_value_for_numeric_rule",
    }
    if low_quality_gaps & gaps:
        # These are usually bad extractions, not nearly-verified rules.
        return "low"

    table_gate_gaps = {
        "table_cell_candidate_requires_review",
        "table_evidence_candidate_requires_review",
        "table_fallback_candidate_requires_review",
    }
    if gaps <= table_gate_gaps:
        # A pure table gate means the deterministic claims are otherwise clean.
        # These are the most repairable review items: a human can inspect the
        # table context and decide whether to expand auto-verification.
        return "high"

    if gaps == {"text_candidate_requires_review"}:
        # Text-only candidates may be correct, but they need a GIS text-rule
        # contract decision rather than urgent evidence repair.
        return "medium"

    if "unresolved_exception_cue" in gaps:
        # Exception/override wording can change legal meaning, so surface it
        # above ordinary scope or text-contract review.
        return "high"

    near_verified_gaps = {
        "operator_not_supported",
        "applies_to_not_supported",
        "constraint_scope_not_supported",
        "table_applies_to_not_supported",
        "table_condition_not_supported",
    }
    if near_verified_gaps & gaps and strength >= 0.55:
        # Missing operator/scope/applies_to support is often repairable, but it
        # is less "nearly done" than a pure table gate. Keep it medium unless the
        # evidence is extremely strong and there are no table-target problems.
        table_target_gaps = {"table_column_not_target_scope", "table_applies_to_not_supported"}
        if strength >= 0.82 and not (table_target_gaps & gaps):
            return "high"
        return "medium"

    if "upstream_extraction_requested_review" in gaps and strength >= 0.65:
        return "medium"
    # Single threshold: anything at or above 0.45 evidence strength is worth a
    # look. (A leftover >=0.80 tier used to sit above this returning the same
    # value — there is deliberately no strength-only "high"; high priority is
    # reserved for the structural cases above.)
    if strength >= 0.45:
        return "medium"
    return "low"


def proof_trace_completion_rate(rules: list[dict[str, Any]]) -> float:
    """Return share of rules that contain at least value/unit/operator proof keys."""
    # We only require the three most inspectable claims here. A rule may not have
    # an applies_to/condition/exception claim.
    if not rules:
        return 0.0
    required = {"value", "unit", "operator"}
    complete = 0
    for rule in rules:
        trace = rule.get("proof_trace", {})
        if required <= set(trace):
            complete += 1
    return round(complete / len(rules), 3)


def count_claim_labels(rules: list[dict[str, Any]]) -> dict[str, int]:
    """Count supported/refuted/not_enough_info labels across proof traces."""
    # Benchmark uses this to summarize how much of the output is proved,
    # contradicted, or still uncertain.
    counts = {SUPPORTED: 0, REFUTED: 0, NOT_ENOUGH_INFO: 0}
    for rule in rules:
        for proof_item in rule.get("proof_trace", {}).values():
            label = proof_item.get("label")
            if label in counts:
                counts[label] += 1
    return counts


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
