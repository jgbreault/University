"""Pure text helpers that render a structured rule as a reviewer-readable sentence.

This is a LEAF module (no project imports) so both ``slim_pipeline`` and
``gis_felt_export`` can use the same sentence rendering through normal
top-level imports. Before this module existed, ``gis_felt_export`` imported
``_rule_sentence`` from ``slim_pipeline``, which forced ``slim_pipeline`` to
import ``gis_felt_export`` function-locally to dodge the resulting cycle.

These helpers carry no verification weight: they only verbalize the already
normalized candidate/rule fields for popups, CSVs, and review surfaces.
"""

from __future__ import annotations

from typing import Any


def _rule_sentence(rule: dict[str, Any]) -> str:
    subject = str(rule.get("applies_to") or "The relevant parcel or proposal item").strip()
    rule_object = str(rule.get("rule_object") or "rule").replace("_", " ")
    scope = str(rule.get("constraint_scope") or "").replace("_", " ").strip()
    value = _format_value_unit(rule.get("value"), rule.get("unit"))
    operator = _operator_phrase(rule.get("operator"), rule.get("constraint_type"), value)
    condition = str(rule.get("condition") or "").strip()
    scope_phrase = f" for {scope}" if scope else ""
    sentence = f"{subject}: {rule_object}{scope_phrase} {operator}"
    if condition:
        sentence += f" when {condition}"
    return sentence.rstrip(" .") + "."


def _format_value_unit(value: Any, unit: Any) -> str:
    if value in (None, ""):
        return ""
    unit_text = str(unit or "").strip()
    return f"{value} {unit_text}".strip()


def _operator_phrase(operator: Any, constraint_type: Any, value_text: str) -> str:
    text = f"{operator or ''} {constraint_type or ''}".lower()
    if any(token in text for token in ("<=", "maximum", "max", "not_exceed")):
        return f"must be no more than {value_text}"
    if any(token in text for token in (">=", "minimum", "min", "at_least")):
        return f"must be at least {value_text}"
    if ">" in text:
        return f"must be more than {value_text}"
    if "<" in text:
        return f"must be less than {value_text}"
    if any(token in text for token in ("allowed", "permitted")):
        return "is permitted" if not value_text else f"is permitted with value {value_text}"
    if "required" in text:
        return "is required" if not value_text else f"is required above {value_text}"
    return f"has value {value_text}" if value_text else "is claimed"
