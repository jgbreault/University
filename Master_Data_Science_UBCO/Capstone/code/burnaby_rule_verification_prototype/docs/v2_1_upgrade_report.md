# V2.1 upgrade report — recall-oriented extraction, review-not-reject policy

Date: 2026-06-12. Safety target held: **false_verified_count = 0 in every run below.**

## Root causes found (Burnaby under-generation)

1. `configs/burnaby_r1.json` targeted laneway/coach-house vocabulary; the R1
   Small-Scale Multi-Unit Housing PDF contains **zero** occurrences of those
   terms ("laneway": 0, "coach house": 0) vs "rowhouse" ×10,
   "small-scale multi-unit" ×3. Discovery scored the wrong chunks.
2. The native extraction prompt hard-coded *"If the text is not a
   laneway/backyard-suite rule, return an empty rules array"* — correct models
   returned empty for SSMUH text.
3. Candidates missing an operator were silently dropped at extraction
   (a hidden hard rejection).
4. Table content was atomized into per-cell chunks (113 of Burnaby's 152
   chunks), starving packs of row context.
5. `non_numeric_value_for_numeric_rule` was a hard rejection; descriptive
   measurement-method text ("midpoint of a sloped roof…") was being rejected
   instead of routed to not_used.

The Burnaby source PDF is correct (SHA256 4eb9ad46…, byte-identical to the
desktop copy). The failure was discovery/extraction recall, not the PDF.

## Changes

| Module | Change |
|---|---|
| `configs/burnaby_r1.json` | Target concept + aliases now use the bylaw's own SSMUH vocabulary (mirrors Zihao's pipeline-9 city config) |
| `configs/calgary_rcg.json` | Adds an explicit target-section contract (`351`, `352`, `358`) so full-bylaw Calgary extraction can over-collect without verifying unrelated district sections |
| `src/burnaby_prototype/native_extraction.py` | Prompt is config-driven (no hard-coded laneway phrase); recall-oriented instruction set; operator-less candidates kept and tagged `operator_missing_from_extraction` → review |
| `src/burnaby_prototype/v2_discovery.py` | Row-level table chunks (title + row header + every column/value pair, cell provenance in `metadata.cells`); two-level list-continuation closure (heading parents own numeric children, numeric lead-ins own letter children; same page, section-compatible, stem always real same-page text, recorded for audit); P9-style metadata on chunks/packs (`selected_because`, `rule_types`, `selection_tier`, `drop_risk`, `discovery_confidence`); per-lane pack quotas (core 40% / table 30% / universal 15% / use 10% / context 5%, score-ordered backfill); `discovery_audit.json` lists near-miss chunks dropped over budget |
| `src/burnaby_prototype/decision_policy.py` | `non_numeric_value_for_numeric_rule` moved CRITICAL_REJECTION → NOT_USED (it can never verify, so false-verified risk is zero by construction); target-section guard routes true-but-out-of-scope full-bylaw sections to NOT_USED |
| `scripts/run_v2_bakeoff.py` | Discovery version folded into the chunk cache key; writes `discovery_audit.json` |
| `dashboard/streamlit_app.py` | Reviewer-first four-bucket dashboard: Verified, Needs review, Out of scope, Rejected; pipeline comparison labels failed gates honestly; V2 source/cost and shadow-examiner panels stay in Advanced diagnostics; bylaw chat is advisory only |
| `scripts/run_mvp_verification.py` | One-command MVP report that refreshes missing benchmarks, inventories PDFs, records V2 discovery, and compares baseline vs V2.1 outputs without treating low recall as a pass |

Verifier checks, repair-before-verify sequencing, gold isolation, and the
examiner are unchanged. Hard rejection still fires for: value/unit absent from
claimed+repaired source, unit/object mismatch, operator/column refuted,
foreign-unit binding, wrong evidence id.

Adapted from Zihao's pipeline 9: discovery metadata fields, list-continuation
closure, lane-based packs, bylaw-native target vocabulary, audit artifacts,
over-generation before review. Not copied: Gemini visual/page-image stack,
Ollama semantic compression, LLM merge-review (our deterministic verifier owns
dedup/trust), his scoring weights.

## Results (before → after)

### Native V2 RAG+LLM bakeoff (per model)

| City / model | Candidates | Verified | Review | Rejected | false_verified |
|---|---|---|---|---|---|
| Burnaby flash-lite | 6 → **76** | 1 → 3 (1 unique ×3 packs) | 5 → 73 | 0 → 0 | 0 |
| Burnaby flash | 4 → **34** | 1 → 3 | 3 → 31 | 0 → 0 | 0 |
| Burnaby gpt-5-mini | 1 → **65** | 0 → 2 | 1 → 60 | 0 → 3* | 0 |
| Vancouver flash-lite | 16 → 14 | 3 → 3 | 11 → 6 | 2 → 5* | 0 |
| Vancouver flash | 8 → 11 | — → 1 | — → 7 | — → 3* | 0 |
| Calgary flash-lite | 40 (40 packs) → 42 (120 packs, full-bylaw discovery) | → 4 | → 25 | → 13* | 0 |

