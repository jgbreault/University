# M4 Gap Report - calgary_rcg

M4 extracts and repairs evidence packs; deterministic verifier decides.

## Summary

| Metric | Value |
|---|---:|
| PDF pages | 1053 |
| Source chunks | 151 |
| Evidence packs | 125 |
| M4 numeric clauses | 54 |
| M4 rule-like numeric clauses | 53 |
| M4 selected rule-like numeric coverage | 1.000 |
| Candidates | 150 |
| Verified | 30 |
| Review | 41 |
| Rejected | 27 |
| Not used | 52 |
| False verified | 0 |
| Verified/review recall | 1.000 |
| Extraction coverage recall | 1.000 |
| Verifier retention rate | 1.000 |
| Estimated cost | 0.044801 |
| Latency ms | 258420 |
| Extraction errors | 2 |

## V2 Comparison

| Metric | Delta |
|---|---:|

## Top Support Gaps

- text_candidate_requires_review: 111
- upstream_extraction_requested_review: 86
- extraction_source_fidelity_hold: 74
- outside_target_section: 56
- rule_object_not_supported: 55
- operator_not_supported: 42
- applies_to_not_supported: 33
- enumerated_branch_condition_missing: 32
- constraint_scope_not_supported: 21
- rule_object_unit_not_compatible: 16

## Missed Rule Categories

- unextracted_gold_rule_ids: 0
- verifier_rejected_gold_rule_ids: 0
- not_used_gold_rule_ids: 3
- missed_verified_or_review_gold_rule_ids: 0

## Interpretation

- M4 preserved the false_verified_count = 0 safety target for this city.
- Missed-rule IDs are evaluation-only and are not used by M4 runtime extraction.
