#!/usr/bin/env python3
"""Convert graph/RAG packs into visual-block style inputs for legacy extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_RAG_DIR = ROOT / "experiments" / "calgary_graph_rag"
DEFAULT_OUTPUT_DIR = DEFAULT_RAG_DIR / "legacy_visual_blocks_adapter"

DEFAULT_LANES = [
    "extract_now_core_packs.jsonl",
    "extract_separately_use_permission_packs.jsonl",
    "district_dimensional_overrides_packs.jsonl",
    "universal_applicable_rules_packs.jsonl",
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def safe_id(value: Any) -> str:
    return str(value or "").replace("/", "_").replace("\\", "_").replace(" ", "_")


def pack_to_text_blocks(pack: dict[str, Any], lane: str, pseudo_page: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    section_path = [
        "calgary_graph_rag",
        lane,
        pack.get("applicability", ""),
        pack.get("scope", ""),
        f"original_page_{int(pack.get('page_number') or 0):04d}",
        pack.get("pack_id", ""),
    ]
    for reading_order, block in enumerate(pack.get("evidence_blocks", []), start=1):
        source_id = safe_id(block.get("source_id"))
        pack_id = safe_id(pack.get("pack_id"))
        blocks.append(
            {
                "block_id": f"{pack_id}__{source_id}",
                "page_number": pseudo_page,
                "reading_order": reading_order,
                "block_type": "heading" if block.get("role") == "scope_heading" else "paragraph",
                "section_path": section_path,
                "parent_context": (
                    f"RAG lane={lane}; applicability={pack.get('applicability', '')}; "
                    f"scope={pack.get('scope', '')}; original_source_id={block.get('source_id', '')}; "
                    f"original_page={pack.get('page_number')}"
                ),
                "text": block.get("text", ""),
                "continues_from_previous_page": False,
                "continues_on_next_page": False,
                "rag_pack_id": pack.get("pack_id", ""),
                "rag_lane": lane,
                "rag_applicability": pack.get("applicability", ""),
                "original_source_id": block.get("source_id", ""),
                "original_page_number": pack.get("page_number"),
            }
        )
    return blocks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rag-dir", type=Path, default=DEFAULT_RAG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--lanes",
        nargs="+",
        default=DEFAULT_LANES,
        help="Pack JSONL files under --rag-dir to expose to the legacy extractor.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    text_path = output_dir / "text_blocks.jsonl"
    table_path = output_dir / "table_regions.jsonl"
    manifest_path = output_dir / "rag_adapter_manifest.json"
    if text_path.exists() and not args.overwrite:
        raise FileExistsError(f"{text_path} exists; use --overwrite to regenerate.")

    text_blocks: list[dict[str, Any]] = []
    pack_rows: list[dict[str, Any]] = []
    pseudo_page = 1
    for lane_file in args.lanes:
        lane_path = (args.rag_dir / lane_file).resolve()
        lane_name = Path(lane_file).stem
        packs = read_jsonl(lane_path)
        for pack in packs:
            blocks = pack_to_text_blocks(pack, lane_name, pseudo_page)
            text_blocks.extend(blocks)
            pack_rows.append(
                {
                    "pseudo_page_number": pseudo_page,
                    "lane": lane_name,
                    "pack_id": pack.get("pack_id", ""),
                    "applicability": pack.get("applicability", ""),
                    "original_page_number": pack.get("page_number"),
                    "block_count": len(blocks),
                    "char_count": pack.get("char_count", 0),
                }
            )
            pseudo_page += 1

    write_jsonl(text_path, text_blocks)
    write_jsonl(table_path, [])
    summary = {
        "rag_dir": str(args.rag_dir.resolve()),
        "output_dir": str(output_dir),
        "lane_files": args.lanes,
        "pack_count": len(pack_rows),
        "text_block_count": len(text_blocks),
        "unique_original_block_count": len({block["original_source_id"] for block in text_blocks}),
        "pseudo_page_count": len(pack_rows),
        "packs": pack_rows,
        "legacy_extractor_command": (
            "python code\\prototype_pipeline_8\\run_legacy_extraction_on_rag.py "
            f"--visual-blocks-dir {output_dir} --output-dir {output_dir.parent / 'legacy_rule_extraction'} "
            "--model gemini-3.5-flash --text-model gemini-3.5-flash --max-workers 1"
        ),
    }
    write_json(manifest_path, summary)
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
