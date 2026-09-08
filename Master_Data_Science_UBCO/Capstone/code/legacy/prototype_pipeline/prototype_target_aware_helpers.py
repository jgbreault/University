import json
import re
from difflib import SequenceMatcher


TARGET_FAMILY_TERMS = [
    "laneway house", "coach house", "garden suite", "backyard home", "backyard homes",
    "accessory dwelling", "detached accessory dwelling", "secondary detached dwelling",
]

ADMISSION_SUBJECT_TERMS = [
    *TARGET_FAMILY_TERMS,
    "building", "buildings", "structure", "structures", "lot", "site", "yard",
    "parking", "access", "driveway", "dwelling unit", "dwelling units",
    "accessory building", "principal building", "rear principal", "rear principal building",
    "all buildings", "principal buildings", "front principal", "front principals",
    "rear principal", "rear principals", "front principal building", "rear principal building",
    "accessory buildings", "small-scale multi-unit", "rowhouse", "rowhouse dwelling",
    "lots", "street yard", "lane yard", "interior rear yard", "interior side yard",
    "flanking yard", "separation", "front and rear principals",
    "between front principals", "between rear principals", "between all other buildings",
]

ADMISSION_CONSTRAINT_LABELS = [
    "height", "roof peak", "storey", "storeys", "floor area", "floor space", "density",
    "fsr", "far", "lot coverage", "site coverage", "coverage", "setback", "yard",
    "separation", "lot width", "site width", "lot area", "lot size", "frontage",
    "parking", "access", "driveway", "permitted use", "required", "maximum", "minimum",
    "impervious", "impervious surfaces", "sprinkler", "fire access", "panhandle",
    "permitted dwelling units", "lot area", "lot width", "sloping roof", "flat roof",
    "street yard", "lane yard", "rear yard", "side yard", "interior rear yard",
    "interior side yard", "minimum separation", "amenity space",
]

ADMISSION_ACTION_PATTERNS = [
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*%",
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:sq\.?\s*m|m2|m\s*\[\s*2\s*\]|square metres?|square meters?)",
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:m|metres?|meters?)\b",
    r"\d+(?:\.\d+)?\s*storeys?\b",
    r"\bnot permitted\b", r"\bpermitted\b", r"\brequired\b", r"\bmust\b", r"\bshall\b",
    r"\bmay be reduced\b", r"\bnot exceed\b", r"\bat least\b", r"\bmaximum\b", r"\bminimum\b",
]

ADMITTED_PRE_CLASSES = {"rule_bearing", "ambiguous_rule_like", "table_value", "condition_rule", "exception_rule"}
REJECTED_PRE_CLASSES = {"context_only", "table_header", "definition_only", "cross_reference_only", "unrelated", "fragment"}

REJECT_REASON_BY_PRE_CLASS = {
    "context_only": "context_only",
    "table_header": "table_header_only",
    "definition_only": "definition_only",
    "cross_reference_only": "cross_reference_only",
    "unrelated": "not_target_relevant",
    "fragment": "fragment_only",
}


def compact_spaces(value) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def normalize_text(text) -> str:
    text = compact_spaces(text).lower()
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = text.replace("_", "")
    return compact_spaces(text)


def is_missing_value(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in {"", "nan", "none", "null"}


def strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text[start:], start=start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _find_terms(text: str, terms: list[str]) -> list[str]:
    lower = normalize_text(text)
    found = []
    for term in terms:
        if term and re.search(r"\b" + re.escape(term.lower()) + r"\b", lower):
            found.append(term)
    return found


def _find_actions(text: str) -> list[str]:
    found = []
    seen = set()
    for pattern in ADMISSION_ACTION_PATTERNS:
        for match in re.finditer(pattern, text or "", flags=re.I):
            raw = compact_spaces(match.group(0))
            key = raw.lower()
            if key not in seen:
                seen.add(key)
                found.append(raw)
    if any(x.lower() == "not permitted" for x in found):
        found = [x for x in found if x.lower() != "permitted"]
    return found


def _find_values_or_permissions(text: str) -> list[str]:
    """Values/actions that can anchor a rule row, excluding standalone max/min labels."""
    found = []
    seen = set()
    value_patterns = [
        r"\d+(?:,\d{3})*(?:\.\d+)?\s*%",
        r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:sq\.?\s*m|m2|m\s*\[\s*2\s*\]|square metres?|square meters?)",
        r"\d+(?:,\d{3})*(?:\.\d+)?\s*(?:m|metres?|meters?)\b",
        r"\d+(?:\.\d+)?\s*storeys?\b",
        r"\bnot permitted\b", r"\bpermitted\b", r"\brequired\b", r"\bmust\b", r"\bshall\b",
    ]
    for pattern in value_patterns:
        for match in re.finditer(pattern, text or "", flags=re.I):
            raw = compact_spaces(match.group(0))
            key = raw.lower()
            if key not in seen:
                seen.add(key)
                found.append(raw)
    if any(x.lower() == "not permitted" for x in found):
        found = [x for x in found if x.lower() != "permitted"]
    return found


