# Multi-City Generalization Results

**Question:** does the deterministic verifier transfer to a *second* municipality
without re-tuning — and does its safety guarantee (precision = 1.00) survive?

**Answer:** yes for the rule families it models, and the safety guarantee holds.
The same verifier code, run on Vancouver laneway-house rules with a config that
carries **zero hand-fit table-scope patterns and a clean (non-Burnaby)
normalization block**, verifies rules at **precision 1.00** and correctly
quarantines everything it cannot prove.

## Method

- **Burnaby R1** — in-domain: the config the verifier was authored against
  (`configs/burnaby_r1.json`), 29 gold rules, Pipeline 5 extraction.
- **Vancouver RS (laneway)** — cross-city: real rules extracted by a *different*
  upstream prototype, adapted into the verifier's candidate/evidence contract by
  `scripts/run_vancouver_holdout.py`, run against `configs/vancouver_rs.json`.
  That config has `structured_table_scope_patterns: []` and an empty
  normalization block — **no Burnaby literals, no per-rule answer patterns**. A
  rule verifies here only on structural proof (value/unit/operator/applies_to/
  scope all grounded in the cited evidence). Reproduce with:
  `.venv/bin/python scripts/run_vancouver_holdout.py`.

## Results

| Metric | Burnaby R1 (in-domain) | Vancouver RS (cross-city, no tuning) | Calgary R-CG (cross-city + OUR extraction) |
|---|---:|---:|---:|
| Extraction system | Pipeline 5 (teammate) | prototype adapter | **internal helper (pdfplumber text stream)** |
| Candidates | 142 | 45 | 24 |
| Verified / Review / Rejected / Not-used | 30 / 58 / 24 / 30 | 5 / 15 / 9 / 16 | 6 / 14 / 4 / 0 |
| **verified_precision** | **1.00** | **1.00** | **1.00** |
| **false_verified_count** | **0** | **0** | **0** |
| verified_gold_recall | 0.90 (26/29) | 0.57 (4/7 in-contract) | 0.75 (6/8) |
| verified_or_review_recall | 1.00 | 1.00 | 1.00 |

**Calgary (backyard suites — Calgary's laneway-home form, Land Use Bylaw
1P2007 s.351–352):** a third city in a DIFFERENT bylaw format, fed by a
different extraction system (our internal helper), verified with an honest
transfer config (zero hand-fit patterns) and 8 hand-checked gold rules.

> **Scope honesty:** the validated Calgary claim covers the
> backyard/secondary-suite provisions only — a deterministic `--pages 393-399`
> slice of the 1,053-page source PDF (content-keyed provenance: source sha256
> + page range recorded in every artifact; evidence units carry FULL-PDF page
> numbers; slice extraction is byte-reproducible run-to-run). It does NOT
> imply full-bylaw validation. Full-bylaw capacity is benchmarked, not
> validated: the text stream processes all 1,053 pages in ~78 s / 1.28 GB
> peak RSS, yielding 3,103 clauses → 951 candidates — the scaling bottleneck
> is gold curation for benchmarking, not compute. Verified: rear setback ≥ 1.5 m, façade separation
≥ 5.0 m, heights ≤ 7.5/5.0 m, balcony setback ≥ 0.6 m, deemed-conforming
front setback ≥ 6.0 m. The two floor-area caps (75 m² backyard / 100 m²
secondary) sit in **review** — correctly fail-closed on their compound
conditions ("excluding stairways…", district/width lists). The precision gate
caught one real leak during activation (a subsection reference "(3.1)"
masquerading as a 3.1 m value) — fixed city-neutrally in the shared
boundary matcher and pinned by regression test.

Vancouver verified families: **height** (≤ 8.5 m), **lot_coverage** (≤ 50 %),
**storeys** (≤ 2), and — since the floor_area family was added — **floor_area**
(≤ 186 m², bylaw 11.3.8.2(b)) — all for the laneway house, each proven from
its own prose. A second, duplicate extraction of the same 186 m² cap
(`vancouver_rs_009`) verified for a while via bundle promotion and now sits in
**review**: when the cue vocabulary became exclusion-aware, it exposed that
the bundle had satisfied that candidate's `constraint_scope='total'` with
"the **total** area of these exclusions" — wording from 11.3.8.9, a
floor-area *exclusion computation* in a different subsection. Refusing that
bundle is the gate working; the cap itself stays covered by
`vancouver_rs_007`.

