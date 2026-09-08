# M5.6 — Honest slot measurement + hardening

M5.6 builds on the M5.5 slot-audited measurement layer. It does **not** change any
verification decision: extraction still only generates candidates, the
deterministic verifier is still the sole authority, and GIS/dashboard still
consume only verified, source-supported rules. M5.6 fixes how the layer
*measures* and closes a batch of latent bugs found by an adversarial bug hunt.

## Why M5.5's numbers were not yet defensible

The M5.5 rule-slot ledger is a deliberately loose over-count ceiling (one slot
per visible numeric signal) so it can never *hide* over-extraction. But it is too
noisy to use as a headline denominator:

- 24–47% of slots had an `unknown` rule family (numeric tokens with no
  recognizable family).
- `extract_measurements` matched any number, including section references
  (`section 6`), dotted clause numbers (`101.5.2`) and enumerators (`(1)`).
- There was no semantic dedup: one legal value repeated across matrix columns
  produced a slot each (Calgary had 2,181 `setback` slots).
- ~26% of Burnaby's "source" slots were actually derived from the verifier's own
  outputs (`observed_output_source_slot`), folded into `total_rule_slots` — a
  denominator that is partly a function of the numerator.

So `missed_slot_count` (302 / 159 / 5,694) was mostly noise, not a backlog.

## The M5.6 scored denominator

`compute_scored_slot_metrics` reports coverage against a **defensible** denominator
alongside the raw ceiling (which is retained, now labelled advisory):

- **Scored** = corpus-derived (`slot_origin == "source_corpus"`), recognized
  family, inside the city's GIS text-rule contract.
- **Distinct legal slots** = scored slots collapsed on `(family, value, unit)`.
  Scope is intentionally excluded from the key because source-inferred scope
  (`source_scope_signal`) is greedy on multi-column table context; scope
  *correctness* is enforced by the verifier's scope/column gates, not here.
- **Coverage is credited by legal identity, not slot id.** A verified rule the
  generic table index could only pin to an output-observed coordinate still
  credits the corpus slot it legally matches. This lets the *denominator* exclude
  output-derived slots (breaking circularity) without zeroing the *numerator*.

Result (M5.6 run `m56_hardened_20260616`):

| City | raw total | scored legal denom | scored verified | coverage | missed (scored) |
|------|-----------|--------------------|-----------------|----------|-----------------|
| Burnaby R1 | 422 | 66 | 21 | 32% | 42 |
| Vancouver RS | 130 | 44 | 4 | 9% | 38 |
| Calgary RCG | 4,300 | 671 | 7 | 1% | 628 |

The scored missed counts are an actionable backlog; the raw ceiling stays visible
as an over-count guardrail.

## Safety contract (unchanged, all green)

`false_verified_count=0`, `false_approval_count=0`, `verified_precision=1.0`,
`verified_source_support_failed_count=0`, `verified_slot_mapping_rate=1.0`,
`unsupported_verified=0`, unresolved duplicate verified slots `=0`, and the M4
reconciliation delta `>= 0`. The adversarial benchmark (24/24 poisoned rule cases
+ 3/3 poisoned bundle cases, 0 leaks) and the full unit suite (474 tests) pass.

M6 metric naming clarification: raw `candidate_recall` is now reported as
`raw_candidate_artifact_recall` for diagnosis. The release gate is
`release_candidate_recall` / `extraction_coverage_recall`, which counts gold
rules surfaced anywhere in the extraction output path: candidate, verified,
review, rejected, or not-used. This prevents a rule that has already moved into a
safe verifier bucket from looking like an extraction miss.

## Bug fixes shipped in M5.6

Found by an adversarial bug hunt, each verified to keep the safety gates green:

- **Verifier (operator borrowing).** `_value_has_same_sentence_operator_parent`
  used `.find()` (first textual hit) to test the operator parent, so a repeated
  value could borrow a neighbouring rule's "maximum"/"minimum". It now anchors on
  the same occurrence the scope window selected. (`verification.py`)
- **Reconciliation circularity.** The M4 baseline slot audit was mapped against
  the *current* run's output-observed slots. It now uses a shared corpus base
  ledger, each run supplemented with its own observed slots. (`m7_measure.py`)
- **Slot ledger noise.** `extract_measurements` now drops section references,
  dotted clause numbers and enumerators (unit-bearing measurements are always
  kept). The duplicate keeper is now deterministic (lowest `rule_id`). (`m7_measure.py`)
- **Range rewrite.** The dwelling-unit "X to Y" range pattern gained decimal
  boundary guards so it cannot latch onto a dotted section number.
  (`normalization_rules.py`)
- **Value/unit integrity.** `_normalize_value` no longer truncates comma-formatted
  numbers (`1,234.5`→`1234.5`); `_normalize_unit` canonicalizes `sq.m` like
  `sq m`. (`native_extraction.py`)
- **GIS export.** `rule_object` coerced to string and `source_rule_ids` filters
  `None`, matching the GIS contract schema. (`gis_felt_export.py`)
- **Table exceptions.** The except-clause regex now matches compound units
  (`m2`); base-value resolution is guarded by a loose claim and the carve-out
  value by a strict subset claim, so ambiguous `N, except M for X` cases route to
  review on both branches. (`table_natural_logic.py`)
- **Benchmark matcher.** `_score_match` now requires *all* `required_rule_terms`
  (was `len-1` for >3 terms). Verified across cities: `false_verified` stays 0 and
  `verified_or_review_recall` stays above the 0.90 gate. (`evaluate_benchmark.py`)
- **Review routing.** `upstream_extraction_requested_review` now has an explicit
  router branch instead of falling through to low-priority deferral.
  (`review_router.py`)

## Two proposal gold cases corrected (not gamed)

`needs_review_fire_access` and `needs_review_heritage_coverage` failed
`proposal_field_expectations_match` while their decisions were already correct
(`false_approval=0`). The field expectations were stale:

- **Fire access**: the WIDTH rule is verified and the 0.8 m proposal fails it
  (decision `rejected`). The vertical CLEARANCE rule is correctly held in review
  (`rule_object_not_supported` — its "clear of any projections" evidence does not
  deterministically support the `fire_access_corridor` family), so that field is
  review, not failed.
- **Heritage coverage**: the heritage IMPERVIOUS limit is verified
  (`burnaby_r1_004`, `<=70%`, evidence "impervious surface area up to 70%",
  matches gold `br1_heritage_002`), so the 69% proposal is checked and passes;
  the heritage LOT-COVERAGE rule is held for text-consensus, so that field defers
  to review and the decision stays `needs_review`.

Both edits make the gold reflect sound, source-supported verifier behaviour. They
do **not** promote any unsupported rule.

## Deferred (tracked, not done — reason: safety / scope)

- **P3 table-proof completion** (raise `table_proof_completion_rate` to convert
  review→verified): only via better evidence *assembly* (matrix-anchor header
  binding), never looser thresholds, and gated by the adversarial benchmark.
- Several table-matrix internals (band header stacking, continuation-row merging,
  family validation across bands) flagged by the bug hunt: real but deep; they
  are over-conservative (route to review) today, so deferred to avoid
  destabilizing the matrix path without a dedicated test harness.
- Frontier methods (LegalBench-RAG retrieval scoring, RAGAS separated metrics,
  ColPali table-image retrieval, DSPy/DocETL extraction optimization) remain
  shadow-only and must beat the M5.6 gates before touching verification.
