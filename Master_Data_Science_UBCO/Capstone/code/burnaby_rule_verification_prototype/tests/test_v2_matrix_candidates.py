"""Tests for the V2.1 deterministic matrix-table candidate emitter.

The emitter is the V2 recall fix for table-heavy bylaws: it reuses the
production band geometry to PROPOSE one candidate per matrix cell. The
verifier still proves each, so these tests pin (a) the count-qualifier guard
that prevented a false-verify ("4 Units Only: 281 m2" -> 281, never 4), and
(b) the real-PDF end-to-end recall + false_verified=0 when present.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from burnaby_prototype.v2_matrix_candidates import _cell_value_emissions, _family_plausible_numbers

SOURCE_PDF = ROOT / "data" / "bylaws" / "burnaby_r1" / "source.pdf"


class CountQualifierGuardTests(unittest.TestCase):
    def test_count_glued_number_skipped_for_non_count_family(self) -> None:
        # "4 Units Only: 281 m2" — the 4 is a dwelling-count qualifier, NOT a
        # lot-area value. lot_area must emit 281, never 4 (that was a real
        # false-verify before the guard).
        self.assertEqual(_family_plausible_numbers("4 Units Only: 281 m2", "lot_area"), [281.0])

    def test_count_glued_number_kept_for_count_family(self) -> None:
        # For dwelling_units the count IS the value.
        self.assertEqual(_family_plausible_numbers("4 Units Only", "dwelling_units"), [4.0])

    def test_conditional_cell_emits_per_branch_value(self) -> None:
        cell = {
            "text": "Lots < 567 m2: 40%\nLots > 567 m2: 30%",
            "numbers": [567.0, 40.0, 567.0, 30.0],
            "branches": [
                {"condition_text": "Lots < 567 m2", "comparator": "<=", "threshold": 567.0, "value_text": "40%", "numbers": [40.0]},
                {"condition_text": "Lots > 567 m2", "comparator": ">", "threshold": 567.0, "value_text": "30%", "numbers": [30.0]},
            ],
        }
        out = _cell_value_emissions(cell, "lot_coverage")
        self.assertEqual([v for v, _, _ in out], [40.0, 30.0])
        self.assertEqual([token for _, _, token in out], ["40", "30"])
        self.assertTrue(all("567" in cond for _, cond, _ in out))

    def test_plain_cell_emits_first_plausible_number(self) -> None:
        self.assertEqual(_cell_value_emissions({"text": "55%", "numbers": [55.0], "branches": []}, "lot_coverage"),
                         [(55.0, "", "55")])

    def test_plain_metric_cell_preserves_decimal_source_token(self) -> None:
        self.assertEqual(_cell_value_emissions({"text": "4.0 m | 1 storey", "numbers": [4.0, 1.0], "branches": []}, "height"),
                         [(4.0, "", "4.0")])

    def test_labeled_metric_cell_emits_each_branch_with_condition(self) -> None:
        out = _cell_value_emissions({"text": "front: 4.0 m | flanking: 3.0 m", "numbers": [4.0, 3.0], "branches": []}, "setback")
        self.assertEqual(out, [(4.0, "front", "4.0"), (3.0, "flanking", "3.0")])

    def test_storey_family_reads_storey_value_not_height_value(self) -> None:
        self.assertEqual(_cell_value_emissions({"text": "4.0 m | 1 storey", "numbers": [4.0, 1.0], "branches": []}, "storeys"),
                         [(1.0, "", "1")])


@unittest.skipUnless(SOURCE_PDF.exists(), "cached Burnaby source.pdf not present")
class RealPdfRecallTests(unittest.TestCase):
    def test_burnaby_matrix_recall_and_zero_false_verified(self) -> None:
        import json
        from burnaby_prototype.config import load_config
        from burnaby_prototype.v2_matrix_candidates import build_matrix_candidate_set
        from burnaby_prototype.slim_pipeline import run_slim_verification

        cfg = load_config(str(ROOT / "configs" / "burnaby_r1.json"))
        ev, cand = build_matrix_candidate_set(SOURCE_PDF, "burnaby_r1", cfg)
        # The flattened-table LLM path produced ~4 candidates; the matrix
        # emitter must produce many more from the same 101.4 table.
        self.assertGreaterEqual(len(cand), 40)
        out = Path(tempfile.mkdtemp())
        run_slim_verification(config_path=cfg, output_dir=out, evidence_units=ev,
                              rule_candidates=cand, input_mode="pipeline5_registry")
        verified = json.loads((out / "verified_rules.json").read_text())
        self.assertGreaterEqual(len(verified), 30)
        # No proposed matrix candidate may produce a value not in its cell:
        # every verified rule must carry no value/unit critical gap.
        for rule in verified:
            self.assertNotIn("value_not_found_in_evidence", rule.get("support_gaps", []))
        # The "4 Units Only" trap must never verify as lot_area >= 4.
        self.assertFalse(any(r["rule_object"] == "lot_area" and str(r["value"]) == "4" for r in verified))


if __name__ == "__main__":
    unittest.main()
