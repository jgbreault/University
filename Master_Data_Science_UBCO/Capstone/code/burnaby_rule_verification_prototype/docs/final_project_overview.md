# Final Project Overview

## What This Prototype Does

This prototype verifies Burnaby R1 zoning rules extracted by Zihao's Pipeline 5.
It does not try to be the extraction model. Instead, it acts as the trust gate
between extracted candidate rules and GIS-ready zoning constraints.

```text
Extraction proposes.
Verification proves.
GIS consumes only verified rules.
```

## Why This Matters

LLM or table extraction can produce useful candidate rules, but those candidates
can still be incomplete, mis-scoped, or unsupported. A GIS workflow should not
trust a rule just because a model extracted it.

The verifier therefore checks whether the cited evidence supports:

```text
value
unit
operator
rule object
applies_to
scope
condition
exception
```

If evidence is incomplete, the rule goes to `review_needed.json`. If evidence
contradicts the candidate, it goes to `rejected_rules.json`. If the candidate is
only a bylaw cross-reference or outside the current validation contract, it is
kept in `not_used.json` for traceability.

## Current Result

The active Pipeline 5 benchmark has:

```text
candidate_recall = 1.00
verified_or_review_recall = 1.00
verified_gold_recall = 0.45
verified_precision = 1.00
false_verified_count = 0
false_approval_count = 0
source_support_failures = 0
proposal_decision_accuracy = 1.00
```

The main limitation is verified recall:

```text
verified_gold_recall = 0.45
```

So the verifier now matches the Pipeline 5 candidate coverage benchmark, while
remaining conservative about promotion. Pipeline 5 text rules can now verify
when their cited prose supports the value, unit, operator, rule object, scope,
and material condition, and when another source stream corroborates the same
rule. Text rules missing material condition support stay in `review_needed.json`.
