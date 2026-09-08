#!/usr/bin/env python3
"""A/B test: run ONLY the two downgrade-candidate stages on a cheap Flash model
and compare quality against the pro baseline (outputs/burnaby).

- TEXT test:   re-run text rule extraction with FLASH, reusing the pro visual
               blocks and the pro (cached) table rules, so only the text stream
               changes. Output -> outputs/burnaby_flash_text/.
- LAYOUT test: re-run the visual split (page-image layout + transcription) with
               FLASH. Output -> outputs/burnaby_flash_layout/.

The pro baseline is never touched. Requires GEMINI_API_KEY in the environment.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
from argparse import Namespace
from pathlib import Path

P7 = Path(__file__).resolve().parent
P5 = P7.parent / "prototype_pipeline_5"
sys.path.insert(0, str(P5))

from gemini_visual_block_extractor import process_pdf  # noqa: E402
from visual_blocks_rule_extractor import (  # noqa: E402
    process_extraction, read_jsonl, clean, operator_direction_conflict,
)
from pipeline7_runner import DEFAULT_PDF  # noqa: E402

PRO = P7 / "outputs" / "burnaby"
PRO_VIS = PRO / "03_visual_blocks"
PRO_RULES = PRO / "04_rule_extraction"
PRO_MODEL = "gemini-3.1-pro-preview"
FLASH = os.environ.get("FLASH_MODEL", "gemini-3.5-flash")


def sig(r: dict) -> tuple:
    return (clean(r.get("rule_object")).lower(), clean(r.get("subject")).lower(),
            clean(r.get("operator")).lower(), clean(r.get("value")).lower(),
            clean(r.get("unit")).lower())


def model_tag(model: str) -> str:
    return model.replace("gemini-", "").replace(".", "").replace("-", "")


def run_text_test() -> Path:
    out = P7 / "outputs" / f"burnaby_text_{model_tag(FLASH)}" / "04_rule_extraction"
    raw = out / "api_raw"
    raw.mkdir(parents=True, exist_ok=True)
    # Reuse pro's cached TABLE responses so table calls hit cache (stay pro);
    # leave text uncached so it actually fires on FLASH.
    for f in glob.glob(str(PRO_RULES / "api_raw" / "page_*table*")):
        shutil.copy(f, raw / Path(f).name)
    process_extraction(Namespace(
        visual_blocks_dir=PRO_VIS, output_dir=out, model=PRO_MODEL,
        text_model=FLASH, table_model=PRO_MODEL, api_key_env="GEMINI_API_KEY",
        timeout=300, max_retries=3, retry_base_seconds=20, overwrite=False))
    return out


def run_layout_test() -> Path:
    out = P7 / "outputs" / f"burnaby_layout_{model_tag(FLASH)}" / "03_visual_blocks"
    process_pdf(Namespace(
        pdf=Path(DEFAULT_PDF), output_dir=out, model=FLASH,
        api_key_env="GEMINI_API_KEY", pages=None, scale=3.0, layout_scale=2.0,
        skip_empty_pages=True, crop_padding_points=6.0, timeout=300,
        max_retries=3, retry_base_seconds=20, overwrite=False))
    return out


def _eqnorm(op: str) -> str:
    op = clean(op).lower()
    return "=" if op == "==" else op


def _numeric_dir_map(rules):
    """value+unit -> set of direction operators (>=,<=,= ) for numeric rules."""
    out = {}
    for r in rules:
        v = clean(r.get("value"))
        if v and any(ch.isdigit() for ch in v):
            out.setdefault((v, clean(r.get("unit"))), set()).add(_eqnorm(r.get("operator")))
    return out


def compare_text(flash_dir: Path) -> None:
    pro = json.load(open(PRO_RULES / "text_rules_raw.json", encoding="utf-8"))
    fl = json.load(open(flash_dir / "text_rules_raw.json", encoding="utf-8"))
    pro_sig, fl_sig = {sig(r) for r in pro}, {sig(r) for r in fl}
    reproduced = pro_sig & fl_sig
    print("\n" + "=" * 74)
    print(f"TEXT extraction:  PRO ({PRO_MODEL})  vs  FLASH ({FLASH})")
    print("=" * 74)
    print(f"  pro text rules            : {len(pro)}")
    print(f"  flash text rules          : {len(fl)}")
    print(f"  pro rules reproduced      : {len(reproduced)}/{len(pro_sig)} "
          f"({len(reproduced)/len(pro_sig)*100:.0f}% recall of pro rules)")
    print(f"  flash-only (new/changed)  : {len(fl_sig - pro_sig)}")
    print(f"  pro-only (missed by flash): {len(pro_sig - fl_sig)}")

    # --- operator-direction agreement on shared value+unit (the key fix metric) ---
    pm, fm = _numeric_dir_map(pro), _numeric_dir_map(fl)
    shared = sorted(set(pm) & set(fm))
    agree = mism = 0
    mism_rows = []
    for k in shared:
        if pm[k] & fm[k]:
            agree += 1
        else:
            mism += 1
            mism_rows.append((k, pm[k], fm[k]))
    print("  --- operator DIRECTION on shared value+unit (==/= treated same) ---")
    den = agree + mism
    print(f"    direction agreement     : {agree}/{den} "
          f"({agree/den*100:.0f}%)" if den else "    (no shared numeric values)")
    for k, po, fo in mism_rows:
        print(f"      {k[0]} {k[1]}: pro={sorted(po)} flash={sorted(fo)}")

    # --- residual flash errors the extended gate guard now catches ---
    flagged = [r for r in fl if operator_direction_conflict(r)]
    print(f"  --- extended gate guard catches {len(flagged)} flash rule(s) -> routed to review ---")
    for r in flagged:
        print(f"      op={clean(r.get('operator')) or 'EMPTY':6s} val={clean(r.get('value'))[:8]:8s} "
              f"evid='{clean(r.get('evidence_text'))[:50]}'")


def compare_layout(flash_dir: Path) -> None:
    pro = json.load(open(PRO_VIS / "summary.json", encoding="utf-8"))
    fl = json.load(open(flash_dir / "summary.json", encoding="utf-8"))
    pro_blocks = read_jsonl(PRO_VIS / "text_blocks.jsonl")
    fl_blocks = read_jsonl(flash_dir / "text_blocks.jsonl")
    pro_chars = sum(len(b.get("text", "")) for b in pro_blocks)
    fl_chars = sum(len(b.get("text", "")) for b in fl_blocks)
    print("\n" + "=" * 74)
    print(f"LAYOUT / visual split:  PRO ({PRO_MODEL})  vs  FLASH ({FLASH})")
    print("=" * 74)
    print(f"  text_block_count  pro={pro.get('text_block_count')}  flash={fl.get('text_block_count')}")
    print(f"  table_region_count pro={pro.get('table_region_count')}  flash={fl.get('table_region_count')}")
    print(f"  transcribed chars  pro={pro_chars}  flash={fl_chars}  "
          f"({fl_chars/pro_chars*100:.0f}% of pro)")
    print("  --- per-page (text_blocks / table_regions) ---")
    pr = {p["page_number"]: p for p in pro.get("page_reports", [])}
    fr = {p["page_number"]: p for p in fl.get("page_reports", [])}
    for pg in sorted(set(pr) | set(fr)):
        a, b = pr.get(pg, {}), fr.get(pg, {})
        flag = "" if (a.get("table_region_count") == b.get("table_region_count")) else "  <-- TABLE COUNT DIFF"
        print(f"    p{pg}: pro {a.get('text_block_count','-')}/{a.get('table_region_count','-')}"
              f"   flash {b.get('text_block_count','-')}/{b.get('table_region_count','-')}{flag}")


def main() -> None:
    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY not set")
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    print(f"FLASH model = {FLASH}")
    if which in ("text", "both"):
        compare_text(run_text_test())
    if which in ("layout", "both"):
        compare_layout(run_layout_test())


if __name__ == "__main__":
    main()
