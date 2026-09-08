from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.compliance import evaluate_case, summarize_case_results
from burnaby_prototype.slim_pipeline import run_slim_verification
from burnaby_prototype.evidence_contract import evidence_quality_summary
from burnaby_prototype.evidence_intelligence import build_evidence_intelligence
from burnaby_prototype.evidence_rerun import apply_bundle_promotions, run_evidence_bundle_reruns
from burnaby_prototype.rule_claims import review_priority
from burnaby_prototype.rule_graph import build_rule_graph
from burnaby_prototype.review_resolution import build_review_resolution
from burnaby_prototype.semantic_review import build_semantic_review_report
from burnaby_prototype.support_checks import has_multiple_numeric_values, operator_supported
from burnaby_prototype.table_natural_logic import table_proof_status, table_proof_trace
from burnaby_prototype.zihao_adapter import adapt_pipeline5_registry, adapt_zihao_outputs
from burnaby_prototype.verification_cache import build_verification_cache_report, cache_key_for_candidate
from burnaby_prototype.verification import verify_candidates
from burnaby_prototype import gis_felt_export as gfe
from burnaby_prototype.gis_felt_export import build_gis_felt_export, validate_gis_felt_export
from burnaby_prototype.geometry_operator import derive_geometry_operator
from burnaby_prototype.evidence_rerun import (
    _provenance_key,
    _single_source_bundle,
    _synthetic_bundle_evidence,
    _bundle_promotion_blockers,
)
from burnaby_prototype import llm_review_assistant as lra
from burnaby_prototype.llm_review_assistant import run_review_assistant, heuristic_brief, build_messages
from benchmark.evaluate_benchmark import _quality_gates


CONFIG = ROOT / "configs" / "burnaby_r1.json"


