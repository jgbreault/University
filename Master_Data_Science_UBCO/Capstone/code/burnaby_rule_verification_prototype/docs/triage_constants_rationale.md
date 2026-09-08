# Triage / Review-Ranking Constants — Rationale

## The invariant that makes these safe

**None of the constants below change a verified / rejected / not-used decision.**
That decision is made *only* by `decision_policy.verification_decision_from_gaps`
from the deterministic `support_gaps` a candidate accumulates. The constants here
feed `evidence_strength`, `review_priority`, the review-triage score, and the
evidence-repair/audit thresholds — all of which **rank and label the review
queue for humans**. They are an *explainability* surface, not a safety surface:
turning every one of them to zero could reorder the review list, but it could not
verify a rule that the support checks did not already verify, nor reject one they
did. The benchmark safety gates (`verified_precision`, `false_verified_count`,
`verified_source_support_failed_count`, `proof_decision_mismatch_count`) are
therefore unaffected by tuning any number on this page.

## `rule_claims.evidence_strength` (Beta-style confidence for triage)

A Beta(α, β) prior updated by deterministic signals; the score is `α / (α + β)`.

| Constant | Value | Why |
|---|---|---|
| prior α, β | 2.0, 2.0 | Neutral 0.5 prior — no evidence yet means "even odds it's repairable". |
| supported claim | α += 1.0 | A proven claim is mild positive evidence. |
| refuted claim | β += 2.0 | A contradiction is heavier than a missing one — it usually signals a real extraction error. |
| not-enough-info claim | β += 0.6 | Missing proof is weak negative evidence (often repairable with better evidence). |
| support check passed | α += 0.35 | Reuse the old boolean checks as features (hence "Bayesian-lite", not a trained model). |
| support check failed | β += 0.8 | A failed check weighs more than a passed one. |
| critical gap present | β += 1.5 each | value/unit/rule-object/source failures pull the score down hard. |
| decision == verified | α += 2.0 | Display boost, applied *after* the deterministic gate already passed. |
| decision == rejected | β += 2.0 | Display penalty for hard rejections. |

These weights were chosen to order the queue sensibly (refuted > missing,
critical > cosmetic), not fit to data. They are deliberately simple so a reviewer
can predict the ranking.

## `rule_claims.review_priority` thresholds

Buckets a review item into high / medium / low for the queue:

- Pure table-gate gaps → **high** (most repairable: the deterministic claims are
  otherwise clean, a human just needs to confirm table context).
- `unresolved_exception_cue` → **high** (exceptions can change legal meaning).
- near-verified gaps (operator/scope/applies_to) with `strength ≥ 0.55` → medium,
  escalating to **high** at `strength ≥ 0.82` when there are no table-target
  problems. The 0.55 / 0.82 cutoffs just separate "worth a look" from "almost
  done"; they only reorder the queue.
- low-quality gaps (value/unit/rule-object/non-numeric) → **low** (usually bad
  extractions, not near-verified rules).
- otherwise `strength ≥ 0.45` → medium, else low.

## `review_triage` likely-correct score and labels

`likely_correct_score = 0.52·strength + 0.28·check_rate + 0.12·similarity + bonus − penalty`.
The weights sum to ≈0.92 and emphasise `evidence_strength` (the richest signal),
then the raw support-check pass rate, then similarity to an existing verified
rule. `likely_status` thresholds (0.78 likely-correct / 0.55 plausible / 0.35
weak) bucket that score for display. Proof-status bonuses (+0.08 complete table
proof, +0.08 complete span proof, −0.12 proof/decision mismatch) and gap penalties
(0.06–0.14 per gap class) nudge the ordering toward items a human can act on.

## `evidence_repair` / `review_audit` thresholds

- `RETRY_CONFIDENCE_THRESHOLD = 0.62`, `REPAIR_CONFIDENCE_DENOMINATOR = 13.0`:
  the lexical evidence scorer sums field-match points (value 4, rule-object 3,
  condition up to 3, unit 2, operator 2, …); 13.0 normalises a strong all-fields
  match to ≈1.0, and 0.62 is the bar for "worth re-running against this packet".
- `review_audit`: `EVIDENCE_PACKET_REPAIR_THRESHOLD = 0.45`,
  `SAFE_TUNING_SCORE_THRESHOLD = 0.72`, `NEAR_VERIFIED_TABLE_THRESHOLD = 0.55`
  route a review item into a next-action bucket (retry / tune / second-source /
  legal review / upstream). These choose *which workflow* a reviewer should try
  first; they never promote a rule.

## If you change any of these

Re-running `python3 benchmark/evaluate_benchmark.py --city burnaby_r1` will show
the same safety gates (precision, false-verified, source-support, proof-mismatch)
regardless — because they are computed from the deterministic decision, not from
these numbers. Only the review-queue ordering and the triage/audit labels move.
