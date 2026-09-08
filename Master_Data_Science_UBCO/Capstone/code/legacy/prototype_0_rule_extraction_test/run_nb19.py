"""Runner for 19_two_stage_rule_extraction_vancouver_laneway_test.ipynb.

Usage, from code/rule_extraction_test:
    python run_nb19.py

Prerequisites:
  - Notebook 07/12 outputs exist, especially:
      outputs/12_auto_block_selection/selected_blocks_auto.jsonl
      outputs/07_test_bylaw_block_normalization_pipeline/blocks_test.jsonl
  - Ollama is running with the qwen35-rules model:
      ollama serve

This executes the current notebook file, including the evidence-unit inventory,
rule-level evidence verification, and numeric coverage warning layer.
"""
import asyncio
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


NB_PATH = Path(__file__).parent / "19_two_stage_rule_extraction_vancouver_laneway_test.ipynb"
TIMEOUT = 21600  # 6 hours, because evidence-aware prompts are larger
KERNEL = "python3"


print(f"Running: {NB_PATH}")
with NB_PATH.open(encoding="utf-8") as f:
    nb = nbformat.read(f, as_version=4)

client = NotebookClient(
    nb,
    timeout=TIMEOUT,
    kernel_name=KERNEL,
    resources={"metadata": {"path": str(NB_PATH.parent)}},
)
client.execute()

with NB_PATH.open("w", encoding="utf-8") as f:
    nbformat.write(nb, f)

print("Done - notebook updated with cell outputs.")
print("Outputs written to outputs/19_two_stage_rule_extraction_vancouver_laneway_test/")