> **Compound-bound caveat (11.3.8.2):** the bylaw caps laneway floor area at
> the *lesser of* 0.25 × site area and 186 sq. m. The verifier grounds the
> absolute 186 m² branch (it is literally stated in the cited clause); the
> 0.25 × site-area branch is FSR-style and stays in review by design. GIS
> consumers must treat 186 m² as an upper envelope, not the exact allowance on
> small lots.

> **Safety note:** adding the family also exposed — and fixed — a real
> stitching hole: a floor-area *computation* clause ("…exceeds 3.7 m…") nearly
> verified as a height cap because a same-page sibling clause supplied "does
> not exceed" wording to its synthetic evidence bundle. The bundle path now
> requires the operator to be grounded in the value-bearing member itself, and
> an adversarial bundle case (`adv_bundle_same_source_operator_stitch`) pins
> the fix.

> **Dormant FSR capability:** the verifier now also carries a
> `floor_space_ratio` family (dimensionless `fsr` unit, `density_ratio_cap`
> geometry on the parcel polygon) — city-neutral and **deliberately inactive**:
> Vancouver's 0.25 × site-area branch stays in review/rejected BY CONFIG
> (`floor_space_ratio` is absent from vancouver_rs.json's contract and no
> `unit_rewrites` entry maps "multiplied by the site area"). Future activation
> is a config + gold change per `docs/ADDING_A_FAMILY_OR_CITY.md`; four
> adversarial FSR traps (value-absent, direction-flip, city-phrasing unit,
> clean-but-out-of-contract) already pin the failure modes.

## Pipeline 9 (graph-RAG extraction): same verifier, second upstream

Pipeline 9 is the team's full-bylaw RAG candidate generator (graph-RAG packs →
pseudo-pages → Gemini rule extraction). It replaces nothing in the verifier:
`scripts/run_slim_verifier.py --pipeline9-run <dir>` adapts its
`merged_rules_deduplicated.json` + `text_blocks.jsonl` into the same
candidate/evidence contract, preserves P9 provenance (original PDF page,
pseudo-page, pack id, RAG lane/applicability, `target_filter_action`), and
**re-anchors** each evidence block to the city's cached `source.pdf`: the
authentic page window replaces the RAG pack context when the block's text is
found on its claimed page, and a block that cannot be found there is marked
`rag_context_mismatch` and FORCED to review. Re-anchoring is evidence repair
only — it can never promote a candidate.

The core rule under test: *Pipeline 9 proposes. Verification proves. GIS
consumes only verified.* No upstream confidence, `review_required=false`, or
P9 label promotes anything.

| Metric (P9-fed, full extraction) | Burnaby R1 | Vancouver RS | Calgary R-CG |
|---|---:|---:|---:|
| P9 candidates / evidence blocks | 72 / 12 | 43 / 35 | 428 / 152 |
| Re-anchored to source page | 12 (0 mismatched) | 35 (0 mismatched) | 136 (16 mismatched → review) |
| Verified / Review / Rejected / Not-used | 0 / 52 / 14 / 6 | 2 / 22 / 13 / 6 | 16 / 348 / 56 / 8 |
| **false_verified within gold scope** | **0** | **0** | **0** |
| verified_gold_recall | 0.00 | 0.29 (2/7) | 0.25 (2/8) |

Reading the table honestly:

- **Vancouver** verifies exactly the two clean laneway rules (height ≤ 8.5 m,
  storeys ≤ 2 — both gold) and holds the rest, including the 3.1 m
  exclusion-criterion clause described below.
- **Burnaby** verifies nothing from P9 — correctly. Burnaby's text-rule policy
  requires multi-evidence consensus or the audited single-source contract; P9
  supplies one block per rule, so everything waits in review. fail-closed,
  not zero-capability.
- **Calgary** is the full 1,053-page bylaw against an 8-rule gold authored for
  the R-CG backyard-suite slice, so gold-keyed "false verified" counts are a
  **scope artifact**: 12 of the 16 verified rules live in bylaw sections the
  gold never covered (H-GO rear setbacks 547.12(1)–(4) with their branch
  conditions carried verbatim, fence/privacy-wall heights, accessory-building
  height, LRT setback depths, §487 heights with the 400 m²/10 m parcel
  qualifier). Each of the 16 was audited against its re-anchored source page:
  all true. In-gold-scope false verifies: 0.

**What P9 testing bought: four live false-verify classes, each now a
permanent adversarial pin** (battery: 18 poisoned candidates + 3 poisoned
bundles, all blocked):