class SlimVerifierTests(unittest.TestCase):
    def test_sentence_value_unit_operator_can_verify(self) -> None:
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
        # The text gate now applies to EVERY non-table candidate (it used to be
        # keyed on provenance strings, so unlabeled candidates bypassed it).
        # Burnaby policy requires cross-source consensus for text height rules,
        # so the clean sentence verifies together with an independent stream.
        corroborating_candidate = {
            **base_candidate,
            "candidate_id": "cand_001_table_stream",
            "source_stream": "gemini_table_image",
        }
        candidates = [base_candidate, corroborating_candidate]

        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 2)
        self.assertEqual(result["review_rule_count"], 0)
        self.assertEqual(result["rejected_rule_count"], 0)

    def test_bundle_source_labels_do_not_count_as_legal_numbers(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_bundle_label",
                "page": 5,
                "evidence_type": "clause",
                "evidence_text": (
                    "[pipeline5_merged_rule_0090__api_01] "
                    "An accessory structure not being a building, excluding a fence or a retaining wall, "
                    "located outside of a required yard, shall not exceed 4.6 m in height."
                ),
                "source_context": (
                    "[pipeline5_merged_rule_0090__api_01] "
                    "An accessory structure not being a building, excluding a fence or a retaining wall, "
                    "located outside of a required yard, shall not exceed 4.6 m in height."
                ),
            }
        ]
        base_candidate = {
            "candidate_id": "cand_bundle_label",
            "evidence_id": "ev_bundle_label",
            "rule_object": "height",
            "constraint_type": "maximum",
            "constraint_scope": "building",
            "applies_to": "accessory_structure",
            "operator": "<=",
            "value": "4.6",
            "unit": "m",
            "condition": "located outside of a required yard",
            "exception": "excluding a fence or a retaining wall",
            "extraction_method": "pipeline5_final_registry",
            "source_stream": "gemini_text_block",
        }
        # Second stream: text height rules need cross-source consensus to pass
        # the (now provenance-independent) text gate.
        candidates = [
            base_candidate,
            {**base_candidate, "candidate_id": "cand_bundle_label_table", "source_stream": "gemini_table_image"},
        ]

        self.assertFalse(has_multiple_numeric_values(evidence[0]["evidence_text"]))
        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 2)
        self.assertEqual(result["review_rule_count"], 0)
        self.assertEqual(result["rejected_rule_count"], 0)

    def test_nor_be_less_than_supports_minimum_operator(self) -> None:
        candidate = {
            "rule_object": "setback",
            "constraint_type": "minimum",
            "operator": ">=",
            "value": "1.2",
            "unit": "m",
        }
        evidence_text = "No part of such structure shall extend above grade, nor be less than 1.2 m from a lot line."

        self.assertTrue(operator_supported(candidate, evidence_text))

    def test_table_cell_context_can_verify(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Maximum Height | Rear Principal Buildings | sloping roof | 7.5 m",
                "source_context": "Maximum Height Rear Principal Buildings Height sloping roof: 7.5 m",
                "table_title": "Maximum Height",
                "row_header": "Rear Principal Buildings",
                "column_header": "sloping roof",
                "cell_value": "7.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "Maximum Height",
                "applies_to": "Rear Principal Buildings",
                "operator": "<=",
                "value": "7.5 m",
                "unit": "m",
                "condition": "sloping roof",
                "extraction_method": "deterministic_table_evidence",
            }
        ]

        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 1)
        self.assertEqual(result["review_rule_count"], 0)
        self.assertEqual(result["rejected_rule_count"], 0)

    def test_dwelling_unit_lower_bound_range_candidate_goes_to_review_not_rejected(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_units_lower",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": (
                    "Permitted Dwelling Units | Dwelling Units (including secondary suites) | "
                    "1 units | Permitted Dwelling Units (including secondary suites) | 1 to 3 Units"
                ),
                "source_context": "Permitted Dwelling Units (including secondary suites) | 1 to 3 Units",
                "table_title": "Permitted Dwelling Units",
                "row_header": "Dwelling Units (including secondary suites)",
                "column_header": "",
                "cell_value": "1 units",
            }
        ]
        candidates = [
            {
                "candidate_id": "units_lower",
                "evidence_id": "table_ev_units_lower",
                "rule_object": "dwelling_units",
                "constraint_type": "minimum",
                "constraint_scope": "lot",
                "applies_to": "Rowhouse",
                "operator": ">=",
                "value": "1",
                "unit": "units",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_table_image",
                "rule_key": "Permitted Dwelling Units",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(len(outputs["review_needed"]), 1)
        self.assertNotIn("value_not_found_in_evidence", outputs["review_needed"][0]["support_gaps"])

    def test_dwelling_unit_upper_bound_range_goes_to_review_without_explicit_maximum(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_units_upper",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": (
                    "Permitted Dwelling Units | Dwelling Units (including secondary suites) | "
                    "5 units | Permitted Dwelling Units (including secondary suites) | 5 to 6 Units"
                ),
                "source_context": "Permitted Dwelling Units (including secondary suites) | 5 to 6 Units",
                "table_title": "Permitted Dwelling Units",
                "row_header": "Dwelling Units (including secondary suites)",
                "column_header": "",
                "cell_value": "5 units",
            }
        ]
        candidates = [
            {
                "candidate_id": "units_upper",
                "evidence_id": "table_ev_units_upper",
                "rule_object": "dwelling_units",
                "constraint_type": "maximum",
                "constraint_scope": "lot",
                "applies_to": "Small-Scale Multi-Unit (5 to 6 Units)",
                "operator": "<=",
                "value": "6",
                "unit": "units",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_table_image",
                "rule_key": "Permitted Dwelling Units",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(len(outputs["review_needed"]), 1)
        rule = outputs["review_needed"][0]
        self.assertEqual(rule["value"], 6)
        self.assertEqual(rule["operator"], "<=")
        self.assertNotIn("value_not_found_in_evidence", rule["support_gaps"])
        self.assertNotIn("operator_not_supported", rule["support_gaps"])
        self.assertEqual(rule["proof_trace"]["value"]["label"], "supported")
        self.assertEqual(rule["proof_trace"]["operator"]["label"], "supported")

    def test_table_cell_output_has_proof_trace_and_evidence_strength(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Minimum Lot Line Setbacks | Lane Yard | 1.5 m",
                "source_context": "Minimum Lot Line Setbacks Lane Yard 1.5 m",
                "table_title": "Minimum Lot Line Setbacks",
                "row_header": "Lane Yard",
                "column_header": "",
                "cell_value": "1.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "Lane Yard",
                "applies_to": "Lane Yard",
                "operator": ">=",
                "value": "1.5",
                "unit": "m",
                "source_stream": "deterministic_table",
                "relevance_category": "direct",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["verified_rules"][0]

        self.assertEqual(rule["proof_type"], "table_natural_logic")
        self.assertEqual(rule["table_proof_status"], "complete")
        self.assertEqual(rule["verification_label"], "supported")
        self.assertEqual(rule["proof_trace"]["operator"]["label"], "supported")
        self.assertEqual(rule["proof_trace"]["value"]["label"], "supported")
        self.assertEqual(rule["proof_trace"]["unit"]["label"], "supported")
        self.assertFalse(rule["proof_decision_mismatch"])
        self.assertIn("operator", rule["table_proof_trace"])
        self.assertIn("operator", rule["text_proof_trace"])
        self.assertGreaterEqual(rule["evidence_strength"], 0.8)
        self.assertEqual(rule["review_priority"], "verified")
        self.assertIn("setback", rule["canonical_rule_key"])

    def test_table_proof_completes_principal_use_context(self) -> None:
        evidence = {
            "evidence_id": "table_ev_use",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": "Principal Use | Small-Scale Multi-Unit Housing | Permitted",
            "table_title": "Principal Use",
            "row_header": "Small-Scale Multi-Unit Housing",
            "column_header": "",
            "cell_value": "Permitted",
        }
        candidate = {
            "candidate_id": "table_cand_use",
            "evidence_id": "table_ev_use",
            "rule_object": "permitted_use",
            "constraint_type": "allowed",
            "constraint_scope": "use",
            "applies_to": "Principal Use",
            "operator": "allowed",
            "value": "Permitted",
            "unit": "",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(table_proof_status(trace), "complete")
        for field in ("rule_object", "constraint_scope", "applies_to", "operator", "value"):
            self.assertEqual(trace[field]["label"], "supported", field)

    def test_table_proof_supports_dwelling_unit_upper_bound_operator_from_range(self) -> None:
        evidence = {
            "evidence_id": "table_ev_units_upper",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": (
                "Permitted Dwelling Units | Dwelling Units (including secondary suites) | "
                "5 units | Permitted Dwelling Units (including secondary suites) | 5 to 6 Units"
            ),
            "table_title": "Permitted Dwelling Units",
            "row_header": "Dwelling Units (including secondary suites)",
            "column_header": "",
            "cell_value": "5 units",
        }
        candidate = {
            "candidate_id": "units_upper",
            "evidence_id": "table_ev_units_upper",
            "rule_object": "dwelling_units",
            "constraint_type": "maximum",
            "constraint_scope": "lot",
            "applies_to": "lot",
            "operator": "<=",
            "value": "6",
            "unit": "units",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(trace["operator"]["label"], "supported")
        self.assertEqual(trace["value"]["label"], "supported")

    def test_table_proof_supports_generic_building_scope_by_visible_phrase(self) -> None:
        evidence = {
            "evidence_id": "table_ev_height",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": "Maximum Height | Front Principal Buildings | flat roof | 10.7 m",
            "table_title": "Maximum Height",
            "row_header": "Front Principal Buildings",
            "column_header": "flat roof",
            "cell_value": "10.7 m",
        }
        candidate = {
            "candidate_id": "table_cand_height",
            "evidence_id": "table_ev_height",
            "rule_object": "height",
            "constraint_type": "maximum",
            "constraint_scope": "building",
            "applies_to": "Front Principal Buildings",
            "operator": "<=",
            "value": "10.7",
            "unit": "m",
            "condition": "flat roof",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(table_proof_status(trace), "complete")
        self.assertEqual(trace["constraint_scope"]["label"], "supported")

    def test_table_proof_does_not_support_unseen_compound_scope(self) -> None:
        evidence = {
            "evidence_id": "table_ev_height",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": "Maximum Height | Front Principal Buildings | flat roof | 10.7 m",
            "table_title": "Maximum Height",
            "row_header": "Front Principal Buildings",
            "column_header": "flat roof",
            "cell_value": "10.7 m",
        }
        candidate = {
            "candidate_id": "table_cand_height",
            "evidence_id": "table_ev_height",
            "rule_object": "height",
            "constraint_type": "maximum",
            "constraint_scope": "front street yard",
            "applies_to": "Front Principal Buildings",
            "operator": "<=",
            "value": "10.7",
            "unit": "m",
            "condition": "flat roof",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(trace["constraint_scope"]["label"], "not_enough_info")

    def test_table_proof_does_not_match_short_claim_inside_larger_word(self) -> None:
        evidence = {
            "evidence_id": "table_ev_setback",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": "Minimum Setbacks | Opposite Lot Line | 1.2 m",
            "table_title": "Minimum Setbacks",
            "row_header": "Opposite Lot Line",
            "column_header": "",
            "cell_value": "1.2 m",
        }
        candidate = {
            "candidate_id": "table_cand_setback",
            "evidence_id": "table_ev_setback",
            "rule_object": "setback",
            "constraint_type": "minimum",
            "constraint_scope": "site",
            "applies_to": "Opposite Lot Line",
            "operator": ">=",
            "value": "1.2",
            "unit": "m",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(trace["constraint_scope"]["label"], "not_enough_info")

    def test_table_proof_uses_matching_matrix_band_for_applies_to_and_condition(self) -> None:
        evidence = {
            "evidence_id": "table_ev_coverage",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": "Maximum Lot Coverage | All Buildings | 45%",
            "table_title": "Maximum Lot Coverage",
            "row_header": "All Buildings",
            "column_header": "All Buildings",
            "cell_value": "45%",
            "matrix_anchor": {
                "bands": [
                    {
                        "header_text": "Dwelling Type | Small-Scale Multi-Unit | 3 to 4 | Units",
                        "text": "40%",
                        "spans_all": False,
                    },
                    {
                        "header_text": "Small-Scale Multi-Unit | 5 to 6 Units | Frequent Transit | Network Area Only",
                        "text": "45%",
                        "spans_all": False,
                    },
                ]
            },
        }
        candidate = {
            "candidate_id": "table_cand_coverage",
            "evidence_id": "table_ev_coverage",
            "rule_object": "lot_coverage",
            "constraint_type": "maximum",
            "constraint_scope": "lot",
            "applies_to": "Small-Scale Multi-Unit (5 to 6 Units)",
            "operator": "<=",
            "value": "45",
            "unit": "%",
            "condition": "Frequent Transit Network Area Only",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(table_proof_status(trace), "complete")
        self.assertEqual(trace["applies_to"]["label"], "supported")
        self.assertEqual(trace["condition"]["label"], "supported")

    def test_table_proof_uses_matching_matrix_branch_condition_only(self) -> None:
        evidence = {
            "evidence_id": "table_ev_coverage",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": "Maximum Lot Coverage | All Buildings | Lots <= 567 m2: 40%",
            "table_title": "Maximum Lot Coverage",
            "row_header": "All Buildings",
            "column_header": "All Buildings",
            "cell_value": "40%",
            "matrix_anchor": {
                "bands": [
                    {
                        "header_text": "Dwelling Type | Small-Scale Multi-Unit | 1 to 2 | Units",
                        "text": "Lots < 567 m2: 40%\nLots > 567 m2: 30%",
                        "spans_all": False,
                        "branches": [
                            {"condition_text": "Lots < 567 m2", "value_text": "40%"},
                            {"condition_text": "Lots > 567 m2", "value_text": "30%"},
                        ],
                    }
                ]
            },
        }
        candidate = {
            "candidate_id": "table_cand_coverage",
            "evidence_id": "table_ev_coverage",
            "rule_object": "lot_coverage",
            "constraint_type": "maximum",
            "constraint_scope": "lot",
            "applies_to": "Small-Scale Multi-Unit (1 to 2 Units)",
            "operator": "<=",
            "value": "40",
            "unit": "%",
            "condition": "Lots <= 567 m2",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(table_proof_status(trace), "complete")
        self.assertEqual(trace["condition"]["label"], "supported")

    def test_table_proof_does_not_use_nonmatching_matrix_band_condition(self) -> None:
        evidence = {
            "evidence_id": "table_ev_coverage",
            "page": 1,
            "evidence_type": "table_cell",
            "evidence_text": "Maximum Lot Coverage | All Buildings | 40%",
            "table_title": "Maximum Lot Coverage",
            "row_header": "All Buildings",
            "column_header": "All Buildings",
            "cell_value": "40%",
            "matrix_anchor": {
                "bands": [
                    {
                        "header_text": "Dwelling Type | Small-Scale Multi-Unit | 3 to 4 | Units",
                        "text": "40%",
                        "spans_all": False,
                    },
                    {
                        "header_text": "Small-Scale Multi-Unit | 5 to 6 Units | Frequent Transit | Network Area Only",
                        "text": "45%",
                        "spans_all": False,
                    },
                ]
            },
        }
        candidate = {
            "candidate_id": "table_cand_coverage",
            "evidence_id": "table_ev_coverage",
            "rule_object": "lot_coverage",
            "constraint_type": "maximum",
            "constraint_scope": "lot",
            "applies_to": "Small-Scale Multi-Unit (5 to 6 Units)",
            "operator": "<=",
            "value": "40",
            "unit": "%",
            "condition": "Frequent Transit Network Area Only",
        }

        trace = table_proof_trace(candidate, evidence)

        self.assertEqual(trace["condition"]["label"], "not_enough_info")

    def test_table_operator_refutation_rejects_wrong_direction(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "source_context": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "table_title": "Maximum Height",
                "row_header": "Rear Principal Buildings",
                "column_header": "",
                "cell_value": "7.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "height",
                "constraint_type": "minimum",
                "constraint_scope": "Maximum Height",
                "applies_to": "Rear Principal Buildings",
                "operator": ">=",
                "value": "7.5",
                "unit": "m",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["rejected_rules"][0]

        self.assertEqual(rule["table_proof_trace"]["operator"]["label"], "refuted")
        self.assertIn("table_operator_refuted", rule["support_gaps"])
        self.assertEqual(rule["verification_decision"], "rejected")

    def test_unresolved_exception_cue_goes_to_review(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Minimum Lot Line Setbacks | Lane Yard unless otherwise specified | 1.5 m",
                "source_context": "Minimum Lot Line Setbacks | Lane Yard unless otherwise specified | 1.5 m",
                "table_title": "Minimum Lot Line Setbacks",
                "row_header": "Lane Yard unless otherwise specified",
                "column_header": "",
                "cell_value": "1.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "Lane Yard",
                "applies_to": "Lane Yard",
                "operator": ">=",
                "value": "1.5",
                "unit": "m",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["review_needed"][0]

        self.assertIn("unresolved_exception_cue", rule["support_gaps"])
        self.assertEqual(rule["proof_trace"]["exception"]["label"], "not_enough_info")
        self.assertEqual(rule["verification_decision"], "review_needed")

    def test_prose_exclusion_criterion_never_verifies_as_a_cap(self) -> None:
        # Live P9-fed false verify (Vancouver 11.3.7.4): an ELIGIBILITY test
        # for a floor-area exclusion reads exactly like a height cap. Before
        # the prose path consulted the text-span trace, this hold could only
        # fire for table evidence, so this clause verified as height <= 3.1 m.
        evidence = [
            {
                "evidence_id": "text_ev_001",
                "page": 12,
                "evidence_type": "text",
                "evidence_text": (
                    "(iii) the ceiling height, excluding roof structure, of the "
                    "total area being excluded does not exceed 3.1 m, measured "
                    "from the top of the floor to the highest point of the ceiling"
                ),
                "source_context": "11.3.7.4 Computation of floor area must exclude...",
            }
        ]
        candidates = [
            {
                "candidate_id": "text_cand_001",
                "evidence_id": "text_ev_001",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "ceiling height",
                "applies_to": "laneway house",
                "operator": "<=",
                "value": "3.1",
                "unit": "m",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["verified_rules"], [])
        held = outputs["review_needed"] + outputs["rejected_rules"]
        self.assertEqual(len(held), 1)
        self.assertIn("unresolved_exception_cue", held[0]["support_gaps"])

    def test_neighbor_clause_exception_in_context_does_not_hold_clean_cell(self) -> None:
        # The cue scan covers the fields the proof validated, NOT
        # source_context: a neighboring clause's "except that the Director
        # may..." (a different rule's discretionary escape) says nothing about
        # this cell's claims. Wide RAG pack context would otherwise hold nearly
        # every candidate for its neighbors' exceptions.
        evidence = [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Maximum Height | Rear Principal Buildings | sloping roof | 7.5 m",
                "source_context": (
                    "Maximum Height Rear Principal Buildings Height sloping roof: "
                    "7.5 m. The minimum site width is 9.8 m, except that the "
                    "Director of Planning may reduce the minimum site width."
                ),
                "table_title": "Maximum Height",
                "row_header": "Rear Principal Buildings",
                "column_header": "sloping roof",
                "cell_value": "7.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "Maximum Height",
                "applies_to": "Rear Principal Buildings",
                "operator": "<=",
                "value": "7.5 m",
                "unit": "m",
                "condition": "sloping roof",
                "extraction_method": "deterministic_table_evidence",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(len(outputs["verified_rules"]), 1)
        rule = outputs["verified_rules"][0]
        self.assertNotIn("unresolved_exception_cue", rule["support_gaps"])
        self.assertEqual(rule["proof_trace"]["exception"]["label"], "supported")

    def test_definition_sentence_never_verifies_as_a_rule(self) -> None:
        # Live Calgary P9 leak: '"corner parcel" means ... intersect at an
        # angle not exceeding 135 degrees.' verified as dwelling_units <= 135.
        # Every per-field check passes (the number and the words are present);
        # only the sentence SHAPE says it is vocabulary, not a regulation —
        # and the unit-less count claim must not be satisfied by a number
        # glued to 'degrees'.
        evidence = [
            {
                "evidence_id": "text_ev_001",
                "page": 62,
                "evidence_type": "text",
                "evidence_text": (
                    "(43) “corner parcel” means a parcel that abuts two streets "
                    "which intersect at an angle not exceeding 135 degrees. "
                    "(45) “cottage building” means a residential building that "
                    "contains one, two or three Dwelling Units."
                ),
                "source_context": "PART 1 - DIVISION 2: DEFINITIONS AND METHODS",
            }
        ]
        candidates = [
            {
                "candidate_id": "text_cand_001",
                "evidence_id": "text_ev_001",
                "rule_object": "dwelling_units",
                "constraint_type": "maximum",
                "constraint_scope": "corner_parcel_intersection_angle",
                "applies_to": "street intersection angle",
                "operator": "<=",
                "value": "135",
                "unit": "",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["verified_rules"], [])
        held = outputs["review_needed"] + outputs["rejected_rules"] + outputs["not_used"]
        self.assertEqual(len(held), 1)
        gaps = set(held[0]["support_gaps"])
        self.assertIn("definition_not_rule", gaps)
        self.assertIn("value_bound_to_foreign_unit", gaps)

    def test_allowance_trigger_threshold_goes_to_review(self) -> None:
        # Live Calgary P9 leak: 'there is no maximum building depth where the
        # minimum building setback ... is 3.0 metres' — the bylaw INCENTIVIZES
        # the 3.0 m setback (it unlocks the no-max-depth allowance); it does
        # not require it. Reading the trigger as a setback rule must be held.
        evidence = [
            {
                "evidence_id": "text_ev_001",
                "page": 1039,
                "evidence_type": "text",
                "evidence_text": (
                    "(3) For a main residential building that is located on a "
                    "corner parcel there is no maximum building depth where the "
                    "minimum building setback from the side property line shared "
                    "with another parcel is 3.0 metres for any portion of the "
                    "building located between the rear property line."
                ),
                "source_context": "",
            }
        ]
        candidates = [
            {
                "candidate_id": "text_cand_001",
                "evidence_id": "text_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "side_property_line",
                "applies_to": "main residential building",
                "operator": ">=",
                "value": "3.0",
                "unit": "m",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["verified_rules"], [])
        review = outputs["review_needed"][0]
        self.assertIn("allowance_trigger_threshold", review["support_gaps"])

    def test_separation_without_building_subject_does_not_verify(self) -> None:
        # Live Calgary P9 leak: 'A minimum horizontal separation of 1.0 metres
        # must be maintained between retaining walls' verified as
        # building_separation — the word 'separation' alone proved the family.
        # The separation's subject must be a building-like entity.
        evidence = [
            {
                "evidence_id": "text_ev_001",
                "page": 825,
                "evidence_type": "text",
                "evidence_text": (
                    "1119 (2) A minimum horizontal separation of 1.0 metres must "
                    "be maintained between retaining walls on a parcel."
                ),
                "source_context": "",
            }
        ]
        candidates = [
            {
                "candidate_id": "text_cand_001",
                "evidence_id": "text_ev_001",
                "rule_object": "building_separation",
                "constraint_type": "minimum",
                "constraint_scope": "retaining_wall_separation",
                "applies_to": "horizontal separation",
                "operator": ">=",
                "value": "1.0",
                "unit": "m",
                "condition": "between retaining walls on a parcel",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["verified_rules"], [])
        held = outputs["review_needed"] + outputs["rejected_rules"]
        self.assertEqual(len(held), 1)
        self.assertIn("rule_object_not_supported", held[0]["support_gaps"])

    def _interior_rear_exception_evidence(self, cell_value: str = "3.0 m") -> list[dict]:
        # Mirror real Pipeline 5 evidence: each branch is its own cell, but the
        # full "3.0 m, except 1.5 m for accessory buildings" clause appears in the
        # surrounding evidence text.
        text = (
            "Minimum Lot Line Setbacks for All Buildings | Interior Rear Yard | "
            f"{cell_value} | Interior Rear Yard | 3.0 m, except 1.5 m for accessory buildings"
        )
        return [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": text,
                "source_context": text,
                "table_title": "Minimum Lot Line Setbacks",
                "row_header": "Interior Rear Yard",
                "column_header": "",
                "cell_value": cell_value,
            }
        ]

    def test_resolved_exception_branch_base_value_verifies(self) -> None:
        # "3.0 m, except 1.5 m for accessory buildings" lists two explicit
        # branches. The 3.0 m base is the general rule; the "except" cue must
        # not hold a correctly-resolved branch in review.
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "interior_rear_yard",
                "applies_to": "Rear Principal Buildings",
                "operator": ">=",
                "value": "3.0",
                "unit": "m",
            }
        ]
        outputs = _run_outputs(self._interior_rear_exception_evidence(), candidates)
        self.assertEqual(len(outputs["verified_rules"]), 1)
        rule = outputs["verified_rules"][0]
        self.assertNotIn("unresolved_exception_cue", rule["support_gaps"])
        self.assertEqual(rule["proof_trace"]["exception"]["label"], "supported")

    def test_resolved_exception_branch_alt_value_with_matching_condition_verifies(self) -> None:
        # The 1.5 m branch resolves only because the candidate names the same
        # group ("accessory buildings") as the "for X" qualifier.
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "interior_rear_yard",
                "applies_to": "Accessory Buildings",
                "condition": "accessory buildings",
                "operator": ">=",
                "value": "1.5",
                "unit": "m",
            }
        ]
        outputs = _run_outputs(self._interior_rear_exception_evidence("1.5 m"), candidates)
        self.assertEqual(len(outputs["verified_rules"]), 1)
        self.assertNotIn("unresolved_exception_cue", outputs["verified_rules"][0]["support_gaps"])

    def test_exception_branch_value_mismatch_still_reviews(self) -> None:
        # Value matches the 1.5 m exception branch, but the candidate names a
        # different group ("end unit lots") than the "accessory buildings"
        # qualifier, so the exception stays unresolved and the rule reviews.
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "interior_rear_yard",
                "applies_to": "All Buildings",
                "condition": "end unit lots",
                "operator": ">=",
                "value": "1.5",
                "unit": "m",
            }
        ]
        outputs = _run_outputs(self._interior_rear_exception_evidence("1.5 m"), candidates)
        self.assertEqual(len(outputs["verified_rules"]), 0)
        review = outputs["review_needed"][0]
        self.assertIn("unresolved_exception_cue", review["support_gaps"])

    def test_base_value_attributed_to_exception_group_still_reviews(self) -> None:
        # Precision guard: a candidate that names the EXCEPTION group ("accessory
        # buildings") but carries the BASE value (3.0 m) is mis-attributing the
        # general rule to the exception group. It must NOT verify -- the cell
        # carves out 1.5 m for accessory buildings, so 3.0 m for them is wrong.
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "interior_rear_yard",
                "applies_to": "Accessory Buildings",
                "condition": "accessory buildings",
                "operator": ">=",
                "value": "3.0",
                "unit": "m",
            }
        ]
        outputs = _run_outputs(self._interior_rear_exception_evidence("3.0 m"), candidates)
        self.assertEqual(len(outputs["verified_rules"]), 0)
        self.assertIn("unresolved_exception_cue", outputs["review_needed"][0]["support_gaps"])

    def test_incompatible_rule_object_unit_is_rejected(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Minimum Lot Area | Example qualifier | 4 Units Only",
                "source_context": "Minimum Lot Area | Example qualifier | 4 Units Only | 281 m2",
                "table_title": "Minimum Lot Area",
                "row_header": "Example qualifier",
                "column_header": "",
                "cell_value": "4 Units Only",
            }
        ]
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "lot_area",
                "constraint_type": "minimum",
                "constraint_scope": "Minimum Lot Area",
                "applies_to": "Example qualifier",
                "operator": ">=",
                "value": "4 Units",
                "unit": "units",
                "extraction_method": "deterministic_table_evidence",
            }
        ]

        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 0)
        self.assertEqual(result["rejected_rule_count"], 1)

    def test_non_numeric_value_for_numeric_rule_is_rejected(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_non_numeric",
                "page": 6,
                "evidence_type": "clause",
                "evidence_text": "Building height is measured to the highest point of a flat roof.",
                "source_context": "Building height is measured to the highest point of a flat roof.",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_non_numeric",
                "evidence_id": "ev_non_numeric",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "building",
                "applies_to": "building",
                "operator": "<=",
                "value": "measured to",
                "unit": "m",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["rejected_rules"][0]

        self.assertEqual(outputs["review_needed"], [])
        self.assertEqual(rule["verification_decision"], "rejected")
        self.assertIn("non_numeric_value_for_numeric_rule", rule["support_gaps"])

    def test_lot_area_text_with_separated_lot_and_area_terms_is_review_not_rejected(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_lot_area_text",
                "page": 4,
                "evidence_type": "clause",
                "evidence_text": "Boarding houses are permitted on a lot with an area of not less than 560 m².",
                "source_context": "Boarding houses are permitted on a lot with an area of not less than 560 m².",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_lot_area_text",
                "evidence_id": "ev_lot_area_text",
                "rule_object": "lot_area",
                "constraint_type": "minimum",
                "constraint_scope": "lot",
                "applies_to": "lot",
                "operator": ">=",
                "value": "560",
                "unit": "m2",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_text_block",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["review_needed"][0]

        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertIn("text_candidate_requires_review", rule["support_gaps"])
        self.assertNotIn("rule_object_not_supported", rule["support_gaps"])

    def test_flanking_street_yard_scope_is_preserved_when_row_also_mentions_front(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_flanking_street_yard",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": (
                    "Minimum Lot Line Setbacks | Street Yard | front: 4.0 m | 3.0 m | "
                    "Minimum Lot Line Setbacks for All Buildings | Street Yard | "
                    "front: 4.0 m | flanking: 3.0 m"
                ),
                "source_context": (
                    "Minimum Lot Line Setbacks for All Buildings | Street Yard | "
                    "front: 4.0 m | flanking: 3.0 m"
                ),
                "table_title": "Minimum Lot Line Setbacks",
                "row_header": "Street Yard",
                "column_header": "front: 4.0 m",
                "cell_value": "3.0 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_flanking_street_yard",
                "evidence_id": "ev_flanking_street_yard",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "street_yard_flanking",
                "applies_to": "All Buildings",
                "operator": ">=",
                "value": "3.0",
                "unit": "m",
                "condition": "flanking",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_table_image",
                "rule_key": "Minimum Lot Line Setbacks for All Buildings - Street Yard",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["verified_rules"][0]

        self.assertEqual(outputs["review_needed"], [])
        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(rule["constraint_scope"], "street_yard_flanking")
        self.assertEqual(rule["condition"], "flanking")

    def test_non_target_table_column_goes_to_review(self) -> None:
        evidence = [
            {
                "evidence_id": "table_ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Minimum Lot Line Setbacks | Interior Side Yard | Unrelated Housing Form | 0 m",
                "source_context": "Minimum Lot Line Setbacks | Interior Side Yard | Unrelated Housing Form | 0 m",
                "table_title": "Minimum Lot Line Setbacks",
                "row_header": "Interior Side Yard",
                "column_header": "Unrelated Housing Form",
                "cell_value": "0 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "table_cand_001",
                "evidence_id": "table_ev_001",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "Minimum Lot Line Setbacks Unrelated Housing Form",
                "applies_to": "Interior Side Yard",
                "operator": ">=",
                "value": "0 m",
                "unit": "m",
                "condition": "Unrelated Housing Form",
                "extraction_method": "deterministic_table_evidence",
            }
        ]

        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 0)
        self.assertEqual(result["review_rule_count"], 1)
        self.assertEqual(result["rejected_rule_count"], 0)

    def test_wrong_value_is_rejected(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_001",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": "Rear Principal Buildings maximum height shall not exceed 7.5 m.",
                "source_context": "Rear Principal Buildings maximum height shall not exceed 7.5 m.",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_001",
                "evidence_id": "ev_001",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "maximum height",
                "applies_to": "Rear Principal Buildings",
                "operator": "<=",
                "value": "8.0 m",
                "unit": "m",
            }
        ]

        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 0)
        self.assertEqual(result["review_rule_count"], 0)
        self.assertEqual(result["rejected_rule_count"], 1)

    def test_bayesian_triage_does_not_verify_wrong_value(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_001",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": "Rear Principal Buildings maximum height shall not exceed 7.5 m.",
                "source_context": "Rear Principal Buildings maximum height shall not exceed 7.5 m.",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_001",
                "evidence_id": "ev_001",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "maximum height",
                "applies_to": "Rear Principal Buildings",
                "operator": "<=",
                "value": "8.0",
                "unit": "m",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["rejected_rules"][0]

        self.assertEqual(rule["verification_decision"], "rejected")
        self.assertEqual(rule["verification_status"], "unsupported")
        self.assertEqual(rule["verification_label"], "refuted")
        self.assertEqual(rule["proof_trace"]["value"]["label"], "refuted")
        self.assertLess(rule["evidence_strength"], 0.8)

    def test_right_value_wrong_rule_object_goes_to_rejected(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_001",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": "Impervious Surfaces maximum coverage is 60%.",
                "source_context": "Impervious Surfaces maximum coverage is 60%.",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_001",
                "evidence_id": "ev_001",
                "rule_object": "setback",
                "constraint_type": "maximum",
                "constraint_scope": "lane yard",
                "applies_to": "Lane Yard",
                "operator": "<=",
                "value": "60%",
                "unit": "%",
            }
        ]

        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 0)
        self.assertEqual(result["rejected_rule_count"], 1)

    def test_same_sentence_wrong_numeric_scope_goes_to_review(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_001",
                "page": 3,
                "evidence_type": "clause",
                "evidence_text": (
                    "A building between a front and rear principal must have a minimum "
                    "6.0 m separation from each front and rear principal, and a minimum "
                    "2.4 m separation from any other principal."
                ),
                "source_context": (
                    "A building between a front and rear principal must have a minimum "
                    "6.0 m separation from each front and rear principal, and a minimum "
                    "2.4 m separation from any other principal."
                ),
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_001",
                "evidence_id": "ev_001",
                "rule_object": "building_separation",
                "constraint_type": "minimum",
                "constraint_scope": "building_separation",
                "applies_to": "Front and Rear Principal Buildings",
                "operator": ">=",
                "value": "2.4",
                "unit": "m",
                "condition": "between front and rear principals",
            }
        ]

        result = _run(evidence, candidates)

        self.assertEqual(result["verified_rule_count"], 0)
        self.assertEqual(result["review_rule_count"], 1)

    def test_missing_applies_to_has_not_enough_info_proof(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_001",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": "Maximum height shall not exceed 7.5 m.",
                "source_context": "Maximum height shall not exceed 7.5 m.",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_001",
                "evidence_id": "ev_001",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "maximum height",
                "applies_to": "Rear Principal Buildings",
                "operator": "<=",
                "value": "7.5",
                "unit": "m",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["review_needed"][0]

        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertEqual(rule["proof_trace"]["applies_to"]["label"], "not_enough_info")
        self.assertIn(rule["review_priority"], {"high", "medium"})

    def test_pipeline5_text_rule_requires_review_even_when_supported(self) -> None:
        evidence = [
            {
                "evidence_id": "p5_text_001",
                "page": 1,
                "evidence_type": "clause",
                "evidence_text": "Maximum height shall not exceed 7.5 m.",
                "source_context": "Maximum height shall not exceed 7.5 m.",
            }
        ]
        candidates = [
            {
                "candidate_id": "p5_cand_001",
                "evidence_id": "p5_text_001",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "maximum height",
                "operator": "<=",
                "value": "7.5",
                "unit": "m",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_text_block",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["review_needed"][0]

        self.assertEqual(rule["verification_decision"], "review_needed")
        self.assertIn("text_candidate_requires_review", rule["support_gaps"])

    def test_configured_single_source_text_family_can_verify_without_consensus(self) -> None:
        evidence_text = (
            "Dwelling units located more than 45 m from a lot line abutting a street "
            "shall contain an automatic sprinkler system."
        )
        evidence = [
            {
                "evidence_id": "sprinkler_text_001",
                "page": 6,
                "evidence_type": "clause",
                "evidence_text": evidence_text,
                "source_context": evidence_text,
            }
        ]
        candidates = [
            {
                "candidate_id": "sprinkler_cand_001",
                "evidence_id": "sprinkler_text_001",
                "rule_object": "automatic_sprinkler",
                "constraint_type": "required",
                "constraint_scope": "dwelling_unit",
                "applies_to": "Dwelling units more than 45 m from a street lot line",
                "condition": "Dwelling units located more than 45 m from a lot line abutting a street",
                "operator": ">",
                "value": "45",
                "unit": "m",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_text_block",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["verified_rules"][0]

        self.assertEqual(rule["verification_decision"], "verified")
        self.assertEqual(rule["text_span_proof_status"], "complete")
        self.assertNotIn("text_candidate_requires_review", rule["support_gaps"])

    def test_enumerated_child_clause_can_inherit_parent_context(self) -> None:
        evidence = [
            {
                "evidence_id": "fire_parent",
                "page": 6,
                "evidence_type": "clause",
                "evidence_text": "All dwelling units shall have a minimum 1.0 m paved or gravel fire access corridor that:",
                "source_context": "All dwelling units shall have a minimum 1.0 m paved or gravel fire access corridor that:",
            },
            {
                "evidence_id": "fire_child",
                "page": 6,
                "evidence_type": "clause",
                "evidence_text": "(b) is clear of any projections or obstructions to a minimum of 2.5 m in height.",
                "source_context": "(b) is clear of any projections or obstructions to a minimum of 2.5 m in height.",
            },
        ]
        candidates = [
            {
                "candidate_id": "fire_clearance",
                "evidence_id": "fire_child",
                "rule_object": "fire_access_corridor",
                "constraint_type": "minimum",
                "constraint_scope": "vertical_clearance",
                "applies_to": "All dwelling units",
                "condition": "All dwelling units; must be clear of any projections or obstructions",
                "operator": ">=",
                "value": "2.5",
                "unit": "m",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_text_block",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["verified_rules"][0]

        self.assertEqual(rule["verification_decision"], "verified")
        self.assertEqual(
            rule["source"]["inherited_parent_context"],
            "All dwelling units shall have a minimum 1.0 m paved or gravel fire access corridor that:",
        )
        self.assertNotIn("rule_object_not_supported", rule["support_gaps"])

    def test_pipeline5_text_rule_can_verify_with_supported_span_and_consensus(self) -> None:
        evidence_text = (
            "Any principal building located between a front and rear principal building "
            "must provide a minimum 6.0 m separation from each of the front and rear principals."
        )
        evidence = [
            {
                "evidence_id": "p5_text_consensus_001",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": evidence_text,
                "source_context": evidence_text,
            },
            {
                "evidence_id": "p5_text_consensus_002",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": evidence_text,
                "source_context": evidence_text,
            },
        ]
        base_candidate = {
            "rule_object": "building_separation",
            "constraint_type": "minimum",
            "constraint_scope": "building_separation",
            "applies_to": "principal building",
            "condition": "located between a front and rear principal building",
            "operator": ">=",
            "value": "6.0",
            "unit": "m",
            "extraction_method": "pipeline5_final_registry",
        }
        candidates = [
            {
                **base_candidate,
                "candidate_id": "p5_text_consensus_text",
                "evidence_id": "p5_text_consensus_001",
                "source_stream": "gemini_text_block",
            },
            {
                **base_candidate,
                "candidate_id": "p5_text_consensus_other",
                "evidence_id": "p5_text_consensus_002",
                "source_stream": "gemini_table_image",
            },
        ]

        outputs = _run_outputs(evidence, candidates)
        text_rule = next(
            rule
            for rule in outputs["verified_rules"]
            if rule["candidate"]["candidate_id"] == "p5_text_consensus_text"
        )

        self.assertEqual(text_rule["verification_decision"], "verified")
        self.assertEqual(text_rule["text_span_proof_status"], "complete")
        self.assertFalse(text_rule["proof_decision_mismatch"])
        self.assertNotIn("text_candidate_requires_review", text_rule["support_gaps"])
        self.assertNotIn("text_condition_not_supported", text_rule["support_gaps"])

    def test_pipeline5_text_rule_needs_review_when_material_condition_is_missing(self) -> None:
        weak_evidence = (
            "and a minimum 2.4 m separation from any other principals between it and a side lot line."
        )
        evidence = [
            {
                "evidence_id": "p5_text_missing_condition_001",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": weak_evidence,
                "source_context": weak_evidence,
            },
            {
                "evidence_id": "p5_text_missing_condition_002",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": weak_evidence,
                "source_context": weak_evidence,
            },
        ]
        base_candidate = {
            "rule_object": "building_separation",
            "constraint_type": "minimum",
            "constraint_scope": "building_separation",
            "applies_to": "principal building",
            "condition": "located between a front and rear principal building",
            "operator": ">=",
            "value": "2.4",
            "unit": "m",
            "extraction_method": "pipeline5_final_registry",
        }
        candidates = [
            {
                **base_candidate,
                "candidate_id": "p5_text_missing_condition_text",
                "evidence_id": "p5_text_missing_condition_001",
                "source_stream": "gemini_text_block",
            },
            {
                **base_candidate,
                "candidate_id": "p5_text_missing_condition_other",
                "evidence_id": "p5_text_missing_condition_002",
                "source_stream": "gemini_table_image",
            },
        ]

        outputs = _run_outputs(evidence, candidates)
        text_rule = next(
            rule
            for rule in outputs["review_needed"]
            if rule["candidate"]["candidate_id"] == "p5_text_missing_condition_text"
        )

        self.assertEqual(text_rule["verification_decision"], "review_needed")
        self.assertEqual(text_rule["text_span_proof_status"], "partial")
        self.assertFalse(text_rule["proof_decision_mismatch"])
        self.assertIn("text_condition_not_supported", text_rule["support_gaps"])
        self.assertEqual(text_rule["proof_trace"]["condition"]["label"], "not_enough_info")
        self.assertEqual(text_rule["review_category"], "missing_condition_evidence")
        self.assertIn("condition_not_in_cited_text", text_rule["potential_mistake_flags"])

    def test_evidence_repair_suggests_stronger_condition_span(self) -> None:
        weak_evidence = "minimum 2.4 m separation from any other principals."
        strong_evidence = (
            "A principal building located between a front and rear principal building "
            "must provide a minimum 2.4 m separation from any other principal."
        )
        evidence = [
            {
                "evidence_id": "weak_ev",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": weak_evidence,
                "source_context": weak_evidence,
            },
            {
                "evidence_id": "strong_ev",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": strong_evidence,
                "source_context": strong_evidence,
            },
        ]
        candidates = [
            {
                "candidate_id": "needs_better_condition_evidence",
                "evidence_id": "weak_ev",
                "rule_object": "building_separation",
                "constraint_type": "minimum",
                "constraint_scope": "building_separation",
                "applies_to": "principal building",
                "condition": "located between a front and rear principal building",
                "operator": ">=",
                "value": "2.4",
                "unit": "m",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_text_block",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        suggestion = outputs["evidence_repair"]["suggestions"][0]

        self.assertEqual(outputs["review_needed"][0]["review_category"], "missing_condition_evidence")
        self.assertEqual(suggestion["rule_id"], outputs["review_needed"][0]["rule_id"])
        self.assertEqual(suggestion["top_evidence"][0]["evidence_id"], "strong_ev")
        self.assertIn("condition", suggestion["repairable_fields"])
        self.assertTrue(suggestion["can_retry_verification"])
        # review_action_bucket on the review row is the action verdict from the
        # merged review layer.
        self.assertEqual(outputs["review_needed"][0]["review_action_bucket"], "retry_with_better_evidence")

    def test_evidence_repair_does_not_treat_generic_lot_overlap_as_condition(self) -> None:
        weak_evidence = "maximum lot coverage may be increased up to 60%."
        nearby_evidence = "impervious surface area may be increased up to 70%."
        evidence = [
            {
                "evidence_id": "weak_ev",
                "page": 6,
                "evidence_type": "clause",
                "evidence_text": weak_evidence,
                "source_context": weak_evidence,
            },
            {
                "evidence_id": "nearby_ev",
                "page": 6,
                "evidence_type": "clause",
                "evidence_text": nearby_evidence,
                "source_context": nearby_evidence,
            },
        ]
        candidates = [
            {
                "candidate_id": "heritage_condition_missing",
                "evidence_id": "weak_ev",
                "rule_object": "lot_coverage",
                "constraint_type": "maximum",
                "constraint_scope": "lot",
                "applies_to": "lots",
                "condition": "Lots on the Community Heritage Register subject to Section 219 Covenant",
                "operator": "<=",
                "value": "60",
                "unit": "%",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_text_block",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        suggestion = outputs["evidence_repair"]["suggestions"][0]

        self.assertIn("text_condition_not_supported", outputs["review_needed"][0]["support_gaps"])
        self.assertNotIn("condition", suggestion["repairable_fields"])
        self.assertFalse(suggestion["can_retry_verification"])

    def test_use_specific_regulation_reference_goes_to_not_used(self) -> None:
        evidence = [
            {
                "evidence_id": "use_ref_001",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": (
                    "Principal Use | Rowhouse Dwellings | 101.5.2 | "
                    "Use-Specific Regulations: 101.5.2"
                ),
                "source_context": "Principal Use | Rowhouse Dwellings | Use-Specific Regulations: 101.5.2",
                "table_title": "Principal Use",
                "row_header": "Rowhouse Dwellings",
                "column_header": "Use-Specific Regulations",
                "cell_value": "101.5.2",
            }
        ]
        candidates = [
            {
                "candidate_id": "use_ref_cand_001",
                "evidence_id": "use_ref_001",
                "rule_object": "permitted_use",
                "constraint_type": "allowed",
                "constraint_scope": "district",
                "applies_to": "Rowhouse Dwellings",
                "operator": "=",
                "value": "101.5.2",
                "unit": "",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_table_image",
            }
        ]

        outputs = _run_outputs(evidence, candidates)
        rule = outputs["not_used"][0]

        self.assertEqual(outputs["verified_rules"], [])
        self.assertEqual(outputs["review_needed"], [])
        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(rule["verification_decision"], "not_used")
        self.assertIn("cross_reference_only", rule["support_gaps"])

    def test_plain_permitted_use_is_not_marked_not_used(self) -> None:
        evidence = [
            {
                "evidence_id": "use_permitted_001",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": (
                    "Principal Use | Small-Scale Multi-Unit Housing | Permitted | "
                    "Use-Specific Regulations: -"
                ),
                "source_context": "Principal Use | Small-Scale Multi-Unit Housing | Permitted",
                "table_title": "Principal Use",
                "row_header": "Small-Scale Multi-Unit Housing",
                "column_header": "Use-Specific Regulations",
                "cell_value": "Permitted",
            }
        ]
        candidates = [
            {
                "candidate_id": "use_permitted_cand_001",
                "evidence_id": "use_permitted_001",
                "rule_object": "permitted_use",
                "constraint_type": "allowed",
                "constraint_scope": "district",
                "applies_to": "Small-Scale Multi-Unit Housing",
                "operator": "allowed",
                "value": "Permitted",
                "unit": "",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_table_image",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["not_used"], [])
        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(len(outputs["review_needed"]), 1)

    def test_unknown_rule_family_goes_to_not_used_when_not_contradicted(self) -> None:
        evidence = [
            {
                "evidence_id": "lot_width_001",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": "Minimum Lot Width | Interior Lot | Small-Scale Multi-Unit | 10 m",
                "source_context": "Minimum Lot Width | Interior Lot | Small-Scale Multi-Unit | 10 m",
                "table_title": "Minimum Lot Width",
                "row_header": "Interior Lot",
                "column_header": "Small-Scale Multi-Unit",
                "cell_value": "10 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "lot_width_cand_001",
                "evidence_id": "lot_width_001",
                "rule_object": "lot_width",
                "constraint_type": "minimum",
                "constraint_scope": "minimum_lot_width",
                "applies_to": "Small-Scale Multi-Unit",
                "operator": ">=",
                "value": "10",
                "unit": "m",
                "extraction_method": "pipeline5_final_registry",
                "source_stream": "gemini_table_image",
            }
        ]

        outputs = _run_outputs(evidence, candidates)

        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(len(outputs["not_used"]), 1)
        self.assertIn("outside_current_rule_contract", outputs["not_used"][0]["support_gaps"])


class ZihaoAdapterTests(unittest.TestCase):
    def test_zihao_adapter_preserves_candidate_and_evidence_contract(self) -> None:
        evidence = [
            {
                "evidence_id": "z_ev_001",
                "source_block_id": "block_1",
                "page_number": 2,
                "evidence_type": "table_row",
                "text": "Lane Yard | 1.5 m",
            }
        ]
        rules = [
            {
                "rule_id": "z_rule_001",
                "evidence_id": "z_ev_001",
                "rule_type": "setback",
                "constraint_type": "min",
                "constraint_scope": "lane yard",
                "applies_to": "Lane Yard",
                "operator": ">=",
                "value": "1.5",
                "unit": "m",
                "confidence": 0.99,
                "verification_status": "possible_sentence_match",
            }
        ]

        adapted = adapt_zihao_outputs(evidence, rules)

        self.assertEqual(adapted["evidence_units"][0]["evidence_id"], "z_ev_001")
        self.assertEqual(adapted["rule_candidates"][0]["rule_object"], "setback")
        self.assertEqual(adapted["rule_candidates"][0]["zihao_confidence"], 0.99)
        self.assertEqual(adapted["rule_candidates"][0]["extraction_source"], "zihao")

    def test_zihao_adapter_derives_operator_and_rule_aliases(self) -> None:
        adapted = adapt_zihao_outputs(
            None,
            [
                {
                    "rule_id": "z_rule_001",
                    "rule_type": "separation",
                    "constraint_type": "min",
                    "constraint_scope": "building separation",
                    "applies_to": "buildings on the same lot",
                    "value": "2.4",
                    "unit": "m",
                    "original_excerpt": "Minimum separation of buildings on the same lot 2.4 m",
                }
            ],
        )

        candidate = adapted["rule_candidates"][0]

        self.assertEqual(candidate["rule_object"], "building_separation")
        self.assertEqual(candidate["constraint_type"], "minimum")
        self.assertEqual(candidate["operator"], ">=")

    def test_zihao_pipeline3_handoff_uses_source_evidence_id(self) -> None:
        adapted = adapt_zihao_outputs(
            [
                {
                    "evidence_id": "p3_ev_001",
                    "evidence_type": "table_cell",
                    "page_number": 2,
                    "row_label": "Lane Yard",
                    "column_header": "Small-Scale Multi-Unit",
                    "cell_text": "1.5 m",
                    "text": "Lane Yard | Small-Scale Multi-Unit | 1.5 m",
                }
            ],
            [
                {
                    "candidate_id": "p3_cand_001",
                    "rule_key": "min_lane_yard_setback",
                    "rule_object": "Lane Yard",
                    "operator": ">=",
                    "value": "1.5",
                    "unit": "m",
                    "source_stream": "deterministic_table",
                    "source_evidence_id": "p3_ev_001",
                    "source_evidence_text": "Lane Yard | Small-Scale Multi-Unit | 1.5 m",
                    "extraction_final_action": "ACCEPT",
                }
            ],
        )

        evidence = adapted["evidence_units"][0]
        candidate = adapted["rule_candidates"][0]

        self.assertEqual(evidence["evidence_id"], "p3_ev_001")
        self.assertEqual(evidence["row_header"], "Lane Yard")
        self.assertEqual(evidence["cell_value"], "1.5 m")
        self.assertEqual(candidate["evidence_id"], "p3_ev_001")
        self.assertEqual(candidate["rule_object"], "setback")
        self.assertEqual(candidate["constraint_scope"], "lane_yard")

    def test_pipeline5_registry_adapts_single_file_final_registry(self) -> None:
        adapted = adapt_pipeline5_registry(
            {
                "rules": [
                    {
                        "rule_id": "pipeline5_rule_001",
                        "merged_rule_id": "pipeline5_merged_rule_001",
                        "source_id": "page_0002__table_001",
                        "rule_key": "Minimum Lot Line Setbacks for All Buildings - Lane Yard",
                        "rule_object": "Multiple explicit scopes; see applies_to_objects",
                        "constraint_type": "minimum",
                        "subject": "Lane Yard",
                        "operator": ">=",
                        "value": "1.5",
                        "unit": "m",
                        "condition": "",
                        "exception": "",
                        "evidence_text": "Minimum Lot Line Setbacks for All Buildings | Lane Yard | 1.5 m",
                        "source_stream": "gemini_table_image",
                        "review_required": False,
                    }
                ]
            }
        )

        evidence = adapted["evidence_units"][0]
        candidate = adapted["rule_candidates"][0]

        self.assertEqual(evidence["evidence_id"], "pipeline5_merged_rule_001")
        self.assertEqual(evidence["evidence_type"], "table_cell")
        self.assertEqual(evidence["page"], 2)
        self.assertEqual(evidence["row_header"], "Lane Yard")
        self.assertEqual(candidate["rule_object"], "setback")
        self.assertEqual(candidate["constraint_scope"], "lane_yard")
        self.assertEqual(candidate["extraction_final_action"], "ACCEPT")

    def test_pipeline5_adapter_uses_unit_to_split_height_and_storeys(self) -> None:
        adapted = adapt_pipeline5_registry(
            {
                "rules": [
                    {
                        "rule_id": "pipeline5_rule_0060",
                        "merged_rule_id": "pipeline5_merged_rule_0041",
                        "source_id": "page_0002__table_001",
                        "rule_key": "Maximum Height - Accessory Buildings",
                        "rule_object": "Multiple explicit scopes; see applies_to_objects",
                        "constraint_type": "maximum",
                        "subject": "Accessory Buildings",
                        "operator": "<=",
                        "value": "4.0",
                        "unit": "m",
                        "condition": "",
                        "evidence_text": "Maximum Height | Accessory Buildings | 4.0 m | 1 storey",
                        "source_stream": "gemini_table_image",
                        "review_required": False,
                    },
                    {
                        "rule_id": "pipeline5_rule_0061",
                        "merged_rule_id": "pipeline5_merged_rule_0042",
                        "source_id": "page_0002__table_001",
                        "rule_key": "Maximum Height - Accessory Buildings",
                        "rule_object": "Multiple explicit scopes; see applies_to_objects",
                        "constraint_type": "maximum",
                        "subject": "Accessory Buildings",
                        "operator": "<=",
                        "value": "1",
                        "unit": "storeys",
                        "condition": "",
                        "evidence_text": "Maximum Height | Accessory Buildings | 4.0 m | 1 storey",
                        "source_stream": "gemini_table_image",
                        "review_required": False,
                    }
                ]
            }
        )

        candidates = {candidate["candidate_id"]: candidate for candidate in adapted["rule_candidates"]}
        outputs = _run_outputs(adapted["evidence_units"], adapted["rule_candidates"])
        verified = {rule["source"]["evidence_id"]: rule for rule in outputs["verified_rules"]}
        review = {rule["source"]["evidence_id"]: rule for rule in outputs["review_needed"]}

        self.assertEqual(candidates["pipeline5_merged_rule_0041"]["rule_object"], "height")
        self.assertEqual(candidates["pipeline5_merged_rule_0042"]["rule_object"], "storeys")
        self.assertEqual(candidates["pipeline5_merged_rule_0041"]["applies_to"], "Accessory Buildings")
        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(verified["pipeline5_merged_rule_0041"]["rule_object"], "height")
        self.assertEqual(verified["pipeline5_merged_rule_0041"]["value"], "4.0")
        self.assertEqual(verified["pipeline5_merged_rule_0041"]["unit"], "m")
        self.assertEqual(review["pipeline5_merged_rule_0042"]["rule_object"], "storeys")

    def test_pipeline5_adapter_recovers_fire_safety_rule_objects(self) -> None:
        adapted = adapt_pipeline5_registry(
            {
                "rules": [
                    {
                        "rule_id": "pipeline5_rule_0157",
                        "merged_rule_id": "pipeline5_merged_rule_0110",
                        "source_id": "page_0006__text_001",
                        "rule_key": "sprinkler_system_requirement",
                        "rule_object": "Dwelling units",
                        "subject": "automatic sprinkler system",
                        "constraint_type": "requirement",
                        "operator": "required",
                        "value": "",
                        "unit": "",
                        "condition": "Dwelling units located more than 45 m from a lot line abutting a street",
                        "evidence_text": (
                            "(1) Dwelling units located more than 45 m from a lot line abutting a street "
                            "shall contain an automatic sprinkler system."
                        ),
                        "source_stream": "gemini_text_block",
                        "review_required": False,
                    },
                    {
                        "rule_id": "pipeline5_rule_0158",
                        "merged_rule_id": "pipeline5_merged_rule_0111",
                        "source_id": "page_0006__text_002",
                        "rule_key": "fire_access_corridor_width",
                        "rule_object": "Dwelling units",
                        "subject": "fire access corridor width",
                        "constraint_type": "minimum",
                        "operator": ">=",
                        "value": "1.0",
                        "unit": "m",
                        "condition": "All dwelling units",
                        "evidence_text": "(2) All dwelling units shall have a minimum 1.0 m paved or gravel fire access corridor that:",
                        "source_stream": "gemini_text_block",
                        "review_required": False,
                    },
                ]
            }
        )

        candidates = {candidate["candidate_id"]: candidate for candidate in adapted["rule_candidates"]}
        outputs = _run_outputs(adapted["evidence_units"], adapted["rule_candidates"])
        verified = {rule["source"]["evidence_id"]: rule for rule in outputs["verified_rules"]}

        self.assertEqual(candidates["pipeline5_merged_rule_0110"]["rule_object"], "automatic_sprinkler")
        self.assertEqual(candidates["pipeline5_merged_rule_0111"]["rule_object"], "fire_access_corridor")
        self.assertEqual(candidates["pipeline5_merged_rule_0110"]["value"], 45)
        self.assertEqual(candidates["pipeline5_merged_rule_0110"]["unit"], "m")
        self.assertEqual(candidates["pipeline5_merged_rule_0110"]["operator"], ">")
        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(verified["pipeline5_merged_rule_0110"]["value"], 45)
        self.assertEqual(verified["pipeline5_merged_rule_0110"]["operator"], ">")
        self.assertEqual(verified["pipeline5_merged_rule_0111"]["constraint_scope"], "corridor_width")
        self.assertNotIn("rule_object_unit_not_compatible", verified["pipeline5_merged_rule_0111"]["support_gaps"])

    def test_pipeline5_adapter_uses_subject_for_heritage_lot_coverage(self) -> None:
        adapted = adapt_pipeline5_registry(
            {
                "rules": [
                    {
                        "rule_id": "pipeline5_rule_0167",
                        "merged_rule_id": "pipeline5_merged_rule_0120",
                        "source_id": "page_0006__text_006",
                        "rule_key": "heritage_max_lot_coverage",
                        "rule_object": "lots",
                        "subject": "lot coverage",
                        "constraint_type": "maximum",
                        "operator": "<=",
                        "value": "60",
                        "unit": "%",
                        "condition": "Lots in the R1 District on the Community Heritage Register",
                        "evidence_text": (
                            "(b) maximum lot coverage as set out in Section 101.4 may be increased "
                            "up to 60% and impervious surface area up to 70%;"
                        ),
                        "source_stream": "gemini_text_block",
                        "review_required": False,
                    },
                    {
                        "rule_id": "pipeline5_rule_0168",
                        "merged_rule_id": "pipeline5_merged_rule_0121",
                        "source_id": "page_0006__text_006",
                        "rule_key": "heritage_max_impervious_surface_area",
                        "rule_object": "lots",
                        "subject": "impervious surface area",
                        "constraint_type": "maximum",
                        "operator": "<=",
                        "value": "70",
                        "unit": "%",
                        "condition": "Lots in the R1 District on the Community Heritage Register",
                        "evidence_text": (
                            "(b) maximum lot coverage as set out in Section 101.4 may be increased "
                            "up to 60% and impervious surface area up to 70%;"
                        ),
                        "source_stream": "gemini_text_block",
                        "review_required": False,
                    }
                ]
            }
        )

        candidates = {candidate["candidate_id"]: candidate for candidate in adapted["rule_candidates"]}
        outputs = _run_outputs(adapted["evidence_units"], adapted["rule_candidates"])
        rules = {rule["source"]["evidence_id"]: rule for rule in outputs["review_needed"]}

        self.assertEqual(candidates["pipeline5_merged_rule_0120"]["rule_object"], "lot_coverage")
        self.assertEqual(candidates["pipeline5_merged_rule_0121"]["rule_object"], "impervious_surface")
        self.assertEqual(candidates["pipeline5_merged_rule_0120"]["applies_to"], "Community Heritage Register lots")
        self.assertEqual(outputs["rejected_rules"], [])
        self.assertEqual(rules["pipeline5_merged_rule_0120"]["rule_object"], "lot_coverage")
        self.assertEqual(rules["pipeline5_merged_rule_0120"]["value"], "60")
        self.assertEqual(rules["pipeline5_merged_rule_0120"]["unit"], "%")
        self.assertEqual(rules["pipeline5_merged_rule_0121"]["rule_object"], "impervious_surface")
        self.assertEqual(rules["pipeline5_merged_rule_0121"]["value"], "70")


class EvidenceContractTests(unittest.TestCase):
    def test_evidence_quality_summary_reports_grounding(self) -> None:
        evidence = [
            {
                "evidence_id": "ev_001",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Lane Yard | 1.5 m",
                "row_header": "Lane Yard",
                "cell_value": "1.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "cand_001",
                "evidence_id": "ev_001",
                "value": "1.5",
                "unit": "m",
            }
        ]

        summary = evidence_quality_summary(evidence, candidates)

        self.assertEqual(summary["candidate_evidence_match_rate"], 1.0)
        self.assertEqual(summary["candidate_value_grounding_rate"], 1.0)
        self.assertEqual(summary["candidate_unit_grounding_rate"], 1.0)


class ReviewPriorityTests(unittest.TestCase):
    def test_pure_table_gate_is_high_priority(self) -> None:
        priority = review_priority(
            "review_needed",
            0.78,
            ["table_cell_candidate_requires_review", "table_evidence_candidate_requires_review"],
        )

        self.assertEqual(priority, "high")

    def test_text_contract_only_is_medium_priority(self) -> None:
        priority = review_priority(
            "review_needed",
            0.9,
            ["text_candidate_requires_review"],
        )

        self.assertEqual(priority, "medium")

    def test_scope_or_operator_gap_is_medium_priority(self) -> None:
        priority = review_priority(
            "review_needed",
            0.68,
            ["operator_not_supported", "applies_to_not_supported"],
        )

        self.assertEqual(priority, "medium")


class ComplianceBenchmarkTests(unittest.TestCase):
    def test_unknown_proposal_field_needs_review(self) -> None:
        case = {
            "case_id": "unknown_field",
            "proposal": {"solar_panel_height_m": 2.0},
            "expected_decision": "needs_review",
            "expected_failed_checks": [],
            "expected_review_checks": ["solar_panel_height_m"],
        }

        result = evaluate_case(case, verified_rules=[], review_rules=[])

        self.assertTrue(result["matches_expected"])
        self.assertEqual(result["review_checks"][0]["reason"], "unsupported_proposal_field")

    def test_context_only_proposal_has_no_checks(self) -> None:
        case = {
            "case_id": "context_only",
            "proposal": {"roof_type": "flat"},
            "expected_decision": "needs_review",
            "expected_failed_checks": [],
            "expected_review_checks": ["proposal"],
        }

        result = evaluate_case(case, verified_rules=[], review_rules=[])

        self.assertTrue(result["matches_expected"])
        self.assertEqual(result["passed_checks"], [])
        self.assertEqual(result["review_checks"][0]["reason"], "no_checkable_proposal_fields")

    def test_expected_review_fields_are_scored(self) -> None:
        case = {
            "case_id": "needs_height_review",
            "proposal": {"rear_principal_height_m": 7.0},
            "expected_decision": "needs_review",
            "expected_failed_checks": [],
            "expected_review_checks": ["rear_principal_height_m"],
        }

        result = evaluate_case(case, verified_rules=[], review_rules=[])

        self.assertTrue(result["matches_expected"])
        self.assertTrue(result["decision_matches_expected"])
        self.assertTrue(result["review_checks_match_expected"])

    def test_right_decision_wrong_review_field_fails_case_accuracy(self) -> None:
        case = {
            "case_id": "wrong_expected_field",
            "proposal": {"rear_principal_height_m": 7.0},
            "expected_decision": "needs_review",
            "expected_failed_checks": [],
            "expected_review_checks": ["lane_yard_setback_m"],
        }

        result = evaluate_case(case, verified_rules=[], review_rules=[])
        summary = summarize_case_results([result])

        self.assertFalse(result["matches_expected"])
        self.assertTrue(result["decision_matches_expected"])
        self.assertFalse(result["review_checks_match_expected"])
        self.assertEqual(summary["proposal_decision_accuracy"], 1.0)
        self.assertEqual(summary["proposal_case_accuracy"], 0.0)
        self.assertEqual(summary["field_expectation_mismatch_count"], 1)

    def test_compliance_matches_distinctive_terms_in_verified_evidence_text(self) -> None:
        case = {
            "case_id": "rear_principal_height",
            "proposal": {"roof_type": "flat", "rear_principal_height_m": 7.4},
            "expected_decision": "rejected",
            "expected_failed_checks": ["rear_principal_height_m"],
            "expected_review_checks": [],
        }
        verified_rule = {
            "rule_id": "height_rear_flat",
            "rule_object": "height",
            "constraint_type": "maximum",
            "constraint_scope": "height",
            "applies_to": "Rowhouse 1 to 3 Units",
            "condition": "flat roof",
            "operator": "<=",
            "value": "7.0",
            "unit": "m",
            "source": {
                "evidence_text": "Maximum Height | Rear Principal Buildings | Height | flat roof: 7.0 m"
            },
        }

        result = evaluate_case(case, verified_rules=[verified_rule], review_rules=[])

        self.assertTrue(result["matches_expected"])
        self.assertEqual(result["failed_checks"][0]["rule_id"], "height_rear_flat")


class BenchmarkGateTests(unittest.TestCase):
    def test_city_without_proposal_cases_does_not_fail_proposal_gates(self) -> None:
        rule_metrics = {
            "verified_precision": 1.0,
            "false_verified_count": 0,
            "retrieval_recall_applicable": False,
            "extraction_coverage_recall": 1.0,
            "verified_or_review_recall": 1.0,
            "verified_source_support_failed_count": 0,
        }
        proposal_metrics = {
            "proposal_case_count": 0,
            "proposal_decision_accuracy": 0.0,
            "proposal_case_accuracy": 0.0,
            "false_approval_count": 0,
            "field_expectation_mismatch_count": 0,
        }

        result = _quality_gates(rule_metrics, proposal_metrics)

        self.assertTrue(result["passed"])
        self.assertNotIn("proposal_decision_accuracy_is_1", result["gates"])
        self.assertNotIn("proposal_case_accuracy_is_1", result["gates"])


class TableScopeModeTests(unittest.TestCase):
    """B1: structural proof verifies table cells; patterns are an optional override."""

    def _config(self, verification: dict) -> dict:
        return {
            "city": "Testville",
            "zone": "X1",
            "source_document": "test.pdf",
            "source_url": "http://example.test",
            "target_concept": "",
            "known_aliases": [],
            "verification": verification,
        }

    def _height_cell(self) -> tuple[list[dict], list[dict]]:
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "source_context": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "table_title": "Maximum Height",
                "row_header": "Rear Principal Buildings",
                "column_header": "",
                "cell_value": "7.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "c1",
                "evidence_id": "ev1",
                "source_stream": "gemini_table_image",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "building",
                "applies_to": "Rear Principal Buildings",
                "operator": "<=",
                "value": "7.5",
                "unit": "m",
            }
        ]
        return evidence, candidates

    def test_deny_ambiguous_verifies_table_cell_without_pattern(self) -> None:
        evidence, candidates = self._height_cell()
        config = self._config(
            {
                "table_scope_pattern_mode": "deny_ambiguous",
                # An unrelated pattern is present; the cell does not match it, yet
                # structural proof alone should verify it.
                "structured_table_scope_patterns": [{"rule_object": "setback", "all_terms": ["lane yard"]}],
            }
        )
        result = verify_candidates(config, evidence, candidates)
        self.assertEqual(len(result["verified_rules"]), 1)
        self.assertEqual(result["verified_rules"][0]["support_gaps"], [])

    def test_allow_list_reviews_table_cell_without_matching_pattern(self) -> None:
        evidence, candidates = self._height_cell()
        config = self._config(
            {
                "table_scope_pattern_mode": "allow_list",
                "structured_table_scope_patterns": [{"rule_object": "setback", "all_terms": ["lane yard"]}],
            }
        )
        result = verify_candidates(config, evidence, candidates)
        self.assertEqual(len(result["verified_rules"]), 0)
        self.assertEqual(len(result["review_needed"]), 1)

    def test_deny_ambiguous_review_action_quarantines_column(self) -> None:
        evidence, candidates = self._height_cell()
        config = self._config(
            {
                "table_scope_pattern_mode": "deny_ambiguous",
                # A matching pattern flagged action:review quarantines this column.
                "structured_table_scope_patterns": [
                    {"rule_object": "height", "all_terms": ["rear principal"], "action": "review"}
                ],
            }
        )
        result = verify_candidates(config, evidence, candidates)
        self.assertEqual(len(result["verified_rules"]), 0)

    def test_family_direction_mismatch_goes_to_review(self) -> None:
        # A "3+ Bedroom Units" minimum-count row mis-typed as dwelling_units >= 1
        # contradicts the family's max direction and must not verify.
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": "3+ Bedroom Units | 1 units | minimum number of dwelling units",
                "source_context": "3+ Bedroom Units | 1 units",
                "table_title": "",
                "row_header": "3+ Bedroom Units",
                "column_header": "",
                "cell_value": "1 units",
            }
        ]
        candidates = [
            {
                "candidate_id": "c1",
                "evidence_id": "ev1",
                "source_stream": "gemini_table_image",
                "rule_object": "dwelling_units",
                "constraint_type": "minimum",
                "operator": ">=",
                "value": "1",
                "unit": "units",
            }
        ]
        config = self._config(
            {
                "table_scope_pattern_mode": "deny_ambiguous",
                "rule_family_direction": {"dwelling_units": "max"},
            }
        )
        result = verify_candidates(config, evidence, candidates)
        self.assertEqual(len(result["verified_rules"]), 0)
        self.assertIn("rule_family_direction_mismatch", result["review_needed"][0]["support_gaps"])

    def test_table_material_condition_must_be_visible(self) -> None:
        # A cleaner table cell with the same value is not enough when the
        # candidate carries a material qualifier. This prevents evidence-repair
        # reruns from verifying a conditional rule against broader evidence.
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": "Minimum Lot Area | Small-Scale Multi-Unit | 281 m2",
                "source_context": "Minimum Lot Area | Small-Scale Multi-Unit | 281 m2",
                "table_title": "Minimum Lot Area",
                "row_header": "Lot Area",
                "column_header": "Small-Scale Multi-Unit",
                "cell_value": "281 m2",
            }
        ]
        candidates = [
            {
                "candidate_id": "c1",
                "evidence_id": "ev1",
                "source_stream": "gemini_table_image",
                "rule_object": "lot_area",
                "constraint_type": "minimum",
                "constraint_scope": "lot",
                "applies_to": "Small-Scale Multi-Unit",
                "condition": "4 Units Only",
                "operator": ">=",
                "value": "281",
                "unit": "m2",
            }
        ]
        config = self._config(
            {
                "table_scope_pattern_mode": "deny_ambiguous",
                "rule_family_direction": {"lot_area": "min"},
            }
        )
        result = verify_candidates(config, evidence, candidates)
        self.assertEqual(len(result["verified_rules"]), 0)
        self.assertIn("text_condition_not_supported", result["review_needed"][0]["support_gaps"])

    def test_table_material_condition_can_verify_when_visible(self) -> None:
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": "Minimum Lot Area | 4 Units Only | 281 m2",
                "source_context": "Minimum Lot Area | 4 Units Only | 281 m2",
                "table_title": "Minimum Lot Area",
                "row_header": "4 Units Only",
                "column_header": "",
                "cell_value": "281 m2",
            }
        ]
        candidates = [
            {
                "candidate_id": "c1",
                "evidence_id": "ev1",
                "source_stream": "gemini_table_image",
                "rule_object": "lot_area",
                "constraint_type": "minimum",
                "constraint_scope": "lot",
                "applies_to": "lot",
                "condition": "4 Units Only",
                "operator": ">=",
                "value": "281",
                "unit": "m2",
            }
        ]
        config = self._config(
            {
                "table_scope_pattern_mode": "deny_ambiguous",
                "rule_family_direction": {"lot_area": "min"},
            }
        )
        result = verify_candidates(config, evidence, candidates)
        self.assertEqual(len(result["verified_rules"]), 1)
        self.assertEqual(result["verified_rules"][0]["support_gaps"], [])


class NormalizationConfigTests(unittest.TestCase):
    """B2: normalization is config-driven; a new city overrides via its config,
    and a config without a normalization block falls back to Burnaby's defaults."""

    def _height_cell(self, row_header: str, applies_to: str) -> tuple[list[dict], list[dict]]:
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 1,
                "evidence_type": "table_cell",
                "evidence_text": f"Maximum Height | {row_header} | 11 m",
                "source_context": f"Maximum Height | {row_header} | 11 m",
                "table_title": "Maximum Height",
                "row_header": row_header,
                "column_header": "",
                "cell_value": "11 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "c1",
                "evidence_id": "ev1",
                "source_stream": "gemini_table_image",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "building",
                "applies_to": applies_to,
                "operator": "<=",
                "value": "11",
                "unit": "m",
            }
        ]
        return evidence, candidates

    def _verify(self, evidence, candidates, verification, normalization=None):
        config = {
            "city": "Testville", "zone": "X1", "source_document": "t.pdf",
            "source_url": "http://t", "target_concept": "", "known_aliases": [],
            "verification": verification,
        }
        if normalization is not None:
            config["normalization"] = normalization
        result = verify_candidates(config, evidence, candidates)
        return result["verified_rules"] + result["review_needed"]

    def test_new_city_applies_to_hint_overrides_label(self) -> None:
        # A city the verifier has never seen supplies its OWN applies_to hint via
        # config; the verifier must use it (not any Burnaby label).
        evidence, candidates = self._height_cell(row_header="Tower Form", applies_to="Building")
        rules = self._verify(
            evidence,
            candidates,
            verification={"table_scope_pattern_mode": "deny_ambiguous", "rule_family_direction": {"height": "max"}},
            normalization={"applies_to_hints": [{"rule_objects": ["height"], "all_terms": ["tower form"], "label": "Tower Form"}]},
        )
        self.assertEqual(rules[0]["applies_to"], "Tower Form")

    def test_non_burnaby_config_without_normalization_does_not_inherit_burnaby_label(self) -> None:
        # City-neutrality guard: a NON-Burnaby config ("Testville") that omits a
        # normalization block must NOT inherit Burnaby's "Rear Principal
        # Buildings" literal — it gets the neutral EMPTY_NORMALIZATION, so the
        # raw applies_to stands. (Burnaby and config=None still fall back to
        # DEFAULT_NORMALIZATION; covered by the adapter/helper tests below.)
        evidence, candidates = self._height_cell(row_header="Rear Principal Buildings", applies_to="Building")
        rules = self._verify(
            evidence,
            candidates,
            verification={"table_scope_pattern_mode": "deny_ambiguous", "rule_family_direction": {"height": "max"}},
        )
        self.assertEqual(rules[0]["applies_to"], "Building")

    def test_burnaby_config_without_normalization_uses_default_literals(self) -> None:
        # The intended fallback still works: get_normalization returns Burnaby's
        # DEFAULT_NORMALIZATION for a Burnaby config (and for config=None), so
        # Burnaby's own run is unaffected by the cross-city isolation fix.
        from burnaby_prototype.normalization_rules import (
            DEFAULT_NORMALIZATION,
            EMPTY_NORMALIZATION,
            get_normalization,
        )

        self.assertIs(get_normalization({"city": "Burnaby"}), DEFAULT_NORMALIZATION)
        self.assertIs(get_normalization(None), DEFAULT_NORMALIZATION)
        self.assertIs(get_normalization({"city": "Calgary"}), EMPTY_NORMALIZATION)

    def test_applies_to_hint_helper_in_isolation(self) -> None:
        from burnaby_prototype.normalization_rules import applies_to_hint

        hints = [{"rule_objects": ["setback"], "all_terms": ["all building"], "label": "All Buildings"}]
        self.assertEqual(applies_to_hint("setback", "minimum all building yard", hints), "All Buildings")
        self.assertIsNone(applies_to_hint("height", "minimum all building yard", hints))

    def test_adapter_does_not_leak_burnaby_label_to_a_configured_city(self) -> None:
        # A record whose text contains "accessory": Burnaby's default path stamps
        # "Accessory Buildings", but a city with its own normalization must NOT
        # inherit that Burnaby label.
        from burnaby_prototype.zihao_adapter import _applies_to_from_record

        record = {"evidence_text": "accessory structure setback", "rule_object": "setback"}
        self.assertEqual(_applies_to_from_record(record, "setback", None), "Accessory Buildings")
        city_config = {"normalization": {"applies_to_hints": [
            {"rule_objects": ["setback"], "all_terms": ["laneway"], "label": "Laneway Lot"}
        ]}}
        self.assertNotEqual(_applies_to_from_record(record, "setback", city_config), "Accessory Buildings")

    def test_non_material_condition_words_override(self) -> None:
        # The non-material word set is config-driven: a word that is material by
        # default can be marked non-material by a city's override (and vice versa).
        from burnaby_prototype.text_span_proof import _material_condition

        self.assertTrue(_material_condition("heritage"))  # default: material cue
        self.assertFalse(_material_condition("heritage", {"heritage"}))  # override: non-material


class MultiCityTests(unittest.TestCase):
    """B4: a brand-new city/zone verifies with config only -- no Python edits."""

    def test_upstream_city_segment_strips_zone(self) -> None:
        from burnaby_prototype.config import upstream_city_segment

        self.assertEqual(upstream_city_segment("burnaby_r1"), "burnaby")
        self.assertEqual(upstream_city_segment("vancouver_rt1"), "vancouver")
        self.assertEqual(upstream_city_segment("surrey"), "surrey")

    def test_new_city_verifies_structural_cell_with_config_only(self) -> None:
        # A minimal config for a city the verifier has never seen: no
        # structured_table_scope_patterns (no answer-key), no Burnaby
        # normalization. Under deny_ambiguous, structural proof alone should
        # verify a clean table cell and produce a schema-valid contract.
        config = {
            "city": "Surrey",
            "zone": "RF",
            "source_document": "surrey_rf.pdf",
            "source_url": "http://example.test/surrey",
            "target_concept": "",
            "known_aliases": [],
            "verification": {
                "structured_table_verification": True,
                "table_scope_pattern_mode": "deny_ambiguous",
                "rule_family_direction": {"height": "max", "setback": "min"},
            },
        }
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 3,
                "evidence_type": "table_cell",
                "evidence_text": "Maximum Building Height | Principal Building | 11 m",
                "source_context": "Maximum Building Height | Principal Building | 11 m",
                "table_title": "Maximum Building Height",
                "row_header": "Principal Building",
                "column_header": "",
                "cell_value": "11 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "c1",
                "evidence_id": "ev1",
                "source_stream": "gemini_table_image",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "building",
                "applies_to": "Principal Building",
                "operator": "<=",
                "value": "11",
                "unit": "m",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "surrey_rf.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output_dir = temp / "out"
            run_slim_verification(
                config_path=config_path,
                output_dir=output_dir,
                evidence_units=evidence,
                rule_candidates=candidates,
                input_mode="unit_test",
            )
            verified = json.loads((output_dir / "verified_rules.json").read_text())
            contract = json.loads((output_dir / "gis_rule_contract.json").read_text())
        self.assertEqual(len(verified), 1)
        self.assertEqual(str(verified[0]["value"]), "11")
        self.assertEqual(contract["city"], "Surrey")
        self.assertEqual(len(contract["rules"]), 1)


class GisContractTests(unittest.TestCase):
    """C1+C2: the GIS contract is slim, verified-only, and schema-valid."""

    SLIM_KEYS = {
        "rule_id", "rule_object", "constraint_type", "constraint_scope", "applies_to",
        "applicability",
        "operator", "value", "value_numeric", "unit", "condition", "exception",
        "geometry", "verification_status", "citation",
    }
    DEBUG_KEYS = {
        "proof_trace", "text_proof_trace", "table_proof_trace", "merged_proof_trace",
        "normalization_trace", "support_checks", "support_gaps", "candidate", "evidence_strength",
    }

    def _contract(self) -> dict:
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "source_context": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "table_title": "Maximum Height",
                "row_header": "Rear Principal Buildings",
                "column_header": "",
                "cell_value": "7.5 m",
            }
        ]
        candidates = [
            {
                "candidate_id": "c1",
                "evidence_id": "ev1",
                "source_stream": "gemini_table_image",
                "rule_object": "height",
                "constraint_type": "maximum",
                "constraint_scope": "building",
                "applies_to": "Rear Principal Buildings",
                "operator": "<=",
                "value": "7.5",
                "unit": "m",
            }
        ]
        return _run_outputs(evidence, candidates)["gis_contract"]

    def test_contract_is_slim_and_carries_no_debug_fields(self) -> None:
        contract = self._contract()
        self.assertTrue(contract["rules"], "expected at least one verified rule")
        for rule in contract["rules"]:
            self.assertEqual(set(rule.keys()), self.SLIM_KEYS)
            self.assertEqual(set(rule.keys()) & self.DEBUG_KEYS, set())
            self.assertEqual(rule["verification_status"], "verified")

    def test_contract_conforms_to_schema(self) -> None:
        import jsonschema
        from burnaby_prototype.slim_pipeline import _GIS_CONTRACT_SCHEMA_PATH

        schema = json.loads(_GIS_CONTRACT_SCHEMA_PATH.read_text())
        contract = self._contract()
        jsonschema.validate(contract, schema)  # passes
        # A leaked debug field must fail validation (additionalProperties: false).
        contract["rules"][0]["support_gaps"] = []
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(contract, schema)

    def test_project_gis_contract_rule_maps_citation(self) -> None:
        from burnaby_prototype.slim_pipeline import project_gis_contract_rule

        rich = {
            "rule_id": "x_1", "rule_object": "height", "value": 7.5, "unit": "m",
            "verification_status": "verified", "support_gaps": [], "proof_trace": {"a": 1},
            "source": {"document": "d.pdf", "url": "u", "page": 2, "evidence_id": "ev1", "evidence_text": "7.5 m"},
        }
        slim = project_gis_contract_rule(rich)
        self.assertNotIn("proof_trace", slim)
        self.assertNotIn("support_gaps", slim)
        self.assertEqual(slim["citation"], {"document": "d.pdf", "url": "u", "page": 2, "evidence_id": "ev1", "quote": "7.5 m"})

    def test_validate_gis_contract_passes_and_rejects(self) -> None:
        # Directly exercise the export safety gate: a clean contract validates,
        # and one carrying a leaked debug field raises (additionalProperties:false).
        import jsonschema
        from burnaby_prototype.slim_pipeline import project_gis_contract_rule, validate_gis_contract

        rule = project_gis_contract_rule({
            "rule_id": "x_1", "rule_object": "height", "constraint_type": "maximum",
            "constraint_scope": "building", "applies_to": "Building", "operator": "<=",
            "value": 7.5, "unit": "m", "condition": None, "exception": None,
            "verification_status": "verified",
            "source": {"document": "d.pdf", "url": "u", "page": 2, "evidence_id": "ev1", "evidence_text": "7.5 m"},
        })
        contract = {"city": "C", "zone": "Z", "schema_version": "1.0", "rules": [rule]}
        validate_gis_contract(contract)  # valid -> no raise
        contract["rules"][0]["support_gaps"] = []
        with self.assertRaises(jsonschema.ValidationError):
            validate_gis_contract(contract)

    def test_verified_table_rule_citation_quote_is_non_empty(self) -> None:
        # The slim citation drops cell-location fields; ensure the quote it keeps
        # is actually populated for a verified table-cell rule.
        contract = self._contract()
        for rule in contract["rules"]:
            self.assertTrue(rule["citation"]["quote"], f"empty citation quote for {rule['rule_id']}")

    def test_contract_merges_exact_duplicate_verified_rules(self) -> None:
        evidence = [
            {
                "evidence_id": "ev1",
                "page": 2,
                "evidence_type": "table_cell",
                "evidence_text": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "source_context": "Maximum Height | Rear Principal Buildings | 7.5 m",
                "table_title": "Maximum Height",
                "row_header": "Rear Principal Buildings",
                "column_header": "",
                "cell_value": "7.5 m",
            }
        ]
        candidate = {
            "evidence_id": "ev1",
            "source_stream": "gemini_table_image",
            "rule_object": "height",
            "constraint_type": "maximum",
            "constraint_scope": "building",
            "applies_to": "Rear Principal Buildings",
            "operator": "<=",
            "value": "7.5",
            "unit": "m",
        }
        outputs = _run_outputs(
            evidence,
            [
                {"candidate_id": "c1", **candidate},
                {"candidate_id": "c2", **candidate},
            ],
        )

        self.assertEqual(len(outputs["verified_rules"]), 2)
        contract = outputs["gis_contract"]
        self.assertEqual(len(contract["rules"]), 1)
        self.assertEqual(contract["deduplication"]["input_verified_rule_count"], 2)
        self.assertEqual(contract["deduplication"]["export_rule_count"], 1)
        self.assertEqual(contract["deduplication"]["duplicate_merged_count"], 1)
        self.assertEqual(
            contract["deduplication"]["duplicate_groups"][0]["merged_rule_ids"],
            [outputs["verified_rules"][1]["rule_id"]],
        )


class GisFeltExportTests(unittest.TestCase):
    """The Felt export is a pure projection of verified rules.

    It must type values safely (alpha/multi-number guards), derive a coarse
    geometry_target without ever guessing, dedupe equivalent rules into one
    buildable-area parameter without losing value-distinct ones, and never
    mutate its inputs. The schema rejects any leaked or mistyped field.
    """

    @staticmethod
    def _vrule(
        rule_id,
        rule_object,
        scope,
        *,
        applies_to="",
        condition="",
        operator=">=",
        value="1",
        unit="m",
        gis_relevance="direct",
        page=2,
    ):
        return {
            "rule_id": rule_id,
            "rule_object": rule_object,
            "constraint_scope": scope,
            "applies_to": applies_to,
            "condition": condition,
            "operator": operator,
            "value": value,
            "unit": unit,
            "gis_relevance": gis_relevance,
            "source": {"page": page, "evidence_id": f"ev_{rule_id}", "evidence_text": "cited quote"},
        }

    def test_value_numeric_alpha_and_multi_number_guards(self) -> None:
        for raw, expected in [
            ("R1", None), ("Permitted", None), ("12,000", 12000.0), ("281", 281.0),
            ("7.5", 7.5), (45, 45.0), ("0", 0.0), ("3 to 4", None),
            ("0.45 or 45%", None), ("", None), (None, None), (True, None),
        ]:
            self.assertEqual(gfe._value_numeric(raw), expected, f"_value_numeric({raw!r})")

    def test_geometry_target_by_family_and_setback_scope_never_guesses(self) -> None:
        self.assertEqual(gfe._geometry_target("height", "building"), "building_footprint")
        self.assertEqual(gfe._geometry_target("storeys", "building"), "building_footprint")
        self.assertEqual(gfe._geometry_target("building_separation", "building_separation"), "building_footprint")
        self.assertEqual(gfe._geometry_target("permitted_use", "use"), "zoning_polygon")
        self.assertEqual(gfe._geometry_target("dwelling_units", "lot"), "parcel_polygon")
        self.assertEqual(gfe._geometry_target("lot_area", "lot"), "parcel_polygon")
        self.assertEqual(gfe._geometry_target("automatic_sprinkler", "dwelling_unit"), "dwelling_unit")
        self.assertEqual(gfe._geometry_target("fire_access_corridor", "corridor_width"), "access_path")
        self.assertEqual(gfe._geometry_target("setback", "street_yard_front"), "front_lot_line")
        self.assertEqual(gfe._geometry_target("setback", "street_yard_flanking"), "side_lot_line")
        self.assertEqual(gfe._geometry_target("setback", "lane_yard"), "lane")
        self.assertEqual(gfe._geometry_target("setback", "interior_rear_yard"), "rear_lot_line")
        self.assertEqual(gfe._geometry_target("setback", "interior_side_yard"), "side_lot_line")
        self.assertIsNone(gfe._geometry_target("setback", "mystery_scope"))
        self.assertIsNone(gfe._geometry_target("parking", None))

    def test_parameter_key_merges_equivalent_and_separates_distinct(self) -> None:
        r058 = self._vrule("058", "building_separation", "building_separation", applies_to="Front and Rear Principal Buildings", value="6.0")
        r074 = self._vrule("074", "building_separation", "building_separation", applies_to="principal building", condition="located between a front and rear principal", value="6.0")
        self.assertEqual(gfe._parameter_key(r058), gfe._parameter_key(r074))
        r057 = self._vrule("057", "building_separation", "building_separation", applies_to="Rear Principal Buildings", value="2.4")
        r059 = self._vrule("059", "building_separation", "building_separation", applies_to="All Other Buildings", value="2.4")
        self.assertNotEqual(gfe._parameter_key(r057), gfe._parameter_key(r058))
        self.assertNotEqual(gfe._parameter_key(r059), gfe._parameter_key(r057))

    def test_build_export_shape_gis_ready_and_parameter_merge(self) -> None:
        verified = [
            self._vrule("001", "permitted_use", "use", applies_to="Principal Use", operator="allowed", value="Permitted", unit="", gis_relevance="context", page=1),
            self._vrule("038", "height", "building", applies_to="Front Principal Buildings", condition="sloping roof", operator="<=", value="10", unit="m"),
            self._vrule("053", "setback", "interior_side_yard", applies_to="All Buildings", operator=">=", value="0", unit="m"),
            self._vrule("058", "building_separation", "building_separation", applies_to="Front and Rear Principal Buildings", operator=">=", value="6.0", unit="m"),
            self._vrule("074", "building_separation", "building_separation", applies_to="principal building", condition="located between a front and rear principal", operator=">=", value="6.0", unit="m", page=3),
            self._vrule("040", "storeys", "building", applies_to="Front Principal Buildings", operator="<=", value="3", unit="storeys"),
            self._vrule("041", "storeys", "building", applies_to="Front Principal Buildings", operator="<=", value="2.5", unit="storeys"),
        ]
        export = build_gis_felt_export(verified, [], [], {"city": "Burnaby", "zone": "R1"})
        validate_gis_felt_export(export)  # must not raise

        cons = {c["constraint_id"]: c for c in export["constraints"]}
        self.assertEqual(len(cons), 7)
        self.assertTrue(all(c["geometry_target"] for c in export["constraints"]), "every geometry_target non-null")
        # permitted_use: non-numeric, context -> not gis_ready
        self.assertIsNone(cons["001"]["value_numeric"])
        self.assertFalse(cons["001"]["gis_ready"])
        # direct numeric -> gis_ready; value "0" -> 0.0 (not None) and still ready
        self.assertEqual(cons["038"]["value_numeric"], 10.0)
        self.assertTrue(cons["038"]["gis_ready"])
        self.assertEqual(cons["053"]["value_numeric"], 0.0)
        self.assertTrue(cons["053"]["gis_ready"])

        params = export["buildable_area_parameters"]
        # 058 + 074 (same key + value) merge into ONE parameter carrying both ids
        merged = [p for p in params.values() if {"058", "074"} <= set(p["source_rule_ids"])]
        self.assertEqual(len(merged), 1)
        # storeys 040/041 share a role key but differ in value -> kept as two, none lost
        storey_params = [p for p in params.values() if p["unit"] == "storeys"]
        self.assertEqual(len(storey_params), 2)
        self.assertEqual({p["value_numeric"] for p in storey_params}, {3.0, 2.5})

        self.assertEqual(export["export_counts"]["verified_rule_count"], 7)
        self.assertEqual(export["export_counts"]["gis_constraint_count"], 7)

    def test_schema_rejects_bad_geometry_target_and_extra_key(self) -> None:
        import jsonschema

        base = build_gis_felt_export(
            [self._vrule("038", "height", "building", applies_to="Front Principal Buildings", condition="sloping roof", operator="<=", value="10", unit="m")],
            [], [], {"city": "B", "zone": "R1"},
        )
        validate_gis_felt_export(base)  # baseline valid
        bad_enum = json.loads(json.dumps(base))
        bad_enum["constraints"][0]["geometry_target"] = "teleport"
        with self.assertRaises(jsonschema.ValidationError):
            validate_gis_felt_export(bad_enum)
        extra_key = json.loads(json.dumps(base))
        extra_key["constraints"][0]["surprise"] = 1
        with self.assertRaises(jsonschema.ValidationError):
            validate_gis_felt_export(extra_key)

    def test_build_does_not_mutate_inputs(self) -> None:
        import copy

        verified = [self._vrule("038", "height", "building", applies_to="Front Principal Buildings", condition="sloping roof", operator="<=", value="10", unit="m")]
        review = [{"rule_id": "r", "rule_object": "setback", "review_category": "missing_applies_to", "review_action_bucket": "retry_with_better_evidence", "support_gaps": ["applies_to_not_supported"]}]
        not_used = [{"rule_id": "n", "support_gaps": ["outside_current_rule_contract"]}]
        snapshot = copy.deepcopy([verified, review, not_used])
        build_gis_felt_export(verified, review, not_used, {"city": "B", "zone": "R1"})
        self.assertEqual([verified, review, not_used], snapshot, "build must not mutate its inputs")

    def test_full_registry_export_when_outputs_present(self) -> None:
        path = ROOT / "outputs" / "burnaby_r1_slim_pipeline5_registry" / "gis_felt_export.json"
        if not path.exists():
            self.skipTest("canonical outputs not generated; run scripts/run_slim_verifier.py first")
        export = json.loads(path.read_text(encoding="utf-8"))
        validate_gis_felt_export(export)
        constraints = export["constraints"]
        # 42 = the original 30 + the 13 matrix-column rules (lot coverage
        # family, per-column dwelling maxima, lot-area variants, impervious
        # 70, accessory storeys), minus 1 duplicate permitted_use row
        # (burnaby_r1_001/004 are byte-identical on every legal field) now that
        # the GIS export dedups on legal identity rather than free-text citation.
        self.assertEqual(len(constraints), 42)
        ready = [c for c in constraints if c.get("gis_ready")]
        self.assertTrue(
            all(c.get("geometry_target") and c.get("geometry") for c in ready),
            "executable GIS constraints must have a geometry target and operator",
        )
        unmapped = [c for c in constraints if not c.get("geometry_target")]
        self.assertTrue(all(not c.get("gis_ready") for c in unmapped), "unmapped constraints are review/display only")
        for constraint in unmapped:
            self.assertNotIn(constraint["parameter_key"], export["buildable_area_parameters"])
        setbacks = [c for c in constraints if c["rule_object"] == "setback"]
        mapped_setbacks = [c for c in setbacks if c.get("geometry")]
        self.assertTrue(mapped_setbacks and all(c.get("geometry", {}).get("operation") == "offset_inward" for c in mapped_setbacks))
        permitted_use = [c for c in constraints if c["rule_object"] == "permitted_use"]
        # The two byte-identical "Principal Use / Permitted" rows now merge to one
        # under legal-identity dedup (they were distinguished only by citation).
        self.assertEqual(len(permitted_use), 1)
        self.assertTrue(all(c["value_numeric"] is None for c in permitted_use))
        numeric = sum(1 for c in constraints if c["value_numeric"] is not None)
        self.assertEqual(numeric, 41)  # 42 minus the 1 permitted_use
        # The felt export is built from the legal-identity-deduped GIS set (42);
        # verified_rules.json keeps the full 43-row audit trail.
        self.assertEqual(export["export_counts"]["verified_rule_count"], 42)


class GeometryOperatorTests(unittest.TestCase):
    """Structured geometry operator: executable {operation, axis, direction}.

    Pure projection — must map every supported family to an operation, anchor
    setbacks to the right lot line, and NEVER guess (unknown family or unmapped
    setback scope -> None).
    """

    @staticmethod
    def _g(rule_object, scope=""):
        return derive_geometry_operator({"rule_object": rule_object, "constraint_scope": scope})

    def test_operation_by_family(self) -> None:
        cases = {
            ("setback", "street_yard_front"): "offset_inward",
            ("building_separation", "building_separation"): "min_separation",
            ("height", "building"): "extrude_z",
            ("storeys", "building"): "storey_count_cap",
            ("lot_coverage", "lot"): "footprint_ratio_cap",
            ("impervious_surface", "lot"): "surface_ratio_cap",
            ("lot_area", "lot"): "area_floor",
            ("dwelling_units", "lot"): "unit_count_cap",
            ("automatic_sprinkler", "dwelling_unit"): "trigger_predicate",
            ("fire_access_corridor", "corridor_width"): "clearance",
            ("permitted_use", "use"): "use_permission",
        }
        for (ro, scope), op in cases.items():
            self.assertEqual(self._g(ro, scope)["operation"], op, f"{ro}/{scope}")

    def test_setback_axis_and_direction(self) -> None:
        axes = {
            "street_yard_front": "front_lot_line",
            "street_yard_flanking": "side_lot_line",
            "lane_yard": "lane_lot_line",
            "interior_rear_yard": "rear_lot_line",
            "interior_side_yard": "side_lot_line",
        }
        for scope, axis in axes.items():
            g = self._g("setback", scope)
            self.assertEqual(g["axis"], axis)
            self.assertEqual(g["direction"], "inward")
            self.assertIn("constraint_scope", g["source_fields"])

    def test_height_is_vertical_up(self) -> None:
        g = self._g("height", "building")
        self.assertEqual((g["axis"], g["direction"]), ("vertical", "up"))

    def test_never_guesses(self) -> None:
        self.assertIsNone(self._g("parking", "lot"))          # unknown family
        self.assertIsNone(self._g("setback", "mystery_yard"))  # unmapped setback scope


class ReviewAssistantTests(unittest.TestCase):
    """The LLM review-assistant is advisory and offline-safe; it never verifies.

    Offline (no client) it must produce a deterministic heuristic brief, never
    mutate its inputs, and the module must NOT import any verifier component.
    """

    @staticmethod
    def _review_rule():
        return {
            "rule_id": "burnaby_r1_028",
            "rule_object": "lot_area",
            "constraint_scope": "lot",
            "applies_to": "Small-Scale Multi-Unit (3 to 4 Units)",
            "condition": "",
            "operator": ">=",
            "value": "281",
            "unit": "m²",
            "support_gaps": ["applies_to_not_supported"],
            "review_category": "missing_applies_to",
            "blocking_reason": "the applies_to field is not clearly grounded",
            "suggested_fix": "Ground applies_to in the cited row/column header.",
            "review_reason": "the applies_to field is not clearly grounded",
            "source": {"page": 1, "evidence_text": "4 Units Only: 281 m2"},
        }

    def test_build_messages_includes_value_gaps_and_evidence(self) -> None:
        system, user = build_messages(self._review_rule())
        self.assertIn("advisory", system.lower())
        self.assertIn("281", user)
        self.assertIn("applies_to_not_supported", user)
        self.assertIn("4 Units Only", user)

    def test_heuristic_brief_maps_applies_to_gap(self) -> None:
        brief = heuristic_brief(self._review_rule())
        self.assertEqual(brief["source"], "heuristic")
        self.assertEqual(brief["likely_fix"]["field"], "applies_to")
        self.assertTrue(brief["advisory_only"])
        self.assertEqual(brief["confidence"], 0.0)

    def test_run_offline_is_heuristic_and_advisory(self) -> None:
        report = run_review_assistant([self._review_rule()], client=None)
        self.assertEqual(report["mode"], "heuristic")
        self.assertIsNone(report["model"])
        self.assertEqual(report["item_count"], 1)
        self.assertTrue(all(item["advisory_only"] for item in report["items"]))
        self.assertTrue(any("NOT verification" in n for n in report["notes"]))

    def test_run_does_not_mutate_inputs(self) -> None:
        import copy

        rules = [self._review_rule()]
        snapshot = copy.deepcopy(rules)
        run_review_assistant(rules, client=None)
        self.assertEqual(rules, snapshot)

    def test_module_imports_no_verifier_component(self) -> None:
        # Architectural boundary: the assistant must never import the verifier,
        # decision policy, or the pipeline — so it can never influence a decision.
        source = (ROOT / "src" / "burnaby_prototype" / "llm_review_assistant.py").read_text(encoding="utf-8")
        for forbidden in ("verification", "decision_policy", "slim_pipeline", "table_natural_logic"):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from .{forbidden}", source)

    def test_advisory_verify_import_boundary_both_directions(self) -> None:
        # Parity of the boundary above, generalized to every advisory module:
        # (1) no verify-path module may import an advisory module, so advisory
        #     signals can never reach a verification decision; and
        # (2) no advisory module may import the verifier/decision policy, so it
        #     cannot re-run or shadow a decision under an advisory name.
        src_dir = ROOT / "src" / "burnaby_prototype"
        advisory = ("llm_review_assistant", "embedding_semantics", "review_resolution", "semantic_review")
        verify_path = (
            "verification",
            "decision_policy",
            "compliance",
            "support_checks",
            "text_span_proof",
            "consensus",
            "conflict_guard",
            "table_natural_logic",
            "rule_claims",
        )
        for module in verify_path:
            source = (src_dir / f"{module}.py").read_text(encoding="utf-8")
            for forbidden in advisory:
                self.assertNotIn(f"import {forbidden}", source, f"{module} imports advisory {forbidden}")
                self.assertNotIn(f"from .{forbidden}", source, f"{module} imports advisory {forbidden}")
        for module in advisory:
            source = (src_dir / f"{module}.py").read_text(encoding="utf-8")
            for forbidden in ("verification", "decision_policy"):
                self.assertNotIn(f"import {forbidden}", source, f"advisory {module} imports {forbidden}")
                self.assertNotIn(f"from .{forbidden}", source, f"advisory {module} imports {forbidden}")


class EvidenceIntelligenceTests(unittest.TestCase):
    def _config(self) -> dict:
        return json.loads(CONFIG.read_text(encoding="utf-8"))

    def _review_rule(self) -> dict:
        return {
            "rule_id": "test_r1_001",
            "rule_object": "setback",
            "constraint_type": "minimum",
            "constraint_scope": "lane_yard",
            "applies_to": "Lane Yard",
            "operator": ">=",
            "value": "1.5",
            "unit": "m",
            "condition": "",
            "support_gaps": ["applies_to_not_supported"],
            "support_checks": {
                "value_supported": True,
                "unit_supported": True,
                "operator_supported": True,
                "rule_object_supported": True,
                "scope_supported": True,
                "applies_to_supported": False,
            },
            "source": {
                "evidence_id": "ev_original",
                "page": 2,
                "evidence_text": "Minimum Lot Line Setbacks require 1.5 m.",
            },
            "candidate": {
                "candidate_id": "cand_lane",
                "evidence_id": "ev_original",
                "rule_object": "setback",
                "constraint_type": "minimum",
                "constraint_scope": "lane_yard",
                "applies_to": "Lane Yard",
                "operator": ">=",
                "value": "1.5",
                "unit": "m",
            },
        }

    def _evidence_units(self, *, exception: bool = False) -> list[dict]:
        alternate = "Minimum Lot Line Setbacks Lane Yard 1.5 m."
        if exception:
            alternate += " Subject to registration of a Section 219 Covenant."
        return [
            {
                "evidence_id": "ev_original",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": "Minimum Lot Line Setbacks require 1.5 m.",
                "source_context": "Minimum Lot Line Setbacks require 1.5 m.",
            },
            {
                "evidence_id": "ev_alternate",
                "page": 2,
                "evidence_type": "clause",
                "evidence_text": alternate,
                "source_context": alternate,
            },
        ]

    def test_evidence_intelligence_safe_retry_is_advisory_only(self) -> None:
        rule = self._review_rule()
        report = build_evidence_intelligence(
            review_rules=[rule],
            verified_rules=[],
            rule_candidates=[rule["candidate"]],
            evidence_units=self._evidence_units(),
        )
        item = report["items"][0]

        self.assertTrue(item["safe_retry"])
        self.assertEqual(item["next_action"], "rerun_with_evidence_bundle")
        self.assertNotIn("verified_rules", item)

    def test_exception_language_blocks_evidence_intelligence_retry(self) -> None:
        rule = self._review_rule()
        report = build_evidence_intelligence(
            review_rules=[rule],
            verified_rules=[],
            rule_candidates=[rule["candidate"]],
            evidence_units=self._evidence_units(exception=True),
        )
        item = report["items"][0]

        self.assertFalse(item["safe_retry"])
        self.assertTrue(any("covenant" in reason or "exception" in reason for reason in item["blocked_by"]))

    def test_bundle_rerun_promotes_only_after_deterministic_verifier_passes(self) -> None:
        rule = self._review_rule()
        evidence_units = self._evidence_units()
        # An independent table-stream candidate asserting the same rule: text
        # setbacks need cross-source consensus inside the rerun's verify pass
        # (the retry candidate copies the original's stream, so it can never
        # fabricate the second source itself).
        corroborator = {
            **rule["candidate"],
            "candidate_id": "cand_lane_table_stream",
            "source_stream": "gemini_table_image",
        }
        rule_candidates = [rule["candidate"], corroborator]
        intelligence = build_evidence_intelligence(
            review_rules=[rule],
            verified_rules=[],
            rule_candidates=rule_candidates,
            evidence_units=evidence_units,
        )
        report = run_evidence_bundle_reruns(
            self._config(),
            evidence_units,
            rule_candidates,
            [rule],
            intelligence,
        )

        self.assertEqual(report["attempt_count"], 1)
        attempt = report["attempts"][0]
        self.assertEqual(attempt["retry_decision"], "verified")
        self.assertTrue(attempt["promotion_ready"])
        self.assertEqual(attempt["promotion_risk_flags"], [])

    def test_bundle_promotion_blocks_when_bundle_fields_still_missing(self) -> None:
        verified_rules, review_rules, report = apply_bundle_promotions(
            verified_rules=[],
            review_rules=[self._review_rule()],
            bundle_rerun_report={
                "attempts": [
                    {
                        "original_rule_id": "test_r1_001",
                        "promotion_ready": True,
                        "retry_decision": "verified",
                        "retry_support_gaps": [],
                        "promotion_risk_flags": [],
                        "bundle_missing_fields": ["scope"],
                        "bundle_provenance_key": "table:test",
                        "value": "281",
                        "verified_rule": {**self._review_rule(), "support_gaps": [], "verification_decision": "verified"},
                    }
                ]
            },
        )

        self.assertEqual(verified_rules, [])
        self.assertEqual(len(review_rules), 1)
        self.assertEqual(report["promotion_count"], 0)
        self.assertEqual(report["rejected_promotions"][0]["blockers"], ["bundle_missing_fields_present"])

    def test_rule_graph_links_candidate_evidence_and_key(self) -> None:
        rule = self._review_rule()
        graph = build_rule_graph(
            rule_candidates=[rule["candidate"]],
            evidence_units=self._evidence_units(),
            verified_rules=[],
            review_rules=[rule],
        )
        edge_types = {edge["type"] for edge in graph["edges"]}

        self.assertIn("cites", edge_types)
        self.assertIn("same_canonical_key", edge_types)
        self.assertIn("missing_field", edge_types)

    def test_cache_key_invalidates_on_candidate_or_evidence_change(self) -> None:
        config = self._config()
        candidate = self._review_rule()["candidate"]
        evidence = self._evidence_units()[0]
        original_key = cache_key_for_candidate(config, candidate, evidence)

        changed_candidate = {**candidate, "value": "2.0"}
        changed_evidence = {**evidence, "evidence_text": "Minimum Lot Line Setbacks require 2.0 m."}

        self.assertNotEqual(original_key, cache_key_for_candidate(config, changed_candidate, evidence))
        self.assertNotEqual(original_key, cache_key_for_candidate(config, candidate, changed_evidence))

    def test_cache_report_marks_safe_reuse_when_context_and_decision_match(self) -> None:
        config = self._config()
        evidence_units = self._evidence_units()
        candidate = self._review_rule()["candidate"]
        verified_rule = {**self._review_rule(), "verification_decision": "verified", "support_gaps": []}
        first = build_verification_cache_report(
            config=config,
            evidence_units=evidence_units,
            rule_candidates=[candidate],
            verified_rules=[verified_rule],
            review_rules=[],
        )
        second = build_verification_cache_report(
            config=config,
            evidence_units=evidence_units,
            rule_candidates=[candidate],
            verified_rules=[verified_rule],
            review_rules=[],
            previous_cache=first,
        )

        self.assertEqual(second["cache_hit_count"], 1)
        self.assertEqual(second["safe_reuse_count"], 1)

    def test_semantic_review_finds_structured_near_match_without_verifying(self) -> None:
        review_rule = {**self._review_rule(), "support_gaps": ["applies_to_not_supported"]}
        verified_rule = {
            **self._review_rule(),
            "rule_id": "verified_lane",
            "support_gaps": [],
            "verification_decision": "verified",
        }
        report = build_semantic_review_report([review_rule], [verified_rule])
        item = report["items"][0]

        self.assertGreaterEqual(item["best_semantic_score"], 0.8)
        self.assertEqual(item["semantic_next_action"], "close_meaning_scope_review")
        self.assertNotIn("verified_rules", item)

    def test_semantic_review_embedding_improves_unlisted_synonym_match(self) -> None:
        class FakeEmbeddingBackend:
            model_name = "fake-minilm"

            def encode(self, texts: list[str]) -> list[list[float]]:
                vectors = []
                for text in texts:
                    lowered = text.lower()
                    vectors.append(
                        [
                            1.0 if "rowhouse" in lowered or "townhouse" in lowered else 0.0,
                            1.0 if "private open space" in lowered or "residence area" in lowered else 0.0,
                            1.0 if "1.2" in lowered else 0.0,
                        ]
                    )
                return vectors

        review_rule = {
            "rule_id": "review_rowhouse",
            "rule_object": "setback",
            "operator": ">=",
            "value": "1.2",
            "unit": "m",
            "constraint_scope": "rowhouse private open space",
            "applies_to": "rowhouse",
            "support_gaps": ["applies_to_not_supported"],
            "candidate": {"candidate_id": "review_rowhouse"},
        }
        verified_rule = {
            "rule_id": "verified_townhouse",
            "rule_object": "setback",
            "operator": ">=",
            "value": "1.2",
            "unit": "m",
            "constraint_scope": "townhouse residence area",
            "applies_to": "townhouse",
            "support_gaps": [],
            "verification_decision": "verified",
        }
        structured_only = build_semantic_review_report(
            [review_rule],
            [verified_rule],
            enable_embeddings=False,
        )["items"][0]
        embedded = build_semantic_review_report(
            [review_rule],
            [verified_rule],
            embedding_backend=FakeEmbeddingBackend(),
        )["items"][0]

        self.assertEqual(embedded["semantic_match_type"], "structured_plus_embedding")
        self.assertGreater(embedded["best_combined_semantic_score"], structured_only["best_semantic_score"])
        self.assertGreaterEqual(embedded["best_combined_semantic_score"], 0.82)
        self.assertEqual(embedded["best_verified_matches"][0]["embedding_score"], 1.0)
        self.assertEqual(embedded["semantic_next_action"], "close_meaning_scope_review")

    def test_semantic_embedding_is_capped_by_numeric_guardrail(self) -> None:
        class AlwaysCloseBackend:
            model_name = "fake-minilm"

            def encode(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0, 0.0] for _ in texts]

        review_rule = {
            "rule_id": "review_wrong_value",
            "rule_object": "setback",
            "operator": ">=",
            "value": "1.5",
            "unit": "m",
            "constraint_scope": "rowhouse private open space",
            "applies_to": "rowhouse",
            "support_gaps": [],
            "candidate": {"candidate_id": "review_wrong_value"},
        }
        verified_rule = {
            "rule_id": "verified_value",
            "rule_object": "setback",
            "operator": ">=",
            "value": "1.2",
            "unit": "m",
            "constraint_scope": "townhouse residence area",
            "applies_to": "townhouse",
            "support_gaps": [],
            "verification_decision": "verified",
        }
        item = build_semantic_review_report(
            [review_rule],
            [verified_rule],
            embedding_backend=AlwaysCloseBackend(),
        )["items"][0]

        self.assertLess(item["best_combined_semantic_score"], 0.82)
        self.assertIn("different_numeric_value", item["semantic_guardrail_blockers"])
        self.assertEqual(item["semantic_next_action"], "close_meaning_guardrail_blocked")

    def test_semantic_embedding_is_capped_by_missing_core_evidence(self) -> None:
        class AlwaysCloseBackend:
            model_name = "fake-minilm"

            def encode(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0, 0.0] for _ in texts]

        review_rule = {
            "rule_id": "review_missing_value",
            "rule_object": "setback",
            "operator": ">=",
            "value": "1.2",
            "unit": "m",
            "constraint_scope": "rowhouse private open space",
            "applies_to": "rowhouse",
            "support_gaps": ["value_not_found_in_evidence"],
            "candidate": {"candidate_id": "review_missing_value"},
        }
        verified_rule = {
            **review_rule,
            "rule_id": "verified_same",
            "support_gaps": [],
            "verification_decision": "verified",
        }
        item = build_semantic_review_report(
            [review_rule],
            [verified_rule],
            embedding_backend=AlwaysCloseBackend(),
        )["items"][0]

        self.assertLess(item["best_combined_semantic_score"], 0.82)
        self.assertIn("missing_core_evidence", item["semantic_guardrail_blockers"])
        self.assertEqual(item["semantic_next_action"], "close_meaning_guardrail_blocked")

    def test_semantic_review_falls_back_to_structured_only_when_embeddings_disabled(self) -> None:
        review_rule = {**self._review_rule(), "support_gaps": ["applies_to_not_supported"]}
        verified_rule = {
            **self._review_rule(),
            "rule_id": "verified_lane",
            "support_gaps": [],
            "verification_decision": "verified",
        }
        report = build_semantic_review_report([review_rule], [verified_rule], enable_embeddings=False)
        item = report["items"][0]

        self.assertEqual(report["embedding"]["mode"], "structured_only")
        self.assertEqual(report["embedding"]["reason"], "disabled")
        self.assertIsNone(item["best_embedding_score"])
        self.assertEqual(item["semantic_match_type"], "structured_only")

    def test_full_pipeline_writes_new_evidence_intelligence_outputs(self) -> None:
        outputs = _run_outputs(self._evidence_units(), [self._review_rule()["candidate"]])

        self.assertIn("evidence_intelligence", outputs)
        self.assertIn("rule_graph", outputs)
        self.assertIn("evidence_bundle_rerun", outputs)
        self.assertIn("verification_cache", outputs)
        self.assertIn("semantic_review", outputs)
        self.assertIn("review_resolution", outputs)
        self.assertGreaterEqual(outputs["evidence_intelligence"]["evidence_index_count"], 1)


