#!/usr/bin/env python3
"""Build generic graph/RAG packs from auto-discovery output.

This builder is city-neutral: it consumes compressed discovery blocks
and emits the same lane files expected by the RAG-to-legacy adapter.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from auto_discovery import lane_for, read_jsonl, write_json, write_jsonl


ROOT = Path(__file__).resolve().parent
DEFAULT_DISCOVERY_DIR = ROOT / "outputs" / "burnaby" / "02_auto_discovery"
DEFAULT_BLOCKS_FILE = ROOT / "outputs" / "burnaby" / "03_semantic_compression" / "compressed_blocks.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "burnaby" / "04_graph_rag_packs"

LANE_TO_PACK_FILE = {
    "core_rule": "extract_now_core_packs.jsonl",
    "use_permission": "extract_separately_use_permission_packs.jsonl",
    "district_dimensional_override": "district_dimensional_overrides_packs.jsonl",
    "universal_applicable_rule": "universal_applicable_rules_packs.jsonl",
    "context_only": "context_only_or_later_packs.jsonl",
}

PACK_SELECTION_REASONS = {
    "target_term_hit",
    "candidate_window",
    "same_page_as_target",
    "same_section_as_target",
    "list_continuation_closure",
}


def pack_applicability(block: dict[str, Any]) -> str:
    lane = lane_for(block)
    if lane == "permission":
        return "use_permission"
    if lane == "dimensional_standard":
        return "district_dimensional_override"
    if lane in {"parking", "permit_process", "cross_reference"}:
        return "universal_applicable_rule"
    if lane in {"context_definition"}:
        return "context_only"
    return "core_rule"


PACK_ALWAYS_KEEP_REASONS = {
    "target_term_hit",
    "candidate_window",
    "list_continuation_closure",
}

ORDINAL_RE = re.compile(r"^\s*\(?[a-z0-9ivxlcdm]{1,5}\)?[\).\s-]+", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
SPACE_RE = re.compile(r"\s+")
LIST_ITEM_RE = re.compile(r"^\s*\([a-z0-9ivxlcdm]{1,5}\)\s+", re.IGNORECASE)


def normalized_duplicate_key(block: dict[str, Any]) -> str:
    text = str(block.get("text_compact") or block.get("text") or "").lower()
    text = ORDINAL_RE.sub("", text)
    text = NUMBER_RE.sub("#", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text[:500]


def merge_duplicate_evidence_blocks(group: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for block in group:
        key = (lane_for(block), normalized_duplicate_key(block))
        by_key[key].append(block)

    representatives: list[dict[str, Any]] = []
    duplicate_clusters: list[dict[str, Any]] = []
    for (_, key), blocks in by_key.items():
        blocks.sort(key=lambda row: int(row.get("page_block_index", row.get("reading_order", 0))))
        representative = blocks[0]
        duplicate_ids = [block["block_id"] for block in blocks]
        representatives.append(
            {
                **representative,
                "duplicate_source_ids": duplicate_ids,
                "duplicate_cluster_size": len(duplicate_ids),
            }
        )
        if len(blocks) > 1:
            duplicate_clusters.append(
                {
                    "representative_source_id": representative["block_id"],
                    "duplicate_source_ids": duplicate_ids,
                    "duplicate_cluster_size": len(duplicate_ids),
                    "role": lane_for(representative),
                    "normalized_key": key,
                }
            )
    representatives.sort(key=lambda row: int(row.get("page_block_index", row.get("reading_order", 0))))
    return representatives, duplicate_clusters


def should_pack_block(block: dict[str, Any], pack_threshold: float = 0.28) -> bool:
    if block.get("noise_reasons"):
        return False
    reasons = set(block.get("selected_because", []))
    if reasons & PACK_ALWAYS_KEEP_REASONS:
        return True
    if "list_sibling_closure" in reasons and "same_section_as_target" in reasons:
        return True
    if "compression_selected" in block:
        if not block.get("compression_selected"):
            return False
        if not (reasons & PACK_SELECTION_REASONS):
            return False
        return float(block.get("compression_score") or 0.0) >= pack_threshold
    if not block.get("discovery_selected"):
        return False
    return bool(reasons & PACK_SELECTION_REASONS)


def effective_pack_applicabilities(blocks: list[dict[str, Any]]) -> dict[str, str]:
    """Assign list children to their nearest rule-intro parent's lane.

    Auto-discovery can correctly keep list items like ``(a) 186 m2`` while the
    list intro lives in a dimensional lane. If we group strictly by each item's
    own weak local signals, parent and children land in separate extraction
    batches and the LLM sees orphaned list items. This pass keeps the logic
    city-neutral by inheriting only within the same page/scope stream.
    """
    result: dict[str, str] = {}
    by_scope: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        page = int(block.get("page_number") or 0)
        scope = str(block.get("scope") or f"page_{page:04d}")
        by_scope[(page, scope)].append(block)

    inheritable_lanes = {"district_dimensional_override", "use_permission", "universal_applicable_rule"}
    for (_, _), scoped_blocks in by_scope.items():
        scoped_blocks.sort(key=lambda row: int(row.get("page_block_index", row.get("reading_order", 0))))
        current: str | None = None
        for block in scoped_blocks:
            own = pack_applicability(block)
            text = str(block.get("text_compact") or block.get("text") or "")
            is_list_item = bool(LIST_ITEM_RE.match(text))
            if is_list_item and current in inheritable_lanes:
                result[block["block_id"]] = current
                continue

            result[block["block_id"]] = own
            if block.get("target_hits_discovered") or block.get("rule_signal") or block.get("rule_types"):
                current = own
    return result


def build_packs(blocks: list[dict[str, Any]], city: str, pack_threshold: float = 0.28) -> list[dict[str, Any]]:
    selected = [
        block for block in blocks
        if should_pack_block(block, pack_threshold=pack_threshold)
    ]
    effective_applicability = effective_pack_applicabilities(selected)
    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for block in selected:
        page = int(block.get("page_number") or 0)
        scope = str(block.get("scope") or f"page_{page:04d}")
        applicability = effective_applicability.get(block["block_id"], pack_applicability(block))
        grouped[(page, scope, applicability)].append(block)

    packs: list[dict[str, Any]] = []
    for index, ((page, scope, applicability), group) in enumerate(sorted(grouped.items()), start=1):
        group.sort(key=lambda row: int(row.get("page_block_index", row.get("reading_order", 0))))
        evidence_group, duplicate_clusters = merge_duplicate_evidence_blocks(group)
        packs.append(
            {
                "pack_id": f"{city}_generic_graph_pack_{index:03d}",
                "page_number": page,
                "scope": scope,
                "applicability": applicability,
                "applicability_counts": dict(
                    Counter(effective_applicability.get(block["block_id"], pack_applicability(block)) for block in group)
                ),
                "roles": dict(Counter(lane_for(block) for block in group)),
                "block_ids": [block["block_id"] for block in group],
                "evidence_block_count": len(evidence_group),
                "source_block_count": len(group),
                "duplicate_cluster_count": len(duplicate_clusters),
                "duplicate_clusters": duplicate_clusters,
                "char_count": sum(len(block.get("text_compact") or block.get("text", "")) for block in evidence_group),
                "evidence_blocks": [
                    {
                        "source_id": block["block_id"],
                        "duplicate_source_ids": block.get("duplicate_source_ids", [block["block_id"]]),
                        "duplicate_cluster_size": block.get("duplicate_cluster_size", 1),
                        "role": lane_for(block),
                        "applicability": applicability,
                        "selected_because": block.get("selected_because", []),
                        "selection_tier": block.get("selection_tier"),
                        "must_keep": block.get("must_keep"),
                        "drop_risk": block.get("drop_risk"),
                        "discovery_confidence": block.get("discovery_confidence"),
                        "semantic_score": block.get("semantic_score"),
                        "structural_score": block.get("structural_score"),
                        "compression_score": block.get("compression_score"),
                        "rule_types": block.get("rule_types", []),
                        "text": block.get("text", ""),
                    }
                    for block in evidence_group
                ],
            }
        )
    return packs


def run(args: argparse.Namespace) -> dict[str, Any]:
    discovery_dir = args.discovery_dir.resolve()
    output_dir = args.output_dir.resolve()
    blocks_file = args.blocks_file.resolve() if args.blocks_file else discovery_dir / "discovered_blocks.jsonl"
    blocks = read_jsonl(blocks_file)
    packs = build_packs(blocks, args.city, pack_threshold=args.pack_threshold)
    pack_counts = Counter(pack["applicability"] for pack in packs)

    write_jsonl(output_dir / "retrieval_packs.jsonl", packs)
    for applicability, filename in LANE_TO_PACK_FILE.items():
        write_jsonl(output_dir / filename, [pack for pack in packs if pack["applicability"] == applicability])

    selected_block_ids = {
        block_id
        for pack in packs
        for block_id in pack.get("block_ids", [])
    }
    duplicate_clusters = [
        {**cluster, "pack_id": pack["pack_id"], "scope": pack["scope"], "page_number": pack["page_number"]}
        for pack in packs
        for cluster in pack.get("duplicate_clusters", [])
    ]
    write_jsonl(output_dir / "duplicate_clusters.jsonl", duplicate_clusters)
    summary = {
        "case": f"{args.city}_pipeline9_generic_discovery_packs",
        "input_discovery_dir": str(discovery_dir),
        "input_blocks_file": str(blocks_file),
        "output_dir": str(output_dir),
        "selected_block_count": len(selected_block_ids),
        "context_pack_count": len(packs),
        "selected_char_count": sum(pack["char_count"] for pack in packs),
        "evidence_block_count": sum(pack.get("evidence_block_count", len(pack.get("evidence_blocks", []))) for pack in packs),
        "duplicate_cluster_count": len(duplicate_clusters),
        "duplicate_source_block_count": sum(
            max(0, int(cluster.get("duplicate_cluster_size", 1)) - 1)
            for cluster in duplicate_clusters
        ),
        "pack_threshold": args.pack_threshold,
        "pack_applicability": dict(pack_counts),
        "recommended_extraction_plan": {
            "extract_now": {
                "applicability": ["core_rule"],
                "pack_count": pack_counts.get("core_rule", 0),
                "estimated_chars": sum(pack["char_count"] for pack in packs if pack["applicability"] == "core_rule"),
            },
            "extract_separately": {
                "applicability": ["use_permission"],
                "pack_count": pack_counts.get("use_permission", 0),
                "estimated_chars": sum(pack["char_count"] for pack in packs if pack["applicability"] == "use_permission"),
            },
            "district_specific_later": {
                "applicability": ["district_dimensional_override"],
                "pack_count": pack_counts.get("district_dimensional_override", 0),
                "estimated_chars": sum(
                    pack["char_count"] for pack in packs if pack["applicability"] == "district_dimensional_override"
                ),
            },
            "universal_applicable": {
                "applicability": ["universal_applicable_rule"],
                "pack_count": pack_counts.get("universal_applicable_rule", 0),
                "estimated_chars": sum(
                    pack["char_count"] for pack in packs if pack["applicability"] == "universal_applicable_rule"
                ),
            },
            "context_only_or_later": {
                "applicability": ["context_only"],
                "pack_count": pack_counts.get("context_only", 0),
            },
        },
    }
    write_json(output_dir / "experiment_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="burnaby")
    parser.add_argument("--discovery-dir", type=Path, default=DEFAULT_DISCOVERY_DIR)
    parser.add_argument("--blocks-file", type=Path, default=DEFAULT_BLOCKS_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pack-threshold", type=float, default=0.28)
    return parser.parse_args()


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
