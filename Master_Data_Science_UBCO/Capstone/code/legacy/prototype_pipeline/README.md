# Prototype Rule Extraction Pipeline (Upgraded to Pipeline 3 — See `../prototype_pipeline_3/`)

> **Note:** This is Pipeline 1. The current best prototype has been superseded by [prototype_pipeline_3](../prototype_pipeline_3/), which adds deterministic table extraction, a dual-track (table + non-table) merge, and a teammate verification handoff package. This folder is kept for reference and because Pipeline 3 imports shared helpers from it (`prototype_target_aware_helpers.py`, `pdfs/`).

This folder contains a runnable prototype notebook that combines block extraction, block selection, evidence-grounded rule extraction, verification, and output generation.

Notebook:

```text
prototype_rule_extraction_pipeline.ipynb
```

## Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

You also need to install and run your own local LLM service. The notebook currently assumes Ollama:

```python
MODEL_NAME = "qwen35-rules"
OLLAMA_URL = "http://localhost:11434/api/generate"
```

Note: `qwen35-rules` is only the local Ollama model name used in this project. It refers to an untuned Qwen3 9B model, not a rule-extraction fine-tuned model.

If you use a different local model, change `MODEL_NAME` and `OLLAMA_URL` in the first configuration cell.

The notebook also exposes a thinking-mode switch:

```python
LLM_THINKING_MODE = "no_think"
```

Use `"no_think"` for the default faster evidence-level calls, `"think"` to compare whether explicit thinking improves extraction quality, or `"none"` to send no thinking directive. The run summaries and extraction logs include `thinking_mode` and per-call `llm_seconds`, so you can compare runtime and output quality across runs.

## How To Use

Open the notebook and edit the first configuration cell:

```python
TARGET_CITY = "vancouver"
```

Supported values:

```python
"vancouver"
"burnaby"
"surrey"
```

Then run:

1. `Restart Kernel`
2. `Run All`

The notebook can be run from the repo root, `code/`, or this folder. It automatically changes into `code/prototype_pipeline`, so the prototype uses its own local PDFs and output folder.

Source PDFs are stored in:

```text
code/prototype_pipeline/pdfs/
```

By default, the prototype runs the full selected-block pipeline:

```python
SMOKE_TEST = False
```

The extraction progress bar advances by evidence/rule item, not by block. The postfix shows the current block id suffix and the cumulative number of parsed rules. For a quick end-to-end check, set `SMOKE_TEST = True` in the first configuration cell.

Outputs are written to:

```text
code/prototype_pipeline/outputs/prototype_<city>_rule_pipeline/
```

## Pipeline Summary

1. **Configuration**
   Select city, target building type, local LLM model, output paths, and extraction settings.

2. **PDF To Blocks**
   Parse the selected bylaw PDF into page-level markdown blocks. Each block keeps source metadata such as document id, city, zone, page, section, and full markdown text.

3. **Candidate Block Proposal**
   Score blocks using target building terms and general zoning terms such as floor area, setback, height, lot coverage, parking, and separation. This stage favors recall.

4. **LLM Block Verification**
   Ask the LLM whether each candidate block contains substantive rules for the selected building type or an applicable parent category. This removes keyword false positives before rule extraction.

5. **Topic Labeling**
   Assign a loose topic label such as `floor_area`, `setbacks`, `height`, or `development_regulations`. This is for context and debugging, not a hard extraction filter.

6. **Object-Based Rule Schema**
   Extract rules as `rule_object + constraint_type + constraint_scope` instead of unstable generated names. For example, site width becomes `site_dimension / min / site_width`, and rear setback becomes `setback / min / rear_yard`.

7. **Evidence Unit Construction**
   Trim selected blocks to the target section scope, then split them into traceable evidence units: sentences, clauses, table rows, table cells, and heading-plus-clause units. This prevents a selected page from leaking into the next unrelated bylaw section.

8. **Evidence-Grounded Rule Extraction**
   Run extraction one evidence unit at a time. Every rule must cite an `evidence_id`, so every value is traceable to a specific source sentence, clause, or table row.

9. **Verification Layer**
   This step integrates Yusen's sentence-level verification idea into the main pipeline. Each extracted rule is converted into a lightweight candidate and checked deterministically against its cited evidence for visible object, value, unit, and operator support.

10. **Numeric Coverage Check**
    Normalize area notation such as `m [2]` / `m2` to `sq. m`, extract visible numeric facts from each evidence unit, and check whether the rules citing that evidence account for them. Uncovered values become review warnings.

11. **Coverage Audit**
    Run a compact LLM audit for table-heavy, exception-heavy, or zero-rule blocks to catch likely missed rules.

12. **Deduplication And Validation**
    Deduplicate rules using object, constraint, scope, value, unit, condition, and section. Attach validation warnings instead of deleting risky rules.

13. **Outputs**
    Save enriched rule tables, evidence units, numeric coverage warnings, validation warnings, and a final verified-or-review registry.
