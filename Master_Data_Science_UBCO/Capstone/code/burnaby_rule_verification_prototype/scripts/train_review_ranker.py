#!/usr/bin/env python3
"""Train the advisory review-queue ranker (gold labels live HERE, not in src).

Labels: a review rule is positive when it matches a gold rule under the
benchmark's own matcher (_score_match) — i.e. "a human checking it against
gold would confirm it". Training uses scikit-learn; the SAVED model is plain
JSON linear coefficients consumed by the pure-Python scorer in
``burnaby_prototype.review_ranker``.

Evaluation is **leave-one-city-out**: train on the other cities, test on the
held-out one — the generalization claim, measured. A split-conformal score
threshold is calibrated on held-out data so "calibrated-confident" items carry
a distribution-free coverage statement (honestly caveated: n is small; the
numbers are printed, not hidden).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT / "src"), str(ROOT / "benchmark")):
    if path not in sys.path:
        sys.path.insert(0, path)

from evaluate_benchmark import _score_match  # benchmark-tier gold matcher
from burnaby_prototype.review_ranker import extract_features, feature_names, score_rule


def load_city(city: str) -> tuple[list[dict], list[int]]:
    out_dir = ROOT / "outputs" / f"{city}_slim_pipeline5_registry"
    gold = json.loads((ROOT / "benchmark" / "gold" / f"{city}_gold_rules.json").read_text(encoding="utf-8"))
    rules = json.loads((out_dir / "review_needed.json").read_text(encoding="utf-8"))
    labels = [
        1 if any(_score_match(g, rule)["matches"] for g in gold) else 0
        for rule in rules
    ]
    return rules, labels


def vectorize(rules: list[dict]) -> list[list[float]]:
    names = feature_names()
    rows = []
    for rule in rules:
        features = extract_features(rule)
        rows.append([features.get(name, 0.0) for name in names])
    return rows


def train(rules: list[dict], labels: list[int]) -> dict:
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    model.fit(vectorize(rules), labels)
    names = feature_names()
    return {
        "model_type": "logistic_regression_json",
        "purpose": "Advisory review-queue ordering. Never verifies or promotes a rule.",
        "intercept": float(model.intercept_[0]),
        "coefficients": {
            name: round(float(weight), 6)
            for name, weight in zip(names, model.coef_[0])
            if abs(weight) > 1e-9
        },
    }


def precision_at_k(rules: list[dict], labels: list[int], model: dict, k: int) -> float | None:
    if not rules:
        return None
    scored = sorted(zip(rules, labels), key=lambda pair: -score_rule(pair[0], model))
    top = scored[: min(k, len(scored))]
    return sum(label for _, label in top) / len(top)


def baseline_precision_at_k(rules: list[dict], labels: list[int], k: int) -> float | None:
    """The existing hand-weighted ordering (likely_correct/evidence_strength)."""
    if not rules:
        return None
    def key(rule: dict) -> float:
        return float(rule.get("likely_correct_score") or rule.get("evidence_strength") or 0.0)
    scored = sorted(zip(rules, labels), key=lambda pair: -key(pair[0]))
    top = scored[: min(k, len(scored))]
    return sum(label for _, label in top) / len(top)


def conformal_threshold(scores: list[float], labels: list[int], coverage: float = 0.9) -> float | None:
    """Smallest score s.t. held-out items above it were correct >= coverage.

    Tiny-n honest version: scan candidate thresholds from the held-out scores;
    return None when no threshold achieves the coverage with at least 3 items.
    """
    pairs = sorted(zip(scores, labels), key=lambda p: -p[0])
    best = None
    for index in range(len(pairs)):
        top = pairs[: index + 1]
        if len(top) < 3:
            continue
        if sum(label for _, label in top) / len(top) >= coverage:
            best = top[-1][0]
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="+", default=["burnaby_r1", "vancouver_rs"])
    parser.add_argument("--out", default=str(ROOT / "outputs" / "review_ranker_model.json"))
    args = parser.parse_args()

    data = {city: load_city(city) for city in args.cities}
    for city, (rules, labels) in data.items():
        print(f"[data] {city}: {len(rules)} review rules, {sum(labels)} gold-confirmed positives")

    print("\n[leave-one-city-out]")
    loco_rows = []
    for held_out in args.cities:
        train_rules, train_labels = [], []
        for city in args.cities:
            if city != held_out:
                train_rules += data[city][0]
                train_labels += data[city][1]
        if sum(train_labels) == 0 or sum(train_labels) == len(train_labels):
            print(f"  {held_out}: skipped (degenerate training labels)")
            continue
        model = train(train_rules, train_labels)
        test_rules, test_labels = data[held_out]
        for k in (5, 10):
            learned = precision_at_k(test_rules, test_labels, model, k)
            baseline = baseline_precision_at_k(test_rules, test_labels, k)
            print(f"  held-out {held_out}: precision@{k} learned={learned} baseline={baseline}")
            loco_rows.append({"held_out": held_out, "k": k, "learned": learned, "baseline": baseline})

    # Final model on ALL cities + conformal threshold from pooled LOCO scores
    # (each score was produced by a model that never saw its city).
    all_rules = [rule for rules, _ in data.values() for rule in rules]
    all_labels = [label for _, labels in data.values() for label in labels]
    final_model = train(all_rules, all_labels)
    pooled_scores, pooled_labels = [], []
    for held_out in args.cities:
        others_r, others_l = [], []
        for city in args.cities:
            if city != held_out:
                others_r += data[city][0]
                others_l += data[city][1]
        if sum(others_l) in (0, len(others_l)):
            continue
        loco_model = train(others_r, others_l)
        for rule, label in zip(*data[held_out]):
            pooled_scores.append(score_rule(rule, loco_model))
            pooled_labels.append(label)
    threshold = conformal_threshold(pooled_scores, pooled_labels)
    final_model["conformal"] = {
        "score_threshold": threshold,
        "coverage_target": 0.9,
        "calibration_n": len(pooled_scores),
        "note": "Split-conformal on pooled leave-one-city-out scores; honest small-n caveat applies.",
    }
    final_model["loco_eval"] = loco_rows
    Path(args.out).write_text(json.dumps(final_model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n[model] conformal threshold={threshold} (calibration n={len(pooled_scores)})")
    print(f"[model] written to {args.out}")


if __name__ == "__main__":
    main()
