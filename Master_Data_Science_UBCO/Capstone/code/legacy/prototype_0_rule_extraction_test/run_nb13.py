"""Runner for 13_multi_city_rule_extraction_generalized.ipynb

Usage (from the rule_extraction_test directory):
    python run_nb13.py

Prerequisite: run_nb07.py must have been executed first to generate
  outputs/12_auto_block_selection/selected_blocks_auto.jsonl

Ollama must be running:
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

NB_PATH  = Path(__file__).parent / "13_multi_city_rule_extraction_generalized.ipynb"
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
print("Outputs written to outputs/13_multi_city_rule_extraction_generalized/")
