"""Safe verifier-tuning candidates from the review audit.

This module turns the broad review audit into a concrete engineering backlog.
It does not change verification decisions. Its job is to say which review rules
look suitable for a general verifier improvement, what kind of improvement to
test, and which guardrails must stay in place.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


SAFE_TUNING_ACTION = "safe_verifier_tuning_candidate"


def build_safe_tuning_report(
    review_rules: list[dict[str, Any]],
    review_audit_report: dict[str, Any],
    evidence_rerun_report: dict[str, Any],
) -> dict[str, Any]:
    """Return verifier-tuning candidates without promoting any rule.

    A tuning candidate means "inspect this pattern and add a general rule only
    if tests/benchmark prove it safe." It never means "relax the verifier for
    this specific Burnaby rule."
    """
    rules_by_id = {str(rule.get("rule_id") or ""): rule for rule in review_rules}
    reruns_by_rule_id = _best_reruns_by_rule_id(evidence_rerun_report.get("attempts", []))
    items: list[dict[str, Any]] = []

    for audit_item in review_audit_report.get("items", []):
        if audit_item.get("action_bucket") != SAFE_TUNING_ACTION:
            continue
        rule_id = str(audit_item.get("rule_id") or "")
        rule = rules_by_id.get(rule_id, {})
        gaps = list(audit_item.get("support_gaps") or rule.get("support_gaps", []))
        tuning_type = _tuning_type(gaps)
        rerun = reruns_by_rule_id.get(rule_id, {})
        source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
        items.append(
            {
                "rule_id": rule_id,
                "candidate_id": rule.get("candidate", {}).get("candidate_id") or audit_item.get("candidate_id"),
                "rule_object": audit_item.get("rule_object") or rule.get("rule_object"),
                "constraint_scope": audit_item.get("constraint_scope") or rule.get("constraint_scope"),
                "applies_to": audit_item.get("applies_to") or rule.get("applies_to"),
                "operator": audit_item.get("operator") or rule.get("operator"),
                "value": audit_item.get("value") or rule.get("value"),
                "unit": audit_item.get("unit") or rule.get("unit"),
                "condition": audit_item.get("condition") or rule.get("condition"),
                "support_gaps": gaps,
                "review_category": audit_item.get("review_category"),
                "likely_status": audit_item.get("likely_status"),
                "likely_correct_score": audit_item.get("likely_correct_score"),
                "tuning_type": tuning_type,
                "proposed_experiment": _proposed_experiment(tuning_type),
                "required_tests": _required_tests(tuning_type),
                "guardrails": _guardrails(tuning_type),
                "source_page": source.get("page"),
                "evidence_id": source.get("evidence_id"),
                "evidence_quote": source.get("evidence_text"),
                "rerun_decision": rerun.get("retry_decision"),
                "rerun_promotion_ready": rerun.get("promotion_ready"),
                "rerun_evidence_id": rerun.get("retry_evidence_id"),
                "rerun_support_gaps": list(rerun.get("retry_support_gaps", [])),
                "status": "design_candidate_only",
            }
        )

    counts = Counter(item["tuning_type"] for item in items)
    return {
        "mode": "safe_verifier_tuning_backlog",
        "candidate_count": len(items),
        "tuning_type_counts": [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        "items": items,
        "notes": [
            "This report does not promote review rules.",
            "Each tuning candidate requires a general implementation plus benchmark/adversarial validation.",
            "Evidence confidence or semantic similarity cannot override value/unit/operator/source support.",
        ],
    }


def safe_tuning_markdown(report: dict[str, Any], *, limit: int = 25) -> str:
    """Render a compact markdown report for verifier-tuning candidates."""
    lines = [
        "# Safe Verifier Tuning Candidates",
        "",
        "These are review rules that may justify a general verifier improvement. They are not automatically verified.",
        "",
        f"- Candidates: {report.get('candidate_count', 0)}",
        "",
        "## Tuning Types",
        "",
    ]
    for item in report.get("tuning_type_counts", []):
        lines.append(f"- `{item['name']}`: {item['count']}")
    lines.extend(["", f"## Top {limit}", ""])
    for item in report.get("items", [])[:limit]:
        lines.append(
            f"- `{item['rule_id']}` type=`{item['tuning_type']}` "
            f"gaps={', '.join(item.get('support_gaps', [])) or 'none'}"
        )
    return "\n".join(lines) + "\n"


def _best_reruns_by_rule_id(attempts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Pick the most useful rerun result for each original rule id."""
    best: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        rule_id = str(attempt.get("original_rule_id") or "")
        if not rule_id:
            continue
        current = best.get(rule_id)
        if current is None or _rerun_rank(attempt) > _rerun_rank(current):
            best[rule_id] = attempt
    return best


