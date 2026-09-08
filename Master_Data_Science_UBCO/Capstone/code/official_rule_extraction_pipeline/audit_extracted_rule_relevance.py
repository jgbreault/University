#!/usr/bin/env python3
"""Audit extracted RAG rules for target-building relevance.

The audit is intentionally conservative: it classifies each extracted rule using
only the rule text and its cited source block, not other blocks on the same
pseudo-page. This surfaces mixed use-list over-extraction.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CITY_DIR = ROOT / "outputs" / "calgary"

TARGET_RE = re.compile(r"\b(backyard suite|secondary suite)\b", re.IGNORECASE)
SUITE_ANY_RE = re.compile(r"\bsuite\b", re.IGNORECASE)
RESIDENTIAL_CONTEXT_RE = re.compile(
    r"\b(dwelling|residential|accessory residential building|single detached|"
    r"semi-detached|duplex|rowhouse|townhouse|parcel|land use district|district)\b",
    re.IGNORECASE,
)
GENERAL_APPLICABLE_RE = re.compile(
    r"\b(all uses|all buildings|all development|all districts|rules governing all districts|"
    r"general rules|low density residential|floodway|parking|development permit|setback|"
    r"parcel width|building height|parcel coverage|landscaped area)\b",
    re.IGNORECASE,
)
OTHER_USE_RE = re.compile(
    r"\b(drinking establishment|drive through|hazardous waste|home occupation|landfill|"
    r"liquor store|night club|pawn shop|payday loan|place of worship|parking lot|"
    r"take out food|seasonal sales|e-scooter|grocery|wine|pawnshop|secondhand|"
    r"sleeping unit|assisted living|swimming pool|hot tub|extensive agriculture|"
    r"natural area|outdoor recreation|multi.?residential development|live work unit|"
    r"power generation|residential care|sign . class)\b",
    re.IGNORECASE,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def classify_text(text: str, *, rag_applicability: str = "") -> str:
    if TARGET_RE.search(text):
        return "direct_target"
    if SUITE_ANY_RE.search(text) and RESIDENTIAL_CONTEXT_RE.search(text):
        return "direct_suite_context"
    if GENERAL_APPLICABLE_RE.search(text) and (
        RESIDENTIAL_CONTEXT_RE.search(text)
        or rag_applicability in {"use_permission", "district_dimensional_override", "universal_applicable_rule"}
    ):
        return "generic_applicable"
    if OTHER_USE_RE.search(text):
        return "likely_irrelevant_other_use"
    return "unclear_or_broad"


def classify_block(text: str, *, rag_applicability: str = "") -> str:
    return classify_text(text, rag_applicability=rag_applicability) + "_block"


def combined_rule_text(rule: dict[str, Any], source_block: dict[str, Any]) -> str:
    fields = [
        "rule_key",
        "rule_object",
        "constraint_type",
        "subject",
        "condition",
        "exception",
        "evidence_text",
    ]
    return " ".join(str(rule.get(field, "")) for field in fields) + " " + str(source_block.get("text", ""))


def audit_input_blocks(city_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blocks = read_jsonl(city_dir / "05_rag_visual_blocks" / "text_blocks.jsonl")
    rows: list[dict[str, Any]] = []
    for block in blocks:
        text = str(block.get("text", ""))
        rows.append(
            {
                "pseudo_page": block.get("page_number"),
                "block_id": block.get("block_id"),
                "original_page_number": block.get("original_page_number"),
                "original_source_id": block.get("original_source_id"),
                "rag_lane": block.get("rag_lane"),
                "rag_applicability": block.get("rag_applicability"),
                "tier": classify_block(text, rag_applicability=str(block.get("rag_applicability", ""))),
                "char_count": len(text),
                "text": text.replace("\n", " "),
            }
        )
    summary = {
        "input_text_block_count": len(rows),
        "tier_counts": dict(Counter(row["tier"] for row in rows)),
        "char_counts_by_tier": {
            tier: sum(row["char_count"] for row in rows if row["tier"] == tier)
            for tier in sorted({row["tier"] for row in rows})
        },
        "by_lane": {
            lane: dict(Counter(row["tier"] for row in rows if row["rag_lane"] == lane))
            for lane in sorted({str(row["rag_lane"]) for row in rows})
        },
    }
    return rows, summary


def audit_extracted_rules(city_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blocks = read_jsonl(city_dir / "05_rag_visual_blocks" / "text_blocks.jsonl")
    by_block = {block["block_id"]: block for block in blocks}
    raw_dir = city_dir / "06_rule_extraction" / "api_raw"
    rows: list[dict[str, Any]] = []
    for parsed_path in sorted(raw_dir.glob("text_page_*_parsed.json")):
        page = int(parsed_path.name.split("_")[2])
        parsed = read_json(parsed_path)
        for rule in parsed.get("rules", []):
            if not isinstance(rule, dict):
                continue
            source_id = str(rule.get("source_id", ""))
            source_block = by_block.get(source_id, {})
            tier = classify_text(
                combined_rule_text(rule, source_block),
                rag_applicability=str(source_block.get("rag_applicability", "")),
            )
            rows.append(
                {
                    "pseudo_page": page,
                    "source_id": source_id,
                    "original_page_number": source_block.get("original_page_number", ""),
                    "original_source_id": source_block.get("original_source_id", ""),
                    "rag_lane": source_block.get("rag_lane", ""),
                    "rag_applicability": source_block.get("rag_applicability", ""),
                    "tier": tier,
                    "subject": rule.get("subject", ""),
                    "rule_key": rule.get("rule_key", ""),
                    "condition": rule.get("condition", ""),
                    "evidence_text": rule.get("evidence_text", ""),
                }
            )
    summary = {
        "parsed_page_count": len(list(raw_dir.glob("text_page_*_parsed.json"))),
        "rule_count": len(rows),
        "tier_counts": dict(Counter(row["tier"] for row in rows)),
        "tier_by_lane": {
            lane: dict(Counter(row["tier"] for row in rows if row["rag_lane"] == lane))
            for lane in sorted({str(row["rag_lane"]) for row in rows})
        },
        "likely_bad_pages": dict(
            Counter(row["pseudo_page"] for row in rows if row["tier"] == "likely_irrelevant_other_use").most_common()
        ),
    }
    return rows, summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-dir", type=Path, default=DEFAULT_CITY_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    city_dir = args.city_dir.resolve()
    output_dir = city_dir / "06_rule_extraction"
    block_rows, block_summary = audit_input_blocks(city_dir)
    rule_rows, rule_summary = audit_extracted_rules(city_dir)
    write_csv(output_dir / "input_block_relevance_audit.csv", block_rows)
    write_csv(output_dir / "relevance_audit_partial_strict.csv", rule_rows)
    summary = {
        "city_dir": str(city_dir),
        "input_blocks": block_summary,
        "extracted_rules": rule_summary,
        "audit_files": {
            "input_blocks": str((output_dir / "input_block_relevance_audit.csv").resolve()),
            "extracted_rules": str((output_dir / "relevance_audit_partial_strict.csv").resolve()),
        },
    }
    write_json(output_dir / "relevance_audit_summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
