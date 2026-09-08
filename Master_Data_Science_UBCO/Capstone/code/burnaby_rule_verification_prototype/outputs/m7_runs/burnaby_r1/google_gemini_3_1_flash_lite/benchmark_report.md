# burnaby_r1 Benchmark Report

## Quality Gates

- PASS: `verified_precision_is_1`
- PASS: `false_verified_is_0`
- PASS: `false_approval_is_0`
- PASS: `retrieval_recall_at_least_0_95`
- PASS: `extraction_coverage_recall_at_least_0_95`
- PASS: `verified_or_review_recall_at_least_0_90`
- PASS: `verified_source_support_failures_is_0`
- PASS: `proposal_decision_accuracy_is_1`
- PASS: `proposal_case_accuracy_is_1`
- PASS: `proposal_field_expectations_match`

## Rule Metrics

- Gold rules: 40
- Candidate rules: 144
- Verified rules: 87
- Review rules: 57
- Rejected rules: 0
- Not-used / traceability-only rules: 0
- Release candidate recall (all surfaced outputs): 0.97
- Raw candidate artifact recall: 0.45
- Verified recall: 0.82
- Verified or review recall: 0.97
- Extraction coverage recall (ceiling): 0.97
- Verifier retention rate: 1.00
- Verifier-rejected gold rules: none
- Not-used gold rules: none
- Unextracted gold rules (upstream gap): br1_fire_003
- Verified precision: 1.00
- Retrieval recall: n/a
- False verified rules: 0
- Source support failures: 0

## Top Review / Rejection Reasons

- `text_candidate_requires_review`: 55
- `operator_not_supported`: 19
- `upstream_extraction_requested_review`: 19
- `rule_object_not_supported`: 18
- `rule_family_direction_mismatch`: 16
- `applies_to_not_supported`: 14
- `constraint_scope_not_supported`: 11
- `range_bound_not_maximum`: 10
- `text_condition_not_supported`: 6
- `extraction_source_fidelity_hold`: 4

## Evidence Quality

- Evidence units: 144
- Mean evidence quality score: 0.80
- Candidate/evidence match rate: 1.00
- Candidate value grounding rate: 1.00
- Candidate unit grounding rate: 1.00
- Table context completion rate: 1.00

## Proof / Bayesian-Lite Triage

- Proof trace completion rate: 1.00
- Supported claims: 1051
- Refuted claims: 0
- Not-enough-info claims: 101
- Mean evidence strength: 0.82
- High-priority review rules: 3
- Table proof rules: 83
- Complete table proofs: 66
- Partial table proofs: 17
- Refuted table proofs: 0
- Proof/decision mismatches: 0

### Top Evidence Quality Issues

- `missing_bbox`: 81
- `evidence_text_not_in_source_context`: 81

## Proposal Metrics

- Proposal cases: 10
- Decision accuracy: 1.00
- Case accuracy including expected fields: 1.00
- False approvals: 0
- False rejections: 0
- Field expectation mismatches: 0
- Needs review decisions: 2

## Missed Gold Rules

- `br1_fire_003`

## Proposal Results

- PASS: `approved_verified_core_flat` -> approved (expected approved)
- PASS: `approved_verified_core_sloping_exact` -> approved (expected approved)
- PASS: `reject_flat_roof_height` -> rejected (expected rejected)
- PASS: `reject_front_rear_separation` -> rejected (expected rejected)
- PASS: `reject_accessory_rear_yard` -> rejected (expected rejected)
- PASS: `needs_review_lane_yard` -> rejected (expected rejected)
- PASS: `needs_review_rear_principal_rear_yard` -> needs_review (expected needs_review)
- PASS: `needs_review_fire_access` -> rejected (expected rejected)
- PASS: `needs_review_heritage_coverage` -> needs_review (expected needs_review)
- PASS: `approve_all_verified_setbacks_and_separations` -> approved (expected approved)
