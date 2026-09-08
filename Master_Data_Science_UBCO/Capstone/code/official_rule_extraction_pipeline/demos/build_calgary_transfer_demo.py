#!/usr/bin/env python3
"""Build Calgary assets for the clickable RAG pipeline transfer demo."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import fitz


ROOT = Path(__file__).resolve().parents[1]
DEMOS = ROOT / "demos"
PDF_PATH = ROOT / "pdfs" / "calgary" / "calgary-land-use-bylaw-1p2007.pdf"
LOCAL_BLOCKS_PATH = ROOT / "outputs" / "calgary" / "01_local_selection" / "local_blocks_scored.jsonl"
MANIFEST_PATH = ROOT / "outputs" / "calgary" / "05_rag_visual_blocks" / "rag_adapter_manifest.json"
VISUAL_BLOCKS_PATH = ROOT / "outputs" / "calgary" / "05_rag_visual_blocks" / "text_blocks.jsonl"
TABLE_REGIONS_PATH = ROOT / "resources" / "visual_blocks" / "calgary" / "table_regions.jsonl"
TABLE_LOGS_PATH = ROOT / "outputs" / "calgary" / "06_rule_extraction_hq" / "table_extraction_logs.json"
TEMPLATE_HTML = DEMOS / "rag_pipeline_transfer_animation.html"

RAW_CROP_DIR = DEMOS / "calgary_raw_block_crops"
RAW_DATA_JS = DEMOS / "calgary_raw_blocks_data.js"
GRAPH_DATA_JS = DEMOS / "calgary_rag_graph_data.js"
OUTPUT_HTML = DEMOS / "calgary_rag_pipeline_transfer_animation.html"

RAW_PREVIEW_LIMIT = 100

APP_COLORS = {
    "city": "#e5e7eb",
    "core_rule": "#f97316",
    "use_permission": "#38bdf8",
    "district_dimensional_override": "#a78bfa",
    "universal_applicable_rule": "#22c55e",
    "table_extraction_package": "#facc15",
    "context_only": "#94a3b8",
    "block": "#facc15",
}

ROLE_COLORS = {
    "target_context": "#fb923c",
    "permission": "#38bdf8",
    "dimensional_standard": "#a78bfa",
    "parking": "#22c55e",
    "permit_process": "#14b8a6",
    "cross_reference": "#c084fc",
    "related_context": "#94a3b8",
    "context_definition": "#64748b",
    "table_region": "#fde047",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def clean_text(value: Any, limit: int = 420) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def node(node_id: str, label: str, group: str, color: str, size: float, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "group": group,
        "color": color,
        "size": size,
        "details": details,
    }


def page_text_blocks(page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
    blocks = []
    for item in page.get_text("blocks"):
        if len(item) < 5:
            continue
        x0, y0, x1, y1, text = item[:5]
        text = str(text or "").strip()
        if not text:
            continue
        blocks.append((float(x0), float(y0), float(x1), float(y1), text))
    return sorted(blocks, key=lambda row: (row[1], row[0]))


def padded_rect(page: fitz.Page, bbox: tuple[float, float, float, float], pad: float = 6.0) -> fitz.Rect:
    rect = fitz.Rect(bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    return rect & page.rect


def build_raw_block_assets() -> tuple[int, int]:
    local_blocks = read_jsonl(LOCAL_BLOCKS_PATH)
    RAW_CROP_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF_PATH)
    page_cache: dict[int, list[tuple[float, float, float, float, str]]] = {}
    rows = []

    for index, block in enumerate(local_blocks[:RAW_PREVIEW_LIMIT], start=1):
        page_number = int(block.get("page_number") or 1)
        page_index = max(0, page_number - 1)
        page = doc[page_index]
        if page_number not in page_cache:
            page_cache[page_number] = page_text_blocks(page)
        blocks = page_cache[page_number]
        block_index = int(block.get("page_block_index") or index) - 1
        if 0 <= block_index < len(blocks):
            x0, y0, x1, y1, _ = blocks[block_index]
            rect = padded_rect(page, (x0, y0, x1, y1))
        else:
            rect = page.rect

        block_id = block.get("block_id") or f"page_{page_number:04d}__local_{index:03d}"
        image_name = f"{block_id}.png"
        image_path = RAW_CROP_DIR / image_name
        pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), clip=rect, alpha=False)
        pix.save(image_path)
        rows.append(
            {
                "id": block_id,
                "label": block_id,
                "page": page_number,
                "kind": "text",
                "section": clean_text(block.get("text"), 90),
                "src": f"calgary_raw_block_crops/{image_name}",
            }
        )

    doc.close()
    omitted_count = max(0, len(local_blocks) - len(rows))
    if omitted_count:
        rows.append(
            {
                "id": "omitted_raw_blocks",
                "label": f"{omitted_count} additional local blocks omitted",
                "page": "",
                "kind": "omitted",
                "section": "preview limit",
                "omitted": True,
                "count": omitted_count,
            }
        )
    RAW_DATA_JS.write_text(
        "window.CALGARY_RAW_BLOCKS = "
        + json.dumps(rows, ensure_ascii=False, indent=2)
        + ";\n"
        + f"window.CALGARY_RAW_BLOCKS_TOTAL = {len(local_blocks)};\n"
        + f"window.CALGARY_RAW_BLOCKS_DISPLAY_LIMIT = {len(rows)};\n",
        encoding="utf-8",
    )
    return len(local_blocks), len(rows)


def build_graph() -> dict[str, Any]:
    manifest = read_json(MANIFEST_PATH) or {}
    visual_blocks = read_jsonl(VISUAL_BLOCKS_PATH)
    table_regions = read_jsonl(TABLE_REGIONS_PATH)
    table_logs = read_json(TABLE_LOGS_PATH) or []
    table_log_by_id = {
        row.get("batch_id"): row
        for row in table_logs
        if isinstance(row, dict) and row.get("batch_id")
    }

    blocks_by_pack: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in visual_blocks:
        blocks_by_pack[block.get("rag_pack_id", "")].append(block)

    pack_rows = manifest.get("packs") or []
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    lane_counts = Counter()
    role_counts = Counter()

    nodes.append(
        node(
            "city:calgary",
            "Calgary Land Use Bylaw",
            "city",
            APP_COLORS["city"],
            13,
            {
                "type": "City Root",
                "city": "Calgary",
                "packs": len(pack_rows),
                "blocks": len(visual_blocks),
                "target": "backyard suite / secondary suite",
                "description": "Current official pipeline adapter output before batched rule extraction.",
            },
        )
    )

    for pack in pack_rows:
        pack_id = pack.get("pack_id", "")
        applicability = pack.get("applicability", "core_rule")
        lane = pack.get("lane", "")
        lane_counts[applicability] += 1
        pack_blocks = blocks_by_pack.get(pack_id, [])
        pack_node_id = f"pack:{pack_id}"
        pack_label = f"{pack_id.replace('calgary_generic_graph_pack_', 'pack ')} | {applicability}"
        nodes.append(
            node(
                pack_node_id,
                pack_label,
                applicability,
                APP_COLORS.get(applicability, "#e5e7eb"),
                5.6 + min(8, max(1, len(pack_blocks)) * 1.1),
                {
                    "type": "RAG Pack",
                    "pack_id": pack_id,
                    "lane": lane,
                    "applicability": applicability,
                    "pseudo_page": pack.get("pseudo_page_number"),
                    "original_page": pack.get("original_page_number"),
                    "block_count": pack.get("block_count"),
                    "source_block_count": pack.get("source_block_count"),
                    "char_count": pack.get("char_count"),
                    "target_filter_actions": pack.get("target_filter_actions"),
                },
            )
        )
        links.append({"source": "city:calgary", "target": pack_node_id, "type": "contains", "value": 2})

        for block in pack_blocks:
            role = block.get("rag_applicability") or applicability
            original_source_id = block.get("original_source_id") or block.get("block_id")
            role_counts[role] += 1
            block_node_id = f"block:{pack_id}:{original_source_id}"
            nodes.append(
                node(
                    block_node_id,
                    f"{original_source_id} | {block.get('target_filter_action', '')}",
                    role,
                    ROLE_COLORS.get(role, APP_COLORS.get(applicability, APP_COLORS["block"])),
                    3.4 + min(4, len(clean_text(block.get("text"), 220)) / 120),
                    {
                        "type": "Evidence Block",
                        "source_id": original_source_id,
                        "pack_id": pack_id,
                        "lane": block.get("rag_lane"),
                        "applicability": block.get("rag_applicability"),
                        "original_page": block.get("original_page_number"),
                        "target_filter_action": block.get("target_filter_action"),
                        "section_path": block.get("section_path", [])[-3:],
                        "text": clean_text(block.get("text"), 900),
                    },
                )
            )
            links.append({"source": pack_node_id, "target": block_node_id, "type": "evidence", "value": 1})

    if table_regions:
        table_package_id = "pack:calgary_table_extraction_package"
        total_table_rules = sum(int((table_log_by_id.get(row.get("region_id")) or {}).get("rule_count") or 0) for row in table_regions)
        nodes.append(
            node(
                table_package_id,
                f"table extraction package | {len(table_regions)} tables",
                "table_extraction_package",
                APP_COLORS["table_extraction_package"],
                9,
                {
                    "type": "Table Extraction Package",
                    "city": "Calgary",
                    "table_count": len(table_regions),
                    "rule_count": total_table_rules,
                    "description": "Special visual/table branch used for regulatory table image extraction.",
                },
            )
        )
        links.append({"source": "city:calgary", "target": table_package_id, "type": "contains", "value": 2.2})
        for table in table_regions:
            region_id = table.get("region_id", "")
            log = table_log_by_id.get(region_id, {})
            table_node_id = f"table:{region_id}"
            nodes.append(
                node(
                    table_node_id,
                    f"{region_id} | p.{table.get('page_number')}",
                    "table_region",
                    ROLE_COLORS["table_region"],
                    5.4,
                    {
                        "type": "Table Region",
                        "region_id": region_id,
                        "page": table.get("page_number"),
                        "section_heading": table.get("section_heading"),
                        "image_path": table.get("image_path"),
                        "rule_count": log.get("rule_count"),
                        "status": log.get("status"),
                    },
                )
            )
            links.append({"source": table_package_id, "target": table_node_id, "type": "table", "value": 1.5})

    return {
        "nodes": nodes,
        "links": links,
        "meta": {
            "city": "Calgary",
            "pack_count": len(pack_rows),
            "block_count": len(visual_blocks),
            "table_count": len(table_regions),
            "lane_counts": dict(lane_counts),
            "role_counts": dict(role_counts),
        },
    }


def build_graph_js() -> tuple[int, int, int]:
    graph = build_graph()
    GRAPH_DATA_JS.write_text(
        "window.CALGARY_RAG_GRAPH_DATA = "
        + json.dumps(graph, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )
    return graph["meta"]["pack_count"], graph["meta"]["block_count"], graph["meta"]["table_count"]


def build_html(total_blocks: int, preview_blocks: int, pack_count: int, evidence_count: int, table_count: int) -> None:
    html = TEMPLATE_HTML.read_text(encoding="utf-8")
    replacements = {
        "RAG Rule Extraction Animation": "Calgary RAG Rule Extraction Animation",
        "From PDF to Structured Rule Table": "Calgary PDF to Structured Rule Table",
        "BURNABY_RAW_BLOCKS": "CALGARY_RAW_BLOCKS",
        "BURNABY_RAG_GRAPH_DATA": "CALGARY_RAG_GRAPH_DATA",
        "burnaby_raw_blocks_data.js": "calgary_raw_blocks_data.js",
        "burnaby_rag_graph_data.js": "calgary_rag_graph_data.js",
        "Burnaby R1 PDF": "Calgary Land Use Bylaw",
        "Burnaby R1": "Calgary LUB",
        "Burnaby RAG Pack Graph": "Calgary RAG Pack Graph",
        "Raw Burnaby PDF block crops": "Raw Calgary PDF block crops",
        "4 Burnaby RAG Packs": "4 Calgary RAG Packs",
        "Burnaby graph data not loaded": "Calgary graph data not loaded",
        "Connect to the internet or use the standalone Burnaby graph demo if the CDN is blocked.": "Connect to the internet or use the standalone Calgary graph data if the CDN is blocked.",
        "Real pipeline output: 12 text RAG packs, 18 evidence blocks, and 1 table extraction package with 4 table regions. Drag to rotate, scroll to zoom, and click a node to inspect its metadata.": (
            f"Real pipeline output: {pack_count} RAG packs, {evidence_count} evidence blocks, "
            f"and {table_count} table region{'s' if table_count != 1 else ''}. Drag to rotate, scroll to zoom, and click a node to inspect its metadata."
        ),
        "The raw PDF is segmented into all raw visual blocks first: 94 text blocks and 4 table regions for Burnaby, before any filtering or semantic compression.": (
            f"The Calgary PDF has {total_blocks} local text blocks. For presentation speed, this stage previews the first {preview_blocks} raw block crops and omits the rest."
        ),
        "This stage uses the actual Burnaby graph: text RAG packs plus the special table extraction package used for visual/table rules.": (
            f"This stage uses the current Calgary graph: {pack_count} filtered RAG packs, {evidence_count} evidence blocks, plus the table package when table regions exist."
        ),
        "101.2, 101.4, 101.5, 101.6": "backyard suite / secondary suite",
        "local recall + auto discovery": "6009 local blocks -> target recall",
        "paragraphs, lists, inherited context": f"{evidence_count} filtered evidence blocks",
        "table regions and page crops": f"{table_count} table region + page crops",
        "small-scale multi-unit housing": "backyard suite / secondary suite",
        "rowhouse dwellings": "backyard / secondary suites",
    }
    for before, after in replacements.items():
        html = html.replace(before, after)
    html = html.replace(
        "    .block.table-block { outline: 2px solid rgba(250, 204, 21, 0.42); }\n",
        """    .block.table-block { outline: 2px solid rgba(250, 204, 21, 0.42); }

    .block.omitted-block {
      min-height: 112px;
      display: grid;
      place-items: center;
      background: rgba(7, 16, 24, 0.82);
      border: 1px dashed rgba(125, 211, 252, 0.42);
      color: #cbd5e1;
    }

    .omitted-card {
      text-align: center;
      font-size: 13px;
      line-height: 1.35;
    }

    .omitted-card strong {
      display: block;
      color: #e0f2fe;
      font-size: 18px;
      margin-bottom: 4px;
    }
