# Verification MVP Handoff

This repo is a verification-first MVP, not a claim that every extractor is
complete. The trust boundary is:

```text
Extractors and RAG propose.
Source repair restores source context.
The deterministic verifier decides.
GIS uses only verified rules.
```

## One Command

From `Burnaby_prototype/`:

```bash
.venv/bin/python scripts/run_mvp_verification.py --refresh-benchmarks --refresh-discovery
```

This fills missing benchmark reports, refreshes dry V2 discovery packs without
LLM calls, and writes:

```text
outputs/mvp_verification/mvp_report.json
outputs/mvp_verification/mvp_report.md
```

## What The Report Proves

- Burnaby, Vancouver, and Calgary PDFs are inventoried from the local source
  files.
- Calgary is treated as the full 1,053-page bylaw in the source inventory.
- P5/P9 baseline outputs are compared with the current native M4 outputs.
- Failed gates are labelled honestly as `scope mismatch`, `fail-closed`, or
  `unsafe / needs fix`.
- Any lane with `false_verified_count > 0`, source-support failures, or false
  approvals is unsafe.

## Current MVP Reading

Current generated report:

```text
outputs/mvp_verification/mvp_report.md
overall_status = mvp_safety_ready
current_path_version = native_m4
current_false_verified_total = 0
```

The safe product claim is:

```text
Native M4 is the current product path.
M4 keeps false verified rules at 0 on Burnaby, Vancouver, and Calgary.
RAG/LLM output remains advisory/proposer-tier; deterministic verification decides.
```

Do not describe a lane as passing unless its benchmark gate passes.

Current key comparison:

```text
Burnaby M4: pass, 84 verified, false_verified 0.
Vancouver M4: pass, 12 verified, false_verified 0.
Calgary M4: pass, 11 verified, false_verified 0, full 1,053-page source.
P5/P9 rows remain legacy/upstream references only.
```

## Final Deliverable Alignment

- Extraction/verification cities: Burnaby, Calgary, Vancouver.
- GIS deliverable cities: Burnaby and Calgary only.
- PIBC vs RAG evaluation matrix: Burnaby and Vancouver only.
- Calgary source handling: full 1,053-page bylaw, not the seven-page test slice.
- Burnaby source handling: correct 7-page R1 PDF; current weakness is
  extraction/table recall, not a wrong PDF.

## Final Gate

Run:

```bash
.venv/bin/python -m unittest discover tests
```

Expected safety standard:

```text
false_verified_count = 0 for every lane claimed as safe
```
