"""Tests for the structured-applicability parser and the matrix-anchor layer.

The geometry tests run against the real cached Burnaby PDF and skip when it
is absent (source.pdf is gitignored); everything else uses synthetic data so
the suite stays green on a fresh clone.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from burnaby_prototype.applicability import (  # noqa: E402
    applicability_slug,
    parse_applicability,
    selector_matches_text,
    vocabulary_from_normalization,
)
from burnaby_prototype.normalization_rules import DEFAULT_NORMALIZATION  # noqa: E402
from burnaby_prototype.table_matrix import anchor_evidence, build_page_matrices  # noqa: E402


VOCAB = vocabulary_from_normalization(DEFAULT_NORMALIZATION)
SOURCE_PDF = ROOT / "data" / "bylaws" / "burnaby_r1" / "source.pdf"


class ParseApplicabilityTests(unittest.TestCase):
    def test_dwelling_type_with_unit_range(self) -> None:
        block = parse_applicability(
            {"applies_to": "Small-Scale Multi-Unit (1 to 2 Units)", "condition": "Lots <= 567 m2"},
            VOCAB,
        )
        self.assertEqual(
            block["selectors"],
            [{"dwelling_type": "small_scale_multi_unit", "unit_range": {"min": 1, "max": 2}}],
        )
        self.assertEqual(
            block["qualifiers"],
            [{"type": "lot_area_threshold", "comparator": "<=", "value": 567.0, "unit": "m2", "source": "condition"}],
        )
        self.assertEqual(applicability_slug(block), "ssmu_1_2u")

    def test_semicolon_union_yields_two_selectors(self) -> None:
        # The impervious-surface row spans Rowhouse AND the 5-6 column; the
        # extracted applies_to joins them with a semicolon and BOTH columns
        # must survive as selectors.
        block = parse_applicability(
            {"applies_to": "Rowhouse; Small-Scale Multi-Unit (5 to 6 Units)", "condition": ""},
            VOCAB,
        )
        self.assertEqual(len(block["selectors"]), 2)
        self.assertEqual(block["selectors"][0], {"dwelling_type": "rowhouse"})
        self.assertEqual(
            block["selectors"][1],
            {"dwelling_type": "small_scale_multi_unit", "unit_range": {"min": 5, "max": 6}},
        )

    def test_overlay_qualifiers(self) -> None:
        block = parse_applicability(
            {
                "applies_to": "Small-Scale Multi-Unit (5 to 6 Units)",
                "condition": "Frequent Transit Network Area Only",
            },
            VOCAB,
        )
        self.assertIn(
            {"type": "overlay", "name": "frequent_transit_network_area", "source": "condition"},
            block["qualifiers"],
        )

    def test_prose_rules_parse_to_none(self) -> None:
        # Selector-less candidates must yield None — that is what guarantees
        # the verifier adds ZERO new gaps for every currently-verified rule.
        self.assertIsNone(
            parse_applicability({"applies_to": "Rear Principal Buildings", "condition": "sloping roof"}, VOCAB)
        )

    def test_empty_vocabulary_keeps_layer_inert_for_dwelling_types(self) -> None:
        block = parse_applicability(
            {"applies_to": "Small-Scale Multi-Unit (1 to 2 Units)", "condition": ""},
            {"dwelling_types": {}, "overlays": {}},
        )
        # The generic unit-range grammar still parses, but no dwelling type
        # is recognized without city vocabulary.
        self.assertEqual(block["selectors"], [{"unit_range": {"min": 1, "max": 2}}])

    def test_units_only_form(self) -> None:
        block = parse_applicability({"applies_to": "4 Units Only", "condition": ""}, VOCAB)
        self.assertEqual(block["selectors"], [{"unit_range": {"exact": 4}}])


class SelectorMatchTests(unittest.TestCase):
    def test_matches_band_header_with_pipe_separators(self) -> None:
        # Header stacks join lines with " | " — "1 to 2 | Units" must still
        # satisfy the unit-range grammar.
        selector = {"dwelling_type": "small_scale_multi_unit", "unit_range": {"min": 1, "max": 2}}
        header = "Dwelling Type | Small-Scale Multi-Unit | 1 to 2 | Units"
        self.assertTrue(selector_matches_text(selector, header, VOCAB))

    def test_wrong_unit_range_does_not_match(self) -> None:
        selector = {"dwelling_type": "small_scale_multi_unit", "unit_range": {"min": 1, "max": 2}}
        header = "Small-Scale Multi-Unit | 5 to 6 Units | Frequent Transit | Network Area Only"
        self.assertFalse(selector_matches_text(selector, header, VOCAB))

    def test_wrong_dwelling_type_does_not_match(self) -> None:
        selector = {"dwelling_type": "rowhouse"}
        header = "Small-Scale Multi-Unit | 1 to 2 | Units"
        self.assertFalse(selector_matches_text(selector, header, VOCAB))


class AnchorEvidenceTests(unittest.TestCase):
    MATRICES = {
        2: [
            {
                "page": 2,
                "bands": [
                    {"key": 0, "header_text": "Rowhouse | 1 to 3 | Units"},
                    {"key": 1, "header_text": "Small-Scale Multi-Unit | 1 to 2 | Units"},
                ],
                "rows": [
                    {
                        "label": "Maximum Lot Coverage | All Buildings",
                        "label_words": {"lot", "coverage", "building"},
                        "cells": {
                            0: {"text": "55%", "numbers": [55.0], "branches": [], "spans_all": False},
                            1: {"text": "40%", "numbers": [40.0], "branches": [], "spans_all": False},
                        },
                    },
                    {
                        "label": "Maximum Height | Front Principal Buildings | Height",
                        "label_words": {"height", "front", "principal", "building"},
                        "cells": {
                            0: {"text": "10 m", "numbers": [10.0], "branches": [], "spans_all": True},
                        },
                    },
                ],
            }
        ]
    }

    def test_unique_match_attaches_anchor(self) -> None:
        evidence = [
            {
                "evidence_id": "ev1",
                "evidence_type": "table_cell",
                "table_title": "Maximum Lot Coverage",
                "row_header": "All Buildings",
            }
        ]
        report = anchor_evidence(evidence, self.MATRICES)
        self.assertEqual(report["anchored"], 1)
        anchor = evidence[0]["matrix_anchor"]
        self.assertEqual(anchor["row_label"], "Maximum Lot Coverage | All Buildings")
        self.assertEqual([band["key"] for band in anchor["bands"]], [0, 1])
        self.assertEqual(anchor["bands"][0]["numbers"], [55.0])

    def test_ambiguous_match_attaches_nothing(self) -> None:
        evidence = [
            {
                "evidence_id": "ev1",
                "evidence_type": "table_cell",
                "table_title": "",
                # 'building' alone matches BOTH rows -> must stay un-anchored.
                "row_header": "Buildings",
            }
        ]
        report = anchor_evidence(evidence, self.MATRICES)
        self.assertEqual(report["anchored"], 0)
        self.assertEqual(report["ambiguous_skipped"], 1)
        self.assertNotIn("matrix_anchor", evidence[0])

    def test_prose_evidence_is_ignored(self) -> None:
        evidence = [
            {
                "evidence_id": "ev1",
                "evidence_type": "clause",
                "table_title": "Maximum Lot Coverage",
                "row_header": "All Buildings",
            }
        ]
        report = anchor_evidence(evidence, self.MATRICES)
        self.assertEqual(report["anchored"], 0)
        self.assertNotIn("matrix_anchor", evidence[0])


@unittest.skipUnless(SOURCE_PDF.exists(), "cached Burnaby source.pdf not present")
class RealPdfGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrices = build_page_matrices(SOURCE_PDF)

    def test_101_4_matrix_recovered(self) -> None:
        self.assertIn(2, self.matrices)
        matrix = self.matrices[2][0]
        self.assertEqual(len(matrix["bands"]), 4)
        # Band 3 is the FTN-only 5-6 unit column.
        self.assertIn("frequent transit", matrix["bands"][3]["header_text"].lower())
        self.assertIn("5 to 6", matrix["bands"][3]["header_text"].lower())
        # Bands 1-3 carry the Small-Scale Multi-Unit phrase (rendered once,
        # spanning three columns).
        for key in (1, 2, 3):
            self.assertIn("small-scale multi-unit", matrix["bands"][key]["header_text"].lower(), key)

    def test_lot_coverage_row_with_conditional_cell(self) -> None:
        matrix = self.matrices[2][0]
        row = next(r for r in matrix["rows"] if "Lot Coverage" in r["label"] and "All Buildings" in r["label"])
        self.assertEqual(row["cells"][0]["numbers"], [55.0])
        branches = row["cells"][1]["branches"]
        self.assertEqual(len(branches), 2)
        self.assertEqual(branches[0]["threshold"], 567.0)
        self.assertEqual(branches[0]["numbers"], [40.0])
        self.assertEqual(branches[1]["comparator"], ">")
        self.assertEqual(branches[1]["numbers"], [30.0])
        self.assertEqual(row["cells"][2]["numbers"], [40.0])
        self.assertEqual(row["cells"][3]["numbers"], [45.0])

    def test_impervious_row(self) -> None:
        matrix = self.matrices[2][0]
        row = next(r for r in matrix["rows"] if "Impervious" in r["label"])
        self.assertEqual(
            [row["cells"][key]["numbers"] for key in (0, 1, 2, 3)],
            [[70.0], [60.0], [60.0], [70.0]],
        )

    def test_spanning_height_cell(self) -> None:
        matrix = self.matrices[2][0]
        row = next(r for r in matrix["rows"] if "Front Principal" in r["label"] and r["label"].endswith("Height"))
        for key in (0, 1, 2, 3):
            self.assertIn(10.0, row["cells"][key]["numbers"])
            self.assertTrue(row["cells"][key]["spans_all"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# End-to-end verifier behavior with a (synthetic) matrix anchor attached.
# These mirror the adversarial pins: geometry must refute cross-column lies,
# hold dropped qualifiers, and stay inert without an anchor.
# ---------------------------------------------------------------------------

from burnaby_prototype.config import load_config  # noqa: E402
from burnaby_prototype.verification import verify_candidates  # noqa: E402

CONFIG = load_config(ROOT / "configs" / "burnaby_r1.json")

COVERAGE_ANCHOR = {
    "page": 2,
    "row_label": "Maximum Lot Coverage | All Buildings",
    "bands": [
        {"key": 0, "header_text": "Rowhouse | 1 to 3 | Units", "text": "55%", "numbers": [55.0], "branches": [], "spans_all": False},
        {
            "key": 1,
            "header_text": "Small-Scale Multi-Unit | 1 to 2 | Units",
            "text": "Lots < 567 m2: 40%\nLots > 567 m2: 30%",
            "numbers": [567.0, 40.0, 567.0, 30.0],
            "branches": [
                {"condition_text": "Lots < 567 m2", "comparator": "<=", "threshold": 567.0, "value_text": "40%", "numbers": [40.0]},
                {"condition_text": "Lots > 567 m2", "comparator": ">", "threshold": 567.0, "value_text": "30%", "numbers": [30.0]},
            ],
            "spans_all": False,
        },
        {"key": 2, "header_text": "Small-Scale Multi-Unit | 3 to 4 | Units", "text": "40%", "numbers": [40.0], "branches": [], "spans_all": False},
        {
            "key": 3,
            "header_text": "Small-Scale Multi-Unit | 5 to 6 Units | Frequent Transit | Network Area Only",
            "text": "45%",
            "numbers": [45.0],
            "branches": [],
            "spans_all": False,
        },
    ],
}


def _coverage_evidence(anchor: bool = True, cell_value: str = "55 %") -> dict:
    # cell_value follows the candidate under test: in the real pipeline each
    # candidate cites evidence whose cell carries ITS value — these tests are
    # about what the COLUMN binding does once the plain value check passes.
    evidence = {
        "evidence_id": "matrix_ev_001",
        "page": 2,
        "evidence_type": "table_cell",
        "evidence_text": f"Maximum Lot Coverage | All Buildings | {cell_value}",
        "source_context": "Maximum Lot Coverage All Buildings 55% Lots < 567 m2: 40% Lots > 567 m2: 30% 40% 45%",
        "table_title": "Maximum Lot Coverage",
        "row_header": "All Buildings",
        "column_header": "Rowhouse",
        "cell_value": cell_value,
    }
    if anchor:
        evidence["matrix_anchor"] = COVERAGE_ANCHOR
    return evidence


def _coverage_candidate(value: str, applies_to: str, condition: str = "") -> dict:
    return {
        "candidate_id": "matrix_cand_001",
        "evidence_id": "matrix_ev_001",
        "rule_object": "lot_coverage",
        "constraint_type": "maximum",
        "constraint_scope": "lot",
        "applies_to": applies_to,
        "condition": condition,
        "operator": "<=",
        "value": value,
        "unit": "%",
        "extraction_method": "deterministic_table_evidence",
    }


class MatrixBindingVerifierTests(unittest.TestCase):
    def _decide(self, evidence: dict, candidate: dict) -> dict:
        result = verify_candidates(CONFIG, [evidence], [candidate])
        rules = result["verified_rules"] + result["review_needed"]
        self.assertEqual(len(rules), 1)
        return rules[0]

    def test_correct_column_claim_verifies(self) -> None:
        rule = self._decide(_coverage_evidence(), _coverage_candidate("55", "Rowhouse"))
        self.assertEqual(rule["verification_decision"], "verified", rule["support_gaps"])
        self.assertEqual(rule["matrix_bands"], [0])

    def test_cross_column_value_is_rejected(self) -> None:
        # 55% claimed for the 5-6 unit column whose cell says 45% — geometry
        # refutes what word overlap cannot (the page contains all the words).
        rule = self._decide(
            _coverage_evidence(),
            _coverage_candidate("55", "Small-Scale Multi-Unit (5 to 6 Units)", "Frequent Transit Network Area Only"),
        )
        self.assertIn("column_value_mismatch", rule["support_gaps"])
        self.assertEqual(rule["verification_decision"], "rejected")

    def test_dropped_overlay_qualifier_is_held(self) -> None:
        # 45% really is the 5-6 column's value, but that column is Frequent
        # Transit Network Area ONLY — claiming it without the condition reads
        # a conditional permission as unconditional.
        rule = self._decide(
            _coverage_evidence(cell_value="45 %"),
            _coverage_candidate("45", "Small-Scale Multi-Unit (5 to 6 Units)"),
        )
        self.assertIn("column_qualifier_not_claimed", rule["support_gaps"])
        self.assertEqual(rule["verification_decision"], "review_needed")

    def test_collapsed_conditional_cell_is_held(self) -> None:
        # 40% is one BRANCH of a lot-size-conditional cell; claiming it
        # without "Lots <= 567 m2" erases the condition.
        rule = self._decide(
            _coverage_evidence(cell_value="40 %"),
            _coverage_candidate("40", "Small-Scale Multi-Unit (1 to 2 Units)"),
        )
        self.assertIn("conditional_cell_condition_missing", rule["support_gaps"])
        self.assertEqual(rule["verification_decision"], "review_needed")

    def test_conditional_branch_with_condition_verifies(self) -> None:
        rule = self._decide(
            _coverage_evidence(cell_value="40 %"),
            _coverage_candidate("40", "Small-Scale Multi-Unit (1 to 2 Units)", "Lots <= 567 m2"),
        )
        self.assertEqual(rule["verification_decision"], "verified", rule["support_gaps"])

    def test_row_family_mismatch_is_held(self) -> None:
        # The Impervious Surfaces sub-row extracted under the section banner's
        # family (lot_coverage): the row label names a different family, so
        # the bind refuses even though the value sits in the claimed band.
        evidence = _coverage_evidence()
        evidence["matrix_anchor"] = {
            "page": 2,
            "row_label": "Maximum Lot Coverage | Impervious Surfaces",
            "bands": [
                {"key": 0, "header_text": "Rowhouse | 1 to 3 | Units", "text": "70%", "numbers": [70.0], "branches": [], "spans_all": False},
                {"key": 3, "header_text": "Small-Scale Multi-Unit | 5 to 6 Units", "text": "70%", "numbers": [70.0], "branches": [], "spans_all": False},
            ],
        }
        evidence["cell_value"] = "70 %"
        evidence["evidence_text"] = "Maximum Lot Coverage | Impervious Surfaces | 70 %"
        rule = self._decide(evidence, _coverage_candidate("70", "Rowhouse"))
        self.assertIn("anchored_row_family_mismatch", rule["support_gaps"])
        self.assertNotEqual(rule["verification_decision"], "verified")

    def test_without_anchor_layer_is_inert(self) -> None:
        # No matrix anchor -> the legacy gates decide exactly as before and
        # the binding adds nothing: no matrix_bands, no anchor-derived gaps.
        # Under the SSMUH-targeted burnaby_r1 config the Rowhouse column is
        # in target scope (gold br1_cov_001), so the legacy structured-table
        # gates verify this fully consistent cell with or without geometry.
        rule = self._decide(_coverage_evidence(anchor=False), _coverage_candidate("55", "Rowhouse"))
        self.assertEqual(rule["verification_decision"], "verified")
        self.assertIsNone(rule.get("matrix_bands"))
        self.assertFalse(
            {"applicability_not_grounded", "column_qualifier_not_claimed", "anchored_row_family_mismatch"}
            & set(rule.get("support_gaps") or [])
        )
