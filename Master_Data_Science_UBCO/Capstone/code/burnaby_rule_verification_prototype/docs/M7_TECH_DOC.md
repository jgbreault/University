# M7 Technical Document — Zoning Bylaw Rule Verification

*A plain-language + technical guide to how the system turns dense legal bylaw text into
machine-readable, trustworthy zoning rules — and why it can be trusted.*

---

## 1. What this is, in one paragraph

Canadian municipalities publish **zoning bylaws** — long legal PDFs that say things like *"the minimum
building setback from a side property line is 1.2 metres."* Planners and GIS teams need those rules as
clean, structured data (`setback ≥ 1.2 m, side`) to check permits and draw maps. This project reads a
bylaw, asks an AI to **propose** candidate rules, and then runs every candidate through a **deterministic
verifier** that only accepts a rule if its exact value, unit, direction, and scope are literally
supported by the cited source text. The AI can suggest; **only the verifier decides.** The result is a
set of `verified` rules that never contradict the bylaw, plus a dashboard and a grounded chatbot to
explore them.

**The headline guarantee:** across all three pilot cities (Burnaby R1, Calgary R‑CG, Vancouver RS),
a ground‑truth audit against the *actual bylaw PDFs* found **zero false‑verifies** — no verified rule
contradicts or is absent from its bylaw, and no min/max direction is ever inverted.

---

## 2. The problem, and why it is hard

- **Bylaws are long and messy.** Calgary's is 1,053 pages. Rules hide in prose *and* in dimensional
  **tables** (matrices of dwelling‑type × value). A naive reader misses most of them.
- **The same number means different things.** "1.2 m" might be a side setback, an easement width, or a
  fence height. Getting the *association* wrong publishes a false rule.
- **LLMs hallucinate.** Studies in 2025 show AI legal tools still hallucinate **17–33% of citations**
  even with retrieval. You cannot ship raw LLM output as law.
- **The cost of a wrong rule is high.** A bad "verified" setback could mis‑approve a building. So the
  system's #1 job is **never to verify something the bylaw doesn't say** — even at the cost of leaving
  some true rules in a human‑review queue.

---

## 3. Background knowledge (quick primer)

| Term | Plain meaning |
|---|---|
| **RAG** (retrieval‑augmented generation) | Find the relevant bylaw passages first, then feed *only those* to the LLM so it answers from real text, not memory. |
| **Structured extraction** | Turning a sentence into fields: `{rule_object, value, unit, operator, scope}`. |
| **Deterministic verifier** | Plain, auditable code (no AI) that checks each field against the cited text and outputs a yes/no. Same input → same output, always. |
| **Source‑support gate** | "Is this exact value/unit/word actually in the quoted clause?" If not, reject. |
| **Matrix / table extraction** | Reading a dimensional table cell‑by‑cell with geometry, so each (row × column) becomes one provable rule. |
| **Gold** | A small set of hand‑checked correct rules used to measure recall/precision. |
| **Adversarial cases** | Deliberately poisoned candidates (wrong value, inverted direction, foreign unit) used to prove the verifier blocks them. |

---

## 4. The big idea (the thesis)

> **Propose with AI. Decide with deterministic rules. Let nothing else be the authority.**

This separation is what makes the system safe *and* useful:

- The **proposer** (retrieval + matrix parser + LLM) can be creative and is allowed to be wrong — its
  job is *recall* (surface every candidate).
- The **verifier** is conservative and is never wrong in the dangerous direction — its job is
  *precision* (admit only source‑proven rules).

Recent literature converges on exactly this recipe for text‑and‑table legal documents: *"the LLM
locates the table, a deterministic parser extracts the cells, minimizing hallucination"* and a
*faithfulness/verification layer* as the gate. M7 leans all the way into it.

---

