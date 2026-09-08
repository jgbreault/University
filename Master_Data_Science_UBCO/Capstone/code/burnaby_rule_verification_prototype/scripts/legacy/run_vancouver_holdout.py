#!/usr/bin/env python3
"""Honest cross-city generalization test: run the verifier on Vancouver data.

NOTE: despite the twin name, this is the CROSS-CITY transfer test; the
within-city Burnaby tuning ablation lives in scripts/run_holdout_eval.py.

Adapts real Vancouver laneway-house rules (extracted by an upstream prototype,
a DIFFERENT pipeline than Burnaby's Pipeline 5) into the verifier's
candidate/evidence contract, then runs the SAME deterministic verifier with a
Vancouver config that has ZERO hand-fit table-scope patterns and a clean
(non-Burnaby) normalization block. Anything that verifies does so on structural
proof alone.

The point is an honest measurement, not a high score: most Vancouver rules use
families the verifier does not model (floor_area / floor-space-ratio / etc.) and
will land in not_used — that is the documented generalization blocker. The
in-contract families (height / setback / lot_coverage / building_separation)
are the transfer signal, measured against benchmark/gold/vancouver_rs_gold_rules.json.

Usage:  .venv/bin/python scripts/run_vancouver_holdout.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.slim_pipeline import run_slim_verification
from burnaby_prototype.domain_schema import RULE_OBJECT_ALIASES

_DEFAULT_INPUT = (
    ROOT.parent
    / "w2025-data599-capstone-projects-green-metrics-technology"
    / "code/prototype_pipeline/outputs/vancouver/prototype_vancouver_rule_pipeline"
    / "03_rules/filtered_target_rules_enriched.json"
)


def _first_number(value) -> str:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return match.group(0) if match else str(value or "")


def _operator(record: dict) -> str:
    # constraint_type outranks free-text operator words: the upstream
    # extractor's typed max/min label is far more reliable than whatever
    # phrasing survived in the operator string, so each branch checks `ct`
    # first and only falls back to wording cues. "from" sits in the minimum
    # cue list because in this corpus it is a reliable minimum marker
    # ("no less than 1.2 m FROM the lot line") — a corpus-specific call,
    # not a general English rule.
    ct = str(record.get("constraint_type") or "").lower()
    op = str(record.get("operator") or "").lower()
    if ct == "max" or any(w in op for w in ("exceed", "max", "maximum", "not more")):
        return "<="
    if ct == "min" or any(w in op for w in ("least", "min", "minimum", "from", "not less")):
        return ">="
    if ct in ("allowed", "permitted") or "permit" in op:
        return "allowed"
    return str(record.get("operator") or "")


def adapt_vancouver(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (evidence_units, rule_candidates) in the verifier's contract."""
    evidence_units: list[dict] = []
    candidates: list[dict] = []
    seen_evidence: set[str] = set()
    for index, record in enumerate(records, start=1):
        rule_id = str(record.get("rule_id") or f"vancouver_{index:04d}")
        evidence_id = str(record.get("evidence_id") or rule_id)
        evidence_text = record.get("evidence_text") or record.get("original_excerpt") or ""
        if evidence_id not in seen_evidence:
            seen_evidence.add(evidence_id)
            evidence_units.append(
                {
                    "evidence_id": evidence_id,
                    "page": record.get("page") or 1,
                    "evidence_type": "clause",  # all Vancouver evidence here is prose
                    "evidence_text": evidence_text,
                    "source_context": evidence_text,
                    "table_title": "",
                    "row_header": "",
                    "column_header": "",
                    "cell_value": "",
                    "unit": record.get("unit") or "",
                    "applies_to_hint": "",
                    "relevance": record.get("relevance_category") or "",
                    "notes": record.get("bylaw_section") or "",
                }
            )
        raw_object = record.get("rule_object")
        candidates.append(
            {
                "candidate_id": rule_id,
                "evidence_id": evidence_id,
                "rule_object": RULE_OBJECT_ALIASES.get(str(raw_object or ""), raw_object),
                "constraint_type": record.get("constraint_type"),
                "constraint_scope": record.get("constraint_scope"),
                "applies_to": record.get("applies_to"),
                "operator": _operator(record),
                "value": _first_number(record.get("value")) if record.get("value") not in (None, "") else None,
                "unit": record.get("unit"),
                "condition": record.get("condition"),
                "exception": record.get("exception"),
                "source_stream": "vancouver_pipeline_text",
                "extraction_method": "vancouver_prototype",
            }
        )
    return evidence_units, candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(_DEFAULT_INPUT), help="Vancouver enriched rules JSON.")
    parser.add_argument("--city", default="vancouver_rs")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        sys.exit(f"Vancouver input not found: {input_path}")
    records = json.loads(input_path.read_text(encoding="utf-8"))
    evidence_units, candidates = adapt_vancouver(records)
    print(f"[vancouver] adapted {len(candidates)} candidates / {len(evidence_units)} evidence units")

    output_dir = ROOT / "outputs" / f"{args.city}_slim_pipeline5_registry"
    run_slim_verification(
        config_path=ROOT / "configs" / f"{args.city}.json",
        output_dir=output_dir,
        evidence_units=evidence_units,
        rule_candidates=candidates,
        input_mode="vancouver_prototype",
    )

    subprocess.run(
        [sys.executable, str(ROOT / "benchmark" / "evaluate_benchmark.py"), "--city", args.city],
        check=True,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
    )
    report = json.loads((output_dir / "benchmark_report.json").read_text(encoding="utf-8"))
    m = report["rule_metrics"]
    print("\n=== Vancouver generalization (no hand-fit patterns) ===")
    print(f"candidates: {m['candidate_rule_count']}  ->  "
          f"verified {m['verified_rule_count']} / review {m['review_rule_count']} / "
          f"rejected {m['rejected_rule_count']} / not_used {m['not_used_rule_count']}")
    print(f"verified_precision = {m['verified_precision']}  (MUST be 1.0)")
    print(f"false_verified_count = {m['false_verified_count']}")
    print(f"verified_gold_recall = {round(m['verified_gold_recall'], 3)}  "
          f"(of {m['gold_rule_count']} in-contract gold rules)")
    print(f"verified_or_review_recall = {m['verified_or_review_recall']}")
    vr = [r.get("rule_object") for r in json.loads((output_dir / "verified_rules.json").read_text())]
    print(f"verified families: {sorted(set(vr))}")


if __name__ == "__main__":
    main()
