"""Evidence intelligence for review rules.

This module is the shared review-support layer. It builds a rule-centric
evidence index once, scores evidence packets against review rules, and proposes
evidence bundles for deterministic reruns.

Important safety boundary:
The bundle score is advisory. It can make a rule easier to review or rerun, but
it cannot promote anything to ``verified``. Promotion still requires
``verify_candidates()`` to return a verified rule with no support gaps.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .domain_schema import (
    PLAIN_ONLY_RULE_OBJECT_PATTERNS,
    TEXT_RULE_OBJECT_PATTERNS,
    UNIT_ALIASES,
    text_words,
    token_visible,
    unresolved_exception_cues,
    unit_key,
)
from .review_text import candidate_sentence, count_lines, counter_rows
from .rule_claims import canonical_rule_key


CRITICAL_FIELDS = {"value", "unit", "operator", "rule_object"}
CONTEXT_FIELDS = {"scope", "applies_to", "condition"}

FIELD_BY_GAP = {
    "value_not_found_in_evidence": "value",
    "unit_not_found_in_evidence": "unit",
    "operator_not_supported": "operator",
    "table_operator_refuted": "operator",
    "rule_object_not_supported": "rule_object",
    "rule_object_not_canonical": "rule_object",
    "table_rule_object_not_supported": "rule_object",
    "applies_to_not_supported": "applies_to",
    "table_applies_to_not_supported": "applies_to",
    "constraint_scope_not_supported": "scope",
    "table_column_not_target_scope": "scope",
    "table_condition_not_supported": "condition",
    "text_condition_not_supported": "condition",
    "unresolved_exception_cue": "exception",
}

HARD_BLOCKER_GAPS = {
    "source_evidence_id_not_found",
    "table_operator_refuted",
    "rule_object_unit_not_compatible",
    "non_numeric_value_for_numeric_rule",
    "cross_family_value_collision",
    "rule_family_direction_mismatch",
    "unresolved_exception_cue",
}


def build_evidence_intelligence(
    *,
    review_rules: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    rule_candidates: list[dict[str, Any]],
    evidence_units: list[dict[str, Any]],
    limit_per_rule: int = 5,
    bundle_size: int = 4,
) -> dict[str, Any]:
    """Build one rule-centric evidence report for review support.

    ``verified_rules`` and ``rule_candidates`` are included so the report can
    show same-key context and source coverage. The scoring itself uses only the
    candidate fields and evidence text.
    """
    evidence_index = build_evidence_index(evidence_units)
    verified_keys = Counter(canonical_rule_key(rule) for rule in verified_rules)
    candidate_keys = Counter(canonical_rule_key(candidate) for candidate in rule_candidates)

    items = [
        _intelligence_item(
            rule,
            evidence_index,
            verified_keys=verified_keys,
            candidate_keys=candidate_keys,
            limit_per_rule=limit_per_rule,
            bundle_size=bundle_size,
        )
        for rule in review_rules
    ]
    items.sort(
        key=lambda item: (
            not item["safe_retry"],
            -item["bundle_score"],
            item["rule_id"],
        )
    )
    action_counts = Counter(item["next_action"] for item in items)
    category_counts = Counter(_primary_category(item) for item in items)
    missing_field_counts = Counter(
        field for item in items for field in item.get("bundle_missing_fields", [])
    )
    return {
        "purpose": "Unified evidence ranking and bundle suggestions for review rules. Advisory only; verifier decisions are unchanged.",
        "review_rule_count": len(review_rules),
        "evidence_index_count": len(evidence_index),
        "safe_retry_count": sum(1 for item in items if item["safe_retry"]),
        "blocked_count": sum(1 for item in items if item["blocked_by"]),
        "items": items,
        "summary": {
            "next_action_counts": counter_rows(action_counts),
            "primary_category_counts": counter_rows(category_counts),
            "missing_field_counts": counter_rows(missing_field_counts),
        },
        "notes": [
            "Evidence intelligence ranks and bundles existing evidence only.",
            "Bundle scores cannot verify a rule.",
            "A rule is promotion-ready only after deterministic bundle rerun verifies it with no risk flags.",
        ],
    }


def build_evidence_index(evidence_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Precompute deterministic evidence features once per run."""
    indexed: list[dict[str, Any]] = []
    for evidence in evidence_units:
        text = _evidence_text(evidence)
        tokens = text_words(text)
        indexed.append(
            {
                "evidence_id": str(evidence.get("evidence_id") or ""),
                "page": evidence.get("page"),
                "evidence_type": evidence.get("evidence_type"),
                "text": text,
                "tokens": sorted(tokens),
                "numbers": _numbers(text),
                "units": sorted(_visible_units(text)),
                "operator_cues": sorted(_operator_cues(text)),
                "rule_family_cues": sorted(_rule_family_cues(text)),
                "scope_words": sorted(_scope_words(text)),
                "condition_words": sorted(_condition_words(text)),
                "exception_cues": sorted(_exception_cues(text)),
                "table_context": {
                    "table_title": evidence.get("table_title"),
                    "row_header": evidence.get("row_header"),
                    "column_header": evidence.get("column_header"),
                    "cell_value": evidence.get("cell_value"),
                },
                "quality_score": float(evidence.get("evidence_quality_score") or 0.0),
                "raw": evidence,
            }
        )
    return indexed


