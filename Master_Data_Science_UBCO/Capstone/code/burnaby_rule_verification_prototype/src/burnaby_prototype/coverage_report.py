"""Coverage and gap summaries for verifier outputs.

This module is reporting-only. It never participates in verification and never
promotes a rule. The slim pipeline uses it without answer-key data to summarize
the current decision buckets; dashboards and benchmark tools may pass labeled
rules and benchmark reports to add coverage/gap context after verification has
completed.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


MATRIX_COLUMNS: list[tuple[str, str]] = [
    ("rowhouse", "Rowhouse (1-3 units)"),
    ("ssmu_1_2", "SSMU 1-2 units"),
    ("ssmu_3_4", "SSMU 3-4 units"),
    ("ssmu_5_6_ftn", "SSMU 5-6 units (FTN only)"),
]

MATRIX_ROW_ORDER = [
    "dwelling_units",
    "lot_area",
    "lot_coverage",
    "impervious_surface",
    "height",
    "storeys",
    "setback",
    "building_separation",
]

_FOOTNOTE_SUFFIX_RE = re.compile(r"\s*\.\d+\s*$")


def plain_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("_", " ").replace("-", " ").capitalize()


def gap_codes(rule: dict[str, Any]) -> list[str]:
    gaps = rule.get("support_gaps")
    if not gaps:
        gaps = rule.get("review_reasons") or []
    return [str(gap) for gap in gaps]


def applicability_buckets(rule: dict[str, Any]) -> set[str]:
    """Map a rule onto the Burnaby 101.4 matrix-style dwelling buckets.

    The function is harmless for non-Burnaby cities: a rule with no dwelling
    signal spans all columns only when a matrix view is explicitly requested.
    """
    buckets: set[str] = set()
    block = rule.get("applicability") or {}
    for selector in block.get("selectors") or []:
        dwelling = selector.get("dwelling_type")
        unit_range = selector.get("unit_range") or {}
        low, high = unit_range.get("min"), unit_range.get("max")
        exact = unit_range.get("exact")
        if dwelling == "rowhouse":
            buckets.add("rowhouse")
        elif dwelling == "small_scale_multi_unit" or low is not None or exact is not None:
            if (low, high) == (1, 2) or exact in (1, 2):
                buckets.add("ssmu_1_2")
            elif (low, high) == (3, 4) or exact in (3, 4):
                buckets.add("ssmu_3_4")
            elif (low, high) == (5, 6) or exact in (5, 6):
                buckets.add("ssmu_5_6_ftn")
            elif dwelling:
                buckets.update({"ssmu_1_2", "ssmu_3_4", "ssmu_5_6_ftn"})
    if buckets:
        return buckets

    text = _FOOTNOTE_SUFFIX_RE.sub("", f"{rule.get('applies_to') or ''}; {rule.get('condition') or ''}").lower()
    if "rowhouse" in text:
        buckets.add("rowhouse")
    if "1 to 2" in text:
        buckets.add("ssmu_1_2")
    if "3 to 4" in text:
        buckets.add("ssmu_3_4")
    if "5 to 6" in text or "frequent transit" in text or "ftn" in text:
        buckets.add("ssmu_5_6_ftn")
    if buckets:
        return buckets
    return {key for key, _ in MATRIX_COLUMNS}


def matrix_row_key(rule: dict[str, Any]) -> tuple[str, str]:
    family = str(rule.get("rule_object") or "")
    scope = str(rule.get("constraint_scope") or "")
    text = f"{rule.get('applies_to') or ''} {rule.get('condition') or ''}".lower()
    qualifier = ""
    if family in {"height", "storeys"}:
        for role in ("front", "rear", "accessory"):
            if role in text or role in scope:
                qualifier = role
                break
        if family == "height":
            if "sloping" in text:
                qualifier += " sloping"
            elif "flat" in text:
                qualifier += " flat"
    elif family in {"setback", "building_separation"}:
        qualifier = scope.replace("_", " ")
    return (family, qualifier.strip())


def matrix_cells(
    verified: list[dict[str, Any]],
    review: list[dict[str, Any]],
    gold_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a matrix-grid summary for Burnaby-style development tables."""
    gold_rules = gold_rules or []
    cells: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def add(rule: dict[str, Any], status: str) -> None:
        family = str(rule.get("rule_object") or "")
        if family not in MATRIX_ROW_ORDER:
            return
        row_key = matrix_row_key(rule)
        for bucket in applicability_buckets(rule):
            slot = cells.setdefault(row_key, {}).get(bucket)
            rank = {"verified": 0, "review": 1, "missing": 2}
            if slot is None or rank[status] < rank[slot["status"]]:
                value = f"{rule.get('value') or ''} {rule.get('unit') or ''}".strip()
                reason = ""
                if status == "review":
                    reason = "; ".join(gap_codes(rule)[:2])
                if status == "missing":
                    reason = "in gold, not yet proven"
                cells.setdefault(row_key, {})[bucket] = {
                    "status": status,
                    "text": value or status,
                    "rule_id": str(rule.get("rule_id") or rule.get("gold_id") or ""),
                    "reason": reason,
                }

    for rule in verified:
        add(rule, "verified")
    for rule in review:
        add(rule, "review")
    for gold in gold_rules:
        add(gold, "missing")

    rows = []
    for row_key in sorted(cells, key=lambda key: (MATRIX_ROW_ORDER.index(key[0]), key[1])):
        family, qualifier = row_key
        label = plain_label(family) + (f" - {qualifier}" if qualifier else "")
        rows.append(
            {
                "label": label,
                "cells": [
                    cells[row_key].get(bucket, {"status": "na", "text": "n/a", "rule_id": "", "reason": ""})
                    for bucket, _ in MATRIX_COLUMNS
                ],
            }
        )
    return {"columns": [label for _, label in MATRIX_COLUMNS], "rows": rows}


