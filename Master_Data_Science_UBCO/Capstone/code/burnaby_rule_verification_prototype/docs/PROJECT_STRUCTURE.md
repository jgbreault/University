# Project Structure

This project has one authority layer: deterministic verification. Everything
else either adapts input, explains decisions, evaluates safety, or prepares
verified outputs for downstream use.

## Runtime Flow

```text
Full bylaw PDF
      |
      v
Native M4 discovery/RAG/native extraction
      |
      v
rule_candidates + evidence_units -> source repair
                                      |
                                      v
                      verification.py + decision_policy.py
                                      |
                                      v
                    verified / review_needed / rejected / not_used
                                      |
                                      v
                    benchmark + dashboard + verified-only GIS exports
```

The MVP report selects the current product path. M4 is current when it preserves
zero false verified rules, passes adversarial gates, covers the full source
inventory, and improves native extraction value. Pipeline 5 and Pipeline 9
artifacts are retained as legacy/upstream reference inputs, but they are not the
current product path. All intake paths still become the same internal shape:
`rule_candidates` plus `evidence_units`. Extraction, RAG, SQLite, and LLM tools
remain proposer or advisory layers.

## Source Folder Skeleton

Canonical modules still live at `src/burnaby_prototype/*.py` so existing
scripts, dashboard code, and tests keep working. The source package now has
navigation folders with README files that define the intended boundaries for a
future import migration:

```text
src/burnaby_prototype/adapters/   upstream/native extraction intake
src/burnaby_prototype/discovery/  full-bylaw retrieval, packs, cache, bakeoff
src/burnaby_prototype/repair/     source-backed evidence repair
src/burnaby_prototype/verifier/   deterministic authority layer
src/burnaby_prototype/review/     advisory human-review support
src/burnaby_prototype/exports/    verified-only GIS/compliance outputs
src/burnaby_prototype/reports/    benchmark/dashboard/proof reporting
```

This is an organization layer, not a behavior change. Moving the actual `.py`
files should be a separate measured migration with the full test suite.

## Core Runtime Files

```text
scripts/run_slim_verifier.py
```

Main verifier CLI. Resolves city config, loads candidates from Pipeline 5,
Pipeline 9, or native extraction output, runs the slim verifier, and writes
output files.

```text
scripts/run_consolidated_prototype.py
```

Handoff front door. Prints current status, refreshes the MVP report, or wraps
native discovery/extraction runs. It contains no verifier logic.

```text
scripts/run_mvp_verification.py
```

Builds the current benchmark/status report across Burnaby, Vancouver, and
Calgary lanes. This is the fastest way to check whether the prototype is safe
and where extraction is still weak.

```text
src/burnaby_prototype/zihao_adapter.py
```

Converts upstream extraction records into the verifier contract:
`evidence_units` and `rule_candidates`.

```text
src/burnaby_prototype/pipeline9_adapter.py
```

Pipeline 9 (graph-RAG) intake: joins `merged_rules_deduplicated.json` rule
records to `text_blocks.jsonl` blocks (`source_id` -> `block_id`, with a
pack-id fallback), preserves P9 provenance (original page, pseudo page, pack,
lane, applicability, filter action), maps family aliases, applies the
asymmetric upstream-label policy, and re-anchors evidence to
`data/bylaws/<city>/source.pdf` (authentic page window or
`rag_context_mismatch` -> forced review). Proposer-tier: never imported by
the verify path.

```text
src/burnaby_prototype/native_extraction.py
scripts/run_v2_bakeoff.py
scripts/run_v3_bakeoff.py
scripts/run_m4_bakeoff.py
```

Our proposer-tier extraction path. It uses full-bylaw evidence packs and one or
more OpenRouter models to produce the same `rule_candidates` and
`evidence_units` contract. V3 adds family-query expansion, section neighbors,
and support-gap repair packs before rerunning extraction. M4 adds exhaustive
source-corpus coverage and is launched through `run_m4_bakeoff.py`. Native
extraction never verifies its own candidates.

```text
src/burnaby_prototype/v2_discovery.py
src/burnaby_prototype/v2_store.py
src/burnaby_prototype/v3_discovery.py
scripts/build_m4_source_corpus.py
```

Full-bylaw source discovery and SQLite run cache. These support faster reruns,
evidence-pack construction, and model bakeoffs. V3 wraps the source chunks with
additional discovery lanes and repair-pack construction. The M4 source-corpus
builder writes benchmark/source snapshots and selected-coverage audits from the
official PDFs without reading gold. SQLite is a rebuildable cache; JSON
artifacts remain the official outputs.

