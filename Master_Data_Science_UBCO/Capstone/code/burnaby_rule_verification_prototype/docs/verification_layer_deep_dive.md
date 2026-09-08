# Verification Layer Deep Dive

This document explains the verification layer at code level: what each file
does, which functions matter, and how a candidate rule moves from Zihao's
Pipeline 5 output into `verified_rules.json`, `review_needed.json`, or
`rejected_rules.json`.

Line numbers below refer to the current source version. If a future edit moves
code around, search for the function name first and then use the explanation
here as the map.

## One Sentence Summary

The verification layer is a deterministic trust gate:

```text
candidate rule + cited evidence -> field checks -> support_gaps -> decision
```

The important safety rule is:

```text
No support gaps = verified
Critical support gaps = rejected
Non-critical uncertainty = review_needed
```

Confidence, extraction labels, and Bayesian-lite scores never verify a rule.
They can only explain or rank decisions after the deterministic checks have
already run.

## File Map

| File | Role | Important Lines |
| --- | --- | --- |
| `scripts/run_slim_verifier.py` | Command-line entry point. Loads config and Zihao input, then calls the slim pipeline. | 88-151 |
| `src/burnaby_prototype/zihao_adapter.py` | Converts Pipeline 5 or Pipeline 3 output into the verifier's standard `candidate` and `evidence` contract. It translates but does not verify. | 41-86, 89-110, 113-220 |
| `src/burnaby_prototype/evidence_contract.py` | Scores evidence packet quality for diagnostics. It does not decide verification. | 19-66, 69-114 |
| `src/burnaby_prototype/slim_pipeline.py` | Orchestrates the run, writes output JSON files, splits review vs rejected, and exports only verified rules to GIS. | 20-100, 103-117 |
| `src/burnaby_prototype/verification.py` | Main deterministic verifier and source of truth for verified/review/rejected decisions. | 36-211, 326-387, 390-510, 587-775, 778-1016, 1266-1593 |
| `src/burnaby_prototype/table_natural_logic.py` | TabVer-lite proof layer for table evidence using table title, row header, column header, and cell value. | 47-100, 103-128, 131-232 |
| `src/burnaby_prototype/rule_claims.py` | Builds proof objects, merges text/table proof traces, computes evidence strength, and assigns review priority. | 32-47, 70-121, 124-246 |
| `src/burnaby_prototype/consensus.py` | Reports cross-source consensus/conflicts and provides source agreement used to gate text auto-verification. It never overrides deterministic gaps. | 1-15, 55-87, 90-157 |
| `src/burnaby_prototype/compliance.py` | Checks proposal cases against the GIS contract with `approved`, `rejected`, or `needs_review`. | 38-119, 133-229 |
| `benchmark/evaluate_benchmark.py` | Scores outputs against gold rules and proposal cases. Enforces safety gates. | 67-107, 119-227, 264-380 |
| `benchmark/evaluate_adversarial.py` | Feeds poisoned candidate/evidence pairs into the real verifier and confirms none are verified. | 37-90 |

## End-to-End Flow

The active demo path is:

```text
Pipeline 5 final_rule_registry.json
  -> zihao_adapter.py
  -> slim_pipeline.py
  -> verification.py
  -> verified / review_needed / rejected
  -> gis_rule_contract.json
  -> benchmark evaluator and compliance checker
```

### 1. Entry Point

`scripts/run_slim_verifier.py`

Lines 88-127 define the CLI arguments:

- `--city` chooses the city/zone key, defaulting to `burnaby_r1`.
- `--config` can override the config file.
- `--input-mode` chooses Pipeline 5 registry input or older Zihao handoff input.
- `--output-dir` controls where artifacts are written.
- `--pipeline5-registry` points to Zihao's `final_rule_registry.json`.

Lines 130-151 are the executable flow:

1. Resolve city paths.
2. Choose config and output directory.
3. Load candidate/evidence input with `_load_candidate_set`.
4. Call `run_slim_verification`.
5. Print counts for evidence units, candidates, verified rules, review rules,
   and rejected rules.

Lines 154-166 choose the adapter:

- Pipeline 5 goes through `adapt_pipeline5_registry`.
- Older Zihao handoff JSON goes through `adapt_zihao_outputs`.

The entry point does not verify rules. It only wires the input to the pipeline.

