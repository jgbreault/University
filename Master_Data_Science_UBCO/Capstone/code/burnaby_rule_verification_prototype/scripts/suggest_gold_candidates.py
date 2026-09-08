#!/usr/bin/env python3
"""Active-learning gold curation: which rules should a human label FIRST?

Uncertainty sampling over signals the pipeline already emits: rules whose
evidence_strength sits near the decision boundary, whose advisory signals
disagree, or whose families are under-represented in the existing gold set
give the benchmark the most information per minute of human labeling time.
Read-only; prints a ranked worklist.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def uncertainty(rule: dict) -> float:
    """Higher = more informative to label. Deterministic, signal-based."""
    strength = float(rule.get("evidence_strength") or 0.0)
    boundary = 1.0 - abs(strength - 0.5) * 2.0  # peak at 0.5, zero at 0/1
    checks = rule.get("support_checks", {}) or {}
    passed = sum(1 for value in checks.values() if value)
    total = len(checks) or 1
    near_miss = passed / total  # mostly-passing rules are decision-relevant
    semantic = rule.get("semantic_match") or {}
    disagreement = 0.3 if semantic.get("blockers") else 0.0
    return round(0.5 * boundary + 0.4 * near_miss + disagreement, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="calgary_rcg")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    out_dir = ROOT / "outputs" / f"{args.city}_slim_pipeline5_registry"
    gold_path = ROOT / "benchmark" / "gold" / f"{args.city}_gold_rules.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8")) if gold_path.exists() else []
    gold_families = Counter(str(g.get("rule_object")) for g in gold)

    rows = []
    for bucket, weight in (("review_needed", 1.0), ("verified_rules", 0.8), ("rejected_rules", 0.5)):
        path = out_dir / f"{bucket}.json"
        if not path.exists():
            continue
        for rule in json.loads(path.read_text(encoding="utf-8")):
            family = str(rule.get("rule_object"))
            coverage_bonus = 0.25 if gold_families.get(family, 0) == 0 else 0.0
            rows.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "bucket": bucket,
                    "rule_object": family,
                    "value": rule.get("value"),
                    "unit": rule.get("unit"),
                    "score": round(weight * uncertainty(rule) + coverage_bonus, 4),
                    "evidence": str((rule.get("source") or {}).get("evidence_text") or "")[:110],
                }
            )
    rows.sort(key=lambda r: (-r["score"], r["rule_id"]))
    print(f"[gold-suggest] {args.city}: label these first (existing gold: {len(gold)} rules)")
    for row in rows[: args.top]:
        print(f"  {row['score']:.3f}  {row['bucket']:<14} {row['rule_id']:<22} {row['rule_object']:<20} {row['value']} {row['unit'] or ''}")
        print(f"         {row['evidence']}")


if __name__ == "__main__":
    main()
