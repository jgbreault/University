"""Module-level tests for the dashboard's gap/coverage/matrix/portfolio views.

Follows the test_dashboard_v2 pattern: load the dashboard as a module (no
streamlit import at test time — every function under test is pure data prep)
and pin behavior against BOTH synthetic fixtures and the real Burnaby outputs
when present.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "dashboard" / "streamlit_app.py"
BURNABY_DIR = ROOT / "outputs" / "burnaby_r1_slim_pipeline5_registry"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module("dashboard_gap_views", DASHBOARD_PATH)


class FunnelTests(unittest.TestCase):
    def test_funnel_reconciles_against_real_burnaby_outputs(self) -> None:
        if not (BURNABY_DIR / "rule_candidates.json").exists():
            self.skipTest("canonical outputs not generated")
        data = MODULE.load_output_data(BURNABY_DIR)
        stages = MODULE.funnel_stages(data)
        self.assertEqual(stages[0]["count"], len(data["rule_candidates"]))
        self.assertEqual(stages[-1]["count"], len(data["verified"]))
        # Monotone non-increasing counts; each stage's drop is explained.
        counts = [stage["count"] for stage in stages]
        self.assertEqual(counts, sorted(counts, reverse=True))
        bucket_total = sum(len(data[key]) for key in ("verified", "review", "rejected", "not_used"))
        self.assertEqual(stages[0]["count"], bucket_total)

    def test_policy_holds_are_a_parking_lot_not_a_loss(self) -> None:
        data = {
            "rule_candidates": [{} for _ in range(4)],
            "verified": [{"rule_id": "v"}],
            "review": [
                {"rule_id": "r1", "support_gaps": ["text_candidate_requires_review"]},
                {"rule_id": "r2", "support_gaps": ["applies_to_not_supported", "text_candidate_requires_review"]},
            ],
            "rejected": [{"rule_id": "x", "support_gaps": ["value_not_found_in_evidence"]}],
            "not_used": [],
        }
        stages = MODULE.funnel_stages(data)
        by_key = {stage["stage"]: stage for stage in stages}
        # r2 dies at fields-proven (it has a FIELD gap); r1 is held by policy only.
        self.assertEqual(by_key["fields_proven"]["dropped"], 1)
        self.assertEqual(by_key["verified"]["dropped"], 1)
        self.assertEqual(by_key["verified"]["outflow_status"], "held")


class ApplicabilityBucketTests(unittest.TestCase):
    def test_prefers_structured_applicability_block(self) -> None:
        rule = {
            "applies_to": "lot",  # normalized away — must NOT be used
            "applicability": {
                "selectors": [
                    {"dwelling_type": "small_scale_multi_unit", "unit_range": {"min": 1, "max": 2}}
                ]
            },
        }
        self.assertEqual(MODULE.applicability_buckets(rule), {"ssmu_1_2"})

    def test_text_fallback_with_footnote_suffix(self) -> None:
        rule = {"applies_to": "Rowhouse .1", "condition": ""}
        self.assertEqual(MODULE.applicability_buckets(rule), {"rowhouse"})

    def test_ftn_condition_maps_to_5_6_column(self) -> None:
        rule = {"applies_to": "", "condition": "Frequent Transit Network Area Only"}
        self.assertEqual(MODULE.applicability_buckets(rule), {"ssmu_5_6_ftn"})

    def test_no_dwelling_signal_spans_all_columns(self) -> None:
        rule = {"applies_to": "All Buildings", "condition": "sloping roof"}
        self.assertEqual(
            MODULE.applicability_buckets(rule), {key for key, _ in MODULE.MATRIX_COLUMNS}
        )


class MatrixCellsTests(unittest.TestCase):
    def test_precedence_and_missing_honesty(self) -> None:
        verified = [
            {"rule_id": "v1", "rule_object": "lot_coverage", "value": "55", "unit": "%",
             "applies_to": "Rowhouse", "condition": "", "support_gaps": []}
        ]
        review = [
            {"rule_id": "r1", "rule_object": "lot_coverage", "value": "40", "unit": "%",
             "applies_to": "Small-Scale Multi-Unit (1 to 2 Units)", "condition": "",
             "support_gaps": ["conditional_cell_condition_missing"]}
        ]
        gold = [
            {"gold_id": "g1", "rule_object": "lot_coverage", "value": 45, "unit": "%",
             "applies_to": "Small-Scale Multi-Unit (5 to 6 Units)",
             "condition": "Frequent Transit Network Area Only"}
        ]
        grid = MODULE.matrix_cells(verified, review, gold)
        row = grid["rows"][0]
        statuses = [cell["status"] for cell in row["cells"]]
        # verified > review > gold-missing; the 3-4 column has NO gold claim
        # and must be honest "na", never "missing".
        self.assertEqual(statuses, ["verified", "review", "na", "missing"])

    def test_matrix_table_html_is_renderable_markup(self) -> None:
        grid = {
            "columns": ["A", "B"],
            "rows": [
                {"label": "Lot coverage", "cells": [
                    {"status": "verified", "text": "55 %", "rule_id": "v1", "reason": ""},
                    {"status": "na", "text": "n/a", "rule_id": "", "reason": ""},
                ]}
            ],
        }
        markup = MODULE.matrix_table_html(grid)
        self.assertIn("matrix-table", markup)
        self.assertIn("status-verified", markup)
        self.assertIn("status-na", markup)
        self.assertIn("55 %", markup)


class BucketCountConsistencyTests(unittest.TestCase):
    def test_kpi_counts_follow_loaded_lists_not_stale_validation_report(self) -> None:
        data = {
            "verified": [{"rule_id": "v1"}, {"rule_id": "v2"}],
            "review": [{"rule_id": "r1"}],
            "rejected": [],
            "not_used": [],
            # Stale/divergent validation report (e.g. from an older pipeline run).
            "validation": {"bucket_counts": {"verified": 99, "review_needed": 99, "rejected": 99, "not_used": 99}},
        }
        counts = MODULE.output_bucket_counts(data)
        self.assertEqual(counts["verified"], 2)
        self.assertEqual(counts["review_needed"], 1)
        self.assertEqual(counts["rejected"], 0)

    def test_kpi_counts_fall_back_to_validation_when_list_absent(self) -> None:
        data = {"validation": {"bucket_counts": {"verified": 5, "review_needed": 3, "rejected": 1, "not_used": 0}}}
        counts = MODULE.output_bucket_counts(data)
        self.assertEqual(counts["verified"], 5)
        self.assertEqual(counts["review_needed"], 3)


class CoverageAndGoldGapTests(unittest.TestCase):
    def test_against_real_burnaby_outputs(self) -> None:
        gold_path = MODULE.gold_path_for(BURNABY_DIR)
        if not gold_path:
            self.skipTest("gold not present")
        data = MODULE.load_output_data(BURNABY_DIR)
        gold = json.loads(gold_path.read_text())
        rows = MODULE.coverage_rows(data, gold, data["benchmark"])
        total_gold = sum(row["gold"] for row in rows)
        self.assertEqual(total_gold, len(gold))
        coverage_families = {row["family"] for row in rows if row["gold"]}
        self.assertIn("Lot coverage", coverage_families)
        gaps = MODULE.gold_gap_rows(data["benchmark"], gold)
        # Every gap row is one of the three honest states.
        self.assertTrue(all(gap["status"] in {"review", "absent", "unproven"} for gap in gaps))
        # Gold rows the benchmark matched as verified never appear as gaps.
        matched = {m.get("gold_id") for m in data["benchmark"]["rule_metrics"].get("matched_verified", [])}
        self.assertFalse({gap["gold_id"] for gap in gaps} & matched)


class PortfolioTests(unittest.TestCase):
    def test_city_comparison_rows_cover_both_lanes(self) -> None:
        rows = MODULE.city_comparison_rows()
        if not rows:
            self.skipTest("no outputs")
        lanes = {(row["city"], row["lane"]) for row in rows}
        self.assertTrue(any(lane == "P5" for _, lane in lanes))
        for row in rows:
            self.assertIn("gate_status", row)
            self.assertIsNotNone(row["output_dir"])


class AssistantEnhancementTests(unittest.TestCase):
    def test_proof_trace_lines_surface_unproven_fields(self) -> None:
        rule = {
            "proof_trace": {
                "operator": {"label": "not_enough_info", "reason": "operator wording is not supported by evidence"},
                "value": {"label": "supported", "reason": "value appears in cited evidence"},
            }
        }
        lines = MODULE.proof_trace_lines(rule)
        self.assertEqual(len(lines), 1)
        self.assertIn("operator", lines[0])
        self.assertIn("not_enough_info", lines[0])

    def test_assistant_prompt_keeps_advisory_guard_and_gains_proof(self) -> None:
        packet = {
            "candidate_rule": {
                "rule_id": "r1",
                "proof_trace": {"operator": {"label": "not_enough_info", "reason": "no direction word"}},
            },
            "support_gaps": ["operator_not_supported"],
        }
        prompt = MODULE._assistant_prompt(packet, "why held?")
        self.assertIn("Advisory only", prompt)
        self.assertIn("Do not say this rule is approved or verified", prompt)
        self.assertIn("Proof trace (unproven fields):", prompt)

    def test_suggested_questions_are_gap_aware(self) -> None:
        packet = {"support_gaps": ["operator_not_supported", "conditional_cell_condition_missing"]}
        questions = MODULE.suggested_review_questions(packet)
        self.assertEqual(questions[0], "Why is this rule in review?")
        self.assertTrue(any("direction" in question for question in questions))
        self.assertTrue(any("lot-size branch" in question for question in questions))

    def test_bylaw_prompt_mentions_read_only_slot_context(self) -> None:
        prompt = MODULE._grounded_bylaw_prompt(
            "Can this rule be approved?",
            [{"section": "101.4", "text": "Maximum height is 10 m."}],
        )
        self.assertIn("Do not approve, verify, or reject rules", prompt)
        self.assertIn("Rule slots, verified rules, and review packets are read-only context", prompt)


class CountAuditViewTests(unittest.TestCase):
    def test_count_audit_status_flags_too_much_and_conservative(self) -> None:
        self.assertEqual(
            MODULE.count_audit_status(
                {"slot_metrics": {"verified_slot_mapping_rate": 0.5, "unsupported_verified_rule_count": 1}}
            ),
            "too much risk",
        )
        self.assertEqual(
            MODULE.count_audit_status(
                {
                    "slot_metrics": {
                        "verified_slot_mapping_rate": 1.0,
                        "unsupported_verified_rule_count": 0,
                        "duplicate_verified_slot_count": 0,
                        "review_slot_count": 2,
                        "missed_slot_count": 3,
                    }
                }
            ),
            "safe but conservative",
        )

    def test_count_audit_rows_are_reader_facing(self) -> None:
        rows = MODULE.count_audit_summary_rows(
            {
                "slot_metrics": {
                    "total_rule_slots": 10,
                    "verified_rule_count": 7,
                    "effective_verified_slot_count": 6,
                    "review_slot_count": 2,
                    "candidate_only_slot_count": 1,
                    "missed_slot_count": 1,
                    "duplicate_merged_count": 1,
                    "unsupported_verified_rule_count": 0,
                }
            },
            {"effective_verified_slot_count_delta": 0},
        )
        self.assertEqual(rows[0]["metric"], "Rule slots")

    def test_count_audit_rows_lead_with_scored_denominator_when_available(self) -> None:
        rows = MODULE.count_audit_summary_rows(
            {
                "slot_metrics": {
                    "total_rule_slots": 422,
                    "effective_verified_slot_count": 82,
                    "distinct_scored_legal_slot_count": 66,
                    "scored_verified_slot_count": 21,
                    "scored_review_slot_count": 3,
                    "scored_missed_slot_count": 42,
                    "scored_verified_coverage": 0.318,
                    "duplicate_merged_count": 2,
                    "unsupported_verified_rule_count": 0,
                }
            },
            {"effective_verified_slot_count_delta": 0},
        )
        metrics = {row["metric"] for row in rows}
        # The honest scored denominator leads; the raw ceiling is kept but labelled advisory.
        self.assertEqual(rows[0]["metric"], "Scored legal slots")
        self.assertIn("Raw rule slots (advisory)", metrics)
        self.assertIn("Verified coverage", metrics)
        coverage_row = next(row for row in rows if row["metric"] == "Verified coverage")
        self.assertEqual(coverage_row["value"], "32%")
        self.assertTrue(any(row["metric"] == "Unique verified slots" for row in rows))


if __name__ == "__main__":
    unittest.main()
