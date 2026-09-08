"""MVP report status labels must stay honest."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_mvp_verification import (  # noqa: E402
    CURRENT_PRODUCT_RUNS,
    LEGACY_REFERENCE_RUNS,
    M4_PRODUCT_RUNS,
    V3_PRODUCT_RUNS,
    display_command,
    m4_promotion_status,
    not_used_summary,
    overall_status_for_rows,
    render_markdown,
    status_label,
    v3_promotion_status,
)


class MvpStatusLabelTests(unittest.TestCase):
    def test_false_verified_is_unsafe_even_if_other_metrics_look_good(self) -> None:
        self.assertEqual(
            status_label(
                {
                    "false_verified_count": 1,
                    "quality_gate_passed": True,
                    "candidate_recall": 1.0,
                }
            ),
            "unsafe / needs fix",
        )

    def test_false_approval_is_unsafe(self) -> None:
        self.assertEqual(
            status_label(
                {
                    "false_verified_count": 0,
                    "false_approval_count": 1,
                    "quality_gate_passed": True,
                    "candidate_recall": 1.0,
                }
            ),
            "unsafe / needs fix",
        )

    def test_source_support_failure_is_unsafe(self) -> None:
        self.assertEqual(
            status_label(
                {
                    "false_verified_count": 0,
                    "verified_source_support_failed_count": 1,
                    "quality_gate_passed": True,
                    "candidate_recall": 1.0,
                }
            ),
            "unsafe / needs fix",
        )

    def test_clean_gate_pass_is_pass(self) -> None:
        self.assertEqual(
            status_label(
                {
                    "false_verified_count": 0,
                    "quality_gate_passed": True,
                    "candidate_recall": 1.0,
                }
            ),
            "pass",
        )

    def test_low_candidate_recall_is_scope_mismatch(self) -> None:
        self.assertEqual(
            status_label(
                {
                    "false_verified_count": 0,
                    "quality_gate_passed": False,
                    "candidate_recall": 0.5,
                }
            ),
            "scope mismatch",
        )

    def test_full_verified_or_review_coverage_is_not_scope_mismatch(self) -> None:
        self.assertEqual(
            status_label(
                {
                    "false_verified_count": 0,
                    "quality_gate_passed": False,
                    "candidate_recall": 0.5,
                    "verified_or_review_recall": 1.0,
                    "extraction_coverage_recall": 1.0,
                    "verified_rule_count": 2,
                    "review_rule_count": 1,
                }
            ),
            "needs review",
        )

    def test_clean_failed_gate_with_zero_verified_is_fail_closed(self) -> None:
        self.assertEqual(
            status_label(
                {
                    "false_verified_count": 0,
                    "quality_gate_passed": False,
                    "candidate_recall": 1.0,
                    "verified_rule_count": 0,
                    "review_rule_count": 4,
                }
            ),
            "fail-closed",
        )


class MvpReportSummaryTests(unittest.TestCase):
    def test_current_product_runs_use_native_m4_not_pipeline5(self) -> None:
        self.assertTrue(CURRENT_PRODUCT_RUNS)
        for run in CURRENT_PRODUCT_RUNS:
            self.assertEqual(run.lane, "native_m4")
            self.assertNotIn("P5", run.label)
            self.assertNotIn("pipeline5", str(run.output_dir).lower())

    def test_pipeline5_is_legacy_reference_only(self) -> None:
        self.assertTrue(any(run.lane == "legacy_p5" for run in LEGACY_REFERENCE_RUNS))

    def test_v3_cannot_promote_with_false_verified(self) -> None:
        v2 = [
            {"city": "burnaby_r1", "verified_or_review_recall": 0.5, "verified_rule_count": 1},
            {"city": "vancouver_rs", "verified_or_review_recall": 0.5, "verified_rule_count": 1},
            {"city": "calgary_rcg", "verified_or_review_recall": 0.5, "verified_rule_count": 1},
        ]
        v3 = [
            {
                "city": "burnaby_r1",
                "verified_or_review_recall": 0.7,
                "verified_rule_count": 2,
                "false_verified_count": 1,
                "verified_source_support_failed_count": 0,
            },
            {
                "city": "vancouver_rs",
                "verified_or_review_recall": 0.7,
                "verified_rule_count": 2,
                "false_verified_count": 0,
                "verified_source_support_failed_count": 0,
            },
            {
                "city": "calgary_rcg",
                "verified_or_review_recall": 0.7,
                "verified_rule_count": 2,
                "false_verified_count": 0,
                "verified_source_support_failed_count": 0,
            },
        ]
        status = v3_promotion_status(v3, v2, {"all_blocked": True})
        self.assertFalse(status["promoted"])
        self.assertIn("v3_safety_gate_failed", status["reasons"])

    def test_v3_requires_adversarial_report_to_promote(self) -> None:
        v2 = [
            {"city": "burnaby_r1", "verified_or_review_recall": 0.5, "verified_rule_count": 1},
            {"city": "vancouver_rs", "verified_or_review_recall": 0.5, "verified_rule_count": 1},
            {"city": "calgary_rcg", "verified_or_review_recall": 0.5, "verified_rule_count": 1},
        ]
        v3 = [
            {
                "city": row["city"],
                "verified_or_review_recall": 0.7,
                "verified_rule_count": 2,
                "false_verified_count": 0,
                "verified_source_support_failed_count": 0,
            }
            for row in v2
        ]
        status = v3_promotion_status(v3, v2, {})
        self.assertFalse(status["promoted"])
        self.assertIn("adversarial_report_missing_or_failed", status["reasons"])

    def test_v3_product_runs_are_native_only(self) -> None:
        self.assertTrue(V3_PRODUCT_RUNS)
        for run in V3_PRODUCT_RUNS:
            self.assertEqual(run.lane, "native_v3")
            self.assertNotIn("P5", run.label)

    def test_m4_product_runs_are_native_only(self) -> None:
        self.assertTrue(M4_PRODUCT_RUNS)
        for run in M4_PRODUCT_RUNS:
            self.assertEqual(run.lane, "native_m4")
            self.assertNotIn("P5", run.label)

    def _reference_rows(self) -> list[dict[str, object]]:
        return [
            {"city": "burnaby_r1", "verified_or_review_recall": 0.7, "verified_rule_count": 10},
            {"city": "vancouver_rs", "verified_or_review_recall": 0.7, "verified_rule_count": 2},
            {"city": "calgary_rcg", "verified_or_review_recall": 0.7, "verified_rule_count": 4},
        ]

    def _m4_rows(self) -> list[dict[str, object]]:
        return [
            {
                "city": row["city"],
                "verified_or_review_recall": 1.0,
                "verified_rule_count": int(row["verified_rule_count"]) + 1,
                "false_verified_count": 0,
                "verified_source_support_failed_count": 0,
                "false_approval_count": 0,
                "m4_selected_rule_like_numeric_coverage": 1.0,
            }
            for row in self._reference_rows()
        ]

    def test_m4_promotes_with_clean_safety_full_coverage_and_no_recall_loss(self) -> None:
        status = m4_promotion_status(self._m4_rows(), self._reference_rows(), {"all_blocked": True})
        self.assertTrue(status["promoted"])
        self.assertTrue(status["safety_ok"])
        self.assertTrue(status["source_coverage_ok"])
        self.assertTrue(status["no_recall_loss"])

    def test_m4_cannot_promote_with_false_verified(self) -> None:
        rows = self._m4_rows()
        rows[0]["false_verified_count"] = 1
        status = m4_promotion_status(rows, self._reference_rows(), {"all_blocked": True})
        self.assertFalse(status["promoted"])
        self.assertIn("m4_safety_gate_failed", status["reasons"])

    def test_m4_requires_full_source_coverage(self) -> None:
        rows = self._m4_rows()
        rows[1]["m4_selected_rule_like_numeric_coverage"] = 0.95
        status = m4_promotion_status(rows, self._reference_rows(), {"all_blocked": True})
        self.assertFalse(status["promoted"])
        self.assertIn("m4_source_coverage_gate_failed", status["reasons"])

    def test_m4_requires_no_recall_loss_against_v3(self) -> None:
        rows = self._m4_rows()
        rows[2]["verified_or_review_recall"] = 0.6
        status = m4_promotion_status(rows, self._reference_rows(), {"all_blocked": True})
        self.assertFalse(status["promoted"])
        self.assertIn("m4_recall_loss_against_v3", status["reasons"])

    def test_m4_requires_adversarial_report_to_promote(self) -> None:
        status = m4_promotion_status(self._m4_rows(), self._reference_rows(), {})
        self.assertFalse(status["promoted"])
        self.assertIn("adversarial_report_missing_or_failed", status["reasons"])

    def test_not_used_summary_explains_outside_target_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "not_used.json").write_text(
                json.dumps(
                    [
                        {
                            "rule_object": "setback",
                            "support_gaps": ["outside_target_section", "operator_not_supported"],
                        },
                        {
                            "rule_object": "height",
                            "support_gaps": ["outside_target_section"],
                        },
                    ]
                ),
                encoding="utf-8",
            )

            summary = not_used_summary(output_dir)

        self.assertEqual(summary["count"], 2)
        self.assertIn("outside the configured target sections", summary["plain_explanation"])
        self.assertEqual(summary["top_reasons"][0]["reason"], "outside_target_section")

    def test_markdown_includes_not_used_explanation(self) -> None:
        report = {
            "overall_status": "mvp_safety_ready",
            "safety_contract": "contract",
            "pdf_inventory": [],
            "current_path_version": "native_m4",
            "current_runs": [
                {
                    "label": "Calgary M4",
                    "city": "calgary_rcg",
                    "candidate_rule_count": 10,
                    "verified_rule_count": 1,
                    "review_rule_count": 2,
                    "rejected_rule_count": 0,
                    "not_used_rule_count": 7,
                    "verified_precision": 1.0,
                    "false_verified_count": 0,
                    "verified_or_review_recall": 1.0,
                    "status_label": "pass",
                    "not_used_summary": {
                        "count": 7,
                        "plain_explanation": "These are outside the configured target sections.",
                        "top_reasons": [{"label": "Outside target section", "count": 7}],
                        "top_rule_families": [{"rule_family": "Setback", "count": 5}],
                    },
                }
            ],
            "m4_promotion": {},
            "v3_promotion": {},
            "v3_experimental_runs": [],
            "v2_reference_runs": [],
            "legacy_references": [],
            "v2_discovery": [],
            "m4_discovery": [],
            "v2_model_runs": [],
            "v3_model_runs": [],
            "m4_model_runs": [],
            "interpretation": [],
        }

        markdown = render_markdown(report)

        self.assertIn("Out-of-scope / Not-used Explanation", markdown)
        self.assertIn("outside the configured target sections", markdown)

    def test_overall_status_uses_any_unsafe_status_label(self) -> None:
        self.assertEqual(
            overall_status_for_rows(
                [
                    {"label": "clean", "status_label": "pass"},
                    {"label": "bad", "status_label": "unsafe / needs fix"},
                ]
            ),
            "unsafe_needs_fix",
        )

    def test_scope_mismatch_is_reported_when_safety_is_clean(self) -> None:
        self.assertEqual(
            overall_status_for_rows(
                [
                    {"label": "burnaby", "status_label": "scope mismatch"},
                    {"label": "vancouver", "status_label": "pass"},
                ]
            ),
            "safety_mvp_extraction_gap",
        )

    def test_clean_rows_are_safety_ready(self) -> None:
        self.assertEqual(
            overall_status_for_rows(
                [
                    {"label": "vancouver", "status_label": "pass"},
                    {"label": "calgary", "status_label": "pass"},
                ]
            ),
            "mvp_safety_ready",
        )

    def test_report_displays_local_python_command(self) -> None:
        self.assertTrue(display_command([sys.executable, "scripts/run_mvp_verification.py"]).startswith(".venv/bin/python "))


if __name__ == "__main__":
    unittest.main()
