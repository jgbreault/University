#!/usr/bin/env python3
"""Assemble a buildable-area envelope from the verified GIS/Felt export.

A read-only post-processing demo: it consumes ``gis_felt_export.json`` and routes
each verified constraint by its structured ``geometry.operation`` into an
envelope a GIS engine or notebook could draw — setback offsets per lot line,
height/storey caps per building role, coverage ratios, and parcel-level floors.

It computes nothing new and proves nothing about correctness; it simply shows
that the verified rules are now *executable* geometry rather than prose. Run it
after ``run_slim_verifier.py``.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "outputs" / "burnaby_r1_slim_pipeline5_registry"


def build_envelope(export: dict) -> dict:
    setbacks: dict[str, list] = defaultdict(list)
    height: dict[str, list] = defaultdict(list)
    storeys: dict[str, list] = defaultdict(list)
    separations: list = []
    coverage: list = []
    impervious: list = []
    # Parcel-level entries are LISTS, like the setback branch: a single-slot
    # dict silently dropped conditional variants (e.g. the base 281 m² floor
    # area cap and its '4 Units Only' variant are both verified rules).
    parcel: dict[str, list] = defaultdict(list)
    context: list = []

    for c in export.get("constraints", []):
        geometry = c.get("geometry") or {}
        op = geometry.get("operation")
        role = c.get("applies_to") or "all"
        item = {
            "rule_id": c.get("constraint_id"),
            "value_numeric": c.get("value_numeric"),
            "unit": c.get("unit"),
            "operator": c.get("operator"),
            "condition": c.get("condition") or None,
            "applies_to": c.get("applies_to") or None,
        }
        if op == "offset_inward":
            setbacks[geometry.get("axis") or "unknown_lot_line"].append(item)
        elif op == "extrude_z":
            height[role].append(item)
        elif op == "storey_count_cap":
            storeys[role].append(item)
        elif op == "min_separation":
            separations.append(item)
        elif op == "footprint_ratio_cap":
            coverage.append(item)
        elif op == "surface_ratio_cap":
            impervious.append(item)
        elif op == "area_floor":
            parcel["min_lot_area"].append(item)
        elif op == "unit_count_cap":
            parcel["max_dwelling_units"].append(item)
        else:  # clearance / trigger_predicate / use_permission
            context.append({**item, "operation": op})

    return {
        "city": export.get("city"),
        "zone": export.get("zone"),
        "source_document": export.get("source_document"),
        "derived_from": "gis_felt_export.json (verified-only)",
        "lot_line_setbacks_m": dict(sorted(setbacks.items())),
        "max_height_m_by_role": dict(sorted(height.items())),
        "max_storeys_by_role": dict(sorted(storeys.items())),
        "building_separations_m": separations,
        "max_lot_coverage_pct": coverage,
        "max_impervious_surface_pct": impervious,
        "parcel_level": dict(sorted(parcel.items())),
        "context_and_triggers": context,
        "notes": [
            "Read-only projection of verified rules; not a verification artifact.",
            "Setbacks are keyed by lot line; multiple entries reflect conditional variants (e.g. end-unit, accessory).",
            "Heights/storeys are grouped by building role; roof-type condition is preserved, not collapsed.",
            "Parcel-level entries are lists so conditional variants (e.g. a '4 Units Only' lot-area floor) are kept alongside the base rule.",
        ],
    }


def _summary_lines(env: dict) -> list[str]:
    lines = [f"# Buildable envelope — {env.get('city')} {env.get('zone')}", ""]
    lines.append("Lot-line setbacks (m):")
    for axis, items in env["lot_line_setbacks_m"].items():
        vals = ", ".join(f"{i['value_numeric']}{' ('+i['condition']+')' if i['condition'] else ''}" for i in items)
        lines.append(f"  - {axis}: {vals}")
    lines.append("Max height (m) by role:")
    for role, items in env["max_height_m_by_role"].items():
        vals = ", ".join(f"{i['value_numeric']}{' ('+i['condition']+')' if i['condition'] else ''}" for i in items)
        lines.append(f"  - {role}: {vals}")
    if env["parcel_level"]:
        lines.append("Parcel-level:")
        for k, items in env["parcel_level"].items():
            vals = ", ".join(
                f"{i['value_numeric']} {i['unit']}{' ('+i['condition']+')' if i['condition'] else ''}"
                for i in items
            )
            lines.append(f"  - {k}: {vals}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args()
    out_dir = Path(args.output_dir).expanduser()
    export = json.loads((out_dir / "gis_felt_export.json").read_text(encoding="utf-8"))
    envelope = build_envelope(export)
    dest = out_dir / "buildable_envelope.json"
    dest.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n".join(_summary_lines(envelope)))
    print(f"\nWrote {dest}")


if __name__ == "__main__":
    main()
