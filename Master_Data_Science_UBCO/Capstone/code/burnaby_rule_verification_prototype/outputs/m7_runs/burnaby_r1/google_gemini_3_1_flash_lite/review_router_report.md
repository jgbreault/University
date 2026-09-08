# Review Router

This file consolidates triage, evidence repair, and audit into one review queue. It does not verify rules.

## Summary

- Review rules: 57

### Action Buckets

- `operator_review`: 31
- `fix_candidate_or_rule_family_mapping`: 9
- `condition_evidence_needed`: 6
- `semantic_guardrail_review`: 4
- `scope_review`: 2
- `defer_low_priority`: 2
- `rerun_with_evidence_bundle`: 2
- `human_legal_review`: 1

### Likelihood

- `plausible`: 21
- `likely_correct`: 14
- `weak`: 12
- `likely_wrong_or_noise`: 10

### Top Support Gaps

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
- `unresolved_exception_cue`: 3

### Recommendations

- Keep 4 close semantic matches blocked until their guardrail mismatch is resolved.
- Keep 1 exception/conflict rules in human legal review.

## Top 25 Review Routes

- `burnaby_r1_092` -> `human_legal_review` / `high`: Resolve exception/covenant/notwithstanding wording manually. Check unresolved_exception_cue in page 2; evidence_id burnaby_r1_matrix_p2_t0_b0_064. Semantic match: burnaby_r1_077 (score 0.59, blockers different_numeric_value, exception_or_override_unresolved).
- `burnaby_r1_006` -> `condition_evidence_needed` / `high`: Find the clause or table header that proves the condition. Check text_candidate_requires_review, text_condition_not_supported in page 6; section 101(1); evidence_id m4_pack_0006_ev_002. Suggested stronger evidence: m4_pack_0006_ev_001. Semantic match: burnaby_r1_041 (score 0.71, blockers exception_or_override_unresolved).
- `burnaby_r1_007` -> `condition_evidence_needed` / `high`: Find the clause or table header that proves the condition. Check text_candidate_requires_review, text_condition_not_supported in page 6; section 101(1); evidence_id m4_pack_0006_ev_003. Suggested stronger evidence: m4_pack_0006_ev_001. Semantic match: burnaby_r1_093 (score 0.71, blockers different_numeric_value).
- `burnaby_r1_119` -> `condition_evidence_needed` / `high`: Find the clause or table header that proves the condition. Check text_candidate_requires_review, text_condition_not_supported in page 6; section 101(1); evidence_id v3_repair_pack_0005_ev_002. Suggested stronger evidence: m4_pack_0006_ev_001. Semantic match: burnaby_r1_041 (score 0.71, blockers exception_or_override_unresolved).
- `burnaby_r1_120` -> `condition_evidence_needed` / `high`: Find the clause or table header that proves the condition. Check text_candidate_requires_review, text_condition_not_supported in page 6; section 101(1); evidence_id v3_repair_pack_0005_ev_003. Suggested stronger evidence: m4_pack_0006_ev_001. Semantic match: burnaby_r1_093 (score 0.71, blockers different_numeric_value).
- `burnaby_r1_005` -> `condition_evidence_needed` / `high`: Find the clause or table header that proves the condition. Check text_candidate_requires_review, text_condition_not_supported in page 6; section 101(1); evidence_id m4_pack_0006_ev_001. Suggested stronger evidence: v3_repair_pack_0005_ev_001. Semantic match: burnaby_r1_036 (score 0.71, blockers different_numeric_value, exception_or_override_unresolved).
- `burnaby_r1_118` -> `condition_evidence_needed` / `high`: Find the clause or table header that proves the condition. Check text_candidate_requires_review, text_condition_not_supported in page 6; section 101(1); evidence_id v3_repair_pack_0005_ev_001. Suggested stronger evidence: m4_pack_0006_ev_001. Semantic match: burnaby_r1_036 (score 0.71, blockers different_numeric_value, exception_or_override_unresolved).
- `burnaby_r1_018` -> `scope_review` / `high`: Check row/column/header/prose context for the correct legal scope. Check text_candidate_requires_review, applies_to_not_supported, unresolved_exception_cue in page 5; section 101(2); evidence_id m4_pack_0021_ev_001. Suggested stronger evidence: m4_pack_0008_ev_001. Semantic match: burnaby_r1_046 (score 0.71, blockers different_numeric_value, exception_or_override_unresolved).
- `burnaby_r1_141` -> `scope_review` / `high`: Check row/column/header/prose context for the correct legal scope. Check text_candidate_requires_review, applies_to_not_supported, unresolved_exception_cue in page 5; section 101(2); evidence_id v3_repair_pack_0013_ev_001. Suggested stronger evidence: m4_pack_0008_ev_001. Semantic match: burnaby_r1_046 (score 0.71, blockers different_numeric_value, exception_or_override_unresolved).
- `burnaby_r1_035` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check rule_family_direction_mismatch in page 2; evidence_id burnaby_r1_matrix_p2_t0_b0_007. Semantic match: burnaby_r1_001 (score 0.60, blockers different_direction, different_numeric_value).
- `burnaby_r1_028` -> `semantic_guardrail_review` / `medium`: Compare the close verified match, but do not relax verification because core legal fields or guardrails disagree. Check text_candidate_requires_review in page 4; section 101(1); evidence_id m4_pack_0058_ev_001. Semantic match: burnaby_r1_001 (score 0.71, blockers different_numeric_value).
- `burnaby_r1_144` -> `semantic_guardrail_review` / `medium`: Compare the close verified match, but do not relax verification because core legal fields or guardrails disagree. Check text_candidate_requires_review in page 4; section 101(1); evidence_id v3_repair_pack_0016_ev_001. Semantic match: burnaby_r1_001 (score 0.71, blockers different_numeric_value).
- `burnaby_r1_020` -> `semantic_guardrail_review` / `medium`: Compare the close verified match, but do not relax verification because core legal fields or guardrails disagree. Check text_candidate_requires_review in page 5; section 101(1); evidence_id m4_pack_0025_ev_002. Suggested stronger evidence: m4_pack_0025_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: burnaby_r1_096 (score 0.71, blockers different_numeric_value).
- `burnaby_r1_138` -> `semantic_guardrail_review` / `medium`: Compare the close verified match, but do not relax verification because core legal fields or guardrails disagree. Check text_candidate_requires_review in page 5; section 101(1); evidence_id v3_repair_pack_0012_ev_002. Suggested stronger evidence: m4_pack_0025_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: burnaby_r1_096 (score 0.71, blockers different_numeric_value).
- `burnaby_r1_008` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, text_candidate_requires_review, range_bound_not_maximum in page 5; section 101(1); evidence_id m4_pack_0008_ev_001. Suggested stronger evidence: m4_pack_0008_ev_002. Semantic match: burnaby_r1_011 (score 0.70, blockers different_numeric_value).
- `burnaby_r1_009` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, text_candidate_requires_review in page 5; section 101(1); evidence_id m4_pack_0008_ev_002. Suggested stronger evidence: m4_pack_0008_ev_001. Semantic match: burnaby_r1_011 (score 0.90, blockers none).
- `burnaby_r1_112` -> `defer_low_priority` / `medium`: Keep in review until more evidence or a general verifier rule is justified. Check text_candidate_requires_review in page 1; section 101.2; evidence_id m4_pack_0045_v3_clause_ev_003. Suggested stronger evidence: m4_pack_0045_v3_clause_ev_002. Semantic match: burnaby_r1_099 (score 0.02, blockers different_direction, different_rule_object, different_unit).
- `burnaby_r1_002` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 1; section 101.3; evidence_id m4_pack_0002_ev_002. Suggested stronger evidence: m4_pack_0002_ev_001. Semantic match: burnaby_r1_001 (score 0.63, blockers different_direction, different_numeric_value).
- `burnaby_r1_114` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 1; section 101.3; evidence_id v3_repair_pack_0001_ev_002. Suggested stronger evidence: m4_pack_0002_ev_001. Semantic match: burnaby_r1_113 (score 0.67, blockers different_direction, different_numeric_value).
- `burnaby_r1_122` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, text_candidate_requires_review, range_bound_not_maximum in page 5; section 101(1); evidence_id v3_repair_pack_0007_ev_001. Suggested stronger evidence: m4_pack_0008_ev_001. Semantic match: burnaby_r1_011 (score 0.70, blockers different_numeric_value).
- `burnaby_r1_123` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, text_candidate_requires_review in page 5; section 101(1); evidence_id v3_repair_pack_0007_ev_002. Suggested stronger evidence: m4_pack_0008_ev_001. Semantic match: burnaby_r1_011 (score 0.90, blockers none).
- `burnaby_r1_026` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 5; section 101(2); evidence_id m4_pack_0044_ev_001. Suggested stronger evidence: m4_pack_0025_ev_003. Semantic match: burnaby_r1_084 (score 0.54, blockers different_direction, different_numeric_value).
- `burnaby_r1_142` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 5; section 101(2); evidence_id v3_repair_pack_0014_ev_001. Suggested stronger evidence: m4_pack_0025_ev_003. Semantic match: burnaby_r1_084 (score 0.54, blockers different_direction, different_numeric_value).
- `burnaby_r1_111` -> `defer_low_priority` / `medium`: Keep in review until more evidence or a general verifier rule is justified. Check text_candidate_requires_review in page 1; section 101.2; evidence_id m4_pack_0045_v3_clause_ev_002. Suggested stronger evidence: m4_pack_0045_v3_clause_ev_003. Semantic match: burnaby_r1_033 (score 0.05, blockers different_direction, different_rule_object, different_unit).
- `burnaby_r1_115` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch, constraint_scope_not_supported in page 1; evidence_id v3_repair_pack_0003_ev_001. Suggested stronger evidence: m4_pack_0002_ev_001. Semantic match: burnaby_r1_001 (score 0.60, blockers different_direction, different_numeric_value).
