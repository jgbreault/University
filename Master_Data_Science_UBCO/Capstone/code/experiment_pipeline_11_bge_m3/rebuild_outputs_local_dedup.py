#!/usr/bin/env python3
"""Rebuild Pipeline 11 final outputs from cached raw rules without API calls."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
from batched_rag_rule_extractor import (  # noqa: E402
    apply_postprocess_filters,
    city_from_output_dir,
    fold_normalized_duplicates,
    split_clean_and_review_rules,
)
from visual_blocks_rule_extractor import (  # noqa: E402
    merge_and_audit_rules,
    non_canonical_unit,
    write_csv,
    write_json,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rebuild(output_dir: Path, *, target_terms: list[str] | None = None) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    combined_rules = read_json(output_dir / "combined_rules_raw.json")
    merged_rules, merge_audit, merge_review_queue = merge_and_audit_rules(combined_rules)
    merged_rules, normalized_merge_audit = fold_normalized_duplicates(merged_rules)
    merged_rules, postprocess_filter_audit = apply_postprocess_filters(
        merged_rules,
        city=city_from_output_dir(output_dir),
        target_terms=target_terms,
    )
    clean_rules, merge_review_queue = split_clean_and_review_rules(merged_rules)

    non_canonical_units = sorted({
        offending
        for rule in merged_rules
        if (offending := non_canonical_unit(rule.get("unit")))
    })
    extraction_quality_flags = Counter(
        reason for rule in merged_rules for reason in rule.get("review_reasons", [])
    )

    write_json(output_dir / "merged_rules_deduplicated.json", merged_rules)
    write_csv(output_dir / "merged_rules_deduplicated.csv", merged_rules)
    write_json(output_dir / "merged_rules_clean.json", clean_rules)
    write_csv(output_dir / "merged_rules_clean.csv", clean_rules)
    write_json(output_dir / "merge_audit.json", merge_audit)
    write_csv(output_dir / "merge_audit.csv", merge_audit)
    write_json(output_dir / "normalized_merge_audit.json", normalized_merge_audit)
    write_csv(output_dir / "normalized_merge_audit.csv", normalized_merge_audit)
    write_json(output_dir / "postprocess_filter_audit.json", postprocess_filter_audit)
    write_csv(output_dir / "postprocess_filter_audit.csv", postprocess_filter_audit)
    write_json(output_dir / "merge_review_queue.json", merge_review_queue)
    write_csv(output_dir / "merge_review_queue.csv", merge_review_queue)

    summary_path = output_dir / "summary.json"
    summary = read_json(summary_path) if summary_path.exists() else {}
    summary.update({
        "combined_rule_count": len(combined_rules),
        "deduplicated_rule_count": len(merged_rules),
        "clean_rule_count": len(clean_rules),
        "auto_folded_group_count": len(merge_audit),
        "auto_folded_rule_count": sum(row["merged_rule_count"] - 1 for row in merge_audit),
        "normalized_folded_group_count": len(normalized_merge_audit),
        "normalized_folded_rule_count": sum(row["folded_rule_count"] - 1 for row in normalized_merge_audit),
        "postprocess_filtered_rule_count": len(postprocess_filter_audit),
        "postprocess_filter_reason_counts": dict(Counter(row["reason"] for row in postprocess_filter_audit)),
        "merge_review_rule_count": len(merge_review_queue),
        "non_canonical_unit_count": len(non_canonical_units),
        "non_canonical_units": non_canonical_units,
        "extraction_quality_flags": dict(extraction_quality_flags),
        "rebuilt_from_cached_raw_rules": True,
    })
    write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dirs", nargs="+", type=Path)
    parser.add_argument("--target-terms", nargs="*", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summaries = [rebuild(path, target_terms=args.target_terms) for path in args.output_dirs]
    print(json.dumps(summaries, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
