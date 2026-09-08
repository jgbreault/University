# Verification Dashboard

The dashboard is a reader for verifier outputs. It can optionally call a small
LLM for the bylaw chat panel, but it never changes decisions or promotes rules.

Run from the project root:

```bash
.venv/bin/python -m streamlit run dashboard/streamlit_app.py --server.port 8620
```

Default product output folder (M7, gemini-3.1-flash-lite):

```text
outputs/m7_runs/<city>/google_gemini_3_1_flash_lite/
```

For final review, prefer the latest M7 measurement run when present:

```text
outputs/m7_measure/m7_gemini31_20260616/<city>/
```

## Current UX — the "Civic Console"

Four obviously-named tabs, ordered as the questions a user actually asks, plus
a conversation. Everything heavier than a glance lives one click away.

- **City selector** — the sidebar lists every discovered city output
  (`outputs/m7_runs/<city>/<model>/`, `outputs/m7_measure/<run>/<city>/`, and the
  `*_slim_pipeline5_registry/` dirs) that contains `verified_rules.json`. New
  cities appear automatically once their outputs exist; nothing is hardcoded.
- **Summary** — a safety chip (green when `false_verified_count == 0`), a
  full-width **coverage hero** (`scored_verified_coverage` over the honest
  scored legal-slot denominator), four outcome KPI tiles, a single
  status-colored decision-mix bar, plain-English next-action cards, and two
  collapsed "how it works / how we got these numbers" expanders.
- **Review Queue** — the reviewer worklist: inline filters (why / urgency /
  likely outcome / family) over the verifier's review queue, with single-rule
  detail and a compare-with-verified view.
- **GIS Handoff** — verified-only, deduplicated, geometry-tagged rules ready
  for the map: counts (incl. `gis_ready`), a constraint table, and download
  buttons for `gis_rule_contract.json` and `gis_felt_export.json`.
- **Ask the Bylaw** — a clean, conversational LLM chatbot (see below).
- **Advanced & diagnostics** — a single collapsed sidebar door (radio picker)
  for the coverage-vs-gold matrix, pipeline comparison, evidence repair, shadow
  reruns, and engineering details. Nothing is deleted — only moved behind one door.
- **Too Much / Too Little** — the overview leads with the M7 scored legal
  denominator: in-contract, recognized-family, corpus-derived legal slots. Raw
  slots remain visible only as an advisory over-count guardrail.
- **GIS handoff counts** — `verified_rules.json` remains the raw verifier audit
  trail. `gis_rule_contract.json` and `gis_felt_export.json` are deduplicated
  for downstream map/GIS consumers, with duplicate merge details stored in the
  contract's `deduplication` block.
- **Map tab** — a pydeck deck centered on the selected city showing a
  representative 30 m x 40 m **demo lot** (not a real parcel) with verified
  setback bands, the buildable footprint extruded to the max verified height,
  and tooltips carrying parameter, value, operator, rule id, and evidence
  quote. Requires the optional extra: `pip install -e .[map]`; without pydeck
  the tab shows an install hint instead.
- **Bylaw tab** — renders extracted bylaw sections from
  `data/bylaws/<city>/` when present, with a rule picker that `<mark>`s the
  picked rule's cited evidence inside the section. Falls back to the
  evidence-units view when no extraction exists yet.
- **3D envelope** — `scripts/build_envelope_3d.py` writes
  `outputs/<city>.../envelope_3d.html` (self-contained Three.js + OrbitControls
  from CDN) from `buildable_envelope.json`; the dashboard embeds it when the
  file exists and always shows a printable SVG plan-view fallback with setback
  arrows, values, and rule ids.
- **Color semantics (strict, everywhere)** — verified `#1a7f37` (green),
  review `#9a6700` (amber), rejected `#cf222e` (red), not_used `#57606a`
  (grey).

The dashboard still runs with only the base dependency (`streamlit`); pydeck,
LLM chat, and the Three.js artifact degrade gracefully with informative messages.

## The Bylaw Chatbot

`Ask the Bylaw` is a real conversational LLM assistant, grounded in retrieved
bylaw sections. It works out of the box: the dashboard auto-loads
`OPENROUTER_API_KEY` from the project `.env` (the same key the extraction layer
uses) and answers with `google/gemini-3.1-flash-lite` by default. It is
multi-turn (recent turns are passed back to the model), renders answers in a
clean chat-shell with per-answer **citation cards** (section · page), and keeps
prompt suggestions hidden behind a `Need ideas?` popover whose chips are
generated from the city's actual verified/review rules — never shown up front.

Answers are advisory: the assistant cites retrieved sections and **cannot**
approve, reject, verify, edit, or promote a rule.

Provider override (optional) via environment variables or Streamlit secrets:

```toml
# default is OpenRouter; override the model or switch providers if desired
BYLAW_RAG_PROVIDER = "openrouter"   # or gemini | openai | anthropic
BYLAW_RAG_MODEL = "google/gemini-3.1-flash-lite"
OPENROUTER_API_KEY = "..."          # already in .env locally
```

If no key is reachable, the chat degrades gracefully to retrieval-only mode
(shows the retrieved sections, generates no answer).

## How To Read It

```text
verified
```

Safe, source-supported rules. These are the only rules that should drive GIS.

```text
review_needed
```

Possibly useful rules that need clearer evidence, scope, condition, or legal
review.

```text
rejected
```

Unsafe or contradicted candidates.

```text
not_used
```

Traceability-only or out-of-contract candidates, such as cross-references and
administrative rules.

## Main Tabs

```text
Summary
```

Safety chip, coverage hero, four outcome KPIs, the decision-mix bar, next-action
cards, and collapsed funnel / quality-gate detail.

```text
Review Queue
```

The reviewer worklist from `review_router.json` with inline filters (priority,
likely status, action bucket, family), single-rule detail, and a
candidate-vs-verified compare view.

```text
GIS Handoff
```

Verified-only, deduplicated, geometry-tagged rules for the map: counts incl.
`gis_ready`, a constraint table, and downloads for `gis_rule_contract.json` and
`gis_felt_export.json`.

```text
Ask the Bylaw
```

The conversational, source-grounded LLM chatbot (OpenRouter / gemini-3.1-flash-lite).

Engineering views (coverage-vs-gold matrix, pipeline comparison, evidence
repair, shadow reruns, verification structure) live behind the sidebar
**Advanced & diagnostics** door.

## Guardrail

The dashboard explains decisions. It does not make decisions.
