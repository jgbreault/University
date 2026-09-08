# M4 Gap Report - vancouver_rs

M4 extracts and repairs evidence packs; deterministic verifier decides.

## Summary

| Metric | Value |
|---|---:|
| PDF pages | 22 |
| Source chunks | 251 |
| Evidence packs | 178 |
| M4 numeric clauses | 40 |
| M4 rule-like numeric clauses | 38 |
| M4 selected rule-like numeric coverage | 1.000 |
| Candidates | 56 |
| Verified | 10 |
| Review | 31 |
| Rejected | 15 |
| Not used | 0 |
| False verified | 0 |
| Verified/review recall | 1.000 |
| Extraction coverage recall | 1.000 |
| Verifier retention rate | 1.000 |
| Estimated cost | 0.032056 |
| Latency ms | 298687 |
| Extraction errors | 0 |

## V2 Comparison

| Metric | Delta |
|---|---:|

## Top Support Gaps

- text_candidate_requires_review: 42
- rule_object_not_supported: 20
- rule_family_direction_mismatch: 14
- applies_to_not_supported: 13
- rule_object_unit_not_compatible: 13
- upstream_extraction_requested_review: 13
- extraction_source_fidelity_hold: 12
- operator_not_supported: 9
- coefficient_operand_not_value: 8
- constraint_scope_not_supported: 7

## Missed Rule Categories

- unextracted_gold_rule_ids: 0
- verifier_rejected_gold_rule_ids: 0
- not_used_gold_rule_ids: 0
- missed_verified_or_review_gold_rule_ids: 0

## Interpretation

- M4 preserved the false_verified_count = 0 safety target for this city.
- Missed-rule IDs are evaluation-only and are not used by M4 runtime extraction.
