"""Deterministic evidence-repair suggestions for review rules.

This is a RAG-lite helper: it searches existing evidence packets for stronger
support candidates, but it never changes verification decisions.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import TEXT_RULE_OBJECT_PATTERNS, UNIT_ALIASES, text_words, token_visible, unit_key


REPAIRABLE_GAPS = {
    "text_candidate_requires_review",
    "text_condition_not_supported",
    "operator_not_supported",
    "applies_to_not_supported",
    "constraint_scope_not_supported",
    "table_applies_to_not_supported",
    "table_condition_not_supported",
    "table_column_not_target_scope",
    "rule_object_not_supported",
}

# These thresholds are intentionally report-only. They decide whether a review
# item is worth retrying with different evidence; they never verify the rule.
#
# Why 0.62 over 13.0: the raw score's core matches are value (4.0), rule_object
# (3.0), unit (2.0), and operator (2.0) = 11.0, while the context bonuses
# (scope/applies_to/condition overlap + evidence quality) can add up to ~7.5
# more. Dividing by 13.0 instead of the theoretical maximum means confidence
# SATURATES once the four core field matches land plus a little context —
# a retry should not require every optional bonus to fire. 0.62 * 13.0 = 8.06,
# i.e. roughly "value + rule_object + one more core field", which is the
# minimum evidence worth re-feeding to the deterministic verifier.
RETRY_CONFIDENCE_THRESHOLD = 0.62
REPAIR_CONFIDENCE_DENOMINATOR = 13.0


def suggest_evidence_repairs(
    review_rules: list[dict[str, Any]],
    evidence_units: list[dict[str, Any]],
    *,
    limit_per_rule: int = 3,
) -> dict[str, Any]:
    """Return ranked evidence suggestions for review rules."""
    # Build the searchable evidence index once. The previous version rebuilt
    # text/word sets for every candidate/evidence pair, which was redundant.
    evidence_index = _prepare_evidence_index(evidence_units)
    suggestions = [
        _rule_suggestion(rule, evidence_index, limit_per_rule=limit_per_rule)
        for rule in review_rules
        if _is_repairable(rule)
    ]
    suggestions.sort(key=lambda item: (-item["best_repair_confidence"], item["rule_id"]))
    return {
        "suggestion_count": len(suggestions),
        "alternative_evidence_count": sum(1 for item in suggestions if item["top_evidence"]),
        "retry_candidate_count": sum(1 for item in suggestions if item["can_retry_verification"]),
        "suggestions": suggestions,
    }


def evidence_repair_markdown(report: dict[str, Any], *, limit: int = 20) -> str:
    """Render a compact evidence-repair report."""
    lines = [
        "# Evidence Repair Suggestions",
        "",
        "This report searches existing evidence packets for stronger support. It does not verify rules.",
        "",
        f"- Suggestions: {report.get('suggestion_count', 0)}",
        f"- With alternative evidence: {report.get('alternative_evidence_count', 0)}",
        f"- Retry candidates: {report.get('retry_candidate_count', 0)}",
        "",
        f"## Top {limit}",
        "",
    ]
    for item in report.get("suggestions", [])[:limit]:
        top = item.get("top_evidence", [{}])[0] if item.get("top_evidence") else {}
        lines.append(
            f"- `{item['rule_id']}` {item['rule_object']} {item['operator']} {item['value']} {item['unit']} "
            f"best={top.get('evidence_id', 'none')} confidence={item['best_repair_confidence']:.2f} "
            f"retry={item['can_retry_verification']} fields={', '.join(item.get('repairable_fields', [])) or 'none'}"
        )
    return "\n".join(lines) + "\n"


def _is_repairable(rule: dict[str, Any]) -> bool:
    return bool(set(rule.get("support_gaps", [])) & REPAIRABLE_GAPS)


def _rule_suggestion(
    rule: dict[str, Any],
    evidence_index: list[dict[str, Any]],
    *,
    limit_per_rule: int,
) -> dict[str, Any]:
    current_evidence_id = ""
    if isinstance(rule.get("source"), dict):
        current_evidence_id = str(rule["source"].get("evidence_id") or "")
    # Do not suggest the same evidence packet already cited by the candidate.
    # A "repair" should mean a better alternate source, not a restatement of the
    # evidence that already failed verification.
    scored = [_score_evidence(rule, evidence) for evidence in evidence_index if evidence["evidence_id"] != current_evidence_id]
    scored = [item for item in scored if item["raw_score"] > 0]
    scored.sort(key=lambda item: (-item["raw_score"], item["evidence_id"]))
    top = scored[:limit_per_rule]
    best_confidence = top[0]["repair_confidence"] if top else 0.0
    repairable_fields = _repairable_fields(rule, top[0] if top else {})
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "candidate_id": str(rule.get("candidate", {}).get("candidate_id") or ""),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "condition": rule.get("condition"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "current_evidence_id": current_evidence_id,
        "support_gaps": list(rule.get("support_gaps", [])),
        "best_repair_confidence": best_confidence,
        "can_retry_verification": bool(best_confidence >= RETRY_CONFIDENCE_THRESHOLD and repairable_fields),
        "repairable_fields": repairable_fields,
        "top_evidence": top,
    }


def _score_evidence(rule: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    # This is a transparent lexical scorer, not an embedding model. It rewards
    # evidence that visibly contains the candidate's value, unit, rule family,
    # operator wording, and scope/condition words.
    text = evidence["text"]
    words = evidence["words"]
    raw = 0.0
    reasons: list[str] = ["alternative_evidence"]

    if _contains_value(text, rule.get("value")):
        raw += 4.0
        reasons.append("value_match")
    if _contains_unit(text, rule.get("unit")):
        raw += 2.0
        reasons.append("unit_match")
    if _rule_object_supported(str(rule.get("rule_object") or ""), text):
        raw += 3.0
        reasons.append("rule_object_cue")
    if _operator_supported(rule.get("operator"), rule.get("constraint_type"), text):
        raw += 2.0
        reasons.append("operator_cue")

    scope_overlap = _overlap(rule.get("constraint_scope"), words)
    applies_overlap = _overlap(rule.get("applies_to"), words)
    condition_overlap = _condition_overlap(rule.get("condition"), words)
    if scope_overlap:
        raw += min(2.0, scope_overlap * 0.8)
        reasons.append("scope_overlap")
    if applies_overlap:
        raw += min(1.5, applies_overlap * 0.5)
        reasons.append("applies_to_overlap")
    if condition_overlap:
        raw += min(3.0, condition_overlap * 0.9)
        reasons.append("condition_overlap")

    # Quality is a tie-breaker only: an evidence packet with NO substantive
    # field/context match must keep raw == 0 so the raw_score > 0 filter can
    # drop it and "no alternative evidence found" stays representable. The old
    # flat +0.25 baseline made every packet score positive, which reported
    # junk 'alternative evidence' for every rule.
    if len(reasons) > 1:  # something beyond the "alternative_evidence" marker
        quality = float(evidence.get("evidence_quality_score") or 0.0)
        raw += min(1.0, quality)

    return {
        "evidence_id": str(evidence.get("evidence_id") or ""),
        "page": evidence.get("page"),
        "evidence_type": evidence.get("evidence_type"),
        "raw_score": round(raw, 3),
        "repair_confidence": round(min(1.0, raw / REPAIR_CONFIDENCE_DENOMINATOR), 3),
        "match_reasons": reasons,
        "evidence_quote": _short_quote(text),
    }


def _repairable_fields(rule: dict[str, Any], scored_evidence: dict[str, Any]) -> list[str]:
    # Map evidence match reasons back to the exact failed verifier fields. This
    # keeps retry suggestions specific: e.g., "operator can be repaired" instead
    # of a vague "this evidence looks similar".
    reasons = set(scored_evidence.get("match_reasons", []))
    gaps = set(rule.get("support_gaps", []))
    fields: list[str] = []
    if "value_not_found_in_evidence" in gaps and "value_match" in reasons:
        fields.append("value")
    if "unit_not_found_in_evidence" in gaps and "unit_match" in reasons:
        fields.append("unit")
    if "operator_not_supported" in gaps and "operator_cue" in reasons:
        fields.append("operator")
    if "rule_object_not_supported" in gaps and "rule_object_cue" in reasons:
        fields.append("rule_object")
    if ("applies_to_not_supported" in gaps or "table_applies_to_not_supported" in gaps) and "applies_to_overlap" in reasons:
        fields.append("applies_to")
    if ("constraint_scope_not_supported" in gaps or "table_column_not_target_scope" in gaps) and "scope_overlap" in reasons:
        fields.append("scope")
    if ("text_condition_not_supported" in gaps or "table_condition_not_supported" in gaps) and "condition_overlap" in reasons:
        fields.append("condition")
    if "text_candidate_requires_review" in gaps and {"value_match", "unit_match", "operator_cue", "rule_object_cue"} <= reasons:
        fields.append("text_consensus_candidate")
    return fields


def _evidence_text(evidence: dict[str, Any]) -> str:
    return " ".join(
        str(evidence.get(field) or "")
        for field in (
            "table_title",
            "row_header",
            "column_header",
            "cell_value",
            "evidence_text",
            "source_context",
        )
    )


def _prepare_evidence_index(evidence_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Precompute searchable text once for each evidence packet."""
    indexed: list[dict[str, Any]] = []
    for evidence in evidence_units:
        text = _evidence_text(evidence)
        indexed.append(
            {
                **evidence,
                "evidence_id": str(evidence.get("evidence_id") or ""),
                "text": text,
                "words": text_words(text),
            }
        )
    return indexed


