"""M5 measurement-layer tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.m7_measure import (  # noqa: E402
    audit_rule_counts,
    audit_rule_slots,
    augment_rule_slot_ledger_from_outputs,
    build_source_registry,
    build_rule_slot_ledger,
    chunk_supports_gold,
    combined_support,
    diagnose_city_run,
    evaluate_rag_retrieval,
    hard_gates,
    m4_baseline_counts,
    reconcile_m4_m55,
    resolve_m5_source_output_dir,
    source_weak_flags,
    verifier_refresh_command,
)
from benchmark.evaluate_benchmark import _score_match  # noqa: E402


class M5SourceRegistryTests(unittest.TestCase):
    def test_source_weak_flags_detect_missing_and_local_provenance(self) -> None:
        flags = source_weak_flags(
            configured_source_url="",
            provenance_url="file:///tmp/source.pdf",
            pdf_hash="",
            fetched_at="",
            page_count=None,
        )

        self.assertIn("missing_configured_source_url", flags)
        self.assertIn("local_file_provenance", flags)
        self.assertIn("tmp_file_provenance", flags)
        self.assertIn("missing_pdf_sha256", flags)
        self.assertIn("missing_fetched_at", flags)
        self.assertIn("missing_page_count", flags)

    def test_registry_uses_manifest_and_config_without_gold_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "configs").mkdir()
            (root / "benchmark" / "source_corpus" / "testville_r1").mkdir(parents=True)
            (root / "configs" / "testville_r1.json").write_text(
                json.dumps({"zone": "R1", "source_url": "https://example.test/bylaw.pdf"}),
                encoding="utf-8",
            )
            (root / "benchmark" / "source_corpus" / "testville_r1" / "manifest.json").write_text(
                json.dumps(
                    {
                        "city": "testville_r1",
                        "zone": "R1",
                        "provenance_url": "https://example.test/bylaw.pdf",
                        "fetched_at": "2026-06-15T00:00:00+00:00",
                        "pdf_sha256": "abc",
                        "page_count": 12,
                        "source_chunk_count": 40,
                        "numeric_clause_count": 8,
                    }
                ),
                encoding="utf-8",
            )

            registry = build_source_registry(root=root, cities=["testville_r1"])

        source = registry["sources"][0]
        self.assertEqual(source["city"], "testville_r1")
        self.assertEqual(source["configured_source_url"], "https://example.test/bylaw.pdf")
        self.assertEqual(source["source_status"], "strong")
        self.assertEqual(source["weak_provenance_flags"], [])


class M5RefreshCommandTests(unittest.TestCase):
    def test_refresh_prefers_existing_candidate_inputs_over_local_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "outputs" / "testville_r1_extraction" / "final_rule_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({"rules": []}), encoding="utf-8")
            source_output_dir = root / "outputs" / "m7_runs" / "testville_r1" / "google_gemini_2_5_flash_lite"
            source_output_dir.mkdir(parents=True)
            (source_output_dir / "evidence_units.json").write_text("[]", encoding="utf-8")
            (source_output_dir / "rule_candidates.json").write_text("[]", encoding="utf-8")

            mode, command = verifier_refresh_command(
                root=root,
                city="testville_r1",
                output_dir=root / "m5" / "testville_r1",
                source_output_dir=source_output_dir,
            )

        self.assertEqual(mode, "refresh_verifier_existing_candidates")
        self.assertIn("--native-extraction", command)
        self.assertIn(str(source_output_dir), command)

    def test_refresh_uses_local_registry_when_no_candidate_inputs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "outputs" / "testville_r1_extraction" / "final_rule_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({"rules": []}), encoding="utf-8")

            mode, command = verifier_refresh_command(
                root=root,
                city="testville_r1",
                output_dir=root / "m5" / "testville_r1",
                source_output_dir=root / "outputs" / "testville_r1_slim_pipeline5_registry",
            )

        self.assertEqual(mode, "refresh_verifier_pipeline5_registry")
        self.assertNotIn("--native-extraction", command)

    def test_refresh_falls_back_to_existing_candidate_inputs_without_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_output_dir = root / "outputs" / "testville_r1_slim_pipeline5_registry"
            source_output_dir.mkdir(parents=True)
            (source_output_dir / "evidence_units.json").write_text("[]", encoding="utf-8")
            (source_output_dir / "rule_candidates.json").write_text("[]", encoding="utf-8")

            mode, command = verifier_refresh_command(
                root=root,
                city="testville_r1",
                output_dir=root / "m5" / "testville_r1",
                source_output_dir=source_output_dir,
            )

        self.assertEqual(mode, "refresh_verifier_existing_candidates")
        self.assertIn("--native-extraction", command)
        self.assertIn(str(source_output_dir), command)

    def test_m5_source_prefers_native_m4_run_over_slim_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m4_dir = root / "outputs" / "m7_runs" / "testville_r1" / "google_gemini_2_5_flash_lite"
            slim_dir = root / "outputs" / "testville_r1_slim_pipeline5_registry"
            for directory in (m4_dir, slim_dir):
                directory.mkdir(parents=True)
                (directory / "evidence_units.json").write_text("[]", encoding="utf-8")
                (directory / "rule_candidates.json").write_text("[]", encoding="utf-8")

            source = resolve_m5_source_output_dir(root=root, city="testville_r1")

        self.assertEqual(source, m4_dir)

    def test_m5_source_falls_back_to_slim_registry_without_m4_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slim_dir = root / "outputs" / "testville_r1_slim_pipeline5_registry"
            slim_dir.mkdir(parents=True)
            (slim_dir / "evidence_units.json").write_text("[]", encoding="utf-8")
            (slim_dir / "rule_candidates.json").write_text("[]", encoding="utf-8")

            source = resolve_m5_source_output_dir(root=root, city="testville_r1")

        self.assertEqual(source, slim_dir)

    def test_m4_baseline_counts_read_native_m4_verified_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m4_dir = root / "outputs" / "m7_runs" / "testville_r1" / "google_gemini_2_5_flash_lite"
            m4_dir.mkdir(parents=True)
            (m4_dir / "evidence_units.json").write_text("[]", encoding="utf-8")
            (m4_dir / "rule_candidates.json").write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")
            (m4_dir / "verified_rules.json").write_text(json.dumps([{"id": 1}]), encoding="utf-8")
            (m4_dir / "review_needed.json").write_text("[]", encoding="utf-8")
            (m4_dir / "rejected_rules.json").write_text("[]", encoding="utf-8")
            (m4_dir / "not_used.json").write_text("[]", encoding="utf-8")

            counts = m4_baseline_counts(root=root, city="testville_r1")

        self.assertTrue(counts["baseline_available"])
        self.assertEqual(counts["candidate_rule_count"], 2)
        self.assertEqual(counts["verified_rule_count"], 1)


class M5RagEvalTests(unittest.TestCase):
    def test_rag_eval_measures_exact_legal_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold_dir = root / "benchmark" / "gold"
            corpus_dir = root / "benchmark" / "source_corpus" / "testville_r1"
            gold_dir.mkdir(parents=True)
            corpus_dir.mkdir(parents=True)
            (gold_dir / "testville_r1_gold_rules.json").write_text(
                json.dumps(
                    [
                        {
                            "gold_id": "height_001",
                            "rule_object": "height",
                            "constraint_type": "max",
                            "constraint_scope": "building",
                            "applies_to": "laneway house",
                            "value": "8.5",
                            "unit": "m",
                            "operator": "<=",
                            "source_block_id": "chunk_1",
                            "required_evidence_terms": ["height", "exceed", "8.5"],
                            "required_rule_terms": ["laneway"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (corpus_dir / "rag_index.json").write_text(
                json.dumps(
                    {
                        "chunks": [
                            {
                                "chunk_id": "chunk_1",
                                "section": "1.1",
                                "page": 1,
                                "text": "The height of a laneway house must not exceed 8.5 m.",
                            },
                            {
                                "chunk_id": "chunk_2",
                                "section": "2.1",
                                "page": 2,
                                "text": "Accessory parking rules are listed elsewhere.",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = evaluate_rag_retrieval(root=root, city="testville_r1", top_k=1)

        self.assertEqual(report["recall_at_k"], 1.0)
        self.assertEqual(report["source_block_hit_rate"], 1.0)
        self.assertEqual(report["exact_support_hit_rate"], 1.0)
        self.assertIsNone(report["results"][0]["failure_reason"])

    def test_combined_support_exposes_missing_operator_or_scope(self) -> None:
        gold = {
            "rule_object": "height",
            "constraint_type": "max",
            "operator": "<=",
            "value": "8.5",
            "unit": "m",
            "applies_to": "laneway house",
            "required_evidence_terms": ["height", "exceed", "8.5"],
        }

        support = combined_support(gold, "The height is 8.5 m.")

        self.assertTrue(support["value_hit"])
        self.assertTrue(support["unit_hit"])
        self.assertFalse(support["operator_hit"])
        self.assertFalse(support["exact_support_hit"])

    def test_retrieval_relevance_accepts_phrase_required_terms(self) -> None:
        gold = {
            "rule_object": "setback",
            "constraint_type": "min",
            "operator": ">=",
            "value": "1.5",
            "unit": "m",
            "constraint_scope": "rear_yard",
            "applies_to": "backyard suite",
            "required_evidence_terms": ["rear property line", "1.5"],
            "required_rule_terms": ["backyard"],
        }
        chunk = {
            "text": (
                "For a Backyard Suite, the minimum building setback from a rear "
                "property line is 1.5 metres for any portion of the building used "
                "as a Backyard Suite."
            )
        }

        self.assertTrue(chunk_supports_gold(chunk, gold))


class M5BenchmarkMatchTests(unittest.TestCase):
    def test_candidate_match_credits_storeys_unit_when_extractor_labels_height(self) -> None:
        gold = {
            "gold_id": "storeys_001",
            "rule_object": "storeys",
            "constraint_type": "max",
            "operator": "<=",
            "value": "2",
            "unit": "storeys",
            "required_rule_terms": ["laneway"],
        }
        candidate = {
            "candidate_id": "cand_storeys",
            "rule_object": "height",
            "constraint_type": "max",
            "operator": "<=",
            "value": "2",
            "unit": "storeys",
            "condition": "for a laneway house",
        }

        self.assertTrue(_score_match(gold, candidate)["matches"])


class M5RuleCountAuditTests(unittest.TestCase):
    def test_rule_count_audit_uses_loose_source_ceiling_and_duplicate_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            city = "testville_r1"
            (root / "configs").mkdir()
            (root / "configs" / f"{city}.json").write_text(
                json.dumps(
                    {
                        "zone": "R1",
                        "verification": {"gis_text_rule_contract": ["height"]},
                    }
                ),
                encoding="utf-8",
            )
            source_dir = root / "benchmark" / "source_corpus" / city
            source_dir.mkdir(parents=True)
            (source_dir / "manifest.json").write_text(
                json.dumps({"rule_like_numeric_clause_count": 2, "numeric_clause_count": 3}),
                encoding="utf-8",
            )
            (source_dir / "coverage_audit.json").write_text(
                json.dumps({"table_cell_count": 1, "table_entry_count": 1}),
                encoding="utf-8",
            )
            output_dir = root / "outputs" / city
            output_dir.mkdir(parents=True)
            duplicate_rule = {
                "rule_id": "r1",
                "rule_object": "height",
                "constraint_type": "maximum",
                "operator": "<=",
                "value": "8.5",
                "unit": "m",
                "applies_to": "laneway house",
                "constraint_scope": "height",
                "source": {"page": 1, "evidence_text": "Height must not exceed 8.5 m."},
            }
            second_duplicate = {**duplicate_rule, "rule_id": "r2"}
            out_of_contract = {**duplicate_rule, "rule_id": "r3", "rule_object": "floor_area"}
            (output_dir / "rule_candidates.json").write_text(
                json.dumps([duplicate_rule, second_duplicate, out_of_contract, {"rule_id": "r4"}]),
                encoding="utf-8",
            )
            (output_dir / "verified_rules.json").write_text(
                json.dumps([duplicate_rule, second_duplicate, out_of_contract]),
                encoding="utf-8",
            )
            for name in ("review_needed", "rejected_rules", "not_used"):
                (output_dir / f"{name}.json").write_text("[]", encoding="utf-8")

            audit = audit_rule_counts(root=root, city=city, output_dir=output_dir)

        self.assertEqual(audit["source_counts"]["loose_source_rule_slot_ceiling"], 3)
        self.assertTrue(audit["flags"]["candidate_count_exceeds_loose_source_ceiling"])
        self.assertFalse(audit["flags"]["verified_count_exceeds_loose_source_ceiling"])
        self.assertEqual(audit["flags"]["verified_exact_duplicate_count"], 1)
        self.assertEqual(audit["flags"]["verified_out_of_contract_count"], 1)


class M55SlotAuditTests(unittest.TestCase):
    def test_rule_slot_ledger_splits_clause_and_table_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            city = "testville_r1"
            _write_m55_source_fixture(root, city)

            ledger = build_rule_slot_ledger(root=root, city=city)

        self.assertEqual(ledger["clause_slot_count"], 2)
        self.assertEqual(ledger["table_slot_count"], 2)
        self.assertEqual(ledger["slot_count"], 4)
        values = {(slot["value"], slot["unit"]) for slot in ledger["slots"]}
        self.assertIn(("8.5", "m"), values)
        self.assertIn(("2", "storeys"), values)
        self.assertIn(("10", "m"), values)
        self.assertIn(("9.5", "m"), values)

    def test_slot_audit_maps_verified_rules_and_merges_duplicate_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            city = "testville_r1"
            _write_m55_source_fixture(root, city)
            output_dir = root / "outputs" / city
            output_dir.mkdir(parents=True)
            verified = [
                _slot_rule("r1", page=2, value="10", unit="m"),
                _slot_rule("r2", page=2, value="10.0", unit="m"),
            ]
            (output_dir / "verified_rules.json").write_text(json.dumps(verified), encoding="utf-8")
            (output_dir / "rule_candidates.json").write_text(json.dumps(verified), encoding="utf-8")
            for name in ("review_needed", "rejected_rules", "not_used", "evidence_units"):
                (output_dir / f"{name}.json").write_text("[]", encoding="utf-8")
            ledger = augment_rule_slot_ledger_from_outputs(
                build_rule_slot_ledger(root=root, city=city),
                output_dir=output_dir,
            )

            audit = audit_rule_slots(root=root, city=city, output_dir=output_dir, rule_slot_ledger=ledger)

        metrics = audit["slot_metrics"]
        self.assertEqual(metrics["verified_slot_mapping_rate"], 1.0)
        self.assertEqual(metrics["effective_verified_slot_count"], 1)
        self.assertEqual(metrics["raw_duplicate_verified_slot_count"], 1)
        self.assertEqual(metrics["duplicate_merged_count"], 1)
        self.assertEqual(metrics["duplicate_verified_slot_count"], 0)
        # M5.6 scored denominator: corpus-derived, deduped, never larger than raw,
        # and the observed supplement is tracked separately (de-circularized).
        self.assertLessEqual(metrics["distinct_scored_legal_slot_count"], metrics["total_rule_slots"])
        self.assertLessEqual(metrics["scored_verified_slot_count"], metrics["distinct_scored_legal_slot_count"])
        self.assertGreaterEqual(metrics["observed_supplement_slot_count"], 0)
        self.assertIn("scored_slot_confusion_matrix", audit)

    def test_hard_gates_reject_unsupported_verified_slot(self) -> None:
        gates = hard_gates(
            benchmark_report=_benchmark_report(),
            benchmark_runtime_seconds=1.0,
            slot_audit={
                "slot_metrics": {
                    "verified_slot_mapping_rate": 0.5,
                    "unsupported_verified_rule_count": 1,
                    "duplicate_verified_slot_count": 0,
                }
            },
        )

        self.assertFalse(gates["passed"])
        self.assertFalse(gates["gates"]["verified_slot_mapping_rate_is_1"])
        self.assertFalse(gates["gates"]["unsupported_verified_rule_count_is_0"])

    def test_reconciliation_labels_kept_duplicate_and_missing_slots(self) -> None:
        baseline = {
            "mappings": {
                "verified_rule_mappings": [
                    {"rule_id": "m4_a", "slot_id": "slot_a"},
                    {"rule_id": "m4_b", "slot_id": "slot_a"},
                    {"rule_id": "m4_c", "slot_id": "slot_c"},
                    {"rule_id": "m4_x", "slot_id": None},
                ]
            }
        }
        current = {
            "mappings": {
                "verified_rule_mappings": [
                    {"rule_id": "m55_a", "slot_id": "slot_a"},
                    {"rule_id": "m55_d", "slot_id": "slot_d"},
                ]
            }
        }

        report = reconcile_m4_m55(baseline_slot_audit=baseline, current_slot_audit=current)

        statuses = [row["status"] for row in report["rows"]]
        self.assertEqual(statuses, ["kept", "duplicate_merged", "missing_from_current", "unsupported_baseline"])
        self.assertEqual(report["effective_verified_slot_count_delta"], 0)
        self.assertEqual(report["new_current_slot_ids"], ["slot_d"])


class M5DiagnosisTests(unittest.TestCase):
    def test_diagnosis_prioritizes_safety_before_optimization(self) -> None:
        report = _benchmark_report(
            false_verified_count=1,
            candidate_recall=0.1,
            candidate_value_grounding_rate=0.1,
        )
        diagnosis = diagnose_city_run(
            benchmark_report=report,
            rag_report={"recall_at_k": 0.0},
            source_record={"weak_provenance_flags": ["local_file_provenance"]},
            benchmark_runtime_seconds=1.0,
        )

        self.assertEqual(diagnosis["bottlenecks"][0]["metric"], "false_verified_count")
        self.assertFalse(diagnosis["hard_gates"]["passed"])

    def test_diagnosis_flags_release_extraction_coverage_gap(self) -> None:
        report = _benchmark_report(
            candidate_recall=0.857,
            release_candidate_recall=0.857,
            candidate_value_grounding_rate=1.0,
        )
        diagnosis = diagnose_city_run(
            benchmark_report=report,
            rag_report={"recall_at_k": 1.0},
            source_record={"weak_provenance_flags": []},
            benchmark_runtime_seconds=1.0,
        )

        self.assertEqual(diagnosis["bottlenecks"][0]["stage"], "extraction")
        self.assertEqual(diagnosis["bottlenecks"][0]["metric"], "extraction_coverage_recall")

    def test_raw_candidate_artifact_gap_is_diagnostic_when_release_coverage_passes(self) -> None:
        report = _benchmark_report(candidate_recall=0.45, release_candidate_recall=0.975)
        diagnosis = diagnose_city_run(
            benchmark_report=report,
            rag_report={"recall_at_k": 1.0},
            source_record={"weak_provenance_flags": []},
            benchmark_runtime_seconds=1.0,
        )

        self.assertTrue(diagnosis["hard_gates"]["passed"])
        self.assertEqual(diagnosis["bottlenecks"][0]["stage"], "extraction_diagnostics")
        self.assertEqual(diagnosis["bottlenecks"][0]["metric"], "raw_candidate_artifact_recall")

    def test_hard_gates_accept_clean_runtime_under_limit(self) -> None:
        gates = hard_gates(benchmark_report=_benchmark_report(), benchmark_runtime_seconds=12.0)

        self.assertTrue(gates["passed"])
        self.assertTrue(gates["gates"]["false_verified_is_0"])
        self.assertTrue(gates["gates"]["runtime_under_300_seconds"])

    def test_hard_gates_reject_failed_benchmark_quality_gates(self) -> None:
        report = _benchmark_report()
        report["quality_gates"] = {
            "passed": False,
            "gates": {
                "proposal_case_accuracy_is_1": False,
            },
        }

        diagnosis = diagnose_city_run(
            benchmark_report=report,
            rag_report={"recall_at_k": 1.0},
            source_record={"weak_provenance_flags": []},
            benchmark_runtime_seconds=1.0,
        )

        self.assertFalse(diagnosis["hard_gates"]["passed"])
        self.assertEqual(diagnosis["bottlenecks"][0]["stage"], "benchmark_contract")

    def test_hard_gates_reject_verified_count_regression_against_m4(self) -> None:
        gates = hard_gates(
            benchmark_report=_benchmark_report(verified_rule_count=43),
            benchmark_runtime_seconds=1.0,
            baseline_counts={"verified_rule_count": 84},
        )

        self.assertFalse(gates["passed"])
        self.assertFalse(gates["gates"]["effective_verified_rule_count_not_below_m4_baseline"])

    def test_hard_gates_allow_raw_count_drop_when_effective_verified_count_is_preserved(self) -> None:
        gates = hard_gates(
            benchmark_report=_benchmark_report(verified_rule_count=82),
            benchmark_runtime_seconds=1.0,
            baseline_counts={"verified_rule_count": 84, "effective_verified_rule_count": 82},
            rule_count_audit={"output_counts": {"effective_verified_rule_count": 82}},
        )

        self.assertTrue(gates["gates"]["effective_verified_rule_count_not_below_m4_baseline"])

    def test_diagnosis_prioritizes_verified_count_regression_before_recall_optimization(self) -> None:
        diagnosis = diagnose_city_run(
            benchmark_report=_benchmark_report(candidate_recall=0.5, verified_rule_count=43),
            rag_report={"recall_at_k": 1.0},
            source_record={"weak_provenance_flags": []},
            benchmark_runtime_seconds=1.0,
            baseline_counts={"verified_rule_count": 84, "baseline_output_dir": "/m4"},
        )

        self.assertFalse(diagnosis["hard_gates"]["passed"])
        self.assertEqual(diagnosis["bottlenecks"][0]["stage"], "measurement_contract")
        self.assertEqual(diagnosis["bottlenecks"][0]["metric"], "effective_verified_rule_count_delta_from_m4")

    def test_hard_gates_reject_oververified_or_duplicate_outputs(self) -> None:
        gates = hard_gates(
            benchmark_report=_benchmark_report(verified_rule_count=4),
            benchmark_runtime_seconds=1.0,
            rule_count_audit={
                "flags": {
                    "verified_count_exceeds_loose_source_ceiling": True,
                    "verified_exact_duplicate_count": 1,
                }
            },
        )

        self.assertFalse(gates["passed"])
        self.assertFalse(gates["gates"]["verified_rule_count_not_above_loose_source_ceiling"])
        self.assertFalse(gates["gates"]["verified_exact_duplicate_count_is_0"])

    def test_diagnosis_flags_duplicate_verified_rules_before_extraction_volume(self) -> None:
        diagnosis = diagnose_city_run(
            benchmark_report=_benchmark_report(candidate_recall=0.5),
            rag_report={"recall_at_k": 1.0},
            source_record={"weak_provenance_flags": []},
            benchmark_runtime_seconds=1.0,
            rule_count_audit={"flags": {"verified_exact_duplicate_count": 1}},
        )

        self.assertFalse(diagnosis["hard_gates"]["passed"])
        self.assertEqual(diagnosis["bottlenecks"][0]["stage"], "deduplication")


def _write_m55_source_fixture(root: Path, city: str) -> None:
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / "configs" / f"{city}.json").write_text(
        json.dumps({"zone": "R1", "verification": {"gis_text_rule_contract": ["height", "storeys"]}}),
        encoding="utf-8",
    )
    source_dir = root / "benchmark" / "source_corpus" / city
    source_dir.mkdir(parents=True)
    (source_dir / "numeric_clause_index.json").write_text(
        json.dumps(
            [
                {
                    "chunk_id": "testville_1.1_001",
                    "page": 1,
                    "section": "1.1",
                    "rule_signal": True,
                    "text_preview": "The building height must not exceed 8.5 m and 2 storeys.",
                }
            ]
        ),
        encoding="utf-8",
    )
    (source_dir / "table_index.json").write_text(
        json.dumps(
            [
                {
                    "chunk_id": "testville_table_001",
                    "page": 2,
                    "section": "1.2",
                    "table_title": "Development Regulations",
                    "row_header": "Height",
                    "cells": [
                        {
                            "column_header": "Principal Building",
                            "cell_value": "sloping roof: 10 m | flat roof: 9.5 m",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )


def _slot_rule(rule_id: str, *, page: int, value: str, unit: str) -> dict:
    return {
        "rule_id": rule_id,
        "rule_object": "height",
        "constraint_type": "maximum",
        "constraint_scope": "height",
        "applies_to": "principal building",
        "operator": "<=",
        "value": value,
        "unit": unit,
        "source": {
            "page": page,
            "evidence_type": "table_cell",
            "table_title": "Development Regulations",
            "row_header": "Height",
            "column_header": "Principal Building",
            "cell_value": "sloping roof: 10 m | flat roof: 9.5 m",
            "evidence_text": "sloping roof: 10 m",
            "source_context": "Height | Principal Building | sloping roof: 10 m | flat roof: 9.5 m",
        },
    }


def _benchmark_report(
    *,
    false_verified_count: int = 0,
    false_approval_count: int = 0,
    candidate_recall: float = 1.0,
    release_candidate_recall: float | None = None,
    candidate_value_grounding_rate: float = 1.0,
    verified_rule_count: int = 10,
) -> dict:
    release_candidate_recall = candidate_recall if release_candidate_recall is None else release_candidate_recall
    return {
        "benchmark": "testville_r1",
        "rule_metrics": {
            "false_verified_count": false_verified_count,
            "verified_rule_count": verified_rule_count,
            "verified_precision": 1.0 if false_verified_count == 0 else 0.5,
            "verified_source_support_failed_count": 0,
            "candidate_recall": candidate_recall,
            "raw_candidate_artifact_recall": candidate_recall,
            "release_candidate_recall": release_candidate_recall,
            "extraction_coverage_recall": release_candidate_recall,
            "evidence_quality": {
                "candidate_value_grounding_rate": candidate_value_grounding_rate,
            },
            "proof_metrics": {
                "table_proof_count": 0,
                "table_proof_complete_count": 0,
            },
        },
        "proposal_metrics": {
            "false_approval_count": false_approval_count,
        },
    }


if __name__ == "__main__":
    unittest.main()
