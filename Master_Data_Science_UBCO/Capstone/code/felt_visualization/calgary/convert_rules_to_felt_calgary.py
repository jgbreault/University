import json
import csv
from pathlib import Path

ROOT   = Path(__file__).resolve().parents[3]
INPUT  = ROOT / "code/burnaby_rule_verification_prototype/outputs/m7_runs/calgary_rcg/google_gemini_3_1_flash_lite/gis_rule_contract.json"
OUTPUT = Path(__file__).parent / "calgary_rcg_rules.csv"

with open(INPUT, encoding="utf-8") as f:
    contract = json.load(f)

def make_description(rule):
    ctype   = rule.get("constraint_type", "")
    obj     = rule.get("rule_object", "")
    applies = rule.get("applies_to", "")
    parts   = [p for p in [ctype.capitalize(), obj, f"({applies})" if applies else ""] if p]
    return " ".join(parts)

rows = []
for rule in contract.get("rules", []):
    try:
        val = float(rule.get("value", 0))
    except (TypeError, ValueError):
        val = rule.get("value", "")

    citation = rule.get("citation", {}) or {}
    rows.append({
        "rule_id":       rule.get("rule_id", ""),
        "rule_key":      rule.get("canonical_rule_key") or rule.get("rule_object", ""),
        "zone_code":     contract.get("zone", ""),
        "municipality":  contract.get("city", ""),
        "rule_object":   rule.get("rule_object", ""),
        "applies_to":    rule.get("applies_to") or "all",
        "operator":      rule.get("operator", ""),
        "value":         val,
        "unit":          rule.get("unit", ""),
        "condition":     rule.get("condition") or "",
        "exception":     rule.get("exception") or "",
        "description":   make_description(rule),
        "bylaw_ref":     citation.get("document") or "",
        "source_page":   citation.get("page", ""),
        "source_url":    citation.get("url", "") or contract.get("source_url", ""),
    })

fieldnames = list(rows[0].keys())
with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"Done — {len(rows)} rules written to {OUTPUT}")
