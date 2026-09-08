#!/usr/bin/env python3
"""Generate a notebook for Gemini rule extraction from visual block outputs."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "visual_blocks_rule_extraction_gemini31pro_demo.ipynb"


def md(text: str):
    return nbf.v4.new_markdown_cell(dedent(text).strip())


def code(text: str):
    return nbf.v4.new_code_cell(dedent(text).strip())


notebook = nbf.v4.new_notebook()
notebook["cells"] = [
    md(
        """
        # Pipeline 5: Gemini Rule Extraction From Visual Blocks

        This demo consumes the visual block splitter output and runs two independent
        Gemini 3.1 Pro extraction tracks:

        ```text
        hierarchical text blocks -> Gemini text-rule extraction
        title-inclusive table crops -> Gemini table-rule extraction
        ```

        Diagram crops are intentionally ignored in this experiment.
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

        import visual_blocks_rule_extractor as extractor
        import visual_blocks_merge_reviewer as merge_reviewer

        print("REPO_ROOT:", REPO_ROOT)
        print("PIPELINE5_DIR:", PIPELINE5_DIR)
        """
    ),
    md("## Configuration"),
    code(
        r"""
        VISUAL_BLOCKS_DIR = PIPELINE5_DIR / "outputs" / "burnaby" / "gemini_visual_blocks_page2"
        OUTPUT_DIR = PIPELINE5_DIR / "outputs" / "burnaby" / "visual_blocks_rule_extraction_gemini31pro"

        GEMINI_MODEL = "gemini-3.1-pro-preview"
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        # GEMINI_API_KEY = "PASTE_KEY_HERE"  # Optional local override. Do not commit keys.

        OVERWRITE_CACHED_RESPONSES = False
        RUN_API_MERGE_REVIEW = True
        OVERWRITE_CACHED_MERGE_REVIEW = False
        MERGE_REVIEW_BENCHMARK = PIPELINE5_DIR / "benchmarks" / "burnaby_merge_review_gold.json"
        REQUEST_TIMEOUT = 300
        GEMINI_MAX_RETRIES = 3
        GEMINI_RETRY_BASE_SECONDS = 20

        if GEMINI_API_KEY:
            os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

        print("VISUAL_BLOCKS_DIR:", VISUAL_BLOCKS_DIR)
        print("OUTPUT_DIR:", OUTPUT_DIR)
        print("Gemini model:", GEMINI_MODEL)
        print("API key set:", bool(GEMINI_API_KEY))
        """
    ),
    md(
        """
        ## Run Extraction

        The helper automatically filters out `Diagram:` regions. For the current
        Burnaby run, it should consume 7 text-page batches and 4 regulatory-table crops.
        """
    ),
    code(
        r"""
        args = Namespace(
            visual_blocks_dir=VISUAL_BLOCKS_DIR,
            output_dir=OUTPUT_DIR,
            model=GEMINI_MODEL,
            api_key_env="GEMINI_API_KEY",
            timeout=REQUEST_TIMEOUT,
            max_retries=GEMINI_MAX_RETRIES,
            retry_base_seconds=GEMINI_RETRY_BASE_SECONDS,
            overwrite=OVERWRITE_CACHED_RESPONSES,
        )

        summary = extractor.process_extraction(args)
        display(summary)
        """
    ),
    md("## Summary"),
    code(
        r"""
        summary_df = pd.DataFrame([{
            "model": summary["model"],
            "text_blocks": summary["text_block_count"],
            "text_page_batches": summary["text_page_batch_count"],
            "regulatory_tables": summary["regulatory_table_count"],
            "ignored_diagrams": summary["ignored_visual_region_count"],
            "text_rules": summary["text_rule_count"],
            "table_rules": summary["table_rule_count"],
            "combined_rules": summary["combined_rule_count"],
            "deduplicated_rules": summary["deduplicated_rule_count"],
            "auto_folded_groups": summary["auto_folded_group_count"],
            "auto_folded_rules": summary["auto_folded_rule_count"],
            "merge_review_rules": summary["merge_review_rule_count"],
            "text_batches_ok": summary["text_successful_batches"],
            "table_batches_ok": summary["table_successful_batches"],
        }])
        display(summary_df)
        """
    ),
    md("## Inspect Merge Deduplication Audit"),
    code(
        r"""
        merged_rules_df = pd.read_csv(OUTPUT_DIR / "merged_rules_deduplicated.csv")
        merge_audit_df = pd.read_csv(OUTPUT_DIR / "merge_audit.csv")
        merge_review_df = pd.read_csv(OUTPUT_DIR / "merge_review_queue.csv")

        print("Deduplicated rules:", len(merged_rules_df))
        print("Auto-folded groups:", len(merge_audit_df))
        print("Rules removed by auto-folding:", summary["auto_folded_rule_count"])
        print("Rules remaining in merge review queue:", len(merge_review_df))
        display(merge_audit_df.head(100))
        display(merge_review_df.head(100))
        """
    ),
    md("## Inspect Table Rules"),
    code(
        r"""
        table_rules_df = pd.read_csv(OUTPUT_DIR / "table_rules_raw.csv")
        print("Table rules:", len(table_rules_df))
        display(table_rules_df[[
            "source_id", "rule_key", "rule_object", "operator", "value", "unit",
            "condition", "exception", "evidence_text", "warnings",
        ]].head(160))
        """
    ),
    md("## Inspect Text Rules"),
    code(
        r"""
        text_rules_df = pd.read_csv(OUTPUT_DIR / "text_rules_raw.csv")
        print("Text rules:", len(text_rules_df))
        display(text_rules_df[[
            "source_id", "rule_key", "rule_object", "operator", "value", "unit",
            "condition", "exception", "evidence_text", "warnings",
        ]].head(200))
        """
    ),
    md(
        """
        ## Run API Merge Review

        The deterministic merge audit safely folds exact same-evidence duplicates first.
        Gemini then reviews only the remaining queue and must resolve each candidate as
        `KEEP`, `REPLACE`, or `DROP`. The Burnaby benchmark fixture is used only for
        evaluation after the API call; it is not included in the prompt.
        """
    ),
    code(
        r"""
        if RUN_API_MERGE_REVIEW:
            review_args = Namespace(
                visual_blocks_dir=VISUAL_BLOCKS_DIR,
                extraction_output_dir=OUTPUT_DIR,
                model=GEMINI_MODEL,
                api_key_env="GEMINI_API_KEY",
                timeout=REQUEST_TIMEOUT,
                max_retries=GEMINI_MAX_RETRIES,
                retry_base_seconds=GEMINI_RETRY_BASE_SECONDS,
                overwrite=OVERWRITE_CACHED_MERGE_REVIEW,
                benchmark=MERGE_REVIEW_BENCHMARK,
            )
            merge_review_summary = merge_reviewer.run_api_review(review_args)
            display(merge_review_summary)
        else:
            print("API merge review skipped.")
        """
    ),
    md("## Inspect API-Reviewed Registry"),
    code(
        r"""
        if RUN_API_MERGE_REVIEW:
            api_reviewed_df = pd.read_csv(OUTPUT_DIR / "final_rules_api_reviewed.csv")
            api_unresolved_df = pd.DataFrame(json.loads(
                (OUTPUT_DIR / "merge_review_api_unresolved.json").read_text(encoding="utf-8")
            ))
            benchmark_checks_df = pd.read_csv(OUTPUT_DIR / "merge_review_benchmark_checks.csv")
            print("Final API-reviewed rules:", len(api_reviewed_df))
            print("Final consolidated rules:", merge_review_summary["final_rule_count"])
            print("Post-review consolidation actions:", merge_review_summary["post_review_consolidation_action_count"])
            print("Unresolved API-review rules:", len(api_unresolved_df))
            print("Benchmark action accuracy:", merge_review_summary["benchmark_action_accuracy"])
            print("Benchmark action + count accuracy:", merge_review_summary["benchmark_action_and_count_accuracy"])
            print("Benchmark numeric endpoint accuracy:", merge_review_summary["benchmark_numeric_endpoint_accuracy"])
            print("Benchmark full-check accuracy:", merge_review_summary["benchmark_full_check_accuracy"])
            print("Single-file final registry:", OUTPUT_DIR / "final_rule_registry.json")
            display(benchmark_checks_df)
            display(api_unresolved_df)
        """
    ),
    md("## Inspect Logs And Ignored Diagrams"),
    code(
        r"""
        text_logs_df = pd.DataFrame(json.loads((OUTPUT_DIR / "text_extraction_logs.json").read_text(encoding="utf-8")))
        table_logs_df = pd.DataFrame(json.loads((OUTPUT_DIR / "table_extraction_logs.json").read_text(encoding="utf-8")))
        ignored_df = pd.DataFrame(json.loads((OUTPUT_DIR / "ignored_visual_regions.json").read_text(encoding="utf-8")))

        display(text_logs_df)
        display(table_logs_df)
        print("Ignored visual regions:", len(ignored_df))
        if not ignored_df.empty:
            display(ignored_df[["region_id", "page_number", "section_heading", "image_path"]])
        """
    ),
]
notebook["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}

nbf.write(notebook, OUTPUT)
print(f"Wrote {OUTPUT}")
