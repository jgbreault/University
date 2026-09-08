# M7 Final Release Story and Runbook

M7 is the final release phase for the municipal zoning verification prototype.
It does not replace the deterministic verifier with a model. It consolidates the
matrix-aware extraction pipeline on `google/gemini-3.1-flash-lite`, the M5.6
scored measurement layer, and the 4-tab Civic Console dashboard into one clear,
reproducible handoff.

The core contract is unchanged:

```text
Extraction proposes.
Verification proves.
GIS consumes only verified, source-supported rules.
```

## What M7 Is

M7 is a release-quality consolidation of the verified pipeline:

- one consolidated, matrix-aware extraction/discovery path feeds the
  deterministic verifier; "Pipeline 5" and "Pipeline 9" are historical names for
  shared upstream code, not separate product lanes;
- the product model moved to `google/gemini-3.1-flash-lite`;
- M5.6 supplies the honest scored legal-slot denominator and too-much/too-little
  counts;
- the dashboard (Civic Console) and bylaw chat are read-only review and
  communication tools;
- Vancouver and Calgary remain generalization checks, not product scope;
- the deterministic verifier (`verification.py` / `decision_policy.py` /
  `support_checks.py`) stays the sole authority. No gate was relaxed to raise a
  count.

## The Consolidated Matrix-Aware Pipeline

The biggest extraction change between the pre-M7 (`google/gemini-2.5-flash-lite`)
and the M7 (`google/gemini-3.1-flash-lite`) runs is a single consolidated
matrix-aware pipeline: matrix tables are bound column-by-column before the
generic text-shape gates run, so a real per-column table value (e.g. a
dwelling-unit or storey count) is proven by its matrix anchor instead of being
sent to review by a text-flattening heuristic. This is what lets Calgary's
verified set roughly double without touching a verifier gate.

### Page-scope fix

Extraction is now scoped to the deliverable district's pages whenever
`provenance.json` pins a page range (`restrict_intermediate_to_pages` over
`page_ranges_from_provenance`). On a large multi-district bylaw such as Calgary
(1053 pages), RAG retrieval previously pulled cross-district numeric noise into
the evidence packs; the page scope mirrors the source-corpus scope and keeps
retrieval inside the right district. Original page numbers are preserved so every
citation stays valid. `tests/test_page_scope_coverage.py` is the silent-failure
guard: it fails CI if any city's authored gold falls outside its own scoped page
range (otherwise recall could silently drop with no signal).

## Per-City Results

M7 product run, `outputs/m7_runs/<city>/google_gemini_3_1_flash_lite/`,
evaluated by `benchmark/evaluate_benchmark.py`:

| City | Verified (pre-M7 -> M7) | Verified-or-review recall | Coverage recall | Verified precision | False verified | Source-support failures |
|---|---|---:|---:|---:|---:|---:|
| Calgary RCG | 16 -> 30 | 0.84 -> 1.00 | 1.000 | 1.000 | 0 | 0 |
| Burnaby R1 | 84 -> 87 | 0.975 (-> 0.97) | 0.975 | 1.000 | 0 | 0 |
| Vancouver RS | 12 -> 10 | 1.00 | 1.000 | 1.000 | 0 | 0 |

Reading the table:

- **Calgary** is the headline generalization win: verified rules grew from 16 to
  30 and verified-or-review recall rose from 0.84 to 1.00, driven by the
  matrix-aware binding plus the page-scope fix, with verified precision still
  1.0 and zero false verifies.
- **Burnaby** grew from 84 to 87 verified rules at 0.97 verified-or-review
  recall. The remaining gold gap is a single fire rule (`br1_fire_003`) whose
  only cited evidence does not deterministically support the
  `fire_access_corridor` family; the verifier holds it rather than guess.
- **Vancouver** stays at 1.00 recall. Its raw verified count is lower than the
  pre-M7 count because exact source-aware duplicate rows are now collapsed in the
  GIS-facing exports; every gold rule remains covered and the de-duplication is
  audit-logged.

## Scored Coverage (M5.6 Denominator)

Raw verified-rule counts overstate coverage on a big bylaw, so M5.6 scores
against the honest denominator: in-contract, recognized-family, corpus-derived
legal slots. M7 measurement run
`outputs/m7_measure/m7_gemini31_20260616/<city>/`:

| City | Distinct scored legal slots | Scored verified | Scored verified coverage |
|---|---:|---:|---:|
| Burnaby R1 | 66 | 21 | 0.318 |
| Calgary RCG | 62 | 10 | 0.161 |
| Vancouver RS | 50 | 4 | 0.091 |

Calgary scored verified coverage rose from 0.129 to 0.161 — a real coverage gain
from the consolidated pipeline, not from loosening verification. Coverage is
deliberately conservative: many scored slots remain in review or missed, and the
right next improvement is evidence assembly and table-proof completeness, not the
verifier gates.

## The C5 Finding: Verifier-Recall Rescue Reverted

During M7 we attempted a "verifier-recall rescue" (C5): promote some
consensus-held review rules to verified to lift scored coverage. We measured it
and **reverted it**, because it injected false verifies — it raised the count by
admitting rules whose cited evidence did not deterministically support the
claim. The consensus hold is therefore kept as a legitimate safety behavior, not
a recall bug: when a rule's evidence only supports a text-consensus reading and
not a deterministic field match, holding it in review is the correct, fail-closed
outcome. C5 is recorded as a deliberate no-go: scored coverage is grown by better
evidence, never by relaxing the trust gate.