### 2. Adapter

`src/burnaby_prototype/zihao_adapter.py`

The adapter's purpose is stated in lines 1-13: it is a translator, not a
verifier. This distinction matters because Pipeline 5 may say a rule is
accepted, but the verifier still has to prove it from evidence.

Lines 21-38 define `RULE_OBJECT_ALIASES`. These map upstream names like
`building_height`, `impervious_surfaces`, or `permitted_dwelling_units` into the
canonical rule objects used downstream.

Lines 41-73 implement `adapt_zihao_outputs` for older handoff-style inputs:

1. Normalize evidence units.
2. Build an evidence lookup by `evidence_id`.
3. Create fallback evidence when a rule cites evidence that is not present in
   the evidence file.
4. Adapt each rule into a standard candidate.
5. Dedupe evidence and candidate records.

Lines 76-86 implement `adapt_pipeline5_registry`, the active path. Pipeline 5
uses one top-level registry file with a `rules` array, so this function turns
each registry row into the common adapter record shape and then reuses
`adapt_zihao_outputs`.

Lines 89-110 implement `_pipeline5_rule_to_record`:

- `candidate_id` and `evidence_id` are both derived from the merged Pipeline 5
  rule ID.
- `source_evidence_text` and `source_context` are set from Pipeline 5 evidence.
- `page` is parsed from Pipeline 5 metadata when needed.
- `evidence_type` is `table_cell` only for `gemini_table_image`; otherwise it is
  a plain clause.
- `extraction_final_action` is preserved as audit metadata.
- Table-image evidence gets `table_title`, `row_header`, `column_header`, and
  `cell_value` recovered.

Lines 113-151 implement `_adapt_evidence_unit`. This creates the standard
evidence packet fields expected by `verification.py`:

```text
evidence_id
page
evidence_type
evidence_text
source_context
table_title
row_header
column_header
cell_value
bbox
table_parser
```

Lines 182-220 implement `_adapt_candidate`. This creates the standard candidate
contract:

```text
candidate_id
evidence_id
rule_object
constraint_type
constraint_scope
applies_to
operator
value
unit
condition
exception
gis_relevance
source_stream
rule_key
extraction metadata
```

The comment at lines 206-208 is the adapter's key safety rule: Zihao's metadata
is preserved for audit, but it cannot verify a rule.

### 3. Evidence Quality

`src/burnaby_prototype/evidence_contract.py`

Evidence quality is diagnostic, not a decision gate.

Lines 14-16 define the expected evidence packet fields:

- Every evidence unit needs `evidence_id` and `evidence_text`.
- Table evidence should also have `table_title`, `row_header`,
  `column_header`, and `cell_value`.

Lines 19-32 implement `annotate_evidence_quality`. It adds:

```text
evidence_quality_score
evidence_quality_issues
```

Lines 35-66 implement `evidence_quality`:

- Missing `evidence_id`, `evidence_text`, or `page` becomes a quality issue.
- Table evidence missing row/column/cell context gets
  `incomplete_table_context`.
- Missing table bounding boxes are tracked as `missing_bbox`.
- Evidence text not found in source context is a warning.

Lines 69-114 implement `evidence_quality_summary`, which computes run-level
diagnostics:

```text
candidate_evidence_match_rate
candidate_value_grounding_rate
candidate_unit_grounding_rate
table_context_completion_rate
top_evidence_quality_issues
```

These metrics help explain why rules go to review or rejection, but they do not
promote a rule to verified.

### 4. Slim Pipeline

`src/burnaby_prototype/slim_pipeline.py`

This file coordinates the run after input is adapted.

Lines 20-100 implement `run_slim_verification`:

1. Load config.
2. Annotate evidence quality.
3. Call `verify_candidates`.
4. Split the non-verified rules into `review_needed.json` and
   `rejected_rules.json`.
5. Write all output files.
6. Write consensus and conflict reports.
7. Export the GIS contract with verified rules only.
8. Write summary and diagram files.

Lines 43-48 show the trust boundary:

```python
verification = verify_candidates(config, {}, evidence_units, rule_candidates)
verified_rules = verification["verified_rules"]
review_rules, rejected_rules = _split_review_and_rejected(verification["review_needed"])
```

