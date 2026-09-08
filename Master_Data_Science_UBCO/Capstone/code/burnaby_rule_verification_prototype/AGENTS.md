# Burnaby Prototype Instructions

This folder contains the Burnaby R1 zoning extraction and verification
prototype.

When working here, treat extraction as candidate generation and verification as
the authority. Only source-supported rules should be promoted into
`verified_rules.json` or `gis_rule_contract.json`.

Primary goal:

- zero false verified rules
- zero false approved proposal decisions
- uncertain evidence, table context, or scope goes to review

Next stage:

- add gold rule benchmark
- add proposal/user-case benchmark
- add evaluator
- add compliance checker
- improve verification using benchmark results
