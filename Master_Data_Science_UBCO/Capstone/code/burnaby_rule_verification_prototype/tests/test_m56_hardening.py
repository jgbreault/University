"""M5.6 hardening regression tests.

Each test pins one bug fix found in the M5.6 adversarial bug hunt so the safe
behaviour cannot silently regress. The bias throughout is safety-first: ambiguous
inputs must route toward review, never toward an unsupported verification.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype import compliance  # noqa: E402
from burnaby_prototype.compliance import evaluate_case  # noqa: E402
from burnaby_prototype.m7_measure import (  # noqa: E402
    compute_scored_slot_metrics,
    extract_measurements,
    legal_slot_key,
    slot_duplicate_summary,
    slot_is_scored,
)
from burnaby_prototype.native_extraction import _normalize_unit, _normalize_value  # noqa: E402
from burnaby_prototype.normalization_rules import DEFAULT_NORMALIZATION, range_upper_bound_rewrite  # noqa: E402
from burnaby_prototype.table_natural_logic import _exception_branch_resolved  # noqa: E402
from burnaby_prototype.verification import _value_has_same_sentence_operator_parent  # noqa: E402


class ExtractMeasurementsTests(unittest.TestCase):
    def test_unit_bearing_measurements_are_kept(self) -> None:
        rows = extract_measurements("The building height must not exceed 8.5 m and 2 storeys.")
        values = {(row["value"], row["unit"]) for row in rows}
        self.assertIn(("8.5", "m"), values)
        self.assertIn(("2", "storeys"), values)

    def test_section_reference_numbers_are_dropped(self) -> None:
        rows = extract_measurements("As described in section 6 and Table 3, see subsection 4.")
        self.assertEqual(rows, [])

    def test_dotted_numbering_and_enumerators_are_dropped(self) -> None:
        rows = extract_measurements("Clause 101.5.2 applies; item (1) and (2) are exempt.")
        self.assertEqual(rows, [])

    def test_unitless_real_value_still_kept(self) -> None:
        rows = extract_measurements("a maximum of 55 per lot")
        self.assertTrue(any(row["value"] == "55" for row in rows))


class ScoredSlotMetricTests(unittest.TestCase):
    def _ledger(self) -> list[dict]:
        # 2 in-contract corpus slots (one repeated value), 1 unknown-family corpus
        # slot, 1 outside-contract corpus slot, and 1 output-observed slot.
        return [
            {"slot_id": "c1", "slot_origin": "source_corpus", "rule_family_signal": "setback",
             "gis_contract_relevance": "in_gis_contract", "value": "3", "unit": "m"},
            {"slot_id": "c2", "slot_origin": "source_corpus", "rule_family_signal": "setback",
             "gis_contract_relevance": "in_gis_contract", "value": "3", "unit": "m"},  # dup legal key
            {"slot_id": "c3", "slot_origin": "source_corpus", "rule_family_signal": "height",
             "gis_contract_relevance": "in_gis_contract", "value": "10", "unit": "m"},
            {"slot_id": "n1", "slot_origin": "source_corpus", "rule_family_signal": "unknown",
             "gis_contract_relevance": "in_gis_contract", "value": "7", "unit": ""},
            {"slot_id": "o1", "slot_origin": "source_corpus", "rule_family_signal": "parking",
             "gis_contract_relevance": "outside_gis_contract", "value": "2", "unit": "spaces"},
            {"slot_id": "obs1", "slot_origin": "output_observed", "rule_family_signal": "setback",
             "gis_contract_relevance": "run_observed", "value": "3", "unit": "m"},
        ]

    def test_scored_excludes_noise_observed_and_outside_contract(self) -> None:
        slots = self._ledger()
        scored = {s["slot_id"] for s in slots if slot_is_scored(s)}
        self.assertEqual(scored, {"c1", "c2", "c3"})

    def test_distinct_legal_dedup_collapses_repeated_value(self) -> None:
        slots = self._ledger()
        slots_by_id = {s["slot_id"]: s for s in slots}
        # The verified rule mapped only to the OUTPUT-OBSERVED coordinate (corpus
        # table index missed the cell); it must still credit the corpus slot it
        # legally matches, and the de-circularized denominator excludes observed.
        slot_status = {
            "verified_slot_ids": {"obs1"},
            "review_slot_ids": set(),
            "candidate_slot_ids": {"obs1"},
        }
        metrics = compute_scored_slot_metrics(slots_by_id, slot_status)
        self.assertEqual(metrics["distinct_scored_legal_slot_count"], 2)  # (setback,3,m)+(height,10,m)
        self.assertEqual(metrics["scored_verified_slot_count"], 1)  # setback 3 m credited via legal key
        self.assertEqual(metrics["observed_supplement_slot_count"], 1)
        self.assertEqual(metrics["source_denominator_slot_count"], 5)
        self.assertNotIn("obs1", {legal_slot_key(slots_by_id[s]) for s in ("c1", "c2", "c3")})


class DeterministicDuplicateKeeperTests(unittest.TestCase):
    def test_keeper_is_lowest_rule_id_regardless_of_order(self) -> None:
        forward = slot_duplicate_summary(
            [{"slot_id": "s1", "rule_id": "b"}, {"slot_id": "s1", "rule_id": "a"}]
        )
        reverse = slot_duplicate_summary(
            [{"slot_id": "s1", "rule_id": "a"}, {"slot_id": "s1", "rule_id": "b"}]
        )
        self.assertEqual(forward["duplicate_verified_slots"][0]["keeper_rule_id"], "a")
        self.assertEqual(reverse["duplicate_verified_slots"][0]["keeper_rule_id"], "a")


class ComplianceHeritageTests(unittest.TestCase):
    HERITAGE_IMPERVIOUS = {
        "rule_id": "imp_heritage", "rule_object": "impervious_surface", "operator": "<=",
        "value": "70", "unit": "%", "constraint_scope": "impervious_surface", "condition": "heritage lots",
    }

    def test_heritage_lot_passes_verified_heritage_impervious_and_reviews_unverified_coverage(self) -> None:
        case = {
            "case_id": "heritage",
            "proposal": {"is_heritage_lot": True, "lot_coverage_percent": 61, "impervious_surface_percent": 69},
            "expected_decision": "needs_review",
        }
        result = evaluate_case(case, [self.HERITAGE_IMPERVIOUS], [])
        self.assertEqual(result["decision"], "needs_review")
        self.assertEqual(result["actual_review_checks"], ["lot_coverage_percent"])
        self.assertNotIn("impervious_surface_percent", result["actual_review_checks"])

    def test_heritage_lot_never_approved_against_non_heritage_rule(self) -> None:
        # A general (non-heritage) coverage rule must NOT be applied to a heritage
        # lot: symmetric gating forces review, never approval.
        non_heritage = {
            "rule_id": "imp_general", "rule_object": "impervious_surface", "operator": "<=",
            "value": "60", "unit": "%", "constraint_scope": "impervious_surface", "condition": "",
        }
        case = {
            "case_id": "heritage_guard",
            "proposal": {"is_heritage_lot": True, "impervious_surface_percent": 55},
            "expected_decision": "needs_review",
        }
        result = evaluate_case(case, [non_heritage], [])
        self.assertNotEqual(result["decision"], "approved")
        self.assertIn("impervious_surface_percent", result["actual_review_checks"])


class NativeExtractionNormalizationTests(unittest.TestCase):
    def test_comma_thousands_not_truncated(self) -> None:
        self.assertEqual(_normalize_value("1,234.5"), "1234.5")

    def test_sq_m_period_without_space_canonicalizes(self) -> None:
        # 'sq.m' used to collapse to 'sqm' which matched no alias.
        self.assertEqual(_normalize_unit("sq.m"), _normalize_unit("sq m"))


class RangeRewriteBoundaryTests(unittest.TestCase):
    def test_range_rewrite_ignores_dotted_section_number(self) -> None:
        specs = DEFAULT_NORMALIZATION["range_rewrites"]
        # A dotted section number like "101.5 to 6" must not be mistaken for a
        # dwelling-unit range and rewrite the value.
        self.assertIsNone(
            range_upper_bound_rewrite("dwelling_units", "see 101.5 to 6 for the following", specs)
        )

    def test_genuine_range_still_rewrites_to_max(self) -> None:
        specs = DEFAULT_NORMALIZATION["range_rewrites"]
        rewrite = range_upper_bound_rewrite("dwelling_units", "5 to 6 units permitted", specs)
        self.assertIsNotNone(rewrite)
        self.assertEqual(rewrite["value"], 6)


class VerifierOperatorParentTests(unittest.TestCase):
    def test_operator_parent_anchors_on_value_window_not_first_occurrence(self) -> None:
        # The page repeats the value 10. The FIRST occurrence sits in a 'maximum'
        # sentence for a different rule; this candidate's own clause (the window)
        # has no operator, so the borrowed 'maximum' must not ground it.
        candidate = {"value": "10", "operator": "<="}
        support = "The maximum height is 10 m. The required separation is 10 m."
        window = "The required separation is 10 m"
        self.assertFalse(_value_has_same_sentence_operator_parent(candidate, support, window))

    def test_operator_parent_recovers_when_window_is_the_max_sentence(self) -> None:
        candidate = {"value": "10", "operator": "<="}
        support = "The maximum height is 10 m. The required separation is 10 m."
        window = "The maximum height is 10 m"
        self.assertTrue(_value_has_same_sentence_operator_parent(candidate, support, window))


class ExceptionBranchTests(unittest.TestCase):
    def test_partial_exception_group_match_does_not_resolve_base(self) -> None:
        # Candidate carries the BASE value but partially names the exception group
        # (2 of 3 words). It must stay unresolved (review), not take the general
        # value, because a loose claim blocks base resolution.
        candidate = {"value": "3.0", "condition": "accessory detached buildings", "applies_to": ""}
        table_text = "3.0 m, except 1.5 m for accessory detached structures"
        self.assertFalse(_exception_branch_resolved(candidate, table_text))

    def test_full_exception_group_match_resolves_alt(self) -> None:
        candidate = {"value": "1.5", "condition": "accessory detached structures", "applies_to": ""}
        table_text = "3.0 m, except 1.5 m for accessory detached structures"
        self.assertTrue(_exception_branch_resolved(candidate, table_text))

    def test_compound_unit_except_clause_matches(self) -> None:
        # 'm2' between value and comma must not break the except-clause match.
        candidate = {"value": "100", "condition": "", "applies_to": ""}
        table_text = "100 m2, except 50 m2 for accessory buildings"
        # Base value with NO exception-group claim resolves.
        self.assertTrue(_exception_branch_resolved(candidate, table_text))


if __name__ == "__main__":
    unittest.main()