def _contains_value(text: str, value: Any) -> bool:
    if value in (None, ""):
        return True
    tokens = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", "")) or [str(value).lower()]
    # Boundary-aware matching (shared token_visible): '4.5' must not be "found"
    # inside '14.5'. Comma grouping is stripped from both sides first.
    normalized = text.replace(",", "")
    return all(token_visible(normalized, token) for token in tokens)


def _contains_unit(text: str, unit: Any) -> bool:
    key = unit_key(unit)
    if key is None:
        return True
    aliases = UNIT_ALIASES.get(key, [str(unit or "").lower()])
    lower = text.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lower) for alias in aliases)


def _operator_supported(operator: Any, constraint_type: Any, text: str) -> bool:
    direction = f"{operator or ''} {constraint_type or ''}".lower()
    lower = text.lower()
    if any(token in direction for token in ("<=", "maximum", "max", "not_exceed")):
        return any(cue in lower for cue in ("maximum", "not exceed", "up to", "limited to"))
    if any(token in direction for token in (">=", "minimum", "min", "at_least")):
        return any(cue in lower for cue in ("minimum", "not less", "at least", "shall have", "must have"))
    if ">" in direction:
        return any(cue in lower for cue in ("more than", "greater than", "exceeds"))
    if "<" in direction:
        return any(cue in lower for cue in ("less than", "fewer than", "under"))
    if "allowed" in direction or "permitted" in direction:
        return any(cue in lower for cue in ("permitted", "allowed"))
    if "required" in direction:
        return any(cue in lower for cue in ("required", "shall", "must"))
    return False


