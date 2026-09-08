#!/usr/bin/env python3
"""Generate the single public Pipeline 6 notebook."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent


PIPELINE_DIR = Path(__file__).resolve().parent
NOTEBOOK_PATH = PIPELINE_DIR / "pipeline6_rule_extraction.ipynb"


def markdown(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": dedent(source).strip().splitlines(True)}


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": dedent(source).strip().splitlines(True),
    }


cells = [
    markdown(
        """
        # Pipeline 6: Recall-Efficient Visual Rule Extraction

        Pipeline 6 adds a local recall layer before the Gemini visual pipeline:

        `PDF -> local blocks -> scored context windows -> Gemini window refinement -> selected-page visual split -> rule extraction -> merge review`

        The local stage is API-free. It is especially useful for long bylaws such as Surrey's 348-page source PDF.
        """
    ),
    code(
        """
        import json
        import os
        import sys
        from pathlib import Path

        PIPELINE6_DIR = Path.cwd()
        if not (PIPELINE6_DIR / "pipeline6_runner.py").exists():
            PIPELINE6_DIR = Path.cwd() / "code" / "prototype_pipeline_6"
        sys.path.insert(0, str(PIPELINE6_DIR))

        from pipeline6_runner import PIPELINE6_DIR, run_pipeline
        """
    ),
    markdown(
        """
        ## Configuration

        Start with `LOCAL_ONLY = True` to inspect recall and API savings. Set it to `False` after setting `GEMINI_API_KEY` to run the complete chain.
        """
    ),
    code(
        """
        import getpass
        from argparse import Namespace

        TARGET_CITY = "vancouver"  # "burnaby", "vancouver", or "surrey"
        LOCAL_ONLY = True
        MODEL = "gemini-3.1-pro-preview"
        OVERWRITE_API_CACHE = False
        MAX_WINDOWS = 100
        INCLUDE_OTHER_ZONES = False  # Surrey defaults to R1 plus shared city-wide regulations.

        # The API key is read from this environment variable name, never stored here.
        # Preferred: set GEMINI_API_KEY in your OS environment before launching.
        # Fallback: if it is missing and an API run is requested, prompt once below;
        # getpass keeps the key out of the saved notebook.
        API_KEY_ENV = "GEMINI_API_KEY"
        if not LOCAL_ONLY and not os.getenv(API_KEY_ENV):
            os.environ[API_KEY_ENV] = getpass.getpass(f"Enter {API_KEY_ENV}: ")

        args = Namespace(
            city=TARGET_CITY,
            output_root=PIPELINE6_DIR / "outputs",
            model=MODEL,
            api_key_env=API_KEY_ENV,
            local_only=LOCAL_ONLY,
            skip_window_refinement=False,
            skip_visual_split=False,
            skip_rule_extraction=False,
            skip_merge_review=False,
            overwrite=OVERWRITE_API_CACHE,
            max_windows=MAX_WINDOWS,
            include_other_zones=INCLUDE_OTHER_ZONES,
        )
        """
    ),
    markdown("## Run Selected City"),
    code(
        """
        summary = run_pipeline(args)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        """
    ),
    markdown(
        """
        ## Compare Local Recall for Vancouver and Surrey

        This optional API-free cell reports the coarse-selection savings before any Gemini request is sent.
        """
    ),
    code(
        """
        comparison = {}
        for city in ["vancouver", "surrey"]:
            local_args = Namespace(**{**vars(args), "city": city, "local_only": True})
            comparison[city] = run_pipeline(local_args)["local_selection"]

        for city, result in comparison.items():
            print(
                f"{city.title()}: {result['pdf_page_count']} PDF pages -> "
                f"{result['candidate_window_count']} candidate windows; "
                f"{result['recommended_visual_page_count']} pre-refinement visual pages "
                f"({result['visual_page_reduction_percent']}% reduction)"
            )
        """
    ),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

NOTEBOOK_PATH.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
print(f"Wrote {NOTEBOOK_PATH}")
