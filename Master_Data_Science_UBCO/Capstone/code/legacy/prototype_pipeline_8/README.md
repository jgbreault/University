# Prototype Pipeline 8

Pipeline 8 = **Pipeline 6's city generalization** + **Pipeline 7's safe token
savings**, in one runner. It produces the same rules each ancestor would, just
on any configured city *and* at a lower image-token cost.

```text
full bylaw PDF
  -> [P6] local candidate selection   (config-driven, offline)
  -> [P6] Gemini window refinement     (pick the pages that carry target rules)
  -> [P7] visual split                 (low-res layout image + high-res table crops)
  -> rule extraction                   (unchanged)
  -> merge review                      (unchanged)
```

## What each ancestor contributes

### From Pipeline 6 — generalization to other cities (stages 01-02)
Instead of hardcoding "process the whole Burnaby PDF", a `CITY_CONFIGS` entry
declares the target zone, PDF, and target/parent keywords. Stage 01
(`local_candidate_block_selector`) scans the **entire** PDF offline and scores
candidate windows; stage 02 (`gemini_candidate_window_refiner`) asks Gemini to
confirm which windows actually contain the target rules and emits the page set
to process. One `city` argument switches between Burnaby / Vancouver / Surrey.

### From Pipeline 7 — safe, quality-neutral token savings (stage 03)
| # | Optimization | Why quality is unaffected |
|---|---|---|
| **S1** | Page **layout image** at `layout_scale = 2.0`; **table crops** stay at `scale = 3.0` | Values are read from the high-res crop; the page image only locates tables + transcribes body text. 2.0× (~144 DPI) is lossless for digital bylaw PDFs. ~50% fewer layout tokens. |
| **S2** | Skip the layout API call for pages with no text and no images | Empty pages cannot produce rules. |
| **S3** | Response caching (reuse cached JSON unless `--overwrite`) | Re-runs never re-call the API. |

Per-stage model overrides (`--layout-model`, `--text-model`, …) exist but every
stage **defaults to `--model`** — no Flash-tier downgrade is applied, matching
Pipeline 7's deliberate "no quality risk" stance.

## Why the merge is safe
Only the **visual-split** call carries Pipeline 7's two extra knobs
(`layout_scale`, `skip_empty_pages`). Stages 01, 02, 04, and 05 are byte-for-byte
the same calls Pipeline 6 makes, and the two knobs were added to the shared
`prototype_pipeline_5/gemini_visual_block_extractor.py` in a backward-compatible
way (`layout_scale` defaults to `scale`, `skip_empty_pages` defaults to `False`).
So Pipeline 8 = P6 page selection feeding P7-optimized imaging; rule *reading* is
identical to both.

## Run
```bash
# end-to-end on any configured city
python pipeline8_runner.py vancouver
python pipeline8_runner.py burnaby
python pipeline8_runner.py surrey

# offline plumbing check — local selection only, no API call
python pipeline8_runner.py vancouver --local-only

# explicit knobs (these are the defaults)
python pipeline8_runner.py vancouver --layout-scale 2.0 --scale 3.0
```

Set `GEMINI_API_KEY` before any stage past `--local-only`. Stage gating flags
(`--skip-window-refinement`, `--skip-visual-split`, `--skip-rule-extraction`,
`--skip-merge-review`) and `--overwrite` behave exactly as in Pipeline 6.

## Outputs
```
outputs/<city>/
  01_local_selection/   candidate_windows.jsonl, summary.json
  02_window_refinement/ refined_windows.jsonl, summary.json
  03_visual_blocks/     text_blocks.jsonl, table_regions.jsonl, page_images/, summary.json
  04_rule_extraction/   final_rule_registry.json, merged_rules_deduplicated.json, ...
```

The final registry (`04_rule_extraction/final_rule_registry.json`) is the same
schema Pipeline 5/6/7 emit, so it feeds the Burnaby/municipal verifier directly:

```bash
cd ../burnaby_rule_verification_prototype
PYTHONPATH=src python scripts/run_slim_verifier.py --city <city> \
  --pipeline5-registry ../prototype_pipeline_8/outputs/<city>/04_rule_extraction/final_rule_registry.json \
  --output-dir outputs/<city>_pipeline8_registry
```

## Relationship to siblings
- **Pipeline 5** — base verification-first extractor (Burnaby, whole-PDF).
- **Pipeline 6** — adds city generalization (local selection + window refinement).
- **Pipeline 7** — adds safe image-token savings to Pipeline 5 (Burnaby only).
- **Pipeline 8** — this one: P6 generalization **and** P7 token savings together.
