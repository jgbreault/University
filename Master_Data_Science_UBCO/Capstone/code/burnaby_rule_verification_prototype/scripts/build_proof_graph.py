#!/usr/bin/env python3
"""Render an interactive "why did this rule verify / go to review?" proof viewer.

Read-only post-processing of the verifier outputs. For every rule it shows the
per-claim proof trace (rule_object / scope / applies_to / operator / value /
unit / condition) with support/refute/not-enough-info badges, plus the
support_gaps that blocked any non-verified rule — so the *reason* for each
decision is visible at a glance. Produces a single self-contained HTML file
(inline CSS + a tiny filter); no build step, no external assets.

Run after run_slim_verifier.py.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.slim_pipeline import _rule_sentence  # polished rule sentence

DEFAULT_DIR = ROOT / "outputs" / "burnaby_r1_slim_pipeline5_registry"

_LABEL_CLASS = {"supported": "ok", "refuted": "bad", "not_enough_info": "warn"}
_DECISION_CLASS = {"verified": "ok", "review_needed": "warn", "rejected": "bad", "not_used": "muted"}


def _badge(label: str, text: str) -> str:
    return f'<span class="badge {label}">{html.escape(text)}</span>'


def _claim_rows(proof_trace: dict) -> str:
    rows = []
    for claim, item in proof_trace.items():
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "not_enough_info")
        cls = _LABEL_CLASS.get(label, "warn")
        quote = html.escape((item.get("evidence_quote") or "")[:240])
        reason = html.escape(item.get("reason") or "")
        rows.append(
            f'<tr><td class="claim">{html.escape(claim)}</td>'
            f'<td>{_badge(cls, label)}</td>'
            f'<td class="reason">{reason}</td>'
            f'<td class="quote">{quote}</td></tr>'
        )
    return "".join(rows)


def _card(rule: dict, decision: str) -> str:
    cls = _DECISION_CLASS.get(decision, "muted")
    rule_id = html.escape(str(rule.get("rule_id")))
    sentence = html.escape(_rule_sentence(rule))
    gaps = rule.get("support_gaps") or []
    reason = html.escape(rule.get("review_reason") or "")
    blockers = ""
    if decision != "verified" and gaps:
        chips = " ".join(_badge("bad" if decision == "rejected" else "warn", g) for g in gaps)
        blockers = f'<div class="blockers"><b>Blocked by:</b> {chips}<div class="reason">{reason}</div></div>'
    claims = _claim_rows(rule.get("proof_trace") or {})
    return (
        f'<div class="card {decision}" data-decision="{decision}" data-id="{rule_id.lower()}">'
        f'<div class="card-head"><span class="rid">{rule_id}</span>'
        f'{_badge(cls, decision)}</div>'
        f'<div class="sentence">{sentence}</div>'
        f'{blockers}'
        f'<table class="claims"><thead><tr><th>claim</th><th>proof</th><th>reason</th><th>evidence</th></tr></thead>'
        f'<tbody>{claims}</tbody></table></div>'
    )


_CSS = """
body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1c2430}
header{background:#0f2a43;color:#fff;padding:18px 24px}
header h1{margin:0 0 4px;font-size:20px}
header .sub{opacity:.8;font-size:13px}
.controls{position:sticky;top:0;background:#fff;border-bottom:1px solid #e2e6ea;padding:12px 24px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;z-index:5}
.controls button{border:1px solid #cbd2d9;background:#fff;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}
.controls button.active{background:#0f2a43;color:#fff;border-color:#0f2a43}
.controls input{flex:1;min-width:160px;padding:7px 10px;border:1px solid #cbd2d9;border-radius:6px}
.wrap{padding:18px 24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}
.card{background:#fff;border:1px solid #e2e6ea;border-radius:10px;padding:14px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.rid{font-weight:700;font-family:ui-monospace,Menlo,monospace}
.sentence{font-size:13px;color:#2c3a4a;margin-bottom:8px}
.blockers{background:#fff8e6;border:1px solid #f0e0b0;border-radius:8px;padding:8px;margin-bottom:8px;font-size:12px}
.card.rejected .blockers{background:#fdecec;border-color:#f3c2c2}
.blockers .reason{margin-top:4px;color:#5a4a2a}
table.claims{width:100%;border-collapse:collapse;font-size:12px}
table.claims th{text-align:left;color:#7a8694;font-weight:600;border-bottom:1px solid #eef1f4;padding:3px 6px}
table.claims td{vertical-align:top;padding:3px 6px;border-bottom:1px solid #f3f5f7}
td.claim{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}
td.reason{color:#42505f}
td.quote{color:#76828f;font-style:italic}
.badge{display:inline-block;border-radius:999px;padding:1px 8px;font-size:11px;font-weight:600}
.badge.ok{background:#e3f6e8;color:#1d7a3a}.badge.bad{background:#fbe3e3;color:#b3261e}
.badge.warn{background:#fdf0d6;color:#9a6b00}.badge.muted{background:#eceff2;color:#5a6675}
.hidden{display:none}
"""

_JS = """
const buttons=document.querySelectorAll('[data-filter]');const cards=document.querySelectorAll('.card');
const search=document.getElementById('q');let filter='all';
function apply(){const q=search.value.trim().toLowerCase();cards.forEach(c=>{
 const okF=filter==='all'||c.dataset.decision===filter;
 const okQ=!q||c.dataset.id.includes(q)||c.textContent.toLowerCase().includes(q);
 c.classList.toggle('hidden',!(okF&&okQ));});}
buttons.forEach(b=>b.onclick=()=>{filter=b.dataset.filter;buttons.forEach(x=>x.classList.toggle('active',x===b));apply();});
search.oninput=apply;
"""


def build_html(data: dict) -> str:
    metrics = (data.get("benchmark") or {}).get("rule_metrics", {})
    buckets = [
        ("verified", data.get("verified", [])),
        ("review_needed", data.get("review", [])),
        ("rejected", data.get("rejected", [])),
    ]
    counts = " · ".join(f"{name}: {len(rules)}" for name, rules in buckets)
    cards = "".join(_card(rule, decision) for decision, rules in buckets for rule in rules)
    btns = "".join(
        f'<button data-filter="{f}"{" class=\"active\"" if f=="all" else ""}>{label}</button>'
        for f, label in [("all", "All"), ("verified", "Verified"), ("review_needed", "Review"), ("rejected", "Rejected")]
    )
    precision = metrics.get("verified_precision")
    recall = metrics.get("verified_gold_recall")
    sub = f"{counts}"
    if precision is not None:
        sub += f" &nbsp;|&nbsp; precision {precision} · recall {round(recall, 3) if recall else recall}"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(str(data.get('city','')))} {html.escape(str(data.get('zone','')))} — Proof Graph</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<header><h1>Verification Proof Graph — {html.escape(str(data.get('city','')))} {html.escape(str(data.get('zone','')))}</h1>"
        f"<div class='sub'>{sub}</div></header>"
        f"<div class='controls'>{btns}<input id='q' placeholder='Search rule id or text…'></div>"
        f"<div class='wrap'>{cards}</div>"
        f"<script>{_JS}</script></body></html>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args()
    out_dir = Path(args.output_dir).expanduser()

    def _load(name, default):
        path = out_dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    contract = _load("gis_rule_contract.json", {})
    data = {
        "city": contract.get("city", "Burnaby"),
        "zone": contract.get("zone", "R1"),
        "verified": _load("verified_rules.json", []),
        "review": _load("review_needed.json", []),
        "rejected": _load("rejected_rules.json", []),
        "benchmark": _load("benchmark_report.json", {}),
    }
    dest = out_dir / "proof_graph.html"
    dest.write_text(build_html(data), encoding="utf-8")
    print(
        f"[proof-graph] verified={len(data['verified'])} review={len(data['review'])} "
        f"rejected={len(data['rejected'])} -> {dest}"
    )


if __name__ == "__main__":
    main()