""",
    )
    html = html.replace(
        """        el.className = `block ${block.kind === 'table' ? 'table-block' : 'text-block'}`;
        el.style.setProperty('--i', index);
        el.title = `${block.id || ''}\\npage ${block.page || ''}\\n${block.section || ''}`;
        el.innerHTML = `
          <img src="${escapeHtml(block.src)}" alt="${escapeHtml(block.label || block.id || 'raw PDF block')}" />
          <span class="block-label">${index + 1}/${rawBlocks.length} | p.${escapeHtml(block.page)} | ${escapeHtml(block.kind)} | ${escapeHtml(block.id)}</span>
        `;
        rawBlockStrip.appendChild(el);""",
        """        if (block.omitted) {
          el.className = 'block omitted-block';
          el.style.setProperty('--i', index);
          el.title = block.label || 'additional raw blocks omitted';
          el.innerHTML = `<div class="omitted-card"><strong>+${escapeHtml(block.count)}</strong><span>additional local blocks omitted from preview</span></div>`;
          rawBlockStrip.appendChild(el);
          return;
        }
        el.className = `block ${block.kind === 'table' ? 'table-block' : 'text-block'}`;
        el.style.setProperty('--i', index);
        el.title = `${block.id || ''}\\npage ${block.page || ''}\\n${block.section || ''}`;
        el.innerHTML = `
          <img src="${escapeHtml(block.src)}" alt="${escapeHtml(block.label || block.id || 'raw PDF block')}" />
          <span class="block-label">${index + 1}/${rawBlocks.length} | p.${escapeHtml(block.page)} | ${escapeHtml(block.kind)} | ${escapeHtml(block.id)}</span>
        `;
        rawBlockStrip.appendChild(el);""",
    )
    OUTPUT_HTML.write_text(html, encoding="utf-8")


def main() -> None:
    total_blocks, preview_blocks = build_raw_block_assets()
    pack_count, evidence_count, table_count = build_graph_js()
    build_html(total_blocks, preview_blocks, pack_count, evidence_count, table_count)
    print(f"Wrote {OUTPUT_HTML}")
    print(f"Raw preview: {preview_blocks}/{total_blocks}; graph: {pack_count} packs, {evidence_count} blocks, {table_count} tables")


if __name__ == "__main__":
    main()
