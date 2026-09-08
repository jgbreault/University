#!/usr/bin/env python3
"""Run legacy extraction on a small subset of RAG pseudo-pages.

This is a fail-fast probe for API status before a full city extraction.
"""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PIPELINE5_DIR = ROOT.parent / "prototype_pipeline_5"
if str(PIPELINE5_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE5_DIR))

from visual_blocks_rule_extractor import process_extraction  # noqa: E402


DEFAULT_INPUT_DIR = ROOT / "outputs" / "calgary" / "05_rag_visual_blocks"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "calgary" / "06_rule_extraction_smoke"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare_subset(input_dir: Path, subset_dir: Path, max_pages: int, pages: list[int] | None = None) -> dict[str, Any]:
    text_blocks = read_jsonl(input_dir / "text_blocks.jsonl")
    available_pages = sorted({int(block.get("page_number", 0)) for block in text_blocks})
    selected_pages = pages or available_pages[:max_pages]
    selected_page_set = set(selected_pages)
    subset_blocks = [block for block in text_blocks if int(block.get("page_number", 0)) in selected_page_set]
    write_jsonl(subset_dir / "text_blocks.jsonl", subset_blocks)
    write_jsonl(subset_dir / "table_regions.jsonl", [])
    return {
        "input_dir": str(input_dir.resolve()),
        "subset_dir": str(subset_dir.resolve()),
        "selected_pages": selected_pages,
        "text_block_count": len(subset_blocks),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--pages", nargs="*", type=int, default=None)
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--text-model", default=None)
    parser.add_argument("--table-model", default=None)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--retry-base-seconds", type=int, default=5)
    parser.add_argument("--target-terms", nargs="*", default=[])
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    label = "pages_" + "_".join(f"{page:04d}" for page in args.pages) if args.pages else f"{args.max_pages:03d}_pages"
    subset_dir = args.output_root / f"subset_{label}"
    extraction_dir = args.output_root / f"extraction_{label}"
    subset_summary = prepare_subset(args.input_dir.resolve(), subset_dir.resolve(), args.max_pages, args.pages)
    extraction_summary = process_extraction(
        Namespace(
            visual_blocks_dir=subset_dir,
            output_dir=extraction_dir,
            model=args.model,
            text_model=args.text_model,
            table_model=args.table_model,
            api_key_env=args.api_key_env,
            timeout=args.timeout,
            max_retries=args.max_retries,
            retry_base_seconds=args.retry_base_seconds,
            max_workers=1,
            overwrite=args.overwrite,
            target_terms=args.target_terms,
        )
    )
    print(json.dumps({"subset": subset_summary, "extraction": extraction_summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
