#!/usr/bin/env python3
"""Extract rules from Calgary graph/RAG core-rule packs only.

This is a small API experiment: it reads ``experiments/calgary_graph_rag/
extract_now_core_packs.jsonl``, batches the packs into one compact prompt, and
writes parsed/raw Gemini responses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PIPELINE5_DIR = ROOT.parent / "prototype_pipeline_5"
if str(PIPELINE5_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE5_DIR))

from visual_blocks_rule_extractor import RULE_SCHEMA, call_gemini, write_json  # noqa: E402


DEFAULT_MODEL = "gemini-3.1-pro-preview"
DEFAULT_PACKS = ROOT / "experiments" / "calgary_graph_rag" / "extract_now_core_packs.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "experiments" / "calgary_graph_rag" / "core_rule_extraction"


PROMPT = """Extract atomic zoning rules from compact graph/RAG evidence packs.

Use only the supplied evidence. These packs are Calgary Land Use Bylaw sections
for Secondary Suite / Backyard Suite core rules. Return one atomic rule per
independently testable constraint, permission, prohibition, exception, numeric
limit, or measurement rule.

Rules:
1. Every rule must cite exactly one source_id from an evidence block.
2. Preserve section/scope from pack_id, page_number, scope, and block text in condition.
3. If a source contains multiple values or sub-rules, emit multiple atomic rules.
4. Preserve exceptions and district qualifiers literally.
5. Skip deleted sections and headings that contain no active rule.
6. For unit, use ASCII canonical tokens only: m, m2, %, storeys, units.
7. value holds only a measured quantity or enumerated value. Do not put section numbers in value.
8. Operators: minimum/not less than -> >=; maximum/not exceed/up to -> <=; fixed quantity -> =;
   permitted/may -> permitted; prohibited/must not -> prohibited; must/shall/required -> required.
9. evidence_text must be a faithful excerpt from the cited source text.

Evidence packs JSON:
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs", type=Path, default=DEFAULT_PACKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def compact_pack(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "pack_id": pack.get("pack_id", ""),
        "page_number": pack.get("page_number"),
        "scope": pack.get("scope", ""),
        "applicability": pack.get("applicability", ""),
        "evidence_blocks": [
            {
                "source_id": block.get("source_id", ""),
                "role": block.get("role", ""),
                "text": block.get("text", ""),
            }
            for block in pack.get("evidence_blocks", [])
            if block.get("applicability") in {"core_rule", "scope_context", "related_context"}
        ],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"{args.api_key_env} is not set.")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed_path = output_dir / "core_rules_parsed.json"
    raw_path = output_dir / "core_rules_raw_response.json"
    summary_path = output_dir / "summary.json"

    packs = [pack for pack in read_jsonl(args.packs) if pack.get("applicability") == "core_rule"]
    inventory = [compact_pack(pack) for pack in packs]

    if parsed_path.exists() and not args.overwrite:
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    else:
        parsed, raw = call_gemini(
            prompt=PROMPT + json.dumps(inventory, ensure_ascii=False),
            api_key=api_key,
            model=args.model,
            timeout=args.timeout,
            max_retries=args.max_retries,
            retry_base_seconds=args.retry_base_seconds,
            response_schema=RULE_SCHEMA,
        )
        write_json(parsed_path, parsed)
        write_json(raw_path, raw)

    rules = parsed.get("rules", [])
    summary = {
        "model": args.model,
        "input_pack_count": len(packs),
        "input_block_count": sum(len(pack.get("evidence_blocks", [])) for pack in inventory),
        "rule_count": len(rules),
        "skipped_source_count": len(parsed.get("skipped_sources", [])),
        "warnings": parsed.get("warnings", []),
        "output_dir": str(output_dir),
    }
    write_json(summary_path, summary)
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