`verify_candidates` returns verified rules plus one combined non-verified list.
The slim pipeline then separates that non-verified list by the rule's
`verification_decision`.

Lines 75-85 are the GIS safety guarantee. The contract is built with:

```python
"rules": verified_rules
```

Review and rejected rules are kept for audit, but they are excluded from
`gis_rule_contract.json`.

Lines 103-117 implement `_split_review_and_rejected`. This is simple policy:

- `verification_decision == "rejected"` goes to `rejected_rules.json`.
- Everything else non-verified goes to `review_needed.json`.

### 5. Verification Constants

`src/burnaby_prototype/verification.py`

This is the core verifier.

Lines 36-44 define `UNIT_ALIASES`. This lets evidence support normal unit
variants:

```text
m      -> m, metre, meter, metres, meters
m2     -> m2, m 2, m2 variants, square metre/meter
%      -> %, percent, percentage
storeys -> storey/storeys/story/stories
units  -> unit/units/dwelling unit/dwelling units
```

Lines 46-59 define `RULE_OBJECT_ALLOWED_UNITS`. This catches unsafe pairings:

```text
height                 must use m
setback                must use m
building_separation    must use m
lot_area               must use m2
lot_coverage           must use %
impervious_surface     must use %
storeys                must use storeys
dwelling_units         must use units
```

This is why a candidate like `height = 60%` should be rejected even if the text
contains both `60` and `%`.

Lines 65-83 define canonical rule-object names. The verifier only understands
known objects such as:

```text
height
storeys
lot_coverage
impervious_surface
lot_area
dwelling_units
setback
building_separation
automatic_sprinkler
fire_access_corridor
permitted_use
```

Lines 85-103 define the supported operator vocabulary:

```text
<=, >=, >, <, =, allowed, permitted, required, range, max, min, not_exceed, at_least
```

Lines 147-165 define deterministic text patterns for recognizing rule families
from evidence wording. Example:

- Evidence with `yard` can support `setback`.
- Evidence with `separation` can support `building_separation`.
- Evidence with `fire access corridor` can support `fire_access_corridor`.

Lines 167-200 define the gap vocabulary.

`TABLE_REVIEW_GAPS` at lines 170-174 are conservative table gates. They route
some table candidates to review when table proof is not strong enough.

`MISSING_SCOPE_GAPS` at lines 175-186 are review-style gaps. These usually mean
the candidate is plausible but not fully grounded.

`CRITICAL_REJECTION_GAPS` at lines 190-200 are hard safety failures. Examples:

```text
source_evidence_id_not_found
value_not_found_in_evidence
unit_not_found_in_evidence
rule_object_not_supported
rule_object_unit_not_compatible
table_operator_refuted
non_numeric_value_for_numeric_rule
```

Lines 202-211 define `CLAIM_TO_SUPPORT_GAP`, the bridge between proof traces and
support gaps. If the proof trace says `value` is supported, it can repair only
the value gap. It cannot repair rule object, scope, or anything unrelated.

### 6. Candidate Normalization

`src/burnaby_prototype/verification.py`

Lines 326-362 implement `_canonical_rule_object`.

This function maps extracted wording into canonical rule families using three
levels:

1. Direct aliases such as `building_height -> height`.
2. Plain text patterns such as `yard -> setback`.
3. Candidate/evidence context when the raw rule object is vague.

Special handling:

- A vague "between ..." phrase becomes `building_separation`.
- Storey/height ambiguity is resolved using unit and context.
- If context contains height wording, the rule object can become `height`.

Lines 365-376 implement `_canonical_constraint_type`, which normalizes min/max
wording into broader constraint types:

```text
<= or maximum -> maximum
>= or minimum -> minimum
allowed/permitted -> allowed
required -> required
```

Lines 379-387 implement `_normalize_candidate`. It copies the candidate,
canonicalizes rule object and constraint type, then calls
`_refine_normalized_candidate`.

Lines 390-510 implement `_refine_normalized_candidate`, the largest
normalization helper. It does deterministic cleanup where the legal meaning is
stable:

- Lines 405-434: For dwelling-unit ranges such as `5 to 6 Units`, convert the
  range to the GIS-useful upper bound only when the candidate already claims a
  range or maximum.
