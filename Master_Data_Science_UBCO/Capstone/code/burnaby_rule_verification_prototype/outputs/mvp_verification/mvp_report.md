# MVP Verification Report

Overall status: **mvp_safety_ready**

Extractors and RAG propose; deterministic verifier decides; GIS uses only verified rules.

## PDF Inventory

| City | Pages | Source |
|---|---:|---|
| burnaby_r1 | 7 | `/Users/thomas/Documents/Capstone_prototype/Burnaby_prototype/data/bylaws/burnaby_r1/source.pdf` |
| vancouver_rs | 22 | `/Users/thomas/Documents/Capstone_prototype/Burnaby_prototype/data/bylaws/vancouver_rs/source.pdf` |
| calgary_rcg | 1053 | `/Users/thomas/Documents/Capstone_prototype/Burnaby_prototype/data/bylaws/calgary_rcg/source.pdf` |

## Current Product Path: native_m4

| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Burnaby native M4 exhaustive full-bylaw extraction | 101 | 84 | 17 | 0 | 0 | 1.000 | 0 | 1.000 | pass |
| Vancouver native M4 exhaustive full-bylaw extraction | 32 | 12 | 11 | 9 | 0 | 1.000 | 0 | 1.000 | pass |
| Calgary native M4 exhaustive full-bylaw extraction | 306 | 11 | 43 | 35 | 217 | 1.000 | 0 | 1.000 | pass |

_Recall verified/review is measured against the curated in-contract benchmark gold set. It is not a claim that every numeric rule in the full bylaw has been extracted._

## Out-of-scope / Not-used Explanation

Not-used candidates are retained for audit but are not verified outputs and are not GIS inputs.

| City | Not used | Plain explanation | Top reasons | Top rule families |
|---|---:|---|---|---|
| calgary_rcg | 217 | These are real numeric candidates from the full bylaw, but they are outside the configured target sections for this product run. They are kept for audit and review, not exported as verified rules. | Outside target section (217), Upstream extraction requested review (215), Pipeline5 text candidate requires review (168), Enumerated branch condition missing (80), Applies to not supported (50), Constraint scope not supported (45) | Setback (118), Height (58), Floor area (15), Lot area (10), Building separation (8), Lot coverage (8) |

## M4 Promotion Gate

Promoted: **True**

| Gate | Status |
|---|---|
| M4 safety | True |
| Adversarial all blocked | True |
| Exhaustive source coverage | True |
| No verified/review recall loss vs V3 | True |
| Improved verified cities | calgary_rcg |
| Blockers |  |

## V3 Promotion Gate

Promoted: **True**

| Gate | Status |
|---|---|
| V3 safety | True |
| Adversarial all blocked | True |
| Improvement in at least 2 cities vs V2 | True |
| Improved cities | burnaby_r1, calgary_rcg, vancouver_rs |
| Blockers |  |

## Previous Native V3 Reference

| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Burnaby native V3 full-bylaw extraction | 103 | 84 | 19 | 0 | 0 | 1.000 | 0 | 1.000 | needs review |
| Vancouver native V3 full-bylaw extraction | 31 | 12 | 11 | 8 | 0 | 1.000 | 0 | 1.000 | pass |
| Calgary native V3 full-bylaw extraction | 225 | 10 | 28 | 28 | 159 | 1.000 | 0 | 1.000 | pass |

## Previous Native V2 Reference

| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Burnaby native V2 full-bylaw extraction | 79 | 50 | 13 | 16 | 0 | 1.000 | 0 | 0.725 | scope mismatch |
| Vancouver native V2 full-bylaw extraction | 14 | 2 | 8 | 4 | 0 | 1.000 | 0 | 0.571 | scope mismatch |
| Calgary native V2 full-bylaw extraction | 129 | 3 | 16 | 14 | 96 | 1.000 | 0 | 0.750 | scope mismatch |

## Legacy / Upstream References

These rows are retained for comparison only. They are not the current product path.

| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Burnaby P5 registry legacy reference | 142 | 43 | 50 | 27 | 22 | 1.000 | 0 | 1.000 | pass |
| Vancouver P5 registry legacy reference | 45 | 3 | 20 | 13 | 9 | 1.000 | 0 | 1.000 | pass |
| Calgary internal registry legacy reference | 24 | 3 | 15 | 4 | 2 | 1.000 | 0 | 1.000 | pass |
| Burnaby P9 graph-RAG upstream reference | 72 | 0 | 50 | 14 | 8 | 0.000 | 0 | 0.625 | scope mismatch |
| Vancouver P9 graph-RAG upstream reference | 43 | 2 | 21 | 12 | 8 | 1.000 | 0 | 1.000 | pass |
| Calgary P9 graph-RAG upstream reference | 428 | 3 | 152 | 49 | 224 | 1.000 | 0 | 0.750 | scope mismatch |