def evidence_intelligence_markdown(report: dict[str, Any], *, limit: int = 30) -> str:
    """Render a compact human-readable evidence intelligence report."""
    lines = [
        "# Evidence Intelligence Report",
        "",
        "This report ranks and bundles evidence for review rules. It does not verify rules.",
        "",
        f"- Review rules: {report.get('review_rule_count', 0)}",
        f"- Evidence packets indexed: {report.get('evidence_index_count', 0)}",
        f"- Safe bundle rerun candidates: {report.get('safe_retry_count', 0)}",
        f"- Blocked items: {report.get('blocked_count', 0)}",
        "",
        "## Next Actions",
        "",
        *count_lines(report.get("summary", {}).get("next_action_counts", [])),
        "",
        f"## Top {limit} Items",
        "",
    ]
    for item in report.get("items", [])[:limit]:
        missing = ", ".join(item.get("bundle_missing_fields", [])) or "none"
        blocked = ", ".join(item.get("blocked_by", [])) or "none"
        lines.append(
            f"- `{item['rule_id']}` score={item['bundle_score']:.2f} "
            f"safe_retry={item['safe_retry']} action=`{item['next_action']}` "
            f"missing={missing} blocked_by={blocked}"
        )
    return "\n".join(lines) + "\n"


def _intelligence_item(
    rule: dict[str, Any],
    evidence_index: list[dict[str, Any]],
    *,
    verified_keys: Counter[str],
    candidate_keys: Counter[str],
    limit_per_rule: int,
    bundle_size: int,
) -> dict[str, Any]:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    current_evidence_id = str(source.get("evidence_id") or "")
    scored = [_score_evidence(rule, evidence) for evidence in evidence_index]
    scored = [item for item in scored if item["raw_score"] > 0 or item["evidence_id"] == current_evidence_id]
    scored.sort(
        key=lambda item: (
            item["evidence_id"] != current_evidence_id,
            -item["raw_score"],
            item["evidence_id"],
        )
    )
    top = scored[:limit_per_rule]
    bundle = _best_bundle(scored, current_evidence_id=current_evidence_id, bundle_size=bundle_size)
    supported_fields = sorted({field for evidence in bundle for field in evidence.get("supported_fields", [])})
    missing_fields = _bundle_missing_fields(rule, supported_fields)
    blocked_by = _blocked_by(rule, bundle, missing_fields)
    bundle_score = _bundle_score(bundle, missing_fields, blocked_by)
    # safe_retry >= 0.62 mirrors evidence_repair.RETRY_CONFIDENCE_THRESHOLD: it
    # marks "worth feeding back through the deterministic verifier", not "looks
    # verified". The hard conditions (no blockers, no missing critical field)
    # do the real gating; the score only filters out weak bundles.
    safe_retry = bool(bundle and bundle_score >= 0.62 and not blocked_by and not (CRITICAL_FIELDS & set(missing_fields)))
    key = str(rule.get("canonical_rule_key") or canonical_rule_key(rule))
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "candidate_id": str(rule.get("candidate", {}).get("candidate_id") or ""),
        "canonical_rule_key": key,
        "same_key_candidate_count": candidate_keys.get(key, 0),
        "same_key_verified_count": verified_keys.get(key, 0),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "condition": rule.get("condition"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "support_gaps": list(rule.get("support_gaps", [])),
        "current_evidence_id": current_evidence_id,
        "top_evidence": [_public_evidence_row(item) for item in top],
        "best_evidence_bundle": [_public_evidence_row(item) for item in bundle],
        "bundle_score": bundle_score,
        "bundle_supported_fields": supported_fields,
        "bundle_missing_fields": missing_fields,
        "safe_retry": safe_retry,
        "blocked_by": blocked_by,
        "next_action": _next_action(rule, safe_retry, missing_fields, blocked_by),
        "candidate_sentence": candidate_sentence(rule),
        "original_evidence_sentence": _short_quote(source.get("evidence_text") or ""),
        "bundle_sentence": _bundle_sentence(bundle),
    }


