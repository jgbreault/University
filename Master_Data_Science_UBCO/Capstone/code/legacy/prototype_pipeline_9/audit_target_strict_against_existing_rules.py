#!/usr/bin/env python3
"""Audit target-strict adapter text against existing extracted rule evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def meaningful(text: str) -> bool:
    return len(text) >= 20 and bool(re.search(r"[a-z]", text))


def run_case(city: str, existing_run: Path, strict_visual_dir: Path, output_dir: Path) -> dict[str, Any]:
    rules = read_json(existing_run / "04_rule_extraction" / "text_rules_raw.json")
    strict_blocks = read_jsonl(strict_visual_dir / "text_blocks.jsonl")
    strict_text = norm(" ".join(block.get("text", "") for block in strict_blocks))
    rows: list[dict[str, Any]] = []
    for rule in rules:
        evidence = norm(rule.get("evidence_text", ""))
        if not meaningful(evidence):
            continue
        rows.append(
            {
                "source_id": rule.get("source_id", ""),
                "rule_key": rule.get("rule_key", ""),
                "subject": rule.get("subject", ""),
                "evidence_text": rule.get("evidence_text", ""),
                "covered_by_strict_text": evidence in strict_text,
            }
        )
    missed = [row for row in rows if not row["covered_by_strict_text"]]
    case_dir = output_dir / city
    write_jsonl(case_dir / "strict_missed_existing_rule_evidence.jsonl", missed)
    summary = {
        "city": city,
        "existing_rule_count_with_evidence": len(rows),
        "covered_existing_rule_evidence_count": len(rows) - len(missed),
        "missed_existing_rule_evidence_count": len(missed),
        "coverage_percent": round(100 * (len(rows) - len(missed)) / len(rows), 1) if rows else 100.0,
        "strict_text_block_count": len(strict_blocks),
        "strict_char_count": sum(len(block.get("text", "")) for block in strict_blocks),
        "audit_file": str((case_dir / "strict_missed_existing_rule_evidence.jsonl").resolve()),
    }
    write_json(case_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "audit_target_strict")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = [
        (
            "burnaby",
            ROOT.parent / "prototype_pipeline_8" / "outputs_local" / "burnaby",
            ROOT / "outputs" / "burnaby" / "05_rag_visual_blocks_target_strict",
        ),
        (
            "vancouver",
            ROOT.parent / "prototype_pipeline_8" / "outputs_local" / "vancouver",
            ROOT / "outputs" / "vancouver" / "05_rag_visual_blocks_target_strict",
        ),
    ]
    summaries = [run_case(city, existing, strict, args.output_dir) for city, existing, strict in cases]
    write_json(args.output_dir / "summary.json", summaries)
    print(json.dumps(summaries, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
