"""Proof-trace helpers for verifier outputs.

The verifier decides from support gaps.  This module only turns those checks
into readable claim labels, review reasons, and diagnostics so humans can audit
the decision.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import text_words, unresolved_exception_cues
from .rule_claims import (
    NOT_ENOUGH_INFO,
    REFUTED,
    SUPPORTED,
    proof,
    verification_label_from_gaps,
)


TABLE_EVIDENCE_TYPES = {"table_row", "table_cell"}

CLAIM_TO_SUPPORT_GAP = {
    "rule_object": "rule_object_not_supported",
    "constraint_scope": "constraint_scope_not_supported",
    "applies_to": "applies_to_not_supported",
    "operator": "operator_not_supported",
    "value": "value_not_found_in_evidence",
    "unit": "unit_not_found_in_evidence",
}


def human_reason(support_gaps: list[str]) -> str:
    """Convert machine gap codes into readable review reasons."""
    if not support_gaps:
        return "all critical evidence checks passed"
    labels = {
        "source_evidence_id_not_found": "the candidate cites evidence that is missing",
        "value_not_found_in_evidence": "the proposed value is not visible in the cited evidence",
        "unit_not_found_in_evidence": "the proposed unit is not visible in the cited evidence",
        "operator_not_supported": "the proposed operator is not supported by the cited wording",
        "applies_to_not_supported": "the applies_to field is not clearly grounded",
        "constraint_scope_not_supported": "the scope or condition is not clearly grounded",
        "rule_object_not_canonical": "the rule object is outside the verifier's known contract",
        "rule_object_not_supported": "the cited evidence does not support the proposed rule object",
        "rule_object_unit_not_compatible": "the unit is not compatible with the proposed rule object",
        "table_operator_refuted": "the table wording supports the opposite operator direction",
        "table_rule_object_not_supported": "the table context does not support the rule object",
        "table_applies_to_not_supported": "the table row or column does not support applies_to",
        "table_condition_not_supported": "the table row or column does not support the condition",
        "table_column_not_target_scope": "the table column does not match the configured target scope",
        "upstream_extraction_requested_review": "the extraction layer marked this candidate for review",
        "non_numeric_value_for_numeric_rule": "the candidate has a text value for a numeric GIS rule family",
        "unresolved_exception_cue": "the evidence contains exception or override wording that needs review",
        "text_candidate_requires_review": "Text rules are held for review until they pass the GIS text-rule contract (value/unit/operator/scope/direction)",
        "text_condition_not_supported": "the cited text does not support a material condition needed for text-rule verification",
        "cross_reference_only": "the candidate is a bylaw section cross-reference, not a directly validated rule",
        "outside_current_rule_contract": "the rule family is outside the current validation contract",
        "outside_target_section": "the source section is outside the configured target sections for this verification run",
        "definition_not_rule": "the value sits inside a defined-term sentence, which defines vocabulary rather than a rule",
        "column_value_mismatch": "the claimed table column does not hold this value — it belongs to a different column",
        "applicability_not_grounded": "the claimed dwelling-type/unit-count column cannot be found in the table",
        "column_qualifier_not_claimed": "the table column carries a qualifier (e.g. Frequent Transit Network Area) the rule does not claim",
        "conditional_cell_condition_missing": "the table cell is conditional (e.g. by lot size) and the rule does not claim its branch condition",
        "anchored_row_family_mismatch": "the table row this cell belongs to regulates a different rule family",
        "enumerated_branch_condition_missing": "the clause lists several values by condition (e.g. side vs rear) and the rule does not prove which branch its value belongs to",
        "allowance_trigger_threshold": "the value is the trigger of a 'no maximum/minimum ... where' allowance, not a requirement",
        "value_bound_to_foreign_unit": "every visible occurrence of the value is glued to a unit from a different rule family",
        "coefficient_operand_not_value": "the value is a ratio coefficient (e.g. 0.25 multiplied by the site area), not an absolute cap",
        "range_bound_not_maximum": "the value is one range bound (e.g. 1 to 3) while a higher range is listed — not the overall maximum",
    }
    return "; ".join(labels.get(gap, gap.replace("_", " ")) for gap in support_gaps)


def text_proof_trace(
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None,
    support_checks: dict[str, bool],
    support_gaps: list[str],
    support_text: str,
) -> dict[str, dict[str, Any]]:
    """Build claim-level proof from deterministic support checks."""
    source_field = "evidence_text"
    if evidence and evidence.get("evidence_type") in TABLE_EVIDENCE_TYPES:
        source_field = "table/evidence_text"

    return {
        "rule_object": _claim_from_check(
            support_checks["rule_object_supported"],
            False,
            source_field,
            support_text,
            "cited evidence supports the canonical rule object",
            "cited evidence does not support the canonical rule object",
        ),
        "constraint_scope": _claim_from_check(
            support_checks["scope_supported"],
            False,
            source_field,
            support_text,
            "scope words are grounded in local evidence",
            "scope words are not grounded in local evidence",
        ),
        "applies_to": _claim_from_check(
            support_checks["applies_to_supported"],
            False,
            source_field,
            support_text,
            "applies_to words are grounded in local evidence",
            "applies_to words are not grounded in local evidence",
            optional=not candidate.get("applies_to"),
        ),
        "operator": _claim_from_check(
            support_checks["operator_supported"],
            False,
            source_field,
            support_text,
            "operator wording is supported by evidence",
            "operator wording is not supported by evidence",
        ),
        "value": _claim_from_check(
            support_checks["value_supported"],
            "value_not_found_in_evidence" in support_gaps,
            source_field,
            support_text,
            "value appears in cited evidence",
            "value is absent from cited evidence",
            optional=candidate.get("value") in (None, ""),
        ),
        "unit": _claim_from_check(
            support_checks["unit_supported"],
            "unit_not_found_in_evidence" in support_gaps or "rule_object_unit_not_compatible" in support_gaps,
            source_field,
            support_text,
            "unit appears in cited evidence and is compatible",
            "unit is absent from evidence or incompatible with rule object",
            optional=candidate.get("unit") in (None, ""),
        ),
        "condition": _prove_optional_text_claim(candidate.get("condition"), support_text, "condition"),
        "exception": _prove_optional_text_claim(candidate.get("exception"), support_text, "exception"),
    }


def claim_supported(trace: dict[str, dict[str, Any]], claim: str) -> bool:
    """Return whether a proof trace explicitly supports one claim."""
    return trace.get(claim, {}).get("label") == SUPPORTED


def claim_refuted(trace: dict[str, dict[str, Any]], claim: str) -> bool:
    """Return whether a proof trace explicitly refutes one claim."""
    return trace.get(claim, {}).get("label") == REFUTED


def apply_table_trace_to_support_checks(
    table_trace: dict[str, dict[str, Any]],
    support_checks: dict[str, bool],
) -> dict[str, bool]:
    """Let table proof update exactly the corresponding support check."""
    updated = dict(support_checks)
    claim_to_check = {
        "rule_object": "rule_object_supported",
        "constraint_scope": "scope_supported",
        "applies_to": "applies_to_supported",
        "operator": "operator_supported",
        "value": "value_supported",
        "unit": "unit_supported",
    }
    for claim, check_name in claim_to_check.items():
        if claim_supported(table_trace, claim):
            updated[check_name] = True
        elif claim_refuted(table_trace, claim):
            updated[check_name] = False
    return updated


def repair_table_context_gaps(
    table_context_gaps: list[str],
    table_trace: dict[str, dict[str, Any]],
) -> list[str]:
    """Remove table context gaps only when table proof supports that claim."""
    repaired = list(table_context_gaps)
    if claim_supported(table_trace, "rule_object"):
        repaired = [gap for gap in repaired if gap != "table_rule_object_not_supported"]
    if claim_supported(table_trace, "applies_to"):
        repaired = [gap for gap in repaired if gap != "table_applies_to_not_supported"]
    if claim_supported(table_trace, "condition"):
        repaired = [gap for gap in repaired if gap != "table_condition_not_supported"]
    return repaired


def table_refutation_gaps(table_trace: dict[str, dict[str, Any]]) -> list[str]:
    """Convert table proof refutations into explicit support gaps."""
    gaps: list[str] = []
    if claim_refuted(table_trace, "operator"):
        gaps.append("table_operator_refuted")
    return gaps


def has_unresolved_exception_cue(
    evidence: dict[str, Any] | None,
    proof_trace: dict[str, dict[str, Any]],
) -> bool:
    """Return True when evidence has exception wording that proof did not solve.

    ``proof_trace`` is whichever trace proved this evidence (table trace for
    table evidence, text-span trace for prose) — previously only the table
    trace was consulted, so prose evidence with unresolved exception wording
    could never trigger this hold ('the ceiling height, excluding roof
    structure, of the total area being excluded does not exceed 3.1 m' — an
    exclusion criterion — verified as a height cap).

    The scan covers the fields the proof actually validated (evidence_text +
    table fields), NOT source_context: context is display/anchoring material,
    and a cue in a NEIGHBORING clause ('...site width is 9.8 m, except that
    the Director may reduce...') says nothing about THIS clause's claims.
    Wide RAG pack context would otherwise hold nearly every prose candidate
    for its neighbors' exceptions. Cue detection is single-sourced in
    domain_schema.unresolved_exception_cues so this gate, the
    bundle-promotion blockers, and the advisory layer can never drift apart.
    """
    if not evidence:
        return False
    exception_label = proof_trace.get("exception", {}).get("label")
    if exception_label != NOT_ENOUGH_INFO:
        return False
    evidence_text = " ".join(
        str(evidence.get(key) or "")
        for key in ("table_title", "row_header", "column_header", "cell_value", "evidence_text")
    )
    return bool(unresolved_exception_cues(evidence_text))


def proof_decision_mismatches(
    proof_trace: dict[str, dict[str, Any]],
    support_gaps: list[str],
) -> list[dict[str, str]]:
    """Find contradictions between proof labels and final support gaps."""
    gaps = set(support_gaps)
    mismatches: list[dict[str, str]] = []
    for claim, gap in CLAIM_TO_SUPPORT_GAP.items():
        label = proof_trace.get(claim, {}).get("label")
        if label == SUPPORTED and gap in gaps:
            mismatches.append({"claim": claim, "label": label, "gap": gap, "type": "supported_but_gap_present"})
        elif label == REFUTED and gap not in gaps:
            mismatches.append({"claim": claim, "label": label, "gap": gap, "type": "refuted_without_gap"})
    return mismatches


def align_proof_trace_with_decision(
    proof_trace: dict[str, dict[str, Any]],
    support_checks: dict[str, bool],
    support_gaps: list[str],
) -> dict[str, dict[str, Any]]:
    """Make the merged public proof trace agree with final support gaps."""
    aligned = {claim: dict(item) for claim, item in proof_trace.items()}
    gaps = set(support_gaps)
    claim_to_check = {
        "rule_object": "rule_object_supported",
        "constraint_scope": "scope_supported",
        "applies_to": "applies_to_supported",
        "operator": "operator_supported",
        "value": "value_supported",
        "unit": "unit_supported",
    }
    for claim, gap in CLAIM_TO_SUPPORT_GAP.items():
        item = aligned.get(claim)
        if not item:
            continue
        if gap in gaps and item.get("label") == SUPPORTED:
            item["label"] = verification_label_from_gaps([gap])
            item["reason"] = f"final support gap remains: {gap}"
            item["decision_gap"] = gap
        elif (
            gap not in gaps
            and item.get("label") == REFUTED
            and support_checks.get(claim_to_check.get(claim, ""), False)
        ):
            item["label"] = SUPPORTED
            item["reason"] = "final deterministic support check passed"
            item.pop("decision_gap", None)
        aligned[claim] = item
    return aligned


def _claim_from_check(
    passed: bool,
    refuted: bool,
    evidence_field: str,
    evidence_quote: str,
    supported_reason: str,
    failed_reason: str,
    *,
    optional: bool = False,
) -> dict[str, Any]:
    """Convert one boolean support check into a proof label."""
    if optional:
        return proof(SUPPORTED, reason="candidate has no explicit claim")
    if passed:
        return proof(SUPPORTED, evidence_field=evidence_field, evidence_quote=_short_quote(evidence_quote), reason=supported_reason)
    if refuted:
        return proof(REFUTED, evidence_field=evidence_field, evidence_quote=_short_quote(evidence_quote), reason=failed_reason)
    return proof(NOT_ENOUGH_INFO, evidence_field=evidence_field, evidence_quote=_short_quote(evidence_quote), reason=failed_reason)


def _prove_optional_text_claim(value: Any, evidence_text: str, claim_name: str) -> dict[str, Any]:
    """Prove optional condition/exception claims when they are present."""
    if value in (None, ""):
        return proof(SUPPORTED, reason=f"candidate has no explicit {claim_name} claim")
    claim_words = text_words(str(value)) - {"the", "and", "for", "with"}
    evidence_words = text_words(evidence_text)
    if claim_words and claim_words & evidence_words:
        return proof(SUPPORTED, evidence_field="evidence_text", evidence_quote=_short_quote(evidence_text), reason=f"{claim_name} words appear in evidence")
    return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(evidence_text), reason=f"{claim_name} words are not fully grounded")


def _short_quote(value: Any, limit: int = 240) -> str:
    """Keep proof_trace readable by trimming long source snippets."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
