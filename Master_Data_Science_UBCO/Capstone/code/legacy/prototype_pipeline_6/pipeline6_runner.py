#!/usr/bin/env python3
"""Run the Pipeline 6 staged zoning-rule extraction workflow."""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from gemini_candidate_window_refiner import process_window_refinement
from local_candidate_block_selector import CITY_CONFIGS, PDF_DIR, process_local_selection


PIPELINE6_DIR = Path(__file__).resolve().parent
PIPELINE5_DIR = PIPELINE6_DIR.parent / "prototype_pipeline_5"
if str(PIPELINE5_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE5_DIR))

from gemini_visual_block_extractor import process_pdf  # noqa: E402
from visual_blocks_merge_reviewer import run_api_review  # noqa: E402
from visual_blocks_rule_extractor import process_extraction  # noqa: E402


DEFAULT_MODEL = "gemini-3.1-pro-preview"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city", choices=sorted(CITY_CONFIGS))
    parser.add_argument("--output-root", type=Path, default=PIPELINE6_DIR / "outputs")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--local-only", action="store_true", help="Stop after local candidate generation.")
    parser.add_argument("--skip-window-refinement", action="store_true")
    parser.add_argument("--skip-visual-split", action="store_true")
    parser.add_argument("--skip-rule-extraction", action="store_true")
    parser.add_argument("--skip-merge-review", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-windows", type=int, default=100)
    parser.add_argument("--include-other-zones", action="store_true", help="Scan non-target Surrey zone chapters too.")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pages_arg(pages: list[int]) -> str:
    if not pages:
        raise RuntimeError("No pages were selected for the visual stage.")
    return ",".join(str(page) for page in pages)


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    city_dir = args.output_root.resolve() / args.city
    local_dir = city_dir / "01_local_selection"
    refine_dir = city_dir / "02_window_refinement"
    visual_dir = city_dir / "03_visual_blocks"
    rules_dir = city_dir / "04_rule_extraction"
    config = CITY_CONFIGS[args.city]
    pdf_path = (PDF_DIR / config["pdf"]).resolve()

    summary: dict[str, Any] = {
        "city": args.city,
        "source_pdf": str(pdf_path),
        "model": args.model,
    }
    summary["local_selection"] = process_local_selection(Namespace(
        city=args.city,
        output_dir=local_dir,
        pdf=None,
        context_lines=4,
        neighbor_blocks=2,
        visual_page_radius=1,
        max_windows=args.max_windows,
        include_other_zones=args.include_other_zones,
    ))
    if args.local_only:
        return summary

    if args.skip_window_refinement:
        selected_pages = summary["local_selection"]["recommended_visual_pages"]
    else:
        summary["window_refinement"] = process_window_refinement(Namespace(
            city=args.city,
            local_selection_dir=local_dir,
            output_dir=refine_dir,
            model=args.model,
            api_key_env=args.api_key_env,
            timeout=300,
            max_retries=3,
            retry_base_seconds=20,
            overwrite=args.overwrite,
        ))
        selected_pages = summary["window_refinement"]["recommended_visual_pages"]

    if args.skip_visual_split:
        return summary
    summary["visual_split"] = process_pdf(Namespace(
        pdf=pdf_path,
        output_dir=visual_dir,
        model=args.model,
        api_key_env=args.api_key_env,
        pages=pages_arg(selected_pages),
        scale=3.0,
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
        api_key_env=args.api_key_env,
        timeout=300,
        max_retries=3,
        retry_base_seconds=20,
        overwrite=args.overwrite,
    ))
    if args.skip_merge_review:
        return summary
    summary["merge_review"] = run_api_review(Namespace(
        visual_blocks_dir=visual_dir,
        extraction_output_dir=rules_dir,
        model=args.model,
        api_key_env=args.api_key_env,
        timeout=300,
        max_retries=3,
        retry_base_seconds=20,
        overwrite=args.overwrite,
        benchmark=None,
    ))
    return summary


def main() -> None:
    args = parse_args()
    summary = run_pipeline(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
