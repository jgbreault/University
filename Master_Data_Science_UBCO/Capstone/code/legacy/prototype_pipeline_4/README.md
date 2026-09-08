# Prototype Pipeline 4

Integrated zoning bylaw rule extraction pipeline. Pipeline 4 reads an official zoning PDF and produces a structured rule registry where every rule is tied to an object, a numeric constraint, and a traceable evidence source.

Pipeline 4 is a targeted upgrade of [Pipeline 3](../prototype_pipeline_3/) that improves **deterministic table extraction only**. Everything else - block extraction, block selection, non-table API extraction, API table semantic review, normalization, verification, and outputs - is unchanged.

## Design philosophy

Rules are extracted along two independent tracks that are later merged:

- **Deterministic table track** - PyMuPDF native table detection recovers the raw cell grid. The pipeline propagates group titles, row labels, and column headers into structured *cell facts*, then converts each fact into atomic `object / operator / value / unit / condition` rules without asking an LLM to invent or read values. An optional Gemini pass may review relevance and action hints, but it never changes the extracted numbers.
- **Non-table API track** - selected text blocks are split into legal clauses and sent to Gemini in block-level batches. Gemini extracts rules with a fixed JSON schema; every rule must cite an `evidence_id` back to the original clause.

After extraction, both streams are normalized, merged, deduplicated, and verified. Verification checks that each rule's value is visible in its evidence text, that the operator is consistent with the evidence wording, and applies `ACCEPT / REVIEW / REJECT` routing.

Supported cities / zones: **Burnaby R1** (Rear Principal Building or Front Principal Building), **Vancouver RS** (Laneway House), **Surrey R1** (Coach House / Garden Suite).

## What changed from Pipeline 3

Four bugs were fixed in the table extraction stage (`build_structured_cell_facts_from_df` and `rules_from_cell_fact`):

### Fix 1 — Span detection (`all_value_cells_identical`)

**Problem**: When a PDF table row has a single merged cell that applies to all dwelling types (e.g. "Rear Principal Buildings / Height / 7.5 m"), PyMuPDF repeats the value in every column. Pipeline 3 emitted one cell fact per column and each inherited a column header like "Rowhouse" or "Small-Scale 1-2 Units", creating spurious dwelling-type conditions on universal rules.

**Fix**: Before processing each row, check whether all value-bearing cells (columns 2+) are identical. If they are, emit only one fact with no column header.

**Effect on Burnaby R1**: reduces spurious duplicates on height, setback, and separation rules that apply to all dwelling types.

### Fix 2 — Merged-cell second pass

**Problem**: PyMuPDF collapses PDF horizontally-merged cells into the leftmost detected column. A rule that spans the entire table width (e.g. accessory building height) lands in the Rowhouse column only, making it look like a Rowhouse-specific rule with a column condition of "Rowhouse / 1 to 3 Units".

**Fix**: After building all facts, scan for rows where exactly one fact was produced and that fact has a Rowhouse column header. If all other columns in that raw row are empty (not even a dash), the cell is a merged cell — clear its `column_header_path`.

**Effect**: `max_accessory_building_height`, `max_accessory_building_storeys`, and similar universal rules lose their incorrect "Rowhouse only" tag.

### Fix 3 — Multi-condition `condition: value%` extraction

**Problem**: The Burnaby lot-coverage table cell for Small-Scale Multi-Unit 1-2 units reads:
```
Lots < 567 m2: 40%
Lots > 567 m2: 30%
```
Pipeline 3 used `re.search` on this pattern, capturing only the first match (40 %). The 30% rule for large lots was silently dropped.

**Fix**: Replace `re.search` with `re.findall` to capture every `condition: value%` match in the cell text, emitting one atomic rule per match.

**Effect**: `max_lot_coverage_all_buildings <= 30%` for `Lots > 567 m2` is now correctly extracted — a rule that was missing in Pipeline 3 and sasivimol.

Also fixed in the same cell: the base rule in an `except` pattern (e.g. `"3.0 m, except 1.5 m for accessory buildings"`) now clears its column header so the base value does not inherit a dwelling-type condition.

### Fix 4 — Sticky row label for multi-row PDF cells

**Problem**: PDF tables sometimes place a single label in the first physical row of a merged cell, leaving subsequent rows with no row label. For example, the Burnaby lot-coverage table has two rows for the Small-Scale 1-2 unit column:
```
All Buildings  |  Lots < 567 m2: 40%
               |  Lots > 567 m2: 30%   ← row_label = empty → missing_row_label → skipped
```
`rules_from_cell_fact` exits immediately on `missing_row_label`, so the 30 % rule was silently dropped.

**Fix**: Track `last_valid_row_label` across rows within a group. When a row has value-bearing cells but no inferred label, inherit the previous valid label. The sticky label resets on every new group section or subject-context line, so it cannot leak across unrelated rule blocks.

**Effect**: `max_lot_coverage_all_buildings <= 30%` for `Lots > 567 m2` is now correctly emitted — the last table rule that was missing from both Pipeline 3 and all prior versions.

