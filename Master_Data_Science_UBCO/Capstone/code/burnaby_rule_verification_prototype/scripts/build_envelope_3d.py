"""Build a self-contained Three.js buildable-envelope viewer.

Reads `outputs/<city>.../buildable_envelope.json` (a read-only projection of
verified rules) and writes `outputs/<city>.../envelope_3d.html`: a single HTML
page that loads Three.js + OrbitControls from a CDN (no build step) and renders
a demo 30 m x 40 m lot, the setback-inset buildable footprint extruded to the
max verified height, storey floor lines, and a hover/click panel showing the
governing rule id, value, and condition per face.

The page degrades per constraint family: any family absent from the envelope
JSON is simply omitted. The dashboard embeds the html when it exists and shows
an SVG plan-view fallback regardless.

This script never touches verifier outputs other than writing the new html
artifact.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "burnaby_r1_slim_pipeline5_registry"
ARTIFACT_NAME = "envelope_3d.html"
DEMO_LOT_WIDTH_M = 30.0
DEMO_LOT_DEPTH_M = 40.0


def envelope_governing_setbacks(envelope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Most restrictive setback per lot line from buildable_envelope.json."""
    governing: dict[str, dict[str, Any]] = {}
    for lot_line, entries in (envelope.get("lot_line_setbacks_m") or {}).items():
        valid = [entry for entry in entries if entry.get("value_numeric") is not None]
        if valid:
            governing[lot_line] = max(valid, key=lambda entry: float(entry["value_numeric"]))
    return governing


def envelope_max_height(envelope: dict[str, Any]) -> dict[str, Any] | None:
    """Tallest verified height limit across roles, with its role attached."""
    best: dict[str, Any] | None = None
    for role, entries in (envelope.get("max_height_m_by_role") or {}).items():
        for entry in entries:
            if entry.get("value_numeric") is None:
                continue
            if best is None or float(entry["value_numeric"]) > float(best["value_numeric"]):
                best = {**entry, "role": role}
    return best


def envelope_max_storeys(envelope: dict[str, Any]) -> dict[str, Any] | None:
    """Highest verified storey limit across roles, with its role attached."""
    best: dict[str, Any] | None = None
    for role, entries in (envelope.get("max_storeys_by_role") or {}).items():
        for entry in entries:
            if entry.get("value_numeric") is None:
                continue
            if best is None or float(entry["value_numeric"]) > float(best["value_numeric"]):
                best = {**entry, "role": role}
    return best