def _looks_like_table_header(text: str) -> bool:
    lower = normalize_text(text)
    if not text or len(lower) < 3:
        return True
    cells = [c.strip() for c in str(text).split("|") if c.strip()]
    if len(cells) >= 2:
        no_values = not _find_values_or_permissions(text)
        repeated = len(set(c.lower() for c in cells)) <= max(2, len(cells) // 2)
        header_words = any(w in lower for w in [
            "development regulations", "maximum height", "maximum lot coverage",
            "minimum lot line setbacks", "building type", "dwelling type",
        ])
        if no_values and (repeated or header_words):
            return True
    return False


def _looks_like_cross_reference_only(text: str) -> bool:
    lower = normalize_text(text)
    has_ref = bool(re.search(r"\b(section|table|part)\s+\d", lower))
    return has_ref and not (_find_actions(text) and _find_terms(text, ADMISSION_CONSTRAINT_LABELS))


def _looks_like_definition_only(text: str) -> bool:
    lower = normalize_text(text)
    return bool(re.search(r"\bmeans\b|\bdefinition\b|\bdefined as\b", lower)) and not _find_actions(text)


def classify_evidence_unit_pre_llm(evidence_unit: dict, target_profile: dict | None = None) -> dict:
    target_profile = target_profile or {}
    text = evidence_unit.get("text", "") or ""
    support = evidence_unit.get("supporting_context") or {}
    support_text = " ".join(
        str(support.get(k, "")) if not isinstance(support.get(k), list)
        else " ".join(map(str, support.get(k)))
        for k in ["heading_path", "table_title", "column_headers", "row_headers", "context_rows", "nearby_text", "footnotes"]
    )
    combined = f"{text} {support_text}"
    target_terms = list(dict.fromkeys(
        [t.lower() for t in target_profile.get("target_terms", []) if t]
        + [t.lower() for t in target_profile.get("primary_keywords", []) if t]
        + [t.lower() for t in target_profile.get("parent_terms", []) if t]
        + [t.lower() for t in TARGET_FAMILY_TERMS]
    ))
    subject_terms = list(dict.fromkeys(target_terms + ADMISSION_SUBJECT_TERMS))

    visible_subject_terms = _find_terms(combined, subject_terms)
    visible_constraint_labels = _find_terms(text, ADMISSION_CONSTRAINT_LABELS)
    visible_values_or_actions = _find_values_or_permissions(text)
    has_subject = bool(visible_subject_terms)
    has_constraint_label = bool(visible_constraint_labels)
    has_value_or_legal_action = bool(visible_values_or_actions)
    score = int(has_subject) + int(has_constraint_label) + int(has_value_or_legal_action)
    lower = normalize_text(text)
    evidence_type = evidence_unit.get("evidence_type", "")

    admission_reason = ""
    table_with_constraint_and_value = evidence_type in {"table_row", "table_cell"} and has_constraint_label and has_value_or_legal_action
    table_with_subject_and_value = evidence_type in {"table_row", "table_cell"} and has_subject and has_value_or_legal_action
    table_with_permission = evidence_type in {"table_row", "table_cell"} and any(
        str(v).lower() in {"permitted", "not permitted", "required"} for v in visible_values_or_actions
    )

    if table_with_constraint_and_value:
        pre_class, reason = "rule_bearing", "generic R1 table row has a constraint label and value/action"
        admission_reason = "table_row_with_constraint_and_value"
    elif table_with_subject_and_value:
        pre_class, reason = "rule_bearing", "generic R1 table row has a regulated subject and value/action"
        admission_reason = "table_row_with_subject_and_value"
    elif table_with_permission:
        pre_class, reason = "ambiguous_rule_like", "table row has permission/prohibition language"
        admission_reason = "table_row_with_permission_or_prohibition"
    elif _looks_like_definition_only(text):
        pre_class, reason = "definition_only", "definition wording without a visible requirement"
        admission_reason = "definition_only"
    elif _looks_like_cross_reference_only(text):
        pre_class, reason = "cross_reference_only", "cross-reference without extractable value/action"
        admission_reason = "cross_reference_only"
    elif _looks_like_table_header(text):
        pre_class, reason = "table_header", "table heading/header row without row-level value/action"
        admission_reason = "table_header_only"
    elif len(lower) < 12 or lower in {"-", "/", "n/a"}:
        pre_class, reason = "fragment", "too short or fragmentary"
        admission_reason = "fragment_only"
    elif score >= 3:
        pre_class, reason = "rule_bearing", "subject, constraint, and value/action are visible"
        admission_reason = "generic_r1_development_rule"
    elif score == 2:
        pre_class, reason = "ambiguous_rule_like", "two admission signals are visible"
        admission_reason = "generic_building_rule"
    elif score == 1 and has_subject and evidence_type in {"table_row", "table_cell"} and _find_actions(text):
        pre_class, reason = "ambiguous_rule_like", "table evidence has target context and value/action"
        admission_reason = "table_row_with_subject_and_value"
    elif score == 1:
        pre_class, reason = "context_only", "only one admission signal is visible"
        admission_reason = "context_only"
    else:
        pre_class, reason = "unrelated", "no admission signals are visible"
        admission_reason = "not_target_relevant"

    return {
        "evidence_id": evidence_unit.get("evidence_id"),
        "pre_class": pre_class,
        "admission_score": score,
        "has_subject": has_subject,
        "has_constraint_label": has_constraint_label,
        "has_value_or_legal_action": has_value_or_legal_action,
        "visible_subject_terms": visible_subject_terms,
        "visible_constraint_labels": visible_constraint_labels,
        "visible_values_or_actions": visible_values_or_actions,
        "admission_reason": admission_reason,
        "reason": reason,
    }


def add_supporting_context_to_evidence(evidence_units: list[dict]) -> list[dict]:
    row_units = [ev for ev in evidence_units if ev.get("evidence_type") == "table_row"]
    row_by_index = {ev.get("row_index"): ev for ev in row_units}
    table_title = row_units[0].get("text", "") if row_units else ""
    for ev in evidence_units:
        support = ev.setdefault("supporting_context", {})
        support.setdefault("heading_path", ev.get("heading_path", ""))
        support.setdefault("table_title", table_title if ev.get("evidence_type", "").startswith("table") else "")
        if ev.get("evidence_type") in {"table_row", "table_cell"}:
            idx = ev.get("row_index")
            context_rows = []
            if isinstance(idx, int):
                for j in range(max(1, idx - 3), idx):
                    if j in row_by_index:
                        context_rows.append(row_by_index[j].get("text", ""))
            support.setdefault("context_rows", context_rows)
            support.setdefault("row_headers", [str(ev.get("text", "")).split("|")[0].strip()])
            support.setdefault("column_headers", [ev.get("column_name", "")] if ev.get("column_name") else [])
        support.setdefault("footnotes", [])
        support.setdefault("nearby_text", "")
    return evidence_units


def apply_pre_llm_admission(evidence_units: list[dict], target_profile: dict) -> tuple[list[dict], list[dict]]:
    admitted, rejected = [], []
    for ev in evidence_units:
        ev.update(classify_evidence_unit_pre_llm(ev, target_profile))
        (admitted if ev["pre_class"] in ADMITTED_PRE_CLASSES else rejected).append(ev)
    return admitted, rejected


def format_evidence_units_for_prompt(evidence_units: list[dict], max_units: int = 12, max_text_chars: int = 900) -> str:
    chunks = []
    for ev in evidence_units[:max_units]:
        support = ev.get("supporting_context") or {}
        support_bits = []
        for key in ["table_title", "column_headers", "row_headers", "context_rows", "footnotes", "nearby_text"]:
            val = support.get(key)
            if not val:
                continue
            if isinstance(val, list):
                val = " || ".join(str(v) for v in val if v)
            support_bits.append(f"{key}: {val}")
        chunks.append(
            f"Evidence ID: {ev.get('evidence_id')}\n"
            f"Type: {ev.get('evidence_type')} | pre_class={ev.get('pre_class')} | admission_score={ev.get('admission_score')}\n"
            f"Evidence to extract from:\n{str(ev.get('text',''))[:max_text_chars]}\n"
            f"Supporting context for interpretation only:\n    " + ("\n    ".join(support_bits) if support_bits else "(none)")
        )
    return "\n\n---\n\n".join(chunks)


def _row_label_from_text(text: str) -> str:
    cells = [compact_spaces(c) for c in str(text or "").split("|") if compact_spaces(c)]
    if not cells:
        return ""
    if re.match(r"row\d+", cells[0], flags=re.I) and len(cells) > 1:
        return cells[1]
    return cells[0]


def _is_group_heading_row(ev: dict) -> bool:
    text = ev.get("text", "") or ""
    label = _row_label_from_text(text).lower()
    if _find_values_or_permissions(text):
        return False
    heading_terms = [
        "maximum lot coverage", "maximum height", "minimum lot line setbacks",
        "minimum separation", "development regulations", "use-specific regulations",
        "general regulations", "heritage", "measurements and calculations",
    ]
    return any(term in label or term in normalize_text(text) for term in heading_terms)


def build_table_rule_groups(evidence_units: list[dict]) -> list[dict]:
    """Group table rows so the LLM can see row headings without stealing values from context.

    Each output rule still has to cite the exact row evidence_id. Heading rows are context;
    value rows are extractable.
    """
    table_rows = [ev for ev in evidence_units if ev.get("evidence_type") in {"table_row", "table_cell"}]
    groups = []
    current = None
    group_index = 0

    def start_group(title, ev):
        nonlocal group_index
        group_index += 1
        return {
            "group_id": f"{ev.get('extraction_unit_id') or ev.get('source_block_id')}__tblgrp_{group_index:03d}",
            "group_title": title or "Table Rules",
            "source_block_id": ev.get("source_block_id"),
            "page_number": ev.get("page_number"),
            "section": ev.get("section") or ev.get("bylaw_section"),
            "heading_path": ev.get("heading_path", ""),
            "rows": [],
            "supporting_context": {
                "table_title": (ev.get("supporting_context") or {}).get("table_title", ""),
                "column_headers": (ev.get("supporting_context") or {}).get("column_headers", []),
                "footnotes": (ev.get("supporting_context") or {}).get("footnotes", []),
                "nearby_context": "",
            },
        }

    for ev in table_rows:
        label = _row_label_from_text(ev.get("text", ""))
        if current is None or _is_group_heading_row(ev):
            if current and current["rows"]:
                groups.append(current)
            current = start_group(label, ev)
            if _find_actions(ev.get("text", "")):
                current["rows"].append({
                    "evidence_id": ev.get("evidence_id"),
                    "row_label": label,
                    "text": ev.get("text", ""),
                    "pre_class": ev.get("pre_class"),
                    "admission_score": ev.get("admission_score"),
                    "admission_reason": ev.get("admission_reason"),
                })
            continue
        current["rows"].append({
            "evidence_id": ev.get("evidence_id"),
            "row_label": label,
            "text": ev.get("text", ""),
            "pre_class": ev.get("pre_class"),
            "admission_score": ev.get("admission_score"),
            "admission_reason": ev.get("admission_reason"),
        })
    if current and current["rows"]:
        groups.append(current)

    useful_groups = []
    for group in groups:
        rows = group.get("rows", [])
        visible_rows = [r for r in rows if _find_actions(r.get("text", ""))]
        if visible_rows:
            group["visible_fact_count"] = sum(len(extract_visible_facts(r.get("text", "")).get("number_unit_pairs", [])) + len(extract_visible_facts(r.get("text", "")).get("permission_terms", [])) for r in visible_rows)
            useful_groups.append(group)
    return useful_groups


def split_table_group_into_extraction_batches(table_group: dict, max_rows: int = 2) -> list[dict]:
    """Split a table group into small extraction batches to keep JSON short/stable."""
    batches = []
    rows = [r for r in table_group.get("rows", []) if _find_values_or_permissions(r.get("text", ""))]
    pending = []

    def flush():
        if not pending:
            return
        idx = len(batches) + 1
        batches.append({
            "batch_id": f"{table_group.get('group_id')}__batch_{idx:03d}",
            "group_id": table_group.get("group_id"),
            "group_title": table_group.get("group_title"),
            "operator_hint": infer_operator_from_table_context(table_group.get("group_title", ""), "", "", "")[0],
            "page_number": table_group.get("page_number"),
            "section": table_group.get("section"),
            "heading_path": table_group.get("heading_path"),
            "column_headers": (table_group.get("supporting_context") or {}).get("column_headers", []),
            "rows": list(pending),
            "supporting_context": {
                "table_title": (table_group.get("supporting_context") or {}).get("table_title", ""),
                "footnotes": (table_group.get("supporting_context") or {}).get("footnotes", []),
                "nearby_context": (table_group.get("supporting_context") or {}).get("nearby_context", ""),
            },
        })
        pending.clear()

    for row in rows:
        facts = extract_visible_facts(row.get("text", ""))
        fact_count = len(facts.get("number_unit_pairs", [])) + len(facts.get("permission_terms", []))
        if fact_count > 1:
            flush()
            pending.append(row)
            flush()
        else:
            pending.append(row)
            if len(pending) >= max_rows:
                flush()
    flush()
    return batches


def format_table_group_for_prompt(group: dict, max_text_chars: int = 1200) -> str:
    rows_text = []
    for row in group.get("rows", []):
        rows_text.append(
            f"- evidence_id: {row.get('evidence_id')}\n"
            f"  row_label: {row.get('row_label')}\n"
            f"  row_text: {str(row.get('text',''))[:max_text_chars]}"
        )
    support = group.get("supporting_context") or {}
    return (
        f"Group ID: {group.get('group_id')}\n"
        f"Group title: {group.get('group_title')}\n"
        f"Rows to extract from:\n" + "\n".join(rows_text) + "\n"
        f"Supporting context for interpretation only:\n"
        f"- heading_path: {group.get('heading_path','')}\n"
        f"- table_title: {support.get('table_title','')}\n"
        f"- column_headers: {support.get('column_headers', [])}\n"
        f"- footnotes: {support.get('footnotes', [])}"
    )


def format_table_batch_for_prompt(batch: dict, max_text_chars: int = 900) -> str:
    rows_text = []
    for row in batch.get("rows", []):
        rows_text.append(
            f"- evidence_id: {row.get('evidence_id')}\n"
            f"  row_label: {row.get('row_label')}\n"
            f"  row_text: {str(row.get('text',''))[:max_text_chars]}"
        )
    support = batch.get("supporting_context") or {}
    return (
        f"Batch ID: {batch.get('batch_id')}\n"
        f"Group ID: {batch.get('group_id')}\n"
        f"Group title: {batch.get('group_title')}\n"
        f"Operator hint: {batch.get('operator_hint')}\n"
        f"Column headers: {batch.get('column_headers', [])}\n"
        f"Rows:\n" + "\n".join(rows_text) + "\n"
        f"Supporting context only:\n"
        f"- heading_path: {batch.get('heading_path','')}\n"
        f"- table_title: {support.get('table_title','')}\n"
        f"- footnotes: {support.get('footnotes', [])}"
    )


def build_table_batch_extraction_prompt(batch: dict, zone: str, doc_config: dict, retry: bool = False):
    city = doc_config.get("city", "Unknown")
    building_type = doc_config.get("building_type", "Target Building")
    retry_line = (
        "Your previous response was invalid JSON. Return only one valid JSON object using the exact schema. No prose.\n"
        if retry else ""
    )
    return f"""{retry_line}Extract zoning bylaw table rules from this small table batch.

Return strict JSON only. No markdown. No comments. No trailing commas.

Target profile:
- city: {city}
- zone: {zone}
- target building family/type: {building_type}

Important:
- Every row shown below has already passed deterministic rule-bearing admission.
- If a row contains a number with a unit, a percentage, storeys, permitted, not permitted, required, must, or shall, you MUST output at least one rule for that row.
- Do not return no_rule for rows such as "All Buildings | 55%", "Lane Yard | 1.5 m", "Height | sloping roof: 10 m", or "Between Front & Rear Principals | 6.0 m".

Rules:
- Extract all atomic rules from the provided rows.
- Use group_title and column_headers only to interpret operator and condition.
- Each value must appear in the cited row_text.
- Do not extract values that appear only in supporting_context.
- If one row has multiple values, output multiple rules.
- Use the cited row's evidence_id for each rule.
- If group_title contains Maximum, use operator "<=" unless row says otherwise.
- If group_title contains Minimum, use operator ">=" unless row says otherwise.
- If the row has "except", put it in exception.
- For not permitted/permitted, use operator "=".
- Keep strings short.

Return exactly this minimal schema:
{{
  "batch_id": "{batch.get('batch_id')}",
  "rules": [
    {{
      "evidence_id": "...",
      "rule_key": "...",
      "subject": "...",
      "operator": "<= / >= / =",
      "value": "...",
      "unit": "...",
      "condition": "...",
      "exception": null
    }}
  ],
  "skipped_rows": [
    {{"evidence_id": "...", "reason": "no_rule / header_only / duplicate / unclear"}}
  ]
}}

Table batch:
{format_table_batch_for_prompt(batch)}
"""


def build_table_group_extraction_prompt(group: dict, zone: str, doc_config: dict):
    # Backward-compatible name; new code uses small table batches.
    batches = split_table_group_into_extraction_batches(group, max_rows=1)
    return build_table_batch_extraction_prompt(batches[0], zone, doc_config) if batches else "{}"


def build_target_aware_prompt(block_id, zone, doc_config, evidence_units):
    city = doc_config.get("city", "Unknown")
    building_type = doc_config.get("building_type", "Target Building")
    target_description = doc_config.get("target_description", "")
    return f"""You are extracting target-aware zoning bylaw rules from admitted evidence units.

Return one valid JSON object only. Do not use markdown or reasoning.
Top-level key must be "evidence_results".

Target profile:
- city: {city}
- zone: {zone}
- target building family/type: {building_type}
- target description: {target_description}

Extract every explicit rule that is direct, indirect, generic-applicable, definition/reference, or plausibly applicable to the target building family.
Do NOT extract clearly unrelated sibling-specific rules or non-rule evidence.
Do NOT convert table headers, fragments, context-only text, definitions without requirements, or cross-reference-only text into rules.
For admitted evidence, assume it is rule-bearing unless it is clearly not a rule.
If an admitted evidence unit contains a requirement/constraint label and a value/legal action, you must extract a rule.
Do not return no_rule for evidence like All Buildings | 55%, Accessory Buildings | 4.0 m | 1 storey, Lane Yard | 1.5 m, Between Front & Rear Principals | 6.0 m, Interior Rear Yard | 3.0 m except 1.5 m, or Front Principal Buildings | sloping roof: 10 m | flat roof: 9.5 m.
no_rule is allowed only for pure section headings, pure table headers with no values, page footers, bylaw amendment markers, pure cross-references without requirements, and fragments with no subject/constraint/value.
Do not mark everything as review. Use no_rule/context_only/table_header/definition_only/unrelated when appropriate.

For each evidence unit return:
{{
  "evidence_id": "...",
  "evidence_decision": "rules_extracted / no_rule / context_only / table_header / definition_only / unrelated / ambiguous_review",
  "non_rule_reason": null,
  "rules": [...],
  "skipped_visible_facts": []
}}

Every rule must include evidence_id, rule_object, constraint_type, constraint_scope, subject, applies_to,
building_type, relevance_category, requirement_text, value, unit, operator, condition, exception,
confidence, needs_review, review_reason, original_excerpt, value_source_text, value_source.

Atomic split requirements:
- "minimum 35 sq. m and maximum 75 sq. m" => two rules.
- "2 storeys, maximum 7.0 m, roof peak 8.3 m" => three rules.
- "Front Yard Not Permitted ... Rear Yard 0.5 m" => separate rules.

Table rules:
- The value must appear in the evidence text/row/cell.
- value_source must be "current_evidence_text" for non-group evidence.
- Operator/scope may be supported by table title, heading, column heading, or row label.
- Supporting context is for interpretation only. Do not extract values from supporting context.

Evidence Unit Inventory:
{format_evidence_units_for_prompt(evidence_units)}
"""


def parse_evidence_extraction_response(raw: str, fallback_evidence_id: str | None = None):
    text = strip_markdown_fences(raw or "")
    obj_text = extract_first_json_object(text) or text
    try:
        obj = json.loads(obj_text)
    except Exception as e:
        return [], [], "parse_error", f"{type(e).__name__}: {e}"
    if isinstance(obj, list):
        for r in obj:
            if isinstance(r, dict):
                r.setdefault("evidence_id", fallback_evidence_id)
        return [r for r in obj if isinstance(r, dict)], [], "success_list", None
    if not isinstance(obj, dict):
        return [], [], "invalid_top_level", f"unexpected type {type(obj).__name__}"
    if isinstance(obj.get("evidence_results"), list):
        rules = []
        for result in obj["evidence_results"]:
            if not isinstance(result, dict):
                continue
            eid = result.get("evidence_id") or fallback_evidence_id
            for rule in result.get("rules") or []:
                if isinstance(rule, dict):
                    rule.setdefault("evidence_id", eid)
                    rule["evidence_decision"] = result.get("evidence_decision")
                    rules.append(rule)
        return rules, obj["evidence_results"], "success_evidence_results", None
    if isinstance(obj.get("rules"), list):
        rules = [r for r in obj["rules"] if isinstance(r, dict)]
        if obj.get("group_id"):
            for r in rules:
                r.setdefault("source_group_id", obj.get("group_id"))
        return rules, [], "success_rules", None
    if "rule_object" in obj or "rule_id" in obj:
        obj.setdefault("evidence_id", fallback_evidence_id)
        return [obj], [], "success_single_rule_object", None
    return [], [], "success_no_rules", None


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text or "")