def _score_evidence(rule: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    text = str(evidence.get("text") or "")
    tokens = set(evidence.get("tokens", []))
    reasons: list[str] = []
    supported_fields: list[str] = []
    raw = 0.0

    if _contains_value(text, rule.get("value")):
        raw += 4.0
        reasons.append("value_match")
        supported_fields.append("value")
    if _contains_unit(text, rule.get("unit")):
        raw += 2.0
        reasons.append("unit_match")
        supported_fields.append("unit")
    if _operator_supported(rule.get("operator"), rule.get("constraint_type"), evidence):
        raw += 2.0
        reasons.append("operator_cue")
        supported_fields.append("operator")
    if _rule_object_supported(rule.get("rule_object"), evidence):
        raw += 3.0
        reasons.append("rule_object_cue")
        supported_fields.append("rule_object")

    scope_overlap = _overlap(rule.get("constraint_scope"), tokens)
    applies_overlap = _overlap(rule.get("applies_to"), tokens)
    condition_overlap = _overlap(rule.get("condition"), tokens)
    if scope_overlap:
        raw += min(2.0, scope_overlap * 0.8)
        reasons.append("scope_overlap")
        supported_fields.append("scope")
    if applies_overlap:
        raw += min(1.5, applies_overlap * 0.5)
        reasons.append("applies_to_overlap")
        supported_fields.append("applies_to")
    if condition_overlap:
        raw += min(3.0, condition_overlap * 0.9)
        reasons.append("condition_overlap")
        supported_fields.append("condition")

    if evidence.get("exception_cues"):
        raw -= 1.5
        reasons.append("exception_warning")
    wrong_family = _wrong_family(rule.get("rule_object"), evidence)
    if wrong_family:
        raw -= 2.0
        reasons.append(f"wrong_rule_family:{wrong_family}")
    raw += min(1.0, float(evidence.get("quality_score") or 0.0))
    return {
        "evidence_id": evidence["evidence_id"],
        "page": evidence.get("page"),
        "evidence_type": evidence.get("evidence_type"),
        "raw_score": round(max(0.0, raw), 3),
        "bundle_confidence": round(min(1.0, max(0.0, raw) / 13.0), 3),
        "match_reasons": reasons,
        "supported_fields": sorted(set(supported_fields)),
        "exception_cues": list(evidence.get("exception_cues", [])),
        "evidence_quote": _short_quote(text),
        "raw": evidence.get("raw", {}),
    }


def _best_bundle(
    scored: list[dict[str, Any]],
    *,
    current_evidence_id: str,
    bundle_size: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    current = next((item for item in scored if item["evidence_id"] == current_evidence_id), None)
    if current:
        selected.append(current)
    for item in sorted(scored, key=lambda row: (-row["raw_score"], row["evidence_id"])):
        if item["evidence_id"] == current_evidence_id:
            continue
        if item["raw_score"] <= 0:
            continue
        if not item.get("supported_fields"):
            # A packet can be raw_score > 0 on its quality bonus alone while
            # matching ZERO candidate fields. Such packets must never join a
            # bundle: their text would later be concatenated into the synthetic
            # bundle evidence, injecting unrelated bylaw text into the rerun.
            continue
        selected.append(item)
        if len(selected) >= bundle_size:
            break
    return selected


def _bundle_missing_fields(rule: dict[str, Any], supported_fields: list[str]) -> list[str]:
    supported = set(supported_fields)
    expected = {"rule_object"}
    if rule.get("value") not in (None, ""):
        expected.add("value")
    if rule.get("unit") not in (None, ""):
        expected.add("unit")
    if rule.get("operator") not in (None, ""):
        expected.add("operator")
    for gap in rule.get("support_gaps", []):
        field = FIELD_BY_GAP.get(str(gap))
        if field:
            expected.add(field)
    if rule.get("condition") not in (None, ""):
        expected.add("condition")
    return sorted(expected - supported)


def _blocked_by(rule: dict[str, Any], bundle: list[dict[str, Any]], missing_fields: list[str]) -> list[str]:
    gaps = set(rule.get("support_gaps", []))
    blocked: list[str] = []
    for gap in sorted(gaps & HARD_BLOCKER_GAPS):
        blocked.append(f"support_gap:{gap}")
    if "exception" in missing_fields:
        blocked.append("unresolved_exception_or_override")
    if any(item.get("exception_cues") for item in bundle):
        blocked.append("bundle_contains_exception_or_covenant_language")
    critical_missing = sorted(CRITICAL_FIELDS & set(missing_fields))
    if critical_missing:
        blocked.append("missing_critical_fields:" + ",".join(critical_missing))
    return blocked


def _bundle_score(bundle: list[dict[str, Any]], missing_fields: list[str], blocked_by: list[str]) -> float:
    if not bundle:
        return 0.0
    # /7.0 = number of scoreable field types (value, unit, operator, rule_object,
    # scope, applies_to, condition): field coverage as a fraction of everything a
    # bundle could possibly prove.
    field_bonus = len({field for item in bundle for field in item.get("supported_fields", [])}) / 7.0
    # /18.0 = max attainable raw score for one packet (4 value + 2 unit + 2
    # operator + 3 rule_object + 2 scope + 1.5 applies_to + 3 condition + 1
    # quality, with penalties at zero, rounded up to a stable constant). Summing
    # over the bundle and capping at 1.0 means the score saturates once the core
    # value/rule_object/unit/operator matches land, without requiring every
    # context bonus on every member.
    evidence_bonus = min(1.0, sum(float(item.get("raw_score") or 0.0) for item in bundle) / 18.0)
    penalty = 0.08 * len(missing_fields) + 0.15 * len(blocked_by)
    return round(max(0.0, min(1.0, (field_bonus * 0.55 + evidence_bonus * 0.45) - penalty)), 3)


def _next_action(
    rule: dict[str, Any],
    safe_retry: bool,
    missing_fields: list[str],
    blocked_by: list[str],
) -> str:
    gaps = set(rule.get("support_gaps", []))
    if safe_retry:
        return "rerun_with_evidence_bundle"
    if any("exception" in item or "covenant" in item for item in blocked_by) or "unresolved_exception_cue" in gaps:
        return "human_legal_review"
    if {"value", "unit", "operator", "rule_object"} & set(missing_fields):
        return "retry_with_better_evidence"
    if {"scope", "applies_to", "condition"} & set(missing_fields):
        return "inspect_context_fields"
    if blocked_by:
        return "blocked_review"
    return "defer_low_priority"


def _primary_category(item: dict[str, Any]) -> str:
    if item.get("safe_retry"):
        return "bundle_safe_retry"
    if item.get("blocked_by"):
        return "blocked"
    missing = set(item.get("bundle_missing_fields", []))
    if missing & CRITICAL_FIELDS:
        return "critical_field_missing"
    if missing & CONTEXT_FIELDS:
        return "context_missing"
    return "general_review"


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
            "inherited_parent_context",
        )
    )


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))


