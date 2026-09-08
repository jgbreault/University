#!/usr/bin/env python3
"""Pipeline 7 — Pipeline 5 with safe, quality-neutral token savings.

Pipeline 7 reuses Pipeline 5's visual splitter, rule extractor, and merge reviewer
unchanged. It only applies token optimizations that do NOT affect the extracted
rules:

  S1. Separate image scales: the full-page LAYOUT image is rendered at a lower
      `layout_scale` (default 2.0), while table CROPS — the quality-critical
      part where values are read — stay at `crop_scale` (default 3.0).
  S2. Skip the layout API call for pages with no text and no images.
  S3. Response caching (reuse cached API JSON unless --overwrite).

It deliberately does NOT downgrade any model tier or cut DPI below 2.0, since
those carry quality risk. See README.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

PIPELINE7_DIR = Path(__file__).resolve().parent
PIPELINE5_DIR = PIPELINE7_DIR.parent / "prototype_pipeline_5"
if str(PIPELINE5_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE5_DIR))

from gemini_visual_block_extractor import process_pdf  # noqa: E402
from visual_blocks_merge_reviewer import run_api_review  # noqa: E402
from visual_blocks_rule_extractor import process_extraction  # noqa: E402

DEFAULT_MODEL = "gemini-3.1-pro-preview"
PDF_DIR = PIPELINE7_DIR.parent / "prototype_pipeline" / "pdfs"
DEFAULT_PDF = PDF_DIR / "R1Small-Scale-Multi-Unit-Housing-District.pdf"

# Safe token-saving defaults.
DEFAULT_LAYOUT_SCALE = 2.0   # full-page layout/bbox image (lossless for digital PDFs)
DEFAULT_CROP_SCALE = 3.0     # table crops — quality-critical, keep high


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.output_root.resolve() / args.run_name
    visual_dir = out_dir / "03_visual_blocks"
    rules_dir = out_dir / "04_rule_extraction"
    pdf_path = Path(args.pdf).resolve()

    # Per-stage model overrides (each defaults to --model). The cost analysis showed
    # the layout (page-image) and text-extraction stages tolerate a cheaper model,
    # while table-image reading and merge review should stay on the strong model.
    layout_model = getattr(args, "layout_model", None) or args.model
    text_model = getattr(args, "text_model", None) or args.model
    table_model = getattr(args, "table_model", None) or args.model
    review_model = getattr(args, "review_model", None) or args.model

    summary: dict[str, Any] = {
        "pipeline": "pipeline7_safe_optimized",
        "source_pdf": str(pdf_path),
        "model": args.model,
        "stage_models": {
            "layout": layout_model,
            "text": text_model,
            "table": table_model,
            "review": review_model,
        },
        "layout_scale": args.layout_scale,
        "crop_scale": args.scale,
        "skip_empty_pages": args.skip_empty_pages,
    }

    summary["visual_split"] = process_pdf(Namespace(
        pdf=pdf_path,
        output_dir=visual_dir,
        model=layout_model,
        api_key_env=args.api_key_env,
        pages=args.pages,
        scale=args.scale,                 # crop scale (high, quality-critical)
        layout_scale=args.layout_scale,   # page layout image scale (lower, safe)
        skip_empty_pages=args.skip_empty_pages,
        crop_padding_points=6.0,
        timeout=300,
        max_retries=3,
        retry_base_seconds=20,
        overwrite=args.overwrite,
    ))
    if args.skip_rule_extraction:
        return summary

    summary["rule_extraction"] = process_extraction(Namespace(
        visual_blocks_dir=visual_dir,
        output_dir=rules_dir,
        model=args.model,
        text_model=text_model,
        table_model=table_model,
        api_key_env=args.api_key_env,
        timeout=300,
        max_retries=3,
        retry_base_seconds=20,
        overwrite=args.overwrite,
    ))
    if args.skip_merge_review:
        return summary

    benchmark_arg = getattr(args, "benchmark", None)
    benchmark_path = Path(benchmark_arg).resolve() if benchmark_arg else None
    summary["merge_review"] = run_api_review(Namespace(
        visual_blocks_dir=visual_dir,
        extraction_output_dir=rules_dir,
        model=review_model,
        api_key_env=args.api_key_env,
        timeout=300,
        max_retries=3,
        retry_base_seconds=20,
        overwrite=args.overwrite,
        benchmark=benchmark_path,
    ))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default=str(DEFAULT_PDF), help="Source bylaw PDF.")
    parser.add_argument("--pages", default=None, help="1-based page selection, e.g. '1-3,7' (default: all).")
    parser.add_argument("--run-name", default="burnaby", help="Subfolder under --output-root.")
    parser.add_argument("--output-root", type=Path, default=PIPELINE7_DIR / "outputs")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Default model for all stages.")
    parser.add_argument("--layout-model", default=None, help="Override model for the page-layout (visual split) stage.")
    parser.add_argument("--text-model", default=None, help="Override model for text rule extraction.")
    parser.add_argument("--table-model", default=None, help="Override model for table-image rule extraction (quality-critical).")
    parser.add_argument("--review-model", default=None, help="Override model for merge review (reasoning-critical).")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--layout-scale", type=float, default=DEFAULT_LAYOUT_SCALE)
    parser.add_argument("--scale", type=float, default=DEFAULT_CROP_SCALE, help="Table-crop scale.")
    parser.add_argument("--no-skip-empty-pages", dest="skip_empty_pages", action="store_false")
    parser.add_argument(
        "--benchmark",
        default=None,
        help="Optional gold fixture (JSON) for merge-review evaluation. The fixture must be "
             "keyed on THIS run's merged_rule_ids; the pipeline5 Burnaby gold is NOT id-compatible "
             "with pipeline7 (different review population). See benchmarks/.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-rule-extraction", action="store_true")
    parser.add_argument("--skip-merge-review", action="store_true")
    parser.set_defaults(skip_empty_pages=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_pipeline(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
