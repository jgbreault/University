"""M7 CI safety gates.

Two release-blocking guards that fail CI if the committed product artifacts
drift away from a safe state. Neither test calls an LLM or relaxes a verifier
gate; they read or deterministically re-project the committed run outputs.

1. ``test_burnaby_proposal_false_approval_is_zero`` — the proposal benchmark
   must never approve a proposal that should not be approved. A non-zero
   ``false_approval_count`` is the single most dangerous failure mode for a
   permitting tool, so we assert it stays 0 for Burnaby straight from the
   committed ``benchmark_report.json`` proposal metrics.

2. ``test_gis_contract_and_felt_export_match_fresh_regen`` — the committed
   ``gis_rule_contract.json`` and ``gis_felt_export.json`` for every city are a
   pure deterministic projection of the committed ``verified_rules.json`` (plus
   the review/not-used buckets and the city config). We regenerate them in
   memory and require an EXACT match. This is a drift guard: if anyone edits a
   GIS-facing export by hand, swaps in stale rules, or changes the projection
   without regenerating, this fails loudly. Because the inputs are the committed
   verified rules, the regen also pins the verified-rule legal identities.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from burnaby_prototype.gis_felt_export import (  # noqa: E402
    build_gis_felt_export,
    validate_gis_felt_export,
)
from burnaby_prototype.slim_pipeline import (  # noqa: E402
    GIS_CONTRACT_SCHEMA_VERSION,
    deduplicate_verified_rules_for_export,
    project_gis_contract_rule,
    validate_gis_contract,
)

CITIES = ("burnaby_r1", "calgary_rcg", "vancouver_rs")
RUNS_ROOT = ROOT / "outputs" / "m7_runs"
# M7 product model, with the pre-M7 model kept as a fallback for any city whose
# 3.1 run has not been committed yet.
MODEL_PREFERENCE = ("google_gemini_3_1_flash_lite", "google_gemini_2_5_flash_lite")


def _run_dir(city: str) -> Path:
    for model in MODEL_PREFERENCE:
        candidate = RUNS_ROOT / city / model
        if (candidate / "gis_rule_contract.json").exists():
            return candidate
    raise AssertionError(
        f"No committed gis_rule_contract.json for {city} under any known model dir"
    )


def _load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class BurnabyProposalSafetyGate(unittest.TestCase):
    """The Burnaby proposal benchmark must never produce a false approval."""

    def test_burnaby_proposal_false_approval_is_zero(self) -> None:
        report_path = _run_dir("burnaby_r1") / "benchmark_report.json"
        self.assertTrue(
            report_path.exists(),
            f"missing committed benchmark report: {report_path}",
        )
        report = _load(report_path)
        proposal = report.get("proposal_metrics", {})

        self.assertGreater(
            proposal.get("proposal_case_count", 0),
            0,
            "Burnaby benchmark report has no proposal cases scored",
        )
        self.assertEqual(
            proposal.get("false_approval_count"),
            0,
            f"Burnaby proposal false_approval_count must be 0, "
            f"got {proposal.get('false_approval_count')} "
            f"(cases: {proposal.get('false_approval_cases')})",
        )
        # Decision accuracy 1.0 is the corollary: every decision matched gold,
        # so the zero false-approval count is real, not an empty-denominator
        # artifact.
        self.assertEqual(
            proposal.get("proposal_decision_accuracy"),
            1.0,
            "Burnaby proposal_decision_accuracy must be 1.0",
        )


class GisExportDriftGuard(unittest.TestCase):
    """Committed GIS-facing exports must match a fresh deterministic regen."""

    def _regen_contract(self, run_dir: Path, config: dict, committed: dict) -> dict:
        verified = _load(run_dir / "verified_rules.json")
        export_rules, dedup = deduplicate_verified_rules_for_export(verified)
        contract = {
            "city": config["city"],
            "zone": config["zone"],
            "source_document": config.get("source_document"),
            "source_url": config.get("source_url"),
            # input_mode is a pipeline run parameter, not a verified-rule
            # property, so it is taken from the committed artifact rather than
            # re-derived.
            "input_mode": committed.get("input_mode"),
            "schema_version": GIS_CONTRACT_SCHEMA_VERSION,
            "deduplication": dedup,
            "rules": [project_gis_contract_rule(rule) for rule in export_rules],
        }
        validate_gis_contract(contract)
        return contract

    def _regen_felt(self, run_dir: Path, config: dict, committed: dict) -> dict:
        verified = _load(run_dir / "verified_rules.json")
        review = _load(run_dir / "review_needed.json")
        not_used = _load(run_dir / "not_used.json")
        export_rules, _ = deduplicate_verified_rules_for_export(verified)
        felt = build_gis_felt_export(export_rules, review, not_used, config)
        felt["input_mode"] = committed.get("input_mode")
        validate_gis_felt_export(felt)
        return felt

    def test_gis_contract_and_felt_export_match_fresh_regen(self) -> None:
        for city in CITIES:
            with self.subTest(city=city):
                run_dir = _run_dir(city)
                config = _load(ROOT / "configs" / f"{city}.json")

                committed_contract = _load(run_dir / "gis_rule_contract.json")
                regen_contract = self._regen_contract(run_dir, config, committed_contract)
                self.assertEqual(
                    json.dumps(regen_contract, sort_keys=True),
                    json.dumps(committed_contract, sort_keys=True),
                    f"{city}: committed gis_rule_contract.json drifted from a "
                    f"fresh regen of verified_rules.json",
                )

                committed_felt = _load(run_dir / "gis_felt_export.json")
                regen_felt = self._regen_felt(run_dir, config, committed_felt)
                self.assertEqual(
                    json.dumps(regen_felt, sort_keys=True),
                    json.dumps(committed_felt, sort_keys=True),
                    f"{city}: committed gis_felt_export.json drifted from a "
                    f"fresh regen of verified_rules.json",
                )


if __name__ == "__main__":
    unittest.main()
