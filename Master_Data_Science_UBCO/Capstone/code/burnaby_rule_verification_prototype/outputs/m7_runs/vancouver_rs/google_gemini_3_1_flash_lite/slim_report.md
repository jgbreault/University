# Slim Verification Report

```text
Pipeline 5 candidates/evidence -> deterministic validation -> verified/review/rejected/not_used
```

- Input mode: `native_rag_llm`
- Evidence units: 56
- Candidate rules: 56
- Verified rules: 10
- Review needed: 31
- Rejected rules: 15
- Not used / traceability only: 0
- Evidence match rate: 1.00
- Value grounding rate: 1.00
- Table context completion: 0.00
- Evidence repair suggestions: 27
- Suggestions with alternative evidence: 27
- Retry candidates from evidence repair: 21
- Evidence intelligence safe bundle retries: 0
- Evidence rerun attempts: 21
- Promotion-ready shadow reruns: 0
- Evidence bundle rerun attempts: 0
- Promotion-ready bundle reruns: 0
- Guarded bundle promotions: 0
- Rule graph nodes / edges: 188 / 677
- Proof DAG sidecar entries: 56
- Cache hits / misses: 0 / 56
- Semantic high-similarity review items: 4
- Review items potentially promotable after evidence fix: 0
- Safe verifier tuning candidates: 0
- Felt verified-rule CSV rows: 7

## Review Actions

- `retry_with_better_evidence`: 21
- `upstream_candidate_issue`: 6
- `defer_low_priority`: 4

## Top Review / Rejection Reasons

- `text_candidate_requires_review`: 42
- `rule_object_not_supported`: 20
- `rule_family_direction_mismatch`: 14
- `upstream_extraction_requested_review`: 13
- `applies_to_not_supported`: 13
- `rule_object_unit_not_compatible`: 13
- `extraction_source_fidelity_hold`: 12
- `operator_not_supported`: 9
- `coefficient_operand_not_value`: 8
- `constraint_scope_not_supported`: 7
