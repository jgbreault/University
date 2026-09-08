#!/usr/bin/env python3
"""Score pipeline7's CACHED merge-review decisions against the validated gold.

This never calls the API. It loads merge_review_api_response.json (the cached
Gemini decisions) and grades them with pipeline5's shared `evaluate_against_gold`
using the pipeline7-keyed gold fixture (benchmarks/burnaby_merge_review_gold_pipeline7.json).

Only the 10 human-validated items carried/re-keyed from the pipeline5 gold are
scored. The 8 draft items and 7 absent pipeline5-gold items are reported as
coverage context (see benchmarks/burnaby_pipeline7_review_coverage.json) but are
NOT counted in the accuracy numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PIPELINE7_DIR = Path(__file__).resolve().parent
PIPELINE5_DIR = PIPELINE7_DIR.parent / "prototype_pipeline_5"
if str(PIPELINE5_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE5_DIR))

from visual_blocks_merge_reviewer import evaluate_against_gold  # noqa: E402
from visual_blocks_rule_extractor import write_csv, write_json  # noqa: E402

DEFAULT_RUN = PIPELINE7_DIR / "outputs" / "burnaby" / "04_rule_extraction"
DEFAULT_GOLD = PIPELINE7_DIR / "benchmarks" / "burnaby_merge_review_gold_pipeline7.json"
DEFAULT_COVERAGE = PIPELINE7_DIR / "benchmarks" / "burnaby_pipeline7_review_coverage.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN,
                        help="04_rule_extraction dir holding merge_review_api_response.json.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    decisions_path = run_dir / "merge_review_api_response.json"
    if not decisions_path.exists():
        raise FileNotFoundError(f"No cached decisions at {decisions_path}")

    decisions = json.loads(decisions_path.read_text(encoding="utf-8")).get("decisions", [])
    result = evaluate_against_gold(decisions, args.gold)

    write_json(run_dir / "merge_review_benchmark_result.json", result)
    write_csv(run_dir / "merge_review_benchmark_checks.csv", result["checks"])

    coverage = json.loads(args.coverage.read_text(encoding="utf-8")) if args.coverage.exists() else {}
    n_scored = result["gold_rule_count"]
    n_draft = len(coverage.get("draft_items_pending_human_review", []))
    n_absent = len(coverage.get("pipeline5_gold_items_absent_in_pipeline7_review", []))

    print("=" * 78)
    print("Pipeline7 Burnaby R1 — merge-review benchmark (cached decisions, no API)")
    print("=" * 78)
    print(f"Scored (human-validated gold items)     : {n_scored}")
    print(f"  action accuracy                       : {result['action_accuracy']:.3f}")
    print(f"  action + count accuracy               : {result['action_and_count_accuracy']:.3f}")
    print(f"  numeric endpoint accuracy             : {result['numeric_endpoint_accuracy']:.3f}")
    print(f"  full-check accuracy                   : {result['full_check_accuracy']:.3f}")
    print("-" * 78)
    print(f"NOT scored — draft items (need human)   : {n_draft}")
    print(f"NOT scored — gold items absent in p7    : {n_absent}")
    print(f"Coverage of pipeline5 gold (17 items)   : {n_scored}/17 scored, {n_absent}/17 absent")
    print("-" * 78)
    print("Per-item checks (scored only):")
    for c in result["checks"]:
        flag = "OK " if (c["action_match"] and c["replacement_count_match"]
                         and c["numeric_rules_match"]) else "XX "
        print(f"  {flag}{c['merged_rule_id']}  "
              f"exp={c['expected_action']}/{c['expected_replacement_count']} "
              f"act={c['actual_action']}/{c['actual_replacement_count']} "
              f"num={'y' if c['numeric_rules_match'] else 'n'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
