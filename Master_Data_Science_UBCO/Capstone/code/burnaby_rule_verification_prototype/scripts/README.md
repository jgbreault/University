# Scripts

All commands run from the repo root with `.venv/bin/python` unless noted.
Start with `run_consolidated_prototype.py`; most other scripts are specialist
tools or legacy/audit helpers.

Current generation is **M7**: the consolidated matrix-aware pipeline on
`google/gemini-3.1-flash-lite`, writing to
`outputs/m7_runs/<city>/google_gemini_3_1_flash_lite/`. Measurement runs land
under `outputs/m7_measure/<run_id>/` (`run_m7_measure.py`). The verifier itself
is model-agnostic and deterministic; the model only proposes candidates.

Naming note: the two "holdout" scripts answer different questions —
`run_holdout_eval.py` is the **within-city** Burnaby tuning ablation, while
`run_vancouver_holdout.py` is the **cross-city** transfer test. Neither is a
rename candidate; their docstrings carry the same clarification.

## Primary Commands

| Script | Purpose |
|---|---|
| `run_consolidated_prototype.py` | One handoff entrypoint for current status, MVP report refresh, and native extraction/discovery runs. |
| `run_mvp_verification.py` | Builds the honest cross-city MVP report from native M4 current outputs at `outputs/mvp_verification/mvp_report.md`; V2/V3/P5/P9 are reference rows only. |
| `run_m4_bakeoff.py` | Current native M4 entrypoint: exhaustive full-bylaw discovery, native extraction, deterministic verification, and reports. |
| `run_slim_verifier.py` | Main deterministic verifier entrypoint. M4 calls it after candidate extraction. |

## Engine Internals

These scripts still exist because the current M4 command uses shared code that
was created during V2/V3. Do not present them as separate product paths.

| Script | Purpose |
|---|---|
| `run_v3_bakeoff.py` | Shared V3/M4 engine. M4 uses it through `run_m4_bakeoff.py` with `--discovery-mode m4`. |
| `run_v2_bakeoff.py` | Older native V2 bakeoff reference for regression analysis. Not a final-demo command. |

## Extraction / Source Helpers

| Script | Purpose |
|---|---|
| `fetch_bylaw.py` | Fetch/cache a source PDF with sha256 provenance. |
| `build_m4_source_corpus.py` | Writes full-bylaw M4 source-corpus snapshots and coverage audits without reading gold. |
| `run_extraction.py` | Legacy PDF-to-Pipeline-5-registry helper. Keep for audit/backward compatibility only. |
| `run_pipeline5_extraction.py` | Legacy preflight/refresh of upstream Pipeline 5 extraction notebook. Not the product path. |
| `run_native_extraction.py` | Smaller native extraction wrapper; prefer `run_consolidated_prototype.py native` for handoff. |
| `build_rag_index.py` | Build bylaw RAG index for dashboard/source search. |

## Reports / Exports

| Script | Purpose |
|---|---|
| `build_proof_graph.py` | Render the proof graph HTML sidecar. |
| `build_buildable_envelope.py` | Build simplified verified-only buildable-envelope JSON. |
| `build_envelope_3d.py` | Build optional 3D envelope visualization. |
| `run_m7_measure.py` | Create fresh `outputs/m7_measure/<run_id>/` benchmark snapshots, scoreboard rows, source registry, RAG retrieval report, and bottleneck diagnosis; use `--refresh-verifier` after verifier/proof changes. |
| `audit_bylaw_coverage.py` | Audit bylaw/source coverage. |
| `audit_strictness.py` | Audit verifier strictness/gap patterns. |
| `minimize_evidence.py` | Minimize evidence text for proof explanation. |

## Advisory / Learning

| Script | Purpose |
|---|---|
| `run_review_assistant.py` | Advisory LLM/offline briefs for review items. Cannot verify rules. |
| `train_review_ranker.py` | Optional learned review ranking experiment. Not part of the verifier gate. |
| `suggest_gold_candidates.py` | Suggest candidate gold items for human curation. |

## Legacy / Specialized Evaluations

The old entry points below still exist as compatibility wrappers. Their
implementations now live under `scripts/legacy/` so they are visibly separate
from the current MVP workflow.

| Script | Purpose |
|---|---|
| `run_holdout_eval.py` -> `legacy/run_holdout_eval.py` | Within-city Burnaby tuning ablation. |
| `run_vancouver_holdout.py` -> `legacy/run_vancouver_holdout.py` | Older cross-city Vancouver transfer test. |
| `demo.sh` -> `legacy/demo.sh` | Earlier all-in-one demo driver. Prefer `run_consolidated_prototype.py` for current handoff. |
| `validate_config.py` | Validate city config structure. |
