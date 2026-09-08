# Slim Verification Report

```text
Pipeline 5 candidates/evidence -> deterministic validation -> verified/review/rejected/not_used
```

- Input mode: `native_rag_llm`
- Evidence units: 150
- Candidate rules: 150
- Verified rules: 29
- Review needed: 42
- Rejected rules: 27
- Not used / traceability only: 52
- Evidence match rate: 1.00
- Value grounding rate: 0.93
- Table context completion: 0.00
- Evidence repair suggestions: 35
- Suggestions with alternative evidence: 35
- Retry candidates from evidence repair: 34
- Evidence intelligence safe bundle retries: 26
- Evidence rerun attempts: 34
- Promotion-ready shadow reruns: 0
- Evidence bundle rerun attempts: 31
- Promotion-ready bundle reruns: 7
- Guarded bundle promotions: 7
- Rule graph nodes / edges: 463 / 2021
- Proof DAG sidecar entries: 150
- Cache hits / misses: 0 / 150
- Semantic high-similarity review items: 10
- Review items potentially promotable after evidence fix: 0
- Safe verifier tuning candidates: 0
- Felt verified-rule CSV rows: 22

## Review Actions

- `retry_with_better_evidence`: 34
- `defer_low_priority`: 5
- `human_legal_review`: 2
- `upstream_candidate_issue`: 1

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
- `unresolved_exception_cue`: 16