def coverage_rows(
    *,
    rule_candidates: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    rejected_rules: list[dict[str, Any]],
    not_used_rules: list[dict[str, Any]],
    gold_rules: list[dict[str, Any]] | None = None,
    benchmark: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-family counts plus optional labeled benchmark coverage."""
    metrics = (benchmark or {}).get("rule_metrics", {})
    matched_verified = {m.get("gold_id") for m in metrics.get("matched_verified", []) if isinstance(m, dict)}
    matched_review = {m.get("gold_id") for m in metrics.get("matched_review", []) if isinstance(m, dict)}

    families: dict[str, dict[str, Any]] = {}

    def slot(family: str) -> dict[str, Any]:
        return families.setdefault(
            family,
            {
                "family": family,
                "candidates": 0,
                "verified": 0,
                "review": 0,
                "rejected": 0,
                "not_used": 0,
                "gold": 0,
                "gold_verified": 0,
                "gold_review": 0,
                "hold_reasons": Counter(),
            },
        )

    for candidate in rule_candidates:
        slot(str(candidate.get("rule_object") or "?"))["candidates"] += 1
    for bucket, rules in (
        ("verified", verified_rules),
        ("review", review_rules),
        ("rejected", rejected_rules),
        ("not_used", not_used_rules),
    ):
        for rule in rules:
            entry = slot(str(rule.get("rule_object") or "?"))
            entry[bucket] += 1
            if bucket == "review":
                for gap in gap_codes(rule)[:1]:
                    entry["hold_reasons"][gap] += 1
    for gold in gold_rules or []:
        entry = slot(str(gold.get("rule_object") or "?"))
        entry["gold"] += 1
        if gold.get("gold_id") in matched_verified:
            entry["gold_verified"] += 1
        elif gold.get("gold_id") in matched_review:
            entry["gold_review"] += 1

    rows = []
    for family, entry in sorted(families.items(), key=lambda item: -item[1]["candidates"]):
        top = entry["hold_reasons"].most_common(1)
        rows.append(
            {
                "family": plain_label(family),
                "family_key": family,
                "candidates": entry["candidates"],
                "verified": entry["verified"],
                "review": entry["review"],
                "rejected": entry["rejected"],
                "not_used": entry["not_used"],
                "top_hold_reason": plain_label(top[0][0]) if top else "",
                "top_hold_reason_code": top[0][0] if top else "",
                "gold": entry["gold"],
                "gold_verified": entry["gold_verified"],
                "gold_review": entry["gold_review"],
                "coverage": (entry["gold_verified"] / entry["gold"]) if entry["gold"] else None,
            }
        )
    return rows


def gold_gap_rows(benchmark: dict[str, Any], gold_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gold rules not proven as verified, with benchmark-derived status."""
    metrics = (benchmark or {}).get("rule_metrics", {})
    matched_verified = {m.get("gold_id"): m for m in metrics.get("matched_verified", []) if isinstance(m, dict)}
    matched_review = {m.get("gold_id"): m for m in metrics.get("matched_review", []) if isinstance(m, dict)}
    missing_entirely = set(metrics.get("missed_verified_or_review_gold_rule_ids") or [])
    rows = []
    for gold in gold_rules:
        gold_id = str(gold.get("gold_id") or "")
        if gold_id in matched_verified:
            continue
        if gold_id in missing_entirely:
            status, detail = "absent", "no candidate covers this rule - upstream extraction gap"
        elif gold_id in matched_review:
            status, detail = "review", f"covered in review as {matched_review[gold_id].get('rule_id')}"
        else:
            status, detail = "unproven", "not matched by any verified rule"
        rows.append(
            {
                "gold_id": gold_id,
                "family": plain_label(str(gold.get("rule_object") or "")),
                "family_key": str(gold.get("rule_object") or ""),
                "claim": f"{_operator_short(gold.get('operator'))} {gold.get('value') or ''} {gold.get('unit') or ''}".strip(),
                "applies_to": str(gold.get("applies_to") or ""),
                "condition": str(gold.get("condition") or ""),
                "status": status,
                "detail": detail,
            }
        )
    return rows


def build_coverage_report(
    *,
    rule_candidates: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    rejected_rules: list[dict[str, Any]],
    not_used_rules: list[dict[str, Any]],
    benchmark: dict[str, Any] | None = None,
    gold_rules: list[dict[str, Any]] | None = None,
    include_matrix: bool = False,
) -> dict[str, Any]:
    """Build the JSON artifact consumed by dashboard coverage views."""
    report = {
        "schema_version": "1.0",
        "family_rows": coverage_rows(
            rule_candidates=rule_candidates,
            verified_rules=verified_rules,
            review_rules=review_rules,
            rejected_rules=rejected_rules,
            not_used_rules=not_used_rules,
            gold_rules=gold_rules,
            benchmark=benchmark,
        ),
        "gold_gaps": gold_gap_rows(benchmark or {}, gold_rules or []) if gold_rules else [],
    }
    if include_matrix:
        report["matrix"] = matrix_cells(verified_rules, review_rules, gold_rules or [])
    return report


def _operator_short(operator: Any) -> str:
    return {
        ">=": ">=",
        "<=": "<=",
        "=": "=",
        "==": "=",
        "allowed": "allowed",
        "permitted": "permitted",
    }.get(str(operator or ""), str(operator or ""))