def parse_llm_json_response(text: str):
    """Parse a model JSON response with simple cleanup and balanced-object recovery."""
    raw = text or ""
    candidates = []
    stripped = strip_markdown_fences(raw)
    candidates.append(stripped)
    first_obj = extract_first_json_object(stripped)
    if first_obj and first_obj not in candidates:
        candidates.append(first_obj)
    first_array_start = stripped.find("[")
    if first_array_start >= 0:
        candidates.append(stripped[first_array_start:])
    for candidate in list(candidates):
        cleaned = _remove_trailing_commas(candidate)
        if cleaned not in candidates:
            candidates.append(cleaned)
    last_error = None
    for candidate in candidates:
        try:
            return json.loads(candidate), None
        except Exception as e:
            last_error = e
    return None, last_error


def _extract_complete_objects_after_key(text: str, key: str = "rules") -> list[dict]:
    marker = f'"{key}"'
    start = text.find(marker)
    if start < 0:
        return []
    arr_start = text.find("[", start)
    if arr_start < 0:
        return []
    objects = []
    depth = 0
    obj_start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text[arr_start + 1:], start=arr_start + 1):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                snippet = _remove_trailing_commas(text[obj_start:i + 1])
                try:
                    objects.append(json.loads(snippet))
                except Exception:
                    pass
                obj_start = None
        elif ch == "]" and depth == 0:
            break
    return objects


def parse_minimal_table_response(raw: str, fallback_batch_id: str | None = None):
    obj, err = parse_llm_json_response(raw)
    recovered = False
    if obj is None:
        rules = _extract_complete_objects_after_key(strip_markdown_fences(raw), "rules")
        if rules:
            obj = {"batch_id": fallback_batch_id, "rules": rules, "skipped_rows": []}
            recovered = True
    if obj is None:
        return [], [], "parse_error", f"{type(err).__name__}: {err}" if err else "parse_error"
    if isinstance(obj, list):
        rules = [r for r in obj if isinstance(r, dict)]
        return rules, [], "success_recovered_list" if recovered else "success_list", None
    if not isinstance(obj, dict):
        return [], [], "invalid_top_level", f"unexpected type {type(obj).__name__}"
    rules = [r for r in obj.get("rules", []) if isinstance(r, dict)]
    skipped = [r for r in obj.get("skipped_rows", []) if isinstance(r, dict)]
    batch_id = obj.get("batch_id") or fallback_batch_id
    for r in rules:
        r.setdefault("source_batch_id", batch_id)
    return rules, skipped, "success_partial_recovery" if recovered else "success_rules", None


def infer_operator_from_table_context(group_title: str, row_label: str = "", rule_key: str = "", raw_operator: str = ""):
    raw = compact_spaces(raw_operator).lower()
    hay = normalize_text(f"{group_title} {row_label}")
    key = normalize_text(rule_key)

    # Permission/prohibition is genuinely row-local. For numeric table rows,
    # Maximum/Minimum often lives in the group heading instead of the row.
    if raw in {"permitted", "not permitted", "required"} or "not permitted" in hay:
        return "=", "row_text"
    if "minimum lot line setbacks" in hay or "minimum separation" in hay or "minimum" in hay:
        return ">=", "group_title"
    if "maximum lot coverage" in hay or "maximum height" in hay or "maximum" in hay:
        return "<=", "group_title"
    if key.startswith("max_") or "_max_" in key:
        return "<=", "rule_key_default"
    if key.startswith("min_") or "_min_" in key:
        return ">=", "rule_key_default"
    if raw in {"<=", ">=", "="}:
        return raw, "row_text"
    if raw in {"maximum", "max", "not exceed", "up to"}:
        return "<=", "row_text"
    if raw in {"minimum", "min", "at least", "no less than"}:
        return ">=", "row_text"
    return "=", "fallback_unknown"


def normalize_burnaby_table_rule_key(group_title: str, row_label: str, rule: dict) -> str:
    parts = [
        group_title,
        row_label,
        rule.get("rule_key"),
        rule.get("subject"),
        rule.get("condition"),
        rule.get("unit"),
    ]
    text = normalize_text(" ".join("" if p is None else str(p) for p in parts))
    value = normalize_text(str(rule.get("value", "")))
    if "maximum lot coverage" in text:
        if "impervious" in text:
            return "max_impervious_surface"
        return "max_lot_coverage_all_buildings"
    if "maximum height" in text or "height" in text or "storey" in text:
        prefix = "max_accessory_building"
        if "front principal" in text:
            prefix = "max_front_principal"
        elif "rear principal" in text:
            prefix = "max_rear_principal"
        if "storey" in text or "storeys" in value:
            return f"{prefix}_storeys"
        if "flat" in text:
            return f"{prefix}_height_flat_roof"
        if "sloping" in text or "sloped" in text:
            return f"{prefix}_height_sloped_roof"
        return f"{prefix}_height"
    if "minimum lot line setbacks" in text or "setback" in text or "yard" in text:
        if "street yard" in text:
            return "min_street_yard_setback"
        if "lane yard" in text:
            return "min_lane_yard_setback"
        if "interior rear" in text:
            return "min_interior_rear_yard_setback"
        if "interior side" in text:
            return "min_interior_side_yard_setback"
    if "minimum separation" in text or "between" in text or "separation" in text:
        if "front & rear" in text or "front and rear" in text:
            return "min_separation_between_front_and_rear_principals"
        if "front principals" in text:
            return "min_separation_between_front_principals"
        if "rear principals" in text:
            return "min_separation_between_rear_principals"
        if "all other buildings" in text:
            return "min_separation_between_all_other_buildings"
        return "min_building_separation"
    key = normalize_text(rule.get("rule_key", "unknown_rule")).replace(" ", "_")
    return key or "unknown_rule"


def enrich_minimal_table_rule(rule: dict, batch: dict, row_lookup: dict, doc_config: dict, zone: str) -> dict:
    row = row_lookup.get(rule.get("evidence_id"), {})
    row_label = row.get("row_label", "")
    group_title = batch.get("group_title", "")
    key = normalize_burnaby_table_rule_key(group_title, row_label, rule)
    operator, operator_source = infer_operator_from_table_context(group_title, row_label, key, rule.get("operator", ""))
    ev_text = row.get("text", "")
    value = rule.get("value", "")
    unit = rule.get("unit") or infer_unit_near_value(ev_text, value, "")
    subject = rule.get("subject") or row_label or group_title
    condition = rule.get("condition") or ""
    exception = rule.get("exception") or ""
    return {
        "rule_id": f"{batch.get('batch_id')}__rule_{abs(hash((rule.get('evidence_id'), key, value, condition, exception))) % 1000000:06d}",
        "evidence_id": rule.get("evidence_id"),
        "rule_key_suggestion": key,
        "rule_type": key,
        "rule_object": "setback" if "setback" in key else "building_height" if "height" in key or "storeys" in key else "lot_coverage" if "coverage" in key else "separation" if "separation" in key else "other",
        "constraint_type": "max" if key.startswith("max_") else "min" if key.startswith("min_") else "permission",
        "constraint_scope": row_label,
        "subject": subject,
        "applies_to": doc_config.get("building_type", ""),
        "building_type": doc_config.get("building_type", ""),
        "zone": zone,
        "requirement_text": compact_spaces(f"{group_title} | {row_label} | {value} {unit}"),
        "value": value,
        "unit": unit,
        "operator": operator,
        "operator_source": operator_source,
        "group_title": group_title,
        "table_title": batch.get("supporting_context", {}).get("table_title", ""),
        "row_label": row_label,
        "column_headers": batch.get("column_headers", []),
        "evidence_type": "table_group_row",
        "rule_type_source": "table_context",
        "condition": condition,
        "exception": exception,
        "relevance_category": "generic_applicable",
        "value_source_text": ev_text,
        "value_source": "table_group_row",
        "confidence": 0.9,
        "needs_review": bool(exception),
        "review_reason": "exception_scope" if exception else None,
        "source_group_id": batch.get("group_id"),
        "source_batch_id": batch.get("batch_id"),
    }


def _condition_before_value(text: str, start: int) -> str:
    prefix = text[max(0, start - 70):start]
    m = re.search(r"(lots?\s*[<>≤≥=]+\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:sq\.?\s*m|m2|m))\s*:?\s*$", prefix, flags=re.I)
    return compact_spaces(m.group(1)) if m else ""


def _minimal_rules_from_row_values(row: dict, group_title: str) -> list[dict]:
    text = row.get("text", "") or ""
    row_label = row.get("row_label", "") or _row_label_from_text(text)
    lower_group = normalize_text(group_title)
    rules = []
    seen = set()

    def add(value, unit, condition="", exception=None):
        key = (str(value).lower(), str(unit).lower(), str(condition).lower(), str(exception).lower())
        if key in seen:
            return
        seen.add(key)
        rules.append({
            "evidence_id": row.get("evidence_id"),
            "rule_key": row_label or group_title,
            "subject": row_label or group_title,
            "operator": "",
            "value": value,
            "unit": unit,
            "condition": condition or "",
            "exception": exception,
        })

    # Percent rows: condition thresholds such as "Lots < 567 sq. m" describe scope,
    # not a separate numeric rule value.
    for m in re.finditer(r"\b\d+(?:\.\d+)?\s*%", text, flags=re.I):
        add(compact_spaces(m.group(0)), "%", _condition_before_value(text, m.start()))

    # Area values are rules in lot-area/floor-area groups, but often conditions in
    # coverage rows when followed by a colon before a percentage.
    for m in re.finditer(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:sq\.?\s*m|m2|square metres?|square meters?)", text, flags=re.I):
        after = text[m.end():m.end() + 8]
        if "coverage" in lower_group and ":" in after:
            continue
        add(compact_spaces(m.group(0)), "sq. m", "")

    for m in re.finditer(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:m|metres?|meters?)\b", text, flags=re.I):
        # Avoid double counting m in sq. m.
        before = text[max(0, m.start() - 5):m.start()].lower()
        if "sq" in before:
            continue
        exception = None
        if re.search(r"\bexcept\b", text, flags=re.I):
            ex = re.search(r"\bexcept\b(.+)$", text, flags=re.I)
            exception = compact_spaces(ex.group(0)) if ex else "except"
        add(compact_spaces(m.group(0)), "m", "", exception)

    for m in re.finditer(r"\b\d+(?:\.\d+)?\s*storeys?\b", text, flags=re.I):
        add(compact_spaces(m.group(0)), "storeys", "")

    low = normalize_text(text)
    if "not permitted" in low:
        add("not permitted", "", "")
    elif re.search(r"\bpermitted\b", low) and "permitted dwelling units" not in low:
        add("permitted", "", "")
    return rules


def deterministic_minimal_rules_from_table_batch(batch: dict) -> list[dict]:
    minimal = []
    group_title = batch.get("group_title", "")
    for row in batch.get("rows", []):
        minimal.extend(_minimal_rules_from_row_values(row, group_title))
    return minimal


def infer_unit_near_value(evidence_text: str, value, fallback_unit: str = "") -> str:
    if is_missing_value(value):
        return fallback_unit or ""
    text = str(evidence_text or "")
    match = re.search(re.escape(str(value).strip()), text, flags=re.I)
    if not match:
        nums = re.findall(r"\d+(?:\.\d+)?", str(value))
        match = re.search(re.escape(nums[0]), text, flags=re.I) if nums else None
    if match:
        window = text[match.start():match.end() + 24].lower()
        if re.search(r"sq\.?\s*m|m2|m\s*\[\s*2\s*\]|square metres?|square meters?", window):
            return "sq. m"
        if re.search(r"%|percent", window):
            return "percent"
        if re.search(r"storeys?|stories", window):
            return "storeys"
        if re.search(r"\d(?:\.\d+)?\s*(?:m|metres?|meters?)\b", window):
            return "m"
    return fallback_unit or ""


def extract_visible_facts(evidence_text: str) -> dict:
    text = evidence_text or ""
    facts = {
        "number_unit_pairs": [],
        "permission_terms": [],
        "operator_terms": [],
        "constraint_labels": _find_terms(text, ADMISSION_CONSTRAINT_LABELS),
        "target_terms": _find_terms(text, ADMISSION_SUBJECT_TERMS + TARGET_FAMILY_TERMS),
    }
    patterns = [
        r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*%",
        r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:sq\.?\s*m|m2|m\s*\[\s*2\s*\]|square metres?|square meters?)",
        r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:m|metres?|meters?)\b",
        r"\b\d+(?:\.\d+)?\s*storeys?\b",
    ]
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            raw = compact_spaces(match.group(0))
            key = raw.lower()
            if key not in seen:
                seen.add(key)
                facts["number_unit_pairs"].append(raw)
    lower = normalize_text(text)
    if "not permitted" in lower:
        facts["permission_terms"].append("not permitted")
    elif re.search(r"\bpermitted\b", lower):
        facts["permission_terms"].append("permitted")
    for term in ["not exceed", "at least", "maximum", "minimum", "required", "shall", "must", "may be reduced", "subject to", "except"]:
        if term in lower:
            facts["operator_terms"].append(term)
    return facts


def check_target_aware_numeric_coverage(evidence_units: list[dict], rules_for_unit: list[dict]) -> list[dict]:
    warnings = []
    by_ev = {}
    for rule in rules_for_unit:
        if str(rule.get("final_action", "")).upper() != "REJECT":
            by_ev.setdefault(rule.get("evidence_id"), []).append(rule)
    for ev in evidence_units:
        if ev.get("pre_class") not in ADMITTED_PRE_CLASSES:
            continue
        facts = extract_visible_facts(ev.get("text", ""))
        visible = facts["number_unit_pairs"] + facts["permission_terms"]
        if not visible or not (facts["constraint_labels"] or facts["target_terms"]):
            continue
        rule_text = " ".join(
            " ".join(compact_spaces(rule.get(k)).lower() for k in ["value", "unit", "description", "requirement_text", "condition", "exception", "original_excerpt"])
            for rule in by_ev.get(ev.get("evidence_id"), [])
        )
        for raw_value in visible:
            raw = raw_value.lower()
            nums = re.findall(r"\d+(?:, \d{3})*(?:\.\d+)?|\d+(?:,\d{3})*(?:\.\d+)?", raw)
            covered = raw in rule_text if raw in {"permitted", "not permitted"} else bool(nums) and all(n.replace(",", "") in rule_text.replace(",", "") for n in nums)
            if not covered:
                group_rules = by_ev.get(ev.get("evidence_id"), [])
                warnings.append({
                    "source_block_id": ev.get("source_block_id"),
                    "evidence_id": ev.get("evidence_id"),
                    "evidence_type": ev.get("evidence_type"),
                    "evidence_text": ev.get("text"),
                    "warning_type": "unaccounted_visible_fact",
                    "unaccounted_value": raw_value,
                    "visible_facts": facts,
                    "reason_code": "unaccounted_numeric_value",
                    "rule_object": "unknown_rule",
                    "constraint_type": "unknown",
                    "description": f"Evidence unit contains unaccounted visible fact: {raw_value}",
                    "original_excerpt": ev.get("text"),
                    "reason_missed": "evidence_visible_fact_not_covered",
                    "allow_repair": bool(group_rules),
                })
    return warnings


def value_visible_in_evidence(rule: dict, evidence_text: str) -> bool:
    value = rule.get("value")
    if is_missing_value(value):
        return True
    hay = normalize_text(evidence_text)
    val = normalize_text(str(value))
    if val and val in hay:
        return True
    nums = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value))
    return bool(nums) and all(n.replace(",", "") in hay.replace(",", "") for n in nums)


def _table_context_text(rule: dict, evidence_unit: dict | None = None, table_context: dict | None = None) -> str:
    ev = evidence_unit or {}
    ctx = table_context or {}
    parts = [
        ev.get("text", ""),
        ev.get("row_label", ""),
        rule.get("group_title", ""),
        rule.get("table_title", ""),
        rule.get("row_label", ""),
        " ".join(rule.get("column_headers") or []),
        ctx.get("group_title", ""),
        ctx.get("table_title", ""),
        ctx.get("row_label", ""),
        " ".join(ctx.get("column_headers") or []),
    ]
    return normalize_text(" ".join(str(p) for p in parts if p))


def table_context_supports_rule_type(rule: dict, evidence_row: dict | None = None, table_context: dict | None = None) -> bool:
    """For table rows, the rule type often lives in headings/row labels, not the value cell."""
    hay = _table_context_text(rule, evidence_row, table_context)
    key = normalize_text(" ".join(str(rule.get(k, "")) for k in ["rule_key_suggestion", "rule_key", "rule_type", "rule_object"]))
    checks = {
        "coverage": ["coverage", "lot coverage"],
        "impervious": ["impervious"],
        "height": ["height", "sloping roof", "flat roof", "storey", "storeys"],
        "storey": ["storey", "storeys", "height"],
        "setback": ["setback", "yard", "street yard", "lane yard", "side yard", "rear yard"],
        "separation": ["separation", "between"],
        "parking": ["parking"],
        "access": ["access", "driveway"],
        "lot_area": ["lot area", "lot size"],
        "lot_width": ["lot width", "site width"],
        "dwelling": ["permitted dwelling units", "dwelling units"],
    }
    if not key:
        return bool(hay)
    for marker, terms in checks.items():
        if marker in key and any(term in hay for term in terms):
            return True
    fallback_terms = [key.replace("_", " "), rule.get("constraint_scope", ""), rule.get("subject", "")]
    return any(str(term).lower() in hay for term in fallback_terms if term)


def table_context_supports_operator(rule: dict, evidence_row: dict | None = None, table_context: dict | None = None) -> bool:
    ev = evidence_row or {}
    ctx = table_context or {}
    hay = _table_context_text(rule, ev, ctx)
    op = compact_spaces(rule.get("operator")).lower()
    if op == "=" and ("not permitted" in hay or re.search(r"\bpermitted\b", hay)):
        return True
    inferred, _ = infer_operator_from_table_context(
        rule.get("group_title") or ctx.get("group_title") or ev.get("group_title") or "",
        rule.get("row_label") or ctx.get("row_label") or ev.get("row_label") or "",
        rule.get("rule_key_suggestion") or rule.get("rule_key") or rule.get("rule_type") or "",
        rule.get("operator") or "",
    )
    return bool(op) and inferred == op


def repair_evidence_id(rule: dict, available_evidence_units: list[dict], batch_context: dict | None = None):
    """Repair small LLM evidence-id corruptions such as unknown__0002 -> unknown__002."""
    rule = dict(rule)
    original = rule.get("evidence_id")
    by_id = {ev.get("evidence_id"): ev for ev in available_evidence_units if ev.get("evidence_id")}
    if original in by_id:
        rule["evidence_id_repaired"] = False
        return rule.get("evidence_id"), "exact", "exact_match", rule

    def norm_id(value):
        value = re.sub(r"_+", "_", str(value or "").lower())
        value = re.sub(r"(\D)0+(\d+)", r"\1\2", value)
        return value

    batch_ids = {
        row.get("evidence_id")
        for row in (batch_context or {}).get("rows", [])
        if row.get("evidence_id")
    }
    candidates = [by_id[i] for i in batch_ids if i in by_id] or list(by_id.values())
    target_norm = norm_id(original)
    value = str(rule.get("value") or "")
    scored = []
    for ev in candidates:
        eid = ev.get("evidence_id")
        sim = SequenceMatcher(None, target_norm, norm_id(eid)).ratio()
        contains_value = value_visible_in_evidence(rule, ev.get("text", ""))
        score = sim + (0.35 if contains_value else 0.0)
        scored.append((score, sim, contains_value, eid, ev))
    scored.sort(reverse=True, key=lambda x: x[0])
    if scored and scored[0][0] >= 0.72 and (scored[0][1] >= 0.86 or scored[0][2]):
        repaired_id = scored[0][3]
        rule["original_evidence_id"] = original
        rule["evidence_id"] = repaired_id
        rule["evidence_id_repaired"] = True
        rule["evidence_id_repair_reason"] = "fuzzy_id_match_value_visible" if scored[0][2] else "fuzzy_id_match"
        return repaired_id, "repaired", rule["evidence_id_repair_reason"], rule
    rule["evidence_id_repaired"] = False
    rule["original_evidence_id"] = original
    rule["evidence_id_repair_reason"] = "no_safe_match"
    return original, "unrepaired", "no_safe_match", rule


def apply_table_context_to_rule(rule: dict, evidence_unit: dict | None, batch_context: dict | None = None) -> dict:
    rule = dict(rule)
    ev = evidence_unit or {}
    ctx = batch_context or {}
    row = next((r for r in ctx.get("rows", []) if r.get("evidence_id") == rule.get("evidence_id")), {})
    row_label = rule.get("row_label") or row.get("row_label") or ev.get("row_label") or ""
    group_title = rule.get("group_title") or ctx.get("group_title") or ev.get("group_title") or ""
    rule["group_title"] = group_title
    rule["row_label"] = row_label
    rule["table_title"] = rule.get("table_title") or ctx.get("supporting_context", {}).get("table_title", "")
    rule["column_headers"] = rule.get("column_headers") or ctx.get("column_headers") or row.get("column_headers") or []
    if ev.get("evidence_type") in {"table_row", "table_cell"} or ctx.get("group_id"):
        rule["evidence_type"] = rule.get("evidence_type") or "table_group_row"
        key = normalize_burnaby_table_rule_key(group_title, row_label, rule)
        rule["rule_key_suggestion"] = key
        rule.setdefault("rule_type", key)
        op, op_source = infer_operator_from_table_context(group_title, row_label, key, rule.get("operator", ""))
        rule["operator"] = op
        rule["operator_source"] = op_source
        rule["rule_type_source"] = "table_context" if table_context_supports_rule_type(rule, ev, ctx) else "rule_text"
    return rule


def split_mixed_unit_rule(rule: dict, evidence_text: str, table_context: dict | None = None) -> list[dict]:
    """Split dense table rows that contain separate metre and storey/roof values."""
    text = evidence_text or ""
    low = normalize_text(text)
    ctx_title = normalize_text((table_context or {}).get("group_title", ""))
    if "height" not in low and "height" not in ctx_title:
        return [rule]

    base = dict(rule)
    out = []
    row_label = base.get("row_label", "")
    group_title = base.get("group_title") or (table_context or {}).get("group_title", "")

    roof_pairs = []
    for label in ["sloping roof", "flat roof"]:
        m = re.search(label + r".{0,40}?(\d+(?:\.\d+)?)\s*m\b", text, flags=re.I)
        if m:
            roof_pairs.append((label, m.group(1)))
    if roof_pairs:
        raw_condition = normalize_text(base.get("condition", ""))
        raw_value_nums = set(re.findall(r"\d+(?:\.\d+)?", str(base.get("value", ""))))
        for label, value in roof_pairs:
            if raw_condition and ("sloping" in raw_condition or "flat" in raw_condition):
                if label.split()[0] not in raw_condition:
                    continue
            if raw_value_nums and value not in raw_value_nums and len(roof_pairs) > 1:
                continue
            r = dict(base)
            r["value"] = value
            r["unit"] = "m"
            r["condition"] = compact_spaces(r.get("condition") or label)
            r["rule_key_suggestion"] = normalize_burnaby_table_rule_key(group_title, row_label, {**r, "condition": label, "unit": "m"})
            r["rule_type"] = r["rule_key_suggestion"]
            r["requirement_text"] = compact_spaces(f"{group_title} | {row_label} | {label}: {value} m")
            out.append(r)

    storey_values = re.findall(r"\b(\d+(?:\.\d+)?)\s*storeys?\b", text, flags=re.I)
    metre_values = re.findall(r"\b(\d+(?:\.\d+)?)\s*m\b", text, flags=re.I)
    if storey_values and metre_values and not roof_pairs:
        r = dict(base)
        r["value"] = metre_values[0]
        r["unit"] = "m"
        r["rule_key_suggestion"] = normalize_burnaby_table_rule_key(group_title, row_label, {**r, "unit": "m"})
        r["rule_type"] = r["rule_key_suggestion"]
        r["requirement_text"] = compact_spaces(f"{group_title} | {row_label} | {metre_values[0]} m")
        out.append(r)

    for value in storey_values:
        r = dict(base)
        r["value"] = value
        r["unit"] = "storeys"
        r["rule_key_suggestion"] = normalize_burnaby_table_rule_key(group_title, row_label, {**r, "value": f"{value} storeys", "unit": "storeys"})
        r["rule_type"] = r["rule_key_suggestion"]
        r["requirement_text"] = compact_spaces(f"{group_title} | {row_label} | {value} storey")
        out.append(r)

    return out or [rule]


