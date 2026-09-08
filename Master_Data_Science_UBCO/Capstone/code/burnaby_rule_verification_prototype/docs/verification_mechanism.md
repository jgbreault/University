# Verification Mechanism

This file gives the short version. For the detailed file/function/line-level
walkthrough, see `docs/verification_layer_deep_dive.md`.

## Mental Model

The verifier treats every extracted rule as a claim that must be proven by its
cited evidence.

```text
candidate rule + evidence packet -> proof checks -> decision
```

The possible decisions are:

```text
verified       evidence supports all critical fields
review_needed  useful but incomplete or outside current GIS contract
rejected       contradicted, unsupported, or unsafe for GIS
```

## Deterministic Checks

The verifier checks field-level support:

```text
value_supported
unit_supported
operator_supported
rule_object_supported
applies_to_supported
scope_supported
table_context_supported
```

These checks create `support_gaps`. A rule is verified only when there are no
critical gaps. Scores and upstream labels cannot override these gaps.

## Pipeline 5 Text-Span Proof

Pipeline 5 prose candidates can be promoted only when deterministic text-span
proof supports the material fields in the cited text. The span proof checks:

```text
value
unit
operator
rule_object
scope
applies_to
condition
exception
```

For text candidates, material conditions such as `heritage`, `front/rear`,
`sloping roof`, `street`, `between`, or exception wording must be visible in the
cited prose. If the number is visible but the condition is not, the verifier
adds `text_condition_not_supported` and sends the rule to review.

Text auto-verification also requires cross-source consensus. A single text
stream cannot override deterministic support gaps.

## TabVer-Lite Table Proof

For table evidence, the verifier uses table structure:

```text
table_title
row_header
column_header
cell_value
```

Example:

```text
Minimum Lot Line Setbacks | Lane Yard | 1.5 m
```

can support:

```text
rule_object = setback
operator = >=
constraint_scope = lane_yard
value = 1.5
unit = m
```

Table proof is allowed to satisfy matching support checks only when the proof
label is `supported`. If table proof is `refuted`, the candidate cannot be
silently verified.

## Proof Traces

Each output rule includes:

```text
text_proof_trace
text_span_proof_trace
table_proof_trace
merged_proof_trace
proof_decision_mismatch
```

The labels are:

```text
supported
refuted
not_enough_info
```

`proof_decision_mismatch = false` means the proof trace and final support gaps
agree.

## Bayesian-Lite Review Triage

`evidence_strength` is a lightweight score based on deterministic support
signals. It helps rank review work, but it never verifies a rule.

```text
verified/review/rejected is decided by support gaps only
review_priority is for humans only
```