class ReviewResolutionTests(unittest.TestCase):
    def _base_rule(self, gaps: list[str]) -> dict[str, Any]:
        return {
            "rule_id": "review_001",
            "candidate": {"candidate_id": "cand_001"},
            "rule_object": "height",
            "constraint_scope": "building",
            "applies_to": "Accessory structure",
            "operator": "<=",
            "value": "4.6",
            "unit": "m",
            "support_gaps": gaps,
            "source": {
                "page": 5,
                "evidence_id": "ev_001",
                "evidence_text": "An accessory structure shall not exceed 4.6 m in height.",
            },
        }

    def test_semantic_duplicate_is_advisory_not_evidence_fix(self) -> None:
        rule = self._base_rule(["text_candidate_requires_review"])
        report = build_review_resolution(
            [rule],
            review_router_report={
                "items": [
                    {
                        "rule_id": "review_001",
                        "action_bucket": "semantic_duplicate_review",
                        "semantic_verified_rule_id": "verified_001",
                        "semantic_score": 0.91,
                        "candidate_sentence": "Accessory structure has height <= 4.6 m.",
                        "evidence_sentence": "An accessory structure shall not exceed 4.6 m in height.",
                    }
                ]
            },
            evidence_bundle_rerun_report={"attempts": []},
        )
        item = report["items"][0]

        self.assertEqual(item["resolution"], "duplicate_or_degraded_extraction")
        self.assertFalse(item["can_promote_after_evidence_fix"])

    def test_text_gate_only_needs_second_source_consensus(self) -> None:
        rule = self._base_rule(["text_candidate_requires_review"])
        report = build_review_resolution(
            [rule],
            review_router_report={"items": [{"rule_id": "review_001", "action_bucket": "needs_second_source_consensus"}]},
            evidence_bundle_rerun_report={"attempts": []},
        )
        item = report["items"][0]

        self.assertEqual(item["resolution"], "needs_second_source_consensus")
        self.assertEqual(item["next_step_type"], "find_independent_corroboration")
        self.assertTrue(item["can_promote_after_evidence_fix"])

    def test_condition_gap_routes_to_condition_evidence(self) -> None:
        rule = self._base_rule(["text_condition_not_supported"])
        report = build_review_resolution(
            [rule],
            review_router_report={"items": [{"rule_id": "review_001", "action_bucket": "condition_evidence_needed"}]},
            evidence_bundle_rerun_report={"attempts": []},
        )
        item = report["items"][0]

        self.assertEqual(item["resolution"], "condition_evidence_needed")
        self.assertEqual(item["next_step_type"], "find_condition_span")