1. **Exclusion criterion as rule** (Vancouver 11.3.7.4): "the ceiling height,
   excluding roof structure, of the total area being excluded does not exceed
   3.1 m" — an eligibility test for a floor-area exclusion that reads exactly
   like a height cap. The unresolved-exception hold previously consulted only
   the table trace (prose was immune) and lacked the exclud* vocabulary.
2. **Definition as rule** (Calgary p62): '"corner parcel" means … intersect at
   an angle not exceeding 135 degrees' proposed as `dwelling_units <= 135`
   with no unit. Defined-term sentences now bucket like cross-references, and
   a unit-less candidate can no longer take its value from a number glued to a
   foreign measure ("135 degrees" is never a count).
3. **Allowance trigger as requirement** (Calgary p1039): "there is no maximum
   building depth **where** the minimum building setback … is 3.0 metres" —
   the 3.0 m unlocks an allowance; the bylaw does not require it.
4. **Subject-flattened separation** (Calgary p825): "a minimum horizontal
   separation of 1.0 metres … between **retaining walls**" proposed as
   `building_separation`. The family cue now requires a building-like subject
   in the SAME SENTENCE as the separation wording — a synthetic bundle had
   satisfied the whole-window check with "buildings" borrowed from the
   neighboring §1118 provision.

None of these is hand-fit to one city: each gate is a sentence-shape or
vocabulary rule (definitions, allowance triggers, foreign measures, resolved
preambles) that applies to all three cities and is enforced by the shared
adversarial battery.

## What this shows

1. **The safety guarantee transfers.** On a brand-new bylaw with no hand-fit
   knowledge, nothing wrong verified — precision stayed 1.00 and
   `false_verified_count` stayed 0. The conservative gates are structural, not
   Burnaby-specific.
2. **Coverage is bounded by the rule-family contract, not by tuning — and
   extending the contract works.** Adding the `floor_area` family (vocabulary
   entries + a Vancouver contract line, no verifier-code special cases)
   recovered the laneway floor-area cap that previously sat in `not_used` with
   the single gap `rule_object_not_supported`, moving Vancouver from 4 to 6
   verified at unchanged precision 1.00 (one of the two later moved back to
   review when its bundle's borrowed scope support was exposed — see above; the
   family's coverage is unchanged). The remaining not-used population is
   the same story: FSR-ratio, bedroom-area, openness, ceiling-height,
   site-dimension, use-combination families. Vancouver's zoning regime is
   FSR-centric; Burnaby's is an envelope of setbacks/height/coverage.
3. **Honest recall.** Of the 7 in-contract gold rules, 4 verified and 3 (the
   4.9 m main-house separation and the 0.9 m / 1.2 m yard setbacks) went to
   **review** — correctly, because their extracted evidence fragments (e.g.
   `"(c) 1.2 m from each side property line…"`) do not themselves contain the
   minimum/“at least” operator wording. The verifier refuses to assume the
   direction. `verified_or_review_recall = 1.00`: every in-contract gold rule
   was surfaced, none silently dropped.

## What it would take to extend coverage

- ~~**Add the floor-area family**~~ **DONE (2026-06-09):** `floor_area`
  (m²-only, max direction) is now in `domain_schema` and the Vancouver
  contract; the 186 m² laneway cap verifies and exports as
  `max_floor_area_m2` / `floor_area_cap` geometry. The m²-only allowed-unit
  set is a deliberate invariant — bylaw floor-area *exclusion* clauses ("8% of
  the floor area") must keep hard-rejecting on unit incompatibility.
- **Add the FSR ratio family** (`floor_space_ratio`, dimensionless `fsr` unit,
  max direction) to model the 0.25 × site-area branch and Vancouver's wider
  FSR-centric regime. Needs a per-city normalization rewrite for verbatim
  phrasing like "multiplied by the site area"; keep that phrasing per-city,
  with only the generic `fsr` aliases shared.
- **Carry parent-clause context on sub-clause evidence** so a fragment like
  `"(c) 1.2 m from each side property line"` inherits the `"must be at least:"`
  heading — this would move the 3 review setbacks toward verification without
  weakening any gate (the same multi-evidence/section-anchor work noted for
  Burnaby).

## Bottom line

The verifier is genuinely city-agnostic *for the families it models*: dropping
in a config + gold set (no code, no answer patterns) produced verified rules at
precision 1.00 on a second municipality — and extending the family contract
(floor_area) raised cross-city coverage with precision intact. The honest
ceiling is now the FSR ratio family, the highest-leverage next step for real
multi-city coverage.
