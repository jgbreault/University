"""Deterministic packets for the dashboard review assistant.

Packets are bounded, source-grounded context for humans and optional LLM chat.
They are advisory artifacts only; no verifier or GIS code reads them.
"""

from __future__ import annotations

from typing import Any


_MAX_CONTEXT_CHARS = 900


def build_review_assistant_packets(
    review_rules: list[dict[str, Any]],
    evidence_units: list[dict[str, Any]],
    source_repair_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_by_id = {str(unit.get("evidence_id") or ""): unit for unit in evidence_units}
    repair_by_id = {
        str(item.get("evidence_id") or ""): item
        for item in (source_repair_report or {}).get("items", [])
    }
    packets = [_packet(rule, evidence_by_id, repair_by_id) for rule in review_rules]
    return {
        "purpose": "Bounded advisory packets for dashboard review and optional LLM chat. Not a verification input.",
        "advisory_only": True,
        "packet_count": len(packets),
        "items": packets,
    }


def _packet(
    rule: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
    repair_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    candidate = rule.get("candidate", {}) if isinstance(rule.get("candidate"), dict) else {}
    evidence_id = str(source.get("evidence_id") or candidate.get("evidence_id") or "")
    evidence = evidence_by_id.get(evidence_id, {})
    repair = repair_by_id.get(evidence_id, {})
    original = str(evidence.get("evidence_text") or source.get("evidence_text") or "")
    repaired = str(evidence.get("source_context") or "")
    packet = {
        "rule_id": rule.get("rule_id"),
        "candidate_id": candidate.get("candidate_id"),
        "advisory_only": True,
        "candidate_rule": {
            "rule_object": rule.get("rule_object"),
            "constraint_scope": rule.get("constraint_scope"),
            "applies_to": rule.get("applies_to"),
            "operator": rule.get("operator"),
            "value": rule.get("value"),
            "unit": rule.get("unit"),
            "condition": rule.get("condition"),
            "exception": rule.get("exception"),
        },
        "support_gaps": list(rule.get("support_gaps", [])),
        "review_category": rule.get("review_category"),
        "suggested_next_action": _suggested_action(rule),
        "source": {
            "page": source.get("page") or evidence.get("page"),
            "evidence_id": evidence_id,
            "original_evidence": _bounded(original),
            "repaired_context": _bounded(repaired),
            "repair_status": repair.get("status") or (evidence.get("source_repair") or {}).get("status"),
            "repair_actions": repair.get("actions") or (evidence.get("source_repair") or {}).get("actions", []),
        },
        "p9_provenance": candidate.get("p9_provenance") or evidence.get("p9_provenance"),
    }
    packet["llm_context"] = _llm_context(packet)
    return packet


def _suggested_action(rule: dict[str, Any]) -> str:
    gaps = set(rule.get("support_gaps", []))
    if "rag_context_mismatch" in gaps or "source_evidence_id_not_found" in gaps:
        return "Find source text on the correct page before rerunning verification."
    if "operator_not_supported" in gaps:
        return "Look for an operator in parent heading or lead-in text: minimum, maximum, required, permitted, or prohibited."
    if "applies_to_not_supported" in gaps:
        return "Find source text naming the target building/use or table row/column that supplies applies_to."
    if "constraint_scope_not_supported" in gaps:
        return "Find source text naming the exact yard, lot line, parcel condition, or scope."
    if "text_condition_not_supported" in gaps:
        return "Check nearby clauses for conditions or exceptions before any verifier rerun."
    if "text_candidate_requires_review" in gaps:
        return "Find a second independent source or stronger source context; do not approve from one weak text block."
    return "Human review should inspect the cited source and keep the rule out of GIS unless deterministic verification passes."


def _llm_context(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": (
            "Advisory only. Explain why this rule is in review and what source evidence "
            "would be needed. Do not approve, verify, or rewrite GIS outputs."
        ),
        "rule": packet["candidate_rule"],
        "support_gaps": packet["support_gaps"],
        "original_evidence": packet["source"]["original_evidence"],
        "repaired_context": packet["source"]["repaired_context"],
        "suggested_next_action": packet["suggested_next_action"],
    }


def _bounded(value: Any, *, limit: int = _MAX_CONTEXT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
