#!/usr/bin/env python3
"""Generate notebook 15: 15_two_stage_rule_extraction.ipynb"""

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent / "15_two_stage_rule_extraction.ipynb"


def code_cell(id_, source):
    return {
        "id": id_,
        "cell_type": "code",
        "metadata": {},
        "source": source,
        "outputs": [],
        "execution_count": None,
    }


def md_cell(id_, source):
    return {
        "id": id_,
        "cell_type": "markdown",
        "metadata": {},
        "source": source,
    }


cells = []

# ── Title ─────────────────────────────────────────────────────────────────────
cells.append(md_cell("cell-title",
"""# Two-Stage Rule Extraction — Surrey (Coach House)

**Notebook 15** — two-stage pipeline based on notebook 13.

**Stage 1**: Extract ALL rules from each block (no building-type topic filter).
**Stage 2**: Classify each rule's relevance: `direct` / `indirect` / `generic_applicable` / `definition_or_reference` / `unrelated`.
**Coverage check**: Second LLM call to audit table blocks, exception-heavy blocks, and zero-rule blocks.

Input: `selected_blocks_auto.jsonl` from notebook 12 (falls back to notebook 07's output if absent).
Output: 5 files in `outputs/15_two_stage_rule_extraction/`."""))

# ── cell-config ───────────────────────────────────────────────────────────────
cells.append(code_cell("cell-config",
"""import json
import re
import time
from pathlib import Path

import pandas as pd
import requests
from tqdm.auto import tqdm

# ── Input ─────────────────────────────────────────────────────────────────────
SELECTED_BLOCKS_JSONL = Path("outputs/12_auto_block_selection/selected_blocks_auto.jsonl")
FALLBACK_BLOCKS_JSONL = Path("outputs/07_test_bylaw_block_normalization_pipeline/selected_blocks_test.jsonl")
ALL_BLOCKS_JSONL      = Path("outputs/07_test_bylaw_block_normalization_pipeline/blocks_test.jsonl")

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path("outputs/15_two_stage_rule_extraction")

# ── Model settings ────────────────────────────────────────────────────────────
MODEL_NAME      = "qwen35-rules"
OLLAMA_URL      = "http://localhost:11434/api/generate"
NUM_CTX         = 32768
NUM_PREDICT     = 8000
TEMPERATURE     = 0.0
REQUEST_TIMEOUT = 3600
MAX_BLOCK_CHARS = 12000
SAVE_EMPTY_RESULTS = False

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
print(f"OUTPUT_DIR          : {OUTPUT_DIR}")
print(f"SELECTED_BLOCKS_JSONL exists: {SELECTED_BLOCKS_JSONL.exists()}")
print(f"FALLBACK_BLOCKS_JSONL exists: {FALLBACK_BLOCKS_JSONL.exists()}")"""))

# ── cell-md-docconfig ─────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-docconfig", "# City / Document configuration\n\nSurrey only for this notebook."))

# ── cell-docconfig ────────────────────────────────────────────────────────────
cells.append(code_cell("cell-docconfig",
"""DOC_CONFIGS = {
    "surrey_zoning_12000": {
        "city": "Surrey",
        "building_type": "Coach House",
        "target_terms": ["coach house"],
        "zone": "R1",
        # Used by the two-stage prompt to explain relevance_category classification.
        "target_description": (
            "Target building type: Coach House (Surrey R1 zone).\\n"
            "Classify each extracted rule's relevance_category as follows:\\n"
            "  direct            — the rule explicitly names 'Coach House' or uses a term in target_terms.\\n"
            "  indirect          — the rule applies to a parent category that includes Coach House\\n"
            "                      (e.g. 'accessory building', 'small-scale multi-unit housing', 'garden suite').\\n"
            "  generic_applicable— the rule applies to all buildings, all uses, or the entire lot\\n"
            "                      with no building-type restriction.\\n"
            "  definition_or_reference — the rule is a definition, purpose clause, or cross-reference.\\n"
            "  unrelated         — the rule applies only to a different specific building type\\n"
            "                      (e.g. principal dwelling, duplex, garage, fence, pool)\\n"
            "                      and does not include Coach House or its parent categories."
        ),
    },
}


def get_doc_config(block):
    doc_id = block.get("doc_id", "")
    if doc_id in DOC_CONFIGS:
        return DOC_CONFIGS[doc_id]
    city = (block.get("city") or "").strip()
    for cfg in DOC_CONFIGS.values():
        if cfg["city"] == city:
            return cfg
    return next(iter(DOC_CONFIGS.values()))


print("DOC_CONFIGS loaded:", list(DOC_CONFIGS.keys()))"""))

# ── cell-md-profiles ──────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-profiles",
"""# Topic profiles + auto detection

Topic profiles are kept for automatic topic labelling only.
The two-stage extraction prompt does **not** use allowed/blocked key lists to filter.
Topic labels are attached to each rule row for reference."""))