def _visible_units(text: str) -> set[str]:
    lower = text.lower()
    found: set[str] = set()
    for key, aliases in UNIT_ALIASES.items():
        for alias in aliases:
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lower):
                found.add(key)
                break
    return found


def _operator_cues(text: str) -> set[str]:
    lower = text.lower()
    cues: set[str] = set()
    if any(cue in lower for cue in ("maximum", "not exceed", "up to", "limited to")):
        cues.add("<=")
    if any(cue in lower for cue in ("minimum", "not less", "at least", "shall have", "must have")):
        cues.add(">=")
    if any(cue in lower for cue in ("more than", "greater than", "exceeds")):
        cues.add(">")
    if any(cue in lower for cue in ("less than", "fewer than", "under")):
        cues.add("<")
    if any(cue in lower for cue in ("permitted", "allowed")):
        cues.add("allowed")
    if any(cue in lower for cue in ("required", "shall", "must")):
        cues.add("required")
    return cues


def _rule_family_cues(text: str) -> set[str]:
    lower = text.lower()
    found: set[str] = set()
    for rule_object, phrase_groups in [*PLAIN_ONLY_RULE_OBJECT_PATTERNS, *TEXT_RULE_OBJECT_PATTERNS]:
        if any(all(phrase in lower for phrase in group) for group in phrase_groups):
            found.add(rule_object)
    return found


