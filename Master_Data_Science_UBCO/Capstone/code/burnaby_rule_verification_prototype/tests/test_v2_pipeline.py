"""V2 cache/discovery/examiner contract tests.

These tests are offline. They pin the safety boundaries: SQLite is a cache,
RAG/discovery is advisory, and the examiner cannot write verifier authority
artifacts.
"""

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

from burnaby_prototype.v2_bakeoff import estimate_cost, model_params_hash
from burnaby_prototype.v2_discovery import build_evidence_packs, retrieval_corpus_from_packs
from burnaby_prototype.v2_examiner import (
    EXAMINER_OUTPUTS,
    PROTECTED_OUTPUTS,
    build_rerun_plan,
    heuristic_examiner_report,
    safe_write_examiner_outputs,
)
from burnaby_prototype.v2_store import V2Store, hash_json


class V2StoreTests(unittest.TestCase):
    def test_source_cache_is_keyed_by_config_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = V2Store(Path(tmp) / "runs.sqlite")
            try:
                chunks = [
                    {
                        "chunk_id": "c1",
                        "page": 1,
                        "section": "1",
                        "text": "The minimum setback is 1.5 m.",
                    }
                ]
                pdf_hash = "pdf"
                config_v1 = hash_json({"zone": "R1"})
                config_v2 = hash_json({"zone": "R2"})
                store.upsert_source_chunks(city="x", pdf_hash=pdf_hash, config_hash=config_v1, chunks=chunks)
                self.assertEqual(len(store.get_source_chunks(city="x", pdf_hash=pdf_hash, config_hash=config_v1)), 1)
                self.assertEqual(store.get_source_chunks(city="x", pdf_hash=pdf_hash, config_hash=config_v2), [])
            finally:
                store.close()

    def test_model_output_cache_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = V2Store(Path(tmp) / "runs.sqlite")
            try:
                params_hash = model_params_hash({"temperature": 0})
                store.upsert_model_output(
                    run_id="run",
                    city="burnaby_r1",
                    model_id="m",
                    params_hash=params_hash,
                    prompt_hash="prompt",
                    pack_id="p1",
                    raw={"rules": [{"value": "1.5"}]},
                    parsed_ok=True,
                    latency_ms=12,
                    input_chars=100,
                    output_chars=40,
                    cost_estimate=0.001,
                )
                cached = store.get_model_output(
                    city="burnaby_r1",
                    model_id="m",
                    params_hash=params_hash,
                    prompt_hash="prompt",
                    pack_id="p1",
                )
                self.assertEqual(cached["model_output"]["rules"][0]["value"], "1.5")
                self.assertEqual(cached["latency_ms"], 12)
            finally:
                store.close()


class V2DiscoveryTests(unittest.TestCase):
    def test_parent_context_is_attached_only_when_chunk_carries_it(self) -> None:
        config = {
            "target_concept": "laneway house",
            "known_aliases": ["laneway house"],
            "bylaw": "section 10",
        }
        without_parent = [
            {
                "chunk_id": "child",
                "page": 1,
                "section": "10(1)",
                "text": "(a) 3.0 metres from the rear property line for a laneway house",
                "parent_text": "",
                "evidence_type": "clause",
            }
        ]
        packs = build_evidence_packs(without_parent, config=config, max_packs=5, max_pack_chars=500)
        self.assertNotIn("The minimum setback is", packs[0]["source_text"])

        with_parent = [dict(without_parent[0], parent_text="The minimum setback is:")]
        packs = build_evidence_packs(with_parent, config=config, max_packs=5, max_pack_chars=500)
        self.assertIn("The minimum setback is:", packs[0]["source_text"])

    def test_table_context_stays_with_value(self) -> None:
        config = {"target_concept": "laneway house", "known_aliases": ["laneway house"]}
        chunks = [
            {
                "chunk_id": "tbl",
                "page": 2,
                "section": "",
                "text": "Laneway House | Rear yard setback | minimum | 1.5 m",
                "evidence_type": "table_cell",
                "table_title": "Laneway House",
                "row_header": "Rear yard setback",
                "column_header": "minimum",
                "cell_value": "1.5 m",
            }
        ]
        packs = build_evidence_packs(chunks, config=config, max_packs=5, max_pack_chars=500)
        self.assertEqual(packs[0]["lane"], "table_rule")
        self.assertIn("Rear yard setback", packs[0]["source_text"])
        self.assertIn("minimum", packs[0]["source_text"])
        self.assertIn("1.5 m", packs[0]["source_text"])
        self.assertEqual(retrieval_corpus_from_packs(packs)[0]["page"], 2)

    def test_verify_path_does_not_import_v2_rag_or_examiner(self) -> None:
        for rel in [
            "src/burnaby_prototype/verification.py",
            "src/burnaby_prototype/support_checks.py",
            "src/burnaby_prototype/decision_policy.py",
        ]:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("v2_discovery", text, rel)
            self.assertNotIn("v2_examiner", text, rel)
            self.assertNotIn("bylaw_rag", text, rel)


class V2BakeoffTests(unittest.TestCase):
    def test_estimated_cost_uses_model_price_table(self) -> None:
        cheap = estimate_cost("openai/gpt-oss-120b", input_chars=4000, output_chars=2000)
        strong = estimate_cost("anthropic/claude-sonnet-4.6", input_chars=4000, output_chars=2000)
        self.assertGreater(strong, cheap)
        self.assertEqual(estimate_cost("nvidia/nemotron-3-ultra-550b-a55b:free", input_chars=4000, output_chars=2000), 0.0)


class V2ExaminerTests(unittest.TestCase):
    def test_examiner_outputs_are_disjoint_from_protected_outputs(self) -> None:
        self.assertTrue(EXAMINER_OUTPUTS)
        self.assertTrue(PROTECTED_OUTPUTS)
        self.assertTrue(EXAMINER_OUTPUTS.isdisjoint(PROTECTED_OUTPUTS))

    def test_safe_write_examiner_outputs_only_writes_advisory_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report = {"advisory_only": True, "findings": []}
            suggestions = {"advisory_only": True, "items": []}
            rerun = {"advisory_only": True, "actions": []}
            safe_write_examiner_outputs(out, report, suggestions, rerun)
            self.assertTrue((out / "llm_examiner_report.json").exists())
            for protected in PROTECTED_OUTPUTS:
                self.assertFalse((out / protected).exists(), protected)

    def test_heuristic_examiner_flags_false_verified_and_low_recall(self) -> None:
        context = {
            "artifacts": {
                "benchmark_report.json": {
                    "rule_metrics": {
                        "false_verified_count": 1,
                        "verified_or_review_recall": 0.25,
                    }
                },
                "extraction_summary.json": {"retrieval_pack_count": 3},
                "review_needed.json": [],
                "rejected_rules.json": [],
                "model_cost_report.json": {},
            },
            "code": [],
            "retrieved_context": [],
        }
        report = heuristic_examiner_report(context, model=None)
        categories = {finding["category"] for finding in report["findings"]}
        self.assertIn("unsafe_verification", categories)
        self.assertIn("low_recall", categories)
        self.assertIn("retrieval_too_narrow", categories)
        plan = build_rerun_plan(report)
        self.assertTrue(plan["advisory_only"])


if __name__ == "__main__":
    unittest.main()
