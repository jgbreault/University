# calgary_rcg Benchmark Report

## Quality Gates

- PASS: `verified_precision_is_1`
- PASS: `false_verified_is_0`
- PASS: `false_approval_is_0`
- PASS: `retrieval_recall_at_least_0_95`
- PASS: `extraction_coverage_recall_at_least_0_95`
- PASS: `verified_or_review_recall_at_least_0_90`
- PASS: `verified_source_support_failures_is_0`

## Rule Metrics

- Gold rules: 19
- Candidate rules: 150
- Verified rules: 29
- Review rules: 42
- Rejected rules: 27
- Not-used / traceability-only rules: 52
- Release candidate recall (all surfaced outputs): 1.00
- Raw candidate artifact recall: 0.95
- Verified recall: 0.95
- Verified or review recall: 1.00
- Extraction coverage recall (ceiling): 1.00
- Verifier retention rate: 1.00
- Verifier-rejected gold rules: none
- Not-used gold rules: cal_rcg_setback_corner_street_001, cal_rcg_setback_garage_001, cal_rcg_setback_side_001
- Unextracted gold rules (upstream gap): none
- Verified precision: 1.00
- Retrieval recall: n/a
- False verified rules: 0
- Source support failures: 0

## Top Review / Rejection Reasons

- `text_candidate_requires_review`: 112
- `upstream_extraction_requested_review`: 86
- `extraction_source_fidelity_hold`: 74
- `outside_target_section`: 56
- `rule_object_not_supported`: 55
- `operator_not_supported`: 43
- `applies_to_not_supported`: 33
- `enumerated_branch_condition_missing`: 32
- `constraint_scope_not_supported`: 21
- `rule_object_unit_not_compatible`: 16

## Evidence Quality

- Evidence units: 150
- Mean evidence quality score: 1.00
- Candidate/evidence match rate: 1.00
- Candidate value grounding rate: 0.93
- Candidate unit grounding rate: 0.15
- Table context completion rate: 0.00

## Proof / Bayesian-Lite Triage

- Proof trace completion rate: 1.00
- Supported claims: 977
- Refuted claims: 16
- Not-enough-info claims: 207
- Mean evidence strength: 0.70
- High-priority review rules: 2
- Table proof rules: 0
- Complete table proofs: 0
- Partial table proofs: 0
- Refuted table proofs: 0
- Proof/decision mismatches: 0

### Top Evidence Quality Issues


## Proposal Metrics

- Proposal cases: 0
- Decision accuracy: 0.00
- Case accuracy including expected fields: 0.00
- False approvals: 0
- False rejections: 0
- Field expectation mismatches: 0
- Needs review decisions: 0

## Missed Gold Rules


## Proposal Results