# ── cell-profiles ─────────────────────────────────────────────────────────────
cells.append(code_cell("cell-profiles",
"""TOPIC_PROFILES = {
    "permitted_uses": {
        "allowed_rule_keys": ["coach_house_permitted_accessory_use",
            "coach_house_or_garden_suite_permitted_accessory_use",
            "coach_house_allowed_if_max_dwelling_units_not_exceeded",
            "coach_house_permission_condition", "laneway_permitted_conditions", "ssmuh_max_units"],
        "blocked_rule_keys": ["max_lot_coverage", "min_back_setback", "max_height_m",
            "floorspace_area_limit", "max_fsr", "parking_requirements", "min_site_width_m"],
        "extraction_mode": "permitted_uses_only",
        "condition_scope": "same_table_or_same_note_only",
        "notes": "Extract permission/use rules only.",
    },
    "floor_area": {
        "allowed_rule_keys": ["floorspace_area_limit", "max_fsr"],
        "blocked_rule_keys": ["max_lot_coverage", "min_back_setback", "max_height_m",
            "parking_requirements", "min_site_width_m", "max_site_coverage_laneway"],
        "extraction_mode": "floor_area_only",
        "condition_scope": "same_table_row_or_same_header_only",
        "notes": "Extract floor area and FSR rules only.",
    },
    "lot_coverage": {
        "allowed_rule_keys": ["max_lot_coverage", "max_impervious_surface",
            "max_site_coverage_laneway", "calculated_lot_coverage_formula"],
        "blocked_rule_keys": ["floorspace_area_limit", "max_fsr", "min_back_setback",
            "max_height_m", "min_site_width_m"],
        "extraction_mode": "lot_coverage_only",
        "condition_scope": "same_table_row_or_same_header_only",
        "notes": "Extract lot/site coverage rules only.",
    },
    "setbacks": {
        "allowed_rule_keys": ["min_front_setback", "min_back_setback", "min_side_setback",
            "main_street_side_setback", "min_other_separation", "min_lane_yard_setback",
            "min_separation_rear_principals", "min_separation_front_rear_principals",
            "min_separation_laneway_to_main", "min_rear_setback_laneway",
            "min_side_setback_laneway", "front_yard_not_permitted", "setback_reduction"],
        "blocked_rule_keys": ["max_height_m", "max_height_stories", "max_roof_peak_height",
            "floorspace_area_limit", "max_lot_coverage", "max_fsr"],
        "extraction_mode": "setbacks_only",
        "condition_scope": "same_table_row_or_same_header_only",
        "notes": "Extract setback, yard, and separation rules.",
    },
    "height": {
        "allowed_rule_keys": ["max_height_m", "max_height_stories", "max_roof_peak_height"],
        "blocked_rule_keys": ["min_back_setback", "min_side_setback", "max_lot_coverage",
            "floorspace_area_limit", "max_fsr", "min_site_width_m"],
        "extraction_mode": "height_only",
        "condition_scope": "same_table_row_or_same_note_only",
        "notes": "Extract height and storey limits only.",
    },
    "parking_access": {
        "allowed_rule_keys": ["parking_requirements", "required_extra_parking_spaces",
            "frequent_bus_stop_parking_exemption", "require_lane_access_small_lots",
            "allow_driveway_access_large_lots", "max_unit_distance_no_sprinkler",
            "coach_house_parking_requirement", "coach_house_access_requirement",
            "coach_house_lane_access_requirement", "coach_house_driveway_access_permission",
            "coach_house_fire_access_sprinkler_requirement"],
        "blocked_rule_keys": ["max_height_m", "min_back_setback", "max_lot_coverage",
            "floorspace_area_limit", "min_site_width_m"],
        "extraction_mode": "parking_access_only",
        "condition_scope": "same_clause_or_same_table_only",
        "notes": "Extract parking and access rules only.",
    },
    "room_requirements": {
        "allowed_rule_keys": ["min_habitable_room_size", "min_bedroom_size",
            "min_bedroom_units_requirement"],
        "blocked_rule_keys": ["max_height_m", "min_back_setback", "max_lot_coverage",
            "floorspace_area_limit", "min_site_width_m"],
        "extraction_mode": "room_requirements_only",
        "condition_scope": "same_lettered_clause_only",
        "notes": "Extract bedroom and habitable room size/count requirements only.",
    },
    "site_dimensions": {
        "allowed_rule_keys": ["min_site_width_m", "site_width_discretion"],
        "blocked_rule_keys": ["floorspace_area_limit", "max_height_m",
            "max_lot_coverage", "min_back_setback"],
        "extraction_mode": "site_dimensions_only",
        "condition_scope": "same_clause_only",
        "notes": "Extract site width and similar site dimension requirements only.",
    },
    "development_regulations": {
        "allowed_rule_keys": [],
        "blocked_rule_keys": ["parking_requirements", "is_heritage", "tree_retention",
            "water_or_sewer_unit_limit", "frequent_transit_network_area",
            "transit_oriented_area_max_units"],
        "extraction_mode": "development_regulations",
        "condition_scope": "same_table_row_or_same_column_header_only",
        "notes": "Multi-topic block: extract all dimensional limits.",
    },
}

DEFAULT_TOPIC_PROFILE = {
    "allowed_rule_keys": [],
    "blocked_rule_keys": [],
    "extraction_mode": "development_regulations",
    "condition_scope": "same_clause_or_same_table_only",
    "notes": "",
}
DEFAULT_BLOCK_PROFILE = DEFAULT_TOPIC_PROFILE

TOPIC_DETECTION_KEYWORDS = {
    "permitted_uses":    ["permitted use", "permitted uses", "accessory use", "is permitted", "may be used"],
    "floor_area":        ["floor area", "floor space ratio", "fsr", "floor space"],
    "lot_coverage":      ["lot coverage", "site coverage", "impervious surface"],
    "setbacks":          ["setback", "rear yard", "front yard", "side yard", "separation",
                          "lot line", "property line", "lane yard"],
    "height":            ["height", "storey", "storeys", "roof peak", "ridge height"],
    "parking_access":    ["parking", "off-street parking", "lane access", "driveway",
                          "sprinkler", "fire access"],
    "room_requirements": ["habitable room", "bedroom", "room size"],
    "site_dimensions":   ["site width", "lot width", "frontage"],
}

EXCEPTION_CUE_PATTERNS = [
    "despite", "except", "exception", "unless", "provided that",
    "if", "where", "provided", "may be reduced", "may be increased",
    "may be relaxed", "up to a maximum", "notwithstanding", "subject to",
]


def detect_block_topic(block: dict) -> str:
    heading_probe = " ".join([
        (block.get("title") or ""),
        (block.get("section") or ""),
        (block.get("text") or "")[:100],
    ]).lower()
    if "development regulation" in heading_probe:
        return "development_regulations"
    probe = " ".join([
        (block.get("title") or ""),
        (block.get("section") or ""),
        (block.get("text") or "")[:500],
    ]).lower()
    scores: dict[str, int] = {}
    for topic, keywords in TOPIC_DETECTION_KEYWORDS.items():
        score = sum(probe.count(kw.lower()) for kw in keywords)
        if score > 0:
            scores[topic] = score
    if len(scores) >= 3:
        return "development_regulations"
    return max(scores, key=scores.get) if scores else "development_regulations"


print(f"TOPIC_PROFILES defined  : {list(TOPIC_PROFILES.keys())}")
print(f"detect_block_topic ready: yes")"""))

# ── cell-md-loadblocks ────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-loadblocks", "# Load blocks from JSONL — Surrey only"))

# ── cell-loadblocks ───────────────────────────────────────────────────────────
cells.append(code_cell("cell-loadblocks",
"""# ── Full blocks dict for parent-block markdown lookups ───────────────────────
jsonl_blocks_by_id: dict[str, dict] = {}
if ALL_BLOCKS_JSONL.exists():
    with open(ALL_BLOCKS_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                b = json.loads(line)
                jsonl_blocks_by_id[b["block_id"]] = b
            except Exception:
                pass
print(f"All JSONL blocks loaded : {len(jsonl_blocks_by_id)}")


def enrich_block(block: dict) -> dict:
    block = dict(block)
    topic = detect_block_topic(block)
    profile = dict(DEFAULT_TOPIC_PROFILE)
    profile.update(TOPIC_PROFILES.get(topic, {}))
    block["detected_topic"] = topic
    for key in ["allowed_rule_keys", "blocked_rule_keys",
                "extraction_mode", "condition_scope", "notes"]:
        block[key] = profile.get(key, DEFAULT_TOPIC_PROFILE.get(key))
    block.setdefault("focus", profile.get("extraction_mode", topic))
    return block


# ── Select input JSONL ────────────────────────────────────────────────────────
input_jsonl = (
    SELECTED_BLOCKS_JSONL if SELECTED_BLOCKS_JSONL.exists()
    else FALLBACK_BLOCKS_JSONL
)
print(f"Input JSONL : {input_jsonl}")

# ── Load and enrich ───────────────────────────────────────────────────────────
_all_blocks: list[dict] = []
with open(input_jsonl, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            _all_blocks.append(enrich_block(json.loads(line)))
        except Exception:
            pass

# ── Filter to Surrey only ─────────────────────────────────────────────────────
selected_blocks = [b for b in _all_blocks if b.get("doc_id") == "surrey_zoning_12000"]

print(f"\\nAll blocks loaded : {len(_all_blocks)}")
print(f"Surrey blocks     : {len(selected_blocks)}")
for b in selected_blocks:
    print(
        f"  [{b.get('city','?'):<10}] {b.get('block_id','?'):<60} "
        f"topic={b.get('detected_topic','?')}"
    )"""))

