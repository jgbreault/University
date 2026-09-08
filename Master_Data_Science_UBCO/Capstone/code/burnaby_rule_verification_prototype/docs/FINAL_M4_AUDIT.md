# Final M4 Audit

This note records the final verification-polish pass for the current native M4
product path.

## Current Authority Boundary

```text
Extraction/RAG proposes.
Source repair restores cited context.
Deterministic verification decides.
GIS consumes only verified rules.
```

Pipeline 5 and Pipeline 9 remain legacy/upstream reference rows. They are not
the current product path.

## Current Product Path

Current path from `outputs/mvp_verification/mvp_report.md`:

```text
current_path_version = native_m4
overall_status = mvp_safety_ready
current_false_verified_total = 0
```

Current M4 rows:

| City | Candidates | Verified | Review | Rejected | Not used | False verified | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Burnaby R1 | 101 | 84 | 17 | 0 | 0 | 0 | pass |
| Vancouver RS | 32 | 12 | 11 | 9 | 0 | 0 | pass |
| Calgary R-CG | 306 | 11 | 43 | 35 | 217 | 0 | pass |

## Source-PDF Audit

Audit artifact:

```text
outputs/topdown_validation/m4_source_pdf_audit.json
```

The audit reads each official local `data/bylaws/<city>/source.pdf` with
`pypdf`, then checks every current M4 `verified_rules.json` row for:

- valid cited source page
- candidate value visible on the cited PDF page or cited source context
- candidate unit visible on the cited PDF page or cited source context

Result:

| City | PDF pages | Verified rules checked | Cited pages | Failures |
|---|---:|---:|---|---:|
| Burnaby R1 | 7 | 84 | 2, 6 | 0 |
| Vancouver RS | 22 | 12 | 8 | 0 |
| Calgary R-CG | 1,053 | 11 | 395, 396, 397, 398 | 0 |

Calgary is audited against the full 1,053-page bylaw, not a seven-page slice.

## Code/Folders Polish

- `scripts/run_consolidated_prototype.py native` now routes to the current M4
  runner instead of the older V2 runner.
- `scripts/build_m4_source_corpus.py` prefers M4 cached chunks/packs before V3
  fallbacks, so rebuilt M4 source-corpus snapshots do not accidentally report
  V3 selected-coverage data.
- README and handoff docs now describe M4 as the current product path and P5/P9
  as reference rows only.
- Existing package skeletons (`adapters/`, `discovery/`, `repair/`,
  `verifier/`, `review/`, `exports/`, `reports/`, `source/`) are kept as the
  folder-polish layer. Moving flat modules into those packages should remain a
  separate measured import-migration, not a final-pass cleanup.

## Remaining Honest Caveat

M4 is safety-ready, not perfect recall for every possible municipal rule. The
remaining review/rejected/not-used rows should be treated as recall and review
workflow work. They are not verified outputs and are not GIS inputs.