def table_aware_clear_support_gaps(rule: dict, evidence_unit: dict | None = None, table_context: dict | None = None) -> dict:
    rule = dict(rule)
    if not (rule.get("value_source") == "table_group_row" or (evidence_unit or {}).get("evidence_type") in {"table_row", "table_cell"}):
        return rule
    gaps = [g.strip() for g in str(rule.get("support_gaps") or "").split(";") if g.strip()]
    cleared = []
    if "rule_type_not_visible_in_evidence" in gaps and table_context_supports_rule_type(rule, evidence_unit, table_context):
        gaps.remove("rule_type_not_visible_in_evidence")
        cleared.append("rule_type_not_visible_in_evidence")
        rule["rule_type_context_supported"] = True
    if "operator_not_visible_in_evidence" in gaps and table_context_supports_operator(rule, evidence_unit, table_context):
        gaps.remove("operator_not_visible_in_evidence")
        cleared.append("operator_not_visible_in_evidence")
        rule["operator_context_supported"] = True
    if cleared:
        rule["table_context_cleared_gaps"] = "; ".join(cleared)
        rule["support_gaps"] = "; ".join(gaps)
    return rule


def apply_value_source_lock(rule: dict, evidence_unit: dict | None) -> dict:
    """Prevent table context values from being attached to the wrong evidence row."""
    rule = dict(rule)
    ev_text = (evidence_unit or {}).get("text", "")
    source = str(rule.get("value_source") or "").strip().lower()
    if not source:
        rule["value_source"] = "current_evidence_text" if (evidence_unit or {}).get("evidence_type") != "table_row" else "table_group_row"
    if source == "supporting_context":
        rule["value_source_warning"] = "value_from_supporting_context"
        rule["final_action"] = "REJECT"
        rule["reason_code"] = "unsupported_in_evidence"
        return rule
    if not value_visible_in_evidence(rule, ev_text):
        existing = str(rule.get("support_gaps") or "")
        if "value_not_visible_in_evidence" not in existing:
            rule["support_gaps"] = "; ".join(x for x in [existing, "value_not_visible_in_evidence"] if x)
        rule["value_source_warning"] = "value_not_visible_in_cited_evidence"
    if rule.get("value") and not rule.get("unit"):
        unit = infer_unit_near_value(ev_text, rule.get("value"), "")
        if unit:
            rule["unit"] = unit
    return rule


def route_final_action(rule: dict, evidence_unit: dict | None = None) -> dict:
    rule = dict(rule)
    if str(rule.get("final_action", "")).upper() == "REJECT" and rule.get("reason_code"):
        return rule
    ev = evidence_unit or {}
    pre_class = rule.get("pre_class") or ev.get("pre_class")
    relevance = str(rule.get("relevance_category") or "").lower()
    verification = str(rule.get("verification_status") or "").lower()
    support_gaps = str(rule.get("support_gaps") or "")
    review_reasons = str(rule.get("review_reasons") or "")
    validation_status = str(rule.get("block_validation_status") or "")
    evidence_decision = str(rule.get("evidence_decision") or "").lower()
    table_operator_context_supported = (
        "operator_not_visible" in support_gaps
        and (ev.get("evidence_type") in {"table_row", "table_cell"} or rule.get("value_source") == "table_group_row")
        and (str(rule.get("operator_source") or "") in {"group_title", "rule_key_default"} or rule.get("operator_context_supported"))
    )
    if table_operator_context_supported:
        support_gaps = "; ".join(g for g in support_gaps.split("; ") if g and g != "operator_not_visible_in_evidence")
        rule["support_gaps"] = support_gaps
        rule["operator_context_supported"] = True
    table_rule_type_context_supported = (
        "rule_type_not_visible" in support_gaps
        and (ev.get("evidence_type") in {"table_row", "table_cell"} or rule.get("value_source") == "table_group_row")
        and (rule.get("rule_type_context_supported") or str(rule.get("rule_type_source") or "") == "table_context")
    )
    if table_rule_type_context_supported:
        support_gaps = "; ".join(g for g in support_gaps.split("; ") if g and g != "rule_type_not_visible_in_evidence")
        rule["support_gaps"] = support_gaps
        rule["rule_type_context_supported"] = True

    if pre_class in REJECTED_PRE_CLASSES:
        action, reason = "REJECT", REJECT_REASON_BY_PRE_CLASS.get(pre_class, "context_only")
    elif relevance == "unrelated" or evidence_decision == "unrelated":
        action, reason = "REJECT", "not_target_relevant"
    elif verification == "missing_sentence":
        action, reason = "REJECT", "unsupported_in_evidence"
    elif any(g in support_gaps for g in ["value_not_visible", "unit_not_visible", "operator_not_visible", "rule_type_not_visible"]):
        action = "REPAIR"
        reason = "value_not_visible" if "value_not_visible" in support_gaps else "unit_mismatch" if "unit_not_visible" in support_gaps else "operator_not_supported" if "operator_not_visible" in support_gaps else "unsupported_in_evidence"
    elif verification == "needs_human_review" or review_reasons:
        action = "REVIEW"
        reason = "discretionary_language" if "discretion" in review_reasons else "exception_scope" if "exception" in review_reasons or "except" in review_reasons else "condition_unclear"
    elif "condition_not_grounded" in validation_status or "exception_cue" in validation_status:
        action, reason = "REVIEW", "condition_unclear"
    elif str(rule.get("needs_review", "")).lower() in {"true", "1", "yes"}:
        action, reason = "REVIEW", "condition_unclear"
    else:
        action, reason = "ACCEPT", "accepted"
    rule["final_action"] = action
    rule["reason_code"] = reason
    return rule


def make_rejected_evidence_record(ev: dict) -> dict:
    pre_class = ev.get("pre_class", "context_only")
    return {
        "evidence_id": ev.get("evidence_id"),
        "source_block_id": ev.get("source_block_id"),
        "evidence_type": ev.get("evidence_type"),
        "evidence_text": ev.get("text"),
        "pre_class": pre_class,
        "admission_score": ev.get("admission_score"),
        "final_action": "REJECT",
        "reason_code": REJECT_REASON_BY_PRE_CLASS.get(pre_class, "context_only"),
        "reason": ev.get("reason"),
    }


def build_repair_queue_from_rules_and_warnings(rules: list[dict], coverage_warnings: list[dict]) -> list[dict]:
    queue = []
    for rule in rules:
        if str(rule.get("final_action", "")).upper() == "REPAIR":
            queue.append({
                "repair_reason": rule.get("reason_code"),
                "evidence_id": rule.get("evidence_id"),
                "rule_id": rule.get("rule_id"),
                "evidence_text": rule.get("evidence_text"),
                "current_rule": rule,
                "visible_facts": None,
            })
    for warning in coverage_warnings:
        if not warning.get("allow_repair"):
            continue
        queue.append({
            "repair_reason": warning.get("reason_code", "unaccounted_numeric_value"),
            "evidence_id": warning.get("evidence_id"),
            "rule_id": None,
            "evidence_text": warning.get("evidence_text"),
            "current_rule": None,
            "visible_facts": warning.get("visible_facts"),
            "warning": warning,
        })
    return queue