- Lines 435-436: Storey rules use the canonical `storeys` unit.
- Lines 438-444: Height/storey rules infer `Rear Principal Buildings`,
  `Front Principal Buildings`, or `Accessory Buildings` from local wording.
- Lines 446-463: Setback rules refine front street yard, flanking street yard,
  and lane yard scopes. They prefer the candidate's existing scope/condition
  before falling back to broad row text, so a shared table row containing both
  `front` and `flanking` does not overwrite the target scope.
- Lines 466-472: Building-separation rules refine applies_to for rear/rear,
  front/rear, and all-other building separation.
- Lines 474-483: Sprinkler rules extract the `more than 45 m` threshold and
  turn it into a required distance condition.
- Lines 485-510: Fire-access and heritage exception wording is normalized into
  stable scope/condition fields.

This is not verification. It prepares a clearer candidate so the field checks
can judge it.

### 7. Evidence Windows

`src/burnaby_prototype/verification.py`

Lines 507-531 implement `_local_source_context`. It finds a short window around
the cited evidence inside a larger source context. This prevents unrelated text
on the same page from proving a rule.

Lines 534-555 implement `_value_local_window`. This is a key wrong-scope
protection. If evidence contains several numbers, the verifier uses the clause
around the candidate value for scope checks.

Example:

```text
front yard 3.0 m; rear yard 7.5 m
```

When verifying the `3.0 m` rule, the verifier should not let `rear yard` or
`7.5 m` prove the front-yard scope. `_value_local_window` clips the evidence to
the local clause around `3.0`.

### 8. Field Support Checks

`src/burnaby_prototype/verification.py`

Lines 587-593 implement `_contains_value`. It extracts numeric or text tokens
from the candidate value and checks that all tokens appear in evidence.

Lines 596-615 implement `_dwelling_unit_upper_bound_supported`. This handles a
narrow but important case: if a candidate says maximum 6 units and the evidence
says `5 to 6 Units`, the range proves the upper bound.

Lines 618-627 implement `_contains_unit`. It checks the candidate unit against
evidence using `UNIT_ALIASES`.

Lines 642-651 implement `_rule_object_unit_compatible`. It checks
`RULE_OBJECT_ALLOWED_UNITS`. This is where wrong units become critical.

Lines 666-686 implement `_applies_to_supported`. It checks whether distinctive
words from `applies_to` appear in evidence. Generic words like `all`,
`building`, `lot`, and `unit` are removed because they are too broad.

Lines 689-704 implement `_scope_supported`. It checks whether the rule object,
constraint scope, or condition is grounded in local evidence.

Lines 707-737 implement `_operator_supported`. It requires legal wording for
the operator:

```text
<= needs maximum / not exceed / up to / limited to
>= needs minimum / not less / at least / shall have
>  needs more than / greater than / exceeds
<  needs less than / fewer than / under
allowed/permitted needs permitted / shall / must / is
range needs text like "5 to 6"
```

Lines 740-775 implement `_rule_object_supported`. It checks whether evidence
actually talks about the claimed rule family. This is one of the main rejection
guards.

Important examples:

- A height candidate is not supported by fire-access text like `clear to a
  height` unless the evidence is actually about building height.
- A lot-area candidate can be supported by the exact phrase `lot area` or by
  separated words like `lot with an area`.
- A permitted-use candidate can be supported by configured target-concept words
  or explicit permitted/allowed wording.

### 9. Table Context Checks

`src/burnaby_prototype/verification.py`

Lines 778-829 implement `_table_context_gaps`. For table cells, value and unit
are not enough. The verifier also checks:

- Does the table title/row/column support the rule object?
- Does row/column/table text support `applies_to`?
- Does the column support the condition?
- Is the table column relevant to the configured target concept?

Lines 832-858 implement `_table_column_in_target_scope`. Generic table columns
such as `front`, `rear`, `lane`, `street`, `minimum`, or `maximum` are allowed.
Non-generic columns must match target-concept terms from config.

Lines 861-897 implement `_table_review_gaps`. This is the conservative
auto-verification gate for table candidates. If structured table proof is not
strong enough, the candidate gets a review gap instead of being verified.

Lines 900-945 implement `_table_has_verifiable_structure`. A table candidate can
pass this gate only when:

- it has table evidence,
- table text exists,
- value/unit are visible,
- rule object is known,
- rule object/unit pairing is compatible,
- table column is in target scope,
- config-defined table scope patterns allow it.

Lines 948-992 implement `_table_scope_allowed`, which checks
`configs/burnaby_r1.json` patterns such as:

```text
minimum lot line setbacks + lane yard
maximum height + accessory buildings
minimum separation + front & rear principals
heritage + lot coverage
```

This is where Burnaby-specific table scope knowledge belongs: in config, not as
hidden hardcoded answers inside the verifier.

### 10. Decision Policy

`src/burnaby_prototype/verification.py`

Lines 995-1002 implement `_verification_status`, the older status field used by
legacy outputs:

```text
no gaps -> verified
missing-scope style gaps -> missing_scope
otherwise -> needs_human_review
```

Lines 1008-1016 implement the active decision function,
`verification_decision_from_gaps`:

```python
if not support_gaps:
    return "verified"
if CRITICAL_REJECTION_GAPS & set(support_gaps):
    return "rejected"
return "review_needed"
```

This is the core policy. The decision is completely determined by
`support_gaps`.

### 11. Proof Traces

`src/burnaby_prototype/verification.py`

Lines 1044-1115 implement `_text_proof_trace`. This converts boolean support
checks into claim-level proof objects for:

```text
rule_object
constraint_scope
applies_to
operator
value
unit
condition
exception
```

Lines 1118-1135 implement `_claim_from_check`. A passed support check becomes
`supported`, a critical failure becomes `refuted`, and ordinary uncertainty
becomes `not_enough_info`.

Lines 1167-1191 implement `_apply_table_trace_to_support_checks`. This is the
bridge between table proof and deterministic gaps. Table proof is allowed to
update only the matching boolean:

```text
table value proof -> value_supported
table unit proof -> unit_supported
table operator proof -> operator_supported
```

It cannot use a supported table value to repair a missing rule object or scope.

Lines 1194-1211 implement `_repair_table_context_gaps`. Table proof can remove
specific table context gaps only when the matching claim is supported.

Lines 1214-1221 implement `_table_refutation_gaps`. If table proof says the
operator direction is refuted, the candidate gets `table_operator_refuted`, a
critical rejection gap.

Lines 1224-1238 implement `_has_unresolved_exception_cue`. If evidence contains
exception language such as `except`, `exception`, `notwithstanding`, or `unless`
and the proof does not resolve it, the candidate goes to review.

Lines 1241-1259 implement `_proof_decision_mismatches`, a diagnostic check. It
flags places where the proof trace says a claim is supported but the final gaps
still contain the matching support gap, or where a claim is refuted without a
gap.

### 12. Text Candidate Verification Gate

`src/burnaby_prototype/verification.py`

Lines 1266-1323 implement `_text_candidate_can_verify`.

This function decides whether a Pipeline 5 text candidate may be auto-verified.
In the current Burnaby config, `verify_text_candidates` is true, but text
candidates are still intentionally gated more tightly than table candidates.

A text candidate must pass all of these:

1. Text verification is enabled in config.
2. The rule object is in `gis_text_rule_contract`.
3. Every deterministic support check passes.
4. Numeric rule families have numeric values, compatible units, and the correct
   min/max direction.
5. Text-span proof has no material condition gap such as
   `text_condition_not_supported`.
6. If `require_text_consensus` is true, at least two source streams must assert
   the exact same rule.

This prevents a single text extraction from entering GIS just because it looks
plausible.

### 13. Main Verification Loop

`src/burnaby_prototype/verification.py`

Lines 1326-1593 implement `verify_candidates`, the main function.

The high-level steps are:

1. Lines 1340-1352 build the evidence lookup and source-agreement index.
2. Lines 1354-1366 iterate over candidates and retrieve each candidate's cited
   evidence.
3. Lines 1367-1381 build support windows:
   - broad evidence text,
   - table support text,
   - local source context,
   - value/unit support text.
4. Lines 1383-1433 run the first field support checks:
   - value,
   - unit,
   - applies_to,
   - scope,
   - operator,
   - rule object.
5. Lines 1438-1456 run TabVer-lite and let table proof update matching support
   checks.
6. Lines 1460-1508 convert failed checks into `support_gaps`.
7. Lines 1514-1532 compute status, decision, proof traces, evidence strength,
   review priority, and proof mismatch diagnostics.