# ── cell-md-schema ────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-schema",
"""# Canonical rule schema

Same schema as notebook 13.
`relevance_category` is added as an output field on each rule object (not a canonical key)."""))

# ── cell-schema ───────────────────────────────────────────────────────────────
cells.append(code_cell("cell-schema",
"""CANONICAL_RULE_SCHEMA = {
    # ── Surrey / general ──────────────────────────────────────────────────────
    "max_lot_coverage": "Maximum percentage of lot/site area that buildings may cover.",
    "min_front_setback": "Minimum front yard/front lot line setback.",
    "front_yard_not_permitted": "Use when the relevant building is explicitly not permitted in the front yard.",
    "min_side_setback": "Minimum interior side yard/side lot line setback.",
    "min_back_setback": "Minimum rear yard/rear lot line setback.",
    "main_street_side_setback": "Minimum setback from flanking street-side lot line.",
    "min_other_separation": "Minimum separation between two buildings on the same lot (general).",
    "setback_reduction": "Conditional reduction or relaxation of a required setback or separation.",
    "max_height_m": "Maximum building height in metres.",
    "max_height_stories": "Maximum number of storeys.",
    "max_roof_peak_height": "Maximum roof peak/ridge height.",
    "floorspace_area_limit": "Absolute minimum or maximum floor area in m2.",
    "max_fsr": "Maximum floor space ratio. Do not use for absolute m2 floor area caps.",
    "parking_requirements": "General parking rule or cross-reference to a parking table.",
    "required_extra_parking_spaces": "Numeric number of additional off-street parking spaces required.",
    "ssmuh_max_units": "Maximum number of dwelling units allowed on a lot/site.",
    "frequent_transit_network_area": "Whether lot is inside a frequent transit network or overlay area.",
    "transit_oriented_area_max_units": "Maximum dwelling units inside Transit-Oriented Areas.",
    "frequent_bus_stop_parking_exemption": "Parking reduction/exemption due to frequent bus stop proximity.",
    "require_lane_access_small_lots": "Lane or rear access requirement for small lots.",
    "allow_driveway_access_large_lots": "Driveway/front access allowance when lane access is not required.",
    "max_unit_distance_no_sprinkler": "Maximum distance threshold before sprinkler/fire access requirement applies.",
    "is_heritage": "Heritage status condition or exception.",
    "tree_retention": "Required retained trees or tree retention rule.",
    "water_or_sewer_unit_limit": "Unit limit when water/sewer service is unavailable.",
    "coach_house_permitted_accessory_use": "Coach House is explicitly permitted as an accessory use.",
    "coach_house_or_garden_suite_permitted_accessory_use": "Shared permission rule explicitly covering Coach House or Garden Suite.",
    "coach_house_allowed_if_max_dwelling_units_not_exceeded": "Coach House permission tied to not exceeding maximum dwelling units.",
    "coach_house_permission_condition": "Other explicit condition on Coach House permission.",
    "coach_house_parking_requirement": "Parking requirement explicitly for Coach House.",
    "coach_house_access_requirement": "Access rule explicitly for Coach House.",
    "coach_house_lane_access_requirement": "Lane or rear access requirement explicitly for Coach House.",
    "coach_house_driveway_access_permission": "Driveway/front access permission explicitly for Coach House.",
    "coach_house_fire_access_sprinkler_requirement": "Fire access, distance, or sprinkler rule explicitly for Coach House.",
    "exception_or_override": "A general exception, override, or special case that changes a base rule.",
    "calculated_lot_coverage_formula": "Lot coverage expressed as a reduction formula.",
    # ── Burnaby ───────────────────────────────────────────────────────────────
    "min_lane_yard_setback": "Minimum setback from a lane (rear lane yard).",
    "max_impervious_surface": "Maximum percentage of the lot covered by impervious surfaces.",
    "min_separation_rear_principals": "Minimum separation between two Rear Principal Buildings.",
    "min_separation_front_rear_principals": "Minimum separation between Front and Rear Principal Buildings.",
    "min_bedroom_units_requirement": "Minimum number of dwelling units that must have at least 3 bedrooms.",
    # ── Vancouver ─────────────────────────────────────────────────────────────
    "laneway_permitted_conditions": "Conditions under which a laneway house is permitted.",
    "min_site_width_m": "Minimum site width required.",
    "site_width_discretion": "Director of Planning discretion to reduce minimum site width.",
    "max_site_coverage_laneway": "Maximum site coverage when a laneway house is present.",
    "min_separation_laneway_to_main": "Minimum separation between laneway house and main dwelling.",
    "min_rear_setback_laneway": "Minimum setback of laneway house from rear property line.",
    "min_side_setback_laneway": "Minimum setback of laneway house from side property line.",
    "min_habitable_room_size": "Minimum floor area of main habitable room in a laneway house.",
    "min_bedroom_size": "Minimum floor area of a bedroom in a laneway house.",
}

# Relevance categories (output field, not a canonical key)
RELEVANCE_CATEGORIES = [
    "direct",               # rule explicitly names target building type
    "indirect",             # rule applies to parent category that includes target
    "generic_applicable",   # applies to all buildings / all uses on lot
    "definition_or_reference",  # definition, purpose clause, or cross-reference
    "unrelated",            # applies only to different specific building type
]

print(f"Canonical schema keys : {len(CANONICAL_RULE_SCHEMA)}")
print(f"Relevance categories  : {RELEVANCE_CATEGORIES}")"""))

# ── cell-md-blocktext ─────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-blocktext", "# Block text loading"))

# ── cell-blocktext ────────────────────────────────────────────────────────────
cells.append(code_cell("cell-blocktext",
"""def slice_text_by_markers(text: str, start_marker=None, stop_marker=None) -> str:
    if start_marker:
        idx = text.find(start_marker)
        if idx >= 0:
            text = text[idx:]
    if stop_marker:
        idx = text.find(stop_marker)
        if idx >= 0:
            text = text[:idx]
    return text.strip()


def load_block_text(block: dict) -> tuple[str, str]:
    block_id  = block.get("block_id")
    source_id = block.get("source_block_id") or block_id
    if source_id != block_id and source_id in jsonl_blocks_by_id:
        text = jsonl_blocks_by_id[source_id].get("markdown", "") or ""
        used = f"jsonl_parent:{source_id}"
    else:
        text = block.get("markdown") or block.get("text") or ""
        used = f"block_field:{block_id}"
    text = slice_text_by_markers(
        text, block.get("text_start_marker"), block.get("text_stop_marker"),
    )
    return text, used


for block in selected_blocks:
    text, src = load_block_text(block)
    block["block_text_path"]       = src
    block["block_text_exists"]     = bool(text)
    block["block_text_char_count"] = len(text)

print("Block text status:")
for b in selected_blocks:
    status = "OK" if b["block_text_exists"] else "MISSING"
    print(
        f"  [{b.get('city')}] {b.get('block_id')} [{status}] "
        f"{b['block_text_char_count']} chars  topic={b.get('detected_topic')}"
    )"""))

# ── cell-md-prompt ────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-prompt",
"""# Two-stage extraction prompt

**Key differences from notebook 13:**
- No topic profile `allowed_rule_keys` / `blocked_rule_keys` filter.
- Extracts ALL rules in the block regardless of building type.
- Each rule includes a `relevance_category` field (Stage 2 classification).
- `target_description` from DOC_CONFIGS defines the relevance classification criteria."""))

# ── cell-prompt-v2 ────────────────────────────────────────────────────────────
cells.append(code_cell("cell-prompt-v2",
"""def build_rule_extraction_prompt_v2(
    block_id, zone, pages, focus, block_text, doc_config=None
):
    # Two-stage extraction prompt.
    # Stage 1: extract ALL rules from the block (no building-type filter).
    # Stage 2: classify each rule's relevance_category in the same pass.
    doc_config    = doc_config or DOC_CONFIGS["surrey_zoning_12000"]
    building_type = doc_config.get("building_type", "Target Building")
    city          = doc_config.get("city", "Unknown")
    target_description = doc_config.get("target_description", "")
    target_terms  = doc_config.get("target_terms", [building_type.lower()])
    target_terms_str = ", ".join(f'"{t}"' for t in target_terms)

    schema_json         = json.dumps(CANONICAL_RULE_SCHEMA, ensure_ascii=False, indent=2)
    exception_cues_json = json.dumps(EXCEPTION_CUE_PATTERNS, ensure_ascii=False, indent=2)
    pages_text          = ", ".join(str(p) for p in pages)

    return f\'\'\'You are extracting ALL zoning bylaw rules from one pre-built text block.
This is a two-stage pipeline. You handle both stages in one pass.

Return one valid JSON object only. Top-level key must be "rules".
Do not use markdown. Do not include reasoning.

STAGE 1 - EXTRACT ALL RULES
Extract EVERY explicit rule from the block text regardless of building type.
Include: numeric limits, min/max values, permissions, prohibitions, conditions,
exceptions, reductions, definitions, cross-references, table rows and cells,
generic lot-wide rules, and any unfamiliar rule types.
Do not skip a rule because it applies to a different building type.
Do not use outside knowledge. Extract only what is explicitly stated in the text.
Prefer canonical rule keys. If no canonical key fits, create a city-specific
snake_case key and set schema_match to "city_specific".

Splitting rules:
- Split table rows, lot-size bands, building type conditions, and exceptions into
  separate rule objects only when the values or requirements differ.
- If a single sentence states both a minimum and a maximum, extract both separately.
- If a sentence states a base maximum plus a conditional higher/lower maximum,
  extract both as separate rule objects.
- If a base rule and reduction/exception both exist, extract both.
- Always scan for exception and override cue words in all block types.

Exception and override detection:
Exception/override cue patterns: {exception_cues_json}
- Treat clauses introduced by these cues as possible exceptions, relaxations, overrides.
- If an exception changes a base numeric limit or condition, output it as a separate rule.
- Put the exception trigger in the condition or exception field.
- Do not merge exception values into the base rule.

Source grounding:
- Every rule must include original_excerpt.
- original_excerpt must contain or directly support the extracted value.
- If the rule has a condition, original_excerpt must also support that condition.
- page must be one of the pages in the current block.

STAGE 2 - CLASSIFY RELEVANCE
For each extracted rule, set relevance_category using the criteria below.
{target_description}

Valid values for relevance_category: direct, indirect, generic_applicable,
definition_or_reference, unrelated.

CANONICAL RULE KEYS
{schema_json}

BLOCK METADATA
city: {city}
zone: {zone}
block_id: {block_id}
pages: [{pages_text}]
focus: {focus}

RETURN SCHEMA
{{
  "rules": [
    {{
      "city": "{city}",
      "zone": "{zone}",
      "block_id": "{block_id}",
      "building_type": "{building_type}",
      "term_used_in_document": null,
      "rule_type": null,
      "rule_key_suggestion": null,
      "schema_match": "canonical",
      "dedup_key": null,
      "description": null,
      "requirement_text": null,
      "value": null,
      "unit": null,
      "operator": null,
      "applies_to_zone": [],
      "condition": null,
      "exception": null,
      "prohibitive": false,
      "category": null,
      "page": null,
      "bylaw_section": null,
      "original_excerpt": null,
      "confidence": "high",
      "relevance_category": "direct"
    }}
  ]
}}

BLOCK TEXT
{block_text}\'\'\'.strip()


print("build_rule_extraction_prompt_v2 ready")"""))

# ── cell-md-coverage-prompt ───────────────────────────────────────────────────
cells.append(md_cell("cell-md-coverage-prompt",
"""# Coverage check prompt + parser

Called for:
- **Table blocks** (≥ 2 Markdown table rows in block text)
- **Exception-heavy blocks** (≥ 2 exception cue words)
- **Zero-rule blocks** (0 rules extracted)

Asks: "Were any rules missed in this block?" """))

# ── cell-coverage-prompt ──────────────────────────────────────────────────────
cells.append(code_cell("cell-coverage-prompt",
"""def build_coverage_check_prompt(block_id: str, building_type: str,
                                block_text: str, extracted_summary: str) -> str:
    return f\'\'\'You are auditing a zoning bylaw block for missed rules.

The following rules were already extracted from this block:
{extracted_summary}

Review the block text below and identify any rules, numeric limits, permissions,
prohibitions, conditions, or exceptions that are present in the text but were
NOT captured in the extracted rules above.

For each missed item, output one object with:
  description     - plain-English description of the missed rule
  rule_key_suggestion - best canonical or city_specific key
  original_excerpt - the exact text from the block that contains the missed rule
  reason_missed   - short tag: table_row_skipped / exception_not_extracted /
                    building_type_filtered / other

Return one valid JSON object only. Top-level key must be "missed_items".
If nothing was missed, return {{"missed_items": []}}.
Do not include reasoning outside the JSON. Do not use markdown.

Block metadata:
  block_id      : {block_id}
  building_type : {building_type}

Block text:
{block_text}\'\'\'.strip()


def parse_coverage_response(raw_text):
    # Parse a coverage check LLM response; returns (missed_items, status, error).
    text = re.sub(r"<think>.*?</think>", "", raw_text or "", flags=re.S | re.I).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "missed_items" in obj:
            return obj.get("missed_items") or [], "success", None
        return [], "failed", "Key 'missed_items' not found."
    except Exception as e1:
        # brace recovery
        start = text.find("{")
        if start >= 0:
            depth, in_string, esc = 0, False, False
            for i in range(start, len(text)):
                ch = text[i]
                if in_string:
                    if esc: esc = False
                    elif ch == "\\\\": esc = True
                    elif ch == '"': in_string = False
                else:
                    if ch == '"': in_string = True
                    elif ch == "{": depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                obj = json.loads(text[start:i + 1])
                                if "missed_items" in obj:
                                    return obj["missed_items"] or [], "success_brace_recovery", None
                            except Exception:
                                pass
                            break
    return [], "failed", str(e1)


def should_audit(block_text: str, rules: list) -> tuple[bool, str]:
    # Return (True, reason) if the block should receive a coverage check.
    # Table blocks
    table_rows = len(re.findall(r"^\|.+\|", block_text, re.MULTILINE))
    if table_rows >= 2:
        return True, "table_block"
    # Exception-heavy blocks
    exc_count = sum(1 for cue in EXCEPTION_CUE_PATTERNS if cue.lower() in block_text.lower())
    if exc_count >= 2:
        return True, "exception_heavy"
    # Zero-rule blocks
    if len(rules) == 0:
        return True, "zero_rules"
    return False, ""


print("Coverage check helpers ready: build_coverage_check_prompt, parse_coverage_response, should_audit")"""))

# ── cell-md-ollama ────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-ollama", "# Ollama helper"))

# ── cell-ollama ───────────────────────────────────────────────────────────────
cells.append(code_cell("cell-ollama",
"""def call_ollama(prompt):
    payload = {
        "model": MODEL_NAME,
        "prompt": "/no_think\\n" + prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": TEMPERATURE,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "top_p": 0.8,
        },
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    raw = data.get("response", "") or data.get("thinking", "")
    if not raw:
        raw = json.dumps(data, ensure_ascii=False)
    return raw, data"""))

# ── cell-md-parser ────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-parser", "# JSON parser (identical to notebook 13)"))

# ── cell-parser ───────────────────────────────────────────────────────────────
cells.append(code_cell("cell-parser",
"""def strip_markdown_fences(raw_text):
    text = raw_text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = text.strip()
    text = re.sub(r"^```(?:json)?\\s*", "", text, flags=re.I)
    text = re.sub(r"\\s*```$", "", text)
    return text.strip()


def extract_first_json_object(text):
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:        escape = False
            elif ch == "\\\\": escape = True
            elif ch == '"':   in_string = False
        else:
            if   ch == '"': in_string = True
            elif ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def extract_rule_array_objects(text):
    rules_match = re.search(r'"rules"\\s*:', text)
    if not rules_match:
        return []
    array_start = text.find("[", rules_match.end())
    if array_start < 0:
        return []
    objects, obj_start, obj_depth = [], None, 0
    in_string, escape = False, False
    for i in range(array_start + 1, len(text)):
        ch = text[i]
        if in_string:
            if escape:        escape = False
            elif ch == "\\\\": escape = True
            elif ch == '"':   in_string = False
        else:
            if   ch == '"': in_string = True
            elif ch == "{":
                if obj_depth == 0: obj_start = i
                obj_depth += 1
            elif ch == "}":
                if obj_depth > 0:
                    obj_depth -= 1
                    if obj_depth == 0 and obj_start is not None:
                        objects.append(text[obj_start:i + 1])
                        obj_start = None
            elif ch == "]" and obj_depth == 0:
                break
    return objects


def salvage_rule_objects(text):
    rules = []
    for candidate in extract_rule_array_objects(text):
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict) and (obj.get("rule_key_suggestion") or obj.get("dedup_key")):
            rules.append(obj)
    return rules


def parse_rules_object(raw_text):
    text = strip_markdown_fences(raw_text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "rules" in obj:
            return obj.get("rules") or [], "success", None
        return [], "failed", "JSON parsed but top-level key 'rules' was not found."
    except Exception as first_error:
        candidate = extract_first_json_object(text)
        if candidate:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict) and "rules" in obj:
                    return obj.get("rules") or [], "success_brace_recovery", None
                return [], "failed", "Recovered JSON parsed but 'rules' key not found."
            except Exception as second_error:
                salvaged = salvage_rule_objects(text)
                if salvaged:
                    return salvaged, "partial_success_salvaged", f"Direct: {first_error}; brace: {second_error}"
                return [], "failed", f"Direct: {first_error}; brace: {second_error}"
        salvaged = salvage_rule_objects(text)
        if salvaged:
            return salvaged, "partial_success_salvaged", f"Direct: {first_error}"
        return [], "failed", f"No JSON object found. Error: {first_error}"


print("Parser helpers ready")"""))

# ── cell-md-run ───────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-run", "# Stage 1+2: Run extraction (all rules + relevance classification)"))

# ── cell-run ──────────────────────────────────────────────────────────────────
cells.append(code_cell("cell-run",
"""logs = []
all_rules = []

for block in tqdm(selected_blocks, desc="Extracting rules"):
    block_id   = block.get("block_id")
    zone       = block.get("zone", "")
    pages      = block.get("pages") or []
    focus      = block.get("focus") or block.get("extraction_mode") or block.get("detected_topic") or ""
    doc_config = get_doc_config(block)
    city       = doc_config.get("city", "")
    topic      = block.get("detected_topic", "development_regulations")

    block_text           = ""
    raw_model_output     = ""
    call_error           = None
    parse_status         = "not_run"
    parse_error_message  = None
    rules                = []
    llm_seconds          = 0.0
    started              = None

    try:
        block_text, used_source = load_block_text(block)
        if len(block_text) > MAX_BLOCK_CHARS:
            block_text = block_text[:MAX_BLOCK_CHARS]
        prompt = build_rule_extraction_prompt_v2(
            block_id, zone, pages, focus, block_text, doc_config
        )
        started = time.time()
        raw_model_output, _ = call_ollama(prompt)
        llm_seconds = time.time() - started
        rules, parse_status, parse_error_message = parse_rules_object(raw_model_output)
    except Exception as e:
        if started is not None:
            llm_seconds = time.time() - started
        call_error = f"{type(e).__name__}: {e}"

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule.setdefault("block_id",   block_id)
        rule.setdefault("zone",       zone)
        rule.setdefault("city",       city)
        # Normalise relevance_category; default to "unrelated" if missing/invalid
        rc = str(rule.get("relevance_category") or "").strip().lower()
        if rc not in RELEVANCE_CATEGORIES:
            rc = "unrelated"
        rule["relevance_category"]   = rc
        rule["doc_id"]               = block.get("doc_id", "")
        rule["source_block_id"]      = block_id
        rule["source_block_pages"]   = pages
        rule["source_block_focus"]   = focus
        rule["block_topic"]          = topic
        all_rules.append(rule)

    logs.append({
        "block_id":             block_id,
        "city":                 city,
        "zone":                 zone,
        "pages":                pages,
        "focus":                focus,
        "detected_topic":       topic,
        "extraction_mode":      block.get("extraction_mode"),
        "call_error":           call_error,
        "parse_status":         parse_status,
        "parse_error_message":  parse_error_message,
        "rule_count":           len(rules),
        "llm_seconds":          llm_seconds,
        "raw_model_output":     raw_model_output,
        "block_text":           block_text,
    })

print(f"Blocks processed: {len(logs)}")
print(f"Rules parsed    : {len(all_rules)}")

# Quick relevance breakdown
from collections import Counter
rc_dist = Counter(r.get("relevance_category", "?") for r in all_rules)
print("Relevance distribution:", dict(rc_dist))"""))

# ── cell-md-coverage ─────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-coverage",
"""# Coverage check

For each block that qualifies (table / exception-heavy / zero-rule), make a second LLM call
to identify any rules that were not captured in Stage 1+2."""))

# ── cell-coverage ─────────────────────────────────────────────────────────────
cells.append(code_cell("cell-coverage",
"""coverage_logs     = []
all_missed_items  = []

for log in tqdm(logs, desc="Coverage check"):
    block_id   = log["block_id"]
    block_text = log.get("block_text", "") or ""
    rules_for_block = [r for r in all_rules if r.get("source_block_id") == block_id]

    do_audit, audit_reason = should_audit(block_text, rules_for_block)
    if not do_audit:
        continue

    # Build a brief summary of already-extracted rules for the coverage prompt
    if rules_for_block:
        extracted_summary = "\\n".join(
            f"- {r.get('rule_key_suggestion','?')}: value={r.get('value','?')} "
            f"{r.get('unit','')}  [{r.get('relevance_category','?')}]  "
            f"excerpt={str(r.get('original_excerpt',''))[:80]}"
            for r in rules_for_block
        )
    else:
        extracted_summary = "(none — zero rules extracted from this block)"

    # Get building_type from doc_config
    block_obj  = next((b for b in selected_blocks if b.get("block_id") == block_id), {})
    doc_config = get_doc_config(block_obj)
    building_type = doc_config.get("building_type", "Target Building")

    raw_coverage = ""
    missed        = []
    cov_error     = None
    started = time.time()
    try:
        prompt = build_coverage_check_prompt(
            block_id, building_type,
            block_text[:MAX_BLOCK_CHARS],
            extracted_summary,
        )
        raw_coverage, _ = call_ollama(prompt)
        missed, _, _    = parse_coverage_response(raw_coverage)
    except Exception as e:
        cov_error    = f"{type(e).__name__}: {e}"
        raw_coverage = cov_error
    cov_seconds = time.time() - started

    for item in missed:
        if not isinstance(item, dict):
            continue
        item["source_block_id"] = block_id
        item["audit_reason"]    = audit_reason
        all_missed_items.append(item)

    coverage_logs.append({
        "block_id":         block_id,
        "audit_reason":     audit_reason,
        "extracted_count":  len(rules_for_block),
        "missed_count":     len(missed),
        "cov_error":        cov_error,
        "cov_seconds":      cov_seconds,
        "raw_output":       raw_coverage,
    })

print(f"Blocks audited    : {len(coverage_logs)}")
print(f"Total missed items: {len(all_missed_items)}")
for cl in coverage_logs:
    print(f"  {cl['block_id']}  reason={cl['audit_reason']}  "
          f"extracted={cl['extracted_count']}  missed={cl['missed_count']}")"""))

# ── cell-md-dedup ─────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-dedup", "# Dedup (deterministic key — identical to notebook 13)"))

# ── cell-dedup ────────────────────────────────────────────────────────────────
cells.append(code_cell("cell-dedup",
"""def is_missing_value(value):
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def normalize_dedup_part(value):
    if is_missing_value(value):
        return ""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    value = str(value).lower().strip()
    value = re.sub(r"\\s+", " ", value)
    return value


def extract_numeric(value) -> str:
    if is_missing_value(value):
        return ""
    s = str(value).strip()
    m = re.search(r"\\d+(?:\\.\\d+)?", s)
    return m.group() if m else s[:30].lower()


def normalize_condition_for_dedup(condition) -> str:
    if is_missing_value(condition) or not str(condition).strip():
        return ""
    return " ".join(re.findall(r"\\d+(?:\\.\\d+)?", str(condition)))


def build_dedup_key(row) -> str:
    parts = [
        row.get("city"),
        row.get("zone"),
        row.get("building_type"),
        row.get("rule_key_suggestion"),
        extract_numeric(row.get("value")),
        row.get("unit"),
        row.get("bylaw_section"),
        normalize_condition_for_dedup(row.get("condition")),
    ]
    return "|".join(normalize_dedup_part(v) for v in parts)


def has_minimum_rule_content(row):
    fields = [row.get("rule_key_suggestion"), row.get("requirement_text"),
              row.get("description"), row.get("value"), row.get("operator")]
    return any(not is_missing_value(v) and str(v).strip() for v in fields)


rules_df = pd.DataFrame(all_rules)

if rules_df.empty:
    deduped_rules_df = rules_df.copy()
else:
    rules_df = rules_df[rules_df.apply(has_minimum_rule_content, axis=1)].reset_index(drop=True)
    rules_df["dedup_key"] = rules_df.apply(build_dedup_key, axis=1)
    rules_df["dedup_key"] = rules_df["dedup_key"].map(normalize_dedup_part)
    rules_df = rules_df[rules_df["dedup_key"].str.len() > 0].reset_index(drop=True)
    deduped_rules_df = rules_df.drop_duplicates(subset=["dedup_key"], keep="first").reset_index(drop=True)

print(f"Raw valid rule rows: {len(rules_df)}")
print(f"Deduped rule rows  : {len(deduped_rules_df)}")"""))

# ── cell-md-split ─────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-split",
"""# Split into all_rules_df and filtered_target_rules_df

- `all_rules_df` — every deduped rule regardless of relevance_category
- `filtered_target_rules_df` — only rules where `relevance_category != "unrelated"`"""))

# ── cell-split ────────────────────────────────────────────────────────────────
cells.append(code_cell("cell-split",
"""all_rules_df = deduped_rules_df.copy()

if deduped_rules_df.empty:
    filtered_target_rules_df = deduped_rules_df.copy()
else:
    filtered_target_rules_df = deduped_rules_df[
        deduped_rules_df["relevance_category"].fillna("").str.lower() != "unrelated"
    ].copy().reset_index(drop=True)

print(f"all_rules_df            : {len(all_rules_df)} rows")
print(f"filtered_target_rules_df: {len(filtered_target_rules_df)} rows")
if not deduped_rules_df.empty:
    print("\\nRelevance breakdown (deduped):")
    print(deduped_rules_df["relevance_category"].value_counts().to_string())"""))