\* all rejections are in the kept critical class (unit/object incompatibility,
value/unit not found post-repair) — model misattributions, not recall losses.
Burnaby verified-or-review gold recall: flash-lite **0.55**, gpt-5-mini 0.525
(was effectively ~0 at 1–6 candidates); Vancouver flash: 1.0. Total bakeoff
cost for all Burnaby models ≈ $0.09.

### Pipeline-5 registry verification (deterministic, offline)

| City | Candidates | Verified | Review | Rejected | Not used | false_verified |
|---|---|---|---|---|---|---|
| Burnaby | 142 | 43 → 43 | 50 → 50 | **35 → 27** | **14 → 22** | 0, precision 1.00 |
| Vancouver (holdout) | 45 | 5 → 5 | 18 → 18 | 13 → 13 | 9 → 9 | 0, precision 1.0 |
| Calgary | 24 | 3 → 3 | 17 → 17 | 4 → 4 | 0 → 0 | 0 |

8 Burnaby candidates moved rejected → not_used; all are descriptive
measurement-method text under numeric families, e.g. `burnaby_r1_137` height =
"midpoint of a sloped roof or the highest point of a flat roof",
`burnaby_r1_118` fire_access_corridor = "paved or gravel", `burnaby_r1_140`
building_separation = "nearest point of each building face".

### Pipeline-9 RAG adapter verification

Burnaby 72: 0/50/14/8, false_verified 0, still a scope/recall gap.
Vancouver 43: 2/21/12/8, false_verified 0, benchmark gate passes.
Calgary 428: 3/152/49/224, false_verified 0 after the target-section guard.
The guard moved unrelated full-bylaw sections (for example R-G/R-Gm 547.x,
generic fence/gateway provisions, and privacy-wall rules) to `not_used`
instead of letting source-true but out-of-target rules enter `verified`.

### Calgary full-bylaw discovery (MVP requirement)

`outputs/v2_runs_full_discovery/calgary_rcg/`: 3,558 chunks spanning pages
7–1052 of the 1,053-page bylaw; 400 packs across 241 distinct pages, all five
lanes represented; `discovery_audit.json` lists 713 rule-signal near-misses
that did not fit the 400-pack budget (raise `--max-packs` to include them).
Bounded extraction (120 packs, flash-lite) verified 4 backyard-suite rules
(setback 0.6/1.5 m, height 7.5 m) with 0 false verified.

### Burnaby discovery quality

93 chunks (row-grouped tables), 80 packs covering all 6 text-bearing pages,
**0 near-misses dropped**, 18 list-continuation closures (e.g. "101.7.1
Height" stem attached to children (1)–(3)).

## Test suite

344 passed (full `tests/`). One test updated:
`test_applicability_matrix.py::test_without_anchor_layer_is_inert` — the
Rowhouse column is now in target scope under the corrected config, so the
no-anchor structured-table gates verify the true rule (gold `br1_cov_001`,
lot_coverage 55% rowhouse); the test now pins the anchor-inertness invariant
(no matrix_bands, no anchor-derived gaps) instead of the stale review outcome.

## Remaining risks / follow-ups

- The native-path Burnaby review queue (73) is dominated by
  `pipeline5_text_candidate_requires_review` + `operator_not_supported`:
  single-model text candidates cannot verify without cross-source consensus
  (config `require_text_consensus`), and table-derived packs often lack
  operator wording. Verified counts on this path stay low by design; the
  registry path remains the verified-rules workhorse (43 Burnaby rules).
  Possible next step: deterministic operator repair from table titles
  ("Maximum Lot Coverage") with auditable provenance — policy-gated, never
  LLM confidence.
- Native bakeoff candidates are not deduplicated across packs (intentional:
  duplicates feed consensus) — report unique counts when quoting verified.
- List-continuation closure currently fires for Burnaby-style dotted headings
  and lead-ins; Calgary/Vancouver clause styles attach parents through their
  existing section-id inheritance instead (0 closures there).
- gpt-5-mini is slow and error-prone on OpenRouter (5 parse errors at
  baseline); consider dropping it from the default bakeoff set.
- Dashboard work is now reviewer-first, but it should remain a review console,
  not a GIS app: show the four trust buckets, source evidence, pipeline
  comparison, and V2 diagnostics; keep GIS de-emphasized.
