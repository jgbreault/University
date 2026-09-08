#!/usr/bin/env python3
"""Delta-debugging evidence minimization (ddmin) — explainability tooling.

For a chosen rule, shrink its cited evidence text to a MINIMAL fragment that
still produces the same verification decision: "the decision hinges on exactly
these words." Classic software-engineering reduction (Zeller's ddmin) applied
to legal evidence. Read-only with respect to the verifier — it calls
``verify_candidates`` as an oracle and never changes any decision artifact
except the optional ``decisive_spans.json`` report it writes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config
from burnaby_prototype.verification import verify_candidates


# Every text-bearing evidence field participates in minimization: for TABLE
# evidence the decision usually rests on the structured fields (title/row/
# cell), not the flat text — minimizing only evidence_text would "remove"
# words the table proof never needed and report nonsense.
_TEXT_FIELDS = ("table_title", "row_header", "column_header", "cell_value", "evidence_text", "source_context")


def _decision_with(config: dict, evidence: dict, candidate: dict, fields: dict[str, str]) -> str:
    probe = {**evidence, **{name: fields.get(name, "") for name in _TEXT_FIELDS}}
    result = verify_candidates(config, [probe], [candidate])
    pool = [*result["verified_rules"], *result["review_needed"]]
    return str(pool[0].get("verification_decision")) if pool else "missing"


def _decision_for(config: dict, evidence: dict, candidate: dict, text: str) -> str:
    """Clause-evidence probe used by tests: minimize over the flat text only."""
    fields = {name: str(evidence.get(name) or "") for name in _TEXT_FIELDS}
    fields["evidence_text"] = text
    fields["source_context"] = text
    return _decision_with(config, evidence, candidate, fields)


def _split(parts_text: str, level: int) -> list[str]:
    """Coarse-to-fine splitting: clause separators first, then words."""
    if level == 0:
        pieces = re.split(r"(?<=[.;|])\s+", parts_text)
    else:
        pieces = parts_text.split()
    return [piece for piece in pieces if piece.strip()]


def minimize_evidence(config: dict, evidence: dict, candidate: dict) -> dict:
    """Return the minimal evidence (fields + words) preserving the decision."""
    fields = {name: str(evidence.get(name) or "") for name in _TEXT_FIELDS}
    target = _decision_with(config, evidence, candidate, fields)

    # Pass 1 — FIELD-level ddmin: which evidence fields are load-bearing?
    for name in _TEXT_FIELDS:
        if not fields[name]:
            continue
        trial = {**fields, name: ""}
        if _decision_with(config, evidence, candidate, trial) == target:
            fields = trial

    # Pass 2 — word/clause-level ddmin inside each surviving text field.
    for name in _TEXT_FIELDS:
        current = fields[name]
        if not current:
            continue
        for level in (0, 1):  # sentences/clauses first, then word granularity
            parts = _split(current, level)
            if len(parts) < 2:
                continue
            changed = True
            while changed:
                changed = False
                for index in range(len(parts) - 1, -1, -1):
                    trial_parts = parts[:index] + parts[index + 1 :]
                    trial = {**fields, name: " ".join(trial_parts)}
                    if trial_parts and _decision_with(config, evidence, candidate, trial) == target:
                        parts = trial_parts
                        changed = True
            current = " ".join(parts)
        fields[name] = current

    surviving = {name: text for name, text in fields.items() if text}
    original_total = sum(len(str(evidence.get(name) or "")) for name in _TEXT_FIELDS)
    return {
        "rule_id": candidate.get("rule_id") or candidate.get("candidate_id"),
        "decision": target,
        "original_length": original_total,
        "minimal_length": sum(len(text) for text in surviving.values()),
        "decisive_fields": surviving,
        "decisive_span": " | ".join(f"{name}: {text}" for name, text in surviving.items()),
        "note": "Minimal evidence fields+words that still yield the same verification decision (ddmin).",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="burnaby_r1")
    parser.add_argument("--rule-id", required=True)
    args = parser.parse_args()

    config = load_config(ROOT / "configs" / f"{args.city}.json")
    out_dir = ROOT / "outputs" / f"{args.city}_slim_pipeline5_registry"
    evidence_by_id = {
        unit["evidence_id"]: unit
        for unit in json.loads((out_dir / "evidence_units.json").read_text(encoding="utf-8"))
    }
    rule = None
    for bucket in ("verified_rules", "review_needed", "rejected_rules", "not_used"):
        for row in json.loads((out_dir / f"{bucket}.json").read_text(encoding="utf-8")):
            if row.get("rule_id") == args.rule_id:
                rule = row
                break
        if rule:
            break
    if rule is None:
        raise SystemExit(f"rule {args.rule_id} not found in {out_dir}")

    candidate = dict(rule.get("candidate") or {})
    candidate.setdefault("rule_id", rule.get("rule_id"))
    evidence = evidence_by_id.get(str(candidate.get("evidence_id") or ""))
    if evidence is None:
        raise SystemExit(f"evidence {candidate.get('evidence_id')} not found (bundle-promoted rules use synthetic evidence)")

    result = minimize_evidence(config, evidence, candidate)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    report_path = out_dir / "decisive_spans.json"
    existing = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    existing[str(result["rule_id"])] = result
    report_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[ddmin] recorded in {report_path}")


if __name__ == "__main__":
    main()
