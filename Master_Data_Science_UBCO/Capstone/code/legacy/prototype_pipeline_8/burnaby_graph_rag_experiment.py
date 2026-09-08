#!/usr/bin/env python3
"""Offline graph/RAG packing experiment for the Pipeline 8 Burnaby case.

This does not call an LLM. It reuses existing Pipeline 8 Burnaby artifacts and
asks: if rule extraction consumed compact graph context packs instead of whole
page text batches, how much text could we send while still covering existing
rule source blocks?
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
DEFAULT_RUN_DIR = ROOT / "outputs_local" / "burnaby"
DEFAULT_OUTPUT_DIR = ROOT / "experiments" / "burnaby_graph_rag"

TARGET_TERMS = [
    "small-scale multi-unit",
    "front principal building",
    "rear principal building",
]
PARENT_TERMS = [
    "principal building",
    "dwelling unit",
    "lot",
    "yard",
    "parking",
    "separation",
]

RULE_SIGNAL_RE = re.compile(
    r"\b(?:shall|must|required|not required|permitted|not permitted|prohibited|"
    r"minimum|maximum|not exceed|may exceed|may project|may be|subject to)\b|"
    r"\b(?:be located|comply with|does not apply|as per Section|provides direct)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:m\b|m2\b|m²|%|storey|storeys|unit|units)\b",
    re.IGNORECASE,
)
SECTION_RE = re.compile(r"\b\d+(?:\.\d+){1,}\b")
FOOTER_RE = re.compile(r"City of Burnaby.*Zoning Bylaw|^\s*Page\s+\d+\s*$", re.IGNORECASE)
AMENDMENT_RE = re.compile(r"^\s*\(B/L No\.[^)]+\)\s*$", re.IGNORECASE)
DIAGRAM_RE = re.compile(r"^\s*Diagram:", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^\s*\([a-z0-9]{1,3}\)\s+", re.IGNORECASE)
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


def term_hits(text: str, terms: list[str]) -> list[str]:
    lowered = clean(text).lower()
    return [term for term in terms if term in lowered]


def classify_block(block: dict[str, Any]) -> dict[str, Any]:
    text = block.get("text", "")
    compact = clean(text)
    is_footer = bool(FOOTER_RE.search(compact))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    is_amendment = bool(lines) and all(AMENDMENT_RE.match(line) for line in lines)
    is_diagram = bool(DIAGRAM_RE.match(compact))
    is_heading = block.get("block_type") == "heading" or bool(
        SECTION_RE.match(compact) and len(compact) <= 80
    )
    rule_signal = bool(RULE_SIGNAL_RE.search(compact))
    section_label = " ".join(block.get("section_path") or [block.get("parent_context", "")])
    if not rule_signal and (
        "permitted uses" in clean(block.get("parent_context", "")).lower()
        or section_label.strip() == "101.2"
    ):
        rule_signal = bool(SECTION_RE.search(compact) and re.search(r"\buses?\b", compact, re.IGNORECASE))
    target_hits = term_hits(compact, TARGET_TERMS)
    parent_hits = term_hits(compact, PARENT_TERMS)
    is_junk = is_footer or is_amendment or is_diagram
    if is_junk:
        role = "junk"
    elif target_hits:
        role = "target_anchor"
    elif rule_signal:
        role = "rule_evidence"
    elif is_heading:
        role = "scope_heading"
    elif parent_hits:
        role = "parent_context"
    else:
        role = "context"
    return {
        **block,
        "text_compact": compact,
        "char_count": len(compact),
        "target_hits": target_hits,
        "parent_hits": parent_hits,
        "rule_signal": rule_signal,
        "is_heading": is_heading,
        "is_junk": is_junk,
        "graph_role": role,
    }


def infer_continuation_sections(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill obvious cross-page/list continuations with the last real section.

    Local PDF layout sometimes emits the first block on a new page with an empty
    section_path, even though it is visibly a numbered footnote/list continuation
    from the previous page. This preserves scope without asking an LLM.
    """
    enriched: list[dict[str, Any]] = []
    current_section = ""
    continuation_re = re.compile(r"^\s*(?:\.\d+|\([a-z0-9]{1,3}\))(?=\s|$)", re.IGNORECASE)
    for node in sorted(nodes, key=lambda row: (int(row["page_number"]), int(row.get("reading_order", 0)))):
        updated = dict(node)
        section_path = updated.get("section_path") or []
        if section_path and not updated["is_junk"]:
            label = " > ".join(str(part) for part in section_path if str(part).strip())
            if AMENDMENT_RE.match(label) and current_section and updated["rule_signal"]:
                updated["section_path"] = [current_section]
                updated["parent_context"] = current_section
                updated["inferred_section_path"] = True
            elif SECTION_RE.search(label):
                current_section = label
        elif current_section and continuation_re.match(updated["text_compact"]):
            updated["section_path"] = [current_section]
            updated["parent_context"] = current_section
            updated["inferred_section_path"] = True
        enriched.append(updated)
    return enriched


