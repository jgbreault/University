# vancouver_rs Benchmark Report

## Quality Gates

- PASS: `verified_precision_is_1`
- PASS: `false_verified_is_0`
- PASS: `false_approval_is_0`
- PASS: `retrieval_recall_at_least_0_95`
- PASS: `extraction_coverage_recall_at_least_0_95`
- PASS: `verified_or_review_recall_at_least_0_90`
- PASS: `verified_source_support_failures_is_0`

## Rule Metrics

- Gold rules: 7
- Candidate rules: 56
- Verified rules: 10
- Review rules: 31
- Rejected rules: 15
- Not-used / traceability-only rules: 0
- Release candidate recall (all surfaced outputs): 1.00
- Raw candidate artifact recall: 1.00
- Verified recall: 1.00
- Verified or review recall: 1.00
- Extraction coverage recall (ceiling): 1.00
- Verifier retention rate: 1.00
- Verifier-rejected gold rules: none
- Not-used gold rules: none
- Unextracted gold rules (upstream gap): none
- Verified precision: 1.00
- Retrieval recall: n/a
- False verified rules: 0
- Source support failures: 0

## Top Review / Rejection Reasons

- `text_candidate_requires_review`: 42
- `rule_object_not_supported`: 20
- `rule_family_direction_mismatch`: 14
- `applies_to_not_supported`: 13
- `rule_object_unit_not_compatible`: 13
- `upstream_extraction_requested_review`: 13
- `extraction_source_fidelity_hold`: 12
- `operator_not_supported`: 9
- `coefficient_operand_not_value`: 8
- `constraint_scope_not_supported`: 7

## Evidence Quality

- Evidence units: 56
- Mean evidence quality score: 0.99
- Candidate/evidence match rate: 1.00
- Candidate value grounding rate: 1.00
- Candidate unit grounding rate: 0.96
- Table context completion rate: 0.00

## Proof / Bayesian-Lite Triage

- Proof trace completion rate: 1.00
- Supported claims: 356
- Refuted claims: 2
- Not-enough-info claims: 90
- Mean evidence strength: 0.70
- High-priority review rules: 0
- Table proof rules: 0
- Complete table proofs: 0
- Partial table proofs: 0
- Refuted table proofs: 0
- Proof/decision mismatches: 0

### Top Evidence Quality Issues

- `evidence_text_not_in_source_context`: 3

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

