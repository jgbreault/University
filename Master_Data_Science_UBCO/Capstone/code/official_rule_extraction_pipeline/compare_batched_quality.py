#!/usr/bin/env python3
"""Compare Pipeline 10 batched extraction against Pipeline 9 target-strict output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip().lower()


def rule_signature(rule: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        clean(rule.get("rule_object")),
        clean(rule.get("subject")),
        clean(rule.get("operator")),
        clean(rule.get("value")),
        clean(rule.get("unit")),
    )


def source_ids(rules: list[dict[str, Any]]) -> set[str]:
    return {str(rule.get("source_id") or "").strip() for rule in rules if rule.get("source_id")}


def load_rules(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    value = read_json(path)
    if not isinstance(value, list):
        raise TypeError(f"{path} is not a JSON list")
    return [item for item in value if isinstance(item, dict)]


def compare_city(city: str, baseline_root: Path, candidate_root: Path) -> dict[str, Any]:
    baseline_dir = baseline_root / city / "06_rule_extraction_target_strict"
    candidate_dir = candidate_root / city / "06_rule_extraction_batched"
    baseline_rules = load_rules(baseline_dir / "merged_rules_deduplicated.json")
    candidate_rules = load_rules(candidate_dir / "merged_rules_deduplicated.json")
    baseline_summary = read_json(baseline_dir / "summary.json")
    candidate_summary = read_json(candidate_dir / "summary.json")

    baseline_sources = source_ids(baseline_rules)
    candidate_sources = source_ids(candidate_rules)
    baseline_signatures = {rule_signature(rule) for rule in baseline_rules}
    candidate_signatures = {rule_signature(rule) for rule in candidate_rules}

    missing_sources = sorted(baseline_sources - candidate_sources)
    missing_signatures = sorted(baseline_signatures - candidate_signatures)
    extra_signatures = sorted(candidate_signatures - baseline_signatures)

    return {
        "city": city,
        "baseline_rule_count": len(baseline_rules),
        "candidate_rule_count": len(candidate_rules),
        "baseline_text_batch_count": baseline_summary.get("text_page_batch_count"),
        "candidate_text_batch_count": candidate_summary.get("text_batch_count"),
        "candidate_preflight_skipped": candidate_summary.get("preflight_skipped_text_block_count"),
        "source_coverage": {
            "baseline_source_count": len(baseline_sources),
            "candidate_source_count": len(candidate_sources),
            "covered_baseline_source_count": len(baseline_sources & candidate_sources),
            "missing_baseline_source_count": len(missing_sources),
            "missing_baseline_sources": missing_sources[:30],
        },
        "signature_coverage": {
            "baseline_signature_count": len(baseline_signatures),
            "candidate_signature_count": len(candidate_signatures),
            "covered_baseline_signature_count": len(baseline_signatures & candidate_signatures),
            "missing_baseline_signature_count": len(missing_signatures),
            "extra_candidate_signature_count": len(extra_signatures),
            "missing_baseline_signatures_sample": missing_signatures[:20],
            "extra_candidate_signatures_sample": extra_signatures[:20],
        },
        "quality_flags": candidate_summary.get("extraction_quality_flags", {}),
        "text_error_batches": candidate_summary.get("text_error_batches"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="+", default=["vancouver", "burnaby"])
    parser.add_argument("--baseline-root", type=Path, default=REPO / "code" / "legacy" / "prototype_pipeline_9" / "outputs")
    parser.add_argument("--candidate-root", type=Path, default=ROOT / "outputs")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "batched_quality_comparison.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = [compare_city(city, args.baseline_root, args.candidate_root) for city in args.cities]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
