#!/usr/bin/env python3
"""Held-out evaluation: how much does Burnaby's recall depend on its tuning?

NOTE: despite the twin name, this is the WITHIN-CITY Burnaby ablation
(leave-one-family-out + core-only tuning removal); the cross-city transfer
test lives in scripts/run_vancouver_holdout.py.

The headline benchmark is measured on the same Burnaby R1 rules the config was
authored for, so it cannot tell you whether the method GENERALIZES. This script
gives an honest signal for the GIS handoff by re-running the verifier with
Burnaby-specific tuning removed and reporting recall/precision:

  * leave-one-family-out (LOFO): for each rule family, that family's hand-written
    table-scope patterns are removed, isolating whether the family still verifies
    without them;
  * core-only: ALL Burnaby tuning removed (no scope patterns, no normalization
    hints), leaving only the city-agnostic structural verifier + general gates.

Precision holding while recall stays high shows the structural approach -- not an
answer key -- is doing the work. A recall drop quantifies the tuning dependence.
Run `python3 scripts/run_slim_verifier.py --city burnaby_r1` first to produce the
adapted inputs this script reuses.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "benchmark"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from burnaby_prototype.config import resolve_city_paths
from burnaby_prototype.config import load_config
from burnaby_prototype.slim_pipeline import run_slim_verification
from evaluate_benchmark import evaluate_rule_outputs  # type: ignore


def _read(path: Path, default: Any) -> Any:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _run(config_dict: dict, evidence: list, candidates: list, gold: list) -> dict:
    """Run verification with a given config and evaluate against the full gold."""
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp) / "out"
        # run_slim_verification accepts the ablated dict directly; no need to
        # round-trip each variant through a temp config file.
        run_slim_verification(
            config_path=config_dict,
            output_dir=out,
            evidence_units=evidence,
            rule_candidates=candidates,
            input_mode="holdout",
        )
        return evaluate_rule_outputs(
            gold_rules=gold,
            evidence_units=evidence,
            candidates=candidates,
            verified_rules=_read(out / "verified_rules.json", []),
            review_rules=_read(out / "review_needed.json", []),
            rejected_rules=_read(out / "rejected_rules.json", []),
            not_used_rules=_read(out / "not_used.json", []),
            retrieval={},
        )


def _family_recall(metrics: dict, gold: list, family: str) -> tuple[int, int]:
    """Return (verified_gold, total_gold) for one family from a full-gold run."""
    missed = set(metrics.get("missed_verified_gold_rule_ids", []))
    fam_gold = [g for g in gold if str(g.get("rule_object")) == family]
    verified = [g for g in fam_gold if g.get("gold_id") not in missed]
    return len(verified), len(fam_gold)


def _pattern_targets_family(pattern: dict, family: str) -> bool:
    rule_objects = pattern.get("rule_objects") or pattern.get("rule_object")
    if isinstance(rule_objects, str):
        rule_objects = [rule_objects]
    return family in {str(item) for item in (rule_objects or [])}


def main() -> None:
    city = resolve_city_paths(ROOT, "burnaby_r1")
    config = load_config(city.config)
    gold = _read(city.gold_rules, [])
    evidence = _read(city.output_dir / "evidence_units.json", [])
    candidates = _read(city.output_dir / "rule_candidates.json", [])
    if not evidence or not candidates:
        raise SystemExit(
            "Missing adapted inputs. Run `python3 scripts/run_slim_verifier.py --city burnaby_r1` first."
        )

    families = sorted({str(g.get("rule_object")) for g in gold})
    patterns = config.get("verification", {}).get("structured_table_scope_patterns", [])

    print("=== HELD-OUT EVALUATION (honest generalization signal) ===\n")

    base = _run(config, evidence, candidates, gold)
    print("In-domain baseline (full tuned config):")
    print(
        f"  ALL families         recall={base['verified_gold_recall']:.2f}  "
        f"precision={base['verified_precision']:.2f}  false_verified={base['false_verified_count']}\n"
    )

    print("Leave-one-family-out (that family's table-scope patterns removed):")
    for family in families:
        cfg = copy.deepcopy(config)
        cfg["verification"]["structured_table_scope_patterns"] = [
            p for p in patterns if not _pattern_targets_family(p, family)
        ]
        metrics = _run(cfg, evidence, candidates, gold)
        verified, total = _family_recall(metrics, gold, family)
        rate = verified / total if total else 0.0
        print(
            f"  {family:<20} family_recall={verified}/{total} ({rate:.2f})  "
            f"overall_precision={metrics['verified_precision']:.2f}  false_verified={metrics['false_verified_count']}"
        )

    print("\nCore-only (ALL Burnaby tuning removed: no scope patterns, no normalization hints):")
    core = copy.deepcopy(config)
    core["verification"]["structured_table_scope_patterns"] = []
    core["verification"]["table_scope_pattern_mode"] = "deny_ambiguous"
    # EXPLICIT EMPTY LISTS, not `del core["normalization"]`: get_normalization()
    # falls back to the hard-coded Burnaby DEFAULT_NORMALIZATION whenever the
    # block is missing or falsy, so deleting the key would silently re-enable
    # Burnaby vocabulary and invalidate the "no normalization hints" ablation.
    core["normalization"] = {key: [] for key in (
        "applies_to_hints", "scope_hints", "distance_rewrites", "range_rewrites",
        "condition_defaults", "generic_applies_to_extra_words", "non_material_condition_words",
        "unit_rewrites", "material_condition_cue_extras",
    )}
    # rule_object_text_cue_extras is a dict-of-lists, not a list.
    core["normalization"]["rule_object_text_cue_extras"] = {}
    core_metrics = _run(core, evidence, candidates, gold)
    print(
        f"  ALL families         recall={core_metrics['verified_gold_recall']:.2f}  "
        f"precision={core_metrics['verified_precision']:.2f}  false_verified={core_metrics['false_verified_count']}"
    )
    for family in families:
        verified, total = _family_recall(core_metrics, gold, family)
        rate = verified / total if total else 0.0
        print(f"    {family:<18} family_recall={verified}/{total} ({rate:.2f})")

    print(
        "\nReading: recall that holds without a family's patterns shows the verifier is not\n"
        "relying on a per-rule answer key. Precision stays 1.00 for families whose patterns\n"
        "are pure answer-key (most of them); the one exception is `setback`, whose patterns\n"
        "include two `action:\"review\"` SAFETY quarantines (degraded duplicates) -- removing\n"
        "those, as LOFO does, correctly lets the duplicates back in and drops setback precision,\n"
        "which is itself evidence the quarantines are load-bearing, not answer-key tuning.\n"
        "The core-only row is the city-agnostic floor (no patterns, no normalization)."
    )


if __name__ == "__main__":
    main()
