# Code

## Official Rule Extraction Pipeline

- `official_rule_extraction_pipeline/`: official generalized graph/RAG rule-extraction
  pipeline for this branch. Use this for normal extraction runs, HQ outputs,
  quality checks, and downstream GIS-rule handoff.

## Additional Experiments

- `experiment_pipeline_11_bge_m3/`: experimental Pipeline 10 variant with local
  `bge-m3` hybrid embedding compression. Use for comparison experiments only;
  do not treat it as the default extraction path.
- `burnaby_rule_verification_prototype/`: deterministic verification and GIS
  contract prototype.

## Legacy

- `legacy/`: archived Pipeline 1-9 prototype source and lightweight benchmark
  files. Generated outputs, notebooks, PDFs, API raw files, and caches are
  ignored inside this folder.
- `legacy/prototype_0_rule_extraction_test/`: prototype 0 early rule-extraction
  notebooks and scripts.
- `legacy/prototype_table_geometry/`: early table-geometry flattening
  experiment.
