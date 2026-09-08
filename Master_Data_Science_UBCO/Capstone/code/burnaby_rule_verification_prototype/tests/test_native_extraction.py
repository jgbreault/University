"""Native RAG+LLM extraction V1 contract tests.

The native extractor is proposer-tier only. These tests pin its JSON contract
and the no-hardcoded-secret boundary without making network calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from burnaby_prototype.bylaw_rag import BylawIndex, load_corpus_from_sections
from burnaby_prototype.native_extraction import (
    OpenRouterChatClient,
    OpenRouterError,
    build_retrieval_queries,
    candidate_set_from_model_rules,
    load_openrouter_api_key,
    retrieve_packs,
)
from run_slim_verifier import _load_candidate_set


PACK = {
    "pack_id": "native_pack_0001",
    "chunk_id": "van_11.3.8.4_001",
    "section": "11.3.8.4",
    "page": 9,
    "source_text": (
        "11.3.8.4 The building height for a laneway house must not exceed "
        "8.5 m and 2 storeys."
    ),
    "retrieval_queries": ["laneway house height maximum"],
    "retrieval_score": 0.123,
}


class NativeCandidateContractTests(unittest.TestCase):
    def test_model_rules_become_verifier_candidate_and_evidence_records(self) -> None:
        payload = {
            "rules": [
                {
                    "rule_object": "building_height",
                    "operator": "maximum",
                    "value": "8.5",
                    "unit": "metres",
                    "applies_to": "laneway house",
                    "condition": "",
                    "exception": "",
                    "source_quote": "building height for a laneway house must not exceed 8.5 m",
                }
            ]
        }
        evidence_units, candidates = candidate_set_from_model_rules("vancouver_rs", PACK, payload)
        self.assertEqual(len(evidence_units), 1)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["rule_object"], "height")
        self.assertEqual(candidate["operator"], "<=")
        self.assertEqual(candidate["unit"], "m")
        self.assertEqual(candidate["value"], "8.5")
        self.assertEqual(candidate["extraction_final_action"], "")
        self.assertEqual(evidence_units[0]["evidence_id"], candidate["evidence_id"])
        self.assertIn("8.5 m", evidence_units[0]["evidence_text"])

    def test_unsupported_source_quote_forces_review(self) -> None:
        payload = {
            "rules": [
                {
                    "rule_object": "height",
                    "operator": "<=",
                    "value": "10",
                    "unit": "m",
                    "applies_to": "laneway house",
                    "source_quote": "the height must not exceed 10 m",
                }
            ]
        }
        _, candidates = candidate_set_from_model_rules("vancouver_rs", PACK, payload)
        self.assertEqual(candidates[0]["extraction_final_action"], "REVIEW")
        self.assertIn("source_quote_not_in_retrieved_pack", candidates[0]["extraction_review_reasons"])

    def test_different_explicit_parcel_designation_forces_review(self) -> None:
        pack = {
            **PACK,
            "source_text": (
                "Parcels designated R-Gm have the following rules. "
                "The maximum height of a Backyard Suite on a laned parcel is 10.0 metres."
            ),
        }
        payload = {
            "rules": [
                {
                    "rule_object": "height",
                    "operator": "<=",
                    "value": "10.0",
                    "unit": "m",
                    "applies_to": "Backyard Suite",
                    "condition": "on a laned parcel",
                    "source_quote": "maximum height of a Backyard Suite on a laned parcel is 10.0 metres",
                }
            ]
        }
        _, candidates = candidate_set_from_model_rules(
            "calgary_rcg",
            pack,
            payload,
            config={"zone": "RCG"},
        )
        self.assertEqual(candidates[0]["extraction_final_action"], "REVIEW")
        self.assertIn("outside_target_zone_context", candidates[0]["extraction_review_reasons"])

    def test_configured_target_sections_force_other_sections_to_review(self) -> None:
        pack = {
            **PACK,
            "section": "547(3)",
            "source_text": "The minimum area of a parcel is 90.0 square metres.",
        }
        payload = {
            "rules": [
                {
                    "rule_object": "lot_area",
                    "operator": ">=",
                    "value": "90.0",
                    "unit": "m2",
                    "applies_to": "parcel",
                    "source_quote": "minimum area of a parcel is 90.0 square metres",
                }
            ]
        }
        _, candidates = candidate_set_from_model_rules(
            "calgary_rcg",
            pack,
            payload,
            config={"bylaw": "Land Use Bylaw 1P2007 section 351 and 352"},
        )
        self.assertEqual(candidates[0]["extraction_final_action"], "REVIEW")
        self.assertIn("outside_target_section_context", candidates[0]["extraction_review_reasons"])


class NativeRetrievalTests(unittest.TestCase):
    def test_retrieval_packs_are_source_chunks_with_query_provenance(self) -> None:
        chunks = load_corpus_from_sections(
            [
                {
                    "chunk_id": "height",
                    "section": "11.3.8.4",
                    "page": 9,
                    "text": "The building height for a laneway house must not exceed 8.5 m.",
                },
                {
                    "chunk_id": "setback",
                    "section": "11.3.8.6",
                    "page": 10,
                    "text": "A laneway house must be at least 0.9 m from the rear property line.",
                },
            ]
        )
        packs = retrieve_packs(
            BylawIndex(chunks),
            ["laneway house height maximum", "laneway house rear property line"],
            top_k_per_query=2,
            max_packs=2,
            max_pack_chars=120,
        )
        self.assertEqual(len(packs), 2)
        self.assertTrue(all(pack["source_text"] for pack in packs))
        self.assertTrue(all(pack["retrieval_queries"] for pack in packs))

    def test_retrieval_queries_include_city_aliases_and_target(self) -> None:
        config = {
            "city": "Calgary",
            "zone": "RCG",
            "bylaw": "Land Use Bylaw 1P2007 section 352 Backyard Suite",
            "target_concept": "backyard suite rules",
            "known_aliases": ["backyard suite", "laneway home"],
        }
        queries = build_retrieval_queries(config)
        self.assertTrue(any("backyard suite rules" in query for query in queries))
        self.assertTrue(any("laneway home height" in query for query in queries))
        self.assertTrue(any("R-CG" in query for query in queries))
        self.assertTrue(any("352 backyard suite" in query for query in queries))


class NativeVerifierInputTests(unittest.TestCase):
    def test_run_slim_verifier_loads_native_extraction_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            evidence = [{"evidence_id": "e1", "evidence_text": "height must not exceed 8.5 m"}]
            candidates = [{"candidate_id": "c1", "evidence_id": "e1", "rule_object": "height"}]
            (out / "evidence_units.json").write_text(json.dumps(evidence), encoding="utf-8")
            (out / "rule_candidates.json").write_text(json.dumps(candidates), encoding="utf-8")
            args = argparse.Namespace(native_extraction=str(out), pipeline9_run=None, input_mode="pipeline5_registry")
            loaded = _load_candidate_set(args, "unused", {})
        self.assertEqual(loaded["evidence_units"], evidence)
        self.assertEqual(loaded["rule_candidates"], candidates)


class SecretHandlingTests(unittest.TestCase):
    def test_openrouter_key_can_be_loaded_from_gitignored_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("OPENROUTER_API_KEY=test-key\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(load_openrouter_api_key(env_path), "test-key")

    def test_no_openrouter_secret_is_hardcoded_in_repo_sources(self) -> None:
        for path in [*ROOT.glob("scripts/*.py"), *ROOT.glob("src/burnaby_prototype/**/*.py")]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("sk-or-v1-", text, str(path))


class OpenRouterRobustnessTests(unittest.TestCase):
    def test_connection_reset_becomes_openrouter_error(self) -> None:
        client = OpenRouterChatClient("test-key", model="test-model")
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionResetError("reset")):
            with self.assertRaises(OpenRouterError) as ctx:
                client.extract_rules("SOURCE")
        self.assertIn("OpenRouter request failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
