#!/usr/bin/env python3
"""Convert graph/RAG packs into visual-block style inputs for legacy extraction."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_RAG_DIR = ROOT / "outputs" / "calgary" / "04_graph_rag_packs"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "calgary" / "05_rag_visual_blocks"

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


GENERIC_SCOPE_RE = re.compile(
    r"\b(all uses|all buildings|all development|all districts|rules governing all districts|"
    r"general rules|low density residential|floodway|unless otherwise specified)\b",
    re.IGNORECASE,
)
UPPER_LEVEL_APPLIES_RE = re.compile(
    r"\b(all dwelling units?|all residential buildings?|all accessory residential buildings?|"
    r"all residential uses?|all parcels?|all developments?(?!\s+containing)|"
    r"all uses in (?:this|the) district|all uses in (?:this|the) land use district|"
    r"all buildings)\b",
    re.IGNORECASE,
)
CONTAINING_SCOPE_RE = re.compile(
    r"\b(all developments?|all buildings?|all parcels?|developments?|buildings?|parcels?)\s+containing\b",
    re.IGNORECASE,
)
DIMENSIONAL_CONTEXT_RE = re.compile(
    r"\b(development permit|setback|parcel width|building height|parcel coverage|"
    r"landscaped area|floor area|separation|amenity space|building setback|parking stall)\b",
    re.IGNORECASE,
)
STRONG_PARENT_CONTEXT_RE = re.compile(
    r"\b(dwelling|residential|accessory residential building|parcel|building|district|"
    r"land use district|single detached|semi-detached|duplex|rowhouse|townhouse)\b",
    re.IGNORECASE,
)
OTHER_USE_LIST_RE = re.compile(
    r"\b(drinking establishment|drive through|hazardous waste|home occupation|landfill|"
    r"liquor store|night club|pawn shop|payday loan|place of worship|parking lot|"
    r"take out food|seasonal sales|e-scooter|grocery|wine|pawnshop|secondhand|"
    r"sleeping unit|assisted living|swimming pool|hot tub|extensive agriculture|"
    r"natural area|outdoor recreation|multi.?residential development|live work unit|"
    r"power generation|residential care|sign . class)\b",
    re.IGNORECASE,
)
LIST_MARKER_RE = re.compile(r"(?=\([a-z0-9](?:\.[0-9])?\)\s+)", re.IGNORECASE)
LIST_ITEM_LABEL_RE = re.compile(r"^\(([a-z0-9](?:\.[0-9])?)\)\s+", re.IGNORECASE)


def list_item_label(segment: str) -> str:
    match = LIST_ITEM_LABEL_RE.match(segment.strip())
    return match.group(1).lower() if match else ""


def is_letter_list_item(segment: str) -> bool:
    label = list_item_label(segment)
    return bool(label and label[:1].isalpha())


def opens_child_list(segment: str) -> bool:
    return bool(
        re.search(
            r"\b(that|where|as follows)\s*:\s*(?:\d+P\d{4})?\s*$|\bwhere the [^:]+:\s*(?:\d+P\d{4})?\s*$",
            segment.strip(),
            re.IGNORECASE,
        )
    )


def compile_terms_regex(terms: list[str]) -> re.Pattern[str] | None:
    cleaned = [term.strip() for term in terms if term and term.strip()]
    if not cleaned:
        return None
    patterns: list[str] = []
    for term in sorted(cleaned, key=len, reverse=True):
        parts = [part for part in re.split(r"\s+", term) if part]
        patterns.append(r"[\s\-]+".join(re.escape(part) for part in parts))
    return re.compile("|".join(patterns), re.IGNORECASE)


def has_target(text: str, target_re: re.Pattern[str] | None) -> bool:
    return bool(target_re and target_re.search(text))


def is_generic_applicable(text: str, pack: dict[str, Any], target_re: re.Pattern[str] | None = None) -> bool:
    combined = f"{text} {pack.get('scope', '')}"
    if CONTAINING_SCOPE_RE.search(combined) and not has_target(combined, target_re):
        return False
    has_upper_scope = bool(GENERIC_SCOPE_RE.search(combined) or UPPER_LEVEL_APPLIES_RE.search(combined))
    if OTHER_USE_LIST_RE.search(combined) and not has_upper_scope:
        return False
    if has_upper_scope:
        return True
    return bool(DIMENSIONAL_CONTEXT_RE.search(text) and STRONG_PARENT_CONTEXT_RE.search(combined))


def trim_to_target_segments(text: str, target_re: re.Pattern[str] | None) -> tuple[str, bool]:
    if not has_target(text, target_re):
        return text, False
    segments = [segment.strip() for segment in LIST_MARKER_RE.split(text) if segment.strip()]
    if len(segments) <= 1:
        return text, False

    kept: list[str] = []
    preamble = segments[0]
    if not LIST_MARKER_RE.match(preamble) and has_target(preamble, target_re):
        kept.append(preamble)
    for index, segment in enumerate(segments):
        if has_target(segment, target_re):
            if index > 0:
                previous = segments[index - 1]
                if (
                    not has_target(previous, target_re)
                    and (
                        previous.rstrip().endswith(":")
                        or re.search(
                            r"\b(required for|where it is required for|minimum|maximum|must|shall|may|permitted|prohibited)\b",
                            previous,
                            re.IGNORECASE,
                        )
                    )
                ):
                    kept.append(previous)
            kept.append(segment)
            if opens_child_list(segment):
                for child in segments[index + 1:]:
                    if has_target(child, target_re):
                        break
                    if re.search(r"\bdeleted\b", child, re.IGNORECASE):
                        break
                    if not is_letter_list_item(child):
                        break
                    kept.append(child)
    trimmed = " ".join(dict.fromkeys(kept)).strip()
    if trimmed and len(trimmed) < len(text):
        return trimmed, True
    return text, False


def adapt_evidence_text(
    block: dict[str, Any],
    pack: dict[str, Any],
    target_re: re.Pattern[str] | None,
    parent_re: re.Pattern[str] | None,
    target_filter: bool,
    include_broad_context: bool,
    pack_has_target: bool,
) -> tuple[str, str]:
    text = str(block.get("text", ""))
    if not target_filter:
        return text, "kept_unfiltered"
    if has_target(text, target_re):
        trimmed, did_trim = trim_to_target_segments(text, target_re)
        return trimmed, "trimmed_to_target" if did_trim else "kept_target_hit"
    reasons = set(block.get("selected_because", []))
    if (
        pack_has_target
        and reasons & {"list_continuation_closure", "list_sibling_closure", "same_section_as_target"}
        and not OTHER_USE_LIST_RE.search(text)
    ):
        return text, "kept_inherited_target_context"
    if is_generic_applicable(text, pack, target_re):
        return text, "kept_generic_applicable"
    if OTHER_USE_LIST_RE.search(text):
        return "", "dropped_other_use_list"
    if pack.get("applicability") == "use_permission":
        return "", "dropped_use_permission_without_target"
    if include_broad_context:
        return text, "kept_broad_context"
    return "", "dropped_broad_context"


def pack_to_text_blocks(
    pack: dict[str, Any],
    lane: str,
    pseudo_page: int,
    target_re: re.Pattern[str] | None = None,
    parent_re: re.Pattern[str] | None = None,
    target_filter: bool = True,
    include_broad_context: bool = False,
) -> tuple[list[dict[str, Any]], Counter]:
    blocks: list[dict[str, Any]] = []
    actions: Counter = Counter()
    pack_has_target = any(has_target(str(item.get("text", "")), target_re) for item in pack.get("evidence_blocks", []))
    section_path = [
        "pipeline9_graph_rag",
        lane,
        pack.get("applicability", ""),
        pack.get("scope", ""),
        f"original_page_{int(pack.get('page_number') or 0):04d}",
        pack.get("pack_id", ""),
    ]
    for reading_order, block in enumerate(pack.get("evidence_blocks", []), start=1):
        adapted_text, action = adapt_evidence_text(
            block,
            pack,
            target_re,
            parent_re,
            target_filter,
            include_broad_context,
            pack_has_target,
        )
        actions[action] += 1
        if not adapted_text.strip():
            continue
        source_id = safe_id(block.get("source_id"))
        pack_id = safe_id(pack.get("pack_id"))
        duplicate_source_ids = block.get("duplicate_source_ids") or [block.get("source_id", "")]
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
                    f"target_filter_action={action}; "
                    f"duplicate_source_ids={','.join(str(item) for item in duplicate_source_ids)}; "
                    f"original_page={pack.get('page_number')}"
                ),
                "text": adapted_text,
                "continues_from_previous_page": False,
                "continues_on_next_page": False,
                "rag_pack_id": pack.get("pack_id", ""),
                "rag_lane": lane,
                "rag_applicability": pack.get("applicability", ""),
                "original_source_id": block.get("source_id", ""),
                "duplicate_source_ids": duplicate_source_ids,
                "duplicate_cluster_size": block.get("duplicate_cluster_size", len(duplicate_source_ids)),
                "original_page_number": pack.get("page_number"),
                "target_filter_action": action,
            }
        )
    return blocks, actions


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
    parser.add_argument("--target-terms", nargs="*", default=[])
    parser.add_argument("--parent-terms", nargs="*", default=[])
    parser.add_argument(
        "--source-visual-blocks-dir",
        type=Path,
        default=None,
        help="Optional visual-blocks directory whose table_regions and table_images should be inherited.",
    )
    parser.add_argument("--disable-target-filter", action="store_true")
    parser.add_argument("--include-broad-context", action="store_true")
    return parser.parse_args()


def inherit_table_regions(
    source_visual_dir: Path | None,
    output_dir: Path,
    selected_original_pages: set[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not source_visual_dir:
        return [], {"status": "not_configured", "table_region_count": 0}
    source_visual_dir = source_visual_dir.resolve()
    source_table_path = source_visual_dir / "table_regions.jsonl"
    if not source_table_path.exists():
        return [], {
            "status": "missing_source_table_regions",
            "source_visual_blocks_dir": str(source_visual_dir),
            "table_region_count": 0,
        }

    source_regions = read_jsonl(source_table_path)
    inherited: list[dict[str, Any]] = []
    copied_images = 0
    for region in source_regions:
        page_number = int(region.get("page_number") or 0)
        if selected_original_pages and page_number not in selected_original_pages:
            continue
        copied = dict(region)
        copied["inherited_from_visual_blocks_dir"] = str(source_visual_dir)
        copied["inherited_by_pipeline10_rag_adapter"] = True
        image_rel = str(copied.get("image_path", ""))
        if image_rel:
            src_image = source_visual_dir / image_rel
            dst_image = output_dir / image_rel
            if src_image.exists():
                dst_image.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_image, dst_image)
                copied_images += 1
        source_page_rel = str(copied.get("source_page_image", ""))
        if source_page_rel:
            src_page = source_visual_dir / source_page_rel
            dst_page = output_dir / source_page_rel
            if src_page.exists():
                dst_page.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_page, dst_page)
        inherited.append(copied)

    return inherited, {
        "status": "inherited",
        "source_visual_blocks_dir": str(source_visual_dir),
        "source_table_region_count": len(source_regions),
        "table_region_count": len(inherited),
        "copied_table_image_count": copied_images,
        "selected_original_page_count": len(selected_original_pages),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    text_path = output_dir / "text_blocks.jsonl"
    table_path = output_dir / "table_regions.jsonl"
    manifest_path = output_dir / "rag_adapter_manifest.json"
    if text_path.exists() and not args.overwrite:
        raise FileExistsError(f"{text_path} exists; use --overwrite to regenerate.")

    text_blocks: list[dict[str, Any]] = []
    pack_rows: list[dict[str, Any]] = []
    target_re = compile_terms_regex(list(getattr(args, "target_terms", []) or []))
    parent_re = compile_terms_regex(list(getattr(args, "parent_terms", []) or []))
    target_filter = not bool(getattr(args, "disable_target_filter", False))
    include_broad_context = bool(getattr(args, "include_broad_context", False))
    filter_actions: Counter = Counter()
    pseudo_page = 1
    selected_original_pages: set[int] = set()
    for lane_file in args.lanes:
        lane_path = (args.rag_dir / lane_file).resolve()
        lane_name = Path(lane_file).stem
        packs = read_jsonl(lane_path)
        for pack in packs:
            if pack.get("page_number"):
                selected_original_pages.add(int(pack.get("page_number")))
            blocks, actions = pack_to_text_blocks(
                pack,
                lane_name,
                pseudo_page,
                target_re=target_re,
                parent_re=parent_re,
                target_filter=target_filter,
                include_broad_context=include_broad_context,
            )
            filter_actions.update(actions)
            if not blocks:
                continue
            text_blocks.extend(blocks)
            pack_rows.append(
                {
                    "pseudo_page_number": pseudo_page,
                    "lane": lane_name,
                    "pack_id": pack.get("pack_id", ""),
                    "applicability": pack.get("applicability", ""),
                    "original_page_number": pack.get("page_number"),
                    "block_count": len(blocks),
                    "target_filter_actions": dict(actions),
                    "source_block_count": pack.get("source_block_count", len(pack.get("block_ids", []))),
                    "duplicate_cluster_count": pack.get("duplicate_cluster_count", 0),
                    "char_count": sum(len(block.get("text", "")) for block in blocks),
                }
            )
            pseudo_page += 1

    write_jsonl(text_path, text_blocks)
    inherited_tables, table_inheritance = inherit_table_regions(
        getattr(args, "source_visual_blocks_dir", None),
        output_dir,
        selected_original_pages,
    )
    write_jsonl(table_path, inherited_tables)
    summary = {
        "rag_dir": str(args.rag_dir.resolve()),
        "output_dir": str(output_dir),
        "lane_files": args.lanes,
        "target_filter_enabled": target_filter,
        "include_broad_context": include_broad_context,
        "target_terms": list(getattr(args, "target_terms", []) or []),
        "parent_terms": list(getattr(args, "parent_terms", []) or []),
        "target_filter_actions": dict(filter_actions),
        "source_visual_blocks_dir": (
            str(getattr(args, "source_visual_blocks_dir", None).resolve())
            if getattr(args, "source_visual_blocks_dir", None)
            else ""
        ),
        "table_inheritance": table_inheritance,
        "table_region_count": len(inherited_tables),
        "pack_count": len(pack_rows),
        "text_block_count": len(text_blocks),
        "unique_original_block_count": len({block["original_source_id"] for block in text_blocks}),
        "unique_source_block_count_including_duplicates": len(
            {
                source_id
                for block in text_blocks
                for source_id in block.get("duplicate_source_ids", [block["original_source_id"]])
            }
        ),
        "duplicate_cluster_count": sum(pack.get("duplicate_cluster_count", 0) for pack in pack_rows),
        "pseudo_page_count": len(pack_rows),
        "packs": pack_rows,
        "legacy_extractor_command": (
            "python code\\legacy\\prototype_pipeline_9\\run_legacy_extraction_on_rag.py "
            f"--visual-blocks-dir {output_dir} --output-dir {output_dir.parent / '06_rule_extraction'} "
            "--model gemini-3.5-flash --text-model gemini-3.5-flash --max-workers 1 "
            + (
                "--target-terms " + " ".join(f'"{term}"' for term in (getattr(args, "target_terms", []) or []))
                if getattr(args, "target_terms", None)
                else ""
            )
        ),
    }
    write_json(manifest_path, summary)
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