def demo_footprint_insets(setbacks: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Map governing setbacks onto the 4-sided demo lot."""
    return {
        "front": float(setbacks.get("front_lot_line", {}).get("value_numeric") or 0.0),
        "rear": float(setbacks.get("rear_lot_line", {}).get("value_numeric") or 0.0),
        "side": float(setbacks.get("side_lot_line", {}).get("value_numeric") or 0.0),
    }


def build_envelope_svg(envelope: dict[str, Any]) -> str:
    """Plan-view SVG fallback for the standalone 3D envelope viewer."""
    setbacks = envelope_governing_setbacks(envelope or {})
    insets = demo_footprint_insets(setbacks)
    height = envelope_max_height(envelope or {})
    storeys = envelope_max_storeys(envelope or {})

    scale = 8.0
    margin_x, margin_y = 200.0, 60.0
    lot_w, lot_d = DEMO_LOT_WIDTH_M * scale, DEMO_LOT_DEPTH_M * scale
    width, height_px = lot_w + 2 * margin_x, lot_d + 2 * margin_y + 40
    lot_x, lot_y = margin_x, margin_y

    fp_x = lot_x + insets["side"] * scale
    fp_y = lot_y + insets["rear"] * scale
    fp_w = max(lot_w - 2 * insets["side"] * scale, 0.0)
    fp_h = max(lot_d - (insets["front"] + insets["rear"]) * scale, 0.0)

    def _label(entry: dict[str, Any], name: str) -> str:
        value = entry.get("value_numeric")
        return f"{name} {value} {entry.get('unit') or 'm'} ({entry.get('rule_id')})" if value is not None else name

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height_px:g}" '
        f'width="{width:g}" height="{height_px:g}" role="img" aria-label="Buildable envelope plan view">',
        "<defs><marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
        "<path d='M 0 0 L 10 5 L 0 10 z' fill='#cf222e'/></marker></defs>",
        f"<rect x='0' y='0' width='{width:g}' height='{height_px:g}' fill='#ffffff'/>",
        f"<text x='{lot_x:g}' y='{margin_y - 32:g}' font-size='16' font-weight='700' fill='#172033'>"
        f"{html.escape(str(envelope.get('city') or ''))} {html.escape(str(envelope.get('zone') or ''))} buildable envelope - plan view</text>",
        f"<text x='{lot_x:g}' y='{margin_y - 14:g}' font-size='12' fill='#57606a'>"
        f"Demo lot {DEMO_LOT_WIDTH_M:g} m x {DEMO_LOT_DEPTH_M:g} m (representative, not a real parcel). Front lot line at bottom.</text>",
        f"<rect x='{lot_x:g}' y='{lot_y:g}' width='{lot_w:g}' height='{lot_d:g}' fill='#f1f4f7' stroke='#57606a' stroke-width='2'/>",
        f"<rect x='{fp_x:g}' y='{fp_y:g}' width='{fp_w:g}' height='{fp_h:g}' fill='#1a7f37' fill-opacity='0.22' stroke='#1a7f37' stroke-width='2'/>",
    ]

    mid_x, mid_y = lot_x + lot_w / 2, lot_y + lot_d / 2
    arrows: list[tuple[str, float, float, float, float, float, float, str]] = []
    front = setbacks.get("front_lot_line")
    if front:
        arrows.append((_label(front, "front"), mid_x, lot_y + lot_d, mid_x, fp_y + fp_h, mid_x + 8, lot_y + lot_d - insets["front"] * scale / 2, "start"))
    rear = setbacks.get("rear_lot_line")
    if rear:
        arrows.append((_label(rear, "rear"), mid_x, lot_y, mid_x, fp_y, mid_x + 8, lot_y + insets["rear"] * scale / 2 + 4, "start"))
    side = setbacks.get("side_lot_line")
    if side:
        arrows.append((_label(side, "side"), lot_x, mid_y, fp_x, mid_y, lot_x - 8, mid_y - 8, "end"))
        arrows.append((_label(side, "side"), lot_x + lot_w, mid_y, fp_x + fp_w, mid_y, lot_x + lot_w + 8, mid_y - 8, "start"))
    for label, x1, y1, x2, y2, tx, ty, anchor in arrows:
        parts.append(
            f"<line x1='{x1:g}' y1='{y1:g}' x2='{x2:g}' y2='{y2:g}' stroke='#cf222e' stroke-width='2' marker-end='url(#arrow)'/>"
        )
        parts.append(f"<text x='{tx:g}' y='{ty:g}' font-size='12' fill='#172033' text-anchor='{anchor}'>{html.escape(label)}</text>")

    notes_y = lot_y + lot_d + 24
    note_lines: list[str] = []
    if height:
        note_lines.append(_label(height, "max height") + f" - {height.get('role')}" + (f", {height.get('condition')}" if height.get("condition") else ""))
    if storeys:
        note_lines.append(_label(storeys, "max storeys") + f" - {storeys.get('role')}")
    lane = setbacks.get("lane_lot_line")
    if lane:
        note_lines.append(_label(lane, "lane setback") + " - demo lot has no lane; shown for reference only")
    for index, line in enumerate(note_lines):
        parts.append(f"<text x='{lot_x:g}' y='{notes_y + index * 16:g}' font-size='12' fill='#57606a'>{html.escape(line)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def summarize_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Reduce the envelope JSON to what the viewer draws: one governing entry
    per family plus the full per-lot-line lists for the info panel."""
    governing = envelope_governing_setbacks(envelope)
    return {
        "city": envelope.get("city"),
        "zone": envelope.get("zone"),
        "source_document": envelope.get("source_document"),
        "lot": {"width_m": DEMO_LOT_WIDTH_M, "depth_m": DEMO_LOT_DEPTH_M},
        "setbacks": governing,
        "setback_variants": envelope.get("lot_line_setbacks_m") or {},
        "insets": demo_footprint_insets(governing),
        "height": envelope_max_height(envelope),
        "storeys": envelope_max_storeys(envelope),
        "separations": envelope.get("building_separations_m") or [],
        "notes": envelope.get("notes") or [],
    }


def build_envelope_html(envelope: dict[str, Any]) -> str:
    """Return the full self-contained HTML page for one envelope JSON."""
    summary = summarize_envelope(envelope)
    return _PAGE_TEMPLATE.replace("__SUMMARY_JSON__", json.dumps(summary, indent=None))


def build(output_dir: Path, out_path: Path | None = None) -> Path:
    """Read buildable_envelope.json from output_dir and write the html artifact."""
    envelope_path = output_dir / "buildable_envelope.json"
    if not envelope_path.exists():
        raise FileNotFoundError(
            f"{envelope_path} not found. This city has no buildable-envelope export yet; "
            "nothing was written."
        )
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    target = out_path or (output_dir / ARTIFACT_NAME)
    target.write_text(build_envelope_html(envelope), encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Verifier output directory")
    parser.add_argument("--out", default=None, help=f"Target html path (default: <output-dir>/{ARTIFACT_NAME})")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser()
    try:
        target = build(output_dir, Path(args.out).expanduser() if args.out else None)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {target}")


# Page template. __SUMMARY_JSON__ is replaced with the envelope summary.
# Three.js + OrbitControls come from a CDN via an import map; everything else
# is inline so the file is fully self-contained.
_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Buildable Envelope 3D Viewer</title>
<style>
  html, body {margin:0; padding:0; height:100%; font-family: Inter, -apple-system, "Segoe UI", sans-serif; background:#f7fafc;}
  #scene {width:100%; height:100%; display:block;}
  .panel {position:absolute; background:#ffffff; border:1px solid #d9e0e8; border-radius:8px; padding:10px 12px;
          box-shadow:0 1px 3px rgba(15,23,42,.12); font-size:12px; color:#172033; max-width:300px;}
  #info {top:12px; left:12px;}
  #info h1 {font-size:14px; margin:0 0 4px;}
  #info p {margin:2px 0; color:#57606a;}
  #hover {bottom:12px; left:12px; display:none;}
  #hover b {font-size:13px;}
  #hover .rule {color:#1a7f37; font-weight:700;}
  #legend {top:12px; right:12px;}
  .swatch {display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:middle;}
  .row {margin:3px 0;}
</style>
</head>
<body>
<canvas id="scene"></canvas>
<div class="panel" id="info">
  <h1 id="title">Buildable envelope</h1>
  <p>Demo lot — representative rectangle, <b>not a real parcel</b>.</p>
  <p>Derived only from verified rules. Drag to orbit, scroll to zoom.</p>
  <p>Hover or click a surface for the governing rule.</p>
</div>
<div class="panel" id="legend"></div>
<div class="panel" id="hover"></div>
<script type="importmap">
{"imports": {"three": "https://unpkg.com/three@0.160.0/build/three.module.js",
             "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"}}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const SUMMARY = __SUMMARY_JSON__;

const COLORS = {lot: 0xe4e9ee, setback: 0xcf222e, envelope: 0x1a7f37, storey: 0x57606a};
const W = SUMMARY.lot.width_m, D = SUMMARY.lot.depth_m;
const insets = SUMMARY.insets || {front: 0, rear: 0, side: 0};
// Lot axes: x spans width (west->east), z spans depth; front lot line at z = +D/2.
const fpW = Math.max(W - 2 * (insets.side || 0), 0);
const fpD = Math.max(D - (insets.front || 0) - (insets.rear || 0), 0);
const fpZ = ((insets.rear || 0) - (insets.front || 0)) / 2;
const H = SUMMARY.height ? Number(SUMMARY.height.value_numeric) : 0;
const STOREYS = SUMMARY.storeys ? Math.round(Number(SUMMARY.storeys.value_numeric)) : 0;

document.getElementById('title').textContent =
  `${SUMMARY.city || ''} ${SUMMARY.zone || ''} buildable envelope`.trim() || 'Buildable envelope';

const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({canvas, antialias: true});
renderer.setPixelRatio(window.devicePixelRatio);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf7fafc);
const camera = new THREE.PerspectiveCamera(48, 2, 0.1, 1000);
camera.position.set(W * 1.2, Math.max(H, 8) * 2.4, D * 1.15);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, Math.max(H, 4) / 2, 0);
controls.update();

scene.add(new THREE.AmbientLight(0xffffff, 0.85));
const sun = new THREE.DirectionalLight(0xffffff, 1.1);
sun.position.set(40, 60, 30);
scene.add(sun);

const pickables = [];
function describe(entry, family, extra) {
  if (!entry) return null;
  return {
    family: family,
    parameter: entry.applies_to || family,
    rule_id: entry.rule_id || '',
    value: `${entry.operator || ''} ${entry.value_numeric} ${entry.unit || ''}`.trim(),
    condition: entry.condition || 'no condition',
    extra: extra || ''
  };
}

// Ground lot plane.
const lot = new THREE.Mesh(
  new THREE.PlaneGeometry(W, D),
  new THREE.MeshLambertMaterial({color: COLORS.lot, side: THREE.DoubleSide}));
lot.rotation.x = -Math.PI / 2;
lot.userData.info = {family: 'demo lot', parameter: `${W} m x ${D} m demo lot`, rule_id: 'n/a',
                     value: 'representative rectangle', condition: 'not a real parcel', extra: ''};
scene.add(lot);
pickables.push(lot);
const lotEdge = new THREE.LineLoop(
  new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-W/2, 0.01, -D/2), new THREE.Vector3(W/2, 0.01, -D/2),
    new THREE.Vector3(W/2, 0.01, D/2), new THREE.Vector3(-W/2, 0.01, D/2)]),
  new THREE.LineBasicMaterial({color: 0x57606a}));