def _rerun_rank(attempt: dict[str, Any]) -> tuple[int, float]:
    if attempt.get("promotion_ready"):
        status_rank = 3
    elif attempt.get("retry_decision") == "verified":
        status_rank = 2
    elif attempt.get("retry_decision") == "review_needed":
        status_rank = 1
    else:
        status_rank = 0
    confidence = attempt.get("best_repair_confidence")
    return status_rank, float(confidence) if isinstance(confidence, (int, float)) else 0.0


def _tuning_type(gaps: list[str]) -> str:
    gap_set = set(gaps)
    if gap_set & {"table_cell_candidate_requires_review", "table_evidence_candidate_requires_review"}:
        return "structured_table_gate"
    if gap_set & {"operator_not_supported", "table_operator_refuted"}:
        return "operator_cue_expansion"
    if gap_set & {"applies_to_not_supported", "table_applies_to_not_supported"}:
        return "applies_to_scope_matching"
    if gap_set & {"constraint_scope_not_supported", "table_column_not_target_scope"}:
        return "scope_context_matching"
    if gap_set & {"text_condition_not_supported", "table_condition_not_supported"}:
        return "condition_context_matching"
    return "general_support_gap"


def _proposed_experiment(tuning_type: str) -> str:
    experiments = {
        "structured_table_gate": "Allow a table candidate only when title, row/column, cell value, unit, and configured scope pattern all pass.",
        "operator_cue_expansion": "Add missing legal wording cues for min/max/required operators and test opposite-direction refutations.",
        "applies_to_scope_matching": "Improve token/alias matching for applies_to without accepting generic one-word overlaps.",
        "scope_context_matching": "Use local value windows plus table row/column context to prove scope more precisely.",
        "condition_context_matching": "Model conditions such as roof type, covenant, exception, and unit-count qualifiers as explicit claims.",
        "general_support_gap": "Inspect manually and convert only repeated, city-agnostic patterns into verifier logic.",
    }
    return experiments.get(tuning_type, experiments["general_support_gap"])


def _required_tests(tuning_type: str) -> list[str]:
    common = [
        "run unit tests",
        "run benchmark/evaluate_benchmark.py",
        "run benchmark/evaluate_adversarial.py",
        "confirm false_verified_count stays 0",
    ]
    extra = {
        "structured_table_gate": ["add positive and negative table-cell tests"],
        "operator_cue_expansion": ["add operator direction mismatch tests"],
        "applies_to_scope_matching": ["add wrong-applies-to negative tests"],
        "scope_context_matching": ["add multi-number local-window tests"],
        "condition_context_matching": ["add unresolved-exception and condition tests"],
    }
    return [*common, *extra.get(tuning_type, [])]


def _guardrails(tuning_type: str) -> list[str]:
    guardrails = [
        "do not verify if value is absent from cited evidence",
        "do not verify if unit is absent or incompatible",
        "do not verify if evidence contains unresolved exception wording",
        "do not use similarity or confidence as a verification override",
    ]
    if tuning_type == "structured_table_gate":
        guardrails.append("do not use table cell value without row/column/table-title support")
    if tuning_type == "operator_cue_expansion":
        guardrails.append("reject or review when evidence implies the opposite operator")
    if tuning_type in {"applies_to_scope_matching", "scope_context_matching"}:
        guardrails.append("require local evidence near the target value, not whole-page context")
    return guardrails