# ── cell-md-validation ────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-validation",
"""# Validation

Checks applied to each rule row:
- **value_grounded**: extracted value appears in original_excerpt
- **condition_grounded**: condition is supported by original_excerpt
- **target_scope_warning**: no target term found anywhere in the rule row
- **table_under_extraction**: block has ≥ 2 table rows but extracted fewer rules than rows
- **has_unknown_type**: `schema_match == "city_specific"` (preserved for review)
- **exception_extraction_warning**: exception cue present but no condition/exception field set

Profile-based `outside_allowed_keys` / `blocked_key_violations` checks are omitted because the
two-stage prompt intentionally extracts all rule types."""))

# ── cell-validation ───────────────────────────────────────────────────────────
cells.append(code_cell("cell-validation",
"""def get_doc_config_for_rule(row):
    doc_id = row.get("doc_id", "")
    return DOC_CONFIGS.get(doc_id, next(iter(DOC_CONFIGS.values())))


def normalize_grounding_text(text):
    text = "" if is_missing_value(text) else str(text)
    text = re.sub(r"<br\\s*/?>", " ", text, flags=re.I)
    text = text.replace("_", "")
    text = re.sub(r"\\s+", " ", text)
    return text.lower().strip()


def value_is_grounded(value, original_excerpt, requirement_text):
    if is_missing_value(value):
        return True
    value_text = str(value).strip()
    if not value_text:
        return True
    haystack = normalize_grounding_text(f"{original_excerpt or ''} {requirement_text or ''}")
    candidates = {value_text.lower()}
    try:
        numeric = float(value)
        candidates.add(f"{numeric:g}".lower())
        candidates.add(f"{numeric:.1f}".lower())
    except Exception:
        pass
    return any(c and c in haystack for c in candidates)


def condition_is_grounded(condition, original_excerpt, requirement_text):
    if is_missing_value(condition) or not str(condition).strip():
        return True
    condition_text = normalize_grounding_text(condition)
    haystack = normalize_grounding_text(f"{original_excerpt or ''} {requirement_text or ''}")
    if condition_text in haystack:
        return True
    numbers  = re.findall(r"\\d+(?:\\.\\d+)?", condition_text)
    keywords = [w for w in re.findall(r"[a-zA-Z]+", condition_text) if len(w) >= 4]
    if numbers and all(n in haystack for n in numbers):
        return True
    if keywords and all(w.lower() in haystack for w in keywords[:4]):
        return True
    return False


def text_has_exception_cue(text):
    text_lower = (text or "").lower()
    return any(cue.lower() in text_lower for cue in EXCEPTION_CUE_PATTERNS)


def find_exception_extraction_warning(row):
    joined = " ".join(
        "" if is_missing_value(row.get(f)) else str(row.get(f))
        for f in ["description", "requirement_text", "condition", "exception", "original_excerpt"]
    )
    if not text_has_exception_cue(joined):
        return ""
    joined_lower = joined.lower()
    if "up to a maximum" in joined_lower and not any(
        cue in joined_lower for cue in ["despite", "if ", "provided", "except", "unless", "may be reduced"]
    ):
        return ""
    rule_key  = "" if is_missing_value(row.get("rule_key_suggestion")) else str(row.get("rule_key_suggestion"))
    condition = "" if is_missing_value(row.get("condition"))           else str(row.get("condition"))
    exception = "" if is_missing_value(row.get("exception"))           else str(row.get("exception"))
    if rule_key == "exception_or_override" or condition.strip() or exception.strip():
        return ""
    return "exception_cue_without_condition_or_exception"


def find_target_scope_warning(row, doc_config=None):
    if doc_config is None:
        doc_config = get_doc_config_for_rule(row)
    target_terms = doc_config.get("target_terms", [])
    text = " ".join(
        "" if is_missing_value(row.get(f)) else str(row.get(f))
        for f in ["building_type", "term_used_in_document", "description",
                  "requirement_text", "condition", "original_excerpt", "bylaw_section"]
    ).lower()
    if any(term in text for term in target_terms):
        return ""
    return "missing_target_scope"


def count_table_rows_in_text(text: str) -> int:
    return len(re.findall(r"^\\|.+\\|", text, re.MULTILINE))


def validate_rules_v2(rules_df):
    if rules_df.empty:
        return rules_df.copy()
    validated = rules_df.copy()
    value_checks, condition_checks = [], []
    target_scope_warnings, exception_warnings = [], []
    unknown_type_flags, statuses = [], []

    # Build a per-block table row count from logs
    block_table_rows = {}
    for log in logs:
        block_table_rows[log["block_id"]] = count_table_rows_in_text(log.get("block_text", ""))

    # Per-block rule counts (for table under-extraction check)
    block_rule_counts = validated.groupby("source_block_id").size().to_dict() if "source_block_id" in validated.columns else {}

    table_under_extraction_flags = []

    for _, row in validated.iterrows():
        doc_config        = get_doc_config_for_rule(row)
        original_excerpt  = row.get("original_excerpt")
        requirement_text  = row.get("requirement_text")
        source_block_id   = row.get("source_block_id", row.get("block_id", ""))

        # Grounding checks
        val_grounded  = value_is_grounded(row.get("value"), original_excerpt, requirement_text)
        cond_grounded = condition_is_grounded(row.get("condition"), original_excerpt, requirement_text)
        target_warn   = find_target_scope_warning(row, doc_config)
        exc_warn      = find_exception_extraction_warning(row)
        unknown_type  = str(row.get("schema_match", "")).strip().lower() == "city_specific"

        # Table under-extraction: block has ≥ 2 table rows and extracted fewer rules than rows/2
        tbl_rows = block_table_rows.get(source_block_id, 0)
        rule_cnt = block_rule_counts.get(source_block_id, 0)
        under_extract = (tbl_rows >= 2) and (rule_cnt < tbl_rows / 2)

        value_checks.append("ok" if val_grounded  else "value_not_grounded")
        condition_checks.append("ok" if cond_grounded else "condition_not_grounded")
        target_scope_warnings.append(target_warn)
        exception_warnings.append(exc_warn)
        unknown_type_flags.append(unknown_type)
        table_under_extraction_flags.append(under_extract)

        row_statuses = []
        if not val_grounded:  row_statuses.append("value_not_grounded")
        if not cond_grounded: row_statuses.append("condition_not_grounded")
        if target_warn:       row_statuses.append(target_warn)
        if exc_warn:          row_statuses.append(exc_warn)
        if under_extract:     row_statuses.append("table_under_extraction")
        if unknown_type:      row_statuses.append("city_specific_key")
        statuses.append("ok" if not row_statuses else "; ".join(row_statuses))

    validated["source_excerpt_value_check"]     = value_checks
    validated["source_excerpt_condition_check"] = condition_checks
    validated["target_scope_warning"]           = target_scope_warnings
    validated["exception_extraction_warning"]   = exception_warnings
    validated["has_unknown_type"]               = unknown_type_flags
    validated["table_under_extraction"]         = table_under_extraction_flags
    validated["block_validation_status"]        = statuses
    return validated


validated_rules_df = validate_rules_v2(all_rules_df)

if validated_rules_df.empty:
    validation_warnings_df = validated_rules_df.copy()
    unknown_types_df       = validated_rules_df.copy()
else:
    validation_warnings_df = validated_rules_df[
        validated_rules_df["block_validation_status"].ne("ok")
    ].copy()
    unknown_types_df = validated_rules_df[
        validated_rules_df["has_unknown_type"].eq(True)
    ].copy()

print(f"validated_rules    : {len(validated_rules_df)}")
print(f"validation_warnings: {len(validation_warnings_df)}")
print(f"unknown_type_rules : {len(unknown_types_df)}")"""))

