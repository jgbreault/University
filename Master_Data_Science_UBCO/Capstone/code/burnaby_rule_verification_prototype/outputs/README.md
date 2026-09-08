# Outputs Folder Map

`outputs/` stores reproducible verifier runs, model bakeoffs, and dashboard
artifacts. Treat these as generated artifacts, not source code.

The current product generation is **M7**: the consolidated matrix-aware pipeline
on `google/gemini-3.1-flash-lite`. The deleted legacy lanes
(`v2_runs/`, `v3_runs/`, `*_p9/`, `*_p9_v21/`, `_baseline_prematrix/`,
`v2_runs_full_discovery/`, `*_pre_v21_backup/`, `*_native_v1_smoke_*`) are no
longer carried in the tree.

## Current High-Signal Outputs

| Path | Purpose |
|---|---|
| `mvp_verification/` | Current cross-city status report. Start with `mvp_report.md`. |
| `m7_runs/<city>/google_gemini_3_1_flash_lite/` | Current product M7 verifier output for each city (gemini-3.1-flash-lite). |
| `m7_runs/<city>/google_gemini_2_5_flash_lite/` | Pre-M7 (gemini-2.5-flash-lite) run, retained for the before/after comparison. |
| `m7_runs/<city>/` | M7 discovery summaries and evidence packs for each city. |
| `m7_measure/m7_gemini31_20260616/<city>/` | M7 scored-coverage measurement run (honest scored legal-slot denominator). |
| `m7_cache/` | Cached extraction/discovery artifacts that let measurement reruns skip new LLM calls. |
| `benchmark/source_corpus/<city>/rag_index.json` | Compact RAG index used by the dashboard's Ask the Bylaw panel. |
| `topdown_validation/m4_source_pdf_audit.json` | Source-PDF audit proving verified values/units against the actual local PDFs. |

Use these first when presenting the project:

```text
outputs/mvp_verification/mvp_report.md
outputs/m7_runs/<city>/google_gemini_3_1_flash_lite/
outputs/m7_measure/m7_gemini31_20260616/<city>/
outputs/topdown_validation/m4_source_pdf_audit.json
```

## Legacy / Reference Outputs (still on disk)

| Path | Meaning |
|---|---|
| `*_slim_pipeline5_registry/` | Legacy/reference verifier output from the Pipeline 5 registry path (one per city). Not the product path. |
| `*_slim_pipeline5_registry_v21/` | V2.1 comparison snapshots for the Pipeline 5 registry lanes. |
| `adversarial_report.json` | Latest adversarial-suite result snapshot. |
| `review_ranker_model.json` | Learned review-queue ordering model (advisory only; not a verifier gate). |
| `strictness_audit.md` | Verifier strictness/gap audit notes. |

These are kept for comparison and reproducibility, not as the first folders to
read.

## Important Files Inside A Run

| File | Meaning |
|---|---|
| `verified_rules.json` | Rules proven by deterministic verification (raw audit trail). |
| `review_needed.json` | Plausible rules with missing/ambiguous evidence. |
| `rejected_rules.json` | Unsafe, contradicted, or malformed candidates. |
| `not_used.json` | Traceability/out-of-scope artifacts. |
| `gis_rule_contract.json` | Verified-only, deduplicated GIS input. |
| `gis_felt_export.json` | Richer deduplicated map/dashboard projection from verified rules. |
| `benchmark_report.json` / `.md` | Precision, false-verified, recall, proposal metrics, and gate status. |
| `slim_summary.json` | Compact run counts for dashboard/reporting. |
| `source_repair_report.json` | Evidence repair/re-anchoring diagnostics. |
| `review_assistant_packets.json` | Deterministic review packets for dashboard/human review. |
| `model_cost_report.json` | Model cost/latency summary where applicable. |

`gis_rule_contract.json` and `gis_felt_export.json` are a pure deterministic
projection of `verified_rules.json`; `tests/test_m7_safety_gates.py` fails CI if
either committed export drifts from a fresh regen.

## Cleanup Rule

`.gitignore` keeps only curated M7/MVP/audit outputs visible for release
commits. Do not use `git add -A`; stage source, docs, tests, configs, and the
curated output paths explicitly.

Do not delete output folders just because they look old. First decide whether
they are:

1. current reporting artifacts,
2. comparison baselines,
3. reproducibility evidence,
4. dashboard inputs, or
5. disposable local experiments.

Only category 5 should be removed, and only after checking `git status` and the
dashboard/tests.