8. Lines 1535-1587 build the output rule object.
9. Lines 1588-1591 route the rule:
   - verified rules go to `verified_rules`;
   - all other rules go to the non-verified list, later split into review or
     rejected by `slim_pipeline.py`.

The most important part is lines 1460-1508, where gaps are created:

```text
upstream_extraction_requested_review
pipeline5_text_candidate_requires_review
non_numeric_value_for_numeric_rule
value_not_found_in_evidence
unit_not_found_in_evidence
applies_to_not_supported
constraint_scope_not_supported
operator_not_supported
rule_object_not_supported
table_operator_refuted
unresolved_exception_cue
rule_object_unit_not_compatible
table context gaps
table review gate gaps
```

Once these gaps exist, lines 1516-1517 call:

```python
status = _verification_status(support_gaps)
slim_decision = verification_decision_from_gaps(support_gaps)
```

That is where the rule becomes verified, review, or rejected.

### 14. Table Natural Logic

`src/burnaby_prototype/table_natural_logic.py`

This module is the table-aware proof layer. It is not a second verifier. It
produces structured claim proofs that the main verifier can use carefully.

Lines 20-32 define `RULE_OBJECT_CUES`. Example:

```text
Maximum Height -> height
Minimum Lot Line Setbacks -> setback
Minimum Separation -> building_separation
Impervious Surfaces -> impervious_surface
```

Lines 36-44 define `OPERATOR_CUES`:

```text
maximum -> <=
minimum -> >=
more than -> >
less than -> <
required/shall/must -> required
permitted/allowed -> allowed
```

Lines 47-100 implement `table_proof_trace`. It reads:

```text
table_title
row_header
column_header
cell_value
evidence_text
```

and returns proof objects for:

```text
rule_object
constraint_scope
applies_to
operator
value
unit
condition
exception
```

Lines 103-128 classify table proof as:

```text
complete
partial
refuted
none
```

Lines 131-151 implement `_prove_rule_object`. If the table title/row contains a
cue for the candidate's rule object, the claim is supported. If it clearly
points to a different rule object, the claim is refuted.

Lines 154-176 implement `_prove_operator`. If the table says `minimum` and the
candidate claims `>=`, it is supported. If the table says `maximum` and the
candidate claims `>=`, it is refuted.

Lines 179-191 implement `_prove_value`. If the cell contains the candidate
number, the value is supported. If the cell contains a different number, it is
refuted.

Lines 194-216 implement `_dwelling_unit_upper_bound_supported`. It lets a range
like `5 to 6 Units` prove a maximum-6 dwelling-unit claim.

Lines 219-232 implement `_prove_unit`. It accepts unit aliases and refutes a
candidate when the table cell clearly shows a different unit.

Lines 235-256 implement `_prove_text_claim`. This is used for row/column text
claims like scope, applies_to, and condition. It requires enough word overlap so
one vague shared word cannot prove the wrong table row.

Lines 259-266 implement `_prove_exception`. Exception wording is legally risky,
so unresolved `except`, `exception`, `notwithstanding`, or `unless` wording
creates uncertainty.

### 15. Proof and Review Triage

`src/burnaby_prototype/rule_claims.py`

Lines 14-16 define the proof labels:

```text
supported
refuted
not_enough_info
```

Lines 20-29 define the claims that matter for legal/GIS verification:

```text
rule_object
constraint_scope
applies_to
operator
value
unit
condition
exception
```

Lines 32-47 implement `proof`, the standard shape used in JSON output:

```json
{
  "label": "supported",
  "evidence_field": "cell_value",
  "evidence_quote": "1.5 m",
  "reason": "numeric value appears in table cell"
}
```

Lines 70-94 implement `verification_label_from_gaps`. This gives a proof-style
summary label:

- no gaps -> `supported`,
- critical gaps -> `refuted`,
- ordinary uncertainty -> `not_enough_info`.

Lines 97-121 implement `merge_proof_traces`. Text proof and table proof are
merged claim by claim. Refuted proof is strongest, then supported, then
not-enough-info. Exception uncertainty is preserved even if another layer says
the optional exception claim is absent.

Lines 124-180 implement `evidence_strength`. This is the Bayesian-lite triage
score. It starts from a neutral prior and updates from proof labels and support
checks. It is useful for review ordering only.