```text
src/burnaby_prototype/slim_pipeline.py
```

Pipeline orchestrator. Writes candidate/evidence files, calls verification,
builds reports, validates GIS/Felt exports, and writes dashboard-ready summaries.

```text
src/burnaby_prototype/verification.py
```

Main trust-gate loop. It looks up evidence, normalizes the candidate, calls
support/proof helpers, collects `support_gaps`, and produces verified or
non-verified rule objects.

```text
src/burnaby_prototype/normalization.py
```

Candidate cleanup before verification. It maps extraction wording into canonical
rule families and applies config-driven normalization rewrites. It does not
prove or promote rules.

```text
src/burnaby_prototype/support_checks.py
```

Reusable deterministic checks for cited evidence: value, unit, operator,
rule-object, scope, applies_to, local evidence windows, and parent-clause
context. This keeps the main verifier loop smaller.

```text
src/burnaby_prototype/decision_policy.py
```

Maps support gaps into final buckets:
`verified`, `review_needed`, `rejected`, or `not_used`. City configs can set
target sections so a broad extraction from a full bylaw does not accidentally
verify rules outside the intended legal slice.

```text
src/burnaby_prototype/table_natural_logic.py
```

Table-aware proof helper. Uses table title, row header, column header, and cell
value to prove or refute field-level claims.

```text
src/burnaby_prototype/text_span_proof.py
```

Text evidence helper. Ensures prose candidates are supported by local evidence
spans rather than broad page-level context.

```text
src/burnaby_prototype/proof_trace.py
```

Reviewer-facing proof and explanation helpers. These build proof traces, human
reasons, table-proof repairs, and proof/decision diagnostics without changing
verification decisions.

## Shared Rule Knowledge

```text
src/burnaby_prototype/domain_schema.py
```

Shared canonical rule families, unit aliases, operator direction, and numeric
parsing helpers.

```text
src/burnaby_prototype/normalization_rules.py
```

Config-driven normalization policy used by `normalization.py`. This keeps
city-specific terminology in config instead of scattering it through verifier
logic.

```text
configs/burnaby_r1.json
configs/vancouver_rs.json
```

City/zone metadata, vocabulary, and verification policy. Config may contain
terminology and aliases; it must not contain final legal answers or gold-rule
thresholds.

## Review Intelligence

These modules make review work easier. They never verify a rule by themselves.

```text
src/burnaby_prototype/evidence_intelligence.py
```

Builds one rule-centric evidence index for the run. It scores evidence packets,
builds best evidence bundles, marks safe shadow-rerun candidates, and writes
`evidence_intelligence.json`. Bundle scores are advisory and cannot promote a
rule.

```text
src/burnaby_prototype/evidence_repair.py
```

Searches existing evidence packets for stronger support candidates.

```text
src/burnaby_prototype/evidence_rerun.py
```

Runs shadow retries with better evidence and with best evidence bundles. Results
remain advisory unless the guarded bundle-promotion policy confirms that the
deterministic verifier returned `verified` with no support gaps, missing bundle
fields, proof mismatch, or exception/covenant risk.

```text
bundle_promotion_report.json
```

Generated by `evidence_rerun.py`. Lists review rules that were moved into
`verified_rules.json` after guarded evidence-bundle rerun. This is the current
safe mechanism for reducing review volume without weakening verification.

```text
src/burnaby_prototype/review_router.py
```

Unified reviewer queue that joins triage, evidence intelligence, evidence
repair, rerun, bundle rerun, and audit into one decision-tree row per review
rule. It writes `review_router.json` for easier dashboard and human review. It
is advisory only and never verifies a rule.

```text
src/burnaby_prototype/review_resolution.py
```

Final operational resolution labels for the remaining review queue (what kind
of work is left per rule: evidence fix, guard-rejected promotion, duplicate,
legal review). Advisory only; writes `review_resolution.json`.

```text
src/burnaby_prototype/embedding_semantics.py
```

Optional MiniLM sentence-embedding similarity used by semantic review to rank
review rules against verified ones. Advisory only, local-files-only model
loading, injectable backend for tests; the pipeline degrades gracefully when
sentence-transformers is not installed.

```text
src/burnaby_prototype/review_text.py
src/burnaby_prototype/rule_text.py
```

Small leaf modules of shared text helpers. `review_text` holds the
reviewer-facing sentence/counter helpers the advisory modules used to
copy-paste (the copies had already drifted); `rule_text` holds the
rule-sentence renderers, breaking the old slim_pipeline <-> gis_felt_export
import cycle.

