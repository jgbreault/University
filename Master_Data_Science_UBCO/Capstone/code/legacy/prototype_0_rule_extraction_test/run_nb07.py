"""Runner for 07_bylaw_block_pipeline.ipynb

Usage (from the rule_extraction_test directory):
    python run_nb07.py

Stage 1 & 2 (PDF parsing + scoring) run without Ollama.
Stage 3 (LLM verification) calls Ollama — make sure it is running first:
    ollama serve       (in a separate terminal)

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

NB_PATH  = Path(__file__).parent / "07_bylaw_block_pipeline.ipynb"
TIMEOUT  = 14400  # 4 hours (PDF parsing is slow for large bylaws)
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
print("Outputs written to:")
print("  outputs/07_test_bylaw_block_normalization_pipeline/blocks_test.jsonl")
print("  outputs/12_auto_block_selection/selected_blocks_auto.jsonl")
print("  outputs/12_auto_block_selection/verification_report.csv")
print("  outputs/12_auto_block_selection/selection_summary.txt")
