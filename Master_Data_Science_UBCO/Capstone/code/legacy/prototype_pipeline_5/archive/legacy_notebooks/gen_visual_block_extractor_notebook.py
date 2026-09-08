#!/usr/bin/env python3
"""Generate the notebook wrapper for Gemini visual block extraction."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "gemini_visual_block_extractor_demo.ipynb"


def md(text: str):
    return nbf.v4.new_markdown_cell(dedent(text).strip())


def code(text: str):
    return nbf.v4.new_code_cell(dedent(text).strip())


notebook = nbf.v4.new_notebook()
notebook["cells"] = [
    md(
        """
        # Gemini Visual Block Extractor Demo

        This notebook splits a zoning PDF page into two downstream branches:

        - clause-style text blocks with visible hierarchy and cross-page markers;
        - table image crops that include the nearest visible section heading or table title.

        Gemini is used for page-layout routing only. This notebook does not reconstruct
        tables as markdown and does not extract zoning rules.
        """
    ),
    md("## Imports And Paths"),
    code(
        r"""
        import json
        import os
        import sys
        from argparse import Namespace
        from pathlib import Path

        import pandas as pd
        from IPython.display import Image, display


        def locate_repo_root():
            cwd = Path.cwd()
            for directory in [cwd, *cwd.parents]:
                if (directory / ".git").exists() and (directory / "code").exists():
                    return directory.resolve()
            raise RuntimeError("Could not locate repository root from the current working directory.")


        REPO_ROOT = locate_repo_root()
        PIPELINE5_DIR = REPO_ROOT / "code" / "prototype_pipeline_5"
        if str(PIPELINE5_DIR) not in sys.path:
            sys.path.insert(0, str(PIPELINE5_DIR))

        import gemini_visual_block_extractor as extractor

        print("REPO_ROOT:", REPO_ROOT)
        print("PIPELINE5_DIR:", PIPELINE5_DIR)
        """
    ),
    md(
        """
        ## Configuration

        The default run processes only Burnaby page 2, which contains the most complex
        development-regulations table. Set `PAGES = "1-7"` to process the full document.

        Prefer setting `GEMINI_API_KEY` in your environment. The commented local override
        is convenient for a temporary notebook session but should not be committed.
        """
    ),
    code(
        r"""
        PDF_PATH = REPO_ROOT / "code" / "prototype_pipeline" / "pdfs" / "R1Small-Scale-Multi-Unit-Housing-District.pdf"
        OUTPUT_DIR = PIPELINE5_DIR / "outputs" / "burnaby" / "gemini_visual_blocks_page2"

        PAGES = "2"  # Use "1-7" for the complete Burnaby PDF.
        GEMINI_MODEL = "gemini-3.1-pro-preview"
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        # GEMINI_API_KEY = "PASTE_KEY_HERE"  # Optional local override. Do not commit keys.

        OVERWRITE_CACHED_LAYOUT = False
        RASTER_SCALE = 3.0
        CROP_PADDING_POINTS = 6.0
        REQUEST_TIMEOUT = 300
        GEMINI_MAX_RETRIES = 3
        GEMINI_RETRY_BASE_SECONDS = 20

        if GEMINI_API_KEY:
            os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

        print("PDF_PATH:", PDF_PATH, "exists" if PDF_PATH.exists() else "MISSING")
        print("OUTPUT_DIR:", OUTPUT_DIR)
        print("PAGES:", PAGES)
        print("Gemini model:", GEMINI_MODEL)
        print("API key set:", bool(GEMINI_API_KEY))
        """
    ),
    md("## Run Visual Block Extraction"),
    code(
        r"""
        args = Namespace(
            pdf=PDF_PATH,
            output_dir=OUTPUT_DIR,
            model=GEMINI_MODEL,
            api_key_env="GEMINI_API_KEY",
            pages=PAGES,
            scale=RASTER_SCALE,
            crop_padding_points=CROP_PADDING_POINTS,
            timeout=REQUEST_TIMEOUT,
            max_retries=GEMINI_MAX_RETRIES,
            retry_base_seconds=GEMINI_RETRY_BASE_SECONDS,
            overwrite=OVERWRITE_CACHED_LAYOUT,
        )

        summary = extractor.process_pdf(args)
        display(summary)
        """
    ),
    md("## Inspect Text Blocks"),
    code(
        r"""
        def read_jsonl(path):
            if not path.exists():
                return []
            return [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]


        text_blocks = read_jsonl(OUTPUT_DIR / "text_blocks.jsonl")
        text_blocks_df = pd.DataFrame(text_blocks)
        print("Text blocks:", len(text_blocks_df))
        if not text_blocks_df.empty:
            display(text_blocks_df[[
                "block_id",
                "page_number",
                "reading_order",
                "block_type",
                "section_path",
                "parent_context",
                "text",
                "continues_from_previous_page",
                "continues_on_next_page",
                "warnings",
            ]])
        """
    ),
    md("## Inspect Table Regions And Crops"),
    code(
        r"""
        table_regions = read_jsonl(OUTPUT_DIR / "table_regions.jsonl")
        table_regions_df = pd.DataFrame(table_regions)
        print("Table regions:", len(table_regions_df))
        if not table_regions_df.empty:
            display(table_regions_df[[
                "region_id",
                "page_number",
                "reading_order",
                "section_path",
                "section_heading",
                "crop_bbox",
                "image_path",
                "continues_from_previous_page",
                "continues_on_next_page",
                "warnings",
            ]])

            for region in table_regions:
                crop_path = OUTPUT_DIR / region["image_path"]
                print(region["region_id"], "-", region.get("section_heading", ""))
                display(Image(filename=str(crop_path)))
        """
    ),
    md("## Inspect Combined Reading Order"),
    code(
        r"""
        document_order = read_jsonl(OUTPUT_DIR / "document_order.jsonl")
        document_order_df = pd.DataFrame(document_order)
        print("Ordered items:", len(document_order_df))
        display(document_order_df)
        """
    ),
]
notebook["metadata"] = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {"name": "python", "version": "3"},
}

nbf.write(notebook, OUTPUT)
print(f"Wrote {OUTPUT}")
