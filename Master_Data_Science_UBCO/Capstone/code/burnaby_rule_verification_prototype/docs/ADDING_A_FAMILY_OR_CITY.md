# Adding a Rule Family or a City

The verifier is designed so that growth happens in two decoupled steps:
**a rule family is added once, city-neutrally, in the shared vocabulary**, and
**a city activates families via config + gold only — zero code edits**.
This recipe is the tested path (floor_area and floor_space_ratio both landed
through it). Follow it exactly; every step ends with the standing gate suite.

## The standing gate suite (run after EVERY step)

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/run_slim_verifier.py --city burnaby_r1
.venv/bin/python benchmark/evaluate_benchmark.py --city burnaby_r1   # precision 1.0, fv 0, gates pass
.venv/bin/python scripts/run_vancouver_holdout.py                    # precision 1.0
.venv/bin/python benchmark/evaluate_benchmark.py --city vancouver_rs
.venv/bin/python benchmark/evaluate_adversarial.py                   # ALL BLOCKED: True
git diff --stat -- outputs/   # decision files byte-identical unless the step says otherwise
```

## Checklist 1 — Adding a rule family (shared vocabulary, activates nothing)

1. **`src/burnaby_prototype/domain_schema.py`**
   - `RULE_OBJECT_ALLOWED_UNITS["<family>"] = {<unit key>}` — pick the narrowest
     unit set and document what must NEVER be added (e.g. floor_area is m2-only
     so %-exclusion clauses keep hard-rejecting). `NUMERIC_RULE_OBJECTS` and
     `KNOWN_RULE_OBJECTS` derive automatically.
   - `UNIT_ALIASES` if the family introduces a new unit key. **Alias-safety
     rule:** every alias enters the table-proof refutation vocabulary
     (`_visible_units`) via word-bounded matching — never add a spelling that
     occurs in ordinary prose ('far' is the canonical counter-example; it
     lives in `RULE_OBJECT_ALIASES` instead, which is an exact-equality lookup
     on the rule_object FIELD).
   - `RULE_OBJECT_ALIASES` entries for every upstream spelling of the family.
   - `TEXT_RULE_OBJECT_PATTERNS` entry. **Ordering rule (load-bearing):**
     most-specific phrase families come BEFORE their substring parents —
     floor_space_ratio before floor_area before lot_area. First match wins in
     `_rule_object_from_patterns` and `_canonical_rule_object`. Pin the order
     with an index-comparison test.
2. **`src/burnaby_prototype/table_natural_logic.py`** — `RULE_OBJECT_CUES`
   entry, same ordering rule (insertion order = match priority in
   `_matching_rule_object`).
3. **`src/burnaby_prototype/text_span_proof.py`** — `cue_groups` entry in
   `_prove_rule_object` (the fallback only matches `family.replace('_',' ')`).
4. **`src/burnaby_prototype/verification.py`** — `_table_context_gaps`
   `required_by_rule_object` entry (stemmed table words for the family).
5. **Geometry + export projection** (post-verification only):
   `geometry_operator.OPERATION_BY_RULE_OBJECT`, `gis_felt_export`
   (`_GEOMETRY_BY_OBJECT`, `_EXPORT_GROUP_BY_OBJECT`, `_parameter_key`), and
   the `operation` enum in BOTH `schemas/gis_felt_export.schema.json` and
   `schemas/gis_rule_contract.schema.json`.
6. **`verification_cache.VERIFIER_VERSION` bump** — mandatory whenever shared
   vocabulary changes; stale cache entries must never mask a newly-supported
   family. (Allowed gate diff at this step: the version string inside
   verification_cache.json + the cache counters for one settle run.)
7. **Safety artifacts (non-negotiable):** at least one adversarial trap per
   failure mode the family introduces — value-absent, direction-flip,
   incompatible-unit, clean-but-out-of-contract — plus unit tests including
   the ordering pins. Gold rules only for corpora where the family is
   expected to verify.
8. Run the gate suite: existing cities must be byte-identical (the family is
   dormant until a city activates it).

## Checklist 2 — Activating for a city (config + gold ONLY, zero code)

In `configs/<city>_<zone>.json`:

1. `verification.gis_text_rule_contract` — add the family (text candidates).
2. `verification.rule_family_direction` — `"min"`/`"max"` for the family in
   this city's regime (per-city: Vancouver caps laneway floor area, Burnaby
   sets minimum unit floor areas).
3. Optional `verification.single_source_text_rule_contract` — only for
   families whose single sentence reliably carries the whole legal claim.
4. `normalization` capability knobs (all additive; absent = shared behavior):
   - `unit_rewrites` — map verbatim jurisdiction phrasing to a canonical unit,
     e.g. `{"rule_objects": ["floor_area"], "all_terms": ["multiplied by the
     site area"], "unit": "fsr", "set_rule_object": "floor_space_ratio"}`.
   - `rule_object_text_cue_extras` — per-family extra SUPPORT phrases for
     prose-phrased rules, e.g. `{"setback": ["property line"]}`. Support-side
     only; never enters refutation vocabulary.
   - `material_condition_cue_extras` — extra words that make a condition
     material (fail-closed: only adds review pressure).
   - `known_aliases` / `target_concept` — the city's building-type vocabulary.
5. `config.py` — path-resolution entry (naming convention; formerly `cities.py`).
6. `benchmark/gold/<city>_gold_rules.json` (+ proposal cases if compliance
   demos are wanted). Hand-check every gold rule against the bylaw text.
7. Optional: `compliance.CHECK_SPECS` proposal field and
   `zihao_adapter` gis_relevance `"direct"` if the family should be drawable.
8. Run the gate suite + the city's own benchmark. **The city's
   verified_precision must be 1.0 from the first run** — a wrong verify shows
   up as `false_verified > 0` and fails the gate. Recall is the finding to
   report honestly.

## Feeding a city through Pipeline 9 (RAG extraction)

Once a city has a config + gold set, the same verifier also consumes the
team's Pipeline 9 graph-RAG extraction directly — no new adapter code per
city:

```bash
.venv/bin/python scripts/run_slim_verifier.py --city <city> \
  --pipeline9-run /path/to/pipeline9_run_outputs/<city> \
  --output-dir outputs/<city>_p9
.venv/bin/python benchmark/evaluate_benchmark.py --city <city> --output-dir outputs/<city>_p9
```

What the adapter (`src/burnaby_prototype/pipeline9_adapter.py`) relies on:

- `06_rule_extraction*/merged_rules_deduplicated.json` — rule records. The
  largest non-smoke extraction wins deterministically; the chosen path is
  surfaced in the run summary and `p9_provenance.json`.
- `05_rag_visual_blocks/text_blocks.jsonl` — block records. **Join fields:**
  a rule's `source_id` joins a block's `block_id`; the fallback join parses
  `source_id` as `<rag_pack_id>__<original_source_id>`. Blocks carry
  `block_id, original_source_id, rag_pack_id, rag_lane, rag_applicability,
  original_page_number, target_filter_action, parent_context` — there is NO
  `source_id` on blocks. A rule whose block cannot be joined is flagged
  `p9_block_unjoined` and forced to review.
- P9 family names map through additive aliases
  (`separation_distance -> building_separation`, `floor_area_ratio ->
  floor_space_ratio`, `building_height -> height`, ...); unknown families
  flow to review/not_used, never silently dropped.
- Upstream labels are handled asymmetrically: `review_required`, `warnings`,
  or merge-review reasons force review; `review_required=false` grants
  nothing.
- Re-anchoring: with `data/bylaws/<city>/source.pdf` cached (use
  `scripts/fetch_bylaw.py`), each block's text is located on its claimed
  `original_page_number`. Found -> `source_context` becomes the authentic
  page window (`reanchored_to_source: true`); not found ->
  `rag_context_mismatch: true` and the candidate is forced to review.
  Re-anchoring can provide authentic source context. It cannot promote a
  candidate.

The gold-scope caveat from `docs/multi_city_results.md` applies: a full-bylaw
P9 run will verify true rules in sections your gold never covered, and the
gold-keyed false-verified count is then a scope artifact — audit the verified
set against source pages before claiming precision beyond the gold's scope.

## Why this split is safe (the defense answer)

Family vocabulary makes a candidate *eligible*; verification still requires
every deterministic support check to pass against the cited evidence, and the
text gate holds any family that the city's contract does not list. The per-city
knobs are at the same trust level as `known_aliases` — deliberate, reviewed
config — and are structurally additive: rule-object cue extras can only flip a
review-tier check, material-condition extras only add review pressure, and a
unit rewrite still has to survive `contains_unit` + unit-compatibility against
the evidence. None of them can touch the critical rejection gaps that carry
the false_verified = 0 guarantee, and the adversarial suite pins each failure
mode permanently.
