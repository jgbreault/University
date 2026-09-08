"""Unified review routing for non-verified rules.

Older outputs split review intelligence into triage, evidence repair, and audit
reports.  This module joins those views into one reviewer-facing route per rule.
It does not change verification decisions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .domain_schema import text_words, unresolved_exception_cues
from .review_text import candidate_sentence, count_lines, counter_rows, evidence_sentence


def build_review_router(
    review_rules: list[dict[str, Any]],
    *,
    triage_report: dict[str, Any],
    audit_report: dict[str, Any],
    evidence_repair_report: dict[str, Any],
    evidence_rerun_report: dict[str, Any],
    evidence_intelligence_report: dict[str, Any] | None = None,
    evidence_bundle_rerun_report: dict[str, Any] | None = None,
    semantic_review_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one consolidated route per review rule."""
    triage_by_id = _items_by_id(triage_report, "items")
    audit_by_id = _items_by_id(audit_report, "items")
    repair_by_id = _items_by_id(evidence_repair_report, "suggestions")
    intelligence_by_id = _items_by_id(evidence_intelligence_report or {}, "items")
    semantic_by_id = _items_by_id(semantic_review_report or {}, "items")
    rerun_by_id = {
        str(item.get("original_rule_id") or ""): item
        for item in evidence_rerun_report.get("attempts", [])
    }
    bundle_rerun_by_id = {
        str(item.get("original_rule_id") or ""): item
        for item in (evidence_bundle_rerun_report or {}).get("attempts", [])
    }

    items = [
        _router_item(
            rule,
            triage_by_id.get(str(rule.get("rule_id") or ""), {}),
            audit_by_id.get(str(rule.get("rule_id") or ""), {}),
            repair_by_id.get(str(rule.get("rule_id") or ""), {}),
            rerun_by_id.get(str(rule.get("rule_id") or ""), {}),
            intelligence_by_id.get(str(rule.get("rule_id") or ""), {}),
            bundle_rerun_by_id.get(str(rule.get("rule_id") or ""), {}),
            semantic_by_id.get(str(rule.get("rule_id") or ""), {}),
        )
        for rule in review_rules
    ]
    items.sort(key=lambda item: (item["priority_rank"], item["rule_id"]))

    category_counts = Counter(item["review_category"] for item in items)
    action_counts = Counter(item["action_bucket"] for item in items)
    priority_counts = Counter(item["priority"] for item in items)
    likelihood_counts = Counter(item["likely_status"] for item in items)
    semantic_counts = Counter(item["semantic_review_class"] for item in items)
    return {
        "purpose": "Single reviewer-facing queue. Advisory only; verification decisions remain in verified/review/rejected/not_used outputs.",
        "review_rule_count": len(items),
        "items": items,
        "summary": {
            "category_counts": counter_rows(category_counts),
            "action_counts": counter_rows(action_counts),
            "priority_counts": counter_rows(priority_counts),
            "likelihood_counts": counter_rows(likelihood_counts),
            "semantic_review_counts": counter_rows(semantic_counts),
            # top_support_gaps histograms the raw support_gaps; top_blocking_reasons
            # histograms the human-facing blocking_reason labels. They used to be
            # the same gap histogram published under two names.
            "top_blocking_reasons": _top_blocking_reasons(items),
            "top_support_gaps": _top_support_gaps(items),
            "action_descriptions": ACTION_DESCRIPTIONS,
            "recommendations": _recommendations(items),
        },
    }


def review_router_markdown(report: dict[str, Any], *, limit: int = 25) -> str:
    """Render a concise reviewer guide from the unified router."""
    lines = [
        "# Review Router",
        "",
        "This file consolidates triage, evidence repair, and audit into one review queue. It does not verify rules.",
        "",
        "## Summary",
        "",
        f"- Review rules: {report.get('review_rule_count', 0)}",
        "",
        "### Action Buckets",
        "",
        *count_lines(report.get("summary", {}).get("action_counts", [])),
        "",
        "### Likelihood",
        "",
        *count_lines(report.get("summary", {}).get("likelihood_counts", [])),
        "",
        "### Top Support Gaps",
        "",
        *count_lines(report.get("summary", {}).get("top_support_gaps", [])),
        "",
        "### Recommendations",
        "",
        *(
            [f"- {item}" for item in report.get("summary", {}).get("recommendations", [])]
            or ["- No immediate recommendation."]
        ),
        "",
        f"## Top {limit} Review Routes",
        "",
    ]
    for item in report.get("items", [])[:limit]:
        lines.append(
            f"- `{item['rule_id']}` -> `{item['action_bucket']}` / `{item['priority']}`: "
            f"{item['human_instruction']}"
        )
    return "\n".join(lines) + "\n"


