"""Shared reviewer-facing text helpers for the advisory layer.

Before this module existed, ``review_router``, ``review_resolution``,
``evidence_intelligence``, and ``semantic_review`` each carried private copies
of the same sentence/counter helpers, and the candidate-sentence defaults had
already drifted between copies. These helpers are presentation-only: they
render advisory report strings and never touch verification decisions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def candidate_sentence(rule: dict[str, Any]) -> str:
    """Render one plain-English sentence for a candidate rule claim."""
    subject = rule.get("applies_to") or rule.get("constraint_scope") or "The rule"
    rule_object = str(rule.get("rule_object") or "constraint").replace("_", " ")
    operator = rule.get("operator") or rule.get("constraint_type") or "has value"
    value = rule.get("value")
    unit = rule.get("unit") or ""
    condition = f" when {rule.get('condition')}" if rule.get("condition") else ""
    if value in (None, ""):
        return f"{subject} has a {rule_object} rule{condition}."
    return f"{subject} has {rule_object} {operator} {value} {unit}{condition}.".replace("  ", " ")


def evidence_sentence(source: dict[str, Any]) -> str:
    """Render the cited evidence text, truncated for report readability."""
    text = str(source.get("evidence_text") or "").strip()
    if not text:
        return "No cited evidence text is available."
    return text if len(text) <= 260 else text[:257].rstrip() + "..."


def counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    """Return ``[{"name": ..., "count": ...}]`` rows for a Counter."""
    return [{"name": name, "count": count} for name, count in counter.most_common()]


def count_lines(rows: list[dict[str, Any]]) -> list[str]:
    """Render counter rows as markdown bullet lines."""
    if not rows:
        return ["- none"]
    return [f"- `{row['name']}`: {row['count']}" for row in rows]
