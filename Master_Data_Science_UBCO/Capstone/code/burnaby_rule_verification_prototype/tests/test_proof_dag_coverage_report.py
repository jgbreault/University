from __future__ import annotations

import unittest

from burnaby_prototype.coverage_report import build_coverage_report
from burnaby_prototype.proof_dag import build_proof_dag
from burnaby_prototype.slim_pipeline import extract_proof_dag_report


class CoverageReportTests(unittest.TestCase):
    def test_builds_family_rows_without_gold(self) -> None:
        report = build_coverage_report(
            rule_candidates=[{"rule_object": "setback"}, {"rule_object": "height"}],
            verified_rules=[{"rule_id": "v1", "rule_object": "setback"}],
            review_rules=[{"rule_id": "r1", "rule_object": "height", "support_gaps": ["operator_not_supported"]}],
            rejected_rules=[],
            not_used_rules=[],
        )
        rows = {row["family_key"]: row for row in report["family_rows"]}
        self.assertEqual(rows["setback"]["verified"], 1)
        self.assertEqual(rows["height"]["review"], 1)
        self.assertEqual(rows["height"]["top_hold_reason_code"], "operator_not_supported")
        self.assertEqual(report["gold_gaps"], [])

    def test_matrix_report_is_optional_and_review_safe(self) -> None:
        report = build_coverage_report(
            rule_candidates=[],
            verified_rules=[
                {
                    "rule_id": "v1",
                    "rule_object": "lot_coverage",
                    "value": "55",
                    "unit": "%",
                    "applies_to": "Rowhouse",
                }
            ],
            review_rules=[
                {
                    "rule_id": "r1",
                    "rule_object": "lot_coverage",
                    "value": "45",
                    "unit": "%",
                    "applies_to": "Small-Scale Multi-Unit (5 to 6 Units)",
                    "support_gaps": ["column_qualifier_not_claimed"],
                }
            ],
            rejected_rules=[],
            not_used_rules=[],
            include_matrix=True,
        )
        self.assertIn("matrix", report)
        statuses = report["matrix"]["rows"][0]["cells"]
        self.assertEqual(statuses[0]["status"], "verified")
        self.assertEqual(statuses[3]["status"], "review")


class ProofDagTests(unittest.TestCase):
    def test_supported_trace_projects_to_decision_node(self) -> None:
        dag = build_proof_dag(
            candidate={"candidate_id": "c1", "evidence_id": "e1", "value": "1.5", "unit": "m"},
            evidence={"evidence_id": "e1"},
            proof_trace={
                "value": {"label": "supported", "reason": "value appears"},
                "unit": {"label": "supported", "reason": "unit appears"},
                "operator": {"label": "supported", "reason": "minimum"},
                "rule_object": {"label": "supported", "reason": "setback"},
                "constraint_scope": {"label": "supported", "reason": "front"},
                "applies_to": {"label": "supported", "reason": "building"},
            },
            support_gaps=[],
            decision="verified",
        )
        self.assertEqual(dag["decision"], "verified")
        self.assertEqual(dag["support_gap_count"], 0)
        self.assertTrue(any(node["id"] == "decision" for node in dag["nodes"]))

    def test_matrix_refutation_becomes_refuted_applicability_node(self) -> None:
        dag = build_proof_dag(
            candidate={"candidate_id": "c1", "evidence_id": "e1"},
            evidence={"evidence_id": "e1"},
            proof_trace={},
            support_gaps=["column_value_mismatch"],
            decision="rejected",
            matrix_binding={"claimed_bands": [3], "supports_column": False},
        )
        nodes = {node["id"]: node for node in dag["nodes"]}
        self.assertEqual(nodes["claim:applicability"]["status"], "refuted")
        self.assertIn("column_value_mismatch", nodes["claim:applicability"]["gap_codes"])
        self.assertEqual(nodes["decision"]["status"], "rejected")


class ProofDagSidecarTests(unittest.TestCase):
    def test_extracts_full_dag_and_leaves_compact_rule_reference(self) -> None:
        rules = [
            {
                "rule_id": "r1",
                "proof_dag": {
                    "decision": "verified",
                    "support_gap_count": 0,
                    "status_counts": {"supported": 3},
                    "nodes": [{"id": "decision"}],
                    "edges": [],
                },
            }
        ]
        report = extract_proof_dag_report([("verified", rules)])

        self.assertEqual(report["dag_count"], 1)
        self.assertEqual(report["dags"][0]["rule_id"], "r1")
        self.assertEqual(report["dags"][0]["bucket"], "verified")
        self.assertNotIn("proof_dag", rules[0])
        self.assertEqual(rules[0]["proof_dag_ref"], "r1::proof_dag")
        self.assertEqual(rules[0]["proof_dag_summary"], {"support_gap_count": 0, "status_counts": {"supported": 3}})


if __name__ == "__main__":
    unittest.main()
