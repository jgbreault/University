"""Decision-oriented proof DAG projection.

The current verifier already computes support checks, support gaps, and proof
traces. This module gives those outputs one universal shape without changing
the decision path. It is intentionally a projection layer: decisions still come
from ``decision_policy`` until the DAG has enough benchmark coverage to become
the primary decision input.
"""

from __future__ import annotations

from typing import Any

from .decision_policy import CRITICAL_REJECTION_GAPS, NOT_USED_GAPS
from .rule_claims import CRITICAL_CLAIMS, NOT_ENOUGH_INFO, REFUTED, SUPPORTED


STATUS_SUPPORTED = "supported"
STATUS_REFUTED = "refuted"
STATUS_NEI = "not_enough_info"
STATUS_NA = "not_applicable"

_LABEL_TO_STATUS = {
    SUPPORTED: STATUS_SUPPORTED,
    REFUTED: STATUS_REFUTED,
    NOT_ENOUGH_INFO: STATUS_NEI,
}

_GAP_TO_CLAIM = {
    "source_evidence_id_not_found": "source",
    "value_not_found_in_evidence": "value",
    "unit_not_found_in_evidence": "unit",
    "operator_not_supported": "operator",
    "table_operator_refuted": "operator",
    "applies_to_not_supported": "applies_to",
    "table_applies_to_not_supported": "applies_to",
    "constraint_scope_not_supported": "constraint_scope",
    "rule_object_not_supported": "rule_object",
    "rule_object_not_canonical": "rule_object",
    "rule_object_unit_not_compatible": "unit",
    "table_rule_object_not_supported": "rule_object",
    "text_condition_not_supported": "condition",
    "table_condition_not_supported": "condition",
    "missing_condition_evidence": "condition",
    "unresolved_exception_cue": "exception",
    "cross_family_value_collision": "rule_object",
    "rule_family_direction_mismatch": "operator",
    "allowance_trigger_threshold": "value",
    "definition_not_rule": "rule_object",
    "value_bound_to_foreign_unit": "value",
    "value_bound_to_foreign_measure": "value",
    "non_numeric_value_for_numeric_rule": "value",
    "column_value_mismatch": "applicability",
    "applicability_not_grounded": "applicability",
    "column_qualifier_not_claimed": "condition",
    "conditional_cell_condition_missing": "condition",
    "anchored_row_family_mismatch": "rule_object",
    "text_candidate_requires_review": "evidence_policy",
    "upstream_extraction_requested_review": "evidence_policy",
    "table_cell_candidate_requires_review": "evidence_policy",
    "table_evidence_candidate_requires_review": "evidence_policy",
    "table_fallback_candidate_requires_review": "evidence_policy",
    "cross_reference_only": "contract_scope",
    "outside_current_rule_contract": "contract_scope",
}


