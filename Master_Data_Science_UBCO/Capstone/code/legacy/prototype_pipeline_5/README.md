# Prototype Pipeline 5

Integrated zoning-bylaw rule extraction pipeline with visual document routing and
traceable rule review. Pipeline 5 reads an official PDF, separates hierarchical legal
text from title-inclusive regulatory-table images, extracts both streams with Gemini
3.1 Pro, and produces a single consolidated rule registry.

Pipeline 5 is an experimental successor to [Pipeline 4](../prototype_pipeline_4/).
Pipeline 4 uses PyMuPDF table-grid recovery plus Burnaby-specific repair heuristics.
Pipeline 5 replaces that fragile table boundary with a municipality-agnostic visual
workflow while keeping every rule tied to visible source evidence.

## Design Philosophy

The pipeline separates visual recovery, rule extraction, review, and deterministic
consolidation into explicit stages:

- **Visual document routing** - Gemini 3.1 Pro reads rendered PDF pages and emits
  hierarchical text blocks plus cropped table images. Each table crop includes its
  visible section heading or nearest title.
- **Text-rule track** - hierarchical legal-text blocks are grouped by page and sent to
  Gemini with their `section_path`, `parent_context`, and source IDs.
- **Table-rule track** - regulatory-table crops are sent to Gemini as images. The model
  extracts atomic value-bearing constraints while preserving row, column, condition,
  exception, and evidence context.
- **Deterministic merge audit** - local code normalizes units and safely folds rules
  that have identical constraints and table evidence but were expanded across visual
  column scopes. Multi-column rules use `scope_mode = multiple_explicit_scopes` and
  list their full `applies_to_objects` instead of inheriting the first visible column
  label. Truly single-column rules retain their original scope.
- **API merge review** - only ambiguous candidates are sent back to Gemini. The reviewer
  resolves each candidate as `KEEP`, `REPLACE`, or `DROP` using same-page text blocks
  and sibling rules.
- **Post-review consolidation** - local code removes reviewer-generated sibling
  duplicates and clears redundant qualifiers already represented by alternate rules.

The final artifact is `final_rule_registry.json`, which contains metadata and the
complete reviewed `rules` array.

Open the latest validated Burnaby R1 deliverable:
[final_rule_registry.json](outputs/burnaby/rule_extraction/final_rule_registry.json).

## What Changed From Pipeline 4

Pipeline 4 successfully recovered Burnaby R1 rules, but its deterministic table parser
needed layout-specific repairs for merged cells, repeated values, multi-condition cells,
and sticky row labels. Those fixes are accurate for Burnaby but difficult to generalize
across municipalities.

Pipeline 5 changes the extraction boundary:

| Concern | Pipeline 4 | Pipeline 5 |
|---------|------------|------------|
| Document block extraction | Page-level markdown | Visual hierarchical text blocks |
| Table detection | PyMuPDF native table grid | Gemini visual region detection |
| Table representation | Reconstructed cell dataframe | Title-inclusive image crop |
| Complex layouts | Local repair heuristics | VLM reads visible layout directly |
| Duplicate handling | Table-parser-specific fixes | Evidence-based merge audit |
| Ambiguous rules | Human review queue | Gemini API review plus local consolidation |
| Final handoff | Multiple CSV and JSON files | Single `final_rule_registry.json` |

The validated experiment intentionally ignores diagrams and illustration-based rules.
Diagram crops remain available for audit but are not sent into rule extraction.

## How To Run

1. Install requirements from `code/prototype_pipeline/requirements.txt`.
2. Set `GEMINI_API_KEY` in your environment.
3. Open `pipeline5_rule_extraction.ipynb`.
4. Run all cells to generate visual blocks, extract both rule streams, run API review,
   consolidate the registry, and save the final single-file deliverable.

All visual and API-review stages use:

```text
gemini-3.1-pro-preview
```

The public notebook is generated from
`gen_pipeline5_rule_extraction_notebook.py`. After changing the generator, run:

```powershell
python code/prototype_pipeline_5/gen_pipeline5_rule_extraction_notebook.py
```

## Pipeline Stages

```text
Official zoning PDF
 |
 v
01  Render selected PDF pages
     -> page_images/page_*.png
 |
 v
02  Gemini 3.1 Pro visual block extraction
     preserve reading order and hierarchical section paths
     |
     +------------------------------------------------------+
     |                                                      |
     v hierarchical legal text                              v title-inclusive visual regions
03a  text_blocks.jsonl                                03b  table_regions.jsonl
     section_path + parent_context                          crop table regions to PNG
     amendment notes retained for audit                     diagram regions retained for audit
     |                                                      |
     v                                                      v
04a  Gemini text-rule extraction                       04b  Gemini table-image rule extraction
     page-grouped API batches                               regulatory tables only
     -> text_rules_raw.*                                    -> table_rules_raw.*
     |                                                      |
     +---------------------------+--------------------------+
                                 |
                                 v
05  Merge raw rules
    -> combined_rules_raw.*
 |
 v
06  Deterministic merge audit
    normalize units
    fold identical same-evidence table expansions
    preserve original scopes in applies_to
    -> merged_rules_deduplicated.*
    -> merge_audit.*
 |
 v
07  Gemini API merge review
    review only flagged ranges, exceptions, and incomplete source blocks
    KEEP / REPLACE / DROP decisions with sibling-rule context
    -> final_rules_api_reviewed.*
 |
 v
08  Deterministic post-review consolidation
    remove semantic sibling duplicates
    clear qualifiers already represented by alternate rules
    -> post_review_consolidation_audit.*
 |
 v
09  Single-file final registry
    -> final_rule_registry.json
```