Lines 183-246 implement `review_priority`. It assigns:

```text
verified
high
medium
low
```

This does not change the verification decision. For example, a high-priority
review rule is still not GIS-safe until it is verified.

### 16. Consensus and Conflict Reporting

`src/burnaby_prototype/consensus.py`

This module supports cross-source reporting and conservative text-rule gating.
It does not decide verification by itself.

Lines 55-68 implement `scope_key`, which groups candidates by rule family and
scope without value.

Lines 71-87 implement `consensus_key`, which includes:

```text
rule_object
constraint_scope
value
unit
operator direction
```

Lines 90-99 build and read a source-agreement map. This lets
`_text_candidate_can_verify` know whether two independent source streams assert
the same exact rule.

Lines 102-157 implement `detect_consensus_and_conflicts`. It writes:

- `rule_consensus.json` when multiple sources agree on a full rule;
- `rule_conflicts.json` when the same rule scope has different numeric
  value/direction variants.

Consensus is reporting-only unless explicitly used as a required gate for text
verification. It cannot override a support gap.

### 17. Compliance Checker

`src/burnaby_prototype/compliance.py`

The compliance checker consumes verified GIS rules and proposal cases.

Lines 38-119 define `CHECK_SPECS`, mapping proposal fields to rule families.
Examples:

```text
rear_principal_height_m -> height + rear principal + m
lane_yard_setback_m -> setback + lane yard + m
lot_coverage_percent -> lot_coverage + %
fire_access_corridor_width_m -> fire_access_corridor + width + m
```

Lines 133-229 implement `evaluate_case`:

1. For each proposal field, find a matching verified rule.
2. If a verified rule exists, compare the proposal value to the rule value.
3. If no verified rule exists, look for a review rule and return
   `needs_review`.
4. Unknown measurement fields also become review.
5. The final decision is:
   - any failed check -> `rejected`;
   - no failures but review checks -> `needs_review`;
   - all relevant fields pass verified rules -> `approved`.

This is why the system has zero false approvals: missing coverage never becomes
approval.

### 18. Benchmark Evaluator

`benchmark/evaluate_benchmark.py`

The benchmark evaluates both rule outputs and proposal safety.

Lines 67-107 implement the evaluator entry point:

1. Load gold rules and proposal cases.
2. Load candidates, evidence, verified rules, review rules, rejected rules, and
   the GIS contract.
3. Evaluate rule metrics.
4. Evaluate proposal decisions.
5. Write `benchmark_report.json`, `benchmark_report.md`, and the diagram.

Lines 119-227 implement `evaluate_rule_outputs`.

Important metrics:

```text
candidate_recall
verified_gold_recall
verified_or_review_recall
extraction_coverage_recall
verifier_retention_rate
verified_precision
false_verified_count
verified_source_support_failed_count
proof_decision_mismatch_count
```

Lines 142-150 decompose recall into:

- extraction coverage: did extraction surface the gold rule at all?
- verifier retention: if extraction surfaced it, did the verifier keep it in
  verified or review instead of wrongly rejecting it?

Lines 264-294 implement gold-rule matching. A match requires:

```text
same normalized rule_object
same numeric value within 0.01
same normalized unit
compatible operator
enough required rule terms
```

Lines 316-349 check source support for verified rules. A verified rule can still
fail the benchmark if its cited evidence does not contain required terms, value,
or unit.

Lines 364-380 define the quality gates:

```text
verified_precision_is_1
false_verified_is_0
false_approval_is_0
proposal_decision_accuracy_is_1
proposal_case_accuracy_is_1
verified_or_review_recall_at_least_0_90
verified_source_support_failures_is_0
proposal_field_expectations_match
```

### 19. Adversarial Safety Benchmark

`benchmark/evaluate_adversarial.py`

This is a separate safety check for deliberately poisoned candidates.

Lines 37-90:

1. Load adversarial cases.
2. Run the real `verify_candidates` function.
3. Fail the benchmark if any poisoned candidate becomes verified.
4. Also compare expected review/rejected decisions.

This test is useful because normal gold-rule benchmarks can prove recall and
precision, but adversarial cases prove the verifier blocks unsafe input.

## Decision Examples

### Example A: Verified Table Setback