def build_edges(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        by_page[int(node["page_number"])].append(node)

    edges: list[dict[str, str]] = []
    latest_heading = ""
    for page in sorted(by_page):
        page_nodes = sorted(by_page[page], key=lambda row: int(row.get("reading_order", 0)))
        for prev, cur in zip(page_nodes, page_nodes[1:]):
            edges.append({"source": prev["block_id"], "target": cur["block_id"], "edge_type": "NEXT"})
            edges.append({"source": cur["block_id"], "target": prev["block_id"], "edge_type": "PREV"})
        for node in page_nodes:
            if node["is_heading"] and not node["is_junk"]:
                latest_heading = node["block_id"]
            elif latest_heading and not node["is_junk"]:
                edges.append({"source": node["block_id"], "target": latest_heading, "edge_type": "PARENT_SECTION"})
    return edges


def selected_context_ids(nodes: list[dict[str, Any]], table_regions: list[dict[str, Any]]) -> set[str]:
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    selected: set[str] = set()
    table_pages = {int(region["page_number"]) for region in table_regions}

    for node in nodes:
        by_page[int(node["page_number"])].append(node)
        if node["is_junk"]:
            continue
        # The core graph/RAG policy: keep direct targets, rule evidence, and
        # headings. Keep parent context only on pages where a target/table exists.
        if node["graph_role"] in {"target_anchor", "rule_evidence", "scope_heading"}:
            selected.add(node["block_id"])
        elif node["graph_role"] == "parent_context" and int(node["page_number"]) in table_pages:
            selected.add(node["block_id"])

    # Add immediate previous heading for every selected evidence node.
    for page, page_nodes in by_page.items():
        page_nodes = sorted(page_nodes, key=lambda row: int(row.get("reading_order", 0)))
        last_heading = ""
        for node in page_nodes:
            if node["is_heading"] and not node["is_junk"]:
                last_heading = node["block_id"]
            if node["is_junk"]:
                continue
            if node["block_id"] in selected and last_heading:
                selected.add(last_heading)
    add_list_continuation_closure(
        nodes,
        selected,
        order_key="reading_order",
        heading_roles={"scope_heading"},
    )
    return selected


def build_packs(
    nodes: list[dict[str, Any]],
    table_regions: list[dict[str, Any]],
    selected_ids: set[str],
) -> list[dict[str, Any]]:
    nodes_by_id = {node["block_id"]: node for node in nodes}
    selected_nodes = [nodes_by_id[node_id] for node_id in selected_ids if node_id in nodes_by_id]
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for node in selected_nodes:
        section = " > ".join(node.get("section_path") or [node.get("parent_context") or "unknown"])
        grouped[(int(node["page_number"]), section)].append(node)

    table_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for region in table_regions:
        table_by_page[int(region["page_number"])].append(region)

    packs: list[dict[str, Any]] = []
    for index, ((page, section), group_nodes) in enumerate(sorted(grouped.items()), start=1):
        group_nodes = sorted(group_nodes, key=lambda row: int(row.get("reading_order", 0)))
        section_head = section.split(" > ")[-1].strip()
        packs.append({
            "pack_id": f"burnaby_graph_pack_{index:03d}",
            "page_number": page,
            "section": section,
            "roles": Counter(node["graph_role"] for node in group_nodes),
            "block_ids": [node["block_id"] for node in group_nodes],
            "char_count": sum(node["char_count"] for node in group_nodes),
            "evidence_blocks": [
                {
                    "source_id": node["block_id"],
                    "role": node["graph_role"],
                    "section_path": node.get("section_path", []),
                    "text": node.get("text", ""),
                }
                for node in group_nodes
            ],
            "nearby_tables": [
                {
                    "region_id": region["region_id"],
                    "section_heading": region.get("section_heading", ""),
                    "image_path": region.get("image_path", ""),
                }
                for region in table_by_page.get(page, [])
                if region.get("section_heading", "").strip() == section_head
            ],
        })
    return packs


def run_experiment(run_dir: Path, output_dir: Path) -> dict[str, Any]:
    visual_dir = run_dir / "03_visual_blocks"
    rules_dir = run_dir / "04_rule_extraction"
    text_blocks = read_jsonl(visual_dir / "text_blocks.jsonl")
    table_regions = read_jsonl(visual_dir / "table_regions.jsonl")
    text_rules = read_json(rules_dir / "text_rules_raw.json")
    table_rules = read_json(rules_dir / "table_rules_raw.json")

    nodes = infer_continuation_sections([classify_block(block) for block in text_blocks])
    edges = build_edges(nodes)
    selected_ids = selected_context_ids(nodes, table_regions)
    packs = build_packs(nodes, table_regions, selected_ids)
    batched_pack_call_count = 0
    current_batch_chars = 0
    max_chars_per_call = 2500
    for pack in sorted(packs, key=lambda row: (row["page_number"], row["pack_id"])):
        pack_chars = int(pack["char_count"])
        if current_batch_chars and current_batch_chars + pack_chars > max_chars_per_call:
            batched_pack_call_count += 1
            current_batch_chars = 0
        current_batch_chars += pack_chars
    if current_batch_chars:
        batched_pack_call_count += 1

    text_rule_source_ids = {rule.get("source_id", "") for rule in text_rules}
    covered_text_rule_sources = text_rule_source_ids & selected_ids
    missed_text_rule_sources = sorted(text_rule_source_ids - selected_ids)

    current_text_chars = sum(len(clean(block.get("text", ""))) for block in text_blocks)
    selected_chars = sum(node["char_count"] for node in nodes if node["block_id"] in selected_ids)
    current_text_pages = sorted({int(block["page_number"]) for block in text_blocks})
    selected_pages = sorted({int(node["page_number"]) for node in nodes if node["block_id"] in selected_ids})

    summary = {
        "case": "burnaby_r1_pipeline8_outputs_local",
        "input_run_dir": str(run_dir.resolve()),
        "current_page_level": {
            "text_pages": current_text_pages,
            "text_page_count": len(current_text_pages),
            "text_block_count": len(text_blocks),
            "text_char_count": current_text_chars,
            "table_region_count": len(table_regions),
            "text_rule_count": len(text_rules),
            "table_rule_count": len(table_rules),
        },
        "graph_rag_pack_policy": {
            "selected_pages": selected_pages,
            "selected_text_block_count": len(selected_ids),
            "selected_text_char_count": selected_chars,
            "context_pack_count": len(packs),
            "estimated_text_extraction_calls_if_batched": batched_pack_call_count,
            "batch_char_budget": max_chars_per_call,
            "table_region_count": len(table_regions),
            "block_reduction_percent": round(100 * (1 - len(selected_ids) / len(text_blocks)), 1),
            "char_reduction_percent": round(100 * (1 - selected_chars / current_text_chars), 1),
        },
        "coverage_against_existing_text_rules": {
            "unique_text_rule_source_blocks": len(text_rule_source_ids),
            "covered_source_blocks": len(covered_text_rule_sources),
            "missed_source_blocks": len(missed_text_rule_sources),
            "source_block_coverage_percent": round(
                100 * len(covered_text_rule_sources) / len(text_rule_source_ids), 1
            ) if text_rule_source_ids else 100.0,
            "missed_source_ids": missed_text_rule_sources,
        },
        "block_roles": dict(Counter(node["graph_role"] for node in nodes)),
        "selected_block_roles": dict(Counter(node["graph_role"] for node in nodes if node["block_id"] in selected_ids)),
    }

    write_jsonl(output_dir / "block_graph_nodes.jsonl", nodes)
    write_jsonl(output_dir / "block_graph_edges.jsonl", edges)
    write_jsonl(output_dir / "retrieval_packs.jsonl", packs)
    write_json(output_dir / "experiment_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_experiment(args.run_dir, args.output_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