def build_proof_dag(
    *,
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None,
    proof_trace: dict[str, dict[str, Any]],
    support_gaps: list[str],
    decision: str,
    support_checks: dict[str, bool] | None = None,
    matrix_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the verifier's existing proof material into a DAG-shaped JSON.

    The graph is intentionally shallow today: claim nodes feed one decision
    node. That is still useful because every text/table/matrix evaluator can
    now target the same node schema as we gradually replace support-gap plumbing.
    """
    support_checks = support_checks or {}
    support_gaps = [str(gap) for gap in support_gaps]

    nodes: list[dict[str, Any]] = []
    seen_claims: set[str] = set()

    nodes.append(
        {
            "id": "source_present",
            "type": "source",
            "claim": "source",
            "status": STATUS_SUPPORTED if evidence else STATUS_REFUTED,
            "severity": "critical",
            "source": "evidence_lookup",
            "gap_codes": [] if evidence else ["source_evidence_id_not_found"],
            "reason": "cited evidence unit exists" if evidence else "candidate cites evidence that was not found",
            "evidence_field": "evidence_id",
            "evidence_quote": str((evidence or {}).get("evidence_id") or candidate.get("evidence_id") or ""),
        }
    )

    for claim in CRITICAL_CLAIMS:
        trace_item = proof_trace.get(claim) or {}
        node = _node_from_trace(claim, trace_item, candidate)
        nodes.append(node)
        seen_claims.add(claim)

    # Matrix/applicability is a first-class proof concept but not part of the
    # older CRITICAL_CLAIMS tuple. Add it explicitly when the matrix layer ran or
    # when a matrix gap is present.
    matrix_gaps = [
        gap
        for gap in support_gaps
        if gap in {"column_value_mismatch", "applicability_not_grounded", "column_qualifier_not_claimed", "conditional_cell_condition_missing", "anchored_row_family_mismatch"}
    ]
    if matrix_binding or matrix_gaps:
        nodes.append(_matrix_node(matrix_binding, matrix_gaps))
        seen_claims.add("applicability")

    # Add policy/contract/gap nodes not represented by the field trace. This is
    # what makes review holds explainable without overloading field nodes.
    for gap in support_gaps:
        claim = _GAP_TO_CLAIM.get(gap, "policy")
        if claim in seen_claims and claim not in {"condition", "exception", "rule_object", "value", "operator"}:
            continue
        if claim in {"condition", "exception", "rule_object", "value", "operator"}:
            # Existing field node already carries the human-facing claim. Keep a
            # separate gap node only for policy/shape/matrix-specific semantics.
            if gap not in {
                "allowance_trigger_threshold",
                "definition_not_rule",
                "value_bound_to_foreign_unit",
                "cross_family_value_collision",
                "rule_family_direction_mismatch",
                "anchored_row_family_mismatch",
            }:
                continue
        nodes.append(_gap_node(gap, claim))

    decision_id = "decision"
    nodes.append(
        {
            "id": decision_id,
            "type": "decision",
            "claim": "final_decision",
            "status": decision,
            "severity": "decision",
            "source": "decision_policy",
            "gap_codes": support_gaps,
            "reason": _decision_reason(decision, support_gaps),
            "evidence_field": "",
            "evidence_quote": "",
        }
    )

    edges = [
        {"from": node["id"], "to": decision_id, "relation": "feeds_decision"}
        for node in nodes
        if node["id"] != decision_id
    ]

    return {
        "schema_version": "1.0",
        "candidate_id": str(candidate.get("candidate_id") or candidate.get("source_rule_id") or ""),
        "evidence_id": str(candidate.get("evidence_id") or ""),
        "decision": decision,
        "support_gap_count": len(support_gaps),
        "status_counts": _status_counts(nodes),
        "nodes": nodes,
        "edges": edges,
        "legacy_support_checks": dict(support_checks),
    }


def _node_from_trace(claim: str, trace_item: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    label = trace_item.get("label")
    status = _LABEL_TO_STATUS.get(str(label), STATUS_NA)
    if claim in {"applies_to", "condition", "exception"} and not candidate.get(claim):
        status = STATUS_NA
    return {
        "id": f"claim:{claim}",
        "type": "claim",
        "claim": claim,
        "status": status,
        "severity": "required" if claim not in {"condition", "exception"} else "conditional",
        "source": "proof_trace",
        "gap_codes": [],
        "reason": str(trace_item.get("reason") or _default_reason(claim, status)),
        "evidence_field": str(trace_item.get("evidence_field") or ""),
        "evidence_quote": str(trace_item.get("evidence_quote") or "")[:500],
    }


def _matrix_node(matrix_binding: dict[str, Any] | None, gaps: list[str]) -> dict[str, Any]:
    binding = matrix_binding or {}
    if "column_value_mismatch" in gaps:
        status = STATUS_REFUTED
    elif gaps:
        status = STATUS_NEI
    elif binding.get("supports_column"):
        status = STATUS_SUPPORTED
    else:
        status = STATUS_NA
    return {
        "id": "claim:applicability",
        "type": "claim",
        "claim": "applicability",
        "status": status,
        "severity": "required",
        "source": "matrix_column_binding",
        "gap_codes": gaps,
        "reason": _matrix_reason(status, gaps),
        "evidence_field": "matrix_anchor",
        "evidence_quote": ", ".join(str(key) for key in binding.get("claimed_bands") or []),
    }


def _gap_node(gap: str, claim: str) -> dict[str, Any]:
    status = STATUS_REFUTED if gap in CRITICAL_REJECTION_GAPS else STATUS_NEI
    if gap in NOT_USED_GAPS:
        status = STATUS_NA
    return {
        "id": f"gap:{gap}",
        "type": "gap",
        "claim": claim,
        "status": status,
        "severity": _gap_severity(gap),
        "source": "support_gap",
        "gap_codes": [gap],
        "reason": gap.replace("_", " "),
        "evidence_field": "",
        "evidence_quote": "",
    }


def _gap_severity(gap: str) -> str:
    if gap in CRITICAL_REJECTION_GAPS:
        return "critical"
    if gap in NOT_USED_GAPS:
        return "contract"
    return "review"


def _matrix_reason(status: str, gaps: list[str]) -> str:
    if gaps:
        return "; ".join(gap.replace("_", " ") for gap in gaps)
    if status == STATUS_SUPPORTED:
        return "candidate selector matched a source table band that holds the value"
    return "matrix binding was not applicable"


def _default_reason(claim: str, status: str) -> str:
    if status == STATUS_SUPPORTED:
        return f"{claim} is supported"
    if status == STATUS_REFUTED:
        return f"{claim} is refuted"
    if status == STATUS_NEI:
        return f"{claim} needs more evidence"
    return f"{claim} is not applicable"


def _decision_reason(decision: str, support_gaps: list[str]) -> str:
    if not support_gaps:
        return "all required proof gates passed"
    if any(gap in CRITICAL_REJECTION_GAPS for gap in support_gaps):
        return "at least one critical proof gate was refuted"
    if any(gap in NOT_USED_GAPS for gap in support_gaps):
        return "candidate is outside the verifier contract"
    return "one or more required proof gates need review"


def _status_counts(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {STATUS_SUPPORTED: 0, STATUS_REFUTED: 0, STATUS_NEI: 0, STATUS_NA: 0}
    for node in nodes:
        status = str(node.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts
