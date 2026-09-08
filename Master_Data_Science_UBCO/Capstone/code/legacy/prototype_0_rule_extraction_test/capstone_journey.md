#  Laneway House Rule Extraction Pipeline Test

---

## My Workflow

### Step 1 — City Registry & PDF Config

I started by building a **city registry** that captures the key facts about each municipality before any extraction happens: what they call a laneway dwelling, which zone it applies to, which bylaw section to look at, and any important caveats (e.g., Vancouver's laneway rules live in Section 11, not in the R1-1 schedule sections 3 and 4 that govern the principal house).

Each city also has a PDF config that points to the source bylaw PDF and a source URL for traceability.

### Step 2 — Rule Config

I defined the zoning rules I want to extract as structured configs, starting with two:

- `max_lot_coverage` — the maximum percentage of the lot that buildings can occupy
- `min_setback` — minimum distance buildings must sit from lot boundaries (front, side, rear, lane)

Each rule config includes keywords for finding relevant text, a description, expected units, and a few-shot example showing what correct input/output looks like. This is what gets fed into the LLM prompt.

### Step 3 — Block Cutting (PDF → Focused Text Chunks)

Rather than feeding an entire bylaw PDF to the LLM (which can be hundreds of pages), I built a **block cutting** step that:

1. Scans the PDF to find only pages containing relevant keywords
2. Splits those pages into section-level text blocks
3. Applies a `MAX_BLOCKS` limit per rule to prevent the LLM from reading too much irrelevant content

For most cities I use a **section-based strategy** (splitting on section numbers like `3.2.2.4`). For Surrey, where the bylaw structure is less clean, I use an **LLM-assisted strategy** where a first LLM call identifies which blocks are relevant before extraction begins.

### Step 4 — LLM Extraction (Optimized Prompt)

The main extraction step sends each text block to an LLM with a carefully engineered prompt that includes:

- City context (zone, laneway term, important caveats)
- A strict output schema (code, type, value, unit, operator, condition, exception, confidence)
- Few-shot examples of correct input/output
- Explicit "DO NOT" rules (e.g., don't include units in the value field, don't return confidence > 1.0)

The pipeline supports three backends automatically: **Claude API → Ollama (local)**. Right now I've been running on Ollama with `qwen2:1.5b` since I don't always have API access during development.

### Step 5 — Second-Pass Search

After the first extraction, a second LLM call checks whether anything was missed — other value variants for different conditions, exceptions, or lot-size-based thresholds. This was adapted from Zihao's approach on the team.

### Step 6 — Ground Truth & Accuracy Scoring

I manually verified the correct rules from the official PDFs and stored them as ground truth. The accuracy scorer then compares extracted rules against ground truth at three levels: exact match (both value and condition match), partial match (value correct but condition wrong), and miss.

### Step 7 — Export

Final output is a structured CSV and JSON file with fields for municipality, zone, rule type, value, unit, condition, exception, confidence, and review status. Anything below 0.80 confidence is flagged as `needs_review`.

---

## Accuracy Experiment (In Progress)

I set up a formal accuracy experiment to measure how well the pipeline extracts rules compared to manually verified ground truth. The experiment runs all active cities × active rules and scores each result at three levels: **exact match** (value and condition both correct), **partial match** (value correct but condition differs), and **miss**.

Results from this experiment are still being collected and will be reported once the full evaluation is complete.

---

## Challenges I'm Running Into

### Issue 1: Value Format Not Respected

Even with few-shot examples explicitly showing the correct format, the model still adds units into the value field.

- **Expected:** `{"value": "50", "unit": "%"}`
- **Got:** `{"value": "50%", "unit": "%"}`

This means the value field is unparseable as a number downstream without post-processing, and it happens consistently with `qwen2:1.5b` despite the prompt instructions.

### Issue 2: Confidence Score Hallucination

The model returns confidence values outside the valid 0.0–1.0 range, indicating it doesn't actually understand the constraint.

- **Expected:** `{"confidence": 0.95}`
- **Got:** `{"confidence": 1.58}`

This makes the confidence field unreliable as a signal for flagging low-quality extractions — which is one of its core purposes in the pipeline.

### Issue 3: Cross-City Contamination

Vancouver section code `3.2.2.4` appeared in Surrey and Burnaby results. When blocks are large (up to 18 blocks for `min_setback`), the LLM mixes information from different cities — likely because earlier context in the prompt bleeds into later extractions. This is a serious correctness issue, not just a formatting one.

### Issue 4: Operator Confusion

The model returns nonsensical operator values that don't reflect what the bylaw actually says.

- **Expected:** `{"operator": "<="}`  (max lot coverage is a ceiling)
- **Got:** `{"operator": "+"}`

This suggests the model isn't reasoning about rule semantics — it's pattern-matching on surface text without understanding what operators mean in this context.

### Issue 5: Second-Pass Duplicates

The second-pass search, which is designed to find *missing* conditions, instead duplicated all existing rules without finding anything new.

- **First extraction:** 3 rules → **After second pass:** 6 rules (all duplicates)

The second-pass prompt needs to be more constrained so the model returns only genuinely new items, not re-extractions of what was already found.

### Issue 6: Every City's Bylaw is Structured Differently

Separate from the model issues above, each municipality requires its own reading strategy just to locate the right rules. Vancouver's laneway rules are split across two PDFs with the laneway-specific content in Section 11, not in the R1-1 schedule. Burnaby uses a lot-size threshold table that spans multiple blocks. Surrey nests coach house rules inside a broader accessory building section with a different naming convention. This structural variation makes a single generic extraction approach insufficient.

---
