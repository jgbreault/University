# Source Module Map

## Final Working Path

For the final demo, treat this as the only product path:

```text
scripts/run_consolidated_prototype.py
-> scripts/run_m4_bakeoff.py
-> scripts/run_v3_bakeoff.py --discovery-mode m4
-> native_extraction.py
-> slim_pipeline.py
-> verification.py / support_checks.py / decision_policy.py
-> verified_rules.json + review_needed.json + dashboard
```

In plain language:

- `run_consolidated_prototype.py` is the handoff command surface.
- `run_m4_bakeoff.py` is the current native full-bylaw extraction entrypoint.
- `run_v3_bakeoff.py` is still used as the shared engine, but M4 calls it in
  `m4` mode. Do not treat it as a separate product version in the demo.
- `verification.py`, `support_checks.py`, and `decision_policy.py` are the
  deterministic trust gate.
- `dashboard/streamlit_app.py` reads artifacts only; it does not verify rules.

The `v2_*` and `v3_*` module names are historical, but some are still active
engine dependencies for M4. Do not delete or move them until the imports are
renamed in one tested migration. For presentation and handoff, call the current
system **M4**.

This package still keeps canonical `.py` modules at the top level for
compatibility: many scripts and tests import modules directly as
`burnaby_prototype.<module>`. The folder skeleton below now exists as the
navigation layer and future import target. Do not move canonical modules into
subpackages until the import migration is done in one tested pass.

## Core Verifier

These files decide whether a candidate rule is proven, review-only, rejected,
or out of scope.

| File | Purpose |
|---|---|
| `verification.py` | Main verification loop. Loads evidence, normalizes candidates, runs support/proof checks, and emits decision buckets. |
| `decision_policy.py` | Maps support gaps to `verified`, `review_needed`, `rejected`, or `not_used`. Also holds global safety gates for known false-verify patterns. |
| `support_checks.py` | Deterministic value/unit/operator/scope/evidence checks. |
| `normalization.py` | Cleans candidate fields into canonical rule objects, operators, units, and scopes. |
| `normalization_rules.py` | Config-driven normalization helpers. |
| `domain_schema.py` | Shared rule families, units, operators, and numeric parsing. |
| `verification_cache.py` | Cache keys and diagnostics for verifier reuse; does not skip verification by default. |

## Table And Text Proof

These files explain or prove evidence support. They are important: recent real
LLM runs showed that flattened table text can leak false rules unless table
geometry is preserved.

| File | Purpose |
|---|---|
| `table_matrix.py` | Recovers row/column/cell structure from matrix-style tables and attaches `matrix_anchor` evidence. |
| `v2_matrix_candidates.py` | Proposes deterministic matrix-table candidates for V2 extraction. |
| `table_natural_logic.py` | Table-aware proof/refutation helpers. |
| `text_span_proof.py` | Prose evidence span and material-condition checks. |
| `proof_trace.py` | Human-readable proof traces and gap labels. |
| `proof_dag.py` | Proof DAG sidecar for explanation/reporting. |
| `rule_claims.py` | Claim labels, proof diagnostics, and evidence-strength helpers. |

## Intake And Extraction

These modules propose candidates or adapt outside extractor output. They do not
verify their own results.

| File | Purpose |
|---|---|
| `zihao_adapter.py` | Converts Pipeline 5-style registry output into `rule_candidates` + `evidence_units`. |
| `pipeline9_adapter.py` | Converts Pipeline 9 graph-RAG output, preserves provenance, and re-anchors evidence to source PDFs. |
| `native_extraction.py` | Current LLM extraction candidate parser/caller used by M4. |
| `v2_store.py` | SQLite cache/run ledger reused by M4 for source chunks, packs, and model outputs. |
| `v2_discovery.py` | Source-chunk helpers reused by M4. Historical name, active dependency. |
| `v2_bakeoff.py` | Shared model-call assembly reused by M4. Historical name, active dependency. |
| `v3_discovery.py` | Discovery wrapper reused by M4 in `m4` mode: family-query packs, section neighbors, target-section expansion, and repair packs. |
| `v3_report.py` | Gap report builder reused by M4/V3 evaluation output. |
| `extraction/` | Legacy internal PDF-to-registry helper path. |

## Source Repair And RAG

These improve evidence packets and reviewer search. They are advisory or
pre-verification support layers.

| File | Purpose |
|---|---|
| `source_repair.py` | Source-backed repair: page re-anchoring, nearby context, table/heading context, mismatch flags. |
| `bylaw_rag.py` | BM25/RAG retrieval support for source search and dashboard Q&A. |
| `evidence_contract.py` | Evidence type constants and lightweight evidence contract helpers. |

## Advisory Review

These help humans understand or triage review items. They must not promote
rules into `verified_rules.json`.

| File | Purpose |
|---|---|
| `evidence_intelligence.py` | Evidence bundle scoring and diagnostics. |
| `evidence_repair.py` | Searches for better evidence among existing packets. |
| `evidence_rerun.py` | Advisory reruns with stronger evidence bundles. |
| `review_router.py` | Unified review queue and reviewer next-action labels. |
| `review_resolution.py` | Operational resolution labels for remaining review items. |
| `review_assistant_packets.py` | Deterministic packets for dashboard/assistant review. |
| `llm_review_assistant.py` | Optional LLM review summaries; advisory only. |
| `semantic_review.py` | Deterministic semantic comparison of review vs verified rules. |
| `embedding_semantics.py` | Optional sentence-embedding ranking for review support. |
| `nli_semantics.py` | Optional entailment second opinion; advisory only. |
| `review_ranker.py` | Optional learned review ranking; advisory only. |
| `safe_tuning.py` | Candidate safe-tuning report; planning support only. |

## Reports And Exports

These turn verified/review outputs into reports, dashboard data, or downstream
GIS artifacts.

| File | Purpose |
|---|---|
| `slim_pipeline.py` | Main orchestrator/writer for verifier outputs and sidecar reports. |
| `coverage_report.py` | Coverage/gap matrix reporting. |
| `rule_graph.py` | Diagnostic graph linking candidates, evidence, verified rules, and review items. |
| `gis_felt_export.py` | Verified-only Felt/GIS export. |
| `geometry_operator.py` | Maps verified rule families into coarse GIS operations. |
| `compliance.py` | Proposal/compliance checker against verified GIS contract. |
| `applicability.py` | Structured applicability parsing for dwelling/unit-range table columns. |
| `conflict_guard.py` | Cross-family collision detection. |
| `consensus.py` | Agreement/conflict diagnostics across evidence sources. |
| `rule_text.py` | Shared rule sentence rendering. |
| `review_text.py` | Shared reviewer-facing wording helpers. |

## Folder Skeleton

These folders now exist with local README files:

```text
adapters/
discovery/
repair/
verifier/
review/
exports/
reports/
```

For now they document ownership and boundaries. The current top-level modules
remain canonical until a later import migration updates scripts, dashboard code,
tests, and any external handoff notes together.
