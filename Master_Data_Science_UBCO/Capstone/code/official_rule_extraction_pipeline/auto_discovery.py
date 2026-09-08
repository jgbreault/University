#!/usr/bin/env python3
"""Automatically discover rule-bearing sections before graph/RAG packing.

This stage is deliberately city-light. It uses the target/profile terms already
known by local selection, then discovers candidate sections, rule-heavy blocks,
cross references, and suspicious gaps without requiring hand-written section
names or city-specific exclude lists.
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
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "calgary" / "02_auto_discovery"

AMENDMENT_CODE_RE = re.compile(r"\b\d+P\d{4}\b")
HEADING_RE = re.compile(
    r"^\s*(?:"
    r"PART\s+\d+(?:\s*[-–]\s*DIVISION\s+\d+)?|"
    r"Division\s+\d+|"
    r"\d{1,4}(?:\.\d+)?\s+[A-Z][A-Za-z0-9 .,'/&()\-–]+"
    r")",
    re.IGNORECASE,
)
RULE_SIGNAL_RE = re.compile(
    r"\b(?:must|shall|required|requires|permitted|discretionary|prohibited|"
    r"not permitted|not required|subject to|may be|may include|may contain|may project|"
    r"may approve|may occupy|no more than|minimum|maximum|not exceed|not be more than|setback|separation|parking|"
    r"floor area|height|density|coverage|amenity|permit|notice)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:m\b|metres?|meters?|m2|m²|square metres?|%|per cent|"
    r"storeys?|units?|stalls?)\b",
    re.IGNORECASE,
)
CROSS_REF_RE = re.compile(
    r"\b(?:section|sections|part|division|subsection)\s+"
    r"([0-9]{1,4}(?:\.[0-9]+)?|[IVXLC]+)(?:\s*[-–]\s*(?:division\s+)?\d+)?",
    re.IGNORECASE,
)
LIST_ITEM_RE = re.compile(r"^\s*\([a-z0-9ivxlcdm]{1,5}\)\s+", re.IGNORECASE)
TOC_RE = re.compile(r"\.{4,}|^\s*contents\b|table of contents", re.IGNORECASE)
HEADER_FOOTER_RE = re.compile(r"land use bylaw|zoning bylaw|^\s*page\s+\d+\s*$|^\s*\d{1,4}(?:\.\d+)?\s*$", re.IGNORECASE)
DELETED_ONLY_RE = re.compile(r"^\s*(?:\(?\d+(?:\.\d+)?\)?\s*)?deleted\b", re.IGNORECASE)
AMENDMENT_ONLY_RE = re.compile(r"^\s*(?:\(?B/L No\.[^)]+\)|\d+P\d{4}|[0-9]{1,2}P[0-9]{4},?)+\s*$", re.IGNORECASE)
STRONG_REASONS = {"target_term_hit", "candidate_window", "list_continuation_closure"}
STRUCTURAL_CONTEXT_REASONS = {"same_page_as_target", "same_section_as_target", "list_sibling_closure", "use_section_listing"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def compact_text(value: Any) -> str:
    return clean(AMENDMENT_CODE_RE.sub(" ", str(value or "")))


def term_hits(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]


def noise_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    if HEADER_FOOTER_RE.search(text):
        reasons.append("header_or_footer")
    if TOC_RE.search(text):
        reasons.append("toc_or_index")
    if DELETED_ONLY_RE.match(text) and len(text) < 220 and text.count(";") == 0:
        reasons.append("deleted_only")
    if AMENDMENT_ONLY_RE.match(text):
        reasons.append("amendment_only")
    return reasons


def rule_types(text: str) -> list[str]:
    lowered = text.lower()
    types: list[str] = []
    if re.search(r"\bpermitted uses?|discretionary uses?|not permitted|prohibited\b", lowered):
        types.append("permission")
    if re.search(r"\bminimum|maximum|not exceed|not be more than|setback|height|floor area|density|coverage|amenity|separation\b", lowered):
        types.append("dimensional_standard")
    if re.search(r"\bparking|stall|driveway|loading\b", lowered):
        types.append("parking")
    if re.search(r"\bdevelopment permit|building permit|notice|approval|authority\b", lowered):
        types.append("permit_process")
    if re.search(r"\bmeans\b|defined uses?|definition\b|\"[^\"]+\"", text, re.IGNORECASE):
        types.append("definition")
    if CROSS_REF_RE.search(text):
        types.append("cross_reference")
    if not types and RULE_SIGNAL_RE.search(text):
        types.append("general_rule")
    return types


def confidence_for(reasons: list[str], is_noise: bool) -> float:
    score = 0.0
    weights = {
        "target_term_hit": 0.35,
        "rule_signal": 0.35,
        "candidate_window": 0.15,
        "use_section_listing": 0.35,
        "same_page_as_target": 0.10,
        "same_section_as_target": 0.15,
        "cross_reference": 0.10,
        "parent_term_hit": 0.05,
        "list_item": 0.05,
        "list_continuation_closure": 0.35,
        "list_sibling_closure": 0.35,
    }
    for reason in reasons:
        score += weights.get(reason, 0.0)
    if is_noise:
        score -= 0.45
    return max(0.0, min(1.0, round(score, 3)))


def selection_quality(block: dict[str, Any]) -> dict[str, Any]:
    reasons = set(block.get("selected_because", []))
    selected = bool(block.get("discovery_selected"))
    confidence = float(block.get("discovery_confidence") or 0.0)
    has_rule_signal = "rule_signal" in reasons or bool(block.get("rule_signal"))
    must_keep = selected and bool(reasons & STRONG_REASONS)

    if block.get("noise_reasons"):
        tier = "noise"
        drop_risk = "low"
    elif not selected:
        tier = "discarded"
        drop_risk = "low" if not has_rule_signal and not block.get("target_hits_discovered") else "medium"
    elif must_keep:
        tier = "core"
        drop_risk = "low"
    elif has_rule_signal and confidence >= 0.5:
        tier = "support"
        drop_risk = "low"
    elif reasons & STRUCTURAL_CONTEXT_REASONS:
        tier = "weak_context"
        drop_risk = "medium" if confidence >= 0.45 else "high"
    else:
        tier = "weak_context"
        drop_risk = "high"

    return {
        "selection_tier": tier,
        "must_keep": must_keep,
        "drop_risk": drop_risk,
    }


def annotate_selection_quality(annotated: list[dict[str, Any]]) -> None:
    for block in annotated:
        block.update(selection_quality(block))


def annotate_blocks(
    blocks: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    target_terms: list[str],
    parent_terms: list[str],
) -> list[dict[str, Any]]:
    covered_ids = {block_id for window in windows for block_id in window.get("local_block_ids", [])}
    target_pages = {
        int(block["page_number"])
        for block in blocks
        if term_hits(compact_text(block.get("text", "")), target_terms)
    }

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_page[int(block["page_number"])].append(block)
    for page_blocks in by_page.values():
        page_blocks.sort(key=lambda row: int(row.get("page_block_index", 0)))

    annotated: list[dict[str, Any]] = []
    target_section_pages: dict[str, set[int]] = defaultdict(set)
    active_scope_by_id: dict[str, str] = {}
    for page in sorted(by_page):
        active_scope = f"page_{page:04d}"
        for block in by_page[page]:
            text = compact_text(block.get("text", ""))
            section_path = [str(part).strip() for part in block.get("section_path") or [] if str(part).strip()]
            if block.get("block_type") == "heading" and text and not noise_reasons(text):
                active_scope = text[:180]
            elif section_path:
                if not active_scope.startswith(section_path[-1]):
                    active_scope = " > ".join(section_path)
            elif block.get("parent_context"):
                active_scope = str(block.get("parent_context")).strip()
            elif HEADING_RE.match(text) and not noise_reasons(text):
                active_scope = text[:180]
            active_scope_by_id[block["block_id"]] = active_scope
            if term_hits(text, target_terms):
                target_section_pages[active_scope].add(page)

    for page in sorted(by_page):
        for block in by_page[page]:
            block_id = block["block_id"]
            text = compact_text(block.get("text", ""))
            target_hits = term_hits(text, target_terms)
            parent_hits = term_hits(text, parent_terms)
            types = rule_types(text)
            noise = noise_reasons(text)
            scope = active_scope_by_id.get(block_id, f"page_{page:04d}")
            reasons: list[str] = []
            if target_hits:
                reasons.append("target_term_hit")
            if RULE_SIGNAL_RE.search(text):
                reasons.append("rule_signal")
            if block_id in covered_ids:
                reasons.append("candidate_window")
            if re.search(r"\b(?:permitted|discretionary)\s+uses?\b", scope, re.IGNORECASE):
                reasons.append("use_section_listing")
            if page in target_pages and not target_hits:
                reasons.append("same_page_as_target")
            nearby_target_pages = target_section_pages.get(scope, set())
            if (
                nearby_target_pages
                and not target_hits
                and min(abs(page - target_page) for target_page in nearby_target_pages) <= 2
            ):
                reasons.append("same_section_as_target")
            if CROSS_REF_RE.search(text):
                reasons.append("cross_reference")
            if parent_hits:
                reasons.append("parent_term_hit")
            if LIST_ITEM_RE.match(text):
                reasons.append("list_item")

            confidence = confidence_for(reasons, bool(noise))
            selected = confidence >= 0.35 and not noise
            annotated.append(
                {
                    **block,
                    "text_compact": text,
                    "scope": scope,
                    "target_hits_discovered": target_hits,
                    "parent_hits_discovered": parent_hits,
                    "rule_signal": bool(RULE_SIGNAL_RE.search(text)),
                    "rule_types": types,
                    "cross_references": [match.group(0) for match in CROSS_REF_RE.finditer(text)],
                    "noise_reasons": noise,
                    "selected_because": reasons,
                    "discovery_confidence": confidence,
                    "discovery_selected": selected,
                }
            )
    selected_ids = {block["block_id"] for block in annotated if block["discovery_selected"]}
    closure_added_ids = add_list_continuation_closure(
        annotated,
        selected_ids,
        order_key="page_block_index",
        heading_roles={"scope_heading"},
    )
    sibling_added_ids = add_list_sibling_closure(annotated, selected_ids)
    for block in annotated:
        added_reasons = []
        if block["block_id"] in closure_added_ids:
            added_reasons.append("list_continuation_closure")
        if block["block_id"] in sibling_added_ids:
            added_reasons.append("list_sibling_closure")
        if added_reasons:
            block["discovery_selected"] = True
            for reason in added_reasons:
                if reason not in block["selected_because"]:
                    block["selected_because"].append(reason)
            block["discovery_confidence"] = max(
                block["discovery_confidence"],
                confidence_for(block["selected_because"], bool(block["noise_reasons"])),
            )
    annotate_selection_quality(annotated)
    return annotated


def add_list_sibling_closure(annotated: list[dict[str, Any]], selected_ids: set[str]) -> set[str]:
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in annotated:
        by_page[int(block["page_number"])].append(block)

    added: set[str] = set()
    for page_blocks in by_page.values():
        page_blocks.sort(key=lambda row: int(row.get("page_block_index", 0)))
        group: list[dict[str, Any]] = []

        def flush() -> None:
            nonlocal group
            if len(group) < 2:
                group = []
                return
            if any(block["block_id"] in selected_ids for block in group):
                for block in group:
                    if not block["noise_reasons"]:
                        selected_ids.add(block["block_id"])
                        added.add(block["block_id"])
            group = []

        for block in page_blocks:
            is_item = LIST_ITEM_RE.match(block["text_compact"])
            if not is_item:
                flush()
                continue
            if group and block.get("scope") != group[-1].get("scope"):
                flush()
            group.append(block)
        flush()
    return added


def summarize_sections(annotated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in annotated:
        grouped[block["scope"]].append(block)

    rows: list[dict[str, Any]] = []
    for scope, blocks in grouped.items():
        target_count = sum(bool(block["target_hits_discovered"]) for block in blocks)
        rule_count = sum(bool(block["rule_signal"]) for block in blocks)
        selected_count = sum(bool(block["discovery_selected"]) for block in blocks)
        if not (target_count or rule_count or selected_count):
            continue
        pages = sorted({int(block["page_number"]) for block in blocks})
        reason_counts = Counter(reason for block in blocks for reason in block["selected_because"])
        type_counts = Counter(rule_type for block in blocks for rule_type in block["rule_types"])
        rows.append(
            {
                "scope": scope,
                "pages": pages,
                "block_count": len(blocks),
                "target_block_count": target_count,
                "rule_signal_block_count": rule_count,
                "selected_block_count": selected_count,
                "avg_confidence": round(sum(block["discovery_confidence"] for block in blocks) / len(blocks), 3),
                "reason_counts": dict(reason_counts),
                "rule_type_counts": dict(type_counts),
                "sample_block_ids": [block["block_id"] for block in blocks[:5]],
            }
        )
    rows.sort(key=lambda row: (row["target_block_count"], row["selected_block_count"], row["rule_signal_block_count"]), reverse=True)
    return rows


def lane_for(block: dict[str, Any]) -> str:
    types = set(block["rule_types"])
    if "definition" in types:
        return "context_definition"
    if "permission" in types:
        return "permission"
    if "dimensional_standard" in types:
        return "dimensional_standard"
    if "parking" in types:
        return "parking"
    if "permit_process" in types:
        return "permit_process"
    if "cross_reference" in types:
        return "cross_reference"
    if block["target_hits_discovered"]:
        return "target_context"
    return "related_context"


def build_summary(local_dir: Path, output_dir: Path, annotated: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [block for block in annotated if block["discovery_selected"]]
    target_blocks = [block for block in annotated if block["target_hits_discovered"]]
    discarded_target_blocks = [block for block in target_blocks if not block["discovery_selected"]]
    rule_signal_discarded = [
        block for block in annotated
        if block["rule_signal"] and not block["discovery_selected"] and not block["noise_reasons"]
    ]
    low_confidence = [
        block for block in selected
        if block["discovery_confidence"] < 0.5
    ]
    lane_counts = Counter(lane_for(block) for block in selected)
    tier_counts = Counter(block.get("selection_tier", "unknown") for block in annotated)
    selected_tier_counts = Counter(block.get("selection_tier", "unknown") for block in selected)
    selected_drop_risk_counts = Counter(block.get("drop_risk", "unknown") for block in selected)
    noise_counts = Counter(reason for block in annotated for reason in block["noise_reasons"])
    reason_counts = Counter(reason for block in selected for reason in block["selected_because"])
    type_counts = Counter(rule_type for block in selected for rule_type in block["rule_types"])
    compact_sections = []
    for section in sections[:20]:
        pages = section.get("pages", [])
        compact_sections.append(
            {
                **{key: value for key, value in section.items() if key != "pages"},
                "page_count": len(pages),
                "page_min": min(pages) if pages else None,
                "page_max": max(pages) if pages else None,
                "sample_pages": pages[:8],
            }
        )

    return {
        "input_local_dir": str(local_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "block_count": len(annotated),
        "selected_block_count": len(selected),
        "target_hit_block_count": len(target_blocks),
        "target_hit_discarded_count": len(discarded_target_blocks),
        "rule_signal_discarded_count": len(rule_signal_discarded),
        "low_confidence_selected_count": len(low_confidence),
        "discovered_section_count": len(sections),
        "lane_counts": dict(lane_counts),
        "tier_counts": dict(tier_counts),
        "selected_tier_counts": dict(selected_tier_counts),
        "selected_drop_risk_counts": dict(selected_drop_risk_counts),
        "selected_reason_counts": dict(reason_counts),
        "selected_rule_type_counts": dict(type_counts),
        "noise_counts": dict(noise_counts),
        "top_discovered_sections": compact_sections,
        "audit_files": {
            "annotated_blocks": str((output_dir / "discovered_blocks.jsonl").resolve()),
            "discovered_sections": str((output_dir / "discovered_sections.json").resolve()),
            "target_hit_discarded": str((output_dir / "target_hit_discarded.jsonl").resolve()),
            "rule_signal_discarded": str((output_dir / "rule_signal_discarded.jsonl").resolve()),
            "low_confidence_selected": str((output_dir / "low_confidence_selected.jsonl").resolve()),
            "cross_references": str((output_dir / "cross_references.jsonl").resolve()),
            "noise_report": str((output_dir / "noise_report.json").resolve()),
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    local_dir = args.local_dir.resolve()
    output_dir = args.output_dir.resolve()
    summary = read_json(local_dir / "summary.json")
    config = summary.get("config", {})
    target_terms = args.target_terms or config.get("target_terms") or []
    parent_terms = args.parent_terms or config.get("parent_terms") or []
    if not target_terms:
        raise ValueError("No target terms supplied and none found in local selection summary.")

    blocks = read_jsonl(local_dir / "local_blocks_scored.jsonl")
    windows = read_jsonl(local_dir / "candidate_windows.jsonl")
    annotated = annotate_blocks(blocks, windows, target_terms, parent_terms)
    sections = summarize_sections(annotated)

    selected = [block for block in annotated if block["discovery_selected"]]
    target_discarded = [block for block in annotated if block["target_hits_discovered"] and not block["discovery_selected"]]
    rule_discarded = [
        block for block in annotated
        if block["rule_signal"] and not block["discovery_selected"] and not block["noise_reasons"]
    ]
    low_confidence = [block for block in selected if block["discovery_confidence"] < 0.5]
    cross_refs = [block for block in annotated if block["cross_references"]]
    noise_counts = Counter(reason for block in annotated for reason in block["noise_reasons"])

    write_jsonl(output_dir / "discovered_blocks.jsonl", annotated)
    write_json(output_dir / "discovered_sections.json", sections)
    write_jsonl(output_dir / "target_hit_discarded.jsonl", target_discarded)
    write_jsonl(output_dir / "rule_signal_discarded.jsonl", rule_discarded)
    write_jsonl(output_dir / "low_confidence_selected.jsonl", low_confidence)
    write_jsonl(output_dir / "cross_references.jsonl", cross_refs)
    write_json(output_dir / "noise_report.json", {"noise_counts": dict(noise_counts)})
    discovery_summary = build_summary(local_dir, output_dir, annotated, sections)
    write_json(output_dir / "summary.json", discovery_summary)
    return discovery_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, default=DEFAULT_LOCAL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-terms", nargs="*", default=None)
    parser.add_argument("--parent-terms", nargs="*", default=None)
    return parser.parse_args()


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
