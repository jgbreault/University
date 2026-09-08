"""Runner for 15_two_stage_rule_extraction.ipynb

Usage (from the rule_extraction_test directory):
    python run_nb15.py

Prerequisites:
  - run_nb07.py must have been executed first to generate
      outputs/12_auto_block_selection/selected_blocks_auto.jsonl
    (or the fallback selected_blocks_test.jsonl from notebook 07)
  - Ollama must be running with the qwen35-rules model:
      ollama serve       (in a separate terminal)

This notebook runs Surrey only (Coach House, R1 zone).
Two-stage pipeline: extract ALL rules, then classify relevance.
Coverage check: second LLM call for table/exception-heavy/zero-rule blocks.
Outputs: 5 CSV files in outputs/15_two_stage_rule_extraction/

Windows event-loop fix is applied so ZMQ does not fail with ProactorEventLoop.
"""
import sys
import asyncio

# Windows: ZMQ requires SelectorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import nbformat
from nbclient import NotebookClient
from pathlib import Path

NB_PATH  = Path(__file__).parent / "15_two_stage_rule_extraction.ipynb"
TIMEOUT  = 14400  # 4 hours
KERNEL   = "python3"

print(f"Running: {NB_PATH}")
with open(NB_PATH, encoding="utf-8") as f:
    nb = nbformat.read(f, as_version=4)

client = NotebookClient(
    nb,
    timeout=TIMEOUT,
    kernel_name=KERNEL,
    resources={"metadata": {"path": str(NB_PATH.parent)}},
)
client.execute()

# Write executed notebook back
with open(NB_PATH, "w", encoding="utf-8") as f:
    nbformat.write(nb, f)

print("Done — notebook updated with cell outputs.")
print("Outputs written to outputs/15_two_stage_rule_extraction/")
