#!/usr/bin/env python3
"""Pipeline 8 — Pipeline 6 city generalization + Pipeline 7 token optimization.

Pipeline 8 fuses two earlier prototypes and changes **nothing** about how rules
are read:

  * Pipeline 6 city generalization (stages 01-02). A config-driven local
    candidate selector (``CITY_CONFIGS``) plus a Gemini window-refinement pass
    narrow a full bylaw PDF down to the pages that actually carry the target
    zone's rules, so the same flow runs on Burnaby / Vancouver / Surrey from a
    single ``city`` argument.
  * Pipeline 7 safe token savings (stage 03). The full-page LAYOUT image is
    rendered at a lower ``layout_scale`` (default 2.0) while quality-critical
    table CROPS stay at ``crop_scale`` (default 3.0); empty pages skip the
    layout API call; cached API JSON is reused unless ``--overwrite``. Per-stage
    model overrides exist but every stage defaults to ``--model`` — no
    quality-risking tier downgrade is applied by default.

Stages: local selection -> window refinement -> visual split -> rule extraction
-> merge review. Only the visual-split call carries Pipeline 7's two extra knobs
(``layout_scale``, ``skip_empty_pages``); every other stage is byte-for-byte the
same call Pipeline 6 makes, so the extracted rules are unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

PIPELINE8_DIR = Path(__file__).resolve().parent
PIPELINE6_DIR = PIPELINE8_DIR.parent / "prototype_pipeline_6"
PIPELINE5_DIR = PIPELINE8_DIR.parent / "prototype_pipeline_5"
for _dep_dir in (PIPELINE6_DIR, PIPELINE5_DIR):
    if str(_dep_dir) not in sys.path:
        sys.path.insert(0, str(_dep_dir))

# Pipeline 6 generalization stages.
from gemini_candidate_window_refiner import process_window_refinement  # noqa: E402
from local_candidate_block_selector import CITY_CONFIGS, PDF_DIR, process_local_selection  # noqa: E402

# Shared Pipeline 5 stages (also used by Pipeline 6 and 7).
from gemini_visual_block_extractor import process_pdf  # noqa: E402
from visual_blocks_merge_reviewer import run_api_review  # noqa: E402
from visual_blocks_rule_extractor import process_extraction  # noqa: E402


DEFAULT_MODEL = "gemini-3.1-pro-preview"

# Pipeline 7 safe token-saving defaults.
DEFAULT_LAYOUT_SCALE = 2.0   # full-page layout/bbox image (lossless for digital PDFs)
DEFAULT_CROP_SCALE = 3.0     # table crops — quality-critical, keep high


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city", choices=sorted(CITY_CONFIGS))
    parser.add_argument("--output-root", type=Path, default=PIPELINE8_DIR / "outputs")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Default model for all stages.")
    # Per-stage model overrides (each defaults to --model). The Pipeline 7 cost
    # analysis showed layout + text extraction tolerate a cheaper model, while
    # table-image reading and merge review should stay on the strong model.
    parser.add_argument("--layout-model", default=None, help="Override model for the page-layout (visual split) stage.")
    parser.add_argument("--refine-model", default=None, help="Override model for window refinement.")
    parser.add_argument("--text-model", default=None, help="Override model for text rule extraction.")
    parser.add_argument("--table-model", default=None, help="Override model for table-image rule extraction (quality-critical).")
    parser.add_argument("--review-model", default=None, help="Override model for merge review (reasoning-critical).")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    # Pipeline 7 token-saving knobs (applied only to the visual-split stage).
    parser.add_argument("--layout-scale", type=float, default=DEFAULT_LAYOUT_SCALE,
                        help="Scale for the full-page layout image (lower = fewer tokens; safe for digital PDFs).")
    parser.add_argument("--scale", type=float, default=DEFAULT_CROP_SCALE,
                        help="Table-crop scale (quality-critical; keep high).")
    parser.add_argument("--no-skip-empty-pages", dest="skip_empty_pages", action="store_false",
                        help="Disable the Pipeline 7 optimization that skips the layout API call for empty pages.")
    parser.set_defaults(skip_empty_pages=True)
    parser.add_argument("--no-local-visual", dest="local_visual", action="store_false",
                        help="Disable local-first layout (text-layer blocks + PyMuPDF table detection) and "
                        "always use the per-page vision layout call. Local-first is on by default; pages with "
                        "no extractable text (scanned) fall back to vision automatically.")
    parser.set_defaults(local_visual=True)
    # Pipeline 6 stage gating.
    parser.add_argument("--local-only", action="store_true", help="Stop after local candidate generation.")
    parser.add_argument("--skip-window-refinement", action="store_true")
    parser.add_argument("--skip-visual-split", action="store_true")
    parser.add_argument("--skip-rule-extraction", action="store_true")
    parser.add_argument("--skip-merge-review", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Call Gemini again even when cached JSON exists.")
    parser.add_argument("--max-workers", type=int, default=8,
                        help="Concurrent API calls per stage (window refinement / visual split / rule extraction). "
                        "1 = sequential (Pipeline 6 behavior). Independent per-page calls run in parallel.")
    parser.add_argument("--no-prune-windows", dest="prune_windows", action="store_false",
                        help="Disable block-level pruning of bare use-list / index windows. Pruning is on by "
                        "default and drops windows with no rule signal before window refinement (fewer API calls).")
    parser.set_defaults(prune_windows=True)
    parser.add_argument("--max-windows", type=int, default=100)
    parser.add_argument("--include-other-zones", action="store_true", help="Scan non-target Surrey zone chapters too.")
    return parser.parse_args()


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

    layout_model = args.layout_model or args.model
    refine_model = args.refine_model or args.model
    text_model = args.text_model or args.model
    table_model = args.table_model or args.model
    review_model = args.review_model or args.model

    summary: dict[str, Any] = {
        "pipeline": "pipeline8_generalized_token_optimized",
        "city": args.city,
        "source_pdf": str(pdf_path),
        "model": args.model,
        "stage_models": {
            "layout": layout_model,
            "refine": refine_model,
            "text": text_model,
            "table": table_model,
            "review": review_model,
        },
        "layout_scale": args.layout_scale,
        "crop_scale": args.scale,
        "skip_empty_pages": args.skip_empty_pages,
        "local_visual": args.local_visual,
    }

    # --- Stage 01: city-generic local candidate selection (deterministic, offline) ---
    summary["local_selection"] = process_local_selection(Namespace(
        city=args.city,
        output_dir=local_dir,
        pdf=None,
        context_lines=4,
        neighbor_blocks=2,
        visual_page_radius=1,
        max_windows=args.max_windows,
        prune_windows=args.prune_windows,
        include_other_zones=args.include_other_zones,
    ))
    if args.local_only:
        return summary

    # --- Stage 02: Gemini window refinement (decides which pages to process visually) ---
    if args.skip_window_refinement:
        selected_pages = summary["local_selection"]["recommended_visual_pages"]
    else:
        summary["window_refinement"] = process_window_refinement(Namespace(
            city=args.city,
            local_selection_dir=local_dir,
            output_dir=refine_dir,
            model=refine_model,
            api_key_env=args.api_key_env,
            timeout=300,
            max_retries=3,
            retry_base_seconds=20,
            overwrite=args.overwrite,
            max_workers=args.max_workers,
        ))
        selected_pages = summary["window_refinement"]["recommended_visual_pages"]

    if args.skip_visual_split:
        return summary

    # --- Stage 03: visual split WITH Pipeline 7 token optimization (the only changed call) ---
    summary["visual_split"] = process_pdf(Namespace(
        pdf=pdf_path,
        output_dir=visual_dir,
        model=layout_model,
        api_key_env=args.api_key_env,
        pages=pages_arg(selected_pages),
        scale=args.scale,                 # crop scale (high, quality-critical)
        layout_scale=args.layout_scale,   # page layout image scale (lower, safe) — Pipeline 7 S1
        skip_empty_pages=args.skip_empty_pages,  # Pipeline 7 S2
        local_visual=args.local_visual,   # local-first layout (text layer + find_tables), vision fallback
        crop_padding_points=6.0,
        timeout=300,
        max_retries=3,
        retry_base_seconds=20,
        overwrite=args.overwrite,
        max_workers=args.max_workers,
    ))
    if args.skip_rule_extraction:
        return summary

    # --- Stage 04: rule extraction (unchanged) ---
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
        max_workers=args.max_workers,
    ))
    if args.skip_merge_review:
        return summary

    # --- Stage 05: merge review (unchanged) ---
    summary["merge_review"] = run_api_review(Namespace(
        visual_blocks_dir=visual_dir,
        extraction_output_dir=rules_dir,
        model=review_model,
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
