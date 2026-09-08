#!/usr/bin/env python3
"""Build a static 3D RAG graph demo for the Burnaby extraction pipeline."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "demos" / "burnaby_rag_3d_demo.html"
PACKS_PATH = ROOT / "outputs" / "burnaby" / "04_graph_rag_packs" / "retrieval_packs.jsonl"
VISUAL_BLOCKS_PATH = ROOT / "outputs" / "burnaby" / "05_rag_visual_blocks" / "text_blocks.jsonl"
TABLE_REGIONS_PATH = ROOT / "resources" / "visual_blocks" / "burnaby" / "table_regions.jsonl"
TABLE_LOGS_PATH = ROOT / "outputs" / "burnaby" / "06_rule_extraction_hq" / "table_extraction_logs.json"

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


def node(
    node_id: str,
    label: str,
    group: str,
    color: str,
    size: float,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "group": group,
        "color": color,
        "size": size,
        "details": details,
    }


def build_graph() -> dict[str, Any]:
    packs = read_jsonl(PACKS_PATH)
    visual_blocks = read_jsonl(VISUAL_BLOCKS_PATH) if VISUAL_BLOCKS_PATH.exists() else []
    table_regions = read_jsonl(TABLE_REGIONS_PATH) if TABLE_REGIONS_PATH.exists() else []
    table_logs = read_json(TABLE_LOGS_PATH) or []
    table_log_by_id = {
        row.get("batch_id"): row
        for row in table_logs
        if isinstance(row, dict) and row.get("batch_id")
    }
    visual_by_source = {
        row.get("original_source_id"): row
        for row in visual_blocks
        if row.get("original_source_id")
    }

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []

    nodes.append(
        node(
            "city:burnaby",
            "Burnaby R1",
            "city",
            APP_COLORS["city"],
            12,
            {
                "type": "City Root",
                "city": "Burnaby",
                "packs": len(packs),
                "blocks": sum(len(pack.get("evidence_blocks", [])) for pack in packs),
                "description": "Graph/RAG evidence structure used before batched rule extraction.",
            },
        )
    )

    lane_counts = Counter()
    role_counts = Counter()

    for pack in packs:
        pack_id = pack["pack_id"]
        applicability = pack.get("applicability", "core_rule")
        lane_counts[applicability] += 1
        pack_node_id = f"pack:{pack_id}"
        pack_label = f"{pack_id.replace('burnaby_generic_graph_pack_', 'pack ')} | {applicability}"
        pack_color = APP_COLORS.get(applicability, "#e5e7eb")
        evidence_blocks = pack.get("evidence_blocks", [])
        nodes.append(
            node(
                pack_node_id,
                pack_label,
                applicability,
                pack_color,
                6 + min(8, len(evidence_blocks) * 1.2),
                {
                    "type": "RAG Pack",
                    "pack_id": pack_id,
                    "applicability": applicability,
                    "page": pack.get("page_number"),
                    "scope": clean_text(pack.get("scope"), 260),
                    "roles": pack.get("roles", {}),
                    "source_block_count": pack.get("source_block_count"),
                    "evidence_block_count": pack.get("evidence_block_count"),
                    "char_count": pack.get("char_count"),
                },
            )
        )
        links.append({"source": "city:burnaby", "target": pack_node_id, "type": "contains", "value": 2})

        for block in evidence_blocks:
            source_id = block.get("source_id", "")
            role = block.get("role", "block")
            role_counts[role] += 1
            visual = visual_by_source.get(source_id, {})
            block_node_id = f"block:{pack_id}:{source_id}"
            text = block.get("text", "")
            block_label = f"{source_id} | {role}"
            block_color = ROLE_COLORS.get(role, APP_COLORS["block"])
            score = float(block.get("compression_score") or block.get("semantic_score") or 0.0)
            nodes.append(
                node(
                    block_node_id,
                    block_label,
                    role,
                    block_color,
                    3.8 + min(5, score * 6),
                    {
                        "type": "Evidence Block",
                        "source_id": source_id,
                        "role": role,
                        "applicability": block.get("applicability"),
                        "original_page": pack.get("page_number"),
                        "selection_tier": block.get("selection_tier"),
                        "drop_risk": block.get("drop_risk"),
                        "semantic_score": block.get("semantic_score"),
                        "structural_score": block.get("structural_score"),
                        "compression_score": block.get("compression_score"),
                        "selected_because": block.get("selected_because", []),
                        "target_filter_action": visual.get("target_filter_action", ""),
                        "text": clean_text(text, 900),
                    },
                )
            )
            links.append({"source": pack_node_id, "target": block_node_id, "type": "evidence", "value": 1})

    if table_regions:
        table_package_id = "pack:burnaby_table_extraction_package"
        total_table_rules = sum(int((table_log_by_id.get(row.get("region_id")) or {}).get("rule_count") or 0) for row in table_regions)
        nodes.append(
            node(
                table_package_id,
                f"table extraction package | {len(table_regions)} tables",
                "table_extraction_package",
                APP_COLORS["table_extraction_package"],
                10,
                {
                    "type": "Table Extraction Package",
                    "city": "Burnaby",
                    "table_count": len(table_regions),
                    "rule_count": total_table_rules,
                    "description": "Special visual/table branch sent through table extraction rather than text-pack extraction.",
                },
            )
        )
        links.append({"source": "city:burnaby", "target": table_package_id, "type": "contains", "value": 2.4})

        for table in table_regions:
            region_id = table.get("region_id", "")
            log = table_log_by_id.get(region_id, {})
            table_node_id = f"table:{region_id}"
            page_number = table.get("page_number")
            section_heading = table.get("section_heading")
            nodes.append(
                node(
                    table_node_id,
                    f"{region_id} | table region",
                    "table_region",
                    ROLE_COLORS["table_region"],
                    6.8,
                    {
                        "type": "Table Region",
                        "region_id": region_id,
                        "page": page_number,
                        "section_heading": section_heading,
                        "image_path": table.get("image_path"),
                        "source_page_image": table.get("source_page_image"),
                        "crop_bbox": table.get("crop_bbox"),
                        "model_crop_bbox": table.get("model_crop_bbox"),
                        "rule_count": log.get("rule_count"),
                        "status": log.get("status"),
                        "seconds": log.get("seconds"),
                    },
                )
            )
            links.append({"source": table_package_id, "target": table_node_id, "type": "table", "value": 1.6})

    return {
        "nodes": nodes,
        "links": links,
        "meta": {
            "city": "Burnaby",
            "pack_count": len(packs),
            "block_count": sum(len(pack.get("evidence_blocks", [])) for pack in packs),
            "table_count": len(table_regions),
            "lane_counts": dict(lane_counts),
            "role_counts": dict(role_counts),
            "source": str(PACKS_PATH.relative_to(ROOT.parent.parent)),
        },
    }


def render_html(graph: dict[str, Any]) -> str:
    graph_json = json.dumps(graph, ensure_ascii=False)
    meta = graph["meta"]
    legend_items = [
        ("Core rule pack", APP_COLORS["core_rule"]),
        ("Use permission pack", APP_COLORS["use_permission"]),
        ("Dimensional override pack", APP_COLORS["district_dimensional_override"]),
        ("Universal applicable pack", APP_COLORS["universal_applicable_rule"]),
        ("Target/context block", ROLE_COLORS["target_context"]),
        ("Permission block", ROLE_COLORS["permission"]),
        ("Dimensional block", ROLE_COLORS["dimensional_standard"]),
        ("Parking block", ROLE_COLORS["parking"]),
    ]
    legend = "\n".join(
        f'<div class="legend-row"><span style="background:{color}"></span>{html.escape(label)}</div>'
        for label, color in legend_items
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Burnaby RAG 3D Graph</title>
  <style>
    html, body {{
      margin: 0;
      height: 100%;
      overflow: hidden;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      background: #05070d;
      color: #e5e7eb;
    }}
    #graph {{
      position: fixed;
      inset: 0;
    }}
    .panel {{
      position: fixed;
      top: 16px;
      left: 16px;
      width: min(390px, calc(100vw - 32px));
      max-height: calc(100vh - 32px);
      overflow: auto;
      background: rgba(8, 12, 22, 0.86);
      border: 1px solid rgba(148, 163, 184, 0.24);
      border-radius: 8px;
      box-shadow: 0 18px 60px rgba(0, 0, 0, 0.35);
      backdrop-filter: blur(10px);
    }}
    .panel header {{
      padding: 14px 16px 10px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    }}
    h1 {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .sub {{
      margin-top: 6px;
      color: #94a3b8;
      font-size: 12px;
      line-height: 1.35;
    }}
    .controls {{
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 8px;
      padding: 12px 16px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    }}
    input {{
      min-width: 0;
      color: #e5e7eb;
      background: #101827;
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 13px;
      outline: none;
    }}
    button {{
      color: #e5e7eb;
      background: #172033;
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 13px;
      cursor: pointer;
    }}
    button:hover {{ background: #1f2a44; }}
    .body {{
      padding: 12px 16px 16px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }}
    .stat {{
      background: rgba(15, 23, 42, 0.78);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 6px;
      padding: 8px;
    }}
    .stat b {{
      display: block;
      font-size: 18px;
      color: #f8fafc;
    }}
    .stat span {{
      display: block;
      margin-top: 2px;
      color: #94a3b8;
      font-size: 11px;
    }}
    .legend {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px 10px;
      margin: 12px 0;
    }}
    .legend-row {{
      display: flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      color: #cbd5e1;
      font-size: 11px;
    }}
    .legend-row span {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex: 0 0 auto;
    }}
    #details {{
      border-top: 1px solid rgba(148, 163, 184, 0.18);
      padding-top: 12px;
    }}
    .empty {{
      color: #94a3b8;
      font-size: 13px;
      line-height: 1.45;
    }}
    .kv {{
      margin: 0 0 8px;
      font-size: 12px;
      line-height: 1.45;
    }}
    .kv strong {{
      color: #f8fafc;
    }}
    .text {{
      white-space: pre-wrap;
      color: #dbeafe;
      background: rgba(15, 23, 42, 0.88);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 6px;
      padding: 10px;
      margin-top: 10px;
      font-size: 12px;
      line-height: 1.45;
    }}
    .hint {{
      position: fixed;
      right: 16px;
      bottom: 14px;
      color: #94a3b8;
      font-size: 12px;
      background: rgba(8, 12, 22, 0.68);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 6px;
      padding: 8px 10px;
    }}
    @media (max-width: 720px) {{
      .panel {{
        width: calc(100vw - 24px);
        left: 12px;
        top: 12px;
      }}
      .legend {{
        grid-template-columns: 1fr;
      }}
      .hint {{
        display: none;
      }}
    }}
  </style>
  <script src="https://unpkg.com/three"></script>
  <script src="https://unpkg.com/3d-force-graph"></script>
</head>
<body>
  <div id="graph"></div>
  <section class="panel">
    <header>
      <h1>Burnaby RAG Structure</h1>
      <div class="sub">Interactive 3D view of graph/RAG packs and evidence blocks before rule extraction.</div>
    </header>
    <div class="controls">
      <input id="search" placeholder="Search block text, e.g. setback" />
      <button id="focus">Focus</button>
      <button id="reset">Reset</button>
    </div>
    <div class="body">
      <div class="stats">
        <div class="stat"><b>{meta["pack_count"]}</b><span>RAG packs</span></div>
        <div class="stat"><b>{meta["block_count"]}</b><span>evidence blocks</span></div>
        <div class="stat"><b>{len(graph["links"])}</b><span>links</span></div>
      </div>
      <div class="legend">{legend}</div>
      <div id="details"><div class="empty">Click a node to inspect its source, role, score, and block text.</div></div>
    </div>
  </section>
  <div class="hint">Drag to rotate · scroll to zoom · click nodes for details</div>
  <script>
    const rawGraph = {graph_json};
    const baseNodeColors = new Map(rawGraph.nodes.map(n => [n.id, n.color]));
    const details = document.getElementById('details');
    const graphEl = document.getElementById('graph');
    const search = document.getElementById('search');

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }}[ch]));
    }}

    function renderDetails(node) {{
      const d = node.details || {{}};
      const rows = Object.entries(d)
        .filter(([key, value]) => key !== 'text' && value !== undefined && value !== null && value !== '')
        .map(([key, value]) => {{
          const printable = typeof value === 'object' ? JSON.stringify(value) : value;
          return `<p class="kv"><strong>${{escapeHtml(key)}}:</strong> ${{escapeHtml(printable)}}</p>`;
        }}).join('');
      const text = d.text ? `<div class="text">${{escapeHtml(d.text)}}</div>` : '';
      details.innerHTML = `<p class="kv"><strong>node:</strong> ${{escapeHtml(node.label)}}</p>${{rows}}${{text}}`;
    }}

    const Graph = ForceGraph3D()(graphEl)
      .graphData(rawGraph)
      .backgroundColor('#05070d')
      .nodeLabel(node => `${{node.label}}`)
      .nodeColor(node => node.color)
      .nodeVal(node => node.size)
      .linkColor(() => 'rgba(148, 163, 184, 0.36)')
      .linkWidth(link => link.value || 1)
      .linkOpacity(0.42)
      .linkDirectionalParticles(1)
      .linkDirectionalParticleWidth(1.4)
      .nodeResolution(18)
      .onNodeClick(node => {{
        renderDetails(node);
        const distance = 90;
        const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
        Graph.cameraPosition(
          {{ x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio }},
          node,
          900
        );
      }});

    Graph.d3Force('charge').strength(-72);
    Graph.d3Force('link').distance(link => link.type === 'contains' ? 52 : 28);

    function applySearch() {{
      const q = search.value.trim().toLowerCase();
      rawGraph.nodes.forEach(node => {{
        const haystack = `${{node.label}} ${{JSON.stringify(node.details || {{}})}}`.toLowerCase();
        node.color = !q || haystack.includes(q) ? baseNodeColors.get(node.id) : '#1f2937';
        node.size = !q || haystack.includes(q) ? node.size : Math.max(1.2, node.size * 0.45);
      }});
      Graph.nodeColor(node => node.color).nodeVal(node => node.size);
    }}

    document.getElementById('focus').addEventListener('click', applySearch);
    search.addEventListener('keydown', event => {{
      if (event.key === 'Enter') applySearch();
    }});
    document.getElementById('reset').addEventListener('click', () => {{
      search.value = '';
      rawGraph.nodes.forEach(node => {{
        node.color = baseNodeColors.get(node.id);
      }});
      Graph.nodeColor(node => node.color);
      Graph.zoomToFit(700, 45);
      details.innerHTML = '<div class="empty">Click a node to inspect its source, role, score, and block text.</div>';
    }});

    setTimeout(() => Graph.zoomToFit(900, 52), 500);
  </script>
</body>
</html>
"""


def main() -> None:
    graph = build_graph()
    OUTPUT.write_text(render_html(graph), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.resolve()), **graph["meta"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