def _router_item(
    rule: dict[str, Any],
    triage: dict[str, Any],
    audit: dict[str, Any],
    repair: dict[str, Any],
    rerun: dict[str, Any],
    intelligence: dict[str, Any],
    bundle_rerun: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    # The decision tree is AUTHORITATIVE for routing: every branch of
    # _decision_tree_route returns a non-empty category/action/next_step, so the
    # older audit/triage fallbacks here were dead code (a merge artifact from
    # when triage, audit, and router were separate modules). action_reason is
    # derived from the chosen route so it can never contradict action_bucket.
    route = _decision_tree_route(rule, intelligence, bundle_rerun, semantic)
    priority = (
        audit.get("triage_priority")
        or triage.get("triage_priority")
        or rule.get("triage_priority")
        or rule.get("review_priority")
        or "low"
    )
    review_rank = int(audit.get("review_rank") or triage.get("review_rank") or rule.get("review_rank") or 999)
    top_repair = _top_repair(repair)
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "candidate_id": str(rule.get("candidate", {}).get("candidate_id") or ""),
        "decision": rule.get("verification_decision"),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "source_evidence_id": source.get("evidence_id"),
        "review_category": route["review_category"],
        "likely_status": triage.get("likely_status") or rule.get("likely_status") or "unknown",
        "priority": priority,
        "triage_priority": priority,
        "review_rank": review_rank,
        "priority_rank": _priority_rank(priority, review_rank),
        "action_bucket": route["action_bucket"],
        "action_reason": _route_action_reason(route),
        "next_action": route["next_action"],
        "next_step": route["next_step"],
        "human_instruction": _human_instruction(rule, source, repair, intelligence, route, semantic),
        "candidate_sentence": candidate_sentence(rule),
        "evidence_sentence": evidence_sentence(source),
        "bundle_sentence": intelligence.get("bundle_sentence") or "No evidence bundle suggestion is available.",
        "decision_path": route["decision_path"],
        "where_to_find_it": _where_to_find_it(source),
        "support_gaps": list(rule.get("support_gaps", [])),
        "likely_correct_score": float(triage.get("likely_correct_score") or rule.get("likely_correct_score") or 0.0),
        "blocking_reason": triage.get("blocking_reason") or rule.get("blocking_reason") or _blocking_reason(rule),
        "suggested_fix": triage.get("suggested_fix") or rule.get("suggested_fix") or "Inspect proof trace and support gaps.",
        "potential_mistake_flags": list(triage.get("potential_mistake_flags") or rule.get("potential_mistake_flags") or []),
        "similar_verified_rule_id": triage.get("similar_verified_rule_id") or rule.get("similar_verified_rule_id"),
        "similar_verified_score": float(triage.get("similar_verified_score") or rule.get("similar_verified_score") or 0.0),
        "best_repair_evidence_id": top_repair.get("evidence_id"),
        "best_repair_confidence": float(repair.get("best_repair_confidence") or 0.0),
        "can_retry_verification": bool(repair.get("can_retry_verification")),
        "repairable_fields": list(repair.get("repairable_fields", [])),
        "rerun_decision": rerun.get("retry_decision"),
        "rerun_promotion_ready": rerun.get("promotion_ready"),
        "bundle_score": intelligence.get("bundle_score"),
        "bundle_safe_retry": intelligence.get("safe_retry"),
        "bundle_missing_fields": list(intelligence.get("bundle_missing_fields", [])),
        "bundle_rerun_decision": bundle_rerun.get("retry_decision"),
        "bundle_rerun_promotion_ready": bundle_rerun.get("promotion_ready"),
        "semantic_review_class": _semantic_review_class(semantic),
        "semantic_verified_rule_id": _semantic_top_match(semantic).get("verified_rule_id"),
        "semantic_score": _semantic_score_value(semantic),
        "semantic_structured_score": semantic.get("best_structured_score"),
        "semantic_embedding_score": semantic.get("best_embedding_score"),
        "semantic_match_type": semantic.get("semantic_match_type"),
        "semantic_next_action": semantic.get("semantic_next_action"),
        "semantic_guardrail_blockers": list(semantic.get("semantic_guardrail_blockers", [])),
    }