scene.add(lotEdge);

// Setback strips (no-build bands). Family omitted entirely when absent.
const sb = SUMMARY.setbacks || {};
const strips = [];
if (sb.front_lot_line && insets.front > 0)
  strips.push([W, insets.front, 0, D/2 - insets.front/2, describe(sb.front_lot_line, 'front setback')]);
if (sb.rear_lot_line && insets.rear > 0)
  strips.push([W, insets.rear, 0, -D/2 + insets.rear/2, describe(sb.rear_lot_line, 'rear setback')]);
if (sb.side_lot_line && insets.side > 0) {
  strips.push([insets.side, D, -W/2 + insets.side/2, 0, describe(sb.side_lot_line, 'side setback (west)')]);
  strips.push([insets.side, D, W/2 - insets.side/2, 0, describe(sb.side_lot_line, 'side setback (east)')]);
}
for (const [sw, sd, x, z, info] of strips) {
  const strip = new THREE.Mesh(
    new THREE.PlaneGeometry(sw, sd),
    new THREE.MeshLambertMaterial({color: COLORS.setback, transparent: true, opacity: 0.35, side: THREE.DoubleSide}));
  strip.rotation.x = -Math.PI / 2;
  strip.position.set(x, 0.03, z);
  strip.userData.info = info;
  scene.add(strip);
  pickables.push(strip);
}

