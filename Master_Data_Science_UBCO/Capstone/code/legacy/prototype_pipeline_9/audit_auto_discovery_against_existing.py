#!/usr/bin/env python3
"""Audit auto-discovery block selection against existing text-rule sources.

This script does not call an LLM. It runs the generic Pipeline 9 discovery
classifier over an existing visual-block run and compares selected block IDs
against `04_rule_extraction/text_rules_raw.json` source IDs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PIPELINE6_DIR = ROOT.parent / "prototype_pipeline_6"
if str(PIPELINE6_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE6_DIR))

from auto_discovery import annotate_blocks, lane_for, read_json, read_jsonl, write_json, write_jsonl  # noqa: E402
from local_candidate_block_selector import CITY_CONFIGS  # noqa: E402
from semantic_compression import build_query, lexical_scores, should_keep, structural_score  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "audit_auto_discovery"


def normalize_visual_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for block in blocks:
        row = dict(block)
        row.setdefault("page_block_index", row.get("reading_order", 0))
        row.setdefault("line_start", row.get("reading_order", 0))
        row.setdefault("line_end", row.get("reading_order", 0))
        normalized.append(row)
    return normalized


def compact_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_id": block.get("block_id"),
        "page_number": block.get("page_number"),
        "text": block.get("text", ""),
        "scope": block.get("scope", ""),
        "selected_because": block.get("selected_because", []),
        "rule_types": block.get("rule_types", []),
        "discovery_confidence": block.get("discovery_confidence"),
        "lane": lane_for(block),
    }


def compressed_ids_for_audit(
    annotated: list[dict[str, Any]],
    config: dict[str, Any],
    threshold: float,
) -> set[str]:
    selected = [
        block for block in annotated
        if block.get("discovery_selected") and not block.get("noise_reasons")
    ]
    query = build_query(
        {"config": config},
        config.get("target_terms", []),
        config.get("parent_terms", []),
    )
    semantic_scores = lexical_scores(selected, query)
    compressed: set[str] = set()
    for block in selected:
        lane = lane_for(block)
        lane_bonus = {
            "target_context": 0.18,
            "permission": 0.12,
            "dimensional_standard": 0.10,
            "parking": 0.08,
            "permit_process": 0.07,
            "cross_reference": 0.04,
            "related_context": 0.02,
            "context_definition": -0.04,
        }.get(lane, 0.0)
        semantic_score = semantic_scores.get(block["block_id"], 0.0)
        final_score = round((0.45 * structural_score(block)) + (0.45 * semantic_score) + lane_bonus, 4)
        if should_keep(block, final_score, semantic_score, threshold):
            compressed.add(block["block_id"])
    return compressed


def run_case(city: str, run_dir: Path, output_dir: Path, compression_threshold: float) -> dict[str, Any]:
    config = CITY_CONFIGS[city]
    visual_dir = run_dir / "03_visual_blocks"
    rules_dir = run_dir / "04_rule_extraction"
    text_blocks = normalize_visual_blocks(read_jsonl(visual_dir / "text_blocks.jsonl"))
    text_rules = read_json(rules_dir / "text_rules_raw.json")

    annotated = annotate_blocks(
        text_blocks,
        windows=[],
        target_terms=config.get("target_terms", []),
        parent_terms=config.get("parent_terms", []),
    )
    by_id = {block["block_id"]: block for block in annotated}
    selected_ids = {block["block_id"] for block in annotated if block["discovery_selected"]}
    compressed_ids = compressed_ids_for_audit(annotated, config, compression_threshold)
    rule_source_ids = {rule.get("source_id", "") for rule in text_rules if rule.get("source_id")}
    covered_ids = sorted(rule_source_ids & selected_ids)
    missed_ids = sorted(rule_source_ids - selected_ids)
    compressed_covered_ids = sorted(rule_source_ids & compressed_ids)
    compressed_missed_ids = sorted(rule_source_ids - compressed_ids)
    extra_selected_ids = sorted(selected_ids - rule_source_ids)
    compressed_extra_ids = sorted(compressed_ids - rule_source_ids)

    case_dir = output_dir / city
    write_jsonl(case_dir / "annotated_visual_blocks.jsonl", annotated)
    write_jsonl(case_dir / "missed_rule_source_blocks.jsonl", [compact_block(by_id[block_id]) for block_id in missed_ids if block_id in by_id])
    write_jsonl(
        case_dir / "compression_missed_rule_source_blocks.jsonl",
        [compact_block(by_id[block_id]) for block_id in compressed_missed_ids if block_id in by_id],
    )
    write_jsonl(case_dir / "extra_selected_blocks.jsonl", [compact_block(by_id[block_id]) for block_id in extra_selected_ids if block_id in by_id])

    summary = {
        "city": city,
        "input_run_dir": str(run_dir.resolve()),
        "visual_text_block_count": len(text_blocks),
        "existing_text_rule_count": len(text_rules),
        "unique_existing_text_rule_source_count": len(rule_source_ids),
        "auto_discovery_selected_block_count": len(selected_ids),
        "covered_rule_source_count": len(covered_ids),
        "missed_rule_source_count": len(missed_ids),
        "source_coverage_percent": round(100 * len(covered_ids) / len(rule_source_ids), 1) if rule_source_ids else 100.0,
        "extra_selected_block_count": len(extra_selected_ids),
        "compression": {
            "provider": "lexical",
            "threshold": compression_threshold,
            "compressed_selected_block_count": len(compressed_ids),
            "covered_rule_source_count": len(compressed_covered_ids),
            "missed_rule_source_count": len(compressed_missed_ids),
            "source_coverage_percent": round(100 * len(compressed_covered_ids) / len(rule_source_ids), 1)
            if rule_source_ids else 100.0,
            "extra_selected_block_count": len(compressed_extra_ids),
            "missed_source_ids": compressed_missed_ids,
        },
        "selected_lane_counts": {},
        "missed_source_ids": missed_ids,
        "audit_files": {
            "annotated_visual_blocks": str((case_dir / "annotated_visual_blocks.jsonl").resolve()),
            "missed_rule_source_blocks": str((case_dir / "missed_rule_source_blocks.jsonl").resolve()),
            "compression_missed_rule_source_blocks": str(
                (case_dir / "compression_missed_rule_source_blocks.jsonl").resolve()
            ),
            "extra_selected_blocks": str((case_dir / "extra_selected_blocks.jsonl").resolve()),
        },
    }
    lane_counts: dict[str, int] = {}
    for block in annotated:
        if block["block_id"] in selected_ids:
            lane_counts[lane_for(block)] = lane_counts.get(lane_for(block), 0) + 1
    summary["selected_lane_counts"] = lane_counts
    write_json(case_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--compression-threshold", type=float, default=0.32)
    parser.add_argument(
        "--case",
        action="append",
        nargs=2,
        metavar=("CITY", "RUN_DIR"),
        help="City and existing Pipeline 8/9 run dir. May be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = args.case or [
        ["burnaby", str(ROOT.parent / "prototype_pipeline_8" / "outputs_local" / "burnaby")],
        ["vancouver", str(ROOT.parent / "prototype_pipeline_8" / "outputs_local" / "vancouver")],
    ]
    summaries = [
        run_case(city, Path(run_dir), args.output_dir, args.compression_threshold)
        for city, run_dir in cases
    ]
    write_json(args.output_dir / "summary.json", summaries)
    print(json.dumps(summaries, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