## How to run

1. Install the prototype requirements from `code/prototype_pipeline/requirements.txt`.
2. Set `GEMINI_API_KEY` in your environment if API extraction is enabled.
3. Open `pipeline4_integrated_rule_extraction.ipynb`.
4. In the first config cell, choose:
   - `TARGET_CITY` - `"burnaby"`, `"vancouver"`, or `"surrey"`
   - `TARGET_BUILDING_TYPE` - for Burnaby, `"rear_principal"` or `"front_principal"`
   - `RUN_API_NON_TABLE_EXTRACTION` - set `False` to skip Gemini calls and reuse cached output
   - `RUN_API_TABLE_SEMANTIC_REVIEW` - set `False` to skip the optional table review pass
   - `RUN_BLOCK_SELECTION_LLM` - set `True` to enable the optional local Ollama selector
5. Run all cells.

The notebook is generated from `gen_pipeline4.py`. Re-run that script to regenerate the `.ipynb` after editing the generator.

## Pipeline stages

```
PDF
 |
 v
01  Local block extraction
     pymupdf4llm -> page-level markdown blocks with doc/city/zone/section metadata
 |
 v
02  Local block selection
     Keyword scoring (primary terms + parent terms + universal development-regulation terms)
     + recall expansion to adjacent pages around strong hits
     Optional: local Ollama LLM to drop obviously irrelevant pages
 |
 +---------------------------------------------------------+
 v non-table text                                          v table pages
03a Clause splitting                                  03b PyMuPDF table detection
    rule-hint filtering                                   structured cell fact extraction
    -> non_table_evidence.csv                             (group/row/column propagation)
 |                                                       -> structured_cell_facts.csv
 v                                                        |
04  Gemini API extraction                            07  Deterministic rule generation
    block-level batches                                   (no LLM for values)
    -> non_table_rules_raw.csv                            -> table_rules_deterministic.csv
                                                          |
                                                     08  Optional Gemini semantic review
                                                          (relevance + action hint only)
                                                          -> table_semantic_reviews.csv
 |                                                        |
 +---------------------------+----------------------------+
                             v
                    09  Normalize + merge
                        key normalization, operator inference
                        -> all_rules_merged_raw.csv
                             |
                             v
                    10  Verification + dedup
                        value visibility check, operator support check
                        review-word detection, ACCEPT/REVIEW/REJECT routing
                        specificity-based deduplication
                        -> final_registry.csv
                             |
                             v
                    11  Save outputs + handoff package
                        accepted_rules.csv, review_queue.csv
                        06_teammate_verification_handoff/
```

## Outputs

All outputs are written under:

```
code/prototype_pipeline_4/outputs/<city>/pipeline4_<city>_<building_type>_rule_pipeline/
```

The building-type component is included for cities such as Burnaby that have multiple target configurations.

| Folder | File | Contents |
|--------|------|----------|
| `01_blocks/` | `blocks.jsonl` | All page blocks extracted from the PDF |
| `02_selected_blocks/` | `selected_blocks.jsonl` | Blocks that passed keyword scoring |
| `03_evidence/` | `non_table_evidence.csv` | Legal clauses extracted from non-table text |
| `03_evidence/` | `structured_cell_facts.csv` | One row per value-bearing table cell |
| `03_evidence/` | `pymupdf_find_tables_*_table.csv` | Raw table grids (one file per detected table) |
| `03_evidence/` | `table_extraction_logs.json` | Selected table candidates and extraction diagnostics |
| `04_api_raw/` | `non_table_rules_raw.csv` | Raw Gemini output for non-table clauses |
| `04_api_raw/` | `table_semantic_reviews.csv` | Optional Gemini relevance review of table rules |
| `05_rules/` | `table_rules_deterministic.csv` | Table rules before API review |
| `05_rules/` | `all_rules_merged_raw.csv` | Both streams merged before verification |
| `05_rules/` | `final_registry.csv` | Deduplicated, verified registry (all actions) |
| `05_rules/` | `accepted_rules.csv` | Rules routed to ACCEPT |
| `05_rules/` | `review_queue.csv` | Rules routed to REVIEW |
| `05_rules/` | `verification_warnings.csv` | Rules with evidence/operator gaps |
| `05_rules/` | `expected_key_coverage.csv` | Coverage check against known expected rule keys |
| `05_rules/` | `pipeline4_summary.md` | Run summary with counts by stream and key |
| `06_teammate_verification_handoff/` | `rule_candidates.json/.csv` | All non-rejected rules for downstream verification |
| `06_teammate_verification_handoff/` | `accepted_rule_candidates.json/.csv` | Accepted rules only |
| `06_teammate_verification_handoff/` | `review_rule_candidates.json/.csv` | Rules that need human review |
| `06_teammate_verification_handoff/` | `evidence_units.json` | All evidence units (clause + table cell) for traceability |

## Burnaby R1 sample results