// Buildable envelope prism (omitted when there is no verified height family;
// the footprint is then drawn flat).
if (fpW > 0 && fpD > 0) {
  const prismH = H > 0 ? H : 0.15;
  const box = new THREE.Mesh(
    new THREE.BoxGeometry(fpW, prismH, fpD),
    new THREE.MeshLambertMaterial({color: COLORS.envelope, transparent: true, opacity: 0.4}));
  box.position.set(0, prismH / 2, fpZ);
  box.userData.info = H > 0
    ? describe(SUMMARY.height, `max height (${SUMMARY.height.role || ''})`,
               'Buildable footprint after governing setbacks, extruded to the max verified height.')
    : {family: 'buildable footprint', parameter: 'footprint only', rule_id: 'n/a',
       value: 'no verified height constraint', condition: '', extra: ''};
  scene.add(box);
  pickables.push(box);
  scene.add(new THREE.LineSegments(
    new THREE.EdgesGeometry(box.geometry),
    new THREE.LineBasicMaterial({color: COLORS.envelope})).translateX(0).translateY(prismH / 2).translateZ(fpZ));

  // Storey floor lines (family omitted when absent).
  if (H > 0 && STOREYS > 1) {
    const storeyInfo = describe(SUMMARY.storeys, `max storeys (${SUMMARY.storeys.role || ''})`);
    for (let i = 1; i < STOREYS; i++) {
      const y = (H * i) / STOREYS;
      const line = new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(-fpW/2, y, fpZ - fpD/2), new THREE.Vector3(fpW/2, y, fpZ - fpD/2),
          new THREE.Vector3(fpW/2, y, fpZ + fpD/2), new THREE.Vector3(-fpW/2, y, fpZ + fpD/2)]),
        new THREE.LineBasicMaterial({color: COLORS.storey}));
      line.userData.info = storeyInfo;
      scene.add(line);
    }
  }
}