## 5. Architecture — the pipeline

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 360" font-family="Inter, sans-serif" font-size="13">
  <style>
    .box{fill:#fff;stroke:#d0d7de;stroke-width:1.5;rx:10}
    .lbl{fill:#1f2328;font-weight:700}
    .sub{fill:#57606a;font-size:11px}
    .acc{fill:#0969da}
    .v{fill:#1a7f37}.r{fill:#9a6700}.x{fill:#cf222e}.n{fill:#57606a}
    .flow{stroke:#0969da;stroke-width:2;fill:none;marker-end:url(#a)}
  </style>
  <defs><marker id="a" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0969da"/></marker></defs>
  <!-- source -->
  <rect class="box" x="10" y="150" width="120" height="60" rx="10"/>
  <text class="lbl" x="70" y="176" text-anchor="middle">Bylaw PDF</text>
  <text class="sub" x="70" y="194" text-anchor="middle">page-scoped</text>
  <!-- discovery -->
  <rect class="box" x="170" y="150" width="130" height="60" rx="10"/>
  <text class="lbl" x="235" y="172" text-anchor="middle">Discovery</text>
  <text class="sub" x="235" y="189" text-anchor="middle">hybrid retrieval</text>
  <text class="sub" x="235" y="203" text-anchor="middle">+ rule sweep</text>
  <!-- extraction split -->
  <rect class="box" x="340" y="95" width="150" height="50" rx="10"/>
  <text class="lbl" x="415" y="116" text-anchor="middle">Matrix extractor</text>
  <text class="sub" x="415" y="132" text-anchor="middle">deterministic table cells</text>
  <rect class="box" x="340" y="215" width="150" height="50" rx="10"/>
  <text class="lbl" x="415" y="236" text-anchor="middle">LLM extractor</text>
  <text class="sub" x="415" y="252" text-anchor="middle">prose clauses (gemini-3.1)</text>
  <!-- verifier -->
  <rect class="box" x="535" y="150" width="150" height="60" rx="10" fill="#f6f8fa" stroke="#0969da"/>
  <text class="lbl acc" x="610" y="174" text-anchor="middle">DETERMINISTIC</text>
  <text class="lbl acc" x="610" y="191" text-anchor="middle">VERIFIER</text>
  <text class="sub" x="610" y="205" text-anchor="middle">the sole authority</text>
  <!-- buckets -->
  <rect class="box" x="730" y="70" width="150" height="34" rx="8"/><circle cx="746" cy="87" r="5" class="v"/><text x="758" y="91" class="lbl">Verified</text>
  <rect class="box" x="730" y="116" width="150" height="34" rx="8"/><circle cx="746" cy="133" r="5" class="r"/><text x="758" y="137" class="lbl">Review needed</text>
  <rect class="box" x="730" y="162" width="150" height="34" rx="8"/><circle cx="746" cy="179" r="5" class="x"/><text x="758" y="183" class="lbl">Rejected</text>
  <rect class="box" x="730" y="208" width="150" height="34" rx="8"/><circle cx="746" cy="225" r="5" class="n"/><text x="758" y="229" class="lbl">Not used</text>
  <!-- consumers -->
  <rect class="box" x="730" y="270" width="150" height="62" rx="10" fill="#f6fbf7" stroke="#1a7f37"/>
  <text class="lbl v" x="805" y="292" text-anchor="middle">GIS contract</text>
  <text class="sub" x="805" y="308" text-anchor="middle">+ dashboard + chatbot</text>
  <text class="sub" x="805" y="322" text-anchor="middle">(verified only)</text>
  <!-- flows -->
  <path class="flow" d="M130,180 H168"/>
  <path class="flow" d="M300,175 C320,175 320,120 338,120"/>
  <path class="flow" d="M300,185 C320,185 320,240 338,240"/>
  <path class="flow" d="M490,120 C515,120 515,170 533,170"/>
  <path class="flow" d="M490,240 C515,240 515,190 533,190"/>
  <path class="flow" d="M685,172 C705,172 710,87 728,87"/>
  <path class="flow" d="M685,178 C705,178 710,133 728,133"/>
  <path class="flow" d="M685,182 C705,182 710,179 728,179"/>
  <path class="flow" d="M685,188 C705,188 710,225 728,225"/>
  <path class="flow" d="M805,242 V268" stroke="#1a7f37" marker-end="url(#a)"/>
  <text class="sub" x="805" y="258" text-anchor="middle" fill="#1a7f37">only the green bucket flows on →</text>
</svg>

**Walkthrough.** The PDF is **page‑scoped** to the target district (e.g. Calgary R‑CG pp. 465–478, not
the whole 1,053 pages). Discovery retrieves relevant passages and sweeps every numeric clause. Two
extractors run: a **deterministic matrix parser** (table cells → provable candidates) and an **LLM**
(prose clauses). All candidates flow into the **verifier**, which sorts them into four buckets. Only
**verified** rules reach GIS, the dashboard's "GIS Handoff," and feed the map.

---

## 6. The two extractors

**(a) Matrix extractor — deterministic, no LLM guessing.** Burnaby's bylaw packs most of its rules into
one dimensional table (dwelling‑type × dimension). The matrix parser reads the table geometry and emits
one candidate per cell. **81 of Burnaby's 87 verified rules come from this path** — and because it is
deterministic, those candidates carry their own table‑cell proof.

**(b) LLM extractor — prose clauses.** For sentences ("the maximum building height is 11.0 metres"), the
LLM (`google/gemini-3.1-flash-lite`, chosen by an A/B over the deterministic verifier) proposes
structured candidates. It is *only a proposer*; everything it returns must still pass the verifier.

```python
# Each candidate is just structured fields + a citation — never a decision:
{
  "rule_object": "height", "constraint_type": "max", "operator": "<=",
  "value": "11.0", "unit": "m", "constraint_scope": "building",
  "applies_to": "R-CG District",
  "source": {"page": 472, "section": "541(1)",
             "evidence_text": "the maximum building height is 11.0 metres measured from grade"}
}
```

---

## 7. The deterministic verifier — the heart of the system

Every candidate is checked against its **cited evidence text**. A rule is `verified` **only if it has no
blocking support gap.** The gates are plain, auditable functions — not a model.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 250" font-family="Inter, sans-serif" font-size="12.5">
  <defs><marker id="b" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#57606a"/></marker></defs>
  <rect x="10" y="100" width="110" height="50" rx="10" fill="#fff" stroke="#d0d7de" stroke-width="1.5"/>
  <text x="65" y="129" text-anchor="middle" fill="#1f2328" font-weight="700">candidate</text>
  <!-- gates -->
  <g>
    <rect x="160" y="20" width="150" height="34" rx="8" fill="#fff" stroke="#d0d7de"/><text x="235" y="42" text-anchor="middle">value in evidence?</text>
    <rect x="160" y="62" width="150" height="34" rx="8" fill="#fff" stroke="#d0d7de"/><text x="235" y="84" text-anchor="middle">unit compatible?</text>
    <rect x="160" y="104" width="150" height="34" rx="8" fill="#fff" stroke="#d0d7de"/><text x="235" y="126" text-anchor="middle">operator/direction?</text>
    <rect x="160" y="146" width="150" height="34" rx="8" fill="#fff" stroke="#d0d7de"/><text x="235" y="168" text-anchor="middle">scope supported?</text>
    <rect x="160" y="188" width="150" height="34" rx="8" fill="#fff" stroke="#d0d7de"/><text x="235" y="210" text-anchor="middle">shape sane? (not a ratio,</text>
  </g>
  <text x="235" y="244" text-anchor="middle" fill="#57606a" font-size="11">range bound, easement, definition…)</text>
  <!-- decision -->
  <rect x="360" y="95" width="150" height="60" rx="10" fill="#f6f8fa" stroke="#0969da" stroke-width="1.5"/>
  <text x="435" y="120" text-anchor="middle" fill="#0969da" font-weight="700">any blocking</text>
  <text x="435" y="137" text-anchor="middle" fill="#0969da" font-weight="700">gap?</text>
  <!-- outcomes -->
  <rect x="560" y="20" width="170" height="34" rx="8" fill="#f6fbf7" stroke="#1a7f37"/><text x="645" y="42" text-anchor="middle" fill="#1a7f37" font-weight="700">none → VERIFIED</text>
  <rect x="560" y="70" width="170" height="34" rx="8" fill="#fdf7ec" stroke="#9a6700"/><text x="645" y="92" text-anchor="middle" fill="#9a6700">soft gap → REVIEW</text>
  <rect x="560" y="120" width="170" height="34" rx="8" fill="#fcebec" stroke="#cf222e"/><text x="645" y="142" text-anchor="middle" fill="#cf222e">value/unit wrong → REJECT</text>
  <rect x="560" y="170" width="170" height="34" rx="8" fill="#f3f4f6" stroke="#57606a"/><text x="645" y="192" text-anchor="middle" fill="#57606a">out of scope → NOT USED</text>
  <line x1="120" y1="125" x2="158" y2="60" stroke="#57606a" marker-end="url(#b)"/>
  <line x1="120" y1="125" x2="158" y2="205" stroke="#57606a" marker-end="url(#b)"/>
  <line x1="310" y1="125" x2="358" y2="125" stroke="#57606a" marker-end="url(#b)"/>
  <line x1="510" y1="115" x2="558" y2="37" stroke="#57606a" marker-end="url(#b)"/>
  <line x1="510" y1="125" x2="558" y2="87" stroke="#57606a" marker-end="url(#b)"/>
  <line x1="510" y1="130" x2="558" y2="137" stroke="#57606a" marker-end="url(#b)"/>
  <line x1="510" y1="140" x2="558" y2="187" stroke="#57606a" marker-end="url(#b)"/>
</svg>

The decision logic is one small, audited function — the only place a bucket is assigned:

```python
# decision_policy.py — the entire safety tiering, in one readable place
def verification_decision_from_gaps(support_gaps: list[str]) -> str:
    blocking = set(support_gaps) - ADVISORY_GAPS      # advisory notes never block
    if not blocking:                       return VERIFIED       # every gate passed
    if CRITICAL_REJECTION_GAPS & blocking: return REJECTED       # value/unit absent or contradicted
    if NOT_USED_GAPS & blocking:           return NOT_USED       # out of contract / a definition
    return REVIEW_NEEDED                                          # a human can repair the rest
```

**Tiering rationale (why it's safe but not brittle):** a *value or unit absent from the evidence* is a
**hard reject** — the citation itself is wrong. A *scope/wording miss* is **review** — the value is real,
the phrasing just wasn't recognized, and a human or better evidence can repair it. This is why precision
stays 1.0 while genuine rules are never silently destroyed.

---

## 8. The safety contract (what can *never* break)

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 120" font-family="Inter, sans-serif" font-size="12.5">
  <path d="M40,10 L100,10 L100,70 Q100,100 70,108 Q40,100 40,70 Z" fill="#f6fbf7" stroke="#1a7f37" stroke-width="2"/>
  <text x="70" y="55" text-anchor="middle" fill="#1a7f37" font-weight="700" font-size="22">✓</text>
  <text x="130" y="28" fill="#1f2328" font-weight="700">false_verified_count = 0</text>
  <text x="130" y="50" fill="#1f2328" font-weight="700">verified_precision = 1.0</text>
  <text x="130" y="72" fill="#1f2328" font-weight="700">source_support_failures = 0</text>
  <text x="130" y="94" fill="#1f2328" font-weight="700">adversarial: ALL BLOCKED  ·  full test suite green</text>
  <text x="470" y="28" fill="#57606a">— no verified rule contradicts source</text>
  <text x="470" y="50" fill="#57606a">— every verified rule is gold-consistent</text>
  <text x="470" y="72" fill="#57606a">— every value is literally in the citation</text>
  <text x="470" y="94" fill="#57606a">— poisons can never enter `verified`</text>
</svg>

These are pinned by automated tests (`tests/test_slim_verifier.py`, `tests/test_adversarial_hardening.py`,
`tests/test_m7_safety_gates.py`). **No change is allowed to ship that breaks them** — proven this very
release when a recall‑raising experiment (see §10) was reverted because it nicked precision.

---

## 9. Outputs

- **`verified_rules.json`** — the full audited rule set (the raw trail).
- **`gis_rule_contract.json`** — slim, deduplicated, verified‑only rules for the GIS team (the file they consume).
- **`gis_felt_export.json`** — map‑ready: each setback carries a geometry (`offset_inward`, `rear_lot_line`) and a `gis_ready` flag.
- **Dashboard** ("Civic Console", 4 tabs: Summary · Review Queue · GIS Handoff · Ask the Bylaw) — every
  count drills down to the exact rules behind it.
- **Chatbot** — a grounded, multi‑turn assistant: it retrieves bylaw sections (hybrid BM25 + cross‑encoder
  rerank), answers with `gemini-3.1-flash-lite`, and **cites the section** for every claim. It is advisory
  and can never verify/approve/reject a rule.

---

## 10. How we know it is accurate (and the most important lesson)

**Ground‑truth audit (M7).** We did not trust our own gold. We read the *actual bylaw PDFs* and checked
every verified rule's value/unit/operator/scope against the real text:

| City | Verified | Accurate vs PDF | False‑verifies |
|---|---|---|---|
| Burnaby R1 | 87 | 87 / 87 | **0** |
| Calgary R‑CG | 29 | 29 / 29 | **0** |
| Vancouver RS | 10 | 10 / 10 | **0** |

The audit caught one real defect the gold benchmark *couldn't*: a rule that read Calgary §539(4)'s
*"1.2 metre private maintenance easement"* as a 1.2 m side setback (the clause actually grants a **zero**
setback). The gold missed it because 1.2 m coincides with the real side‑setback value — only reading the
PDF exposed it. We added a deterministic guard (a setback value glued to "easement" is held) and pinned
it with a test.

**The lesson (don't relitigate).** We also *tried* to raise recall by auto‑promoting confident
single‑source LLM candidates (a "co‑location proof"). It injected real false‑verifies
(`dwelling_units ≤ 1` from a "1 to 3 units" range; a separation read from a height clause) and was
**reverted**. The verifier's conservatism is *legitimate safety*, not over‑caution. **Recall is raised by
better extraction, never by a looser verifier.**

---

## 11. Why it is excellent / innovative

1. **Propose‑then‑verify with a deterministic sole authority.** Matches the 2025/26 SOTA recipe for
   text‑and‑table legal extraction, and gives a *provable* zero‑false‑verify guarantee that pure‑LLM or
   pure‑RAG systems cannot (those still hallucinate 17–33% of citations).
2. **Deterministic matrix extraction.** Dimensional tables — where most dwelling rules live and where LLMs
   mangle columns — become cell‑by‑cell *provable* candidates (81/87 of Burnaby).
3. **Honest measurement.** Coverage is reported against a *scored legal‑slot denominator*, not an inflated
   raw count; recall is measured against independently authored gold; and we audit against the **real PDFs**.
4. **Closed leak classes as named, tested gates** — operator‑fill inversion, ratio‑coefficient,
   range‑lower‑bound, foreign‑unit, definition‑sentence, allowance‑trigger, easement‑width. Each is a
   one‑line, auditable rule with a regression test.
5. **Generalizes across cities** (config‑driven targets, token‑robust scope vocab) without overfitting —
   the same verifier serves Burnaby, Calgary, and Vancouver unchanged.

---

## 12. What's new in M7 (generational changes)

- Fixed a real bug: the product pipeline ignored `provenance.pages` (Calgary spanned the whole 1,053‑page
  bylaw). Now page‑scoped → focused extraction + honest denominator.
- Single, strongest experimented model (`gemini-3.1-flash-lite`) on the **matrix‑aware** pipeline:
  **Calgary 16→30 verified (recall 0.84→1.0)**, **Burnaby 84→87 (recall →0.97)**, Vancouver recall 1.0.
- Chatbot upgraded to two‑stage retrieval + **cross‑encoder rerank** (fixes "what's the max height?").
- Full structural rename to the M7 generation (`m7_runs`, `m7_measure`), consolidation of dead lanes, and
  a dashboard "Civic Console" with count drill‑downs.
- New CI safety gate + ground‑truth PDF audit + the easement / range‑bound leak fixes above.

---

## 13. How to run it

```bash
# 1. Extract + verify a city through the matrix-aware product pipeline (writes outputs/m7_runs/<city>/<model>/)
.venv/bin/python scripts/run_m4_bakeoff.py --city calgary_rcg --models google/gemini-3.1-flash-lite

# 2. Measure (scored coverage, benchmark, slot audit) -> outputs/m7_measure/<run-id>/
.venv/bin/python scripts/run_m7_measure.py --run-id m7_gemini31_final_20260616 --model google/gemini-3.1-flash-lite

# 3. Safety gates
.venv/bin/python -m pytest -q
.venv/bin/python benchmark/evaluate_adversarial.py --config configs/calgary_rcg.json --cases benchmark/gold/calgary_rcg_adversarial_cases.json

# 4. Explore (dashboard + grounded chatbot; reads OPENROUTER_API_KEY from .env)
.venv/bin/python -m streamlit run dashboard/streamlit_app.py --server.port 8501
```

---

## 14. Code structure (the map)

```text
src/burnaby_prototype/
  verification.py        ← the deterministic verifier (field gates, support checks)
  decision_policy.py     ← gap → bucket tiering (the ONLY place a decision is made)
  support_checks.py      ← value/unit/operator/scope "is it in the evidence?" checks
  v3_discovery.py        ← retrieval + exhaustive rule-signal sweep (proposer)
  v2_matrix_candidates.py← deterministic table-cell extraction (proposer)
  native_extraction.py   ← OpenRouter LLM client + reranker (proposer)
  gis_felt_export.py     ← verified rules → map-ready geometry
  slim_pipeline.py       ← verified → slim GIS contract (deduplicated)
  m7_measure.py          ← scored-coverage / benchmark measurement layer
scripts/                 ← run_m4_bakeoff (extract+verify), run_m7_measure (measure)
dashboard/streamlit_app.py ← Civic Console + grounded chatbot
benchmark/               ← gold rules, adversarial cases, evaluators
docs/M7_FINAL_RELEASE.md ← the M7 release runbook + numbers
```

---

## 15. Honest limitations & future work

- **Recall is bounded by safety.** Some genuinely‑true rules stay in `review` (heritage conditionals,
  exceptions, single‑source prose). That is by design — promoting them risks false‑verifies.
- **Scored coverage is still modest** (Calgary 0.16, Vancouver 0.09) because many real district rules
  aren't yet *extracted*; the lever is richer extraction, not a looser gate.
- **Provenance labels can lag** (a few Calgary rows cite §534 where the clause is §535 — value/page
  correct). Fix belongs at the extraction section‑attribution step.
- **Vancouver** would benefit from a larger authored gold (principal/duplex/triplex sections) — a
  multi‑week effort deferred past M7.

> **Bottom line:** the system is a trustworthy *proposer‑plus‑deterministic‑verifier*. It is honest about
> what it does not know, it never lets a wrong rule into `verified`, and it gives humans a clean queue for
> the rest. That combination — high recall on the easy rules, zero false‑verifies, and an auditable gate —
> is what makes it ready to hand to a GIS team.