## V2 Discovery

| City | Chunks | Packs | Chunked page span | Version |
|---|---:|---:|---|---|
| burnaby_r1 | 93 | 80 | 1 to 7 (6 pages with chunks) | v2_discovery_2 |
| vancouver_rs | 251 | 80 | 1 to 21 (21 pages with chunks) | v2_discovery_2 |
| calgary_rcg | 3558 | 400 | 7 to 1052 (709 pages with chunks) | v2_discovery_2 |

## M4 Exhaustive Discovery

| City | Full PDF pages | Chunks | Packs | Rule-like numeric clauses | Selected coverage | Chunked page span | Version |
|---|---:|---:|---:|---:|---:|---|---|
| burnaby_r1 | 7 | 93 | 87 | 23 | 1.000 | 1 to 7 (6 pages with chunks) | m4_exhaustive_discovery_1 |
| vancouver_rs | 22 | 251 | 173 | 38 | 1.000 | 1 to 21 (21 pages with chunks) | m4_exhaustive_discovery_1 |
| calgary_rcg | 1053 | 3558 | 1400 | 1044 | 1.000 | 7 to 1052 (709 pages with chunks) | m4_exhaustive_discovery_1 |

## V2 Model Runs

| City | Model | Packs | Candidates | Verified | Review | Rejected | False verified | Recall verified/review | Cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| burnaby_r1 | dry_run | 80 | 66 | 48 | 2 | 16 | 0 | 0.600 | 0.0 |
| burnaby_r1 | google/gemini-2.5-flash | 178 | 34 | 3 | 31 | 0 | 0 | 0.225 | 0.040975 |
| burnaby_r1 | google/gemini-2.5-flash-lite | 80 | 79 | 50 | 13 | 16 | 0 | 0.725 | 0.003718 |
| burnaby_r1 | openai/gpt-5-mini | 178 | 65 | 2 | 60 | 3 | 0 | 0.525 | 0.038908 |
| calgary_rcg | dry_run | 400 | 0 | None | None | None | None |  | 0.0 |
| calgary_rcg | google/gemini-2.5-flash | 40 | 6 | 3 | 3 | 0 | 0 | 0.625 | 0.008606 |
| calgary_rcg | google/gemini-2.5-flash-lite | 400 | 129 | 3 | 16 | 14 | 0 | 0.750 | 0.03081 |
| vancouver_rs | dry_run | 80 | 0 | None | None | None | None |  | 0.0 |
| vancouver_rs | google/gemini-2.5-flash | 80 | 11 | 1 | 7 | 3 | 0 | 1.000 | 0.015543 |
| vancouver_rs | google/gemini-2.5-flash-lite | 80 | 14 | 2 | 8 | 4 | 0 | 0.571 | 0.004828 |

## V3 Model Runs

| City | Model | Packs | Candidates | Verified | Review | Rejected | False verified | Recall verified/review | Cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| burnaby_r1 | google/gemini-2.5-flash-lite | 84 | 103 | 84 | 19 | 0 | 0 | 1.000 | 0.002688 |
| calgary_rcg | google/gemini-2.5-flash-lite | 580 | 225 | 10 | 28 | 28 | 0 | 1.000 | 0.043808 |
| vancouver_rs | google/gemini-2.5-flash-lite | 134 | 31 | 12 | 11 | 8 | 0 | 1.000 | 0.008153 |

## M4 Model Runs

| City | Model | Packs | Candidates | Verified | Review | Rejected | False verified | Recall verified/review | Cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| burnaby_r1 | dry_run | 87 | 84 | None | None | None | None |  | 0.0 |
| burnaby_r1 | google/gemini-2.5-flash-lite | 95 | 101 | 84 | 17 | 0 | 0 | 1.000 | 0.003131 |
| calgary_rcg | dry_run | 1400 | 6 | None | None | None | None |  | 0.0 |
| calgary_rcg | google/gemini-2.5-flash-lite | 1480 | 306 | 11 | 43 | 35 | 0 | 1.000 | 0.09968 |
| vancouver_rs | dry_run | 173 | 5 | None | None | None | None |  | 0.0 |
| vancouver_rs | google/gemini-2.5-flash-lite | 186 | 32 | 12 | 11 | 9 | 0 | 1.000 | 0.010884 |

## Interpretation

- Current MVP outputs satisfy the safety target: false_verified_count is 0 wherever benchmarks are present.
- NATIVE_M4 covers the benchmarked gold rules through verified or review dispositions in every current city.
- NATIVE_M4 keeps out-of-contract full-bylaw candidates in not_used for audit in: calgary_rcg. They are not verified outputs.
- M4 passed promotion gates and is the current product path.
- Pipeline 5 and Pipeline 9 rows are legacy/upstream references only; they are not part of the current product-path status.
- This report proves the native-extraction verification handoff state; legacy extractors remain reference rows only.
