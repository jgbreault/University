"""Permanent regression pins for the adversarial-hardening campaign.

Each test reproduces a confirmed false-verify vector found by the adversarial
audit and asserts the verifier now holds/rejects it. They call the REAL
verifier / adapter (no mocks) so a future edit that re-opens a hole fails here.

Vectors pinned:
1. Prose enumerated multi-branch clause — a branch value without its
   discriminating condition (and a MISPAIRED condition) must not verify.
2. Exclusion exception-field dodge — echoing the cue word in the candidate
   ``exception`` field must not clear the unresolved-exception hold.
3. Re-anchor hallucinated value — a value not present on the claimed source
   page must be forced to review (both P9 adapter and source_repair paths).
4. P9 stitch label with a hyphen/dot pack id must still be detected.
5. Matrix FTN overlay band-dilution — an over-broad selector must not erase
   the overlay restriction for a value that lives only in the overlay band.
6. Cross-city normalization isolation — a non-Burnaby config without a
   normalization block must not inherit Burnaby vocabulary.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from burnaby_prototype.config import load_config  # noqa: E402
from burnaby_prototype.verification import verify_candidates  # noqa: E402

CALGARY = load_config(str(ROOT / "configs" / "calgary_rcg.json"))
BURNABY = load_config(str(ROOT / "configs" / "burnaby_r1.json"))
VANCOUVER = load_config(str(ROOT / "configs" / "vancouver_rs.json"))
CALGARY_PDF = ROOT / "data" / "bylaws" / "calgary_rcg" / "source.pdf"

# Per-city adversarial suites. evaluate_adversarial.py defaults to Burnaby-only,
# so these poisoned-case files (incl. the operator-fill inversion pins) would
# otherwise never run in CI. AdversarialCaseFileTests is the safety gate.
_ADVERSARIAL_SUITES = {
    "calgary_rcg": (CALGARY, ROOT / "benchmark" / "gold" / "calgary_rcg_adversarial_cases.json"),
    "vancouver_rs": (VANCOUVER, ROOT / "benchmark" / "gold" / "vancouver_rs_adversarial_cases.json"),
    "burnaby_r1": (BURNABY, ROOT / "benchmark" / "gold" / "burnaby_r1_adversarial_cases.json"),
}


def _decide(config, evidence, candidate):
    res = verify_candidates(config, [evidence], [candidate])
    rules = res["verified_rules"] + res["review_needed"]
    assert len(rules) == 1, rules
    return rules[0]


_HEIGHT_BRANCH_CLAUSE = (
    "(4.1) The maximum building height for a Backyard Suite is: "
    "(a) 5.0 metres measured from grade at a side property line shared with a parcel "
    "designated with a low density residential district; "
    "(b) 3.0 metres measured from grade at a rear property line shared with a parcel "
    "designated with a low density residential district; and "
    "(c) increases at a 45 degree angle to a maximum of 7.5 metres at a proportional "
    "distance from the shared property line."
)


def _height_candidate(value, condition=""):
    return {
        "candidate_id": "c", "evidence_id": "e1", "rule_object": "height",
        "constraint_type": "maximum", "operator": "<=", "value": value, "unit": "m",
        "applies_to": "Backyard Suite", "constraint_scope": "building height",
        "condition": condition, "extraction_method": "pipeline5_final_registry",
        "source_stream": "gemini_text",
    }


class ProseEnumeratedBranchGateTests(unittest.TestCase):
    EV = {"evidence_id": "e1", "page": 1, "evidence_type": "clause",
          "evidence_text": _HEIGHT_BRANCH_CLAUSE, "source_context": _HEIGHT_BRANCH_CLAUSE}

    def test_unconditioned_branch_value_goes_to_review(self) -> None:
        # The two clean numeric branches (5.0 side, 3.0 rear) are held by the
        # branch gate specifically; all three are held (never verified) — the
        # (c) "to a maximum of 7.5" sub-bound is held by the field checks too.
        for value in ("5.0", "3.0"):
            rule = _decide(CALGARY, self.EV, _height_candidate(value, condition=""))
            self.assertEqual(rule["verification_decision"], "review_needed", value)
            self.assertIn("enumerated_branch_condition_missing", rule["support_gaps"], value)
        rule = _decide(CALGARY, self.EV, _height_candidate("7.5", condition=""))
        self.assertEqual(rule["verification_decision"], "review_needed")

    def test_mispaired_condition_goes_to_review(self) -> None:
        # 5.0 m is the SIDE branch; pairing it with 'rear property line' (where
        # the source says 3.0 m) must not verify.
        rule = _decide(CALGARY, self.EV, _height_candidate("5.0", condition="at a rear property line"))
        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertIn("enumerated_branch_condition_missing", rule["support_gaps"])

    def test_correctly_conditioned_branch_verifies(self) -> None:
        rule = _decide(CALGARY, self.EV, _height_candidate("5.0", condition="at a side property line"))
        self.assertEqual(rule["verification_decision"], "verified", rule["support_gaps"])

    def test_lesser_of_aggregation_is_not_branch_gated(self) -> None:
        # "must not exceed the lesser of (a) X; and (b) Y" — every operand is a
        # valid one-sided bound on the same quantity, so the 186 m² operand is
        # a genuine (if loose) cap and must NOT be branch-gated.
        lane = ("The floor area for a laneway house must not exceed the lesser of: "
                "(a) 0.25 multiplied by the site area; and (b) 186 sq. m.")
        ev = {"evidence_id": "e2", "page": 1, "evidence_type": "clause",
              "evidence_text": lane, "source_context": lane}
        cand = {"candidate_id": "l", "evidence_id": "e2", "rule_object": "floor_area",
                "constraint_type": "maximum", "operator": "<=", "value": "186", "unit": "sq. m",
                "applies_to": "laneway house", "constraint_scope": "total", "condition": "",
                "extraction_method": "pipeline5_final_registry"}
        rule = _decide(BURNABY, ev, cand)
        self.assertNotIn("enumerated_branch_condition_missing", rule["support_gaps"])


class RangeLowerBoundNotMaximumTests(unittest.TestCase):
    """A count range whose unit noun is separated from the bound by qualifiers
    ('1 to 3 small-scale multi-unit dwelling units') must still trigger the
    range_bound_not_maximum guard, so the lower bound (1) cannot be verified as
    the lot maximum. Regression for an M7 leak class: the old regex required the
    noun immediately after the high bound, so this evidence escaped the guard."""

    EV = {
        "evidence_id": "e1", "page": 1, "evidence_type": "clause",
        "evidence_text": "1 to 3 small-scale multi-unit dwelling units on a lot",
        "source_context": "1 to 3 small-scale multi-unit dwelling units on a lot",
    }

    @staticmethod
    def _units_candidate(value: str) -> dict:
        return {
            "candidate_id": f"u{value}", "evidence_id": "e1", "rule_object": "dwelling_units",
            "constraint_type": "maximum", "operator": "<=", "value": value, "unit": "units",
            "applies_to": "lot", "constraint_scope": "lot", "condition": "",
            "extraction_method": "pipeline5_final_registry",
        }

    def test_evidence_shape_flags_lower_bound_not_maximum(self) -> None:
        # Unit-level: the interrupted-noun range ('1 to 3 ... dwelling units')
        # must now flag the lower bound (1) and leave the true max (3) clean.
        from burnaby_prototype.decision_policy import evidence_shape_gaps
        low = self._units_candidate("1")
        hi = self._units_candidate("3")
        self.assertIn("range_bound_not_maximum", evidence_shape_gaps(low, self.EV))
        self.assertNotIn("range_bound_not_maximum", evidence_shape_gaps(hi, self.EV))

    def test_lower_bound_as_max_never_verifies(self) -> None:
        # End-to-end safety: a lower-bound count mis-extracted as the lot maximum
        # is never verified (held by the value/operator/consensus gates).
        rule = _decide(BURNABY, self.EV, self._units_candidate("1"))
        self.assertNotEqual(rule["verification_decision"], "verified")


class EasementWidthNotSetbackTests(unittest.TestCase):
    """Calgary R-CG s.539(4): 'the minimum building setback from a side property
    line may be reduced to a zero setback where ... a 1.2 metre private
    maintenance easement'. The 1.2 m is the EASEMENT width that unlocks a ZERO
    setback, NOT a 1.2 m minimum setback. Ground-truth PDF audit caught this
    (the gold benchmark missed it — the value coincides with the real 1.2 m side
    setback). Must be held, while the real side setback still verifies."""

    EASEMENT_EV = {
        "evidence_id": "e1", "page": 471, "evidence_type": "clause",
        "evidence_text": "the minimum building setback from a side property line may be reduced to a zero setback where the owners register against both titles a 1.2 metre private maintenance easement",
        "source_context": "the minimum building setback from a side property line may be reduced to a zero setback where the owners register against both titles a 1.2 metre private maintenance easement",
    }
    REAL_EV = {
        "evidence_id": "e2", "page": 471, "evidence_type": "clause",
        "evidence_text": "the minimum building setback from any side property line is 1.2 metres",
        "source_context": "the minimum building setback from any side property line is 1.2 metres",
    }

    @staticmethod
    def _setback(evidence_id: str) -> dict:
        return {
            "candidate_id": "s", "evidence_id": evidence_id, "rule_object": "setback",
            "constraint_type": "minimum", "operator": ">=", "value": "1.2", "unit": "m",
            "applies_to": "R-CG District", "constraint_scope": "side_yard", "condition": "",
            "extraction_method": "pipeline5_final_registry",
        }

    def test_easement_width_is_not_verified_as_setback(self) -> None:
        rule = _decide(CALGARY, self.EASEMENT_EV, self._setback("e1"))
        self.assertNotEqual(rule["verification_decision"], "verified")
        self.assertIn("allowance_trigger_threshold", rule["support_gaps"])

    def test_real_side_setback_still_verifies(self) -> None:
        rule = _decide(CALGARY, self.REAL_EV, self._setback("e2"))
        self.assertNotIn("allowance_trigger_threshold", rule["support_gaps"])


class ExclusionExceptionFieldDodgeTests(unittest.TestCase):
    EVID = ("The maximum floor area of a Backyard Suite, excluding any area covered by "
            "stairways and internal landings not exceeding 2.5 square metres, is 75.0 square metres.")

    def test_carve_out_value_with_cue_exception_field_still_reviews(self) -> None:
        ev = {"evidence_id": "e1", "page": 352, "evidence_type": "clause",
              "evidence_text": self.EVID, "source_context": self.EVID}
        cand = {"candidate_id": "L", "evidence_id": "e1", "rule_object": "floor_area",
                "constraint_type": "maximum", "operator": "<=", "value": "2.5", "unit": "m2",
                "applies_to": "stairways and internal landings", "constraint_scope": "",
                "condition": "", "exception": "excluding", "extraction_method": "pipeline5_text"}
        rule = _decide(CALGARY, ev, cand)
        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertIn("unresolved_exception_cue", rule["support_gaps"])


@unittest.skipUnless(CALGARY_PDF.exists(), "cached Calgary source.pdf not present")
class ReanchorHallucinatedValueTests(unittest.TestCase):
    def test_p9_reanchor_value_not_on_page_forces_review(self) -> None:
        from burnaby_prototype.pipeline9_adapter import reanchor_to_source

        unit = {"evidence_id": "e4", "page": 396, "evidence_type": "clause",
                "evidence_text": "GENERAL RULES: a minimum separation of 99.0 metres is required "
                "between the closest facade of the main residential building to the closest facade "
                "of a Backyard Suite", "source_context": "", "p9_provenance": {"original_page_number": 396}}
        cand = {"candidate_id": "c4", "evidence_id": "e4", "rule_object": "building_separation",
                "constraint_type": "minimum", "constraint_scope": "building_separation",
                "applies_to": "backyard suite", "operator": ">=", "value": "99.0", "unit": "m",
                "extraction_method": "pipeline9_rag", "source_stream": "gemini_text_block",
                "extraction_review_reasons": []}
        summary = reanchor_to_source([unit], [cand], CALGARY_PDF)
        self.assertEqual(summary["mismatched"], 1)
        self.assertEqual(cand.get("extraction_final_action"), "REVIEW")
        res = verify_candidates(CALGARY, [unit], [cand])
        self.assertEqual(len(res["verified_rules"]), 0)


class P9StitchRegexTests(unittest.TestCase):
    def test_hyphen_and_dot_pack_ids_are_detected_as_stitch_labels(self) -> None:
        from burnaby_prototype.pipeline9_adapter import STITCH_LABEL_RE

        for label in ("[rcg__page_0440__local_001]", "[r-cg__page_0440__local_001]",
                      "[rcg.v2__page_0440__local_001]"):
            self.assertTrue(STITCH_LABEL_RE.findall(label), label)
        # Ordinary bracketed prose is not a stitch label.
        self.assertEqual(STITCH_LABEL_RE.findall("see [Schedule A] and [note 1]"), [])


class TargetSectionGuardTests(unittest.TestCase):
    def test_out_of_target_calgary_section_is_not_used_not_verified(self) -> None:
        # Live Calgary P9 false-verify pattern: the rule is real source text,
        # but it belongs to R-G/R-Gm section 547.13, outside this verifier's
        # configured Calgary target sections 351/352/358.
        text = (
            "PART 5 - DIVISION 12: (R-G)(R-Gm) 547.13 Building Height "
            "547.13 (2) The maximum height of a Backyard Suite on a laned parcel "
            "is 10.0 metres."
        )
        ev = {"evidence_id": "e1", "page": 484, "evidence_type": "clause",
              "evidence_text": text, "source_context": text}
        cand = {"candidate_id": "c1", "evidence_id": "e1", "rule_object": "height",
                "constraint_type": "maximum", "operator": "<=", "value": "10.0",
                "unit": "m", "applies_to": "Backyard Suite",
                "constraint_scope": "building height", "condition": "on a laned parcel",
                "extraction_method": "pipeline9_rag", "source_stream": "gemini_text_block"}
        rule = _decide(CALGARY, ev, cand)
        self.assertEqual(rule["verification_decision"], "not_used")
        self.assertIn("outside_target_section", rule["support_gaps"])

    def test_configured_calgary_section_can_still_verify(self) -> None:
        text = (
            "352 Backyard Suite 352 (4) The maximum building height for a "
            "Backyard Suite is 7.5 metres."
        )
        ev = {"evidence_id": "e2", "page": 396, "evidence_type": "clause",
              "evidence_text": text, "source_context": text}
        cand = {"candidate_id": "c2", "evidence_id": "e2", "rule_object": "height",
                "constraint_type": "maximum", "operator": "<=", "value": "7.5",
                "unit": "m", "applies_to": "Backyard Suite",
                "constraint_scope": "building height", "condition": "",
                "extraction_method": "pipeline9_rag", "source_stream": "gemini_text_block"}
        rule = _decide(CALGARY, ev, cand)
        self.assertEqual(rule["verification_decision"], "verified", rule["support_gaps"])

    def test_generic_p9_block_without_target_hit_cannot_verify(self) -> None:
        text = (
            "(iii) the privacy wall is a minimum of 2.0 metres in height and "
            "a maximum of 3.0 metres in height."
        )
        provenance = {"target_filter_action": "kept_generic_applicable"}
        ev = {"evidence_id": "e3", "page": 390, "evidence_type": "clause",
              "evidence_text": text, "source_context": text, "p9_provenance": provenance}
        cand = {"candidate_id": "c3", "evidence_id": "e3", "rule_object": "height",
                "constraint_type": "maximum", "operator": "<=", "value": "3.0",
                "unit": "m", "applies_to": "privacy wall",
                "constraint_scope": "privacy_wall_maximum_height", "condition": "",
                "extraction_method": "pipeline9_rag", "source_stream": "gemini_text_block",
                "p9_provenance": provenance}
        rule = _decide(CALGARY, ev, cand)
        self.assertEqual(rule["verification_decision"], "not_used")
        self.assertIn("outside_target_section", rule["support_gaps"])


class MatrixOverlayDilutionTests(unittest.TestCase):
    ANCHOR = {
        "page": 2, "row_label": "Maximum Lot Coverage | All Buildings",
        "bands": [
            {"key": 1, "header_text": "Dwelling Type | Small-Scale Multi-Unit | 1 to 2 | Units",
             "text": "40%", "numbers": [40.0], "branches": [], "spans_all": False},
            {"key": 2, "header_text": "Dwelling Type | Small-Scale Multi-Unit | 3 to 4 | Units",
             "text": "40%", "numbers": [40.0], "branches": [], "spans_all": False},
            {"key": 3, "header_text": "Small-Scale Multi-Unit | 5 to 6 Units | Frequent Transit | Network Area Only",
             "text": "45%", "numbers": [45.0], "branches": [], "spans_all": False},
        ],
    }

    def _coverage(self, applies_to, value="45", cell="45 %"):
        ev = {"evidence_id": "m1", "page": 2, "evidence_type": "table_cell",
              "evidence_text": f"Maximum Lot Coverage | All Buildings | {cell}",
              "source_context": "Maximum Lot Coverage All Buildings 55% 40% 40% 45%",
              "table_title": "Maximum Lot Coverage", "row_header": "All Buildings",
              "column_header": "Rowhouse", "cell_value": cell, "matrix_anchor": self.ANCHOR}
        cand = {"candidate_id": "mc", "evidence_id": "m1", "rule_object": "lot_coverage",
                "constraint_type": "maximum", "constraint_scope": "lot", "applies_to": applies_to,
                "condition": "", "operator": "<=", "value": value, "unit": "%",
                "extraction_method": "deterministic_table_evidence"}
        return _decide(BURNABY, ev, cand)

    def test_overbroad_selector_does_not_erase_ftn_overlay(self) -> None:
        # 45% lives ONLY in band 3 (Frequent Transit). An over-broad
        # "Small-Scale Multi-Unit" selector (bands 1,2,3) must NOT verify it
        # unconditionally — the value's only home carries the overlay.
        rule = self._coverage("Small-Scale Multi-Unit")
        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertIn("column_qualifier_not_claimed", rule["support_gaps"])

    def test_precise_selector_without_overlay_claim_still_reviews(self) -> None:
        # Even the precise "(5 to 6 Units)" selector must claim the FTN overlay
        # condition; without it the rule is held (the overlay restriction is
        # real and unclaimed). This is the conservative direction.
        rule = self._coverage("Small-Scale Multi-Unit (5 to 6 Units)")
        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertIn("column_qualifier_not_claimed", rule["support_gaps"])

    def test_precise_selector_with_overlay_condition_verifies(self) -> None:
        ev = {"evidence_id": "m1", "page": 2, "evidence_type": "table_cell",
              "evidence_text": "Maximum Lot Coverage | All Buildings | Frequent Transit Network Area Only | 45 %",
              "source_context": "Maximum Lot Coverage All Buildings 55% 40% 40% 45% Frequent Transit Network Area Only",
              "table_title": "Maximum Lot Coverage", "row_header": "All Buildings",
              "column_header": "Rowhouse", "cell_value": "45 %", "matrix_anchor": self.ANCHOR}
        cand = {"candidate_id": "mc", "evidence_id": "m1", "rule_object": "lot_coverage",
                "constraint_type": "maximum", "constraint_scope": "lot",
                "applies_to": "Small-Scale Multi-Unit (5 to 6 Units)",
                "condition": "Frequent Transit Network Area Only", "operator": "<=",
                "value": "45", "unit": "%", "extraction_method": "deterministic_table_evidence"}
        rule = _decide(BURNABY, ev, cand)
        self.assertEqual(rule["verification_decision"], "verified", rule["support_gaps"])


if __name__ == "__main__":
    unittest.main()


class LlmLaneShapeGateTests(unittest.TestCase):
    """LLM-lane leak classes found by running V2's REAL model extraction.

    Flattened-table clause evidence dodges the structured matrix gates, so a
    coefficient ("0.25 multiplied by the site area") or a range bound ("1 to 3
    Units" when 4 to 6 is also listed) verified as an absolute cap. These hold
    such candidates for review WITHOUT touching the structured table path
    (matrix_anchor / table_cell), which the matrix binding proves column-wise.
    """

    def _decide(self, evidence, candidate):
        result = verify_candidates(CALGARY, [evidence], [candidate])
        rules = [r for key in ("verified_rules", "review_needed", "rejected_rules", "not_used")
                 for r in result.get(key, [])]
        self.assertEqual(len(rules), 1, rules)
        return rules[0]

    def test_fsr_coefficient_not_verified_as_absolute_cap(self) -> None:
        evid = "The floor area for a laneway house must not exceed the lesser of: (a) 0.25 multiplied by the site area; and (b) 186 m2."
        ev = {"evidence_id": "e1", "page": 1, "evidence_type": "clause", "evidence_text": evid, "source_context": evid}
        cand = {"candidate_id": "c", "evidence_id": "e1", "rule_object": "floor_area",
                "constraint_type": "maximum", "operator": "<=", "value": "0.25", "unit": "m2",
                "applies_to": "laneway house", "condition": "", "extraction_method": "native_rag_llm_v2"}
        rule = self._decide(ev, cand)
        self.assertNotEqual(rule["verification_decision"], "verified")
        self.assertIn("coefficient_operand_not_value", rule["support_gaps"])

    def test_range_bound_not_verified_as_lot_maximum(self) -> None:
        evid = "Total Dwelling Units on a Lot: 1 to 3 Units; 4 to 6 Units"
        ev = {"evidence_id": "e2", "page": 1, "evidence_type": "clause", "evidence_text": evid, "source_context": evid}
        cand = {"candidate_id": "c", "evidence_id": "e2", "rule_object": "dwelling_units",
                "constraint_type": "maximum", "operator": "<=", "value": "3", "unit": "units",
                "applies_to": "lot", "condition": "", "extraction_method": "native_rag_llm_v2"}
        rule = self._decide(ev, cand)
        self.assertNotEqual(rule["verification_decision"], "verified")
        self.assertIn("range_bound_not_maximum", rule["support_gaps"])

    def test_structured_table_cell_count_is_not_shape_gated(self) -> None:
        # A matrix table_cell candidate (proven column-wise by the binding)
        # must NOT be caught by the clause-only count gate, even though its
        # row context names higher counts.
        ev = {"evidence_id": "e3", "page": 2, "evidence_type": "table_cell",
              "evidence_text": "Permitted Dwelling Units | Small-Scale Multi-Unit 3 to 4 Units | 4 Units",
              "source_context": "Permitted Dwelling Units 1 to 3 1 to 2 3 to 4 5 to 6 Units",
              "table_title": "Permitted Dwelling Units", "row_header": "Dwelling Units",
              "column_header": "Small-Scale Multi-Unit 3 to 4 Units", "cell_value": "4 Units"}
        cand = {"candidate_id": "c", "evidence_id": "e3", "rule_object": "dwelling_units",
                "constraint_type": "maximum", "operator": "<=", "value": "4", "unit": "units",
                "applies_to": "Small-Scale Multi-Unit 3 to 4 Units", "condition": "",
                "extraction_method": "deterministic_matrix_v2"}
        from burnaby_prototype.decision_policy import evidence_shape_gaps
        self.assertNotIn("range_bound_not_maximum", evidence_shape_gaps(cand, ev))


class AdversarialCaseFileTests(unittest.TestCase):
    """Every poisoned case in each per-city adversarial file must fail to verify.

    This is the CI safety gate for Calgary/Vancouver (and Burnaby), since
    benchmark/evaluate_adversarial.py defaults to Burnaby-only and never loads
    the Calgary/Vancouver files. It pins the operator-fill inversion cases.
    """

    def test_all_city_adversarial_cases_blocked(self) -> None:
        import json

        ran_any = False
        for city, (config, path) in _ADVERSARIAL_SUITES.items():
            if not path.exists():
                continue
            ran_any = True
            cases = json.loads(path.read_text(encoding="utf-8"))
            evidence_units = [c["evidence"] for c in cases if c.get("evidence")]
            candidates = [c["candidate"] for c in cases]
            res = verify_candidates(config, evidence_units, candidates)
            verified_ids = {
                r.get("candidate", {}).get("candidate_id") for r in res["verified_rules"]
            }
            for case in cases:
                cid = case["candidate"]["candidate_id"]
                self.assertNotIn(
                    cid,
                    verified_ids,
                    f"{city}: poisoned adversarial case {case['case_id']} LEAKED to verified",
                )
        self.assertTrue(ran_any, "no adversarial case files found")


class ImperialUnitHandlingTests(unittest.TestCase):
    """Imperial-stated rules are handled honestly: routed to review (for
    conversion), never silently verified against a metric threshold, and never
    confused with a genuine unit error (% for height) which must still reject."""

    def _height(self, unit, value, evidence_text):
        ev = {"evidence_id": "e", "page": 1, "evidence_type": "clause",
              "evidence_text": evidence_text, "source_context": evidence_text}
        cand = {"candidate_id": "c", "evidence_id": "e", "rule_object": "height",
                "constraint_type": "maximum", "operator": "<=", "value": value,
                "unit": unit, "applies_to": "building"}
        return _decide(CALGARY, ev, cand)

    def test_imperial_height_routed_to_review_not_verified(self) -> None:
        rule = self._height("feet", "30", "The maximum building height is 30 feet.")
        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertIn("non_metric_unit_requires_review", rule["support_gaps"])
        self.assertNotIn("rule_object_unit_not_compatible", rule["support_gaps"])

    def test_bogus_percent_height_still_rejected(self) -> None:
        rule = self._height("%", "60", "The maximum building height is 60 %.")
        self.assertEqual(rule["verification_decision"], "rejected")
        self.assertIn("rule_object_unit_not_compatible", rule["support_gaps"])
