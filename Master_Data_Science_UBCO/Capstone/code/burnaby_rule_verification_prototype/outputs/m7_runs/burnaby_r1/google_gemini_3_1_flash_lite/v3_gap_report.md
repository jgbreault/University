# M4 Gap Report - burnaby_r1

M4 extracts and repairs evidence packs; deterministic verifier decides.

## Summary

| Metric | Value |
|---|---:|
| PDF pages | 7 |
| Source chunks | 93 |
| Evidence packs | 93 |
| M4 numeric clauses | 40 |
| M4 rule-like numeric clauses | 23 |
| M4 selected rule-like numeric coverage | 1.000 |
| Candidates | 144 |
| Verified | 87 |
| Review | 57 |
| Rejected | 0 |
| Not used | 0 |
| False verified | 0 |
| Verified/review recall | 0.975 |
| Extraction coverage recall | 0.975 |
| Verifier retention rate | 1.000 |
| Estimated cost | 0.014857 |
| Latency ms | 81334 |
| Extraction errors | 2 |

## V2 Comparison

| Metric | Delta |
|---|---:|

## Top Support Gaps

- text_candidate_requires_review: 55
- operator_not_supported: 19
- upstream_extraction_requested_review: 19
- rule_object_not_supported: 18
- rule_family_direction_mismatch: 16
- applies_to_not_supported: 14
- constraint_scope_not_supported: 11
- range_bound_not_maximum: 8
- text_condition_not_supported: 6
- extraction_source_fidelity_hold: 4

## Missed Rule Categories

- unextracted_gold_rule_ids: 1
- verifier_rejected_gold_rule_ids: 0
- not_used_gold_rule_ids: 0
- missed_verified_or_review_gold_rule_ids: 1

## Interpretation

- M4 preserved the false_verified_count = 0 safety target for this city.
- Missed-rule IDs are evaluation-only and are not used by M4 runtime extraction.