// Legend: only the families actually drawn.
const legendRows = [['#e4e9ee', `demo lot ${W} x ${D} m`]];
for (const [key, label] of [['front_lot_line','front'], ['rear_lot_line','rear'], ['side_lot_line','side'], ['lane_lot_line','lane (reference only)']]) {
  const entry = sb[key];
  if (entry) legendRows.push(['#cf222e', `${label} setback ${entry.value_numeric} ${entry.unit || 'm'} — ${entry.rule_id}`]);
}
if (SUMMARY.height) legendRows.push(['#1a7f37', `max height ${SUMMARY.height.value_numeric} ${SUMMARY.height.unit || 'm'} — ${SUMMARY.height.rule_id}`]);
if (SUMMARY.storeys) legendRows.push(['#57606a', `max storeys ${SUMMARY.storeys.value_numeric} — ${SUMMARY.storeys.rule_id}`]);
document.getElementById('legend').innerHTML = legendRows
  .map(([color, text]) => `<div class="row"><span class="swatch" style="background:${color}"></span>${text}</div>`)
  .join('');

// Hover / click info panel.
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const hoverPanel = document.getElementById('hover');
let pinned = false;
function showInfo(info) {
  if (!info) { if (!pinned) hoverPanel.style.display = 'none'; return; }
  hoverPanel.style.display = 'block';
  hoverPanel.innerHTML =
    `<b>${info.family}</b><div class="rule">${info.rule_id}</div>` +
    `<div>${info.value}</div><div>condition: ${info.condition}</div>` +
    `<div>${info.parameter}</div>` + (info.extra ? `<div>${info.extra}</div>` : '');
}
function pick(event) {
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(pickables, false);
  return hits.length ? hits[0].object.userData.info : null;
}
canvas.addEventListener('pointermove', (event) => { if (!pinned) showInfo(pick(event)); });
canvas.addEventListener('click', (event) => {
  const info = pick(event);
  pinned = Boolean(info);
  showInfo(info);
});

function resize() {
  const w = canvas.clientWidth || window.innerWidth;
  const h = canvas.clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
resize();
animate();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