Evidence:

```text
Minimum Lot Line Setbacks | Lane Yard | 1.5 m
```

Candidate:

```text
rule_object = setback
constraint_scope = lane_yard
operator = >=
value = 1.5
unit = m
```

Why it can verify:

- `value_supported`: `1.5` appears in the cell.
- `unit_supported`: `m` appears in the cell.
- `operator_supported`: `Minimum` supports `>=`.
- `rule_object_supported`: `Setbacks`/`Yard` supports `setback`.
- `scope_supported`: `Lane Yard` supports `lane_yard`.
- table scope pattern in config allows lane-yard setback.
- no support gaps remain.

Decision:

```text
verified
```

### Example B: Correct But Review-Only Text Rule

Evidence:

```text
on a lot with an area of not less than 560 m2
```

Candidate:

```text
rule_object = lot_area
operator = >=
value = 560
unit = m2
source_stream = gemini_text_block
```

Why it should not be rejected:

- `560` is visible.
- `m2` is visible, including m2 variants.
- `not less than` supports `>=`.
- separated words `lot` and `area` support `lot_area`.

Why it is still review:

- text verification requires deterministic span proof plus cross-source
  consensus;
- if another source does not assert the same rule, the candidate receives
  `pipeline5_text_candidate_requires_review`.

Decision:

```text
review_needed
```

### Example C: Cross-Reference Permitted-Use Rule

Evidence:

```text
Principal Use | Rowhouse Dwellings | 101.5.2 | Use-Specific Regulations: 101.5.2
```

Candidate:

```text
rule_object = permitted_use
value = 101.5.2
```

Why it is not GIS-verified:

- the value is a bylaw cross-reference, not a geometric rule value;
- it may be useful for traceback, but it does not prove a measurable GIS
  constraint like setback, height, or coverage.

Decision is usually review or rejected depending on the exact gaps, but it
should not enter `gis_rule_contract.json`.

### Example D: Unsafe Unit Pairing

Candidate:

```text
rule_object = height
value = 60
unit = %
```

Why it is rejected:

- `height` must use `m`;
- `%` is only compatible with coverage-style rules.

Support gap:

```text
rule_object_unit_not_compatible
```

Decision:

```text
rejected
```

## Safety Invariants

These are the rules that should not be weakened:

1. `verified_rules.json` may contain only rules with no critical unresolved
   support gaps.
2. `gis_rule_contract.json` may contain only verified rules.
3. `review_needed.json` is the correct place for plausible but unproven rules.
4. `rejected_rules.json` is the correct place for contradicted, malformed, or
   unsafe candidates.
5. Upstream `ACCEPT`, confidence, and evidence strength cannot override
   deterministic gaps.
6. Table proof can repair only the exact matching claim it proves.
7. Cross-source consensus is reporting or gating only; it cannot verify a rule
   that failed deterministic support checks.
8. Proposal approval requires verified rule coverage. Missing coverage returns
   `needs_review`.

## How To Debug One Rule

When a rule lands in the wrong bucket, debug in this order:

1. Open `rule_candidates.json` and find the candidate by `candidate_id` or
   `original_rule_id`.
2. Open `evidence_units.json` and find its `evidence_id`.
3. Check whether the evidence text visibly contains the value and unit.
4. Check `support_gaps` on the output rule.
5. For a table rule, inspect:
   - `table_title`,
   - `row_header`,
   - `column_header`,
   - `cell_value`,
   - `table_proof_trace`,
   - `table_proof_status`.
6. For a text rule, check whether `pipeline5_text_candidate_requires_review` is
   the only gap. If so, it is probably a policy/config review item, not an
   extraction contradiction.
7. Check `proof_decision_mismatches`. It should be false.
8. If the candidate is a verified rule, run the benchmark and confirm
   `verified_source_support_failed_count = 0`.

## What To Tell Someone Reviewing The System

The concise explanation is:

```text
Zihao's extraction proposes candidate rules.
The adapter translates those candidates into a stable contract.
The verifier checks the cited evidence field by field.
Table evidence is checked using title, row, column, and cell proof.
The decision comes only from support_gaps.
GIS receives only verified rules.
Uncertain proposal checks return needs_review, never approval.
The benchmark verifies zero false verified rules and zero false approvals.
```
