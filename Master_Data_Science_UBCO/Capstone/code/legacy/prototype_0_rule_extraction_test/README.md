# Rule Extraction Test

This folder contains experiments for extracting structured zoning rules from the Surrey zoning bylaw PDF. The current target document is `BYL_Zoning_12000.pdf`, with the latest experiment focused on Coach House / Garden Suite rules in Surrey `R1 Suburban Residential Zone`.

## Experiment Phase 1: Single-City Rule Extraction

The current approach is block-based extraction, not page-by-page extraction. The first-stage Surrey R1 pipeline is:

1. `00_compare_pdf_parsers.ipynb`
   - Compares PyMuPDF, PyMuPDF4LLM, Docling, Unstructured, and other parser options.
   - PyMuPDF is used as the page-number ground truth and visual line/span source.
   - PyMuPDF4LLM is used as the main markdown/table text source.
   - Docling is kept as an optional backup.

2. `01_surrey_coach_house_page_relevance.ipynb`
   - Uses strict keywords and residential zone anchors to find Coach House / Garden Suite candidate pages.
   - Produces candidate pages, context pages, and preview files for early page targeting and sanity checks.

3. `03_build_surrey_document_map_and_blocks.ipynb`
   - Builds the PDF page map, zone map, zone subsection map, and extraction-ready blocks.
   - The current R1 zone is detected as PDF pages `114-123`, with no document-map quality warnings.
   - Writes block text files to `outputs/document_map/block_texts/`.
   - Later LLM extraction reads these block files instead of the full PDF.

4. `05_extract_surrey_r1_rules_all_categories.ipynb`
   - This is the latest R1 Coach House / Garden Suite extraction notebook.
   - Uses local Ollama endpoint: `http://localhost:11434/api/generate`.
   - Current model name in the notebook: `qwen35-rules`.
   - Output directory: `outputs/rule_extraction_r1_all_categories/`.
   - The latest run processes only R1 and only these blocks:
     - `r1_permitted_uses_density`
     - `r1_floor_area_fsr`
     - `r1_lot_coverage`
     - `r1_setbacks_base`
     - `r1_setback_reductions`
     - `r1_height`
     - `r1_parking_access_other`

`02_surrey_r1_coach_house_rule_extraction.ipynb` and `04_extract_surrey_rules_from_blocks.ipynb` are earlier/intermediate experiments. The latest result should be read from `05_extract_surrey_r1_rules_all_categories.ipynb`.

## Experiment Phase 2: Multi-City Generalized Pipeline

The second phase extends the Surrey-only experiment into a multi-city workflow. The main goal is to test whether the same block-based method can generalize across different municipal zoning bylaw formats, with less manual block configuration.

The current complete Phase 2 pipeline is:

1. `07_bylaw_block_pipeline.ipynb`
   - Expands the input scope from one Surrey zoning bylaw PDF to three city/document targets:
     - Surrey: `BYL_Zoning_12000.pdf`
     - Burnaby: `R1Small-Scale-Multi-Unit-Housing-District.pdf`
     - Vancouver: `zoning-by-law-section-11.pdf`
   - Normalizes each PDF into page-level blocks.
   - Uses city-specific primary keywords plus universal secondary zoning keywords to score every block.
   - Keeps top candidate blocks per document.
   - Uses an LLM verification prompt to decide whether each candidate block directly contains rules for the target building type.
   - Writes all normalized blocks to:

```text
outputs/07_test_bylaw_block_normalization_pipeline/blocks_test.jsonl
```

   - Writes the automatically selected relevant blocks to:

```text
outputs/12_auto_block_selection/selected_blocks_auto.jsonl
```

2. `13_multi_city_rule_extraction_generalized.ipynb`
   - Reads the auto-selected blocks from `outputs/12_auto_block_selection/selected_blocks_auto.jsonl`.
   - Replaces hand-written per-block extraction profiles with universal `TOPIC_PROFILES`.
   - Automatically detects the block topic from headings and block text, such as:
     - `setbacks`
     - `height`
     - `floor_area`
     - `development_regulations`
   - Applies one general multi-city extraction prompt to all selected blocks.
   - Extracts explicit zoning rules into a shared structured schema.
   - Allows city-specific rule keys when no canonical rule key fits.
   - Runs validation checks for blocked keys, target scope, condition leakage, ungrounded values, exceptions, and ungrounded conditions.
   - Writes the generalized extraction result to:

```text
outputs/13_multi_city_rule_extraction_generalized/
```

Phase 2 changes the experiment from:

```text
single city -> manually selected Surrey R1 blocks -> category-specific extraction
```

to:

```text
multiple cities -> automatic block creation and block selection -> universal prompt-based rule extraction
```

### Phase 2 Pipeline Implementation Notes

Phase 2 is built around a simple normalization idea: convert every city PDF into the same block format first, then run selection and extraction on those normalized blocks. The LLM does not read the full PDF. It only receives one selected block at a time with metadata.

#### Normalization

`07_bylaw_block_pipeline.ipynb` normalizes each PDF into page-level JSONL blocks. Each block keeps:

```text
block_id, doc_id, city, zone, building_type, page, section, title, markdown/text
```

The `block_id` combines document ID, detected section heading, and page number, for example:

```text
surrey_zoning_12000__13__0118
burnaby_r1__101_6_3__0006
vancouver_section_11_2026_02__11_3_8_8__0009
```

This page-level normalization is deliberately conservative. It avoids writing a separate structural parser for every municipal bylaw format, while still giving each downstream step a stable unit of text, page provenance, and city/zone/building metadata.

After normalization, all blocks are saved to:

```text
outputs/07_test_bylaw_block_normalization_pipeline/blocks_test.jsonl
```

The notebook then scores blocks using target-specific keywords, parent-category terms, and general zoning terms such as `setback`, `height`, `floor area`, `lot coverage`, `parking`, and `lane`. The top candidate blocks are checked by an LLM verification prompt, and only verified relevant blocks are written to:

```text
outputs/12_auto_block_selection/selected_blocks_auto.jsonl
```

`13_multi_city_rule_extraction_generalized.ipynb` reads this file, detects a topic for each block, and applies a shared extraction prompt. Topic profiles such as `setbacks`, `height`, `floor_area`, and `development_regulations` control which rule keys are preferred or blocked. This replaces the earlier hand-built block-by-block prompt setup.

#### Current Quality

The current Phase 2 run is functional across three city/document targets: Surrey Coach House, Burnaby Rear Principal Building, and Vancouver Laneway House. It successfully normalized `377` page blocks, selected `8` verified relevant blocks, and extracted `62` deduped rule rows.

Validation quality is generally good on hard failures:

```text
blocked_key_violations: 0
condition_leakage_warnings: 0
ungrounded_value_warnings: 0
target_scope_warnings: 0
exception_extraction_warnings: 0
```

The main remaining review signal is:

```text
outside_allowed_keys: 6
ungrounded_condition_warnings: 14
```

This suggests the pipeline is already able to extract structured rules from multiple cities without manual block selection, but conditions and city-specific rule keys still need review before treating the output as final.

#### Current Challenges

- PDF layouts vary by city, so page-level normalization is robust but sometimes coarse. One page can contain multiple topics, or a rule can continue across pages.
- Some rules apply through parent categories, especially in Burnaby. The pipeline handles this with configured type hierarchy, but these cases remain harder to validate automatically.
- Automatic topic detection works for common headings, but mixed regulation tables often fall into the broader `development_regulations` profile.
- Conditions and exceptions are the hardest part. The model may extract the numeric value correctly while attaching a condition that is not fully grounded in the same row, clause, or note.
- The current selection step prioritizes recall over precision, so LLM verification is still needed after keyword scoring.

### Phase 2 Current Run Summary

The latest Phase 2 run uses:

```text
model: qwen35-rules
input_jsonl: outputs/12_auto_block_selection/selected_blocks_auto.jsonl
selected_blocks: 8
processed_blocks: 8
raw_rule_rows: 67
deduped_rule_rows: 62
blocked_key_violations: 0
outside_allowed_keys: 6
condition_leakage_warnings: 0
ungrounded_value_warnings: 0
target_scope_warnings: 0
exception_extraction_warnings: 0
ungrounded_condition_warnings: 14
```

Automatic block normalization and selection produced:

```text
total_blocks_loaded: 377
total_candidates: 37
verified_relevant: 8
```

Per-document selected block counts:

| City | Document ID | Candidate blocks | Verified relevant blocks |
| --- | --- | ---: | ---: |
| Surrey | `surrey_zoning_12000` | 15 | 3 |
| Burnaby | `burnaby_r1` | 7 | 3 |
| Vancouver | `vancouver_section_11_2026_02` | 15 | 2 |

Block results from the latest generalized extraction:

| City | Block | Detected topic | Rule count |
| --- | --- | --- | ---: |
| Surrey | `surrey_zoning_12000__16__0161` | `setbacks` | 8 |
| Surrey | `surrey_zoning_12000__13__0119` | `setbacks` | 5 |
| Surrey | `surrey_zoning_12000__13__0118` | `height` | 6 |
| Burnaby | `burnaby_r1__unknown__0002` | `development_regulations` | 10 |
| Burnaby | `burnaby_r1__101_6_3__0006` | `setbacks` | 13 |
| Burnaby | `burnaby_r1__unknown__0003` | `setbacks` | 3 |
| Vancouver | `vancouver_section_11_2026_02__11_3_7_1__0008` | `development_regulations` | 12 |
| Vancouver | `vancouver_section_11_2026_02__11_3_8_8__0009` | `floor_area` | 10 |

### Phase 2 Key Outputs

| File | Purpose |
| --- | --- |
| `outputs/07_test_bylaw_block_normalization_pipeline/blocks_test.jsonl` | All page-level normalized blocks across the selected city documents |
| `outputs/12_auto_block_selection/selected_blocks_auto.jsonl` | Blocks automatically selected and verified as relevant for extraction |
| `outputs/12_auto_block_selection/verification_report.csv` | Candidate-block verification log and relevance decisions |
| `outputs/12_auto_block_selection/selection_summary.txt` | Summary of block scoring and selected blocks by city |
| `outputs/13_multi_city_rule_extraction_generalized/rules_deduped.csv` | Final deduped multi-city rule table |
| `outputs/13_multi_city_rule_extraction_generalized/rules_deduped.xlsx` | Excel version of the final deduped rule table |
| `outputs/13_multi_city_rule_extraction_generalized/rules_by_block_raw.json` | Raw parsed rules grouped by source block |
| `outputs/13_multi_city_rule_extraction_generalized/block_extraction_log_full.xlsx` | Full LLM extraction log, raw outputs, prompt context, and parsing status |
| `outputs/13_multi_city_rule_extraction_generalized/block_validation_report.xlsx` | Validation report for the generalized extraction |
| `outputs/13_multi_city_rule_extraction_generalized/block_extraction_summary.txt` | Core Phase 2 run summary |

### Phase 2 Reproduction Notes

To reproduce the current Phase 2 experiment:

1. Open `code/rule_extraction_test/`.
2. Confirm the three input PDFs exist in this folder:
   - `BYL_Zoning_12000.pdf`
   - `R1Small-Scale-Multi-Unit-Housing-District.pdf`
   - `zoning-by-law-section-11.pdf`
3. Make sure Ollama is installed and running locally.
4. Make sure the local model alias `qwen35-rules` is available, or update the model name in the notebooks.
5. Run `07_bylaw_block_pipeline.ipynb`.
6. Confirm `outputs/12_auto_block_selection/selected_blocks_auto.jsonl` was created.
7. Run `13_multi_city_rule_extraction_generalized.ipynb`.
8. Review `outputs/13_multi_city_rule_extraction_generalized/block_extraction_summary.txt` and `outputs/13_multi_city_rule_extraction_generalized/rules_deduped.csv`.

## Experiment Phase 3: Toward Generalized Bylaw-File Extraction