def _rule_object_supported(rule_object: str, text: str) -> bool:
    lower = text.lower()
    plain = rule_object.replace("_", " ")
    if rule_object and (rule_object in lower or plain in lower):
        return True
    for candidate_rule_object, phrase_groups in TEXT_RULE_OBJECT_PATTERNS:
        if candidate_rule_object != rule_object:
            continue
        if any(all(phrase in lower for phrase in group) for group in phrase_groups):
            return True
    return False


def _overlap(value: Any, evidence_words: set[str]) -> int:
    if value in (None, ""):
        return 0
    claim_words = {
        word for word in text_words(str(value)) if len(word) > 2 and word not in {"and", "the", "for", "all"}
    }
    return len(claim_words & evidence_words)


_CONDITION_STOPWORDS = {
    "all",
    "and",
    "area",
    "district",
    "for",
    "lot",
    "lots",
    "r1",
    "rule",
    "the",
    "unit",
    "units",
}

_MATERIAL_CONDITION_WORDS = {
    "abutting",
    "access",
    "accessory",
    "approval",
    "covenant",
    "director",
    "end",
    "except",
    "exception",
    "flanking",
    "front",
    "heritage",
    "lane",
    "network",
    "only",
    "planning",
    "register",
    "street",
    "subject",
    "transit",
}


def _condition_overlap(value: Any, evidence_words: set[str]) -> int:
    """Return condition overlap only when distinctive condition words match.

    Generic zoning words such as "lot" are too weak to repair a condition like
    "Community Heritage Register ... Section 219 Covenant". Requiring at least
    one material condition word keeps evidence repair from over-ranking nearby
    but legally different clauses.
    """
    if value in (None, ""):
        return 0
    claim_words = {
        word
        for word in text_words(str(value))
        if len(word) > 2 and word not in _CONDITION_STOPWORDS
    }
    matched = claim_words & evidence_words
    if len(matched) < 2:
        return 0
    if not (matched & _MATERIAL_CONDITION_WORDS):
        return 0
    return len(matched)


def _short_quote(value: Any, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