def _scope_words(text: str) -> set[str]:
    return {
        word
        for word in text_words(text)
        if len(word) > 2
        and word
        not in {
            "maximum",
            "minimum",
            "shall",
            "must",
            "have",
            "with",
            "than",
            "not",
            "and",
            "the",
            "for",
        }
    }


def _condition_words(text: str) -> set[str]:
    words = _scope_words(text)
    condition_cues = {
        "flat",
        "sloping",
        "roof",
        "heritage",
        "accessory",
        "principal",
        "rear",
        "front",
        "lane",
        "street",
        "covenant",
        "exception",
    }
    return words & condition_cues


def _exception_cues(text: str) -> set[str]:
    # Shared preamble-aware detection: a packet whose only cue is a resolved
    # "unless otherwise referenced in ..." default-rule preamble is NOT
    # penalized out of bundles, while genuine exclusion/override wording is.
    found = unresolved_exception_cues(text)
    if "section 219 covenant" in text.lower():
        found.add("covenant")
    return found


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
    lower = text.lower()
    aliases = UNIT_ALIASES.get(key, [str(unit or "").lower()])
    return any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lower) for alias in aliases)


def _operator_supported(operator: Any, constraint_type: Any, evidence: dict[str, Any]) -> bool:
    direction = f"{operator or ''} {constraint_type or ''}".lower()
    cues = set(evidence.get("operator_cues", []))
    if any(token in direction for token in ("<=", "maximum", "max", "not_exceed")):
        return "<=" in cues
    if any(token in direction for token in (">=", "minimum", "min", "at_least")):
        return ">=" in cues
    if ">" in direction:
        return ">" in cues
    if "<" in direction:
        return "<" in cues
    if "allowed" in direction or "permitted" in direction:
        return "allowed" in cues
    if "required" in direction:
        return "required" in cues
    return False


def _rule_object_supported(rule_object: Any, evidence: dict[str, Any]) -> bool:
    rule_object_text = str(rule_object or "")
    if not rule_object_text:
        return False
    text = str(evidence.get("text") or "").lower()
    plain = rule_object_text.replace("_", " ")
    return (
        rule_object_text in text
        or plain in text
        or rule_object_text in set(evidence.get("rule_family_cues", []))
    )


def _wrong_family(rule_object: Any, evidence: dict[str, Any]) -> str:
    expected = str(rule_object or "")
    families = set(evidence.get("rule_family_cues", []))
    if expected in families or not families:
        return ""
    if expected in {"height", "storeys"} and families & {"height", "storeys"}:
        return ""
    return sorted(families)[0]


def _overlap(value: Any, evidence_words: set[str]) -> int:
    if value in (None, ""):
        return 0
    claim_words = {
        word
        for word in text_words(str(value))
        if len(word) > 2 and word not in {"and", "the", "for", "all", "building", "buildings"}
    }
    return len(claim_words & evidence_words)


def _bundle_sentence(bundle: list[dict[str, Any]]) -> str:
    if not bundle:
        return "No stronger evidence bundle was found."
    parts = []
    for item in bundle:
        fields = ", ".join(item.get("supported_fields", [])) or "no critical fields"
        parts.append(f"{item.get('evidence_id')} supports {fields}")
    return "; ".join(parts) + "."


def _public_evidence_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": item.get("evidence_id"),
        "page": item.get("page"),
        "evidence_type": item.get("evidence_type"),
        "raw_score": item.get("raw_score"),
        "bundle_confidence": item.get("bundle_confidence"),
        "match_reasons": list(item.get("match_reasons", [])),
        "supported_fields": list(item.get("supported_fields", [])),
        "exception_cues": list(item.get("exception_cues", [])),
        "evidence_quote": item.get("evidence_quote"),
    }


def _short_quote(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
