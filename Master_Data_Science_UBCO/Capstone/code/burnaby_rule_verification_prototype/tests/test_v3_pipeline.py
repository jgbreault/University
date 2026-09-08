"""V3 native extraction/discovery contract tests."""

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

from burnaby_prototype.v3_discovery import (  # noqa: E402
    REPAIR_GAPS,
    build_family_queries,
    build_m4_evidence_packs,
    build_v3_evidence_packs,
    build_v3_repair_packs,
    v3_discovery_options_hash,
)
from burnaby_prototype.v2_bakeoff import _looks_like_table_pack  # noqa: E402
from burnaby_prototype.v3_report import build_v3_gap_report  # noqa: E402


class V3DiscoveryTests(unittest.TestCase):
    def test_v3_discovery_source_does_not_read_gold_or_benchmark(self) -> None:
        text = (ROOT / "src" / "burnaby_prototype" / "v3_discovery.py").read_text(encoding="utf-8")
        self.assertNotIn("benchmark", text)
        self.assertNotIn("gold", text)
        self.assertNotIn("benchmark/gold", text)

    def test_family_query_packs_include_rule_family_provenance(self) -> None:
        config = {
            "target_concept": "laneway house",
            "known_aliases": ["laneway house"],
            "zone": "R1",
        }
        chunks = [
            {
                "chunk_id": "height",
                "page": 1,
                "section": "1",
                "text": "The maximum height for a laneway house is 8.5 m.",
                "metadata": {"measurement_count": 1, "rule_cue_count": 1},
            }
        ]
        packs = build_v3_evidence_packs(chunks, config=config, max_packs=10, max_pack_chars=500)
        family_packs = [pack for pack in packs if pack.get("lane") == "family_query"]
        self.assertTrue(family_packs)
        self.assertTrue(any(pack.get("rule_family") == "height" for pack in family_packs))

    def test_pack_merge_dedupes_repeated_chunks(self) -> None:
        config = {"target_concept": "laneway house", "known_aliases": ["laneway house"], "zone": "R1"}
        chunks = [
            {
                "chunk_id": "same",
                "page": 1,
                "section": "1",
                "text": "Laneway house maximum height is 8.5 m.",
                "metadata": {"measurement_count": 1, "rule_cue_count": 1},
            },
            {
                "chunk_id": "same",
                "page": 1,
                "section": "1",
                "text": "Laneway house maximum height is 8.5 m.",
                "metadata": {"measurement_count": 1, "rule_cue_count": 1},
            },
        ]
        packs = build_v3_evidence_packs(chunks, config=config, max_packs=10, max_pack_chars=500)
        self.assertEqual(len({pack["chunk_id"] for pack in packs}), len(packs))

    def test_target_section_expansion_reads_nested_verification_config(self) -> None:
        config = {
            "target_concept": "backyard suite",
            "known_aliases": ["backyard suite"],
            "zone": "RCG",
            "verification": {"target_section_ids": ["351", "352", "358"]},
        }
        chunks = [
            {
                "chunk_id": "s358",
                "page": 398,
                "section": "358(3)",
                "text": "The building setback from the front property line is a minimum of 6.0 metres.",
                "metadata": {"measurement_count": 1, "rule_cue_count": 1},
            }
        ]
        packs = build_v3_evidence_packs(chunks, config=config, max_packs=10, max_pack_chars=500)
        self.assertTrue(any(pack.get("lane") == "target_section_expansion" for pack in packs))

    def test_family_query_table_pack_is_still_table_for_llm_routing(self) -> None:
        self.assertTrue(_looks_like_table_pack({"lane": "family_query", "chunk_id": "burnaby_r1_table_003_r018"}))

    def test_repair_packs_are_built_from_support_gaps(self) -> None:
        chunks = [
            {
                "chunk_id": "operator",
                "page": 2,
                "section": "2",
                "text": "The minimum rear setback for a laneway house is 1.5 m.",
                "metadata": {"measurement_count": 1, "rule_cue_count": 1},
            }
        ]
        run_output = {
            "review": [
                {
                    "rule_id": "r1",
                    "support_gaps": ["operator_not_supported"],
                    "candidate": {
                        "rule_object": "setback",
                        "value": "1.5",
                        "unit": "m",
                        "applies_to": "laneway house",
                    },
                    "source": {"page": 2, "section": "2"},
                }
            ],
            "rejected": [],
            "not_used": [],
        }
        packs = build_v3_repair_packs(chunks, run_output=run_output, max_packs=5, max_pack_chars=500)
        self.assertEqual(packs[0]["lane"], "review_gap_repair")
        self.assertIn("operator_not_supported", packs[0]["selected_because"])
        self.assertIn("operator_not_supported", REPAIR_GAPS)

    def test_m4_rule_signal_sweep_packs_exhaustive_numeric_rules(self) -> None:
        config = {"target_concept": "laneway house", "known_aliases": ["laneway house"], "zone": "R1"}
        chunks = []
        for index in range(45):
            chunks.append(
                {
                    "chunk_id": f"rule_{index:02d}",
                    "page": index + 1,
                    "section": str(index + 1),
                    "text": f"The maximum height is {index + 1}.0 m.",
                    "metadata": {"measurement_count": 1, "rule_cue_count": 1},
                }
            )
        packs = build_m4_evidence_packs(chunks, config=config, max_packs=80, max_pack_chars=500)
        sweep_ids = {pack["chunk_id"] for pack in packs if pack.get("lane") == "m4_rule_signal_sweep"}
        self.assertIn("rule_44", sweep_ids)
        self.assertEqual(len({pack["chunk_id"] for pack in packs}), len(chunks))

    def test_m4_discovery_hash_is_not_v3_hash(self) -> None:
        v3_hash = v3_discovery_options_hash(max_packs=100, max_pack_chars=1000, mode="v3")
        m4_hash = v3_discovery_options_hash(max_packs=100, max_pack_chars=1000, mode="m4")
        self.assertNotEqual(v3_hash, m4_hash)


