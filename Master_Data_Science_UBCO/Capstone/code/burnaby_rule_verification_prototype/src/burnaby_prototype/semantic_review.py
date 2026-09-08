"""Deterministic semantic review support.

It builds compact rule "meaning signatures" from structured fields, and can
optionally add MiniLM-style embedding similarity for vocabulary variation such
as rowhouse/townhouse. Embeddings are review intelligence only; they cannot
verify rules.

The purpose is reviewer efficiency:
find rules that mean almost the same thing as an existing verified rule, then
show what field still blocks verification.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .domain_schema import text_words, to_float, unit_key, unresolved_exception_cues
from .embedding_semantics import embedding_similarity_lookup
from .review_text import counter_rows
from .rule_claims import canonical_rule_key


def build_semantic_review_report(
    review_rules: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    *,
    limit_per_rule: int = 3,
    embedding_backend: Any | None = None,
    enable_embeddings: bool = True,
) -> dict[str, Any]:
    """Compare review rules to verified rules by structured semantic signature."""
    verified_signatures = [
        {
            "rule_id": rule.get("rule_id"),
            "signature": semantic_signature(rule),
            "rule": rule,
        }
        for rule in verified_rules
    ]
    embedding_report = (
        embedding_similarity_lookup(review_rules, verified_rules, backend=embedding_backend)
        if enable_embeddings
        else {
            "available": False,
            "model": None,
            "mode": "structured_only",
            "reason": "disabled",
            "scores": {},
            "notes": ["Embedding semantic review disabled; using structured signatures only."],
        }
    )
    items = []
    for rule in review_rules:
        signature = semantic_signature(rule)
        matches = [
            _match_row(rule, signature, verified, embedding_report)
            for verified in verified_signatures
        ]
        matches = [match for match in matches if match["combined_semantic_score"] > 0]
        matches.sort(key=lambda item: (-item["combined_semantic_score"], item["verified_rule_id"]))
        best = matches[:limit_per_rule]
        best_score = best[0]["combined_semantic_score"] if best else 0.0
        items.append(
            {
                "rule_id": rule.get("rule_id"),
                "candidate_id": rule.get("candidate", {}).get("candidate_id"),
                "canonical_rule_key": rule.get("canonical_rule_key") or canonical_rule_key(rule),
                "signature": signature,
                "best_verified_matches": best,
                # Keep the old field name for dashboard/backward compatibility.
                "best_semantic_score": best_score,
                "best_structured_score": best[0]["structured_score"] if best else 0.0,
                "best_embedding_score": best[0]["embedding_score"] if best else None,
                "best_combined_semantic_score": best_score,
                "semantic_match_type": (
                    "structured_plus_embedding"
                    if best and best[0].get("embedding_score") is not None
                    else "structured_only"
                ),
                "semantic_guardrails": best[0]["semantic_guardrails"] if best else [],
                "semantic_guardrail_blockers": best[0]["semantic_guardrail_blockers"] if best else [],
                "semantic_next_action": _semantic_next_action(rule, best),
                "support_gaps": list(rule.get("support_gaps", [])),
            }
        )
    items.sort(key=lambda item: (-item["best_semantic_score"], str(item["rule_id"])))
    action_counts: Counter[str] = Counter(item["semantic_next_action"] for item in items)
    return {
        "purpose": "Advisory semantic-signature comparison for review rules. It never verifies rules.",
        "review_rule_count": len(review_rules),
        "verified_rule_count": len(verified_rules),
        "high_similarity_count": sum(1 for item in items if item["best_semantic_score"] >= 0.82),
        "embedding": {
            key: value
            for key, value in embedding_report.items()
            if key not in {"scores", "review_texts", "verified_texts"}
        },
        "items": items,
        "summary": {
            "semantic_action_counts": counter_rows(action_counts),
        },
        "notes": [
            "Semantic score uses normalized structured fields plus optional MiniLM embeddings.",
            "Embedding similarity is advisory and cannot clear support gaps.",
            "Guardrails cap high similarity when core legal fields disagree.",
        ],
    }


def semantic_signature(rule: dict[str, Any]) -> dict[str, Any]:
    """Return a compact meaning signature for a zoning rule."""
    direction = _direction(rule.get("operator"), rule.get("constraint_type"))
    value = to_float(rule.get("value"))
    return {
        "rule_object": rule.get("rule_object"),
        "direction": direction,
        "value_bucket": _value_bucket(value),
        "value_numeric": round(value, 3) if value is not None else None,
        "unit": unit_key(rule.get("unit")),
        "scope_concepts": sorted(_concept_words(rule.get("constraint_scope"))),
        "applies_to_concepts": sorted(_concept_words(rule.get("applies_to"))),
        "condition_concepts": sorted(_concept_words(rule.get("condition"))),
    }


def _match_row(
    review_rule: dict[str, Any],
    signature: dict[str, Any],
    verified: dict[str, Any],
    embedding_report: dict[str, Any],
) -> dict[str, Any]:
    verified_sig = verified["signature"]
    structured_score, reasons = _semantic_score(signature, verified_sig)
    verified_rule = verified["rule"]
    review_id = str(review_rule.get("rule_id") or "")
    verified_id = str(verified.get("rule_id") or "")
    embedding_score = embedding_report.get("scores", {}).get((review_id, verified_id))
    guardrails, blockers = _semantic_guardrails(review_rule, signature, verified_sig)
    combined_score = _combined_score(structured_score, embedding_score, blockers)
    match_reasons = list(reasons)
    if embedding_score is not None:
        match_reasons.append("embedding_similarity")
    return {
        "verified_rule_id": verified.get("rule_id"),
        # Keep semantic_score as the dashboard-facing combined score.
        "semantic_score": combined_score,
        "structured_score": structured_score,
        "embedding_score": embedding_score,
        "combined_semantic_score": combined_score,
        "semantic_guardrails": guardrails,
        "semantic_guardrail_blockers": blockers,
        "match_reasons": match_reasons,
        "verified_rule_object": verified_rule.get("rule_object"),
        "verified_scope": verified_rule.get("constraint_scope"),
        "verified_applies_to": verified_rule.get("applies_to"),
        "verified_operator": verified_rule.get("operator"),
        "verified_value": verified_rule.get("value"),
        "verified_unit": verified_rule.get("unit"),
    }


def _semantic_score(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if a["rule_object"] == b["rule_object"]:
        score += 0.26
        reasons.append("same_rule_object")
    if a["direction"] == b["direction"]:
        score += 0.16
        reasons.append("same_direction")
    if a["unit"] == b["unit"]:
        score += 0.12
        reasons.append("same_unit")
    if a["value_numeric"] is not None and b["value_numeric"] is not None:
        if abs(a["value_numeric"] - b["value_numeric"]) <= 0.01:
            score += 0.20
            reasons.append("same_value")
        elif a["value_bucket"] == b["value_bucket"]:
            score += 0.06
            reasons.append("same_value_bucket")
    score += 0.16 * _jaccard(set(a["scope_concepts"]), set(b["scope_concepts"]))
    score += 0.07 * _jaccard(set(a["applies_to_concepts"]), set(b["applies_to_concepts"]))
    score += 0.03 * _jaccard(set(a["condition_concepts"]), set(b["condition_concepts"]))
    if set(a["scope_concepts"]) & set(b["scope_concepts"]):
        reasons.append("scope_concept_overlap")
    if set(a["applies_to_concepts"]) & set(b["applies_to_concepts"]):
        reasons.append("applies_to_concept_overlap")
    if set(a["condition_concepts"]) & set(b["condition_concepts"]):
        reasons.append("condition_concept_overlap")
    return round(min(1.0, score), 3), reasons


def _semantic_next_action(rule: dict[str, Any], matches: list[dict[str, Any]]) -> str:
    if not matches:
        return "no_close_verified_analogue"
    if matches[0].get("semantic_guardrail_blockers") and (
        matches[0].get("structured_score", 0.0) >= 0.72
        or (matches[0].get("embedding_score") or 0.0) >= 0.82
    ):
        return "close_meaning_guardrail_blocked"
    if matches[0]["combined_semantic_score"] < 0.72:
        return "no_close_verified_analogue"
    gaps = set(rule.get("support_gaps", []))
    if gaps & {"value_not_found_in_evidence", "unit_not_found_in_evidence", "operator_not_supported"}:
        return "close_meaning_but_missing_core_evidence"
    if gaps & {"constraint_scope_not_supported", "applies_to_not_supported", "table_applies_to_not_supported"}:
        return "close_meaning_scope_review"
    if gaps & {"table_condition_not_supported", "text_condition_not_supported"}:
        return "close_meaning_condition_review"
    return "close_meaning_general_review"


def _combined_score(structured_score: float, embedding_score: float | None, blockers: list[str]) -> float:
    if embedding_score is None:
        combined = structured_score
    else:
        # Structured fields carry more weight because zoning verification depends
        # on legal fields, not just natural-language similarity.
        combined = 0.65 * structured_score + 0.35 * embedding_score
    if blockers:
        # Guardrail-blocked matches are capped at 0.71 — deliberately just below
        # the 0.72 close-match bar used by the router and next-action logic. A
        # match whose CORE legal fields disagree (rule family, direction, unit,
        # numeric value, or unresolved exception) must never present itself as a
        # high-confidence match, no matter how similar the wording is. Consumers
        # that still need to surface these cases (router step 9a) must check the
        # raw structured/embedding scores plus the blocker list instead.
        combined = min(combined, 0.71)
    return round(max(0.0, min(1.0, combined)), 3)


def _semantic_guardrails(
    review_rule: dict[str, Any],
    review_signature: dict[str, Any],
    verified_signature: dict[str, Any],
) -> tuple[list[str], list[str]]:
    guardrails: list[str] = []
    blockers: list[str] = []
    if review_signature["rule_object"] == verified_signature["rule_object"]:
        guardrails.append("same_rule_object")
    else:
        blockers.append("different_rule_object")
    if review_signature["direction"] == verified_signature["direction"]:
        guardrails.append("same_direction")
    else:
        blockers.append("different_direction")
    if review_signature["unit"] == verified_signature["unit"]:
        guardrails.append("same_unit")
    else:
        blockers.append("different_unit")

    left_value = review_signature["value_numeric"]
    right_value = verified_signature["value_numeric"]
    if left_value is not None and right_value is not None:
        if abs(left_value - right_value) <= 0.01:
            guardrails.append("same_value")
        else:
            blockers.append("different_numeric_value")

    gaps = set(review_rule.get("support_gaps", []))
    if gaps & {"value_not_found_in_evidence", "unit_not_found_in_evidence", "operator_not_supported"}:
        blockers.append("missing_core_evidence")
    if "unresolved_exception_cue" in gaps or _has_exception_cue(review_rule):
        blockers.append("exception_or_override_unresolved")
    return guardrails, sorted(set(blockers))


def _has_exception_cue(rule: dict[str, Any]) -> bool:
    text = " ".join(str(rule.get(key) or "") for key in ("condition", "exception"))
    return bool(unresolved_exception_cues(text))


def _direction(operator: Any, constraint_type: Any) -> str:
    text = f"{operator or ''} {constraint_type or ''}".lower()
    if any(token in text for token in (">=", "minimum", "min", "at_least")):
        return "min"
    if any(token in text for token in ("<=", "maximum", "max", "not_exceed")):
        return "max"
    if ">" in text:
        return "gt"
    if "<" in text:
        return "lt"
    if "allow" in text or "permit" in text:
        return "allowed"
    if "required" in text:
        return "required"
    return "eq"


def _value_bucket(value: float | None) -> str:
    if value is None:
        return "none"
    if value < 1:
        return "under_1"
    if value < 3:
        return "1_to_3"
    if value < 10:
        return "3_to_10"
    if value < 100:
        return "10_to_100"
    return "100_plus"


def _concept_words(value: Any) -> set[str]:
    stopwords = {
        "all",
        "the",
        "and",
        "for",
        "with",
        "building",
        "buildings",
        "lot",
        "lots",
        "unit",
        "units",
        "maximum",
        "minimum",
    }
    return {
        _concept_alias(word)
        for word in text_words(str(value or ""))
        if len(word) > 2 and word not in stopwords
    }


def _concept_alias(word: str) -> str:
    aliases = {
        "yard": "setback_area",
        "setback": "setback_area",
        "principal": "principal",
        "principals": "principal",
        "accessory": "accessory",
        "front": "front",
        "rear": "rear",
        "lane": "lane",
        "street": "street",
        "flanking": "flanking",
        "interior": "interior",
        "side": "side",
        "heritage": "heritage",
        "roof": "roof",
        "sloping": "sloping",
        "flat": "flat",
    }
    return aliases.get(re.sub(r"[^a-z0-9]+", "", word.lower()), word)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
