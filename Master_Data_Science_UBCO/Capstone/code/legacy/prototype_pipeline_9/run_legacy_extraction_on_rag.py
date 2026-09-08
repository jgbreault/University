#!/usr/bin/env python3
"""Run the legacy visual-block rule extractor on RAG-adapted text blocks."""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PIPELINE5_DIR = ROOT.parent / "prototype_pipeline_5"
if str(PIPELINE5_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE5_DIR))

from visual_blocks_rule_extractor import process_extraction  # noqa: E402


DEFAULT_VISUAL_BLOCKS = ROOT / "outputs" / "calgary" / "05_rag_visual_blocks"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "calgary" / "06_rule_extraction"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-blocks-dir", type=Path, default=DEFAULT_VISUAL_BLOCKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--text-model", default=None)
    parser.add_argument("--table-model", default=None)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=int, default=20)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--target-terms", nargs="*", default=[])
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = process_extraction(
        Namespace(
            visual_blocks_dir=args.visual_blocks_dir,
            output_dir=args.output_dir,
            model=args.model,
            text_model=args.text_model,
            table_model=args.table_model,
            api_key_env=args.api_key_env,
            timeout=args.timeout,
            max_retries=args.max_retries,
            retry_base_seconds=args.retry_base_seconds,
            max_workers=args.max_workers,
            overwrite=args.overwrite,
            target_terms=args.target_terms,
        )
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
