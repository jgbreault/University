# Prototype Pipeline 3

Integrated zoning bylaw rule extraction pipeline. Pipeline 3 is the current best prototype: it reads an official zoning PDF and produces a structured rule registry where every rule is tied to an object, a numeric constraint, and a traceable evidence source.

## Design philosophy

Rules are extracted along two independent tracks that are later merged:

- **Deterministic table track** — PyMuPDF native table detection recovers the raw cell grid. The pipeline then propagates group titles, row labels, and column headers into structured *cell facts*, and converts each fact into atomic `object / operator / value / unit / condition` rules without asking an LLM to invent or read values. An optional Gemini pass may review relevance and action hints, but it never changes the extracted numbers.
- **Non-table API track** — selected text blocks are split into legal clauses and sent to Gemini in block-level batches. Gemini extracts rules with a fixed JSON schema; every rule must cite an `evidence_id` back to the original clause.

After extraction both streams are normalized, merged, deduplicated, and verified. Verification checks that each rule's value is visible in its evidence text, that the operator is consistent with the evidence wording, and applies `ACCEPT / REVIEW / REJECT` routing.

Supported cities / zones: **Burnaby R1** (Rear Principal Building), **Vancouver RS** (Laneway House), **Surrey R1** (Coach House / Garden Suite).

## How to run

1. Install the prototype requirements from `code/prototype_pipeline/requirements.txt`.
2. Set `GEMINI_API_KEY` in your environment if API extraction is enabled.
3. Open `pipeline3_integrated_rule_extraction.ipynb`.
4. In the first config cell, choose:
   - `TARGET_CITY` — `"burnaby"`, `"vancouver"`, or `"surrey"`
   - `RUN_API_NON_TABLE_EXTRACTION` — set `False` to skip Gemini calls and reuse cached output
   - `RUN_API_TABLE_SEMANTIC_REVIEW` — set `False` to skip the optional table review pass
   - `RUN_BLOCK_SELECTION_LLM` — set `True` to enable the optional local Ollama selector
5. Run all cells top to bottom.

The notebook is generated from `gen_pipeline3.py`. Re-run that script to regenerate the `.ipynb` after editing the generator.

## Pipeline stages

```
PDF
 │
 ▼
01  Local block extraction
     pymupdf4llm → page-level markdown blocks with doc/city/zone/section metadata
 │
 ▼
02  Local block selection
     Keyword scoring (primary terms + parent terms + universal development-regulation terms)
     + recall expansion to adjacent pages around strong hits
     Optional: local Ollama LLM to drop obviously irrelevant pages
 │
 ├──────────────────────────────────────────────────────┐
 ▼ non-table text                                       ▼ table pages
03a  Clause splitting                               03b  PyMuPDF table detection
      rule-hint filtering                                cell fact extraction
      → non_table_evidence.csv                           (group/row/column propagation)
 │                                                       → structured_cell_facts.csv
 ▼                                                       │
04   Gemini API extraction                          07   Deterministic rule generation
      block-level batches                               (no LLM for values)
      → non_table_rules_raw.csv                         → table_rules_deterministic.csv
                                                         │
                                                    08   Optional Gemini semantic review
                                                         (relevance + action hint only)
                                                         → table_semantic_reviews.csv
 │                                                       │
 └──────────────────────────┬──────────────────────────┘
                            ▼
                   09  Normalize + merge
                        key normalization, operator inference
                        → all_rules_merged_raw.csv
                            │
                            ▼
                   10  Verification + dedup
                        value visibility check, operator support check
                        review-word detection, ACCEPT/REVIEW/REJECT routing
                        specificity-based deduplication
                        → final_registry.csv
                            │
                            ▼
                   11  Save outputs + handoff package
                        accepted_rules.csv, review_queue.csv
                        06_teammate_verification_handoff/
```

## Outputs

All outputs are written under:

```
code/prototype_pipeline_3/outputs/<city>/pipeline3_<city>_rule_pipeline/
```

| Folder | File | Contents |
|--------|------|----------|
| `01_blocks/` | `blocks.jsonl` | All page blocks extracted from the PDF |
| `02_selected_blocks/` | `selected_blocks.jsonl` | Blocks that passed keyword scoring |
| `03_evidence/` | `non_table_evidence.csv` | Legal clauses extracted from non-table text |
| `03_evidence/` | `structured_cell_facts.csv` | One row per value-bearing table cell |
| `03_evidence/` | `pymupdf_find_tables_*_table.csv` | Raw table grids (one file per detected table) |
| `04_api_raw/` | `non_table_rules_raw.csv` | Raw Gemini output for non-table clauses |
| `04_api_raw/` | `table_semantic_reviews.csv` | Optional Gemini relevance review of table rules |
| `05_rules/` | `table_rules_deterministic.csv` | Table rules before API review |
| `05_rules/` | `all_rules_merged_raw.csv` | Both streams merged before verification |
| `05_rules/` | `final_registry.csv` | Deduplicated, verified registry (all actions) |
| `05_rules/` | `accepted_rules.csv` | Rules routed to ACCEPT |
| `05_rules/` | `review_queue.csv` | Rules routed to REVIEW |
| `05_rules/` | `verification_warnings.csv` | Rules with evidence/operator gaps |
| `05_rules/` | `expected_key_coverage.csv` | Coverage check against known expected rule keys |
| `05_rules/` | `pipeline3_summary.md` | Run summary with counts by stream and key |
| `06_teammate_verification_handoff/` | `rule_candidates.json/.csv` | All non-rejected rules for downstream verification |
| `06_teammate_verification_handoff/` | `accepted_rule_candidates.json/.csv` | Accepted rules only |
| `06_teammate_verification_handoff/` | `review_rule_candidates.json/.csv` | Rules that need human review |
| `06_teammate_verification_handoff/` | `evidence_units.json` | All evidence units (clause + table cell) for traceability |

## Burnaby R1 sample results

Running on `R1Small-Scale-Multi-Unit-Housing-District.pdf` (7 pages):

| Metric | Count |
|--------|-------|
| Selected blocks | 7 / 7 |
| Non-table evidence clauses | 51 |
| Structured cell facts | 51 |
| Deterministic table rules | 58 |
| Non-table API rules (raw) | 63 |
| Final registry (deduped) | 120 |
| Accepted | 64 |
| Review queue | 49 |
| Rejected | 7 |
| Expected keys covered | 34 / 34 |