class MultiCityGeneralizationTests(unittest.TestCase):
    """Cross-city: the safety guarantee must transfer with NO hand-fit patterns."""

    def test_vancouver_config_carries_no_hand_fit_patterns(self) -> None:
        cfg = json.loads((ROOT / "configs" / "vancouver_rs.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["verification"]["structured_table_scope_patterns"], [])
        self.assertEqual(cfg["normalization"]["applies_to_hints"], [])  # clean, non-Burnaby

    def test_vancouver_precision_holds_when_holdout_present(self) -> None:
        path = ROOT / "outputs" / "vancouver_rs_slim_pipeline5_registry" / "benchmark_report.json"
        if not path.exists():
            self.skipTest("run scripts/run_vancouver_holdout.py first")
        m = json.loads(path.read_text(encoding="utf-8"))["rule_metrics"]
        # The crown jewel must survive a brand-new city with zero tuning.
        self.assertEqual(m["verified_precision"], 1.0)
        self.assertEqual(m["false_verified_count"], 0)
        self.assertGreaterEqual(m["verified_rule_count"], 1, "expected at least some transfer")
        self.assertEqual(m["verified_or_review_recall"], 1.0)

    def test_runtime_modules_do_not_import_gold_benchmark_files(self) -> None:
        # Intentionally-redundant belt-and-braces under the stricter test_no_runtime_module_reads_gold.
        runtime_modules = [
            "verification.py",
            "normalization.py",
            "support_checks.py",
            "decision_policy.py",
            "evidence_intelligence.py",
            "evidence_rerun.py",
            "semantic_review.py",
            "slim_pipeline.py",
            "zihao_adapter.py",
        ]
        forbidden = ("benchmark/gold", "burnaby_r1_gold_rules", "vancouver_rs_gold_rules")
        for name in runtime_modules:
            path = ROOT / "src" / "burnaby_prototype" / name
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, source, f"{path.name} must not depend on benchmark gold labels")


class FloorAreaFamilyTests(unittest.TestCase):
    """The laneway-home floor_area family: m2-only, max-direction, sq.m aliases."""

    def test_sq_m_spellings_canonicalize_to_m2(self) -> None:
        from burnaby_prototype.domain_schema import unit_key, unit_visible

        for spelling in ("sq. m", "sq.m", "sq m", "sqm", "m²", "m2"):
            self.assertEqual(unit_key(spelling), "m2", spelling)
        # Vancouver writes '186 sq. m' — the alias must be visible in evidence.
        self.assertTrue(unit_visible("the floor area must not exceed 186 sq. m .", "sq. m"))
        self.assertTrue(unit_visible("the floor area must not exceed 186 sq. m .", "m2"))

    def test_floor_area_is_m2_only_so_percent_exclusions_cannot_verify(self) -> None:
        # Bylaw EXCLUSION clauses ('balconies up to 8% of the floor area') match
        # the family wording but carry %; the unit gate must hard-stop them.
        from burnaby_prototype.support_checks import rule_object_unit_compatible

        self.assertTrue(rule_object_unit_compatible({"rule_object": "floor_area", "unit": "sq. m"}))
        self.assertFalse(rule_object_unit_compatible({"rule_object": "floor_area", "unit": "%"}))

    def test_floor_area_text_does_not_misroute_to_lot_area(self) -> None:
        # 'floor area' text must claim floor_area, never lot_area (whose old
        # bare-'area' cue would have matched), and lot-area text stays lot_area.
        from burnaby_prototype.normalization import normalize_candidate

        floor = normalize_candidate(
            {"rule_object": "floor_area", "value": "186", "unit": "sq. m"},
            {"evidence_text": "The floor area for a laneway house must not exceed 186 sq. m."},
            None,
        )
        self.assertEqual(floor.get("rule_object"), "floor_area")
        lot = normalize_candidate(
            {"rule_object": "lot_area", "value": "281", "unit": "m2"},
            {"evidence_text": "Minimum Lot Area | Small-Scale Multi-Unit | 281 m²"},
            None,
        )
        self.assertEqual(lot.get("rule_object"), "lot_area")


class BundlePromotionSafetyTests(unittest.TestCase):
    """Guarded bundle promotion must never stitch across logical sources (C1)
    nor launder a candidate past its native gates (C2)."""

    def test_bundle_operator_must_be_grounded_in_value_member(self) -> None:
        # Pinned from the live vancouver_rs_027 leak: the value member says
        # 'exceeds 3.7 m' (direction >) while a same-page sibling supplies
        # 'does not exceed'. The bundle must be dropped at construction.
        candidate = {"rule_object": "height", "operator": "<=", "value": "3.7", "unit": "m"}
        evidence_by_id = {
            "R1": {"evidence_id": "R1", "page": 9, "evidence_type": "clause",
                   "evidence_text": "(c) where the distance from a floor to the floor above, exceeds 3.7 m, an amount equal to the area below."},
            "R2": {"evidence_id": "R2", "page": 9, "evidence_type": "clause",
                   "evidence_text": "(iii) the ceiling height of the total area being excluded must not exceed the maximum permitted."},
        }
        bundle = [
            {"evidence_id": "R1", "raw_score": 2.0},
            {"evidence_id": "R2", "raw_score": 1.0},
        ]
        members, key, value_member = _single_source_bundle(bundle, candidate, evidence_by_id)
        self.assertEqual(members, [])
        self.assertIsNone(key)
        self.assertIsNone(value_member)
        # Control: when the value member ITSELF carries the bound wording, the
        # bundle is allowed (this is the legitimate r075/r076 shape).
        grounded = dict(evidence_by_id)
        grounded["R1"] = {**grounded["R1"], "evidence_text": "Minimum separation of buildings 3.7 m."}
        candidate_min = {**candidate, "operator": ">="}
        members, key, value_member = _single_source_bundle(bundle, candidate_min, grounded)
        self.assertTrue(members)
        self.assertEqual(value_member["evidence_id"], "R1")

    def test_provenance_key_prefers_table_then_section_then_page(self) -> None:
        self.assertEqual(_provenance_key({"table_title": "Minimum Lot Area", "page": 2}), "table:minimum lot area")
        self.assertEqual(_provenance_key({"section": "101.4", "page": 2}), "section:101.4")
        self.assertEqual(_provenance_key({"page": 5}), "page:5")

    def test_single_source_bundle_drops_cross_source_members(self) -> None:
        # The value (281) lives in a "Minimum Lot Area" table cell. A second,
        # higher-scored packet from a DIFFERENT source also contains "281" plus a
        # wrong qualifier — it must NOT be composed into the same bundle.
        evidence_by_id = {
            "A1": {"evidence_id": "A1", "page": 1, "evidence_type": "table_cell",
                   "table_title": "Minimum Lot Area", "cell_value": "281 m2",
                   "evidence_text": "Minimum Lot Area | Small-Scale Multi-Unit | 281 m2"},
            "B9": {"evidence_id": "B9", "page": 4, "evidence_type": "clause", "table_title": None,
                   "evidence_text": "Rowhouse lots may exceed 281 m2 under a covenant"},
        }
        candidate = {"value": "281"}
        bundle = [{"evidence_id": "B9", "raw_score": 9.0}, {"evidence_id": "A1", "raw_score": 8.0}]
        members, key, value_member = _single_source_bundle(bundle, candidate, evidence_by_id)
        # B9 is highest-scored AND contains 281 -> it becomes the value member, and
        # only B9's own source is kept; A1 (different table source) is dropped.
        self.assertEqual(value_member["evidence_id"], "B9")
        self.assertEqual([m["evidence_id"] for m in members], ["B9"])
        self.assertNotIn("A1", [m["evidence_id"] for m in members])

    def test_single_source_bundle_keeps_same_table_members(self) -> None:
        evidence_by_id = {
            "A1": {"evidence_id": "A1", "page": 1, "evidence_type": "table_cell",
                   "table_title": "Minimum Lot Area", "cell_value": "281 m2", "evidence_text": "281 m2"},
            "A2": {"evidence_id": "A2", "page": 2, "evidence_type": "table_cell",
                   "table_title": "Minimum Lot Area", "evidence_text": "Small-Scale Multi-Unit"},
            "Z": {"evidence_id": "Z", "page": 9, "evidence_type": "clause", "evidence_text": "unrelated"},
        }
        members, key, value_member = _single_source_bundle(
            [{"evidence_id": "A1", "raw_score": 9}, {"evidence_id": "A2", "raw_score": 8}, {"evidence_id": "Z", "raw_score": 7}],
            {"value": "281"}, evidence_by_id,
        )
        self.assertEqual(key, "table:minimum lot area")
        self.assertEqual(sorted(m["evidence_id"] for m in members), ["A1", "A2"])  # same table kept, Z dropped

    def test_single_source_bundle_none_when_value_absent(self) -> None:
        members, key, value_member = _single_source_bundle(
            [{"evidence_id": "A1", "raw_score": 9}],
            {"value": "999"},
            {"A1": {"evidence_id": "A1", "evidence_text": "no matching number here", "page": 1}},
        )
        self.assertIsNone(value_member)
        self.assertEqual(members, [])

    def test_synthetic_bundle_keeps_value_member_type_not_evidence_bundle(self) -> None:
        # C2: a table-cell value member yields a table_cell synthetic unit, so it
        # faces the table-review gates — NOT a permissive "evidence_bundle" type.
        value_member = {"evidence_id": "A1", "page": 1, "evidence_type": "table_cell",
                        "table_title": "Minimum Lot Area", "row_header": "Lot Area",
                        "column_header": "Small-Scale Multi-Unit", "cell_value": "281 m2",
                        "evidence_text": "281 m2"}
        syn = _synthetic_bundle_evidence({"rule_id": "r"}, [value_member], value_member, "table:minimum lot area")
        self.assertEqual(syn["evidence_type"], "table_cell")
        self.assertNotEqual(syn["evidence_type"], "evidence_bundle")
        self.assertEqual(syn["table_title"], "Minimum Lot Area")
        self.assertEqual(syn["bundle_provenance_key"], "table:minimum lot area")

    def test_blocker_rejects_bundle_without_provenance_key(self) -> None:
        blockers = _bundle_promotion_blockers(
            {"promotion_ready": True, "retry_decision": "verified", "retry_support_gaps": [],
             "promotion_risk_flags": [], "bundle_missing_fields": [], "bundle_provenance_key": None},
            {"rule_id": "x"},
        )
        self.assertIn("bundle_not_single_source", blockers)

    def test_apply_promotions_refuses_non_single_source_attempt(self) -> None:
        # Even a "verified, no gaps" attempt is NOT promoted if it lacks a single
        # provenance key — the defensive backstop for C1.
        review = [{"rule_id": "r1", "candidate": {}}]
        report = {"attempts": [{
            "original_rule_id": "r1", "promotion_ready": True, "retry_decision": "verified",
            "retry_support_gaps": [], "promotion_risk_flags": [], "bundle_missing_fields": [],
            "bundle_provenance_key": None, "verified_rule": {"rule_id": "r1"},
        }]}
        verified, remaining_review, promo_report = apply_bundle_promotions([], review, report)
        self.assertEqual(promo_report["promotion_count"], 0)
        self.assertEqual([r["rule_id"] for r in remaining_review], ["r1"])  # stays in review

    def test_no_runtime_module_reads_gold(self) -> None:
        # Cardinal rule: gold is benchmark-only. No src module may read a gold file.
        src = ROOT / "src" / "burnaby_prototype"
        for path in src.glob("*.py"):
            # config.py hosts the shared path resolver (formerly cities.py): it
            # builds the gold path STRING for the benchmark/runner but never
            # reads gold content — resolve_city_paths returns paths only.
            if path.name == "config.py":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("_gold_rules", text, f"{path.name} references a gold file")
            self.assertNotIn("benchmark/gold", text, f"{path.name} references the gold dir")


def _run(evidence: list[dict], candidates: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        return run_slim_verification(
            config_path=CONFIG,
            output_dir=Path(temp_dir),
            evidence_units=evidence,
            rule_candidates=candidates,
            input_mode="unit_test",
        )


def _run_outputs(evidence: list[dict], candidates: list[dict]) -> dict[str, list[dict]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        run_slim_verification(
            config_path=CONFIG,
            output_dir=output_dir,
            evidence_units=evidence,
            rule_candidates=candidates,
            input_mode="unit_test",
        )
        return {
            "verified_rules": json.loads((output_dir / "verified_rules.json").read_text()),
            "review_needed": json.loads((output_dir / "review_needed.json").read_text()),
            "rejected_rules": json.loads((output_dir / "rejected_rules.json").read_text()),
            "not_used": json.loads((output_dir / "not_used.json").read_text()),
            "evidence_intelligence": json.loads((output_dir / "evidence_intelligence.json").read_text()),
            "evidence_repair": json.loads((output_dir / "evidence_repair_suggestions.json").read_text()),
            "evidence_bundle_rerun": json.loads((output_dir / "evidence_bundle_rerun_report.json").read_text()),
            "review_router": json.loads((output_dir / "review_router.json").read_text()),
            "review_resolution": json.loads((output_dir / "review_resolution.json").read_text()),
            "rule_graph": json.loads((output_dir / "rule_graph.json").read_text()),
            "verification_cache": json.loads((output_dir / "verification_cache.json").read_text()),
            "semantic_review": json.loads((output_dir / "semantic_review_report.json").read_text()),
            "gis_contract": json.loads((output_dir / "gis_rule_contract.json").read_text()),
        }


if __name__ == "__main__":
    unittest.main()
