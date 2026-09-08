"""V3 deterministic prose-clause candidate tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.v3_clause_candidates import build_clause_candidate_set  # noqa: E402
from burnaby_prototype.verification import verify_candidates  # noqa: E402


VANCOUVER_CONFIG = {
    "city": "Vancouver",
    "zone": "RS",
    "target_concept": "laneway house",
    "known_aliases": ["laneway house"],
    "verification": {
        "verify_text_candidates": True,
        "gis_text_rule_contract": ["setback", "building_separation", "floor_area", "lot_coverage"],
        "single_source_text_rule_contract": ["setback", "building_separation", "floor_area", "lot_coverage"],
        "rule_family_direction": {
            "setback": "min",
            "building_separation": "min",
            "floor_area": "max",
            "lot_coverage": "max",
        },
    },
}


class V3ClauseCandidateTests(unittest.TestCase):
    def test_minimum_distance_list_emits_setback_and_separation_candidates(self) -> None:
        packs = [
            {
                "pack_id": "v3_pack_0009",
                "chunk_id": "van_11.3.8.6",
                "page": 8,
                "section": "11.3.8.6",
                "source_text": (
                    "A laneway house must be at least: "
                    "(a) 4.9 m, measured across the width of the site, from the single detached house "
                    "or single detached house with secondary suite on the site; "
                    "(b) 0.9 m from the ultimate rear property line; and "
                    "(c) 1.2 m from each side property line, except that the Director of Planning may "
                    "reduce this requirement for sites less than 10.1 m in width."
                ),
            }
        ]
        evidence, candidates = build_clause_candidate_set("vancouver_rs", packs, VANCOUVER_CONFIG)
        self.assertEqual(len(evidence), 3)
        got = {(c["rule_object"], c["operator"], c["value"], c["constraint_scope"]) for c in candidates}
        self.assertIn(("building_separation", ">=", "4.9", "building_separation"), got)
        self.assertIn(("setback", ">=", "0.9", "rear setback"), got)
        self.assertIn(("setback", ">=", "1.2", "side setback"), got)
        side = next(c for c in candidates if c["value"] == "1.2")
        self.assertIn("Director of Planning", side["exception"])

    def test_vancouver_clause_candidates_can_verify_through_existing_gate(self) -> None:
        packs = [
            {
                "pack_id": "v3_pack_0009",
                "chunk_id": "van_11.3.8.6",
                "page": 8,
                "section": "11.3.8.6",
                "source_text": (
                    "A laneway house must be at least: "
                    "(a) 4.9 m, measured across the width of the site, from the single detached house "
                    "or single detached house with secondary suite on the site; "
                    "(b) 0.9 m from the ultimate rear property line; and "
                    "(c) 1.2 m from each side property line, except that the Director of Planning may "
                    "reduce this requirement for sites less than 10.1 m in width."
                ),
            }
        ]
        evidence, candidates = build_clause_candidate_set("vancouver_rs", packs, VANCOUVER_CONFIG)
        outputs = verify_candidates(VANCOUVER_CONFIG, evidence, candidates)
        verified = {(r["rule_object"], r["operator"], str(r["value"])) for r in outputs["verified_rules"]}
        self.assertIn(("building_separation", ">=", "4.9"), verified)
        self.assertIn(("setback", ">=", "0.9"), verified)
        self.assertIn(("setback", ">=", "1.2"), verified)

    def test_lesser_of_absolute_m2_branch_can_verify_but_coefficient_stays_held(self) -> None:
        text = "The floor area for a laneway house must not exceed the lesser of: (a) 0.25 multiplied by the site area; and (b) 186 m2."
        evidence = [{"evidence_id": "e1", "page": 8, "section": "11.3.8.2", "evidence_type": "clause", "evidence_text": text, "source_context": text}]
        candidates = [
            {
                "candidate_id": "absolute",
                "evidence_id": "e1",
                "rule_object": "floor_area",
                "constraint_type": "maximum",
                "constraint_scope": "floor_area",
                "applies_to": "laneway house",
                "operator": "<=",
                "value": "186",
                "unit": "m2",
            },
            {
                "candidate_id": "coefficient",
                "evidence_id": "e1",
                "rule_object": "floor_area",
                "constraint_type": "maximum",
                "constraint_scope": "floor_area",
                "applies_to": "laneway house",
                "operator": "<=",
                "value": "0.25",
                "unit": "m2",
            },
        ]
        outputs = verify_candidates(VANCOUVER_CONFIG, evidence, candidates)
        self.assertTrue(any(r["candidate"]["candidate_id"] == "absolute" for r in outputs["verified_rules"]))
        held = [r for r in outputs["review_needed"] if r["candidate"]["candidate_id"] == "coefficient"]
        self.assertEqual(len(held), 1)
        self.assertIn("coefficient_operand_not_value", held[0]["support_gaps"])

    def test_site_coverage_percent_of_site_area_is_not_a_coefficient_trap(self) -> None:
        text = "Despite the maximum permitted site coverage in an applicable district schedule, for a site with a laneway house, the maximum site coverage is 50% of the site area."
        packs = [{"pack_id": "v3_pack_0010", "page": 8, "section": "11.3.8.5", "source_text": text}]
        evidence, candidates = build_clause_candidate_set("vancouver_rs", packs, VANCOUVER_CONFIG)
        outputs = verify_candidates(VANCOUVER_CONFIG, evidence, candidates)
        self.assertTrue(any(r["rule_object"] == "lot_coverage" and str(r["value"]) == "50" for r in outputs["verified_rules"]))

    def test_calgary_backyard_suite_floor_area_uses_cap_not_exclusion_threshold(self) -> None:
        text = (
            "The maximum floor area of a Backyard Suite, excluding any area covered by stairways "
            "and internal landings not exceeding 2.5 square metres, is 75.0 square metres."
        )
        packs = [{"pack_id": "v3_pack_352_5", "page": 396, "section": "352(5)", "source_text": text}]
        _, candidates = build_clause_candidate_set("calgary_rcg", packs, {"known_aliases": ["backyard suite"]})
        self.assertTrue(any(c["rule_object"] == "floor_area" and c["value"] == "75.0" for c in candidates))
        self.assertFalse(any(c["rule_object"] == "floor_area" and c["value"] == "2.5" for c in candidates))

    def test_calgary_height_branch_emits_side_property_line_limit_only(self) -> None:
        text = (
            "The maximum building height for a Backyard Suite is: "
            "(a) 5.0 metres measured from grade at a side property line shared with a parcel "
            "designated with a low density residential district; "
            "(b) 3.0 metres measured from grade at a rear property line shared with a parcel "
            "designated with a low density residential district; and "
            "(c) increases at a 45 degree angle to a maximum of 7.5 metres at a proportional distance "
            "from the shared property line."
        )
        packs = [{"pack_id": "v3_pack_352_41", "page": 396, "section": "352(4.1)", "source_text": text}]
        _, candidates = build_clause_candidate_set("calgary_rcg", packs, {"known_aliases": ["backyard suite"]})
        self.assertTrue(any(c["rule_object"] == "height" and c["value"] == "5.0" for c in candidates))
        self.assertFalse(any(c["rule_object"] == "height" and c["value"] == "3.0" for c in candidates))

    def test_burnaby_sprinkler_distance_requirement_can_verify(self) -> None:
        text = (
            "Dwelling units located more than 45 m from a lot line abutting a street "
            "shall contain an automatic sprinkler system."
        )
        packs = [{"pack_id": "burnaby_pack_101_1", "page": 6, "section": "101(1)", "source_text": text}]
        evidence, candidates = build_clause_candidate_set("burnaby_r1", packs, {"known_aliases": ["dwelling units"]})
        outputs = verify_candidates(
            {
                "city": "Burnaby",
                "zone": "R1",
                "target_concept": "Small-Scale Multi-Unit Housing",
                "known_aliases": ["Small-Scale Multi-Unit Housing"],
                "verification": {
                    "verify_text_candidates": True,
                    "gis_text_rule_contract": ["automatic_sprinkler"],
                    "single_source_text_rule_contract": ["automatic_sprinkler"],
                    "rule_family_direction": {"automatic_sprinkler": "min"},
                },
            },
            evidence,
            candidates,
        )
        self.assertTrue(any(r["rule_object"] == "automatic_sprinkler" and str(r["value"]) == "45" for r in outputs["verified_rules"]))

    def test_burnaby_permitted_uses_are_source_backed_review_candidates(self) -> None:
        text = (
            "101.2 Permitted Uses Principal Use Use-Specific Regulations "
            "Small-Scale Multi-Unit Housing - Rowhouse Dwellings 101.5.2 "
            "Group Home - Supportive Housing (Category A) 101.5.4"
        )
        packs = [{"pack_id": "burnaby_pack_101_2", "page": 1, "section": "101.2", "source_text": text}]
        evidence, candidates = build_clause_candidate_set("burnaby_r1", packs, {"known_aliases": ["Small-Scale Multi-Unit Housing"]})
        got = {(c["rule_object"], c["operator"], c["applies_to"], c["condition"]) for c in candidates}
        self.assertIn(("permitted_use", "allowed", "Small-Scale Multi-Unit Housing", ""), got)
        self.assertIn(("permitted_use", "allowed", "Principal Use", "Group Home"), got)
        outputs = verify_candidates(
            {
                "city": "Burnaby",
                "zone": "R1",
                "target_concept": "Small-Scale Multi-Unit Housing",
                "known_aliases": ["Small-Scale Multi-Unit Housing"],
                "verification": {
                    "verify_text_candidates": True,
                    "gis_text_rule_contract": ["permitted_use"],
                    "single_source_text_rule_contract": [],
                },
            },
            evidence,
            candidates,
        )
        self.assertEqual(len(outputs["verified_rules"]), 0)
        self.assertEqual(len(outputs["review_needed"]), 2)


if __name__ == "__main__":
    unittest.main()
