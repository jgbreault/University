# Municipal Zoning Rule Verification Prototype

This project verifies zoning rules extracted from municipal bylaws before they
can be used downstream by GIS or map dashboards.

The core boundary is unchanged:

```text
Extraction proposes.
RAG/discovery finds source context.
Source repair restores evidence context.
Deterministic verification decides.
GIS consumes only verified rules.
```

The final release phase is **M7**. M7 packages the consolidated matrix-aware
extraction pipeline (on `google/gemini-3.1-flash-lite`), the M5.6 scored
measurement layer, and the 4-tab Civic Console dashboard into one reproducible
handoff. The product verification path is full-bylaw source discovery plus
RAG/evidence packs, matrix-aware native extraction, source repair, and
deterministic verification. Pipeline 5 and Pipeline 9 are historical names for
shared upstream code, not separate product lanes. Every extraction path feeds
the same verifier contract: `rule_candidates` plus `evidence_units`.
Re-anchoring, RAG, SQLite, and LLM/examiner tools are support layers only; none
of them can promote a rule.

## Safety Contract

The core rule is simple:

```text
Extraction proposes.
Verification proves.
GIS consumes only verified rules.
```

No upstream confidence score, `review_required=false` flag, or extraction
label ever promotes a candidate.

The verifier checks each candidate field against cited evidence:

```text
rule_object, value, unit, operator, scope, applies_to, condition, exception
```

If evidence is incomplete, ambiguous, contradicted, or outside the current
verification contract, the rule is not promoted to `verified_rules.json`.

## Current Results

M7 release status, the per-city before/after story, scored coverage, and the C5
verifier-recall finding are documented in:

```text
docs/M7_FINAL_RELEASE.md
```

The current release gate uses `extraction_coverage_recall` /
`release_candidate_recall`, not raw candidate artifact recall. Raw candidate
artifact recall remains diagnostic because rules can move directly into
verified, review, rejected, or not-used output buckets after extraction.

The current product run (M7, `google/gemini-3.1-flash-lite`) is evaluated by:

```bash
.venv/bin/python benchmark/evaluate_benchmark.py --city burnaby_r1 --output-dir outputs/m7_runs/burnaby_r1/google_gemini_3_1_flash_lite
```

M7 per-city benchmark status (from
`outputs/m7_runs/<city>/google_gemini_3_1_flash_lite/benchmark_report.json`):

| City | Verified | Review | Coverage recall | Verified precision | False verified | Source-support failures | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Burnaby R1 | 87 | 57 | 0.975 | 1.000 | 0 | 0 | pass |
| Calgary RCG | 30 | 41 | 1.000 | 1.000 | 0 | 0 | pass |
| Vancouver RS | 10 | 31 | 1.000 | 1.000 | 0 | 0 | pass |

The Burnaby proposal benchmark holds `proposal_decision_accuracy = 1.0` and
`false_approval_count = 0`.

This is a safety-ready verification story, not a claim that every possible
municipal rule has been extracted. The verifier is fail-closed with zero false
verified rules in all benchmarked cities. Remaining work is recall and review
efficiency, not loosening the verifier.

## Quick Start