# ── cell-md-save ──────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-save",
"""# Save outputs (5 files)

| File | Contents |
|------|----------|
| `all_extracted_rules.csv` | All deduped rules (every relevance category) |
| `filtered_target_rules.csv` | Rules where `relevance_category != "unrelated"` |
| `coverage_missing_items.csv` | Items flagged by the coverage check LLM |
| `extraction_validation_warnings.csv` | Rows with at least one validation warning |
| `unknown_rule_types.csv` | Rules with `schema_match == "city_specific"` |"""))

# ── cell-save ─────────────────────────────────────────────────────────────────
cells.append(code_cell("cell-save",
"""from collections import Counter

log_df           = pd.DataFrame(logs)
coverage_df      = pd.DataFrame(coverage_logs) if coverage_logs else pd.DataFrame()
missed_items_df  = pd.DataFrame(all_missed_items) if all_missed_items else pd.DataFrame()

all_rules_path         = OUTPUT_DIR / "all_extracted_rules.csv"
filtered_rules_path    = OUTPUT_DIR / "filtered_target_rules.csv"
coverage_missing_path  = OUTPUT_DIR / "coverage_missing_items.csv"
validation_warn_path   = OUTPUT_DIR / "extraction_validation_warnings.csv"
unknown_types_path     = OUTPUT_DIR / "unknown_rule_types.csv"
log_xlsx_path          = OUTPUT_DIR / "block_extraction_log_full.xlsx"
summary_path           = OUTPUT_DIR / "block_extraction_summary.txt"

has_call_error = any(log.get("call_error") for log in logs)
skip_rule_write = rules_df.empty and has_call_error and not SAVE_EMPTY_RESULTS

if skip_rule_write:
    print("Skipping rule CSV writes — zero rules after call error.")
else:
    all_rules_df.to_csv(all_rules_path,        index=False, encoding="utf-8-sig")
    filtered_target_rules_df.to_csv(filtered_rules_path, index=False, encoding="utf-8-sig")
    missed_items_df.to_csv(coverage_missing_path, index=False, encoding="utf-8-sig")
    validation_warnings_df.to_csv(validation_warn_path,   index=False, encoding="utf-8-sig")
    unknown_types_df.to_csv(unknown_types_path,   index=False, encoding="utf-8-sig")
    print(f"Saved: {all_rules_path}         ({len(all_rules_df)} rows)")
    print(f"Saved: {filtered_rules_path}    ({len(filtered_target_rules_df)} rows)")
    print(f"Saved: {coverage_missing_path}  ({len(missed_items_df)} rows)")
    print(f"Saved: {validation_warn_path}   ({len(validation_warnings_df)} rows)")
    print(f"Saved: {unknown_types_path}     ({len(unknown_types_df)} rows)")

log_df.to_excel(log_xlsx_path, index=False)

topic_dist = Counter(log.get("detected_topic", "?") for log in logs)
rc_dist    = Counter(r.get("relevance_category", "?") for r in all_rules)

summary_lines = [
    f"notebook: 15_two_stage_rule_extraction",
    f"model: {MODEL_NAME}",
    f"input_jsonl: {input_jsonl}",
    f"selected_blocks: {len(selected_blocks)}",
    f"processed_blocks: {len(logs)}",
    f"topic_distribution: {dict(topic_dist)}",
    f"raw_rule_rows: {len(rules_df)}",
    f"deduped_rule_rows: {len(deduped_rules_df)}",
    f"relevance_distribution: {dict(rc_dist)}",
    f"filtered_target_rules: {len(filtered_target_rules_df)}",
    f"coverage_blocks_audited: {len(coverage_logs)}",
    f"coverage_missed_items: {len(all_missed_items)}",
    f"validation_warnings: {len(validation_warnings_df)}",
    f"unknown_type_rules: {len(unknown_types_df)}",
    f"skipped_rule_output_write: {skip_rule_write}",
    "",
    "Block results:",
]
for log in logs:
    summary_lines.append(
        f"  [{log['city']}] {log['block_id']}: "
        f"topic={log.get('detected_topic','?')}; "
        f"call_error={log['call_error']}; "
        f"parse_status={log['parse_status']}; "
        f"rule_count={log['rule_count']}; "
        f"llm_seconds={log['llm_seconds']:.2f}"
    )

summary_path.write_text("\\n".join(summary_lines), encoding="utf-8")
print("\\n" + summary_path.read_text(encoding="utf-8"))"""))

# ── cell-summary ──────────────────────────────────────────────────────────────
cells.append(md_cell("cell-md-summary", "# Summary and review"))

cells.append(code_cell("cell-summary",
"""print("All rules — by block and relevance_category:")
if not all_rules_df.empty:
    display(
        all_rules_df
        .groupby(["source_block_id", "rule_key_suggestion", "relevance_category"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["source_block_id", "relevance_category", "rule_key_suggestion"])
    )
else:
    print("No rules extracted yet.")"""))

cells.append(code_cell("cell-review-filtered",
"""print("Filtered target rules (relevance != unrelated):")
if not filtered_target_rules_df.empty:
    cols = [c for c in [
        "source_block_id", "rule_key_suggestion", "relevance_category",
        "value", "unit", "condition", "original_excerpt",
        "block_validation_status",
    ] if c in filtered_target_rules_df.columns]
    display(filtered_target_rules_df[cols])
else:
    print("No filtered rules.")"""))

cells.append(code_cell("cell-review-missed",
"""if not missed_items_df.empty:
    print(f"Coverage missed items ({len(missed_items_df)}):")
    display(missed_items_df)
else:
    print("No missed items flagged by coverage check.")"""))

cells.append(code_cell("cell-review-warnings",
"""if not validation_warnings_df.empty:
    print(f"Validation warnings ({len(validation_warnings_df)}):")
    cols = [c for c in [
        "source_block_id", "rule_key_suggestion", "relevance_category",
        "value", "original_excerpt", "block_validation_status",
    ] if c in validation_warnings_df.columns]
    display(validation_warnings_df[cols])
else:
    print("No validation warnings.")"""))


# ── Assemble notebook ─────────────────────────────────────────────────────────
notebook = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.10.0",
        },
    },
    "cells": cells,
}

OUTPUT_PATH.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"Written: {OUTPUT_PATH}  ({OUTPUT_PATH.stat().st_size:,} bytes)  {len(cells)} cells")
