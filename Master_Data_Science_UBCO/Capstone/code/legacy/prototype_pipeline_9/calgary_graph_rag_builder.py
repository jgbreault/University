#!/usr/bin/env python3
"""Build graph/RAG rule-extraction packs for Calgary local-selection outputs.

This stage does not call an LLM. It starts from pruned candidate windows,
classifies the distinct local blocks covered by those windows, and builds compact
RAG-style context packs that could replace page-level extraction.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from graph_rag_selection import add_list_continuation_closure


ROOT = Path(__file__).resolve().parent
DEFAULT_LOCAL_DIR = ROOT / "outputs" / "calgary" / "01_local_selection"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "calgary" / "03_graph_rag_packs"

TARGET_TERMS = ["backyard suite", "secondary suite"]
PARENT_TERMS = ["parcel", "building", "dwelling", "yard", "parking", "use"]

HEADER_FOOTER_RE = re.compile(
    r"land use bylaw|^\s*\d{1,4}(?:\.\d+)?\s*$",
    re.IGNORECASE,
)
AMENDMENT_CODE_RE = re.compile(r"\b\d+P\d{4}\b")
DELETED_RE = re.compile(r"^\s*(?:\(?\d+(?:\.\d+)?\)?\s*)?deleted\b", re.IGNORECASE)
DELETED_ONLY_SECTION_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s+.*?\bdeleted\b\s*$", re.IGNORECASE)
SECTION_HEADING_RE = re.compile(
    r"^\s*(?:PART\s+\d+|Division\s+\d+|[0-9]{2,4}(?:\.[0-9]+)?\s+[A-Z][A-Za-z0-9 .,\-–/&()]+)",
    re.IGNORECASE,
)
LIST_ITEM_RE = re.compile(r"^\s*\(?[a-z0-9.]{1,5}\)?\s+")
RULE_SIGNAL_RE = re.compile(
    r"\b(?:must|shall|required|requires|does not require|not required|permitted|discretionary|"
    r"may include|may contain|may be|must not|not be more than|minimum|maximum|not exceed|"
    r"setback|separation|parking stalls?|amenity space|floor area|height|privacy wall)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:m\b|metre|metres|meter|meters|square metres?|m2|m²|%|per cent|"
    r"storey|storeys|unit|units|stall|stalls)\b",
    re.IGNORECASE,
)
PURPOSE_ONLY_RE = re.compile(r"\bpurpose\b|intended to|accommodates", re.IGNORECASE)
PERMITTED_USE_LIST_RE = re.compile(r"\bpermitted uses?\b|discretionary uses?\b", re.IGNORECASE)
CORE_SECTION_RE = re.compile(
    r"\b(?:351|352|354)\b|Secondary Suite\s*[–-]\s*|Backyard Suite\s*[–-]\s*",
    re.IGNORECASE,
)
CORE_CONTINUATION_RE = re.compile(
    r"\bBackyard Suite\b.*\b(?:setback|separation|project|height|floor area|amenity space)\b|"
    r"\bSecondary Suite\b.*\b(?:setback|floor area|amenity space)\b",
    re.IGNORECASE | re.DOTALL,
)
DEFINITION_SECTION_RE = re.compile(r"\b(?:Defined Uses|Definitions and Methods|means a use|“[^”]+”|\"[^\"]+\")", re.IGNORECASE)
PARKING_SECTION_RE = re.compile(r"\bparking\b|motor vehicle parking stalls?|bicycle parking", re.IGNORECASE)
PERMIT_NOTICE_RE = re.compile(r"\bdevelopment permits?|notice posted|building permit", re.IGNORECASE)
DISTRICT_SECTION_RE = re.compile(r"\bDistrict|R-CG|R-C1|R-G|R-2M|R-1|Residential", re.IGNORECASE)
FLOODWAY_RE = re.compile(r"\bfloodway|flood fringe|overland flow", re.IGNORECASE)
GENERAL_RULES_SCOPE_RE = re.compile(r"\bPART\s+5\s*[-–]\s*DIVISION\s+1\b(?!\d)", re.IGNORECASE)
PART5_DISTRICT_SCOPE_RE = re.compile(r"\bPART\s+5\s*[-–]\s*DIVISION\s+(?!1\b)\d+\b", re.IGNORECASE)
DISTRICT_SCOPE_RE = re.compile(
    r"\bPART\s+(?:5|6|11|15)\s*[-–]\s*(?:DIVISION|Division)\s+\d+\b|"
    r"\b(?:R-[A-Z0-9]+|M-[A-Z0-9]+|R-CG|R-Gm|H-GO|CC-MH)\b",
    re.IGNORECASE,
)
DIMENSIONAL_RULE_RE = re.compile(
    r"\b(?:Parcel Width|Parcel Depth|Parcel Area|Parcel Coverage|Building Setback|Building Height|"
    r"Building Depth|Density|Floor Area Ratio|Motor Vehicle Parking|Bicycle Parking|Mobility Storage|"
    r"Driveway|Setback Areas?|Private Amenity Space|Main Residential Buildings?|"
    r"minimum|maximum|no requirement|must not exceed|not be more than)\b",
    re.IGNORECASE,
)
UNIVERSAL_APPLICABLE_RE = re.compile(
    r"\b(?:notice posted|Development Permit|floodway|flood fringe|overland flow|"
    r"motor vehicle parking stall|bicycle parking stall|mobility storage|Controlled Streets Bylaw)\b",
    re.IGNORECASE,
)
SUITE_OR_UNIT_RE = re.compile(
    r"\b(?:Backyard Suite|Secondary Suite|suite|suites|Dwelling Unit|Dwelling Units)\b",
    re.IGNORECASE,
)
EXPLICIT_SUITE_RULE_RE = re.compile(
    r"\b(?:Backyard Suite|Secondary Suite|units and suites|unit or suite|suites?)\b",
    re.IGNORECASE,
)
DISTRICT_USE_TABLE_RE = re.compile(
    r"\b(?:Permitted Uses|Discretionary Uses|additional permitted uses|additional discretionary uses|"
    r"permitted and discretionary uses)\b",
    re.IGNORECASE,
)
DISTRICT_PAGE_RE = re.compile(
    r"\b(?:PART\s+(?:5|6|14)\s*[-–]\s*DIVISION|Residential|Multi-Residential|Housing\s+[-–]\s+Grade|"
    r"\bR-[A-Z0-9]+|\bM-[A-Z0-9]+|\bH-GO\b)",
    re.IGNORECASE,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_amendments(text: str) -> str:
    return clean(AMENDMENT_CODE_RE.sub(" ", text))


def term_hits(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def classify_block(block: dict[str, Any], covered_ids: set[str]) -> dict[str, Any]:
    raw = block.get("text", "")
    text = strip_amendments(raw)
    target_hits = term_hits(text, TARGET_TERMS)
    parent_hits = term_hits(text, PARENT_TERMS)
    is_header_footer = bool(HEADER_FOOTER_RE.search(text))
    is_deleted_only_section = (
        bool(DELETED_ONLY_SECTION_RE.match(text))
        and len(text) < 220
        and text.count(";") == 0
    )
    is_deleted = bool(DELETED_RE.match(text) or is_deleted_only_section)
    is_heading = (bool(SECTION_HEADING_RE.match(text)) or len(text) < 45) and not is_header_footer
    rule_signal = bool(RULE_SIGNAL_RE.search(text))
    is_purpose = bool(PURPOSE_ONLY_RE.search(text)) and not rule_signal
    is_use_list = bool(PERMITTED_USE_LIST_RE.search(text)) or (
        bool(target_hits) and not rule_signal and LIST_ITEM_RE.match(text)
    )
    is_junk = is_header_footer or is_deleted

    if is_junk:
        role = "junk"
    elif rule_signal and target_hits:
        role = "target_rule"
    elif rule_signal:
        role = "rule_evidence"
    elif target_hits and is_use_list:
        role = "use_listing"
    elif target_hits:
        role = "target_context"
    elif is_heading:
        role = "scope_heading"
    elif is_purpose:
        role = "purpose_context"
    elif parent_hits:
        role = "parent_context"
    else:
        role = "context"

    return {
        **block,
        "covered_by_candidate_window": block["block_id"] in covered_ids,
        "text_compact": text,
        "char_count": len(text),
        "target_hits": target_hits,
        "parent_hits": parent_hits,
        "rule_signal": rule_signal,
        "is_heading": is_heading,
        "is_junk": is_junk,
        "graph_role": role,
    }


def classify_applicability(node: dict[str, Any], scope: str = "") -> str:
    """Classify how a block should be used by downstream extraction."""
    text = f"{scope} {node['text_compact']}"
    role = node["graph_role"]
    in_general_rules_scope = bool(GENERAL_RULES_SCOPE_RE.search(scope))
    in_part5_district_scope = bool(PART5_DISTRICT_SCOPE_RE.search(scope))
    if node["is_junk"]:
        return "discard_noise"
    if DEFINITION_SECTION_RE.search(text) and node["target_hits"]:
        return "definition_context"
    if PERMITTED_USE_LIST_RE.search(text) or (
        role == "use_listing" and node["target_hits"] and DISTRICT_SECTION_RE.search(text)
    ):
        return "use_permission"
    if PERMIT_NOTICE_RE.search(text) and node["target_hits"]:
        return "universal_applicable_rule"
    if FLOODWAY_RE.search(text) and node["target_hits"]:
        return "universal_applicable_rule"
    if UNIVERSAL_APPLICABLE_RE.search(text) and SUITE_OR_UNIT_RE.search(text):
        return "universal_applicable_rule"
    if (
        DIMENSIONAL_RULE_RE.search(text)
        and SUITE_OR_UNIT_RE.search(text)
        and DISTRICT_SCOPE_RE.search(text)
        and not in_general_rules_scope
    ):
        return "district_dimensional_override"
    if PARKING_SECTION_RE.search(text) and node["target_hits"]:
        return "universal_applicable_rule"
    if (
        (CORE_SECTION_RE.search(text) or CORE_CONTINUATION_RE.search(text))
        and role in {"target_rule", "rule_evidence", "target_context", "use_listing"}
        and not DELETED_RE.search(text)
    ):
        if in_part5_district_scope:
            return "district_rule"
        if not in_general_rules_scope and not re.search(r"\b(?:351|352|353|354|355|356)\b", node["text_compact"]):
            return "related_context"
        return "core_rule"
    if role in {"scope_heading", "purpose_context"}:
        return "scope_context"
    if role in {"target_rule", "rule_evidence", "target_context", "use_listing"}:
        return "related_context"
    return "discard_noise"


def nearest_scope(block: dict[str, Any], blocks_by_page: dict[int, list[dict[str, Any]]]) -> str:
    page = int(block["page_number"])
    order = int(block.get("page_block_index", 0))
    page_blocks = blocks_by_page.get(page, [])
    previous = [
        candidate for candidate in page_blocks
        if int(candidate.get("page_block_index", 0)) <= order
        and candidate["graph_role"] in {"scope_heading", "target_context", "purpose_context"}
    ]
    if previous:
        return previous[-1]["text_compact"][:120]
    return f"page_{page:04d}"


def is_district_use_sweep_candidate(node: dict[str, Any]) -> bool:
    """Pull district use-table rows missed by the local candidate-window pass."""
    page = int(node["page_number"])
    text = node["text_compact"]
    if page < 400 or node["is_junk"] or not node["target_hits"]:
        return False
    if re.search(r"^\s*CONTENTS\b|\.{5,}", text, re.IGNORECASE):
        return False
    return bool(DISTRICT_USE_TABLE_RE.search(text) or LIST_ITEM_RE.match(text))


def add_district_use_sweep_ids(nodes: list[dict[str, Any]], selected_ids: set[str]) -> None:
    """Supplement RAG input with full-document district use tables.

    The local-selection candidate windows are tuned for rule-heavy text and can miss
    district use tables when the anchor score is not high enough. Use eligibility is
    district-specific, so we add those blocks from the full local block inventory.
    """
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_id = {node["block_id"]: node for node in nodes}
    for node in nodes:
        by_page[int(node["page_number"])].append(node)
    for page_nodes in by_page.values():
        page_nodes.sort(key=lambda row: int(row.get("page_block_index", 0)))

    for node in nodes:
        if not is_district_use_sweep_candidate(node):
            continue
        selected_ids.add(node["block_id"])
        page = int(node["page_number"])
        order = int(node.get("page_block_index", 0))

        # Include same-page district headers and immediate table continuations.
        for candidate in by_page.get(page, []):
            candidate_order = int(candidate.get("page_block_index", 0))
            if not candidate["is_junk"] and candidate_order <= order and (
                candidate["graph_role"] == "scope_heading"
                or DISTRICT_PAGE_RE.search(candidate["text_compact"])
                or DISTRICT_USE_TABLE_RE.search(candidate["text_compact"])
            ):
                selected_ids.add(candidate["block_id"])
            if order < candidate_order <= order + 2 and (
                candidate["target_hits"]
                or DISTRICT_USE_TABLE_RE.search(candidate["text_compact"])
                or LIST_ITEM_RE.match(candidate["text_compact"])
            ) and not candidate["is_junk"]:
                selected_ids.add(candidate["block_id"])

        # If a use list continues at top of the next page, keep the page header too.
        for candidate in by_page.get(page + 1, [])[:3]:
            if candidate["is_junk"]:
                continue
            if candidate["graph_role"] == "scope_heading" or DISTRICT_PAGE_RE.search(candidate["text_compact"]):
                selected_ids.add(candidate["block_id"])
            if candidate["target_hits"] and not candidate["is_junk"]:
                selected_ids.add(candidate["block_id"])

        # Also keep the previous page header for tables split over a page boundary.
        for candidate in by_page.get(page - 1, []):
            if (
                not candidate["is_junk"]
                and candidate["graph_role"] == "scope_heading"
                and DISTRICT_PAGE_RE.search(candidate["text_compact"])
            ):
                selected_ids.add(candidate["block_id"])


def is_applicable_rule_sweep_candidate(node: dict[str, Any]) -> bool:
    text = node["text_compact"]
    page = int(node["page_number"])
    if page < 80 or node["is_junk"]:
        return False
    if re.search(r"^\s*CONTENTS\b|\.{5,}", text, re.IGNORECASE):
        return False
    if DEFINITION_SECTION_RE.search(text) or re.search(r"\bmeans a use where\b", text, re.IGNORECASE):
        return False
    if not EXPLICIT_SUITE_RULE_RE.search(text):
        return False
    if page < 400:
        return bool(UNIVERSAL_APPLICABLE_RE.search(text))
    return bool(DIMENSIONAL_RULE_RE.search(text) or UNIVERSAL_APPLICABLE_RE.search(text))


def add_applicable_rule_sweep_ids(nodes: list[dict[str, Any]], selected_ids: set[str]) -> None:
    """Supplement indirect suite rules such as all-units parking or district dimensions."""
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        by_page[int(node["page_number"])].append(node)
    for page_nodes in by_page.values():
        page_nodes.sort(key=lambda row: int(row.get("page_block_index", 0)))

    for node in nodes:
        if not is_applicable_rule_sweep_candidate(node):
            continue
        selected_ids.add(node["block_id"])
        page = int(node["page_number"])
        order = int(node.get("page_block_index", 0))

        for candidate in by_page.get(page, []):
            candidate_order = int(candidate.get("page_block_index", 0))
            if candidate_order <= order and not candidate["is_junk"] and (
                candidate["graph_role"] == "scope_heading"
                or DISTRICT_SCOPE_RE.search(candidate["text_compact"])
                or UNIVERSAL_APPLICABLE_RE.search(candidate["text_compact"])
            ):
                selected_ids.add(candidate["block_id"])
            if order < candidate_order <= order + 1 and not candidate["is_junk"] and (
                SUITE_OR_UNIT_RE.search(candidate["text_compact"])
                or DIMENSIONAL_RULE_RE.search(candidate["text_compact"])
            ):
                selected_ids.add(candidate["block_id"])


def build_packs(nodes: list[dict[str, Any]], selected_ids: set[str]) -> list[dict[str, Any]]:
    selected = [node for node in nodes if node["block_id"] in selected_ids]
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        by_page[int(node["page_number"])].append(node)
    for page_nodes in by_page.values():
        page_nodes.sort(key=lambda row: int(row.get("page_block_index", 0)))

    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for node in selected:
        grouped[(int(node["page_number"]), nearest_scope(node, by_page))].append(node)

    packs: list[dict[str, Any]] = []
    for index, ((page, scope), group) in enumerate(sorted(grouped.items()), start=1):
        group.sort(key=lambda row: int(row.get("page_block_index", 0)))
        group = [
            node for node in group
            if classify_applicability(node, scope) != "discard_noise"
        ]
        if not group:
            continue
        if all(node["graph_role"] in {"scope_heading", "purpose_context"} for node in group):
            continue
        applicability_counts = Counter(
            classify_applicability(node, scope)
            for node in group
            if node["graph_role"] != "scope_heading"
        )
        if not applicability_counts:
            pack_applicability = "scope_context"
        else:
            pack_applicability = max(
                applicability_counts,
                key=lambda label: (
                    {
                        "core_rule": 5,
                        "district_dimensional_override": 4,
                        "universal_applicable_rule": 4,
                        "district_rule": 4,
                        "use_permission": 3,
                        "definition_context": 3,
                        "general_reference": 2,
                        "related_context": 1,
                        "scope_context": 0,
                        "discard_noise": -1,
                    }.get(label, 0),
                    applicability_counts[label],
                ),
            )
        packs.append({
            "pack_id": f"calgary_graph_pack_{index:03d}",
            "page_number": page,
            "scope": scope,
            "applicability": pack_applicability,
            "applicability_counts": dict(applicability_counts),
            "roles": dict(Counter(node["graph_role"] for node in group)),
            "block_ids": [node["block_id"] for node in group],
            "char_count": sum(node["char_count"] for node in group),
            "evidence_blocks": [
                {
                    "source_id": node["block_id"],
                    "role": node["graph_role"],
                    "applicability": classify_applicability(node, scope),
                    "text": node["text"],
                }
                for node in group
            ],
        })
    return packs


def run_experiment(local_dir: Path, output_dir: Path) -> dict[str, Any]:
    summary = read_json(local_dir / "summary.json")
    windows = read_jsonl(local_dir / "candidate_windows.jsonl")
    all_blocks = read_jsonl(local_dir / "local_blocks_scored.jsonl")

    covered_ids: set[str] = set()
    for window in windows:
        covered_ids.update(window.get("local_block_ids", []))

    all_nodes = [classify_block(block, covered_ids) for block in all_blocks]
    covered_nodes = [node for node in all_nodes if node["block_id"] in covered_ids]

    selected_ids = {
        node["block_id"]
        for node in covered_nodes
        if node["graph_role"] in {
            "target_rule",
            "rule_evidence",
            "target_context",
            "use_listing",
            "purpose_context",
        }
        and not node["is_junk"]
    }
    add_district_use_sweep_ids(all_nodes, selected_ids)
    after_district_use_sweep_ids = set(selected_ids)
    add_applicable_rule_sweep_ids(all_nodes, selected_ids)
    after_applicable_rule_sweep_ids = set(selected_ids)
    list_continuation_added_ids = add_list_continuation_closure(
        all_nodes,
        selected_ids,
        order_key="page_block_index",
        heading_roles={"scope_heading", "purpose_context"},
    )

    # Keep immediate previous same-page scope for every selected rule evidence block.
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in all_nodes:
        by_page[int(node["page_number"])].append(node)
    for page_nodes in by_page.values():
        page_nodes.sort(key=lambda row: int(row.get("page_block_index", 0)))
        latest_scope = ""
        for node in page_nodes:
            if node["graph_role"] in {"scope_heading", "purpose_context", "target_context"} and not node["is_junk"]:
                latest_scope = node["block_id"]
            if node["block_id"] in selected_ids and latest_scope:
                selected_ids.add(latest_scope)

    nodes = [node for node in all_nodes if node["block_id"] in covered_ids or node["block_id"] in selected_ids]
    packs = build_packs(all_nodes, selected_ids)
    pack_applicability = Counter(pack["applicability"] for pack in packs)
    selected_applicability = Counter()
    for pack in packs:
        for block in pack["evidence_blocks"]:
            selected_applicability[block["applicability"]] += 1

    covered_chars = sum(node["char_count"] for node in covered_nodes)
    selected_chars = sum(node["char_count"] for node in all_nodes if node["block_id"] in selected_ids)
    selected_pages = sorted({node["page_number"] for node in all_nodes if node["block_id"] in selected_ids})

    # Batched call estimate for pack-based text extraction.
    max_chars_per_call = 3000
    estimated_calls = 0
    current = 0
    for pack in sorted(packs, key=lambda row: (row["page_number"], row["pack_id"])):
        if current and current + pack["char_count"] > max_chars_per_call:
            estimated_calls += 1
            current = 0
        current += pack["char_count"]
    if current:
        estimated_calls += 1

    result = {
        "case": "calgary_pipeline9_graph_rag_local_selection",
        "local_selection_summary": {
            "pdf_page_count": summary["pdf_page_count"],
            "local_block_count": summary["local_block_count"],
            "candidate_window_count": summary["candidate_window_count"],
            "candidate_window_pages": len(summary["candidate_window_pages"]),
            "recommended_visual_page_count": summary["recommended_visual_page_count"],
        },
        "window_covered_blocks": {
            "distinct_block_count": len(covered_nodes),
            "distinct_page_count": len({node["page_number"] for node in covered_nodes}),
            "char_count": covered_chars,
            "roles": dict(Counter(node["graph_role"] for node in covered_nodes)),
        },
        "graph_rag_pack_policy": {
            "selected_block_count": len(selected_ids),
            "selected_page_count": len(selected_pages),
            "selected_pages": selected_pages,
            "selected_char_count": selected_chars,
            "context_pack_count": len(packs),
            "estimated_text_extraction_calls_if_batched": estimated_calls,
            "batch_char_budget": max_chars_per_call,
            "block_reduction_vs_window_blocks_percent": round(100 * (1 - len(selected_ids) / len(covered_nodes)), 1),
            "char_reduction_vs_window_blocks_percent": round(100 * (1 - selected_chars / covered_chars), 1),
            "page_reduction_vs_visual_pages_percent": round(
                100 * (1 - len(selected_pages) / summary["recommended_visual_page_count"]), 1
            ),
            "roles": dict(Counter(node["graph_role"] for node in all_nodes if node["block_id"] in selected_ids)),
            "pack_applicability": dict(pack_applicability),
            "selected_block_applicability": dict(selected_applicability),
            "recommended_extraction_plan": {
                "extract_now": {
                    "applicability": ["core_rule"],
                    "pack_count": pack_applicability.get("core_rule", 0),
                    "estimated_chars": sum(
                        pack["char_count"] for pack in packs if pack["applicability"] == "core_rule"
                    ),
                },
                "extract_separately": {
                    "applicability": ["use_permission"],
                    "pack_count": pack_applicability.get("use_permission", 0),
                    "estimated_chars": sum(
                        pack["char_count"] for pack in packs if pack["applicability"] == "use_permission"
                    ),
                },
                "district_specific_later": {
                    "applicability": ["district_rule", "district_dimensional_override"],
                    "pack_count": pack_applicability.get("district_rule", 0)
                    + pack_applicability.get("district_dimensional_override", 0),
                    "estimated_chars": sum(
                        pack["char_count"] for pack in packs
                        if pack["applicability"] in {"district_rule", "district_dimensional_override"}
                    ),
                },
                "universal_applicable": {
                    "applicability": ["universal_applicable_rule"],
                    "pack_count": pack_applicability.get("universal_applicable_rule", 0),
                    "estimated_chars": sum(
                        pack["char_count"] for pack in packs if pack["applicability"] == "universal_applicable_rule"
                    ),
                },
                "context_only_or_later": {
                    "applicability": ["definition_context", "general_reference", "related_context", "scope_context"],
                    "pack_count": sum(
                        pack_applicability.get(label, 0)
                        for label in ["definition_context", "general_reference", "related_context", "scope_context"]
                    ),
                },
            },
        },
        "district_use_sweep": {
            "supplemental_selected_block_count": len(after_district_use_sweep_ids - covered_ids),
            "supplemental_selected_pages": sorted(
                {node["page_number"] for node in all_nodes if node["block_id"] in after_district_use_sweep_ids - covered_ids}
            ),
        },
        "applicable_rule_sweep": {
            "supplemental_selected_block_count": len(after_applicable_rule_sweep_ids - after_district_use_sweep_ids),
            "supplemental_selected_pages": sorted(
                {
                    node["page_number"]
                    for node in all_nodes
                    if node["block_id"] in after_applicable_rule_sweep_ids - after_district_use_sweep_ids
                }
            ),
        },
        "list_continuation_closure": {
            "supplemental_selected_block_count": len(list_continuation_added_ids),
            "supplemental_selected_pages": sorted(
                {node["page_number"] for node in all_nodes if node["block_id"] in list_continuation_added_ids}
            ),
        },
        "discarded_roles": dict(Counter(node["graph_role"] for node in covered_nodes if node["block_id"] not in selected_ids)),
    }

    write_jsonl(output_dir / "block_graph_nodes.jsonl", nodes)
    write_jsonl(output_dir / "retrieval_packs.jsonl", packs)
    write_jsonl(
        output_dir / "extract_now_core_packs.jsonl",
        [pack for pack in packs if pack["applicability"] == "core_rule"],
    )
    write_jsonl(
        output_dir / "extract_separately_use_permission_packs.jsonl",
        [pack for pack in packs if pack["applicability"] == "use_permission"],
    )
    write_jsonl(
        output_dir / "district_specific_later_packs.jsonl",
        [pack for pack in packs if pack["applicability"] == "district_rule"],
    )
    write_jsonl(
        output_dir / "district_dimensional_overrides_packs.jsonl",
        [pack for pack in packs if pack["applicability"] == "district_dimensional_override"],
    )
    write_jsonl(
        output_dir / "universal_applicable_rules_packs.jsonl",
        [pack for pack in packs if pack["applicability"] == "universal_applicable_rule"],
    )
    write_jsonl(
        output_dir / "context_only_or_later_packs.jsonl",
        [
            pack for pack in packs
            if pack["applicability"] in {"definition_context", "general_reference", "related_context", "scope_context"}
        ],
    )
    write_json(output_dir / "experiment_summary.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, default=DEFAULT_LOCAL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_experiment(args.local_dir, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