## Outputs

The validated Burnaby experiment writes visual routing artifacts under:

```text
code/prototype_pipeline_5/outputs/burnaby/visual_blocks/
```

The current saved run covers PDF pages 1 through 7.

| File or folder | Contents |
|----------------|----------|
| `page_images/` | Rendered PDF pages sent to Gemini |
| `table_images/` | Cropped visual regions with section titles |
| `text_blocks.jsonl` | Hierarchical non-table text blocks |
| `table_regions.jsonl` | Table and diagram region metadata |
| `document_order.jsonl` | Combined reading order across both streams |
| `summary.json` | Visual-routing counts and page-level diagnostics |

Rule-extraction and review artifacts are written under:

```text
code/prototype_pipeline_5/outputs/burnaby/rule_extraction/
```

| File | Contents |
|------|----------|
| `text_rules_raw.*` | Raw Gemini rules from hierarchical text blocks |
| `table_rules_raw.*` | Raw Gemini rules from regulatory-table images |
| `combined_rules_raw.*` | Both extraction streams before merge review |
| `merged_rules_deduplicated.*` | Rules after unit normalization and safe duplicate folding |
| `merge_audit.*` | Automatically folded groups with original IDs and scopes |
| `merge_review_queue.*` | Candidates requiring API review |
| `merge_review_api_response.json` | Auditable Gemini `KEEP / REPLACE / DROP` decisions |
| `final_rules_api_reviewed.*` | Intermediate registry immediately after API review |
| `post_review_consolidation_audit.*` | Final deterministic cleanup log |
| `final_rule_registry.json` | Single-file final deliverable |

## Burnaby R1 Sample Results

The latest validated Burnaby R1 run processed all seven source pages. The visual router
separated clause-style text from visual regions before extraction:

| Visual-routing metric | Count |
|-----------------------|------:|
| PDF pages processed | 7 |
| Hierarchical text blocks | 97 |
| Visual regions detected | 8 |
| Regulatory tables extracted | 4 |
| Diagram regions retained but ignored | 4 |

The four regulatory tables are:

| Page | Section | Raw table rules |
|-----:|---------|----------------:|
| 1 | `101.2 Permitted Uses` | 10 |
| 1 | `101.3 Subdivision Regulations` | 9 |
| 2 | `101.4 Development Regulations` | 81 |
| 4 | `101.5.1 All Dwelling Units` | 2 |

Both extraction tracks completed successfully:

| Rule-extraction metric | Count |
|------------------------|------:|
| Successful text API batches | 7 / 7 |
| Successful table-image API batches | 4 / 4 |
| Raw text rules | 81 |
| Raw table rules | 102 |
| Combined raw rules | 183 |

The merge and review stages reduced table-scope expansion while preserving traceability:

| Merge and review metric | Count |
|-------------------------|------:|
| Initial deterministic merge groups folded | 19 |
| Duplicate table expansions removed | 47 |
| Rules after initial merge audit | 136 |
| Candidates sent to API merge review | 17 |
| API decisions returned | 17 / 17 |
| API-reviewed intermediate rules | 144 |
| Post-review consolidation actions | 3 |
| Final consolidated rules | 142 |
| Unresolved rules | 0 |
| Remaining semantic duplicate groups | 0 |
| Remaining rules requiring review | 0 |

The final registry contains `81` rules sourced from hierarchical legal text and `61`
rules sourced from table images.

## Extraction Quality

The complex `101.4 Development Regulations` table is the primary stress test. Pipeline 5
recovered values that are easy to lose in text-first parsing, including:

- `Lots <= 567 m2: 40%` and `Lots > 567 m2: 30%`;
- `281 m2` minimum lot area and `280 m2` maximum Rowhouse lot area;
- `7.5 m / 7.0 m` rear-principal sloping-roof and flat-roof heights;
- `3.0 m, except 1.5 m for accessory buildings`;
- `0 m, except 1.2 m for end unit lots`;
- `2.4 m / 6.0 m` building-separation values;
- the `1` and `2` unit minimum 3+ bedroom requirements.

The API reviewer is evaluated against
`benchmarks/burnaby_merge_review_gold.json`. The fixture is used only after inference
and is never included in the API prompt:

| API-review benchmark metric | Result |
|-----------------------------|-------:|
| Review candidates evaluated | 17 |
| Numeric endpoint accuracy | 100.0% |
| Action accuracy | 88.2% |
| Strict action + replacement-count accuracy | 82.4% |
| Unresolved API decisions | 0 |

The strict benchmark records the raw API-review quality. The deterministic
post-review consolidation then removes stable, machine-detectable sibling duplicates
and redundant qualifiers, yielding the final `142`-rule registry.

## Current Scope

The latest checked result validates the end-to-end visual-block workflow on **Burnaby
R1**. Pipeline 4 configuration targets for Vancouver RS and Surrey R1 remain useful
future test cases, but they have not yet been validated with this Pipeline 5 workflow.

Historical notebooks and generators are retained under `archive/legacy_notebooks/`.
They are useful for audit and comparison but are not public entry points. The validated
workflow documented above is exposed through the single
`pipeline5_rule_extraction.ipynb` notebook.
