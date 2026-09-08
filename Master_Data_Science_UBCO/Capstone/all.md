# Burnaby Zoning Verification - Easy Guide

## One-Sentence Summary

This project checks zoning rules from city bylaw PDFs before those rules are
used in GIS maps or proposal decisions.

The most important rule is:

```text
Extraction suggests rules.
Verification checks the source.
GIS uses only verified rules.
```

## Why This Project Exists

Zoning bylaws are long, legal, and full of tables. An AI model can find useful
rules, but it can also make mistakes.

So we do not trust extraction by itself.

Our system asks:

```text
Does the cited bylaw evidence really support this rule?
```

If yes, the rule becomes verified.

If no or uncertain, the rule goes to review, rejected, or not used.

## The Simple Workflow

```text
1. Read city bylaw PDFs
2. Extract possible zoning rules
3. Attach source evidence
4. Verify each rule field
5. Split rules into safe buckets
6. Export only verified rules to GIS
7. Test proposal decisions against verified rules
```

## The Four Output Buckets

### verified

The rule is supported by source evidence.

GIS can use it.

### review_needed

The rule may be right, but something is missing or unclear.

Examples:

- condition is unclear
- scope is unclear
- table row or column context is incomplete
- exception language needs human review

GIS should not use it yet.

### rejected

The rule is contradicted or unsafe.

Examples:

- wrong value
- wrong unit
- wrong operator
- source evidence does not support the claim

GIS should not use it.

### not_used

The candidate is useful for audit, but outside the current product scope.

GIS should not use it.

## Current Safety Result

Burnaby R1 benchmark:

```text
candidate_rules = 142
verified_rules = 27
review_needed = 66
rejected = 16
not_used = 33

verified_precision = 1.00
false_verified_count = 0
false_approval_count = 0
verified_or_review_recall = 1.00
```

Vancouver holdout:

```text
candidate_rules = 45
verified_rules = 4
review_needed = 9
rejected = 3
not_used = 29

verified_precision = 1.00
false_verified_count = 0
verified_or_review_recall = 1.00
```

Plain meaning:

```text
The system is conservative.
It does not approve unsupported rules.
Uncertain rules are sent to review.
```

## What File Should GIS Use?

GIS should use only this file:

```text
code/burnaby_rule_verification_prototype/outputs/burnaby_r1_slim_pipeline5_registry/gis_rule_contract.json
```

That file contains verified rules only.

Do not use these files directly for GIS:

```text
review_needed.json
rejected_rules.json
not_used.json
raw extraction outputs
LLM review outputs
```

Those files are for debugging, review, or audit.

## What File Explains The Benchmark?

Use:

```text
code/burnaby_rule_verification_prototype/outputs/burnaby_r1_slim_pipeline5_registry/benchmark_report.md
```

It shows:

- verified precision
- false verified count
- false approval count
- proposal decision results
- missed or reviewed rules

## What File Shows The Review Queue?

Use:

```text
code/burnaby_rule_verification_prototype/outputs/burnaby_r1_slim_pipeline5_registry/review_needed.json
```

This file is important because it shows what the verifier refused to promote.

That is a good thing. It protects GIS from unsafe rules.

## How To Run The Main Check

From:

```text
code/burnaby_rule_verification_prototype
```

Run:

```bash
.venv/bin/python scripts/run_slim_verifier.py --city burnaby_r1
.venv/bin/python benchmark/evaluate_benchmark.py --city burnaby_r1
```

Run the Vancouver holdout:

```bash
.venv/bin/python scripts/run_vancouver_holdout.py
.venv/bin/python benchmark/evaluate_benchmark.py --city vancouver_rs
```

Run the adversarial safety check:

```bash
.venv/bin/python benchmark/evaluate_adversarial.py
```

Run the dashboard:

```bash
.venv/bin/python -m streamlit run dashboard/streamlit_app.py --server.port 8502
```

## What The Dashboard Is For

The dashboard is for review and inspection.

It helps users see:

- verified rules
- rules needing review
- rejected rules
- GIS export readiness
- benchmark results

The dashboard should not override the verifier.

## What The Blocker Report Says

The latest blocker report is:

```text
code/blocker_reports/br_2026-06-15.pdf
```

It has three questions:

```text
Question 1: Is the extraction layer acceptable?
Question 2: Is the verification layer acceptable?
Question 3: Is the GIS/proposal checker acceptable?
```

Short answer:

```text
Extraction is acceptable for the prototype.
Verification is acceptable as the authority layer.
GIS/proposal checking is acceptable only as a verified-only tri-state checker.
```

## What Still Needs Work

The biggest remaining problem is table-heavy bylaw evidence.

We need better:

- table row context
- table column context
- page and bounding-box evidence
- condition and exception handling
- review workflow

But we should not relax the verifier just to get more verified rules.

## The Rule To Remember

If you remember only one thing, remember this:

```text
A rule is not safe because an AI extracted it.
A rule is safe only when the verifier proves it from source evidence.
```
