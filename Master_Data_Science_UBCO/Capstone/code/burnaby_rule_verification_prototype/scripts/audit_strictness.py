#!/usr/bin/env python3
"""Calibrated strictness audit (read-only).

For every review/rejected rule across the given cities, classify each support
gap into one of three bins:

* ``cue_lexicon_miss`` — the cited evidence DOES state the semantics, in
  wording our lexicons don't list (a recall-safe loosening candidate);
* ``policy_gate`` — held by a deliberate per-city policy (text contract,
  consensus requirement), i.e. a config decision, not a matcher gap;
* ``genuine_evidence_gap`` — the evidence really does not state the claim
  (the strictness is load-bearing; loosening would risk precision).

The output (`strictness_audit.md` per city + stdout summary) ranks loosening
candidates by how many rules they would help, so strictness changes are
measured, not guessed. This script never modifies anything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.domain_schema import to_float, token_visible

# Candidate operator synonyms NOT currently in the lexicons. The audit counts
# real-evidence occurrences; only phrases that actually occur (and survive a
# paired negative test) graduate into support_checks/text_span_proof/
# table_natural_logic.
MAX_SYNONYM_CANDIDATES = (
    "no more than",
    "may not exceed",
    "not greater than",
    "no greater than",
    "a maximum of",
    "not to exceed",
    "cannot exceed",
    "must not be more than",
)
MIN_SYNONYM_CANDIDATES = (
    "a minimum of",
    "no fewer than",
    "not fewer than",
    "must be at least",
    "or more",
    "or greater",
)
MAX_CURRENT = ("maximum", "not exceed", "up to", "limited to")
MIN_CURRENT = ("minimum", "not less", "not be less", "nor be less", "no less", "at least", "shall have")

POLICY_GAPS = {
    "pipeline5_text_candidate_requires_review",
    "outside_current_rule_contract",
    "table_cell_candidate_requires_review",
    "table_evidence_candidate_requires_review",
    "table_fallback_candidate_requires_review",
}


def _rule_text_blob(rule: dict) -> str:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    return " ".join(
        str(source.get(key) or "")
        for key in ("evidence_text", "source_context", "table_title", "row_header", "column_header", "cell_value")
    ).lower()


def _numeric_equivalence_would_fix(rule: dict, blob: str) -> str | None:
    """Would float-equality find the value where boundary matching failed?"""
    value = rule.get("value")
    target = to_float(value)
    if target is None:
        return None
    if token_visible(blob.replace(",", ""), str(value)):
        return None  # boundary matching already finds it; gap came from elsewhere
    for number in re.findall(r"\d+(?:\.\d+)?", blob.replace(",", "")):
        parsed = to_float(number)
        if parsed is not None and parsed == target and str(number) != str(value):
            return f"float-equal spelling '{number}' for value '{value}'"
    return None


def _operator_synonym_would_fix(rule: dict, blob: str) -> str | None:
    operator = str(rule.get("operator") or "")
    if operator in {"<=", "max", "maximum", "not_exceed", "≤"}:
        current, candidates = MAX_CURRENT, MAX_SYNONYM_CANDIDATES
    elif operator in {">=", "min", "minimum", "at_least", "≥"}:
        current, candidates = MIN_CURRENT, MIN_SYNONYM_CANDIDATES
    else:
        return None
    if any(phrase in blob for phrase in current):
        return None  # lexicon already matches; gap came from window narrowing etc.
    for phrase in candidates:
        if phrase in blob:
            return f"unlisted synonym '{phrase}'"
    return None


def audit_city(city: str) -> dict:
    out_dir = ROOT / "outputs" / f"{city}_slim_pipeline5_registry"
    rows: list[dict] = []
    for bucket in ("review_needed", "rejected_rules"):
        path = out_dir / f"{bucket}.json"
        if not path.exists():
            continue
        for rule in json.loads(path.read_text(encoding="utf-8")):
            blob = _rule_text_blob(rule)
            for gap in rule.get("support_gaps", []):
                finding = {
                    "city": city,
                    "bucket": bucket,
                    "rule_id": rule.get("rule_id"),
                    "rule_object": rule.get("rule_object"),
                    "gap": gap,
                    "classification": "genuine_evidence_gap",
                    "detail": "",
                }
                if gap in POLICY_GAPS:
                    finding["classification"] = "policy_gate"
                elif gap == "value_not_found_in_evidence":
                    hit = _numeric_equivalence_would_fix(rule, blob)
                    if hit:
                        finding["classification"] = "cue_lexicon_miss"
                        finding["detail"] = hit
                elif gap == "operator_not_supported":
                    hit = _operator_synonym_would_fix(rule, blob)
                    if hit:
                        finding["classification"] = "cue_lexicon_miss"
                        finding["detail"] = hit
                rows.append(finding)
    return {"city": city, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="+", default=["burnaby_r1", "vancouver_rs"])
    args = parser.parse_args()

    all_rows: list[dict] = []
    for city in args.cities:
        all_rows.extend(audit_city(city)["rows"])

    by_class = Counter(row["classification"] for row in all_rows)
    by_gap = Counter(row["gap"] for row in all_rows)
    misses = [row for row in all_rows if row["classification"] == "cue_lexicon_miss"]
    miss_details = Counter(row["detail"] for row in misses)
    policy_by_family: dict[str, Counter] = defaultdict(Counter)
    for row in all_rows:
        if row["classification"] == "policy_gate":
            policy_by_family[row["city"]][row["rule_object"]] += 1

    lines = [
        "# Strictness Audit",
        "",
        "Read-only classification of every support gap on review/rejected rules.",
        "Loosenings are implemented ONLY for `cue_lexicon_miss` findings, each",
        "with a paired negative test; `policy_gate` items are per-city config",
        "decisions; `genuine_evidence_gap` strictness is load-bearing.",
        "",
        f"Cities: {', '.join(args.cities)}  |  gap occurrences: {len(all_rows)}",
        "",
        "## Classification totals",
        "",
    ]
    for name, count in by_class.most_common():
        lines.append(f"- {name}: {count}")
    lines += ["", "## Gap histogram", ""]
    for name, count in by_gap.most_common():
        lines.append(f"- {name}: {count}")
    lines += ["", "## Cue-lexicon misses (the actionable surface)", ""]
    if miss_details:
        for detail, count in miss_details.most_common():
            lines.append(f"- {count}x {detail}")
        lines += ["", "Affected rules:", ""]
        for row in misses:
            lines.append(f"- {row['city']} {row['rule_id']} ({row['rule_object']}, {row['gap']}): {row['detail']}")
    else:
        lines.append("- none found: every lexicon already covers the wording that occurs in evidence")
    lines += ["", "## Policy-gated volume by family (config decisions, not matcher gaps)", ""]
    for city, counter in policy_by_family.items():
        for family, count in counter.most_common():
            lines.append(f"- {city}: {family} x{count}")

    # Rules held ONLY by the text-gate policy with every deterministic support
    # check already passing: the population a single config line
    # (single_source_text_rule_contract) could verify. Reported for a HUMAN
    # decision per city — this script changes nothing.
    lines += ["", "## Fully-proven rules held only by the text-gate policy", ""]
    for city in args.cities:
        out_dir = ROOT / "outputs" / f"{city}_slim_pipeline5_registry"
        path = out_dir / "review_needed.json"
        if not path.exists():
            continue
        promotable = Counter()
        examples: dict[str, list[str]] = defaultdict(list)
        for rule in json.loads(path.read_text(encoding="utf-8")):
            gaps = set(rule.get("support_gaps", []))
            checks = rule.get("support_checks", {})
            if gaps == {"pipeline5_text_candidate_requires_review"} and all(checks.values()):
                family = str(rule.get("rule_object"))
                promotable[family] += 1
                examples[family].append(str(rule.get("rule_id")))
        if promotable:
            for family, count in promotable.most_common():
                lines.append(f"- {city}: {family} x{count} ({', '.join(examples[family][:4])})")
        else:
            lines.append(f"- {city}: none — every policy-held rule also has at least one failed check")
    lines += [
        "",
        "## What stays strict (load-bearing, out of scope by design)",
        "",
        "- digit-boundary value matching ('5' must never match inside '7.5')",
        "- unit compatibility (the %-exclusion trap for floor_area)",
        "- direction refutation and exception/covenant blockers",
        "- single-source bundle guards (operator grounded in the value member)",
        "",
        "Each of the above caught a live failure; loosening them trades the",
        "false_verified = 0 guarantee for recall, which this project refuses.",
    ]

    report = "\n".join(lines) + "\n"
    out_path = ROOT / "outputs" / "strictness_audit.md"
    out_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"[audit] written to {out_path}")


if __name__ == "__main__":
    main()
