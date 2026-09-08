"""M4 source-corpus contract tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.source.corpus import build_m4_source_corpus, write_m4_source_corpus  # noqa: E402


SCRIPTS = ROOT / "scripts"


def _load_build_script():
    spec = importlib.util.spec_from_file_location("build_m4_source_corpus_test", SCRIPTS / "build_m4_source_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class M4SourceCorpusTests(unittest.TestCase):
    def test_source_corpus_does_not_read_gold_or_verifier_outputs(self) -> None:
        text = (ROOT / "src" / "burnaby_prototype" / "source" / "corpus.py").read_text(encoding="utf-8")
        self.assertNotIn("benchmark/gold", text)
        self.assertNotIn("verified_rules", text)
        self.assertNotIn("review_needed", text)

    def test_manifest_keeps_official_url_and_provenance_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4 test")
            corpus = build_m4_source_corpus(
                city="testville",
                pdf_path=pdf,
                config={
                    "zone": "R1",
                    "source_document": "official.pdf",
                    "source_url": "https://example.test/official.pdf",
                },
                provenance={"url": "file:///local/source.pdf", "sha256": "abc", "fetched_at": "2026-01-01"},
                chunks=[],
                page_count=7,
            )
        manifest = corpus["manifest"]
        self.assertEqual(manifest["configured_source_url"], "https://example.test/official.pdf")
        self.assertEqual(manifest["provenance_url"], "file:///local/source.pdf")
        self.assertEqual(manifest["page_count"], 7)
        self.assertIn("No benchmark gold", manifest["gold_leakage_guard"])

    def test_numeric_and_table_indexes_preserve_source_context(self) -> None:
        chunks = [
            {
                "chunk_id": "c1",
                "section": "101.1",
                "page": 1,
                "heading": "Height",
                "parent_text": "The maximum height is:",
                "text": "(a) 8.5 m for a laneway house.",
                "evidence_type": "clause",
                "metadata": {
                    "measurement_count": 1,
                    "rule_cue_count": 1,
                    "rule_types": ["dimensional_standard"],
                    "discovery_selected": True,
                    "selection_tier": "core",
                },
            },
            {
                "chunk_id": "t1",
                "section": "",
                "page": 2,
                "heading": "Siting table",
                "table_title": "Siting table",
                "row_header": "Rear yard",
                "text": "Siting table | Rear yard | Minimum: 1.5 m",
                "evidence_type": "table_row",
                "metadata": {
                    "measurement_count": 1,
                    "rule_cue_count": 1,
                    "cells": [{"column_header": "Minimum", "cell_value": "1.5 m"}],
                    "discovery_selected": False,
                },
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4 test")
            corpus = build_m4_source_corpus(
                city="testville",
                pdf_path=pdf,
                config={"zone": "R1"},
                chunks=chunks,
                page_count=2,
            )

        self.assertEqual(corpus["manifest"]["numeric_clause_count"], 2)
        self.assertEqual(corpus["manifest"]["table_entry_count"], 1)
        self.assertIn("Parent context: The maximum height is:", corpus["rag_index"]["chunks"][0]["text"])
        self.assertEqual(corpus["table_index"][0]["cells"][0]["column_header"], "Minimum")
        self.assertEqual(corpus["coverage_audit"]["selected_rule_like_numeric_clause_count"], 1)
        self.assertEqual(corpus["coverage_audit"]["selected_rule_like_numeric_coverage"], 0.5)

    def test_write_source_corpus_creates_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4 test")
            corpus = build_m4_source_corpus(
                city="testville",
                pdf_path=pdf,
                config={},
                chunks=[],
                page_count=1,
            )
            out = Path(tmp) / "corpus"
            write_m4_source_corpus(corpus, out)
            for name in (
                "manifest.json",
                "source_chunks.json",
                "rag_index.json",
                "table_index.json",
                "numeric_clause_index.json",
                "coverage_audit.json",
            ):
                self.assertTrue((out / name).exists(), name)

    def test_actual_evidence_packs_define_selected_coverage(self) -> None:
        chunks = [
            {
                "chunk_id": "rule",
                "section": "1",
                "page": 1,
                "text": "The maximum height is 8.5 m.",
                "evidence_type": "clause",
                "metadata": {
                    "measurement_count": 1,
                    "rule_cue_count": 1,
                    "discovery_selected": False,
                },
            }
        ]
        packs = [{"pack_id": "p1", "chunk_id": "rule", "lane": "family_query", "selection_tier": "core"}]
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4 test")
            corpus = build_m4_source_corpus(
                city="testville",
                pdf_path=pdf,
                config={},
                chunks=chunks,
                packs=packs,
                page_count=1,
            )
        row = corpus["numeric_clause_index"][0]
        self.assertTrue(row["selected_by_discovery"])
        self.assertEqual(row["selected_pack_id"], "p1")
        self.assertEqual(corpus["coverage_audit"]["selected_rule_like_numeric_coverage"], 1.0)

    def test_standalone_builder_prefers_m4_packs_over_v3_packs(self) -> None:
        module = _load_build_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "data" / "bylaws" / "testville" / "source.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF-1.4 test")
            pdf_hash = module.hash_file(pdf)
            for run_root, pack_id in (("v3_runs", "v3_pack"), ("m7_runs", "m7_pack")):
                out = root / "outputs" / run_root / "testville"
                out.mkdir(parents=True)
                (out / "source_summary.json").write_text(
                    f'{{"pdf_hash": "{pdf_hash}"}}',
                    encoding="utf-8",
                )
                (out / "evidence_packs.json").write_text(
                    f'[{{"pack_id": "{pack_id}", "chunk_id": "c1"}}]',
                    encoding="utf-8",
                )
            original_root = module.ROOT
            module.ROOT = root
            try:
                packs = module._load_existing_packs(city="testville", pdf_path=pdf)
            finally:
                module.ROOT = original_root

        self.assertEqual(packs[0]["pack_id"], "m7_pack")


if __name__ == "__main__":
    unittest.main()
