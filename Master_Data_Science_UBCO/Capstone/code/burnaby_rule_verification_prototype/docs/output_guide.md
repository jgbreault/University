# Output Guide

The final demo output folder is:

```text
outputs/burnaby_r1_slim_pipeline5_registry/
```

## Files

```text
evidence_units.json
```

Evidence packets adapted from Zihao Pipeline 5. Each candidate rule points to
one of these evidence units.

```text
rule_candidates.json
```

Normalized candidate rules before verification. These are proposals, not trusted
rules.

```text
verified_rules.json
```

Rules that passed deterministic verification. These have no unresolved critical
support gaps.

```text
review_needed.json
```

Rules that may be useful but are incomplete, ambiguous, outside the current GIS
contract, or require human checking.

```text
rejected_rules.json
```

Candidates with hard contradictions or unsafe malformed values, such as wrong
value, missing unit, incompatible unit, or refuted operator direction.

```text
not_used.json
```

Candidates kept for traceability but not validated in the current contract,
such as bylaw section cross-references or rule families outside the current
scope.

```text
gis_rule_contract.json
```

The downstream-safe contract. GIS should consume this file only. It is **slim
and verified-only**: flat rule fields plus one `citation` (document/url/page/
evidence_id/quote); full proof/debug detail stays in `verified_rules.json`. The
export is validated against `schemas/gis_rule_contract.schema.json` at write time
(`additionalProperties: false`), so any leaked internal field fails loudly.

```text
gis_felt_export.json
```

A richer, map-oriented handoff projected from the same verified rules, for the
Felt dashboard and GIS buildable-area work. Adds machine-usable `value_numeric`
(typed float) and a coarse `geometry_target` string (e.g. `front_lot_line`,
`building_footprint`) per constraint, plus a `buildable_area_parameters` map and
review-blocker counts. Validated against `schemas/gis_felt_export.schema.json`.
It is a pure post-verification projection — `gis_rule_contract.json` remains the
authoritative slim contract; this is the convenience export the dashboard renders.

```text
rule_consensus.json
rule_conflicts.json
```

Reporting-only multi-source agreement and disagreement groups. Consensus never
overrides verification, and conflicts never silently pick a winner.

```text
benchmark_report.json
benchmark_report.md
```

Machine-readable and human-readable benchmark summaries.

```text
validation_report.json
```

Compact run summary for dashboard use: bucket counts/rates, evidence quality,
and top review/rejection/not-used reasons without requiring gold labels.

```text
review_router.json
review_router_report.md
```

The single merged review record. Each review rule carries a category,
likely-correct score, priority, potential-mistake flags, closest verified rule,
blocking reason, the next action needed (better evidence, safe tuning, legal
review, upstream issue, or defer), and a decision route. This is the one queue a
human reviewer works from.

```text
review_resolution.json
review_resolution_report.md
```

Operational resolution labels for the remaining review queue: per rule, what
kind of work is left (evidence fix, guard-rejected promotion, duplicate or
degraded extraction, legal review) plus summary counts. Advisory only; never
promotes a rule.

```text
evidence_repair_suggestions.json
evidence_repair_report.md
```

Deterministic RAG-lite suggestions that search existing evidence packets for
stronger support. These suggestions never verify a rule by themselves.

```text
evidence_rerun_report.json / .md
safe_verifier_tuning_candidates.json / .md
```

> **Review diagnostics, not promoters.** The evidence-repair, evidence-rerun,
> and safe-tuning modules exist only to make the 66-item review
> queue actionable for a human reviewer. **None of them can promote a rule into
> `verified_rules.json`** — only the deterministic verifier does that. They
> currently promote 0 rules by design; that is the safety feature, not a bug.
> (The real recoverable surface is small — most review items are structural
> extraction errors, need a second source, or are deliberate scope decisions.)

```text
pipeline5_extraction_preflight.json
```

Machine-readable preflight status for running Zihao's Pipeline 5 extraction
notebook. This explains whether full extraction execution is ready or blocked.

```text
evidence_quality_report.json
```

Diagnostics about candidate/evidence matching, value grounding, unit grounding,
and table context completeness.

```text
slim_summary.json
slim_report.md
```

Short run summaries, including top review reasons.

```text
pipeline_diagram.mmd
benchmark_diagram.mmd
```

Mermaid diagrams for presentation or documentation.

## What To Show In A Demo

Recommended order:

1. `rule_candidates.json` to show extraction proposals.
2. `verified_rules.json` to show trusted rules.
3. `review_needed.json` to show conservative uncertainty handling.
4. `review_router_report.md` to show which review items matter first and what work would reduce review volume.
5. `evidence_repair_report.md` to show possible evidence fixes.
6. `not_used.json` to show traceability-only candidates are preserved.
7. `benchmark_report.md` to show safety metrics.

For interactive review:

```bash
streamlit run dashboard/streamlit_app.py --server.port 8502
```
