"""Pipeline 9 adapter: join, mapping, provenance, and the re-anchoring contract.

Fixtures mirror REAL P9 records (field names verified against live runs):
rules carry source_id/review_required/warnings/list-shaped applies_to; blocks
carry block_id/original_source_id/rag_pack_id/rag_lane/rag_applicability/
original_page_number/target_filter_action — and NO source_id field.
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

from burnaby_prototype.config import load_config
from burnaby_prototype.pipeline9_adapter import (
    PROVENANCE_FIELDS,
    adapt_pipeline9_run,
    reanchor_to_source,
)
from burnaby_prototype.verification import verify_candidates

CONFIG = load_config(ROOT / "configs" / "calgary_rcg.json")

BLOCK = {
    "block_id": "test_pack_075__page_0396__local_002",
    "page_number": 116,  # pseudo page
    "reading_order": 2,
    "block_type": "paragraph",
    "original_page_number": 396,
    "original_source_id": "page_0396__local_002",
    "rag_pack_id": "test_pack_075",
    "rag_lane": "extract_now_core_packs",
    "rag_applicability": "core_rule",
    "target_filter_action": "trimmed_to_target",
    "parent_context": "RAG lane=extract_now_core_packs; original_page=396",
    "text": "minimum separation of 5.0 metres is required between the closest facade of the main residential building to the closest facade of a Backyard Suite.",
}
SIBLING = {**BLOCK, "block_id": "test_pack_075__page_0396__local_003",
           "original_source_id": "page_0396__local_003", "reading_order": 3,
           "text": "The minimum facade separation may be reduced to 1.5 metres where amenity space is provided."}

RULE = {
    "rule_id": "pipeline5_rule_0002",
    "merged_rule_id": "p9_merged_0002",
    "source_id": "test_pack_075__page_0396__local_002",
    "rule_key": "backyard_suite_separation_distance",
    "rule_object": "separation_distance",
    "constraint_type": "dimensional",
    "subject": "separation between main residential building and Backyard Suite",
    "operator": ">=",
    "value": "5.0",
    "unit": "m",
    "condition": "",
    "exception": "",
    "evidence_text": "minimum separation of 5.0 metres is required",
    "warnings": [],
    "review_required": False,
    "review_reasons": [],
    "source_stream": "gemini_text_block",
    "batch_id": "text_page_0116",
    "applies_to": [{"rule_id": "pipeline5_rule_0002", "rule_object": "separation_distance", "condition": ""}],
}


def _write_run(tmp: Path, rules: list[dict], blocks: list[dict]) -> Path:
    run = tmp / "cityrun"
    (run / "06_rule_extraction" / "batch").mkdir(parents=True)
    (run / "05_rag_visual_blocks").mkdir(parents=True)
    (run / "06_rule_extraction" / "batch" / "merged_rules_deduplicated.json").write_text(
        json.dumps(rules), encoding="utf-8"
    )
    with (run / "05_rag_visual_blocks" / "text_blocks.jsonl").open("w", encoding="utf-8") as fh:
        for block in blocks:
            fh.write(json.dumps(block) + "\n")
    (run / "pipeline9_summary.json").write_text(json.dumps({"pipeline": "p9", "city": "test"}), encoding="utf-8")
    return run


class AdapterMappingTests(unittest.TestCase):
    def _adapt(self, rules, blocks):
        with tempfile.TemporaryDirectory() as tmp:
            return adapt_pipeline9_run(_write_run(Path(tmp), rules, blocks), "test_city", CONFIG)

    def test_join_and_mapping_from_real_shapes(self) -> None:
        result = self._adapt([RULE], [BLOCK, SIBLING])
        self.assertEqual(result["summary"]["unjoined_blocks"], 0)
        candidate = result["rule_candidates"][0]
        evidence = result["evidence_units"][0]
        # Family alias: P9 'separation_distance' -> verifier family.
        self.assertEqual(candidate["rule_object"], "building_separation")
        # 'dimensional' + '>=' -> minimum.
        self.assertEqual(candidate["constraint_type"], "minimum")
        # applies_to comes from the human-meaningful subject.
        self.assertIn("Backyard Suite", candidate["applies_to"])
        # Evidence carries the TRUE page and same-pack context.
        self.assertEqual(evidence["page"], 396)
        self.assertIn("reduced to 1.5 metres", evidence["source_context"])
        # review_required=False grants NOTHING (no auto-promotion field).
        self.assertEqual(candidate["extraction_final_action"], "")

    def test_provenance_round_trip_on_both_records(self) -> None:
        result = self._adapt([RULE], [BLOCK])
        for record in (result["rule_candidates"][0], result["evidence_units"][0]):
            provenance = record["p9_provenance"]
            self.assertEqual(set(PROVENANCE_FIELDS), set(provenance))
            self.assertEqual(provenance["original_page_number"], 396)
            self.assertEqual(provenance["rag_pack_id"], "test_pack_075")
            self.assertEqual(provenance["rag_lane"], "extract_now_core_packs")
            self.assertEqual(provenance["target_filter_action"], "trimmed_to_target")

    def test_fallback_join_via_pack_and_original_source_id(self) -> None:
        # block_id differs (re-packed run) but pack + original_source_id match.
        moved = {**BLOCK, "block_id": "different_prefix__page_0396__local_002"}
        result = self._adapt([RULE], [moved])
        self.assertEqual(result["summary"]["unjoined_blocks"], 1 if False else 0)
        self.assertEqual(result["evidence_units"][0]["page"], 396)

    def test_unjoined_block_forces_review(self) -> None:
        orphan_rule = {**RULE, "source_id": "missing_pack__page_0001__local_001"}
        result = self._adapt([orphan_rule], [BLOCK])
        self.assertEqual(result["summary"]["unjoined_blocks"], 1)
        self.assertTrue(result["evidence_units"][0].get("p9_block_unjoined"))
        self.assertEqual(result["rule_candidates"][0]["extraction_final_action"], "REVIEW")

    def test_upstream_uncertainty_is_honored_asymmetrically(self) -> None:
        flagged = {**RULE, "review_required": True}
        result = self._adapt([flagged], [BLOCK])
        self.assertEqual(result["rule_candidates"][0]["extraction_final_action"], "REVIEW")
        warned = {**RULE, "warnings": ["context truncated"]}
        result = self._adapt([warned], [BLOCK])
        self.assertEqual(result["rule_candidates"][0]["extraction_final_action"], "REVIEW")

    def test_unknown_family_flows_to_verifier_unchanged(self) -> None:
        odd = {**RULE, "rule_object": "private_amenity_space"}
        result = self._adapt([odd], [BLOCK])
        self.assertEqual(result["rule_candidates"][0]["rule_object"], "private_amenity_space")

    def test_largest_extraction_wins_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _write_run(Path(tmp), [RULE], [BLOCK])
            small = run / "06_rule_extraction_smoke" / "older"
            small.mkdir(parents=True)
            (small / "merged_rules_deduplicated.json").write_text(json.dumps([RULE, RULE]), encoding="utf-8")
            result = adapt_pipeline9_run(run, "test_city", CONFIG)
            # non-smoke single-rule file beats the 2-rule smoke file.
            self.assertIn("06_rule_extraction/batch", result["summary"]["rules_path"])


class ReanchoringContractTests(unittest.TestCase):
    """Re-anchoring can provide authentic source context. It cannot promote."""

    def test_mismatch_flags_and_forces_review(self) -> None:
        # No PDF page will contain this text -> mismatch path via fake pdf?
        # Use the real Calgary source.pdf with a block claiming page 396 but
        # carrying text that is NOT on that page.
        source = ROOT / "data" / "bylaws" / "calgary_rcg" / "source.pdf"
        if not source.exists():
            self.skipTest("calgary source.pdf not cached")
        unit = {
            "evidence_id": "e1", "page": 396, "evidence_type": "clause",
            "evidence_text": "the quick brown fox jumps over the lazy zoning bylaw",
            "source_context": "",
            "p9_provenance": {"original_page_number": 396},
        }
        candidate = {"candidate_id": "c1", "evidence_id": "e1", "extraction_review_reasons": []}
        summary = reanchor_to_source([unit], [candidate], source)
        self.assertEqual(summary["mismatched"], 1)
        self.assertTrue(unit.get("rag_context_mismatch"))
        self.assertEqual(candidate["extraction_final_action"], "REVIEW")
        self.assertIn("rag_context_mismatch", candidate["extraction_review_reasons"])

    def test_successful_reanchor_repairs_context_but_verifier_still_decides(self) -> None:
        source = ROOT / "data" / "bylaws" / "calgary_rcg" / "source.pdf"
        if not source.exists():
            self.skipTest("calgary source.pdf not cached")
        # Real s.352(3) sentence: re-anchor finds it on page 396.
        unit = {
            "evidence_id": "e2", "page": 396, "evidence_type": "clause",
            "evidence_text": "minimum separation of 5.0 metres is required between the closest",
            "source_context": "",
            "p9_provenance": {"original_page_number": 396},
        }
        candidate = {
            "candidate_id": "c2", "evidence_id": "e2",
            "rule_object": "building_separation", "constraint_type": "minimum",
            "constraint_scope": "building_separation", "applies_to": "backyard suite",
            "operator": ">=", "value": "5.0", "unit": "m",
            "extraction_method": "pipeline9_rag", "source_stream": "gemini_text_block",
            "extraction_review_reasons": [],
        }
        summary = reanchor_to_source([unit], [candidate], source)
        self.assertEqual(summary["reanchored"], 1)
        self.assertTrue(unit.get("reanchored_to_source"))
        # The verifier decides; the repair itself never promotes.
        result = verify_candidates(CONFIG, [unit], [candidate])
        pool = [*result["verified_rules"], *result["review_needed"]]
        self.assertEqual(len(pool), 1)

    def test_reanchored_text_that_refutes_never_verifies(self) -> None:
        source = ROOT / "data" / "bylaws" / "calgary_rcg" / "source.pdf"
        if not source.exists():
            self.skipTest("calgary source.pdf not cached")
        # Candidate claims a 99.0 m separation; the authentic page text
        # (re-anchored from the real evidence sentence) states 5.0 m.
        unit = {
            "evidence_id": "e3", "page": 396, "evidence_type": "clause",
            "evidence_text": "minimum separation of 5.0 metres is required between the closest",
            "source_context": "",
            "p9_provenance": {"original_page_number": 396},
        }
        candidate = {
            "candidate_id": "c3", "evidence_id": "e3",
            "rule_object": "building_separation", "constraint_type": "minimum",
            "constraint_scope": "building_separation", "applies_to": "backyard suite",
            "operator": ">=", "value": "99.0", "unit": "m",
            "extraction_method": "pipeline9_rag", "source_stream": "gemini_text_block",
            "extraction_review_reasons": [],
        }
        reanchor_to_source([unit], [candidate], source)
        result = verify_candidates(CONFIG, [unit], [candidate])
        self.assertEqual(result["verified_rules"], [])
        gaps = result["review_needed"][0]["support_gaps"]
        self.assertIn("value_not_found_in_evidence", gaps)


class AdapterBoundaryTests(unittest.TestCase):
    def test_adapter_is_proposer_tier(self) -> None:
        src_dir = ROOT / "src" / "burnaby_prototype"
        adapter_source = (src_dir / "pipeline9_adapter.py").read_text(encoding="utf-8")
        for forbidden in ("from .verification", "import verification", "from .decision_policy"):
            self.assertNotIn(forbidden, adapter_source)
        for module in ("verification", "decision_policy", "slim_pipeline", "support_checks"):
            source = (src_dir / f"{module}.py").read_text(encoding="utf-8")
            self.assertNotIn("pipeline9_adapter", source, f"{module} must not import the adapter")


if __name__ == "__main__":
    unittest.main()


class StitchedEvidenceTests(unittest.TestCase):
    """P9 pre-stitched multi-block evidence must never auto-verify.

    Pinned from the live vancouver_rs_035 leak: a ceiling-height COMPUTATION
    threshold (3.1 m) verified as a height cap because P9's merger stitched
    operator/qualifier wording from neighboring blocks into one evidence_text
    — single-unit stitching that bypasses the bundle guards.
    """

    def test_bracket_labeled_multiblock_evidence_forces_review(self) -> None:
        import tempfile

        stitched_rule = {
            **RULE,
            "rule_id": "stitch_01",
            "merged_rule_id": "stitch_01",
            "source_id": "missing_pack__page_0009__local_003",
            "evidence_text": (
                "[vanc_pack_009__page_0009__local_003] (a) all floors, including earthen floor; "
                "[vanc_pack_009__page_0009__local_004] ceiling height must not exceed 3.1 m"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            run = _write_run(Path(tmp), [stitched_rule], [BLOCK])
            result = adapt_pipeline9_run(run, "test_city", CONFIG)
        candidate = result["rule_candidates"][0]
        self.assertEqual(candidate["extraction_final_action"], "REVIEW")
        self.assertIn("p9_stitched_multiblock_evidence", candidate["extraction_review_reasons"])

    def test_single_block_evidence_is_not_flagged_as_stitched(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            run = _write_run(Path(tmp), [RULE], [BLOCK])
            result = adapt_pipeline9_run(run, "test_city", CONFIG)
        candidate = result["rule_candidates"][0]
        self.assertNotIn("p9_stitched_multiblock_evidence", candidate["extraction_review_reasons"])
        self.assertEqual(candidate["extraction_final_action"], "")