From this folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
```

Check the current consolidated status:

```bash
.venv/bin/python scripts/run_consolidated_prototype.py status
```

Refresh the full MVP report:

```bash
.venv/bin/python scripts/run_consolidated_prototype.py mvp
```

Run the current extraction/discovery path without an LLM call:

```bash
.venv/bin/python scripts/run_m4_bakeoff.py --city calgary_rcg --models google/gemini-3.1-flash-lite --dry-run
```

Run extraction with full-bylaw discovery and verification:

```bash
.venv/bin/python scripts/run_m4_bakeoff.py --city burnaby_r1 --models google/gemini-3.1-flash-lite
```

Run the main verifier directly:

```bash
.venv/bin/python scripts/run_slim_verifier.py --city burnaby_r1
.venv/bin/python benchmark/evaluate_benchmark.py --city burnaby_r1
```

Run the M7 measurement layer (scored legal-slot coverage):

```bash
.venv/bin/python scripts/run_m7_measure.py --run-id m7_gemini31_20260616 --changed-component m7_matrix_pipeline_gemini_3_1 --model google/gemini-3.1-flash-lite --overwrite
```

A refresh variant reuses existing extraction artifacts and refreshes only the
deterministic verifier (`--refresh-verifier`), so it improves proof traces
without a new LLM call. GIS-facing exports deduplicate exact source-aware
duplicate verified rows; the raw audit trail remains `verified_rules.json`.

"Pipeline 5" and "Pipeline 9" are historical names for shared upstream code,
not separate product paths.

Run the test suite:

```bash
.venv/bin/python -m pytest -q
```

Run the local dashboard:

```bash
.venv/bin/python -m streamlit run dashboard/streamlit_app.py --server.port 8620
```

## Main Outputs

Current M7 product outputs are written to:

```text
outputs/m7_runs/<city>/google_gemini_3_1_flash_lite/
```

The most important files are:

```text
verified_rules.json          source-supported rules only
review_needed.json           plausible but incomplete or ambiguous rules
rejected_rules.json          contradicted or unsafe malformed candidates
not_used.json                traceability-only or out-of-contract candidates
gis_rule_contract.json       slim verified-only, deduplicated GIS contract
gis_felt_export.json         richer deduplicated map/dashboard export from verified rules
benchmark_report.md          readable benchmark result
validation_report.json       compact dashboard-ready run summary
```

Downstream GIS should consume only:

```text
gis_rule_contract.json
```

`gis_felt_export.json` is a convenience projection for map dashboards. It is
derived only from verified rules.

## Decision Buckets

```text
verified
```

All required claims are supported by cited evidence.

```text
review_needed
```

The candidate may be correct, but scope, condition, exception, operator, or
evidence context is incomplete.

```text
rejected
```

The candidate has a hard contradiction or unsafe malformed field, such as a
wrong value, incompatible unit, missing evidence ID, or refuted operator.

```text
not_used
```

The candidate is useful for traceability but outside the active verification or
GIS contract, such as a cross-reference or administrative/process rule.

## Project Layout

```text
benchmark/      gold rules, proposal cases, evaluators, adversarial tests
configs/        city/zone config; vocabulary only, not answer keys
dashboard/      Streamlit review and export dashboard
docs/           concise architecture and output documentation
outputs/        reproducible demo outputs
schemas/        JSON schemas for verified exports
scripts/        CLI entrypoints and post-processing tools
src/            adapter, verifier, proof, triage, and export code
tests/          unit tests for verifier, adapters, exports, and safety gates
```

For the consolidated handoff map, see:

```text
docs/CONSOLIDATED_PROTOTYPE.md
docs/PROJECT_STRUCTURE.md
```

For folder-level navigation, see:

```text
docs/README.md
scripts/README.md
src/burnaby_prototype/README.md
outputs/README.md
```

## What Is Advisory Only

These modules help a human reviewer but never promote rules:

```text
review_router
evidence_repair
evidence_rerun
safe_tuning
llm_review_assistant
v2_examiner          (private development examiner)
bylaw_rag            (Ask-the-bylaw retrieval)
review_ranker        (learned queue ordering, JSON model)
nli_semantics        (entailment second opinion)
native_extraction    (our proposer-tier extraction path)
```

Only deterministic verification can write `verified_rules.json`.

## Generalization Guardrails

The verifier must not use:

```text
gold-rule answers
known final thresholds
page-specific expected values
city-specific hardcoded legal outcomes
```

The verifier may use:

```text
candidate fields
cited evidence
local source context
generic zoning vocabulary
city terminology and aliases
unit aliases
operator cues
```

Gold rules are benchmark-only.
