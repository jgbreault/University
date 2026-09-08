# Review Router

This file consolidates triage, evidence repair, and audit into one review queue. It does not verify rules.

## Summary

- Review rules: 31

### Action Buckets

- `operator_review`: 19
- `fix_candidate_or_rule_family_mapping`: 6
- `scope_review`: 4
- `defer_low_priority`: 2

### Likelihood

- `likely_correct`: 12
- `plausible`: 12
- `likely_wrong_or_noise`: 5
- `weak`: 2

### Top Support Gaps

- `text_candidate_requires_review`: 27
- `upstream_extraction_requested_review`: 13
- `rule_object_not_supported`: 13
- `rule_family_direction_mismatch`: 12
- `extraction_source_fidelity_hold`: 12
- `operator_not_supported`: 7
- `applies_to_not_supported`: 6
- `constraint_scope_not_supported`: 5
- `coefficient_operand_not_value`: 2

### Recommendations

- No immediate recommendation.

## Top 25 Review Routes

- `vancouver_rs_019` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 4; section 11.3.1.2; evidence_id m4_pack_0010_ev_001. Suggested stronger evidence: v3_repair_pack_0013_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value, exception_or_override_unresolved).
- `vancouver_rs_048` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 4; section 11.3.1.2; evidence_id v3_repair_pack_0013_ev_001. Suggested stronger evidence: m4_pack_0010_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value, exception_or_override_unresolved).
- `vancouver_rs_008` -> `defer_low_priority` / `medium`: Keep in review until more evidence or a general verifier rule is justified. Check coefficient_operand_not_value in page 8; section 11.3.8.2; evidence_id m4_pack_0004_ev_001. Semantic match: vancouver_rs_027 (score 0.65, blockers different_numeric_value, different_unit).
- `vancouver_rs_009` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, extraction_source_fidelity_hold in page 8; section 11.3.8.2; evidence_id m4_pack_0004_ev_002. Semantic match: vancouver_rs_027 (score 0.97, blockers none).
- `vancouver_rs_037` -> `defer_low_priority` / `medium`: Keep in review until more evidence or a general verifier rule is justified. Check coefficient_operand_not_value in page 8; section 11.3.8.2; evidence_id v3_repair_pack_0003_ev_001. Semantic match: vancouver_rs_027 (score 0.65, blockers different_numeric_value, different_unit).
- `vancouver_rs_038` -> `fix_candidate_or_rule_family_mapping` / `medium`: Extraction flagged this candidate for review; investigate and correct it upstream before rerun. Check upstream_extraction_requested_review, extraction_source_fidelity_hold in page 8; section 11.3.8.2; evidence_id v3_repair_pack_0003_ev_002. Semantic match: vancouver_rs_027 (score 0.97, blockers none).
- `vancouver_rs_017` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 7; section 11.3.6.6; evidence_id m4_pack_0009_ev_001. Suggested stronger evidence: m4_pack_0010_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_046` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 7; section 11.3.6.6; evidence_id v3_repair_pack_0010_ev_001. Suggested stronger evidence: m4_pack_0010_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_025` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, rule_family_direction_mismatch in page 11; section 11.4.4.3; evidence_id m4_pack_0051_ev_003. Suggested stronger evidence: m4_pack_0051_ev_001. Semantic match: vancouver_rs_006 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_053` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, rule_family_direction_mismatch in page 11; section 11.4.4.3; evidence_id v3_repair_pack_0016_ev_003. Suggested stronger evidence: m4_pack_0051_ev_001. Semantic match: vancouver_rs_006 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_021` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 5; section 11.3.2.2; evidence_id m4_pack_0015_ev_001. Suggested stronger evidence: v3_repair_pack_0014_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_049` -> `operator_review` / `medium`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch in page 5; section 11.3.2.2; evidence_id v3_repair_pack_0014_ev_001. Suggested stronger evidence: m4_pack_0015_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_022` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, constraint_scope_not_supported in page 11; section 11.4.3.2; evidence_id m4_pack_0050_ev_001. Suggested stronger evidence: v3_repair_pack_0015_ev_001. Semantic match: vancouver_rs_029 (score 0.62, blockers different_numeric_value).
- `vancouver_rs_050` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, constraint_scope_not_supported in page 11; section 11.4.3.2; evidence_id v3_repair_pack_0015_ev_001. Suggested stronger evidence: m4_pack_0050_ev_001. Semantic match: vancouver_rs_029 (score 0.62, blockers different_numeric_value).
- `vancouver_rs_023` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, constraint_scope_not_supported in page 11; section 11.4.4.3; evidence_id m4_pack_0051_ev_001. Suggested stronger evidence: m4_pack_0051_ev_002. Semantic match: vancouver_rs_029 (score 0.62, blockers different_numeric_value).
- `vancouver_rs_051` -> `scope_review` / `medium`: Check row/column/header/prose context for the correct legal scope. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, constraint_scope_not_supported in page 11; section 11.4.4.3; evidence_id v3_repair_pack_0016_ev_001. Suggested stronger evidence: m4_pack_0051_ev_001. Semantic match: vancouver_rs_029 (score 0.62, blockers different_numeric_value).
- `vancouver_rs_013` -> `fix_candidate_or_rule_family_mapping` / `low`: Check whether extraction chose the wrong rule family. Check text_candidate_requires_review, rule_object_not_supported in page 8; section 11.3.8.6; evidence_id m4_pack_0007_ev_001. Semantic match: vancouver_rs_028 (score 0.97, blockers none).
- `vancouver_rs_039` -> `fix_candidate_or_rule_family_mapping` / `low`: Check whether extraction chose the wrong rule family. Check text_candidate_requires_review, rule_object_not_supported in page 8; section 11.3.8.6; evidence_id v3_repair_pack_0004_ev_001. Semantic match: vancouver_rs_028 (score 0.97, blockers none).
- `vancouver_rs_004` -> `operator_review` / `low`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch, rule_object_not_supported in page 8; section 11.3.8.7; evidence_id m4_pack_0002_ev_001. Semantic match: vancouver_rs_027 (score 0.57, blockers different_direction, different_numeric_value).
- `vancouver_rs_005` -> `operator_review` / `low`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch, rule_object_not_supported in page 8; section 11.3.8.7; evidence_id m4_pack_0002_ev_002. Suggested stronger evidence: m4_pack_0004_ev_001. Semantic match: vancouver_rs_027 (score 0.59, blockers different_direction, different_numeric_value).
- `vancouver_rs_032` -> `operator_review` / `low`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch, rule_object_not_supported in page 8; section 11.3.8.7; evidence_id v3_repair_pack_0001_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_033` -> `operator_review` / `low`: Confirm the legal direction: maximum/minimum/required/permitted. Check text_candidate_requires_review, rule_family_direction_mismatch, rule_object_not_supported in page 8; section 11.3.8.7; evidence_id v3_repair_pack_0001_ev_002. Suggested stronger evidence: m4_pack_0004_ev_001. Semantic match: vancouver_rs_027 (score 0.54, blockers different_direction, different_numeric_value).
- `vancouver_rs_026` -> `fix_candidate_or_rule_family_mapping` / `low`: Check whether extraction chose the wrong rule family. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, rule_object_not_supported in page 12; section 11.6.1.1; evidence_id m4_pack_0061_ev_001. Semantic match: vancouver_rs_027 (score 0.26, blockers different_direction, different_numeric_value, different_rule_object).
- `vancouver_rs_054` -> `fix_candidate_or_rule_family_mapping` / `low`: Check whether extraction chose the wrong rule family. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, rule_object_not_supported in page 12; section 11.6.1.1; evidence_id v3_repair_pack_0017_ev_001. Semantic match: vancouver_rs_027 (score 0.26, blockers different_direction, different_numeric_value, different_rule_object).
- `vancouver_rs_024` -> `operator_review` / `low`: Confirm the legal direction: maximum/minimum/required/permitted. Check upstream_extraction_requested_review, extraction_source_fidelity_hold, text_candidate_requires_review, applies_to_not_supported in page 11; section 11.4.4.3; evidence_id m4_pack_0051_ev_002. Suggested stronger evidence: m4_pack_0051_ev_001. Semantic match: vancouver_rs_029 (score 0.68, blockers different_numeric_value, missing_core_evidence).
