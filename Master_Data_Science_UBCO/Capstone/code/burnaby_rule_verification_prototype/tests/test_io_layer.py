"""Tests for the IO/projection layer cleanups.

Covers: per-candidate cache keys without run-context coupling, the rule_text
leaf module + import-cycle removal, config-dict pass-through, the per-city
Felt layer paths, the single-sourced setback geometry map, boundary-aware
value grounding, and parcel-level envelope variants.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from burnaby_prototype.config import load_config
from burnaby_prototype.evidence_contract import evidence_quality_summary
from burnaby_prototype.geometry_operator import AXIS_BY_SCOPE
from burnaby_prototype.gis_felt_export import _SETBACK_GEOMETRY_BY_SCOPE, build_gis_felt_export
from burnaby_prototype.rule_text import _rule_sentence
from burnaby_prototype.slim_pipeline import run_slim_verification
from burnaby_prototype.slim_pipeline import _rule_sentence as reexported_rule_sentence
from burnaby_prototype.verification_cache import build_verification_cache_report
from build_buildable_envelope import build_envelope


_CACHE_CONFIG = {"city": "Testville", "zone": "T1", "verification": {}, "normalization": {}}
_CACHE_EVIDENCE = [
    {"evidence_id": "ev_a", "evidence_text": "Front yard setback shall be at least 4.0 m."},
    {"evidence_id": "ev_b", "evidence_text": "Height shall not exceed 9.0 m."},
]


def _candidate(candidate_id: str, evidence_id: str, value: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "evidence_id": evidence_id,
        "rule_object": "setback",
        "constraint_scope": "street_yard_front",
        "applies_to": "All Buildings",
        "operator": ">=",
        "value": value,
        "unit": "m",
    }


def _cache_report(candidates: list[dict], previous: dict | None = None) -> dict:
    return build_verification_cache_report(
        config=_CACHE_CONFIG,
        evidence_units=_CACHE_EVIDENCE,
        rule_candidates=candidates,
        verified_rules=[],
        review_rules=[],
        previous_cache=previous,
    )


class VerificationCacheKeyTests(unittest.TestCase):
    def test_changing_one_candidate_keeps_other_entries_hitting(self) -> None:
        # The regression this guards: when run_context_hash lived inside every
        # per-candidate key, editing ONE candidate invalidated EVERY key.
        candidates = [_candidate("c1", "ev_a", "4.0"), _candidate("c2", "ev_b", "9.0")]
        first = _cache_report(candidates)
        changed = [_candidate("c1", "ev_a", "4.0"), _candidate("c2", "ev_b", "10.0")]
        second = _cache_report(changed, previous=first)

        by_id = {entry["candidate_id"]: entry for entry in second["entries"]}
        self.assertTrue(by_id["c1"]["cache_hit"], "unchanged candidate must still hit")
        self.assertFalse(by_id["c2"]["cache_hit"], "changed candidate must miss")
        self.assertEqual(second["cache_hit_count"], 1)
        self.assertEqual(second["cache_miss_count"], 1)

    def test_run_context_hash_lives_at_report_level_not_in_keys(self) -> None:
        report = _cache_report([_candidate("c1", "ev_a", "4.0")])
        self.assertIn("run_context_hash", report)
        for entry in report["entries"]:
            self.assertNotIn("run_context_hash", entry["key_parts"])

    def test_safe_to_reuse_requires_unchanged_run_context(self) -> None:
        # Unchanged rerun: hit + same run context + same decision -> safe.
        candidates = [_candidate("c1", "ev_a", "4.0"), _candidate("c2", "ev_b", "9.0")]
        first = _cache_report(candidates)
        same = _cache_report(candidates, previous=first)
        self.assertEqual(same["safe_reuse_count"], 2)

        # One changed candidate changes the run-level context, so even the
        # untouched candidate's hit is conservatively NOT safe_to_reuse
        # (verification still depends on run-level agreement/collision signals).
        changed = [_candidate("c1", "ev_a", "4.0"), _candidate("c2", "ev_b", "10.0")]
        second = _cache_report(changed, previous=first)
        by_id = {entry["candidate_id"]: entry for entry in second["entries"]}
        self.assertTrue(by_id["c1"]["cache_hit"])
        self.assertFalse(by_id["c1"]["safe_to_reuse"])


class RuleTextLeafModuleTests(unittest.TestCase):
    def test_slim_pipeline_reexports_rule_sentence(self) -> None:
        # scripts/build_proof_graph.py imports _rule_sentence from slim_pipeline.
        self.assertIs(reexported_rule_sentence, _rule_sentence)

    def test_rule_text_is_a_leaf_module(self) -> None:
        source = (ROOT / "src" / "burnaby_prototype" / "rule_text.py").read_text(encoding="utf-8")
        self.assertNotIn("from .", source.replace("from __future__", ""))
        self.assertNotIn("import burnaby_prototype", source)

    def test_gis_felt_export_imports_without_slim_pipeline_cycle(self) -> None:
        source = (ROOT / "src" / "burnaby_prototype" / "gis_felt_export.py").read_text(encoding="utf-8")
        self.assertNotIn("slim_pipeline", source)


class ConfigDictPassThroughTests(unittest.TestCase):
    def test_run_slim_verification_accepts_loaded_config_dict(self) -> None:
        config = load_config(ROOT / "configs" / "burnaby_r1.json")
        self.assertIn("_config_path", config)  # provenance stamped by load_config
        evidence = [
            {
                "evidence_id": "ev_001",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": "Rear Principal Buildings maximum height shall not exceed 7.5 m.",
                "source_context": "Rear Principal Buildings maximum height shall not exceed 7.5 m.",
            }
        ]
        base_candidate = {
            "candidate_id": "cand_001",
            "evidence_id": "ev_001",
            "rule_object": "height",
            "constraint_type": "maximum",
            "constraint_scope": "maximum height",
            "applies_to": "Rear Principal Buildings",
            "operator": "<=",
            "value": "7.5 m",
            "unit": "m",
            "extraction_method": "pipeline5_final_registry",
            "source_stream": "gemini_text_block",
        }
        # Burnaby policy needs cross-source consensus for text height rules.
        candidates = [
            base_candidate,
            {**base_candidate, "candidate_id": "cand_001_table", "source_stream": "gemini_table_image"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            run_slim_verification(
                config_path=config,
                output_dir=output_dir,
                evidence_units=evidence,
                rule_candidates=candidates,
                input_mode="unit_test",
            )
            verified = json.loads((output_dir / "verified_rules.json").read_text())
        self.assertEqual(len(verified), 2)
        self.assertIn("7.5", str(verified[0]["value"]))


class GisFeltExportCityTests(unittest.TestCase):
    def _verified_setback(self) -> dict:
        return {
            "rule_id": "r_setback",
            "rule_object": "setback",
            "constraint_type": "min",
            "constraint_scope": "street_yard_front",
            "applies_to": "All Buildings",
            "operator": ">=",
            "value": "4.0",
            "unit": "m",
            "gis_relevance": "direct",
            "source": {"evidence_id": "ev_1", "page": 2, "evidence_text": "Front yard 4.0 m."},
        }

    def test_example_team_file_uses_city_from_config(self) -> None:
        export = build_gis_felt_export(
            [self._verified_setback()], [], [], {"city": "Vancouver", "zone": "RS"}
        )
        layers = export["map_layer_requirements"]
        self.assertTrue(layers)
        for layer in layers:
            self.assertTrue(
                layer["example_team_file"].startswith("code/gis_files/vancouver/"),
                layer["example_team_file"],
            )

    def test_setback_geometry_map_is_derived_from_axis_by_scope(self) -> None:
        self.assertEqual(set(_SETBACK_GEOMETRY_BY_SCOPE), set(AXIS_BY_SCOPE))
        # The lane edge is the one Felt-vs-axis naming difference.
        self.assertEqual(_SETBACK_GEOMETRY_BY_SCOPE["lane_yard"], "lane")
        for scope, axis in AXIS_BY_SCOPE.items():
            if axis != "lane_lot_line":
                self.assertEqual(_SETBACK_GEOMETRY_BY_SCOPE[scope], axis)


class ValueGroundingTokenDisciplineTests(unittest.TestCase):
    def _summary(self, evidence_text: str, value: str) -> dict:
        evidence = [{"evidence_id": "ev_1", "page": 1, "evidence_text": evidence_text}]
        candidates = [{"candidate_id": "c1", "evidence_id": "ev_1", "value": value, "unit": ""}]
        return evidence_quality_summary(evidence, candidates)

    def test_value_not_grounded_by_substring_of_another_number(self) -> None:
        # '5' must not count as grounded by '1.5' (the old substring check did).
        summary = self._summary("Lane setback shall be at least 1.5 m.", "5")
        self.assertEqual(summary["candidate_value_grounding_rate"], 0.0)

    def test_exact_value_still_grounds(self) -> None:
        summary = self._summary("Setback shall be at least 5 m.", "5")
        self.assertEqual(summary["candidate_value_grounding_rate"], 1.0)

    def test_comma_grouped_value_grounds(self) -> None:
        summary = self._summary("Minimum lot area is 1,200 m2.", "1200")
        self.assertEqual(summary["candidate_value_grounding_rate"], 1.0)

    def test_section_reference_value_grounds_as_traceability_not_measurement(self) -> None:
        summary = self._summary(
            "Principal Use | Rowhouse Dwellings | Use-Specific Regulations: 101.5.2",
            "101.5.2",
        )
        self.assertEqual(summary["candidate_value_grounding_rate"], 1.0)

    def test_text_value_grounds_by_exact_normalized_phrase(self) -> None:
        summary = self._summary(
            "Parking shall be provided in an attached or detached garage.",
            "in an attached or detached garage",
        )
        self.assertEqual(summary["candidate_value_grounding_rate"], 1.0)


class BuildableEnvelopeVariantTests(unittest.TestCase):
    def test_parcel_level_keeps_conditional_variants(self) -> None:
        export = {
            "city": "Burnaby",
            "zone": "R1",
            "constraints": [
                {
                    "constraint_id": "r_base",
                    "geometry": {"operation": "area_floor"},
                    "value_numeric": 281.0,
                    "unit": "m²",
                    "operator": ">=",
                    "condition": "",
                    "applies_to": "Small-Scale Multi-Unit",
                },
                {
                    "constraint_id": "r_variant",
                    "geometry": {"operation": "area_floor"},
                    "value_numeric": 281.0,
                    "unit": "m²",
                    "operator": ">=",
                    "condition": "4 Units Only",
                    "applies_to": "Small-Scale Multi-Unit (3 to 4 Units)",
                },
            ],
        }
        envelope = build_envelope(export)
        entries = envelope["parcel_level"]["min_lot_area"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            sorted(entry["rule_id"] for entry in entries), ["r_base", "r_variant"]
        )


if __name__ == "__main__":
    unittest.main()