def _items_by_id(report: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    return {str(item.get("rule_id") or ""): item for item in report.get(key, [])}


def _where_to_find_it(source: dict[str, Any]) -> str:
    parts = []
    if source.get("page") is not None:
        parts.append(f"page {source.get('page')}")
    if source.get("source_section"):
        parts.append(f"section {source.get('source_section')}")
    if source.get("source_heading"):
        parts.append(f"heading {source.get('source_heading')}")
    if source.get("evidence_id"):
        parts.append(f"evidence_id {source.get('evidence_id')}")
    return "; ".join(parts) if parts else "Use the evidence_id/source quote in the rule source block."


def _human_instruction(
    rule: dict[str, Any],
    source: dict[str, Any],
    repair: dict[str, Any],
    intelligence: dict[str, Any],
    route: dict[str, Any],
    semantic: dict[str, Any],
) -> str:
    gaps = ", ".join(str(gap) for gap in rule.get("support_gaps", [])[:4]) or "no listed support gaps"
    repair_hint = ""
    if repair.get("can_retry_verification"):
        top = _top_repair(repair)
        repair_hint = f" Suggested stronger evidence: {top.get('evidence_id')}."
    bundle_hint = ""
    if intelligence.get("safe_retry"):
        bundle_hint = " Evidence bundle is safe to rerun through the verifier."
    semantic_hint = ""
    top_semantic = _semantic_top_match(semantic)
    if top_semantic:
        semantic_hint = (
            f" Semantic match: {top_semantic.get('verified_rule_id')} "
            f"(score {_semantic_score_value(semantic):.2f}, blockers "
            f"{', '.join(semantic.get('semantic_guardrail_blockers', [])) or 'none'})."
        )
    # The decision tree always supplies a next_step, so no fallback is needed.
    next_step = route["next_step"]
    return f"{next_step} Check {gaps} in {_where_to_find_it(source)}.{repair_hint}{bundle_hint}{semantic_hint}"


def _decision_tree_route(
    rule: dict[str, Any],
    intelligence: dict[str, Any],
    bundle_rerun: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    """Route one review item through the explicit reviewer decision tree.

    This tree is the authoritative router (older triage/audit buckets are kept
    only as advisory annotations). Branch ORDER is the safety argument: the
    hard legal-meaning problems are checked first — contract membership (1),
    missing core value/unit evidence (2), operator direction (3), wrong rule
    family (4), scope (5), condition (6), exception/covenant wording (7), and
    sibling-family conflicts (8) — before any automation-friendly route such as
    semantic matching (9a/9b) or bundle rerun (9). A later branch can therefore
    never make a rule with an unresolved legal-meaning problem look like an
    easy automated win.
    """
    gaps = set(rule.get("support_gaps", []))
    path: list[str] = []

    if gaps & {"cross_reference_only", "outside_current_rule_contract"}:
        path.append("1:not_used_or_outside_contract")
        return _route("not_used_traceability", "not_used_traceability", "Keep as traceability metadata; do not tune verifier.", path)
    if gaps & {"value_not_found_in_evidence", "unit_not_found_in_evidence"}:
        path.append("2:value_or_unit_missing")
        return _route("better_evidence_needed", _evidence_action(intelligence), "Find direct evidence for the missing value/unit before rerun.", path)
    if gaps & {"operator_not_supported", "table_operator_refuted", "rule_family_direction_mismatch"}:
        path.append("3:operator_missing_or_refuted")
        return _route("operator_review", "operator_review", "Confirm the legal direction: maximum/minimum/required/permitted.", path)
    if gaps & {"rule_object_not_supported", "rule_object_not_canonical", "table_rule_object_not_supported"}:
        path.append("4:rule_family_unsupported")
        return _route("upstream_extraction_issue", "fix_candidate_or_rule_family_mapping", "Check whether extraction chose the wrong rule family.", path)
    if gaps & {"constraint_scope_not_supported", "applies_to_not_supported", "table_applies_to_not_supported", "table_column_not_target_scope"}:
        path.append("5:scope_or_applies_to_missing")
        action = "rerun_with_evidence_bundle" if intelligence.get("safe_retry") else "scope_review"
        return _route("scope_review", action, "Check row/column/header/prose context for the correct legal scope.", path)
    if gaps & {"table_condition_not_supported", "text_condition_not_supported"}:
        path.append("6:condition_missing")
        action = "rerun_with_evidence_bundle" if intelligence.get("safe_retry") else "condition_evidence_needed"
        return _route("condition_evidence_needed", action, "Find the clause or table header that proves the condition.", path)
    if gaps & {"unresolved_exception_cue"} or _has_exception_text(rule, intelligence):
        path.append("7:exception_covenant_notwithstanding")
        return _route("human_legal_review", "human_legal_review", "Resolve exception/covenant/notwithstanding wording manually.", path)
    if gaps & {"cross_family_value_collision"}:
        path.append("8:conflict_or_collision")
        return _route("conflict_review", "conflict_review", "Compare sibling candidates and decide which family owns the value.", path)
    if gaps & {"upstream_extraction_requested_review"}:
        # The extraction layer itself asked for review. Route it explicitly to an
        # upstream-investigation bucket rather than letting it fall through to the
        # generic low-priority deferral, where the upstream signal would be lost.
        path.append("8b:upstream_extraction_requested_review")
        return _route(
            "upstream_extraction_issue",
            "fix_candidate_or_rule_family_mapping",
            "Extraction flagged this candidate for review; investigate and correct it upstream before rerun.",
            path,
        )
    semantic_route = _semantic_route(rule, semantic)
    if semantic_route:
        path.append(semantic_route["path_step"])
        return _route(
            semantic_route["review_category"],
            semantic_route["action_bucket"],
            semantic_route["next_step"],
            path,
        )
    if intelligence.get("safe_retry") or bundle_rerun.get("promotion_ready"):
        path.append("9:bundle_safe_retry_available")
        return _route("almost_verified", "rerun_with_evidence_bundle", "Rerun using the evidence bundle; promote only if deterministic verifier passes.", path)

    path.append("10:defer_low_priority")
    return _route("defer_low_priority", "defer_low_priority", "Keep in review until more evidence or a general verifier rule is justified.", path)


def _route(review_category: str, action_bucket: str, next_step: str, path: list[str]) -> dict[str, Any]:
    return {
        "review_category": review_category,
        "action_bucket": action_bucket,
        "next_action": action_bucket,
        "next_step": next_step,
        "decision_path": path,
    }


def _route_action_reason(route: dict[str, Any]) -> str:
    """Derive the action reason from the authoritative route itself.

    The reason used to be copied from the separate audit report, which could
    disagree with the decision-tree bucket. Deriving it from the chosen route
    makes an action_bucket/action_reason contradiction impossible.
    """
    step = route["decision_path"][-1] if route.get("decision_path") else "unrouted"
    return f"Decision tree step `{step}` routed this to `{route['action_bucket']}`: {route['next_step']}"


def _evidence_action(intelligence: dict[str, Any]) -> str:
    return "rerun_with_evidence_bundle" if intelligence.get("safe_retry") else "better_evidence_needed"


SEMANTIC_HIGH_CONFIDENCE_THRESHOLD = 0.82
SEMANTIC_CLOSE_THRESHOLD = 0.72
SEMANTIC_ROUTABLE_GAPS = {
    "text_candidate_requires_review",
    "table_cell_candidate_requires_review",
    "table_evidence_candidate_requires_review",
    "table_fallback_candidate_requires_review",
}


def _semantic_route(rule: dict[str, Any], semantic: dict[str, Any]) -> dict[str, str] | None:
    """Return an advisory semantic route for close review-vs-verified matches.

    This is deliberately placed after core evidence/operator/scope/condition
    checks. It only helps humans interpret remaining review noise. It does not
    clear any support gap or promote a rule.
    """
    # Guardrail-blocked close matches must be evaluated on the RAW structured/
    # embedding scores, BEFORE the combined-score gate: _combined_score caps any
    # blocked match at 0.71, just under the 0.72 close-match bar, so gating on
    # the combined score first made this branch unreachable. This mirrors
    # semantic_review._semantic_next_action's close_meaning_guardrail_blocked.
    blockers = set(semantic.get("semantic_guardrail_blockers", []))
    if blockers and (
        float(semantic.get("best_structured_score") or 0.0) >= SEMANTIC_CLOSE_THRESHOLD
        or float(semantic.get("best_embedding_score") or 0.0) >= SEMANTIC_HIGH_CONFIDENCE_THRESHOLD
    ):
        return {
            "path_step": "9a:semantic_guardrail_blocked",
            "review_category": "semantic_guardrail_review",
            "action_bucket": ACTION_SEMANTIC_GUARDRAIL_REVIEW,
            "next_step": "Compare the close verified match, but do not relax verification because core legal fields or guardrails disagree.",
        }
    score = _semantic_score_value(semantic)
    if score < SEMANTIC_CLOSE_THRESHOLD:
        return None
    gaps = set(rule.get("support_gaps", []))
    if score >= SEMANTIC_HIGH_CONFIDENCE_THRESHOLD and gaps and gaps <= SEMANTIC_ROUTABLE_GAPS:
        return {
            "path_step": "9b:semantic_near_duplicate",
            "review_category": "semantic_near_duplicate",
            "action_bucket": ACTION_SEMANTIC_DUPLICATE_REVIEW,
            "next_step": "Compare against the verified match; if it is only a duplicate or degraded extraction, keep it out of GIS instead of tuning the verifier.",
        }
    return None


def _semantic_top_match(semantic: dict[str, Any]) -> dict[str, Any]:
    matches = semantic.get("best_verified_matches", [])
    if isinstance(matches, list) and matches:
        return matches[0]
    return {}


def _semantic_score_value(semantic: dict[str, Any]) -> float:
    value = semantic.get("best_combined_semantic_score", semantic.get("best_semantic_score", 0.0))
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _semantic_review_class(semantic: dict[str, Any]) -> str:
    score = _semantic_score_value(semantic)
    blockers = semantic.get("semantic_guardrail_blockers", [])
    if blockers:
        return "close_match_guardrail_blocked" if score >= SEMANTIC_CLOSE_THRESHOLD else "guardrail_blocked_low_similarity"
    if score >= SEMANTIC_HIGH_CONFIDENCE_THRESHOLD:
        return "high_confidence_near_duplicate"
    if score >= SEMANTIC_CLOSE_THRESHOLD:
        return "close_semantic_match"
    return "no_close_semantic_match"


def _has_exception_text(rule: dict[str, Any], intelligence: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(rule.get("condition") or ""),
            str(rule.get("exception") or ""),
            str(intelligence.get("bundle_sentence") or ""),
        ]
    )
    return bool(unresolved_exception_cues(text))


def _top_repair(repair: dict[str, Any]) -> dict[str, Any]:
    top = repair.get("top_evidence", [])
    return top[0] if isinstance(top, list) and top else {}


def _priority_rank(priority: str, existing_rank: Any) -> int:
    try:
        rank = int(existing_rank)
    except (TypeError, ValueError):
        rank = 99
    base = {"high": 0, "medium": 1000, "low": 2000}.get(str(priority), 3000)
    return base + rank


def _top_support_gaps(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in items:
        for gap in item.get("support_gaps", []):
            counts[str(gap)] += 1
    return [{"name": name, "count": count} for name, count in counts.most_common(limit)]


def _top_blocking_reasons(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter(
        str(item.get("blocking_reason") or "") for item in items if item.get("blocking_reason")
    )
    return [{"name": name, "count": count} for name, count in counts.most_common(limit)]


# --- merged from review_triage.py (triage) ---

def build_review_triage(
    review_rules: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return dashboard-ready triage rows and summary counts."""
    items = [_triage_item(rule, verified_rules) for rule in review_rules]
    items.sort(key=lambda item: (item["review_rank"], -item["likely_correct_score"], item["rule_id"]))
    category_counts = Counter(item["review_category"] for item in items)
    likelihood_counts = Counter(item["likely_status"] for item in items)
    priority_counts = Counter(item["triage_priority"] for item in items)
    return {
        "review_rule_count": len(review_rules),
        "items": items,
        "summary": {
            "category_counts": counter_rows(category_counts),
            "likelihood_counts": counter_rows(likelihood_counts),
            "priority_counts": counter_rows(priority_counts),
            "top_blocking_reasons": _top_blocking_reasons(items),
        },
    }

def apply_review_triage(
    review_rules: list[dict[str, Any]],
    triage_report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach triage fields back onto review rules before writing JSON."""
    by_id = {item["rule_id"]: item for item in triage_report.get("items", [])}
    enriched: list[dict[str, Any]] = []
    for rule in review_rules:
        item = by_id.get(str(rule.get("rule_id") or ""))
        if not item:
            enriched.append(rule)
            continue
        updated = dict(rule)
        updated["review_category"] = item["review_category"]
        updated["likely_correct_score"] = item["likely_correct_score"]
        updated["likely_status"] = item["likely_status"]
        updated["blocking_reason"] = item["blocking_reason"]
        updated["suggested_fix"] = item["suggested_fix"]
        updated["potential_mistake_flags"] = item["potential_mistake_flags"]
        updated["similar_verified_rule_id"] = item["similar_verified_rule_id"]
        updated["similar_verified_score"] = item["similar_verified_score"]
        updated["triage_priority"] = item["triage_priority"]
        updated["review_rank"] = item["review_rank"]
        enriched.append(updated)
    return enriched

def _triage_item(rule: dict[str, Any], verified_rules: list[dict[str, Any]]) -> dict[str, Any]:
    category = _review_category(rule)
    similar_rule, similar_score = _closest_verified(rule, verified_rules)
    score = _likely_correct_score(rule, similar_score)
    likely_status = _likely_status(score, rule.get("support_gaps", []))
    priority = _triage_priority(rule, category, score)
    rank = _triage_priority_rank(priority, score)
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "candidate_id": str(rule.get("candidate", {}).get("candidate_id") or ""),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "source_evidence_id": rule.get("source", {}).get("evidence_id") if isinstance(rule.get("source"), dict) else "",
        "support_gaps": list(rule.get("support_gaps", [])),
        "review_category": category,
        "triage_priority": priority,
        "review_rank": rank,
        "likely_correct_score": score,
        "likely_status": likely_status,
        "blocking_reason": _blocking_reason(rule),
        "suggested_fix": _suggested_fix(category, rule),
        "potential_mistake_flags": _potential_mistake_flags(rule),
        "similar_verified_rule_id": similar_rule.get("rule_id") if similar_rule else None,
        "similar_verified_score": round(similar_score, 3),
    }

def _review_category(rule: dict[str, Any]) -> str:
    gaps = set(rule.get("support_gaps", []))
    if "cross_family_value_collision" in gaps:
        return "cross_family_conflict"
    if "unresolved_exception_cue" in gaps:
        return "unresolved_exception"
    if "text_condition_not_supported" in gaps:
        return "missing_condition_evidence"
    if gaps == {"text_candidate_requires_review"}:
        return "text_candidate_needs_consensus"
    table_gate_gaps = {
        "table_cell_candidate_requires_review",
        "table_evidence_candidate_requires_review",
        "table_fallback_candidate_requires_review",
    }
    if gaps and gaps <= table_gate_gaps:
        return "near_verified_table_context"
    if "operator_not_supported" in gaps:
        return "operator_uncertain"
    if "applies_to_not_supported" in gaps:
        return "missing_applies_to"
    if "constraint_scope_not_supported" in gaps or "table_column_not_target_scope" in gaps:
        return "missing_scope_evidence"
    if "rule_object_not_supported" in gaps:
        return "possible_rule_object_mismatch"
    if "upstream_extraction_requested_review" in gaps:
        return "upstream_review_requested"
    return "general_review"

def _likely_correct_score(rule: dict[str, Any], similar_verified_score: float) -> float:
    # Weighting rationale: actual evidence support must dominate. Evidence
    # strength (0.52) plus passed support checks (0.28) carry 0.80 of the score,
    # while similarity to already-verified rules is capped at 0.12 — so a rule
    # that merely LOOKS like a verified rule can never outvote what its own
    # cited evidence actually proves. This keeps the advisory ranking aligned
    # with the verifier's evidence-first safety argument.
    strength = float(rule.get("evidence_strength") or 0.0)
    checks = rule.get("support_checks", {}) if isinstance(rule.get("support_checks"), dict) else {}
    check_values = [bool(value) for value in checks.values()]
    check_rate = sum(check_values) / len(check_values) if check_values else 0.0
    status_bonus = _proof_status_bonus(rule)
    penalty = _gap_penalty(rule.get("support_gaps", []))
    score = 0.52 * strength + 0.28 * check_rate + 0.12 * similar_verified_score + status_bonus - penalty
    return round(max(0.0, min(1.0, score)), 3)

def _proof_status_bonus(rule: dict[str, Any]) -> float:
    bonus = 0.0
    if rule.get("table_proof_status") == "complete":
        bonus += 0.08
    elif rule.get("table_proof_status") == "partial":
        bonus += 0.03
    if rule.get("text_span_proof_status") == "complete":
        bonus += 0.08
    elif rule.get("text_span_proof_status") == "partial":
        bonus += 0.02
    if rule.get("proof_decision_mismatch"):
        bonus -= 0.12
    return bonus

def _gap_penalty(gaps: list[str]) -> float:
    gap_set = set(gaps)
    penalty = 0.0
    penalty += 0.12 * len(gap_set & {"rule_object_not_supported", "operator_not_supported"})
    penalty += 0.10 * len(gap_set & {"text_condition_not_supported", "unresolved_exception_cue"})
    penalty += 0.08 * len(gap_set & {"applies_to_not_supported", "constraint_scope_not_supported"})
    penalty += 0.06 * len(gap_set & {"table_column_not_target_scope", "table_applies_to_not_supported"})
    penalty += 0.14 * len(gap_set & {"cross_family_value_collision"})
    return penalty

def _likely_status(score: float, gaps: list[str]) -> str:
    gap_set = set(gaps)
    if {"rule_object_not_supported", "operator_not_supported"} <= gap_set:
        return "likely_wrong_or_noise"
    if score >= 0.78:
        return "likely_correct"
    if score >= 0.55:
        return "plausible"
    if score >= 0.35:
        return "weak"
    return "likely_wrong_or_noise"

def _triage_priority(rule: dict[str, Any], category: str, score: float) -> str:
    if category in {"unresolved_exception", "cross_family_conflict"}:
        return "high"
    if category in {"near_verified_table_context", "missing_condition_evidence"} and score >= 0.55:
        return "high"
    if category in {"text_candidate_needs_consensus", "missing_scope_evidence", "missing_applies_to"}:
        return "medium" if score >= 0.45 else "low"
    if score >= 0.72:
        return "medium"
    return "low"

def _triage_priority_rank(priority: str, score: float) -> int:
    base = {"high": 1, "medium": 100, "low": 200}.get(priority, 300)
    return base + int((1.0 - score) * 99)

def _blocking_reason(rule: dict[str, Any]) -> str:
    gaps = rule.get("support_gaps", [])
    if not gaps:
        return "No support gap recorded; inspect proof trace."
    return ", ".join(gaps[:4])

def _suggested_fix(category: str, rule: dict[str, Any]) -> str:
    if category == "missing_condition_evidence":
        return "Find evidence span that includes the material condition, not only the value/unit."
    if category == "text_candidate_needs_consensus":
        return "Look for table or second text source asserting the exact same rule."
    if category == "near_verified_table_context":
        return "Inspect table title, row, column, and cell; consider adding a safe table-scope pattern."
    if category == "missing_applies_to":
        return "Recover row/header or local text that names the affected building/use type."
    if category == "missing_scope_evidence":
        return "Recover local evidence around the value that proves the scope."
    if category == "operator_uncertain":
        return "Find wording such as minimum, maximum, required, permitted, not less, or not exceed."
    if category == "cross_family_conflict":
        return "Compare sibling rule families sharing the same value; do not auto-pick a winner."
    if category == "unresolved_exception":
        return "Resolve exception/override wording before promotion."
    if category == "possible_rule_object_mismatch":
        return "Check whether Pipeline 5 attached the value to the wrong rule family."
    return "Inspect proof trace and support gaps."

def _potential_mistake_flags(rule: dict[str, Any]) -> list[str]:
    gaps = set(rule.get("support_gaps", []))
    flags: list[str] = []
    mapping = {
        "rule_object_not_supported": "possible_wrong_rule_family",
        "operator_not_supported": "operator_direction_or_wording_missing",
        "text_condition_not_supported": "condition_not_in_cited_text",
        "cross_family_value_collision": "possible_sibling_metric_mixup",
        "table_column_not_target_scope": "table_column_scope_mismatch",
        "unresolved_exception_cue": "exception_or_override_unresolved",
        "applies_to_not_supported": "applies_to_not_grounded",
        "constraint_scope_not_supported": "scope_not_grounded",
    }
    for gap, flag in mapping.items():
        if gap in gaps:
            flags.append(flag)
    return flags

def _closest_verified(rule: dict[str, Any], verified_rules: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best_rule: dict[str, Any] | None = None
    best_score = 0.0
    for verified in verified_rules:
        score = _rule_similarity(rule, verified)
        if score > best_score:
            best_rule = verified
            best_score = score
    return best_rule, best_score

def _rule_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_words = _rule_words(left)
    right_words = _rule_words(right)
    if not left_words or not right_words:
        return 0.0
    overlap = len(left_words & right_words) / len(left_words | right_words)
    same_family = 0.25 if left.get("rule_object") == right.get("rule_object") else 0.0
    same_unit = 0.10 if str(left.get("unit") or "") == str(right.get("unit") or "") else 0.0
    return min(1.0, overlap + same_family + same_unit)

def _rule_words(rule: dict[str, Any]) -> set[str]:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    parts = [
        rule.get("rule_object"),
        rule.get("constraint_type"),
        rule.get("constraint_scope"),
        rule.get("applies_to"),
        rule.get("condition"),
        rule.get("operator"),
        rule.get("value"),
        rule.get("unit"),
        source.get("evidence_text"),
    ]
    return text_words(" ".join(str(part) for part in parts if part not in (None, "")))


# --- merged from review_audit.py (action audit) ---

ACTION_RETRY_WITH_BETTER_EVIDENCE = "retry_with_better_evidence"

ACTION_SAFE_VERIFIER_TUNING = "safe_verifier_tuning_candidate"

ACTION_EVIDENCE_PACKET_REPAIR = "evidence_packet_repair_candidate"

ACTION_SECOND_SOURCE = "needs_second_source_consensus"

ACTION_HUMAN_LEGAL_REVIEW = "human_legal_review"

ACTION_UPSTREAM_CANDIDATE_ISSUE = "upstream_candidate_issue"

ACTION_SEMANTIC_DUPLICATE_REVIEW = "semantic_duplicate_review"

ACTION_SEMANTIC_GUARDRAIL_REVIEW = "semantic_guardrail_review"

ACTION_DEFER_LOW_PRIORITY = "defer_low_priority"

ACTION_ORDER = {
    ACTION_RETRY_WITH_BETTER_EVIDENCE: 1,
    ACTION_SAFE_VERIFIER_TUNING: 2,
    ACTION_EVIDENCE_PACKET_REPAIR: 3,
    ACTION_SECOND_SOURCE: 4,
    ACTION_SEMANTIC_DUPLICATE_REVIEW: 5,
    ACTION_SEMANTIC_GUARDRAIL_REVIEW: 6,
    ACTION_HUMAN_LEGAL_REVIEW: 7,
    ACTION_UPSTREAM_CANDIDATE_ISSUE: 8,
    ACTION_DEFER_LOW_PRIORITY: 9,
}

ACTION_DESCRIPTIONS = {
    ACTION_RETRY_WITH_BETTER_EVIDENCE: "Rerun candidate against a different, stronger evidence packet.",
    ACTION_SAFE_VERIFIER_TUNING: "Inspect whether a general verifier/table rule can safely reduce review.",
    ACTION_EVIDENCE_PACKET_REPAIR: "Repair evidence attachment first; current suggestion is not strong enough to rerun.",
    ACTION_SECOND_SOURCE: "Find independent text/table consensus before promotion.",
    ACTION_SEMANTIC_DUPLICATE_REVIEW: "Compare a high-similarity review item against an already verified rule; usually a duplicate/degraded extraction.",
    ACTION_SEMANTIC_GUARDRAIL_REVIEW: "Close semantic match, but core guardrails disagree; inspect manually instead of tuning.",
    ACTION_HUMAN_LEGAL_REVIEW: "Resolve exception or cross-family conflict manually.",
    ACTION_UPSTREAM_CANDIDATE_ISSUE: "Return likely extraction/normalization issue upstream.",
    ACTION_DEFER_LOW_PRIORITY: "Leave in review until broader benchmark evidence exists.",
}

EVIDENCE_PACKET_REPAIR_THRESHOLD = 0.45

SAFE_TUNING_SCORE_THRESHOLD = 0.72

NEAR_VERIFIED_TABLE_THRESHOLD = 0.55

def build_review_audit(
    review_rules: list[dict[str, Any]],
    triage_report: dict[str, Any],
    evidence_repair_report: dict[str, Any],
) -> dict[str, Any]:
    """Build one action row per review rule."""
    # Triage has human-facing labels/scores. Evidence repair has candidate
    # alternate evidence. The audit joins those two reports into one next-action
    # table so the user does not need to compare JSON files manually.
    triage_by_id = {str(item.get("rule_id") or ""): item for item in triage_report.get("items", [])}
    repair_by_id = {str(item.get("rule_id") or ""): item for item in evidence_repair_report.get("suggestions", [])}
    items = [
        _audit_item(
            rule,
            triage_by_id.get(str(rule.get("rule_id") or ""), {}),
            repair_by_id.get(str(rule.get("rule_id") or ""), {}),
        )
        for rule in review_rules
    ]
    items.sort(key=lambda item: (ACTION_ORDER.get(item["action_bucket"], 99), item["review_rank"], -item["likely_correct_score"], item["rule_id"]))
    action_counts = Counter(item["action_bucket"] for item in items)
    category_counts = Counter(item["review_category"] for item in items)
    return {
        "review_rule_count": len(review_rules),
        "items": items,
        "summary": {
            "action_counts": counter_rows(action_counts),
            "category_counts": counter_rows(category_counts),
            "action_descriptions": ACTION_DESCRIPTIONS,
            "top_support_gaps": _top_support_gaps(items),
            "recommendations": _recommendations(items),
        },
    }

def apply_review_audit(
    review_rules: list[dict[str, Any]],
    audit_report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach audit fields onto review rules for dashboard and JSON inspection."""
    by_id = {str(item.get("rule_id") or ""): item for item in audit_report.get("items", [])}
    enriched: list[dict[str, Any]] = []
    for rule in review_rules:
        item = by_id.get(str(rule.get("rule_id") or ""))
        if not item:
            enriched.append(rule)
            continue
        # Attach only review-management fields. Verification fields, proof
        # traces, and support gaps are left unchanged.
        updated = dict(rule)
        updated["review_action_bucket"] = item["action_bucket"]
        updated["review_action_reason"] = item["action_reason"]
        updated["review_next_step"] = item["next_step"]
        updated["repair_evidence_id"] = item["best_repair_evidence_id"]
        updated["repair_confidence"] = item["best_repair_confidence"]
        updated["can_retry_verification"] = item["can_retry_verification"]
        enriched.append(updated)
    return enriched


def apply_semantic_review(
    review_rules: list[dict[str, Any]],
    semantic_review_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach advisory semantic-review fields onto review rules.

    The fields added here are review-management metadata only. They are written
    to ``review_needed.json`` so the dashboard can compare candidate meaning
    against verified rules, but they never change support gaps or decisions.
    """
    if not semantic_review_report:
        return review_rules
    by_id = _items_by_id(semantic_review_report, "items")
    enriched: list[dict[str, Any]] = []
    for rule in review_rules:
        item = by_id.get(str(rule.get("rule_id") or ""))
        if not item:
            enriched.append(rule)
            continue
        top_match = _semantic_top_match(item)
        updated = dict(rule)
        updated["semantic_review_class"] = _semantic_review_class(item)
        updated["semantic_verified_rule_id"] = top_match.get("verified_rule_id")
        updated["semantic_score"] = _semantic_score_value(item)
        updated["semantic_structured_score"] = item.get("best_structured_score")
        updated["semantic_embedding_score"] = item.get("best_embedding_score")
        updated["semantic_match_type"] = item.get("semantic_match_type")
        updated["semantic_next_action"] = item.get("semantic_next_action")
        updated["semantic_guardrail_blockers"] = list(item.get("semantic_guardrail_blockers", []))
        enriched.append(updated)
    return enriched

def _audit_item(rule: dict[str, Any], triage: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    best_repair = _top_repair(repair)
    action = _action_bucket(rule, triage, repair)
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "candidate_id": str(rule.get("candidate", {}).get("candidate_id") or triage.get("candidate_id") or ""),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "support_gaps": list(rule.get("support_gaps", [])),
        "review_category": triage.get("review_category") or rule.get("review_category") or "general_review",
        "likely_status": triage.get("likely_status") or rule.get("likely_status") or "unknown",
        "likely_correct_score": float(triage.get("likely_correct_score") or rule.get("likely_correct_score") or 0.0),
        "triage_priority": triage.get("triage_priority") or rule.get("triage_priority") or rule.get("review_priority"),
        "review_rank": int(triage.get("review_rank") or rule.get("review_rank") or 999),
        "can_retry_verification": bool(repair.get("can_retry_verification")),
        "repairable_fields": list(repair.get("repairable_fields", [])),
        "best_repair_evidence_id": best_repair.get("evidence_id"),
        "best_repair_confidence": float(repair.get("best_repair_confidence") or 0.0),
        "action_bucket": action,
        "action_reason": _action_reason(action, rule, triage, repair),
        "next_step": _next_step(action),
    }

def _action_bucket(rule: dict[str, Any], triage: dict[str, Any], repair: dict[str, Any]) -> str:
    # This policy is deliberately conservative. It recommends work, but it does
    # not override verification. Anything with exceptions/conflicts goes to
    # human review even if the score looks high.
    category = str(triage.get("review_category") or rule.get("review_category") or "")
    likely_status = str(triage.get("likely_status") or rule.get("likely_status") or "")
    score = float(triage.get("likely_correct_score") or rule.get("likely_correct_score") or 0.0)
    repair_confidence = float(repair.get("best_repair_confidence") or 0.0)
    gaps = set(rule.get("support_gaps", []))
    flags = set(triage.get("potential_mistake_flags") or rule.get("potential_mistake_flags") or [])

    if category in {"cross_family_conflict", "unresolved_exception"}:
        return ACTION_HUMAN_LEGAL_REVIEW
    if repair.get("can_retry_verification"):
        # Strongest low-risk path: the same candidate can be tested against a
        # different evidence packet, and the verifier still has final authority.
        return ACTION_RETRY_WITH_BETTER_EVIDENCE
    if category == "near_verified_table_context" and score >= NEAR_VERIFIED_TABLE_THRESHOLD:
        # These are usually blocked by table-scope gates. They should be audited
        # for generalizable verifier rules, not one-off Burnaby hardcodes.
        return ACTION_SAFE_VERIFIER_TUNING
    if category == "text_candidate_needs_consensus":
        return ACTION_SECOND_SOURCE
    if likely_status == "likely_wrong_or_noise" or category == "possible_rule_object_mismatch" or "possible_wrong_rule_family" in flags:
        # Do not tune the verifier around likely extraction/normalization errors.
        # Those should go back upstream.
        return ACTION_UPSTREAM_CANDIDATE_ISSUE
    if repair_confidence >= EVIDENCE_PACKET_REPAIR_THRESHOLD and gaps & {
        "text_condition_not_supported",
        "operator_not_supported",
        "applies_to_not_supported",
        "constraint_scope_not_supported",
        "table_applies_to_not_supported",
        "table_condition_not_supported",
        "table_column_not_target_scope",
    }:
        return ACTION_EVIDENCE_PACKET_REPAIR
    if score >= SAFE_TUNING_SCORE_THRESHOLD and gaps <= {
        "operator_not_supported",
        "applies_to_not_supported",
        "constraint_scope_not_supported",
        "text_candidate_requires_review",
        "table_cell_candidate_requires_review",
        "table_evidence_candidate_requires_review",
        "table_fallback_candidate_requires_review",
    }:
        return ACTION_SAFE_VERIFIER_TUNING
    return ACTION_DEFER_LOW_PRIORITY

def _action_reason(action: str, rule: dict[str, Any], triage: dict[str, Any], repair: dict[str, Any]) -> str:
    category = triage.get("review_category") or rule.get("review_category") or "general_review"
    score = float(triage.get("likely_correct_score") or rule.get("likely_correct_score") or 0.0)
    repair_confidence = float(repair.get("best_repair_confidence") or 0.0)
    if action == ACTION_RETRY_WITH_BETTER_EVIDENCE:
        return f"Evidence repair found enough matching fields to rerun verification (confidence {repair_confidence:.2f})."
    if action == ACTION_SAFE_VERIFIER_TUNING:
        return f"Category `{category}` has high support but is blocked by conservative verifier gates."
    if action == ACTION_EVIDENCE_PACKET_REPAIR:
        return f"Evidence repair found a possible stronger packet, but not enough fields for automatic retry (confidence {repair_confidence:.2f})."
    if action == ACTION_SECOND_SOURCE:
        return "Pipeline 5 text candidate needs a second source or table-backed consensus before promotion."
    if action == ACTION_HUMAN_LEGAL_REVIEW:
        return f"Category `{category}` can change legal meaning, so deterministic relaxation is unsafe."
    if action == ACTION_UPSTREAM_CANDIDATE_ISSUE:
        return f"Low likelihood or rule-family mismatch indicates an extraction/normalization issue (score {score:.2f})."
    return f"No safe automatic repair path yet (category `{category}`, score {score:.2f})."

def _next_step(action: str) -> str:
    if action == ACTION_RETRY_WITH_BETTER_EVIDENCE:
        return "Rerun the same candidate against the suggested evidence packet and require deterministic proof again."
    if action == ACTION_SAFE_VERIFIER_TUNING:
        return "Inspect whether a general verifier rule or table-scope pattern can be added without weakening safety gates."
    if action == ACTION_EVIDENCE_PACKET_REPAIR:
        return "Repair Pipeline 5 evidence attachment or retrieval context, then rerun verification."
    if action == ACTION_SECOND_SOURCE:
        return "Find a second independent evidence packet or table context before allowing this text candidate past review."
    if action == ACTION_HUMAN_LEGAL_REVIEW:
        return "Resolve exception, override, or sibling-rule conflict manually before changing verifier behavior."
    if action == ACTION_UPSTREAM_CANDIDATE_ISSUE:
        return "Send back to extraction/adapter normalization; do not tune verifier around this case."
    return "Leave in low-priority review until more evidence or a broader bylaw benchmark is available."

def _recommendations(items: list[dict[str, Any]]) -> list[str]:
    counts = Counter(item["action_bucket"] for item in items)
    recommendations: list[str] = []
    retry_count = counts.get(ACTION_RETRY_WITH_BETTER_EVIDENCE, 0)
    tuning_count = counts.get(ACTION_SAFE_VERIFIER_TUNING, 0)
    evidence_count = counts.get(ACTION_EVIDENCE_PACKET_REPAIR, 0)
    legal_count = counts.get(ACTION_HUMAN_LEGAL_REVIEW, 0)
    upstream_count = counts.get(ACTION_UPSTREAM_CANDIDATE_ISSUE, 0)
    semantic_duplicate_count = counts.get(ACTION_SEMANTIC_DUPLICATE_REVIEW, 0)
    semantic_guardrail_count = counts.get(ACTION_SEMANTIC_GUARDRAIL_REVIEW, 0)
    if retry_count:
        recommendations.append(f"Start with {retry_count} rules that can be rerun against stronger evidence.")
    if tuning_count:
        recommendations.append(f"Audit {tuning_count} near-verified rules for safe general verifier/table-scope tuning.")
    if evidence_count:
        recommendations.append(f"Repair evidence attachments for {evidence_count} rules before changing verifier logic.")
    if semantic_duplicate_count:
        recommendations.append(f"Use semantic review to close out {semantic_duplicate_count} likely duplicate/degraded extraction items.")
    if semantic_guardrail_count:
        recommendations.append(f"Keep {semantic_guardrail_count} close semantic matches blocked until their guardrail mismatch is resolved.")
    if legal_count:
        recommendations.append(f"Keep {legal_count} exception/conflict rules in human legal review.")
    if upstream_count:
        recommendations.append(f"Return {upstream_count} likely extraction/normalization mistakes upstream.")
    return recommendations

def build_review_layer(
    review_rules: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    *,
    evidence_repair_report: dict[str, Any],
    evidence_rerun_report: dict[str, Any],
    evidence_intelligence_report: dict[str, Any] | None = None,
    evidence_bundle_rerun_report: dict[str, Any] | None = None,
    semantic_review_report: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Single entry point for the review-annotation layer.

    Runs triage -> audit -> router in order, applying triage and audit fields to
    the review rules, and returns ``(annotated_review_rules, triage_report,
    audit_report, router_report)``. This is the one call slim_pipeline makes for
    review routing; it never changes a verification decision.
    """
    triage_report = build_review_triage(review_rules, verified_rules)
    review_rules = apply_review_triage(review_rules, triage_report)
    audit_report = build_review_audit(review_rules, triage_report, evidence_repair_report)
    review_rules = apply_review_audit(review_rules, audit_report)
    review_rules = apply_semantic_review(review_rules, semantic_review_report)
    router_report = build_review_router(
        review_rules,
        triage_report=triage_report,
        audit_report=audit_report,
        evidence_repair_report=evidence_repair_report,
        evidence_rerun_report=evidence_rerun_report,
        evidence_intelligence_report=evidence_intelligence_report,
        evidence_bundle_rerun_report=evidence_bundle_rerun_report,
        semantic_review_report=semantic_review_report,
    )
    return review_rules, triage_report, audit_report, router_report
