"""Advisory bylaw-RAG: hybrid retrieval correctness + the advisory boundary."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.bylaw_rag import (
    BylawIndex,
    build_index_payload,
    grounded_answer_prompt,
    load_corpus_from_evidence_units,
    load_corpus_from_sections,
)

SECTIONS = [
    {"section": "11.3.8.2", "page": 9, "text": "11.3.8.2 The floor area for a laneway house must not exceed the lesser of 0.25 multiplied by the site area and 186 sq. m."},
    {"section": "11.3.8.4", "page": 9, "text": "11.3.8.4 The building height for a laneway house must not exceed 8.5 m and 2 storeys."},
    {"section": "11.3.8.6", "page": 10, "text": "11.3.8.6 A laneway house must be at least 0.9 m from the ultimate rear property line."},
    {"section": "11.3.8.6", "page": 10, "text": "11.3.8.6 (c) 1.2 m from each side property line."},
    {"section": "11.3.8.5", "page": 10, "text": "11.3.8.5 The maximum site coverage is 50% of the site area for a site with a laneway house."},
]


class FakeBackend:
    """Deterministic toy embeddings: bag of indicator dimensions."""

    VOCAB = ("height", "floor", "coverage", "property", "laneway")

    def encode(self, texts):
        return [[float(word in text.lower()) for word in self.VOCAB] for text in texts]


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = load_corpus_from_sections(SECTIONS)
        self.index = BylawIndex(self.chunks)

    def test_bm25_only_mode_finds_the_governing_clause(self) -> None:
        # Lexical question (BM25 has no synonym power — that is what the
        # optional dense signal adds; see the hybrid test below).
        hits = self.index.ask("building height limit for a laneway house", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["section"], "11.3.8.4")
        self.assertIn("8.5 m", hits[0]["text"])

    def test_results_are_deterministic(self) -> None:
        first = self.index.ask("setback from the property line", top_k=5)
        second = BylawIndex(load_corpus_from_sections(SECTIONS)).ask("setback from the property line", top_k=5)
        self.assertEqual([h["chunk_id"] for h in first], [h["chunk_id"] for h in second])

    def test_parent_section_expansion_returns_whole_section(self) -> None:
        hits = self.index.ask("side property line distance", top_k=2)
        side = next(h for h in hits if "1.2 m" in h["text"])
        # The expanded section text carries BOTH 11.3.8.6 chunks.
        self.assertIn("0.9 m", side["section_text"])
        self.assertIn("1.2 m", side["section_text"])

    def test_hybrid_fusion_uses_both_signals(self) -> None:
        hybrid = BylawIndex(self.chunks, embedding_backend=FakeBackend())
        hits = hybrid.search("floor area limits", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["section"], "11.3.8.2")
        self.assertIn("bm25_rank", hits[0]["signals"])
        self.assertIn("dense_rank", hits[0]["signals"])

    def test_zero_signal_questions_return_empty(self) -> None:
        self.assertEqual(self.index.search("zzz qqq xxx"), [])

    def test_evidence_units_fallback_corpus(self) -> None:
        units = [
            {"evidence_id": "ev1", "page": 2, "table_title": "Maximum Height",
             "row_header": "Front Principal", "cell_value": "10 m",
             "evidence_text": "Maximum Height | Front Principal | 10 m"},
            {"evidence_id": "ev2", "page": 3, "evidence_text": ""},
        ]
        chunks = load_corpus_from_evidence_units(units)
        self.assertEqual(len(chunks), 1)  # empty-text unit dropped
        index = BylawIndex(chunks)
        self.assertEqual(index.ask("maximum height")[0]["chunk_id"], "ev1")

    def test_grounded_answer_prompt_cites_only_retrieved_sections(self) -> None:
        hits = self.index.ask("building height limit for a laneway house", top_k=2)
        prompt = grounded_answer_prompt("building height limit for a laneway house", hits)
        self.assertIn("ONLY the bylaw sections", prompt)
        self.assertIn("[11.3.8.4]", prompt)
        self.assertIn("do not speculate", prompt)

    def test_index_payload_round_trip(self) -> None:
        payload = build_index_payload(self.chunks)
        self.assertEqual(payload["chunk_count"], len(self.chunks))
        rebuilt = BylawIndex(payload["chunks"])
        self.assertEqual(
            rebuilt.ask("height")[0]["chunk_id"], self.index.ask("height")[0]["chunk_id"]
        )


class AdvisoryBoundaryTests(unittest.TestCase):
    def test_rag_respects_the_verify_boundary_both_directions(self) -> None:
        src_dir = ROOT / "src" / "burnaby_prototype"
        rag_source = (src_dir / "bylaw_rag.py").read_text(encoding="utf-8")
        for forbidden in ("verification", "decision_policy", "slim_pipeline"):
            self.assertNotIn(f"import {forbidden}", rag_source)
            self.assertNotIn(f"from .{forbidden}", rag_source)
        verify_path = (
            "verification", "decision_policy", "compliance", "support_checks",
            "text_span_proof", "table_natural_logic", "consensus",
            "conflict_guard", "rule_claims", "slim_pipeline",
        )
        for module in verify_path:
            source = (src_dir / f"{module}.py").read_text(encoding="utf-8")
            self.assertNotIn("bylaw_rag", source, f"{module} must not import bylaw_rag")


if __name__ == "__main__":
    unittest.main()


class QueryExpansionTests(unittest.TestCase):
    """Deterministic expansion closes BM25's synonym gap — pinned before/after."""

    def setUp(self) -> None:
        self.index = BylawIndex(load_corpus_from_sections(SECTIONS))

    def test_colloquial_height_question_finds_the_height_cap(self) -> None:
        from burnaby_prototype.bylaw_rag import expand_query_terms

        # 'tall' is not in any chunk; expansion adds 'height'.
        self.assertIn("height", expand_query_terms("how tall can a laneway house be"))
        hits = self.index.ask("how tall can a laneway house be", top_k=1)
        self.assertEqual(hits[0]["section"], "11.3.8.4")

    def test_domain_vocabulary_expansion_is_derived_not_hardcoded(self) -> None:
        from burnaby_prototype.bylaw_rag import expand_query_terms

        # 'fsr' expands through domain_schema's unit aliases to 'floor/space/ratio'.
        expanded = set(expand_query_terms("what is the fsr"))
        self.assertIn("floor", expanded)
        self.assertIn("ratio", expanded)

    def test_expansion_is_deterministic_and_additive(self) -> None:
        from burnaby_prototype.bylaw_rag import expand_query_terms

        first = expand_query_terms("how big is the setback")
        self.assertEqual(first, expand_query_terms("how big is the setback"))
        # Original tokens always survive, in order, at the front.
        self.assertEqual(first[:5], ["how", "big", "is", "the", "setback"])


class CoverageAuditTests(unittest.TestCase):
    def test_measurement_regex_counts_values_not_references(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from audit_bylaw_coverage import MEASUREMENT_RE

        self.assertTrue(MEASUREMENT_RE.search("must not exceed 7.5 metres"))
        self.assertTrue(MEASUREMENT_RE.search("is 75.0 square metres"))
        self.assertTrue(MEASUREMENT_RE.search("maximum of 10.0 per cent"))
        # Bare section references and amendment codes are NOT measurements.
        self.assertFalse(MEASUREMENT_RE.search("see subsection (3.1) and 12P2019"))
        self.assertFalse(MEASUREMENT_RE.search("section 101.5.2 applies"))