## The Range-Bound Leak Fix

A real false-verify class was closed in `decision_policy.evidence_shape_gaps`.
When the LLM flattens a multi-cell table into one evidence pack
("1 to 3 Units; 4 to 6 Units"), a lower range bound can be mis-extracted as the
lot maximum (`dwelling_units <= 3` when the lot maximum is 6). The
`range_bound_not_maximum` guard sends such a count to review unless the scope
carries a disambiguator (front/rear/accessory). The leak was that the in-text
unit-range pattern required the unit noun immediately after the high bound, so
qualifier text between them ("1 to 3 small-scale multi-unit dwelling units")
let the lower bound escape the guard. The pattern now matches the unit noun via a
bounded lookahead that stops at a sentence/clause break, so the range bound is
caught without spanning into an unrelated clause. Structured table cells (proven
column-by-column by the matrix anchor) are explicitly exempt so real verified
table rules are not wrongly reviewed. See
`tests/test_adversarial_hardening.py::test_range_bound_not_verified_as_lot_maximum`.

## Safety Contract Held Throughout

Every M7 change kept the non-negotiable safety contract:

| Check | Status |
|---|---|
| Full test suite (`pytest -q`) | 483 passed (incl. 3 subtests) |
| Burnaby adversarial cases | 24 / 24 blocked — ALL BLOCKED: True |
| Calgary adversarial cases | 6 / 6 blocked — ALL BLOCKED: True |
| Vancouver adversarial cases | 4 / 4 blocked — ALL BLOCKED: True |
| Burnaby adversarial bundles | 3 / 3 blocked |
| Verified precision (all cities) | 1.000 |
| False verified (all cities) | 0 |
| Source-support failures (all cities) | 0 |
| Burnaby proposal false approvals | 0 (`proposal_decision_accuracy = 1.0`) |

Two CI safety gates added in M7 keep this from regressing silently
(`tests/test_m7_safety_gates.py`):

1. **Proposal false-approval gate** — asserts the committed Burnaby
   `benchmark_report.json` proposal metrics keep `false_approval_count == 0` and
   `proposal_decision_accuracy == 1.0`.
2. **GIS export drift guard** — re-projects each city's committed
   `gis_rule_contract.json` and `gis_felt_export.json` from the committed
   `verified_rules.json` and requires an exact match, pinning the verified-rule
   legal identities against any hand edit or stale swap.

## How To Run M7 Locally

From `Burnaby_prototype/`:

```bash
.venv/bin/python -m pytest -q

.venv/bin/python benchmark/evaluate_adversarial.py \
  --config configs/burnaby_r1.json \
  --cases benchmark/gold/burnaby_r1_adversarial_cases.json \
  --out /tmp/adv_burnaby_r1.json

.venv/bin/python benchmark/evaluate_benchmark.py \
  --city burnaby_r1 \
  --output-dir outputs/m7_runs/burnaby_r1/google_gemini_3_1_flash_lite

.venv/bin/python scripts/run_m7_measure.py \
  --run-id m7_gemini31_20260616 \
  --changed-component m7_matrix_pipeline_gemini_3_1 \
  --model google/gemini-3.1-flash-lite --overwrite
```

Run the dashboard:

```bash
.venv/bin/python -m streamlit run dashboard/streamlit_app.py --server.port 8620
```

The dashboard opens on the current M7 overview and leads with the scored
too-much / too-little coverage panel.

## What To Show Reviewers

1. Safety contract: extraction proposes, verification proves, GIS consumes only
   verified rules.
2. Per-city M7 results: Calgary 16 -> 30 verified at recall 1.0, Burnaby 87 at
   0.97, Vancouver 1.0 — all at verified precision 1.0, zero false verifies.
3. Scored coverage with the honest legal-slot denominator (Calgary
   0.129 -> 0.161), framed as conservative, not complete.
4. The C5 finding: a recall rescue was tried, measured to inject false verifies,
   and reverted — the consensus hold is legitimate safety.
5. GIS handoff: `gis_rule_contract.json` is verified-only and deduplicated for
   downstream consumers; `verified_rules.json` keeps the raw audit trail; the
   drift guard pins both.
6. Review queue: unresolved table/scope/condition cases are intentionally held.

## Known Limits

- Scored coverage is the largest useful next area. Improve evidence assembly and
  table-proof completeness by legal slot; do not loosen verification gates.
- Calgary has a large scored denominator because the source bylaw is far broader
  than the product scope; Calgary is a stress test.
- Chatbot answers are advisory and source-grounded. The chat cannot verify,
  approve, reject, edit, or promote outputs.

## M7 Finalization Checklist

- [x] Consolidate the matrix-aware pipeline on `google/gemini-3.1-flash-lite`.
- [x] Apply the page-scope fix and the range-bound leak fix.
- [x] Confirm all hard gates pass (precision 1.0, false verified 0,
      source-support failures 0, proposal false approvals 0).
- [x] Record the C5 finding and revert the verifier-recall rescue.
- [x] Add the two CI safety gates (proposal false-approval, GIS drift guard).
- [x] Point README/docs/dashboard at M7 and remove deleted-lane references.
- [ ] Deploy the cloud dashboard.
- [ ] Produce the final PDF handoff report.
- [ ] Commit and push the final release branch.