```text
src/burnaby_prototype/verification_cache.py
```

Builds stable cache keys and hit/miss diagnostics for future incremental
multi-bylaw runs. Cache keys include candidate fields, cited evidence text,
config hash, verifier version, and run-context hash so consensus/collision
dependencies are visible. Current mode reports safe reuse; it does not skip
verification by default.

```text
src/burnaby_prototype/semantic_review.py
```

Builds deterministic semantic signatures from structured fields and compares
review rules to verified rules by meaning: rule family, direction, value, unit,
scope, applies_to, and condition concepts. It is advisory only and cannot clear
support gaps.

```text
src/burnaby_prototype/safe_tuning.py
```

Lists possible verifier-tuning candidates with guardrails. This is planning
support, not automatic promotion.

```text
src/burnaby_prototype/llm_review_assistant.py
```

Optional advisory summaries for review items. It can explain, but it cannot
verify.

## Extraction And Discovery Helpers

```text
src/burnaby_prototype/extraction/
scripts/fetch_bylaw.py
scripts/run_extraction.py
```

Legacy helper for the team to read and extract a bylaw PDF themselves
(diagnose verification, curate gold sets, trial new cities). It emits the same
`final_rule_registry.json` contract so an experimental verify-run is
`run_slim_verifier.py --pipeline5-registry <path>` with zero verifier changes.
`pdf_ingest` layers docling over a pdfplumber fallback; `text_stream` is a
deterministic section-anchored clause proposer; `table_stream` is a cached,
rate-limited Gemini table reader (key from `GOOGLE_API_KEY` env only, never
written to disk; injectable fake client for tests); `registry_writer` merges
both streams into the Pipeline-5 contract plus an all-clauses evidence
sidecar. The verify path never imports this package (boundary test in
`tests/test_extraction_layer.py`); its candidates are proposals and the
deterministic verifier remains the gate.

## Safety And Relationship Guards

```text
src/burnaby_prototype/consensus.py
```

Reports multi-source agreement and conflicts. Consensus can support review
triage, but it does not override deterministic evidence checks.

```text
src/burnaby_prototype/conflict_guard.py
```

Finds cross-family collisions, such as lot coverage and impervious surface
being confused. Conflicts route to review.

```text
src/burnaby_prototype/rule_claims.py
```

Claim labels, proof traces, evidence-strength scoring, and proof/decision
diagnostics.

```text
src/burnaby_prototype/rule_graph.py
```

Creates `rule_graph.json`, a diagnostic graph linking candidates, evidence
packets, canonical rule keys, verified rules, and review rules. It helps find
duplicates, conflicts, same-scope clusters, and missing-field patterns. It does
not override support gaps.

## GIS And Dashboard Outputs

```text
src/burnaby_prototype/gis_felt_export.py
```

Creates the richer verified-only Felt/GIS export.

```text
src/burnaby_prototype/geometry_operator.py
```

Maps verified rule families into coarse geometry operations, such as setbacks,
height limits, and coverage limits.

```text
scripts/build_buildable_envelope.py
```

Builds a simple buildable-envelope JSON from verified rules.

```text
scripts/build_proof_graph.py
```

Creates `proof_graph.html`, an interactive proof viewer for verified and review
rules.

```text
dashboard/streamlit_app.py
```

Streamlit dashboard for results, evidence intelligence, review decision tree,
bundle rerun, rule graph, review queues, proof explanations, and GIS/Felt
exports.

## Benchmark Files

```text
benchmark/evaluate_benchmark.py
```

Measures rule recall/precision, source support, quality gates, and proposal
decision safety.

```text
benchmark/evaluate_adversarial.py
```

Runs poisoned candidates that must not leak into verified outputs.

```text
benchmark/gold/*.json
```

Gold rules and cases used only for evaluation. Runtime verification must never
import or depend on these answers.

## Important Output Files

```text
verified_rules.json
```

Rich verified rules with proof traces.

```text
gis_rule_contract.json
```

Slim verified-only contract for downstream GIS.

```text
gis_felt_export.json
```

Map/dashboard-oriented verified-only projection.

```text
review_needed.json
```

Rules that are plausible but need more evidence, clearer scope, or legal review.

```text
not_used.json
```

Extraction artifacts kept for audit but outside the current verifier contract.

```text
benchmark_report.md
```

Readable benchmark summary and quality gates.