The latest checked-in `pipeline4_burnaby_rear_principal_rule_pipeline` sample selected
all seven PDF pages and completed both extraction tracks. The deterministic table
track recovered numeric constraints from structured cells, while the Gemini
non-table track recovered rules from legal clauses that do not appear in tables.

| Metric | Count |
|--------|-------|
| PDF pages / selected blocks | 7 / 7 |
| Non-table evidence clauses | 51 |
| Successful non-table API chunks | 7 / 7 |
| Gemini non-table rules | 55 |
| Structured cell facts | 47 |
| Deterministic table rules | 56 |
| Combined raw rules | 111 |
| Deduplicated final registry | 110 |
| Accepted rules | 79 |
| Notes retained | 18 |
| Review / rejected rules | 13 / 0 |
| Verification warnings | 3 |
| Expected Burnaby keys found | 32 / 37 |
| Downstream handoff candidates | 110 |
| Evidence units retained for audit | 98 |

The deterministic table track generated 56 rules and produced 55 accepted rules after
deduplication:

| Source page | Accepted rules | Main content |
|-------------|---------------:|--------------|
| Page 1 | 9 | Subdivision lot width and lot area |
| Page 2 | 44 | Units, lot coverage, height, setbacks, and separation |
| Page 4 | 2 | Minimum number of 3+ bedroom units |

All 55 accepted table rules passed local value-visibility and operator-support checks
with no table-track verification warnings.

## Overall Extraction Coverage

Pipeline 4 combines deterministic table extraction with Gemini-assisted legal-text
extraction. This hybrid architecture improves coverage while keeping each rule tied to
traceable evidence.

### Deterministic table track

The table pipeline recovered the core numeric development regulations, including:

- permitted dwelling-unit ranges;
- minimum lot width and lot area;
- maximum lot coverage and impervious-surface limits;
- front, rear, and accessory-building height and storey limits;
- street, lane, rear-yard, and side-yard setbacks;
- minimum separation distances between building combinations;
- the 3+ bedroom-unit requirement.

All 55 deduplicated table rules passed the local value-visibility and operator-support
checks. The deterministic table track has no verification warnings.

### Gemini non-table track

The local non-table splitter prepared 51 clauses across all pages. All seven
page-grouped API requests completed successfully and produced 55 rules:

| Page | Prepared clauses |
|------|-----------------:|
| 1 | 4 |
| 2 | 5 |
| 3 | 1 |
| 4 | 12 |
| 5 | 11 |
| 6 | 14 |
| 7 | 4 |

These clauses include rules that cannot be recovered from tables alone, such as:

- main-entrance orientation;
- pedestrian walkway spacing, width, and clearance;
- automatic sprinkler and fire-access-corridor requirements;
- heritage-lot exceptions;
- parking exceptions;
- accessory-structure and projection rules;
- measurement and reference clauses.

After normalization and verification, the non-table track contributed 24 automatically
accepted rules, 18 contextual notes, and 13 rules for lightweight human review. The
review queue primarily contains exceptions, cross-references, discretionary wording,
and external approval conditions. No rules were rejected.

### Final routing

| Routing | Count | Meaning |
|---------|------:|---------|
| `ACCEPT` | 79 | Directly usable rules |
| `NOTE` | 18 | Retained contextual or exception rules |
| `REVIEW` | 13 | Lightweight human confirmation |
| `REJECT` | 0 | No pipeline-rejected rules |

### Current expected-key coverage

The deterministic table-only baseline finds 24 of the 37 Burnaby expected keys. The
latest hybrid run finds 32 of 37 exact expected-key names:

| Result | Expected keys found | Coverage |
|--------|--------------------:|---------:|
| Deterministic table-only baseline | 24 / 37 | 64.9% |
| Hybrid table + non-table run | 32 / 37 | 86.5% |

Two additional target-relevant rule categories were extracted but currently use more
specific normalized names:

| Expected key | Extracted form |
|--------------|----------------|
| `min_panhandle_width` | Lane-access and no-lane-access variants |
| `not_required_off_street_parking` | `parking_location_permission` with operator `not required` |

Within the rear-principal target scope, the pipeline therefore recovered all relevant
expected rule categories. The remaining expected keys are use-specific rules outside
the rear-principal scope:

| Missing expected key |
|----------------------|
| `max_pedestrian_walkway_spacing` |
| `min_pedestrian_walkway_width` |
| `min_floor_area` |

See `05_rules/pipeline4_summary.md`, `04_api_raw/non_table_api_logs.csv`, and
`05_rules/expected_key_coverage.csv` for the exact saved run.

## Expected improvements vs Pipeline 3 (Burnaby R1)

| Metric | Pipeline 3 | Pipeline 4 (expected) |
|---|---|---|
| Spurious Rowhouse-only conditions on universal rules | present | removed |
| `max_lot_coverage_all_buildings <= 30%` (large lots) | missing | present |
| Duplicate facts for merged/spanned rows | ~4 extra | 0 |
| All other metrics | unchanged | unchanged |
