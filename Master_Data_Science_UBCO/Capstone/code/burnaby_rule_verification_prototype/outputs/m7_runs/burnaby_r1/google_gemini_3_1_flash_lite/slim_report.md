# Slim Verification Report

```text
Pipeline 5 candidates/evidence -> deterministic validation -> verified/review/rejected/not_used
```

- Input mode: `native_rag_llm`
- Evidence units: 144
- Candidate rules: 144
- Verified rules: 87
- Review needed: 57
- Rejected rules: 0
- Not used / traceability only: 0
- Evidence match rate: 1.00
- Value grounding rate: 1.00
- Table context completion: 1.00
- Evidence repair suggestions: 55
- Suggestions with alternative evidence: 55
- Retry candidates from evidence repair: 51
- Evidence intelligence safe bundle retries: 18
- Evidence rerun attempts: 51
- Promotion-ready shadow reruns: 0
- Evidence bundle rerun attempts: 18
- Promotion-ready bundle reruns: 2
- Guarded bundle promotions: 2
- Rule graph nodes / edges: 568 / 2194
- Proof DAG sidecar entries: 144
- Cache hits / misses: 0 / 144
- Semantic high-similarity review items: 5
- Review items potentially promotable after evidence fix: 2
- Safe verifier tuning candidates: 0
- Felt verified-rule CSV rows: 84

## Review Actions

- `retry_with_better_evidence`: 49
- `human_legal_review`: 3
- `evidence_packet_repair_candidate`: 2
- `needs_second_source_consensus`: 2
- `defer_low_priority`: 1

## Top Review / Rejection Reasons

- `text_candidate_requires_review`: 55
- `upstream_extraction_requested_review`: 19
- `operator_not_supported`: 19
- `rule_object_not_supported`: 18
- `rule_family_direction_mismatch`: 16
- `applies_to_not_supported`: 14
- `constraint_scope_not_supported`: 11
- `range_bound_not_maximum`: 10
- `text_condition_not_supported`: 6
- `extraction_source_fidelity_hold`: 4
