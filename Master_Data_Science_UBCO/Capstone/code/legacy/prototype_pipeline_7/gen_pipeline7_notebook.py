#!/usr/bin/env python3
"""Generate the Pipeline 7 notebook (safe, quality-neutral token savings)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).resolve().parent / "pipeline7_rule_extraction.ipynb"
cells: list = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(dedent(text).strip("\n")))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(dedent(text).strip("\n")))


md(
    """
    # Pipeline 7 — Pipeline 5 + safe token savings

    Reuses Pipeline 5's visual splitter, rule extractor, and merge reviewer
    unchanged. Applies only **quality-neutral** optimizations:

    - **S1** lower-resolution page-layout image (`LAYOUT_SCALE = 2.0`) while table
      crops stay full-res (`CROP_SCALE = 3.0`) — table values are read from the crop,
      so reading quality is untouched.
    - **S2** skip the layout API call for pages with no text and no images.
    - **S3** response caching (set `OVERWRITE_API_CACHE = False`).

    Model tiers are **not** downgraded and DPI is not cut below 2.0 (those carry
    quality risk and are deferred).
    """
)

code(
    """
    import json
    import os
    import sys
    from pathlib import Path

    PIPELINE7_DIR = Path.cwd()
    if not (PIPELINE7_DIR / "pipeline7_runner.py").exists():
        PIPELINE7_DIR = Path.cwd() / "code" / "prototype_pipeline_7"
    sys.path.insert(0, str(PIPELINE7_DIR))

    from pipeline7_runner import PIPELINE7_DIR, DEFAULT_PDF, run_pipeline
    """
)

md("## Configuration")
code(
    """
    import getpass
    from argparse import Namespace

    PDF_PATH = str(DEFAULT_PDF)        # any zoning bylaw PDF
    PAGES = None                       # '1-3,7' or None for all pages
    RUN_NAME = "burnaby"
    MODEL = "gemini-3.1-pro-preview"

    # ---- Safe token-saving knobs --------------------------------------------
    LAYOUT_SCALE = 2.0                 # page layout image (lower = cheaper, still lossless)
    CROP_SCALE = 3.0                   # table crops (keep high — quality-critical)
    SKIP_EMPTY_PAGES = True
    OVERWRITE_API_CACHE = False

    # ---- API key: read from env; never stored in this notebook --------------
    API_KEY_ENV = "GEMINI_API_KEY"
    if not os.getenv(API_KEY_ENV):
        os.environ[API_KEY_ENV] = getpass.getpass(f"Enter {API_KEY_ENV}: ")

    args = Namespace(
        pdf=PDF_PATH,
        pages=PAGES,
        run_name=RUN_NAME,
        output_root=PIPELINE7_DIR / "outputs",
        model=MODEL,
        api_key_env=API_KEY_ENV,
        layout_scale=LAYOUT_SCALE,
        scale=CROP_SCALE,
        skip_empty_pages=SKIP_EMPTY_PAGES,
        overwrite=OVERWRITE_API_CACHE,
        skip_rule_extraction=False,
        skip_merge_review=False,
    )
    print("layout_scale:", LAYOUT_SCALE, "| crop_scale:", CROP_SCALE,
          "| skip_empty_pages:", SKIP_EMPTY_PAGES)
    """
)

md("## Run")
code(
    """
    summary = run_pipeline(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    """
)

notebook = nbf.v4.new_notebook()
notebook["cells"] = cells
notebook["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}
NOTEBOOK_PATH.write_text(nbf.writes(notebook) + "\n", encoding="utf-8")
print(f"Wrote {NOTEBOOK_PATH}")
