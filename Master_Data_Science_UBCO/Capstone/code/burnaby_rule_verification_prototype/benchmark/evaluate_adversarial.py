#!/usr/bin/env python3
"""Adversarial safety benchmark (improvement #5).

Feeds deliberately poisoned candidate/evidence pairs through the *real* verifier
and asserts that none of them is ever verified. This proves the gate actively
rejects unsafe rules, rather than merely staying quiet on a small input set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config
from burnaby_prototype.verification import verify_candidates
from burnaby_prototype.evidence_rerun import run_evidence_bundle_reruns, apply_bundle_promotions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs" / "burnaby_r1.json"))
    parser.add_argument(
        "--cases",
        default=str(ROOT / "benchmark" / "gold" / "burnaby_r1_adversarial_cases.json"),
    )
    parser.add_argument(
        "--bundle-cases",
        default=str(ROOT / "benchmark" / "gold" / "burnaby_r1_adversarial_bundles.json"),
        help="Poisoned evidence-bundle cases; each must fail to promote.",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "outputs" / "adversarial_report.json"),
        help="Write a JSON report for downstream promotion gates.",
    )
    return parser.parse_args()


def run_bundle_cases(config: dict[str, Any], cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Run poisoned bundles through the REAL bundle-promotion path.

    Each case proposes a bundle that stitches a value with a qualifier from a
    different logical source. The single-source provenance guard must drop the
    cross-source member so the candidate stays in review — never promoted.
    """
    rows: list[dict[str, Any]] = []
    leaks: list[str] = []
    for case in cases:
        review_rule = case["review_rule"]
        evidence_units = case["evidence_units"]
        evidence_by_id = {unit["evidence_id"]: unit for unit in evidence_units}
        bundle_ids = case["bundle_evidence_ids"]
        # Force a bundle attempt so the guard (not the scorer) is what's tested.
        intelligence_report = {
            "items": [
                {
                    "rule_id": review_rule["rule_id"],
                    "safe_retry": True,
                    "blocked_by": [],
                    "bundle_missing_fields": [],
                    "bundle_score": 0.99,
                    "current_evidence_id": review_rule.get("source", {}).get("evidence_id"),
                    "best_evidence_bundle": [
                        {
                            "evidence_id": eid,
                            "raw_score": float(len(bundle_ids) - index),
                            "evidence_quote": evidence_by_id.get(eid, {}).get("evidence_text")
                            or evidence_by_id.get(eid, {}).get("cell_value"),
                            "page": evidence_by_id.get(eid, {}).get("page"),
                        }
                        for index, eid in enumerate(bundle_ids)
                    ],
                }
            ]
        }
        bundle_report = run_evidence_bundle_reruns(
            config, evidence_units, [review_rule["candidate"]], [review_rule], intelligence_report
        )
        _, _, promotion = apply_bundle_promotions([], [review_rule], bundle_report)
        promoted = review_rule["rule_id"] in (promotion.get("promoted_rule_ids") or [])
        if promoted:
            leaks.append(case["case_id"])
        rows.append(
            {
                "case_id": case["case_id"],
                "description": case["description"],
                "promoted": promoted,
                "passed": not promoted,
            }
        )
    return rows, leaks


def run(config_path: Path, cases_path: Path, bundle_cases_path: Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    evidence_units = [case["evidence"] for case in cases if case.get("evidence")]
    candidates = [case["candidate"] for case in cases]
    result = verify_candidates(config, evidence_units, candidates)

    verified_ids = {
        rule.get("candidate", {}).get("candidate_id") for rule in result["verified_rules"]
    }
    # verify_candidates returns only TWO buckets: verified_rules and
    # review_needed, where review_needed is the entire non-verified pool. The
    # fine-grained outcome (rejected / not_used / review) lives on each rule's
    # verification_decision field — slim_pipeline is what splits them into
    # separate output files. So scanning these two lists covers every case.
    decision_by_candidate = {
        rule.get("candidate", {}).get("candidate_id"): rule.get("verification_decision")
        for rule in [*result["verified_rules"], *result["review_needed"]]
    }

    rows: list[dict[str, Any]] = []
    leaks: list[str] = []
    decision_mismatches: list[str] = []
    for case in cases:
        cand_id = case["candidate"]["candidate_id"]
        verified = cand_id in verified_ids
        decision = decision_by_candidate.get(cand_id)
        expected_decision = case.get("expected_decision")
        decision_matches = expected_decision is None or decision == expected_decision
        if verified:
            leaks.append(case["case_id"])
        if not decision_matches:
            decision_mismatches.append(case["case_id"])
        rows.append(
            {
                "case_id": case["case_id"],
                "description": case["description"],
                "verified": verified,
                "decision": decision,
                "expected_decision": expected_decision,
                # Blocking verification is necessary but not quite sufficient:
                # poisoned candidates that are truly contradictory should usually
                # be rejected, while ambiguous wrong-scope cases may be review.
                "decision_matches_expected": decision_matches,
                "passed": not verified and decision_matches,
            }
        )

    bundle_rows: list[dict[str, Any]] = []
    bundle_leaks: list[str] = []
    if bundle_cases_path and Path(bundle_cases_path).exists():
        bundle_cases = json.loads(Path(bundle_cases_path).read_text(encoding="utf-8"))
        bundle_rows, bundle_leaks = run_bundle_cases(config, bundle_cases)

    return {
        "total_cases": len(cases),
        "blocked_count": sum(1 for row in rows if row["passed"]),
        "leaked_count": len(leaks),
        "leaked_case_ids": leaks,
        "decision_mismatch_count": len(decision_mismatches),
        "decision_mismatch_case_ids": decision_mismatches,
        "bundle_case_count": len(bundle_rows),
        "bundle_blocked_count": sum(1 for row in bundle_rows if row["passed"]),
        "bundle_leaked_count": len(bundle_leaks),
        "bundle_leaked_case_ids": bundle_leaks,
        "bundle_results": bundle_rows,
        "all_blocked": not leaks and not decision_mismatches and not bundle_leaks,
        "results": rows,
    }


def main() -> None:
    args = parse_args()
    report = run(Path(args.config), Path(args.cases), Path(args.bundle_cases))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Adversarial safety benchmark")
    print(f"  cases:   {report['total_cases']}")
    print(f"  blocked: {report['blocked_count']}")
    print(f"  leaked:  {report['leaked_count']} {report['leaked_case_ids']}")
    print(f"  decision mismatches: {report['decision_mismatch_count']} {report['decision_mismatch_case_ids']}")
    print(f"  bundle cases: {report['bundle_case_count']}  blocked: {report['bundle_blocked_count']}  leaked: {report['bundle_leaked_count']} {report['bundle_leaked_case_ids']}")
    print(f"  ALL BLOCKED: {report['all_blocked']}")
    for row in report["results"]:
        status = "OK " if row["passed"] else "LEAK"
        expected = f" (expected {row['expected_decision']})" if row.get("expected_decision") else ""
        print(f"  [{status}] {row['case_id']} -> {row['decision']}{expected}")
    for row in report["bundle_results"]:
        status = "OK " if row["passed"] else "LEAK"
        print(f"  [{status}] {row['case_id']} -> promoted={row['promoted']}")
    sys.exit(0 if report["all_blocked"] else 1)


if __name__ == "__main__":
    main()
