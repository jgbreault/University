# Review Router

This file consolidates triage, evidence repair, and audit into one review queue. It does not verify rules.

## Summary

- Review rules: 42

### Action Buckets

- `operator_review`: 19
- `fix_candidate_or_rule_family_mapping`: 11
- `rerun_with_evidence_bundle`: 5
- `scope_review`: 4
- `human_legal_review`: 2
- `semantic_guardrail_review`: 1

### Likelihood

- `plausible`: 16
- `likely_correct`: 11
- `weak`: 8
- `likely_wrong_or_noise`: 7

### Top Support Gaps

- `text_candidate_requires_review`: 35
- `upstream_extraction_requested_review`: 23
- `extraction_source_fidelity_hold`: 18
- `operator_not_supported`: 14
- `rule_object_not_supported`: 13
- `applies_to_not_supported`: 11
- `enumerated_branch_condition_missing`: 6
- `rule_family_direction_mismatch`: 5
- `constraint_scope_not_supported`: 5
- `coefficient_operand_not_value`: 4
- `unresolved_exception_cue`: 2
- `text_condition_not_supported`: 2

### Recommendations

- Keep 1 close semantic matches blocked until their guardrail mismatch is resolved.
- Keep 2 exception/conflict rules in human legal review.

## Top 25 Review Routes

