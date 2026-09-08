# Native Extraction V1

Native extraction is a candidate generator for the verification layer. It uses
retrieval to find source-backed bylaw text, asks an OpenRouter model to extract
numeric zoning rule candidates, and writes the same verifier contract used by
other upstream extractors.

It does not verify rules. The authority remains:

```text
PDF source -> native retrieval/extraction -> source repair -> deterministic verifier
```

## Secret Handling

Do not put API keys in Python code or committed JSON. Use one of:

```bash
export OPENROUTER_API_KEY=...
```

or create a local git-ignored `.env` file:

```text
OPENROUTER_API_KEY=...
```

The repository `.gitignore` already excludes `.env`.

## Run Extraction

Dry-run retrieval only:

```bash
.venv/bin/python scripts/run_native_extraction.py --city calgary_rcg --dry-run
```

Full extraction:

```bash
.venv/bin/python scripts/run_native_extraction.py --city calgary_rcg
```

Default models:

```text
chat:      openai/gpt-oss-120b
embedding: baai/bge-m3
rerank:    cohere/rerank-4-fast
```

Outputs are written to:

```text
outputs/<city>_native_extraction/
  retrieval_packs.json
  raw_model_outputs.json
  evidence_units.json
  rule_candidates.json
  extraction_summary.json
```

## Verify Native Output

```bash
.venv/bin/python scripts/run_slim_verifier.py \
  --city calgary_rcg \
  --native-extraction outputs/calgary_rcg_native_extraction \
  --output-dir outputs/calgary_rcg_native_verified \
  --no-cache
```

GIS and proposal decisions must still consume only verifier outputs:

```text
verified_rules.json
gis_rule_contract.json
```