class V3ReportTests(unittest.TestCase):
    def test_report_uses_benchmark_missed_fields_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "benchmark_report.json").write_text(
                json.dumps(
                    {
                        "rule_metrics": {
                            "candidate_rule_count": 1,
                            "verified_rule_count": 0,
                            "review_rule_count": 1,
                            "rejected_rule_count": 0,
                            "not_used_rule_count": 0,
                            "false_verified_count": 0,
                            "verified_source_support_failed_count": 0,
                            "verified_or_review_recall": 0.5,
                            "extraction_coverage_recall": 0.5,
                            "verifier_retention_rate": 1.0,
                            "unextracted_gold_rule_ids": ["g1"],
                            "verifier_rejected_gold_rule_ids": [],
                            "not_used_gold_rule_ids": [],
                            "missed_verified_or_review_gold_rule_ids": ["g1"],
                            "top_review_reasons": [{"reason": "operator_not_supported", "count": 1}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (out / "extraction_summary.json").write_text(json.dumps({"model": "m"}), encoding="utf-8")
            (out / "model_cost_report.json").write_text(json.dumps({"estimated_cost_usd": 0.1}), encoding="utf-8")
            report = build_v3_gap_report(
                city="test",
                output_dir=out,
                source_summary={
                    "source_chunk_count": 2,
                    "evidence_pack_count": 3,
                    "m4_source_corpus": {
                        "path": "benchmark/source_corpus/test",
                        "corpus_version": "m4_source_corpus_1",
                        "numeric_clause_count": 4,
                        "rule_like_numeric_clause_count": 3,
                        "selected_rule_like_numeric_coverage": 0.75,
                    },
                },
            )
        self.assertEqual(report["missed_rules"]["unextracted_gold_rule_ids"], ["g1"])
        self.assertTrue(report["advisory_gold_fields"])
        self.assertEqual(report["m4_source_corpus"]["numeric_clause_count"], 4)


if __name__ == "__main__":
    unittest.main()