Phase 3 tests whether the workflow can move beyond a few hand-reviewed city examples and become a general pipeline for new bylaw files. The main shift is from rule-name-based extraction to an object-based rule schema plus source coverage checking.

The current Phase 3 pipeline starts from the same normalized blocks created by `07_bylaw_block_pipeline.ipynb`:

```text
PDFs -> normalized page blocks -> candidate scoring -> LLM block verification
```

The latest `07` run produced:

```text
total_blocks_loaded: 377
total_candidates: 34
verified_relevant: 12
```

Verified relevant blocks are now:

| City | Document ID | Verified relevant blocks |
| --- | --- | ---: |
| Surrey | `surrey_zoning_12000` | 7 |
| Burnaby | `burnaby_r1` | 3 |
| Vancouver | `vancouver_section_11_2026_02` | 2 |

### Phase 3 Pipeline

1. `07_bylaw_block_pipeline.ipynb`
   - Normalizes every configured PDF into page-level JSONL blocks.
   - Scores all blocks with target-specific and general zoning keywords.
   - Uses LLM verification to keep blocks that likely contain target rules.
   - Writes selected blocks to:

```text
outputs/12_auto_block_selection/selected_blocks_auto.jsonl
```

2. `15_two_stage_rule_extraction.ipynb`
   - Current Surrey Coach House testbed for the new object-based schema.
   - Extracts rules as:

```text
rule_object + constraint_type + constraint_scope
```

   - Examples:
     - `lot_coverage + max + lot_area_band`
     - `setback + min + rear_yard`
     - `building_height + max + floodplain`
     - `storeys + max`
   - This avoids relying on brittle generated names such as `max_lot_coverage_laneway`.

3. `16_two_stage_rule_extraction_burnaby_table_test.ipynb`
   - Burnaby table-block stress test.
   - Tests mixed development-regulation tables where many rules are compressed into one markdown table.
   - Large tables are split into row batches. Each extracted rule keeps:

```text
extraction_unit_id, unit_row_start, unit_row_end
```

   - The latest Burnaby table test split one table block into `5` batches and extracted `39` deduped rule rows.
   - This recovered rules from the front half of the table that the single-prompt version missed, including dwelling units, lot area, lot coverage, and impervious surface limits.

4. `17_source_coverage_inventory.ipynb`
   - Adds a deterministic source coverage layer.
   - Does not call the LLM.
   - Reads extracted rules and source blocks, then inventories meaningful source evidence:
     - numeric values
     - units
     - ranges
     - rule-bearing table rows
     - important regulatory terms
   - Marks each item as covered, uncovered, artifact, or needs review.
   - The latest Burnaby table audit found `136` evidence rows, with `115` covered and `7` high-risk uncovered.

5. `18_high_risk_coverage_repair.ipynb`
   - Consumes high-risk uncovered evidence from notebook 17.
   - Groups evidence into row-level repair cases.
   - Skips repeated heading rows.
   - Optionally calls the LLM only on small repair cases instead of rerunning the whole block.
   - Writes candidate repair rules separately and does not merge them automatically.
   - In the latest run, `18` sent `4` cases to the LLM; all were judged `already_covered`, so no candidate repair rules were added.

### Current Phase 3 Quality

Phase 3 is promising but not finished. The strongest improvement is that source coverage is now auditable from the original text, not only from the model's self-reported coverage.

Current strengths:

- `07` can normalize and select relevant blocks across Surrey, Burnaby, and Vancouver.
- Object-based extraction makes rule semantics easier to validate than generated rule names.
- Table batching improves recall for dense regulation tables.
- Deterministic source coverage catches possible missed text without adding LLM runtime.
- Repair is small and controlled: only high-risk uncovered rows are sent to the LLM.

Current challenges:

- Table batching improves recall but increases runtime because one large table becomes multiple LLM calls.
- Some source coverage warnings are conservative. Heading rows may be flagged as high risk even when their numeric child rows are already covered.
- Relevance categories still need careful handling. `direct`, `generic_applicable`, and `indirect` should not always be merged into the same final rule table.
- Parent-category rules, such as `All Buildings` or `Principal Buildings`, are important for generalization but require explicit downstream interpretation.
- The pipeline has been tested on three city/document targets, but it is not yet proven across all bylaw files.

### Phase 3 Key Outputs

| File | Purpose |
| --- | --- |
| `outputs/12_auto_block_selection/selected_blocks_auto.jsonl` | Verified blocks from notebook 07 |
| `outputs/15_two_stage_rule_extraction/` | Surrey object-based two-stage extraction output |
| `outputs/16_two_stage_rule_extraction_burnaby_table_test/` | Burnaby dense-table batch extraction output |
| `outputs/17_source_coverage_inventory/source_coverage_inventory.csv` | Deterministic evidence coverage inventory |
| `outputs/17_source_coverage_inventory/source_coverage_high_risk.csv` | High-risk uncovered evidence |
| `outputs/18_high_risk_coverage_repair/repair_cases.csv` | Row-level repair cases |
| `outputs/18_high_risk_coverage_repair/candidate_repair_rules.csv` | Optional LLM repair candidates, kept separate from final rules |

### Phase 3 Generalization Plan

The intended generalized pipeline for new bylaw files is:

```text
07 normalize/select
  -> 15-style object-based extraction
  -> table batching when needed
  -> 17 deterministic source coverage
  -> optional 18 high-risk repair
  -> final reviewed rule table
```

The next step is to apply this whole Phase 3 loop to every configured bylaw document, then compare source coverage rates and high-risk uncovered counts by document. The goal is not just to maximize extracted rule count, but to ensure that every meaningful number, condition, and regulatory term in selected blocks has an explicit explanation.

## Latest Experiment: Surrey R1 Coach House Extraction

The latest complete output is in:

```text
outputs/rule_extraction_r1_all_categories/
```

Run summary:

```text
model: qwen35-rules
run_all_blocks: False
run_zone: R1
selected_blocks: 7
processed_blocks: 7
raw_rule_rows: 22
deduped_rule_rows: 22
validation_rows: 22
blocked_key_violations: 0
outside_allowed_keys: 0
condition_leakage_warnings: 0
ungrounded_value_warnings: 0
target_scope_warnings: 0
exception_extraction_warnings: 2
ungrounded_condition_warnings: 4
```

Extraction result by block:

| Block | Rule count | Notes |
| --- | ---: | --- |
| `r1_permitted_uses_density` | 2 | Coach House permitted/accessory-use related rules |
| `r1_floor_area_fsr` | 3 | Minimum/maximum coach house floor area and 120 sq. m conditional maximum |
| `r1_lot_coverage` | 4 | Lot coverage bands and calculated reduction formula |
| `r1_setbacks_base` | 5 | Front yard not permitted, rear/side/street-side setbacks, separation |
| `r1_setback_reductions` | 1 | Rear yard reduction to 1.0 m with rear lane garage/carport condition |
| `r1_height` | 7 | Height, storeys, roof peak height, floodplain-related variations |
| `r1_parking_access_other` | 0 | No coach house-specific rule extracted in this run |

Summary by category:

| Category | Count |
| --- | ---: |
| `accessory_use` | 2 |
| `floor_area` | 3 |
| `lot_coverage` | 4 |
| `height` | 7 |
| `setback` | 5 |
| `separation` | 1 |

All 22 deduped rules have `high` confidence.

## Key Outputs

Main files from the latest experiment:

| File | Purpose |
| --- | --- |
| `outputs/rule_extraction_r1_all_categories/surrey_rules_deduped.csv` | Final deduped rule table for quick review or downstream import |
| `outputs/rule_extraction_r1_all_categories/surrey_rules_deduped.xlsx` | Excel version of the final rule table |
| `outputs/rule_extraction_r1_all_categories/surrey_rules_by_block_raw.json` | Raw parsed rules by block, including source block information |
| `outputs/rule_extraction_r1_all_categories/surrey_block_extraction_log_full.xlsx` | LLM call log, raw model output, context text, and parsing status |
| `outputs/rule_extraction_r1_all_categories/surrey_block_extraction_summary.txt` | Core run summary |
| `outputs/rule_extraction_r1_all_categories/surrey_block_validation_report.xlsx` | Validation report |
| `outputs/rule_extraction_r1_all_categories/surrey_exception_extraction_warnings.xlsx` | Exception extraction warning review file |
| `outputs/rule_extraction_r1_all_categories/surrey_ungrounded_condition_warnings.xlsx` | Condition grounding warning review file |

