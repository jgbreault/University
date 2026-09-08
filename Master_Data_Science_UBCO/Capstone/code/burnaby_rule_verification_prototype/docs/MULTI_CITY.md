# Multi-City Porting Guide

This verifier is built to generalize across BC municipalities. The verification
logic is city-agnostic; the city-specific knowledge lives in **data**, not code.

## Naming convention

Add a new city/zone by dropping these files (see `resolve_city_paths` in `src/burnaby_prototype/config.py`):

```text
configs/<city>.json                          # required: city/zone config
benchmark/gold/<city>_gold_rules.json        # required: hand-labelled gold rules
benchmark/gold/<city>_proposal_cases.json    # required: proposal compliance cases
benchmark/gold/<city>_adversarial_cases.json # optional: poisoned-candidate cases
```

Then run, with no code changes:

```bash
python3 scripts/run_slim_verifier.py   --city <city> --pipeline5-registry <path/to/final_rule_registry.json>
python3 benchmark/evaluate_benchmark.py --city <city>
```

Output lands in `outputs/<city>_slim_pipeline5_registry/`.

## What is already city-agnostic (no work to port)

- The deterministic verification gate (`verification.py`) and its support checks.
- TabVer-lite table proof (`table_natural_logic.py`).
- Cross-source consensus / conflict detection (`consensus.py`).
- Proof traces and Bayesian-lite triage (`rule_claims.py`).
- The benchmark evaluator, retention metric, and adversarial harness.
- Unit/rule-object compatibility and operator-direction safety.

## What is configured per city (edit the config)

`configs/<city>.json` already carries the city-specific knobs:

- `city`, `zone`, `source_document`, `source_url`
- `target_concept` + `known_aliases` — the buildings/uses this zone cares about
- `verification.structured_table_scope_patterns` — table scope safety patterns
- `verification.gis_text_rule_contract` + `rule_family_direction` — text-rule policy
- `verification.verify_text_candidates` / `require_text_consensus` — opt-in text gate

## Normalization is now config-driven

The verifier's normalization (building-type `applies_to` labels, setback
scope/condition rewrites, the sprinkler distance parse, the "X to Y units"
range→max rewrite, heritage/fire condition defaults, and the generic /
non-material word sets) lives in a `normalization` config block, applied by the
pure helpers in `src/burnaby_prototype/normalization_rules.py`. Burnaby's literals
are isolated in `DEFAULT_NORMALIZATION` (used when a config omits the block), so
the verification *logic* is city-agnostic and a new city overrides behaviour by
supplying its own `normalization` — no Python edit. See the `NormalizationConfigTests`
in `tests/test_slim_verifier.py` for a new-city override and a fallback example.

Table-cell auto-verification is likewise config-driven: `table_scope_pattern_mode`
defaults to `deny_ambiguous` (structural proof verifies; a pattern with
`"action": "review"` only quarantines a known-ambiguous column). Burnaby uses
`allow_list` historically but runs in `deny_ambiguous`; a new city needs no
patterns at all.

`deny_ambiguous` does **not** mean "trust any number in a cell". A cell only
auto-verifies if it passes the full structural gate in
`verification._table_has_verifiable_structure`: the candidate value must appear
in the cell, the unit must be present and compatible with the rule family, the
rule object must be known, the column must be in the configured target scope, and
TabVer (`table_natural_logic`) must not refute the value/unit/operator. The
config-driven `_family_direction_mismatch` gate additionally rejects a candidate
whose operator contradicts its family's direction (e.g. a `dwelling_units >= N`
extracted from a bedroom-count row). The pattern list only adds *review*
quarantines on top of that gate; it never relaxes it.

### Minor Burnaby-specific remnants (do not block a new city)

A few narrow, out-of-contract cases are still in code and simply won't fire on a
new city's wording:

- `verification._refine_normalized_candidate` — the fire-access-corridor
  vertical-clearance block (the `condition_default` first-match model doesn't fit
  its OR-guard) and a generic "All dwelling units" label.
- `zihao_adapter._applies_to_from_record` / `_constraint_scope_from_record` —
  building-type labels duplicated in the adapter. These are redundant for the
  verified output because the verifier's config-driven `_refine_normalized_candidate`
  re-derives `applies_to`/scope; cleaning them is a low-priority follow-on.

## Worked example: Vancouver (cross-city, measured)

No longer hypothetical. `configs/vancouver_rs.json` +
`benchmark/gold/vancouver_rs_gold_rules.json` + `scripts/run_vancouver_holdout.py`
run the verifier on real Vancouver laneway-house rules with **zero hand-fit
patterns and a clean (non-Burnaby) normalization block**. Result: **precision
1.00 holds on a second city**, 3/6 in-contract gold rules verify
(height / lot_coverage / storeys), and Vancouver's FSR / floor-area families
correctly fall to `not_used` (the documented contract gap). Full write-up and
the honest two-city table: [multi_city_results.md](multi_city_results.md).

## Richer GIS handoff

Each verified rule is also projected into `gis_felt_export.json` (typed
`value_numeric` + coarse `geometry_target` + a structured `geometry` operator)
and assembled into `buildable_envelope.json`. See [output_guide.md](output_guide.md).
