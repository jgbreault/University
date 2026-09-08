# Week 4

## Summary
Focused on validating and improving the rule extraction pipeline (Pipeline 3) for Burnaby R1, building a ground truth dataset to measure extraction accuracy, and fixing core table extraction bugs. Also met with the partner to discuss the extraction workflow and GIS integration direction.

## Tasks
- Built a ground truth dataset (113 rules) to evaluate Pipeline 3 extraction accuracy against the actual Burnaby R1 bylaw
- Identified and fixed table extraction bugs in Pipeline 3 — the pipeline was incorrectly labeling universal rules (lane yard, building height, separations) as "Rowhouse only" due to how PyMuPDF handles merged cells in PDF tables
- Fixed the exception pattern extraction ("3.0m except 1.5m for accessory buildings") so base and exception rules now have correct conditions
- Fixed the verification step that was over-flagging clean table rules as REVIEW
- Met with partner to discuss extraction workflow and confirmed GIS Phase 1 direction — focus on answering buildability using development feasibility rules for Burnaby first before scaling to other cities

## Time
| Activity | Hours |
|---|---|
| Pipeline debugging and code fixes | 20 |
| Ground truth building and validation | 8 |
| Unit test development | 3 |
| Partner meeting and discussion | 2 |
| Documentation | 2 |
| **Total** | **35** |


## Challenges
- PyMuPDF collapses merged PDF table cells into a single column, making it hard to distinguish between universal rules and Rowhouse-specific rules — required a dash-aware detection approach to resolve correctly
- Pipeline needed multiple run iterations to validate each fix due to Gemini API call time — resolved by building standalone unit tests
- Using the free tier API limits extraction quality compared to the paid version — the model occasionally misses condition scope or produces vague action hints (REVIEW instead of ACCEPT) for rules that are clearly correct, which required additional post-processing logic (`STRICT_TABLE_ACCEPT`) to compensate

## Next Steps

- Run Pipeline 3 on Vancouver RS (Laneway House) and Surrey R1 (Coach House) to test generalizability