Document map / block input files:

| File | Purpose |
| --- | --- |
| `outputs/document_map/document_map_report.md` | Parser choice, zone block summary, and R1 block summary |
| `outputs/document_map/surrey_recommended_extraction_blocks.json` | Recommended extraction blocks |
| `outputs/document_map/block_texts/*.md` | Block-level context text used by LLM extraction |
| `outputs/document_map/surrey_page_map.xlsx` | Page-level parser/source map |

## Main Extracted Rules

The latest R1 Coach House / Garden Suite extraction found these main rules:

- Coach House is a permitted accessory use in R1, subject to the maximum dwelling unit limit.
- Coach House floor area:
  - minimum `35 sq. m`
  - maximum `75 sq. m`, excluding garage/carport
  - conditional maximum `120 sq. m` if the single family dwelling or duplex has not used the maximum available floor area on the lot
- Lot coverage:
  - lot area `<= 560 sq. m`: `45%`
  - lot area `> 560 sq. m` and `<= 1,262 sq. m`: starts at `45%` and is reduced by `2%` for each additional `93 sq. m` of lot area until `30%`
  - lot area `> 1,262 sq. m`: `30%`
- Setbacks and separation:
  - front yard: not permitted
  - rear yard: `1.8 m`
  - side yard: `1.8 m`
  - street side yard: `2.4 m`
  - separation: `5.0 m`
  - rear yard setback may be reduced to `1.0 m` if the coach house is constructed above a garage or carport with rear lane access, for lot area `<= 1,500 sq. m`
- Height:
  - normal maximum height `7.0 m`
  - maximum `2 storeys`
  - normal maximum roof peak height `8.3 m`
  - floodplain-related height / roof peak height variation up to `8.5 m`

## Known Review Items

The latest validation did not find blocked keys, outside allowed keys, condition leakage, ungrounded values, or target scope warnings.

The following warnings still need manual review:

- `exception_extraction_warnings: 2`
- `ungrounded_condition_warnings: 4`

These warnings do not necessarily mean the extracted rules are wrong. They mark places where condition/exception text should be checked against the source text, especially for floor area rules, the lot coverage formula, and floodplain height variations.

## Reproduction Notes

To reproduce the latest experiment:

1. Open `code/rule_extraction_test/`.
2. Confirm `BYL_Zoning_12000.pdf` exists in this folder.
3. Run `03_build_surrey_document_map_and_blocks.ipynb` to generate or update the document map and block text files.
4. Make sure Ollama is installed and running locally.
5. Make sure a local Qwen 3.5 9B model is available in Ollama.
6. The notebook currently calls the model alias `qwen35-rules`. If your local Ollama model is named differently, either create a matching alias or update `MODEL_NAME` in `05_extract_surrey_r1_rules_all_categories.ipynb`.
7. Run `05_extract_surrey_r1_rules_all_categories.ipynb`.
8. Review `outputs/rule_extraction_r1_all_categories/surrey_block_extraction_summary.txt` and `outputs/rule_extraction_r1_all_categories/surrey_rules_deduped.csv`.

Common Python dependencies:

```text
pandas
openpyxl
requests
tqdm
pymupdf
pymupdf4llm
docling optional
```

## Suggested Next Steps

- Manually review the exception and ungrounded-condition warning files.
- Extend the same block-based pipeline from R1 to R2, R2-O, R3, R4, R5, R5-S, and R6.
- Build a small gold set for the deduped rules so future prompt/schema changes can be evaluated with precision and recall.
