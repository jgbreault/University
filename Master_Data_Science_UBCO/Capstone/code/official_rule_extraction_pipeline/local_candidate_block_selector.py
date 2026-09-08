#!/usr/bin/env python3
"""Locally recall zoning-bylaw text windows before using an API."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import fitz


PIPELINE_DIR = Path(__file__).resolve().parent
PDF_DIR = PIPELINE_DIR / "pdfs"

CITY_CONFIGS = {
    "burnaby": {
        "pdf": "burnaby/R1Small-Scale-Multi-Unit-Housing-District.pdf",
        "city": "Burnaby",
        "zone": "R1",
        "target_description": "R1 small-scale multi-unit housing development regulations",
        "target_terms": ["rear principal building", "front principal building", "small-scale multi-unit"],
        "parent_terms": ["principal building", "dwelling unit", "lot", "yard", "parking", "separation"],
    },
    "vancouver": {
        "pdf": "vancouver/zoning-by-law-section-11.pdf",
        "city": "Vancouver",
        "zone": "RS",
        "target_description": "laneway-house regulations and directly applicable parent regulations",
        "target_terms": ["laneway house", "laneway home", "laneway dwelling", "laneway"],
        "parent_terms": ["site", "building", "yard", "accessory building", "parking", "floor area"],
    },
    "surrey": {
        "pdf": "surrey/BYL_Zoning_12000.pdf",
        "city": "Surrey",
        "zone": "R1",
        "target_description": "Surrey R1 coach-house and garden-suite regulations and directly applicable shared regulations",
        "target_terms": ["coach house", "garden suite"],
        "parent_terms": ["lot", "building", "yard", "accessory", "parking", "floor area"],
        "shared_chapter_last_page": 99,
        "target_zone_page_pattern": r"\bR1\b",
    },
    "calgary": {
        "pdf": "calgary/calgary-land-use-bylaw-1p2007.pdf",
        "city": "Calgary",
        "zone": "Backyard/Secondary Suite",
        "target_description": "backyard suite and secondary suite regulations and directly applicable small-scale residential district rules",
        # Backyard Suite is Calgary's analog to Vancouver's laneway house / Surrey's
        # coach house (a detached rear-yard dwelling); secondary suite is the in-house
        # variant. Kept tight so the score concentrates on the target feature.
        "target_terms": ["backyard suite", "secondary suite"],
        # Calgary uses "parcel" (not "lot") and "building/use" framing throughout.
        "parent_terms": ["parcel", "building", "dwelling", "yard", "parking", "use"],
        # First pass deliberately scans the whole bylaw (no target_zone_page_pattern):
        # backyard/secondary-suite rules are scattered across several residential
        # districts, so we want to see real coverage before constraining to a zone.
    },
}

UNIVERSAL_TERMS = [
    "development regulations",
    "lot coverage",
    "impervious",
    "height",
    "storey",
    "setback",
    "yard",
    "separation",
    "parking",
    "access",
    "floor area",
    "dwelling unit",
    "permitted",
    "minimum",
    "maximum",
    "lane",
    "driveway",
]


# --- Block-level noise filter -------------------------------------------------
# A candidate window is "noise" (a bare use-list / table-of-contents mention of the
# target term, with no actual rule) when none of the target-term occurrences sit in
# a regulatory clause and the window carries no measurement. Such windows are
# dropped before window refinement so they never cost an API call. The filter is
# deliberately high-precision: when in doubt it KEEPS (a false keep only costs one
# refinement call; a false drop would lose a real rule), so it never removes a
# window that carries a measurement or a substantive clause about the target.
_MEASURE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:m\b|metre|metres|meters|m2|m²|%|storey|storeys|stories|unit|units)", re.IGNORECASE
)
_SUBSTANTIVE_RE = re.compile(
    r"(is |are |may |must |shall |for a|of a|on a|in a|of the|on the|in the|with |accommodat|permitt|"
    r"relax|approv|exceed|contain|provid|requir|maximum|minimum|metre)", re.IGNORECASE
)
# Bylaw amendment codes (e.g. "12P2010") are interleaved into wrapped clause text by
# the PDF text layer; strip them so a target phrase split across a line break still
# matches as one phrase.
_AMENDMENT_CODE_RE = re.compile(r"\b\d+P\d{4}\b")


def _target_phrase_re(term: str) -> re.Pattern:
    # Allow any non-word run (line wraps, stray punctuation) between phrase words.
    return re.compile(r"\W+".join(re.escape(part) for part in term.split()), re.IGNORECASE)


def window_has_rule_signal(window: dict[str, Any], target_terms: list[str]) -> bool:
    """True if the window looks like it carries a real rule about the target (keep);
    False if it is only a bare use-list / index mention (drop)."""
    raw = " ".join(row["text"] for row in window.get("numbered_lines", [])).replace("\n", " ")
    text = re.sub(r"[ \t]+", " ", _AMENDMENT_CODE_RE.sub(" ", raw))
    if _MEASURE_RE.search(text):
        return True
    matches = [m for term in target_terms for m in _target_phrase_re(term).finditer(text)]
    if not matches:  # term only present in neighbouring context -> keep conservatively
        return True
    return any(_SUBSTANTIVE_RE.search(text[max(0, m.start() - 70): m.end() + 90]) for m in matches)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city", choices=sorted(CITY_CONFIGS))
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--pdf", type=Path, help="Override the configured source PDF.")
    parser.add_argument("--context-lines", type=int, default=4)
    parser.add_argument("--neighbor-blocks", type=int, default=2)
    parser.add_argument("--visual-page-radius", type=int, default=1)
    parser.add_argument("--max-windows", type=int, default=100)
    parser.add_argument("--prune-windows", action="store_true",
                        help="Drop bare use-list / index windows (no rule signal) before window refinement.")
    parser.add_argument("--include-other-zones", action="store_true", help="Disable Surrey's default R1 scope filter.")
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def term_hits(text: str, terms: list[str]) -> list[str]:
    normalized = normalize(text)
    return sorted({term for term in terms if normalize(term) in normalized})


def split_page_into_blocks(page: fitz.Page, page_number: int) -> tuple[list[str], list[dict[str, Any]]]:
    raw_lines = page.get_text("text", sort=True).splitlines()
    lines = [line.strip() for line in raw_lines]
    blocks: list[dict[str, Any]] = []
    block_start: int | None = None
    block_lines: list[str] = []

    def flush() -> None:
        nonlocal block_start, block_lines
        if block_start is None or not block_lines:
            block_start = None
            block_lines = []
            return
        blocks.append({
            "page_number": page_number,
            "line_start": block_start + 1,
            "line_end": block_start + len(block_lines),
            "text": "\n".join(block_lines),
        })
        block_start = None
        block_lines = []

    for index, line in enumerate(lines):
        if not line:
            flush()
            continue
        if block_start is None:
            block_start = index
        block_lines.append(line)
        if len(block_lines) >= 12:
            flush()
    flush()
    for index, block in enumerate(blocks, start=1):
        block["block_id"] = f"page_{page_number:04d}__local_{index:03d}"
        block["page_block_index"] = index
    return lines, blocks


def score_block(block: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    target_hits = term_hits(block["text"], config["target_terms"])
    parent_hits = term_hits(block["text"], config["parent_terms"])
    universal_hits = term_hits(block["text"], UNIVERSAL_TERMS)
    return {
        **block,
        "selection_score": 10 * len(target_hits) + 3 * len(parent_hits) + len(universal_hits),
        "target_hits": target_hits,
        "parent_hits": parent_hits,
        "universal_hits": universal_hits,
        "is_target_anchor": bool(target_hits),
    }


def page_is_scope_eligible(
    page_number: int,
    lines: list[str],
    config: dict[str, Any],
    include_other_zones: bool,
) -> bool:
    if include_other_zones or "target_zone_page_pattern" not in config:
        return True
    if page_number <= int(config.get("shared_chapter_last_page", 0)):
        return True
    page_heading = " ".join(line for line in lines[:4] if line)
    return bool(re.search(config["target_zone_page_pattern"], page_heading, flags=re.IGNORECASE))


def merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def build_candidate_windows(
    *,
    page_lines: dict[int, list[str]],
    scored_blocks: list[dict[str, Any]],
    context_lines: int,
    neighbor_blocks: int,
    max_windows: int,
) -> list[dict[str, Any]]:
    by_page: dict[int, list[dict[str, Any]]] = {}
    for block in scored_blocks:
        by_page.setdefault(block["page_number"], []).append(block)
    windows: list[dict[str, Any]] = []
    for page_number, blocks in sorted(by_page.items()):
        anchors = [index for index, block in enumerate(blocks) if block["is_target_anchor"]]
        spans = []
        for index in anchors:
            first = max(0, index - neighbor_blocks)
            last = min(len(blocks) - 1, index + neighbor_blocks)
            spans.append((blocks[first]["line_start"], blocks[last]["line_end"]))
        for start, end in merge_spans(spans):
            lines = page_lines[page_number]
            context_start = max(1, start - context_lines)
            context_end = min(len(lines), end + context_lines)
            numbered_lines = [
                {"line_number": number, "text": lines[number - 1]}
                for number in range(context_start, context_end + 1)
                if lines[number - 1]
            ]
            relevant_blocks = [
                block for block in blocks
                if block["line_end"] >= start and block["line_start"] <= end
            ]
            windows.append({
                "window_id": f"page_{page_number:04d}__window_{len(windows) + 1:03d}",
                "page_number": page_number,
                "candidate_line_start": start,
                "candidate_line_end": end,
                "context_line_start": context_start,
                "context_line_end": context_end,
                "local_block_ids": [block["block_id"] for block in relevant_blocks],
                "selection_score": sum(block["selection_score"] for block in relevant_blocks),
                "target_hits": sorted({hit for block in relevant_blocks for hit in block["target_hits"]}),
                "parent_hits": sorted({hit for block in relevant_blocks for hit in block["parent_hits"]}),
                "universal_hits": sorted({hit for block in relevant_blocks for hit in block["universal_hits"]}),
                "numbered_lines": numbered_lines,
                "text": "\n".join(f"L{row['line_number']}: {row['text']}" for row in numbered_lines),
            })
    return sorted(windows, key=lambda row: (-row["selection_score"], row["page_number"]))[:max_windows]


def expanded_visual_pages(anchor_pages: list[int], page_count: int, radius: int) -> list[int]:
    return sorted({
        page
        for anchor in anchor_pages
        for page in range(max(1, anchor - radius), min(page_count, anchor + radius) + 1)
    })


def process_local_selection(args: argparse.Namespace) -> dict[str, Any]:
    config = CITY_CONFIGS[args.city]
    pdf_path = (args.pdf or (PDF_DIR / config["pdf"])).resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(pdf_path)
    page_lines: dict[int, list[str]] = {}
    scored_blocks: list[dict[str, Any]] = []
    for page_number, page in enumerate(document, start=1):
        lines, blocks = split_page_into_blocks(page, page_number)
        page_lines[page_number] = lines
        scope_eligible = page_is_scope_eligible(
            page_number,
            lines,
            config,
            getattr(args, "include_other_zones", False),
        )
        for block in blocks:
            scored = score_block(block, config)
            scored["scope_eligible"] = scope_eligible
            scored["is_target_anchor"] = scored["is_target_anchor"] and scope_eligible
            scored_blocks.append(scored)
    windows = build_candidate_windows(
        page_lines=page_lines,
        scored_blocks=scored_blocks,
        context_lines=args.context_lines,
        neighbor_blocks=args.neighbor_blocks,
        max_windows=args.max_windows,
    )
    prune_windows = getattr(args, "prune_windows", False)
    pruned_window_count = 0
    if prune_windows:
        target_terms = config["target_terms"]
        kept = [w for w in windows if window_has_rule_signal(w, target_terms)]
        pruned_window_count = len(windows) - len(kept)
        windows = kept
        # Base the visual-page set on the surviving windows so pruning also trims the
        # pages sent downstream (a page kept only by a noise window is dropped too).
        anchor_pages = sorted({window["page_number"] for window in windows})
    else:
        anchor_pages = sorted({block["page_number"] for block in scored_blocks if block["is_target_anchor"]})
    visual_pages = expanded_visual_pages(anchor_pages, document.page_count, args.visual_page_radius)
    summary = {
        "city": args.city,
        "source_pdf": str(pdf_path),
        "pdf_page_count": document.page_count,
        "local_block_count": len(scored_blocks),
        "target_anchor_block_count": sum(block["is_target_anchor"] for block in scored_blocks),
        "target_anchor_pages": anchor_pages,
        "candidate_window_count": len(windows),
        "pruned_window_count": pruned_window_count,
        "window_pruning_enabled": prune_windows,
        "candidate_window_pages": sorted({window["page_number"] for window in windows}),
        "recommended_visual_pages": visual_pages,
        "recommended_visual_page_count": len(visual_pages),
        "visual_page_reduction_percent": round(100 * (1 - len(visual_pages) / document.page_count), 1),
        "include_other_zones": getattr(args, "include_other_zones", False),
        "config": config,
    }
    write_jsonl(output_dir / "local_blocks_scored.jsonl", scored_blocks)
    write_jsonl(output_dir / "candidate_windows.jsonl", windows)
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    args = parse_args()
    summary = process_local_selection(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
