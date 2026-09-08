# Official Rule Extraction Pipeline

`code/official_rule_extraction_pipeline` is the official pipeline for zoning rule
extraction in this branch. Use this folder for reproducible extraction runs,
quality checks, cached HQ outputs, and downstream GIS-rule handoff.

Pipeline 10 is the current generalized graph/RAG rule-extraction pipeline. It
migrates the Pipeline 9 city-neutral selection path, then adds a lower-cost and
higher-quality extraction layer:

1. lexical or local-embedding semantic compression before extraction;
2. graph/RAG evidence packs grouped by rule role;
3. target-scoped adapter with continuation-aware trimming;
4. inherited table crops from bundled visual-block resources;
5. batched LLM extraction with cache, retry, and partial rerun support;
6. postprocess filters that separate clean GIS-ready rules from review items.

The default run is offline and stops before API extraction.

Pipeline 11 is intentionally kept as an additional embedding experiment. It is
not the default extraction pipeline unless explicitly requested.

## Self-Contained Layout

Pipeline 10 is intended to run without importing code from older prototype
folders. The required runtime pieces now live under this directory:

```text
local_candidate_block_selector.py      # local PDF block recall
visual_blocks_rule_extractor.py        # Gemini calls, prompts, merge helpers
pdfs/<city>/                           # default source PDFs by city
resources/visual_blocks/<city>/        # bundled table_regions/table_images
outputs/<city>/...                     # generated pipeline outputs
```

`resources/visual_blocks/<city>/` is used only to inherit table crops into the
RAG visual-block adapter. A caller can still override it with
`--source-visual-blocks-dir`.

## Flow

```mermaid
flowchart TD
    A[Full bylaw PDF] --> B[01 Local candidate selection]
    B --> C[02 Auto discovery]
    C --> D[03 Semantic compression]
    D --> E[04 Graph/RAG pack builder]

    E --> E1[Core rules]
    E --> E2[Use permissions]
    E --> E3[District dimensional overrides]
    E --> E4[Universal applicable rules]
    E1 --> F[05 Target-scoped RAG visual blocks]
    E2 --> F
    E3 --> F
    E4 --> F

    T[Bundled table regions and crops] --> F
    F --> G[Preflight filters]
    G --> G1[Skip headings, deleted text, no-op blocks]
    G --> G2[Hold table-like OCR text]
    G --> H[Pack-adaptive text batches]
    F --> I[Regulatory table image batches]

    H --> J[LLM text rule extraction]
    I --> K[LLM table image extraction]
    J --> L[Raw extracted rules]
    K --> L

    L --> M[Merge and deduplicate]
    M --> N[Canonicalize units, objects, approval type]
    N --> O[Postprocess filters]
    O --> O1[Filter non-target and broad rules]
    O --> O2[Prefer table image over same-page OCR text]
    O --> P[Final outputs]
    P --> Q[merged_rules_deduplicated]
    P --> R[merged_rules_clean]
    P --> S[merge_review_queue]
```

## What Changed From Pipeline 9

Pipeline 9 used the generalized graph/RAG selection path, then adapted each pack
into pseudo-pages for extraction. Pipeline 10 keeps the generalized upstream
logic but changes the extraction transport and cleanup stages:

```text
Pipeline 9:
RAG packs -> target-strict pseudo-pages -> extraction -> merge

Pipeline 10:
RAG packs -> continuation-aware target adapter
          -> inherited table crops
          -> local preflight filters
          -> batched text extraction + table-image extraction
          -> merge/dedup/canonicalize/postprocess
          -> clean final + review queue
```

Important current behaviors:

- `pack_adaptive` batching keeps dense packs isolated and groups smaller
  low-risk packs.
- Cached `api_raw/*_parsed.json` files are reused unless `--overwrite` is
  passed.
- `--only-batches` can rerun selected text batches while preserving previously
  cached text/table rules.
- Target trimming keeps governing clauses before target list items and keeps
  child list items after `that:` or `where:` clauses.
- When Burnaby table-image extraction succeeds, same-page OCR table text is
  filtered out of final results to avoid duplicate and weaker table rules.
- Rules with incomplete evidence, source warnings, or unit/object conflicts stay
  in `merge_review_queue.*`; complete rules with exceptions can still enter the
  clean output.

## Run Offline

From the repo root:

```powershell
python code\official_rule_extraction_pipeline\pipeline10_runner.py vancouver
python code\official_rule_extraction_pipeline\pipeline10_runner.py burnaby
python code\official_rule_extraction_pipeline\pipeline10_runner.py calgary
```

Build extraction batches without calling the API:

```powershell
python code\official_rule_extraction_pipeline\pipeline10_runner.py vancouver --dry-run-extraction
python code\official_rule_extraction_pipeline\pipeline10_runner.py burnaby --dry-run-extraction
python code\official_rule_extraction_pipeline\pipeline10_runner.py calgary --dry-run-extraction
```

Useful offline controls:

```powershell
--compression-provider lexical
--compression-provider ollama --ollama-model nomic-embed-text
--compression-threshold 0.32
--pack-threshold 0.28
--max-windows 100
```

## Run Extraction

Set `GEMINI_API_KEY`, then run a full extraction:

```powershell
python code\official_rule_extraction_pipeline\pipeline10_runner.py burnaby --run-extraction --model gemini-2.5-flash --text-model gemini-2.5-flash --table-model gemini-3.1-pro-preview --max-workers 1
python code\official_rule_extraction_pipeline\pipeline10_runner.py calgary --run-extraction --model gemini-2.5-flash --text-model gemini-2.5-flash --table-model gemini-3.1-pro-preview --max-workers 1
```

Useful extraction controls:

```powershell
--max-blocks-per-batch 8
--max-chars-per-batch 12000
--call-delay-seconds 1
--max-retries 3
--retry-base-seconds 20
```

Rerun only selected text batches after adapter or prompt changes:

```powershell
python code\official_rule_extraction_pipeline\batched_rag_rule_extractor.py --visual-blocks-dir code\official_rule_extraction_pipeline\outputs\calgary\05_rag_visual_blocks --output-dir code\official_rule_extraction_pipeline\outputs\calgary\06_rule_extraction_hq --model gemini-2.5-flash --text-model gemini-2.5-flash --table-model gemini-3.1-pro-preview --only-batches text_batch_0006 text_batch_0025 --overwrite --target-terms "backyard suite" "backyard suites" "secondary suite" "secondary suites"
```

Rebuild final outputs from cached raw rules without API calls:

```powershell
python code\official_rule_extraction_pipeline\rebuild_outputs_local_dedup.py code\official_rule_extraction_pipeline\outputs\burnaby\06_rule_extraction_hq --target-terms "small-scale multi-unit housing" "small scale multi unit housing" "rowhouse dwellings" "rowhouse dwelling" "rowhouse"
python code\official_rule_extraction_pipeline\rebuild_outputs_local_dedup.py code\official_rule_extraction_pipeline\outputs\calgary\06_rule_extraction_hq --target-terms "backyard suite" "backyard suites" "secondary suite" "secondary suites"
```

## Outputs

High-quality extraction outputs live under:

```text
outputs/<city>/06_rule_extraction_hq/
```

Use these files by default:

```text
merged_rules_clean.json
merged_rules_clean.csv
```

These contain the clean, postprocessed rule set intended for downstream GIS
classification and rule modeling.

Supporting outputs:

```text
merged_rules_deduplicated.json/csv  # full deduplicated set after filters
merge_review_queue.json/csv         # incomplete/conflicted rules for review
postprocess_filter_audit.json/csv   # rules filtered out and why
combined_rules_raw.json/csv         # raw text + table rules before merge
text_rules_raw.json/csv             # raw text-batch rules
table_rules_raw.json/csv            # raw table-image rules
api_raw/                            # cached prompts, parsed JSON, API responses
```

Current checked HQ summaries after the latest cleanup:

```text
Burnaby: dedup=60, clean=60, review=0
Calgary: dedup=145, clean=137, review=8
Vancouver: dedup=47, clean=39, review=8
```

## Quality Checks

Compare Pipeline 10 against a baseline:

```powershell
python code\official_rule_extraction_pipeline\compare_batched_quality.py
```

Manual quality checks should focus on:

- source coverage against PDF pages;
- table-image rules versus table OCR duplicates;
- target relevance for the requested building/use type;
- review queue reasons, especially incomplete `where:` / `that:` evidence;
- canonical `rule_object`, `operator`, `value`, and `unit` fields.

The clean output is not a legal interpretation. It is a structured extraction
artifact for downstream GIS and rule-classification work.
