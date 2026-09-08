#!/usr/bin/env python3
"""Generate the single public Pipeline 5 notebook."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "pipeline5_rule_extraction.ipynb"


def md(text: str):
    return nbf.v4.new_markdown_cell(dedent(text).strip())


def code(text: str):
    return nbf.v4.new_code_cell(dedent(text).strip())


notebook = nbf.v4.new_notebook()
notebook["cells"] = [
    md(
        """
        # Pipeline 5: Visual Zoning Rule Extraction

        This is the single public notebook for Pipeline 5. It runs the complete chain:

        ```text
        PDF
         -> Gemini visual routing
         -> hierarchical text blocks + title-inclusive table crops
         -> Gemini text and table rule extraction
         -> deterministic merge audit
         -> Gemini merge review
         -> deterministic post-review consolidation
         -> final_rule_registry.json
        ```

        Diagram regions are retained for audit but intentionally excluded from rule
        extraction.
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
        from IPython.display import display


        def locate_repo_root():
            cwd = Path.cwd()
            for directory in [cwd, *cwd.parents]:
                if (directory / ".git").exists() and (directory / "code").exists():
                    return directory.resolve()
            raise RuntimeError("Could not locate repository root.")


        REPO_ROOT = locate_repo_root()
        PIPELINE5_DIR = REPO_ROOT / "code" / "prototype_pipeline_5"
        if str(PIPELINE5_DIR) not in sys.path:
            sys.path.insert(0, str(PIPELINE5_DIR))

        import gemini_visual_block_extractor as block_extractor
        import visual_blocks_rule_extractor as rule_extractor
        import visual_blocks_merge_reviewer as merge_reviewer

        print("REPO_ROOT:", REPO_ROOT)
        print("PIPELINE5_DIR:", PIPELINE5_DIR)
        """
    ),
    md(
        """
        ## Configuration

        The checked configuration runs the full seven-page Burnaby R1 PDF. Cached
        responses are reused unless an overwrite flag is enabled.
        """
    ),
    code(
        r"""
        PDF_PATH = REPO_ROOT / "code" / "prototype_pipeline" / "pdfs" / "R1Small-Scale-Multi-Unit-Housing-District.pdf"
        VISUAL_BLOCKS_DIR = PIPELINE5_DIR / "outputs" / "burnaby" / "visual_blocks"
        RULE_OUTPUT_DIR = PIPELINE5_DIR / "outputs" / "burnaby" / "rule_extraction"
        MERGE_REVIEW_BENCHMARK = PIPELINE5_DIR / "benchmarks" / "burnaby_merge_review_gold.json"

        PAGES = "1-7"
        GEMINI_MODEL = "gemini-3.1-pro-preview"
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        # GEMINI_API_KEY = "PASTE_KEY_HERE"  # Optional local override. Do not commit keys.

        OVERWRITE_CACHED_LAYOUT = False
        OVERWRITE_CACHED_RULE_EXTRACTION = False
        OVERWRITE_CACHED_MERGE_REVIEW = False

        RASTER_SCALE = 3.0
        CROP_PADDING_POINTS = 6.0
        REQUEST_TIMEOUT = 300
        GEMINI_MAX_RETRIES = 3
        GEMINI_RETRY_BASE_SECONDS = 20

        if GEMINI_API_KEY:
            os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

        print("PDF_PATH:", PDF_PATH, "exists" if PDF_PATH.exists() else "MISSING")
        print("VISUAL_BLOCKS_DIR:", VISUAL_BLOCKS_DIR)
        print("RULE_OUTPUT_DIR:", RULE_OUTPUT_DIR)
        print("PAGES:", PAGES)
        print("Gemini model:", GEMINI_MODEL)
        print("API key set:", bool(GEMINI_API_KEY))
        """
    ),
    md("## 1. Visual Block Extraction"),
    code(
        r"""
        block_args = Namespace(
            pdf=PDF_PATH,
            output_dir=VISUAL_BLOCKS_DIR,
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

        block_summary = block_extractor.process_pdf(block_args)
        display(pd.DataFrame([{
            "model": block_summary["model"],
            "pages": len(block_summary["selected_pages"]),
            "text_blocks": block_summary["text_block_count"],
            "visual_regions": block_summary["table_region_count"],
        }]))
        """
    ),
    md("## 2. Text And Table Rule Extraction"),
    code(
        r"""
        extraction_args = Namespace(
            visual_blocks_dir=VISUAL_BLOCKS_DIR,
            output_dir=RULE_OUTPUT_DIR,
            model=GEMINI_MODEL,
            api_key_env="GEMINI_API_KEY",
            timeout=REQUEST_TIMEOUT,
            max_retries=GEMINI_MAX_RETRIES,
            retry_base_seconds=GEMINI_RETRY_BASE_SECONDS,
            overwrite=OVERWRITE_CACHED_RULE_EXTRACTION,
        )

        extraction_summary = rule_extractor.process_extraction(extraction_args)
        display(pd.DataFrame([{
            "text_page_batches": extraction_summary["text_page_batch_count"],
            "regulatory_tables": extraction_summary["regulatory_table_count"],
            "ignored_diagrams": extraction_summary["ignored_visual_region_count"],
            "text_rules": extraction_summary["text_rule_count"],
            "table_rules": extraction_summary["table_rule_count"],
            "combined_raw_rules": extraction_summary["combined_rule_count"],
            "deduplicated_rules": extraction_summary["deduplicated_rule_count"],
            "merge_review_candidates": extraction_summary["merge_review_rule_count"],
        }]))
        """
    ),
    md("## 3. API Merge Review And Final Consolidation"),
    code(
        r"""
        review_args = Namespace(
            visual_blocks_dir=VISUAL_BLOCKS_DIR,
            extraction_output_dir=RULE_OUTPUT_DIR,
            model=GEMINI_MODEL,
            api_key_env="GEMINI_API_KEY",
            timeout=REQUEST_TIMEOUT,
            max_retries=GEMINI_MAX_RETRIES,
            retry_base_seconds=GEMINI_RETRY_BASE_SECONDS,
            overwrite=OVERWRITE_CACHED_MERGE_REVIEW,
            benchmark=MERGE_REVIEW_BENCHMARK,
        )

        review_summary = merge_reviewer.run_api_review(review_args)
        display(pd.DataFrame([review_summary]))
        """
    ),
    md("## 4. Final Registry"),
    code(
        r"""
        FINAL_REGISTRY_PATH = RULE_OUTPUT_DIR / "final_rule_registry.json"
        final_registry = json.loads(FINAL_REGISTRY_PATH.read_text(encoding="utf-8"))
        final_rules_df = pd.DataFrame(final_registry["rules"])

        print("Final registry:", FINAL_REGISTRY_PATH)
        display(pd.DataFrame([{
            key: value
            for key, value in final_registry.items()
            if key != "rules"
        }]))
        display(final_rules_df)
        """
    ),
    md("## 5. Audit Artifacts"),
    code(
        r"""
        merge_audit_df = pd.read_csv(RULE_OUTPUT_DIR / "merge_audit.csv")
        consolidation_audit_df = pd.read_csv(RULE_OUTPUT_DIR / "post_review_consolidation_audit.csv")
        unresolved = json.loads((RULE_OUTPUT_DIR / "merge_review_api_unresolved.json").read_text(encoding="utf-8"))
        ignored_regions = json.loads((RULE_OUTPUT_DIR / "ignored_visual_regions.json").read_text(encoding="utf-8"))

        print("Initial merge-audit groups:", len(merge_audit_df))
        print("Post-review consolidation actions:", len(consolidation_audit_df))
        print("Unresolved API-review rules:", len(unresolved))
        print("Ignored diagram regions:", len(ignored_regions))
        display(merge_audit_df)
        display(consolidation_audit_df)
        """
    ),
]
notebook["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}

nbf.write(notebook, OUTPUT)
print(f"Wrote {OUTPUT}")