- `calgary_rcg_023` -> `human_legal_review` / `high`: Resolve exception/covenant/notwithstanding wording manually. Check unresolved_exception_cue in page 396; section 352(5); evidence_id m4_pack_0021_ev_002. Semantic match: calgary_rcg_083 (score 0.70, blockers different_numeric_value, exception_or_override_unresolved).
- `calgary_rcg_122` -> `human_legal_review` / `high`: Resolve exception/covenant/notwithstanding wording manually. Check unresolved_exception_cue in page 396; section 352(5); evidence_id v3_repair_pack_0012_ev_002. Semantic match: calgary_rcg_083 (score 0.70, blockers different_numeric_value, exception_or_override_unresolved).
- `calgary_rcg_016` -> `operator_review` / `high`: Confirm the legal direction: maximum/minimum/required/permitted. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, text_condition_not_supported in page 397; section 352(8); evidence_id m4_pack_0015_ev_001. Suggested stronger evidence: m4_pack_0015_ev_002. Semantic match: calgary_rcg_004 (score 0.60, blockers different_direction, different_numeric_value).
- `calgary_rcg_091` -> `operator_review` / `high`: Confirm the legal direction: maximum/minimum/required/permitted. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, text_condition_not_supported in page 397; section 352(8); evidence_id v3_repair_pack_0003_ev_001. Suggested stronger evidence: m4_pack_0015_ev_002. Semantic match: calgary_rcg_004 (score 0.60, blockers different_direction, different_numeric_value).
- `calgary_rcg_002` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, extraction_source_fidelity_hold in page 396; section 352(4.1); evidence_id m4_pack_0001_ev_002. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_012 (score 0.71, blockers different_numeric_value).
- `calgary_rcg_071` -> `rerun_with_evidence_bundle` / `medium`: Rerun using the evidence bundle; promote only if deterministic verifier passes. Check text_candidate_requires_review, enumerated_branch_condition_missing in page 471; section 539(2); evidence_id m4_pack_0069_ev_001. Suggested stronger evidence: m4_pack_0003_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_013 (score 0.97, blockers none).
- `calgary_rcg_086` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, extraction_source_fidelity_hold in page 396; section 352(4.1); evidence_id v3_repair_pack_0001_ev_002. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_012 (score 0.71, blockers different_numeric_value).
- `calgary_rcg_136` -> `rerun_with_evidence_bundle` / `medium`: Rerun using the evidence bundle; promote only if deterministic verifier passes. Check text_candidate_requires_review, enumerated_branch_condition_missing in page 471; section 539(2); evidence_id v3_repair_pack_0023_ev_001. Suggested stronger evidence: m4_pack_0003_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_013 (score 0.97, blockers none).
- `calgary_rcg_017` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, enumerated_branch_condition_missing in page 397; section 352(8); evidence_id m4_pack_0015_ev_002. Suggested stronger evidence: m4_pack_0015_ev_003. Semantic match: calgary_rcg_079 (score 0.56, blockers different_direction, different_numeric_value).
- `calgary_rcg_045` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, extraction_source_fidelity_hold in page 472; section 541(2); evidence_id m4_pack_0042_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_012 (score 0.71, blockers different_numeric_value).
- `calgary_rcg_092` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, enumerated_branch_condition_missing in page 397; section 352(8); evidence_id v3_repair_pack_0003_ev_002. Suggested stronger evidence: m4_pack_0015_ev_002. Semantic match: calgary_rcg_079 (score 0.56, blockers different_direction, different_numeric_value).
- `calgary_rcg_080` -> `semantic_guardrail_review` / `medium`: Compare the close verified match, but do not relax verification because core legal fields or guardrails disagree. Check text_candidate_requires_review, enumerated_branch_condition_missing in page 396; section 352(3.2); evidence_id m4_pack_0006_v3_clause_ev_002. Suggested stronger evidence: m4_pack_0001_v3_clause_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_020 (score 0.71, blockers different_numeric_value).
- `calgary_rcg_029` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 398; section 358(1); evidence_id m4_pack_0031_ev_001. Suggested stronger evidence: m4_pack_0015_ev_002. Semantic match: calgary_rcg_012 (score 0.54, blockers different_direction, different_numeric_value).
- `calgary_rcg_001` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, extraction_source_fidelity_hold in page 396; section 352(4.1); evidence_id m4_pack_0001_ev_001. Semantic match: calgary_rcg_079 (score 1.00, blockers none).
- `calgary_rcg_085` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, extraction_source_fidelity_hold in page 396; section 352(4.1); evidence_id v3_repair_pack_0001_ev_001. Semantic match: calgary_rcg_079 (score 1.00, blockers none).
- `calgary_rcg_022` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check text_candidate_requires_review, applies_to_not_supported in page 396; section 352(5); evidence_id m4_pack_0021_ev_001. Suggested stronger evidence: m4_pack_0001_ev_001. Semantic match: calgary_rcg_083 (score 0.71, blockers different_numeric_value, exception_or_override_unresolved).
- `calgary_rcg_121` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check text_candidate_requires_review, applies_to_not_supported in page 396; section 352(5); evidence_id v3_repair_pack_0012_ev_001. Suggested stronger evidence: m4_pack_0001_ev_001. Semantic match: calgary_rcg_083 (score 0.71, blockers different_numeric_value, exception_or_override_unresolved).
- `calgary_rcg_003` -> `rerun_with_evidence_bundle` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, applies_to_not_supported in page 396; section 352(4.1); evidence_id m4_pack_0001_ev_003. Suggested stronger evidence: m4_pack_0001_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_012 (score 0.97, blockers none).
- `calgary_rcg_087` -> `rerun_with_evidence_bundle` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, applies_to_not_supported in page 396; section 352(4.1); evidence_id v3_repair_pack_0001_ev_003. Suggested stronger evidence: m4_pack_0001_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_012 (score 0.97, blockers none).
- `calgary_rcg_119` -> `rerun_with_evidence_bundle` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, enumerated_branch_condition_missing in page 472; section 541(2); evidence_id v3_repair_pack_0011_ev_001. Suggested stronger evidence: m4_pack_0042_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_012 (score 0.71, blockers different_numeric_value).
- `calgary_rcg_018` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, applies_to_not_supported in page 397; section 352(8); evidence_id m4_pack_0015_ev_003. Suggested stronger evidence: m4_pack_0015_ev_002. Semantic match: calgary_rcg_012 (score 0.71, blockers different_numeric_value).
- `calgary_rcg_093` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, applies_to_not_supported in page 397; section 352(8); evidence_id v3_repair_pack_0003_ev_003. Suggested stronger evidence: m4_pack_0015_ev_002. Semantic match: calgary_rcg_012 (score 0.71, blockers different_numeric_value).
- `calgary_rcg_070` -> `operator_review` / `low`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, operator_not_supported, allowance_trigger_threshold in page 471; section 539(4); evidence_id m4_pack_0068_ev_001. Suggested stronger evidence: m4_pack_0070_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_006 (score 0.71, blockers different_numeric_value, missing_core_evidence).
- `calgary_rcg_011` -> `fix_candidate_or_rule_family_mapping` / `low`: Check whether extraction chose the wrong rule family. Check text_candidate_requires_review, rule_object_not_supported in page 398; section 358(3); evidence_id m4_pack_0007_ev_001. Suggested stronger evidence: v3_repair_pack_0008_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_004 (score 0.90, blockers none).
- `calgary_rcg_046` -> `fix_candidate_or_rule_family_mapping` / `low`: Check whether extraction chose the wrong rule family. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, rule_object_not_supported in page 472; section 541(2); evidence_id m4_pack_0042_ev_002. Suggested stronger evidence: m4_pack_0042_ev_001. Evidence bundle is safe to rerun through the verifier. Semantic match: calgary_rcg_055 (score 0.90, blockers none).
