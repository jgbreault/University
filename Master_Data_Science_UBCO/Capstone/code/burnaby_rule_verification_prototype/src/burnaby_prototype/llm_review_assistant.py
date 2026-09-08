"""Advisory LLM assistant for the human review queue — NEVER a verifier.

This module makes the 66-item review queue actionable for a human reviewer. For
each review rule it produces a short brief: *why* the rule was not verified and
the single most likely missing field value, drawn strictly from the cited
evidence. It is purely advisory.

ARCHITECTURAL BOUNDARY (enforced by a test): this module imports nothing from
the verifier (`verification`, `decision_policy`, `slim_pipeline`) and is imported
by nothing in the core pipeline. Its output is written to its own
`review_assistant.json` and is never read by `decision_policy`. An LLM can never
move a rule into `verified_rules.json` — only the deterministic verifier does
that.

OFFLINE-SAFE: with no Anthropic client (no SDK / no API key), every function
falls back to a deterministic heuristic brief synthesized from the review
fields the triage layer already produced (`support_gaps`, `review_category`,
`blocking_reason`, `suggested_fix`). The core pipeline and the test suite never
need network access or a key.
"""

from __future__ import annotations

from typing import Any


# Per the claude-api guidance, default to the most capable model; the user can
# opt into a cheaper model (claude-sonnet-4-6 / claude-haiku-4-5) via --model.
DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM_PROMPT = (
    "You are a zoning-rule REVIEW ASSISTANT. A separate deterministic verifier has already "
    "decided this candidate rule is not yet verifiable and routed it to human review. "
    "Your job is advisory only: (1) explain in one or two plain sentences WHY it is blocked, "
    "and (2) propose the single most likely missing field value, drawn STRICTLY from the cited "
    "evidence text. You do NOT decide whether the rule is correct or verified — never say a rule "
    "should be verified or approved. If the evidence does not support a confident fix, say so and "
    "return proposed_value null. Respond with JSON only, matching the requested schema."
)

# Closed JSON schema for structured output (output_config.format). Only
# JSON-Schema features the API supports: enum, additionalProperties:false,
# basic types — no numeric min/max constraints.
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["why_blocked", "likely_fix", "confidence"],
    "properties": {
        "why_blocked": {"type": "string"},
        "likely_fix": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "proposed_value", "rationale"],
            "properties": {
                "field": {"enum": ["applies_to", "condition", "constraint_scope", "operator", "none"]},
                "proposed_value": {"type": ["string", "null"]},
                "rationale": {"type": "string"},
            },
        },
        "confidence": {"type": "number"},
    },
}

# support_gap -> the review field a second look would most likely repair.
_GAP_TO_FIELD = {
    "applies_to_not_supported": "applies_to",
    "table_applies_to_not_supported": "applies_to",
    "text_condition_not_supported": "condition",
    "table_condition_not_supported": "condition",
    "constraint_scope_not_supported": "constraint_scope",
    "operator_not_supported": "operator",
}


def review_context(rule: dict[str, Any]) -> dict[str, Any]:
    """Extract the minimal, evidence-grounded context shown to the assistant."""
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    return {
        "rule_id": rule.get("rule_id"),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "condition": rule.get("condition"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "support_gaps": list(rule.get("support_gaps", [])),
        "review_category": rule.get("review_category"),
        "blocking_reason": rule.get("blocking_reason") or rule.get("review_reason"),
        "evidence_quote": source.get("evidence_text") or rule.get("review_reason"),
        "source_page": source.get("page"),
    }


def build_messages(rule: dict[str, Any]) -> tuple[str, str]:
    """Return (system, user_text) for the LLM call. Deterministic and testable."""
    ctx = review_context(rule)
    gaps = ", ".join(ctx["support_gaps"]) or "none"
    user_text = (
        f"Rule {ctx['rule_id']} ({ctx['rule_object']}): operator={ctx['operator']!r} "
        f"value={ctx['value']!r} {ctx['unit'] or ''}, applies_to={ctx['applies_to']!r}, "
        f"scope={ctx['constraint_scope']!r}, condition={ctx['condition']!r}.\n"
        f"Verifier support gaps: {gaps}.\n"
        f"Review category: {ctx['review_category']}.\n"
        f"Cited evidence: \"{ctx['evidence_quote']}\"\n\n"
        "Explain why it is blocked and propose the single most likely missing field "
        "value from the evidence (or null if unsupported)."
    )
    return _SYSTEM_PROMPT, user_text


def heuristic_brief(rule: dict[str, Any]) -> dict[str, Any]:
    """Deterministic, no-API brief from the triage fields already on the rule."""
    ctx = review_context(rule)
    gaps = ctx["support_gaps"]
    target_field = next((_GAP_TO_FIELD[g] for g in gaps if g in _GAP_TO_FIELD), "none")
    why = ctx["blocking_reason"] or rule.get("review_reason") or "held for review"
    fix_hint = str(rule.get("suggested_fix") or "").strip()
    if target_field == "none":
        rationale = "No single missing-context field dominates; needs human inspection."
    else:
        rationale = f"Largest unmet gap maps to '{target_field}'; check the cited evidence for it."
        if fix_hint:
            rationale += f" Triage guidance: {fix_hint}"
    return {
        "rule_id": ctx["rule_id"],
        "source": "heuristic",
        "why_blocked": f"Verifier held this rule because: {why}.",
        "likely_fix": {
            "field": target_field,
            # The schema promises a FIELD VALUE drawn from the evidence (or
            # null). The heuristic cannot ground a value in evidence — triage
            # guidance is a sentence, not a value — so it always proposes null
            # and keeps the guidance in the rationale.
            "proposed_value": None,
            "rationale": rationale,
        },
        "confidence": 0.0,  # heuristic makes no probabilistic claim
        "advisory_only": True,
    }


def assist_review_item(
    rule: dict[str, Any],
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Return an advisory brief for one review rule.

    With no client, returns the deterministic heuristic brief. With a client,
    calls Claude with structured output and merges the result; on any API error
    it falls back to the heuristic so the run never hard-fails.
    """
    if client is None:
        return heuristic_brief(rule)

    system, user_text = build_messages(rule)
    try:
        import json

        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        parsed = json.loads(text)
    except Exception as exc:  # pragma: no cover - network/SDK path
        brief = heuristic_brief(rule)
        brief["llm_error"] = f"{type(exc).__name__}: {exc}"
        return brief

    return {
        "rule_id": rule.get("rule_id"),
        "source": "llm",
        "model": model,
        "why_blocked": parsed.get("why_blocked"),
        "likely_fix": parsed.get("likely_fix"),
        "confidence": parsed.get("confidence"),
        "advisory_only": True,
    }


def run_review_assistant(
    review_rules: list[dict[str, Any]],
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
    limit: int | None = None,
) -> dict[str, Any]:
    """Produce advisory briefs for the review queue. Never mutates input rules."""
    rules = review_rules if limit is None else review_rules[:limit]
    items = [assist_review_item(rule, client=client, model=model) for rule in rules]
    return {
        "mode": "llm" if client is not None else "heuristic",
        "model": model if client is not None else None,
        "notes": [
            "Advisory only. These suggestions are NOT verification decisions.",
            "The deterministic verifier alone decides verified/review/rejected.",
            "An LLM suggestion must be human-confirmed and re-run through the verifier to take effect.",
        ],
        "item_count": len(items),
        "items": items,
    }
