"""Tests for the legacy INTERNAL extraction helper.

Covers: deterministic text-stream clause/candidate extraction on dict fixtures,
section-anchor preservation, the registry round-trip through
``adapt_pipeline5_registry`` (candidate/evidence linkage), the table stream
with a FAKE Gemini client (schema-validated merge + response caching), keyless
graceful skip, the extraction import boundary in both directions, and
fetch_bylaw idempotence over a file:// URL (no network, no API key needed).
"""

from __future__ import annotations

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

from burnaby_prototype.extraction.registry_writer import (
    build_evidence_units,
    build_registry,
    write_registry_outputs,
)
from burnaby_prototype.extraction.table_stream import (
    derive_table_candidates,
    run_table_stream,
    validate_table_payload,
)
from burnaby_prototype.extraction.text_stream import run_text_stream
from burnaby_prototype.zihao_adapter import adapt_pipeline5_registry
from fetch_bylaw import fetch_bylaw
from run_extraction import _apply_page_offset, _best_contiguous_page_match


def _fixture_intermediate() -> dict:
    """Fabricated ingest intermediate: 2 sections, one max clause, one min clause."""
    return {
        "source_pdf": "fixture.pdf",
        "ingest_backend": "fixture",
        "pages": [
            {
                "page_number": 12,
                "text": "",
                "blocks": [
                    {"text": "BUILDING REGULATIONS", "kind": "heading"},
                    {
                        "text": "11.3.8.2 The height of a laneway home must not exceed 9.5 m",
                        "kind": "heading",
                    },
                    {"text": "measured from the average grade.", "kind": "paragraph"},
                    {
                        "text": "5.7(3)(a) An interior side yard setback shall be provided of at least 1.2 m for each principal building.",
                        "kind": "paragraph",
                    },
                ],
                "tables": [
                    {
                        "title_guess": "Maximum Height",
                        "rows": [["Use", "Height"], ["Laneway Home", "9.5 m"]],
                        "page": 12,
                    }
                ],
            },
            {
                "page_number": 13,
                "text": "",
                "blocks": [
                    {
                        "text": "The general intent of this district is described here without numbers.",
                        "kind": "paragraph",
                    },
                ],
                "tables": [],
            },
        ],
    }


_EXPECTED_TEXT_CANDIDATES = [
    {
        "clause_id": "testville_11.3.8.2_001",
        "section": "11.3.8.2",
        "page": 12,
        "rule_key": "max_height",
        "rule_object": "height",
        "constraint_type": "maximum",
        "subject": "building",
        "operator": "<=",
        "value": "9.5",
        "unit": "m",
        "condition": "",
        "exception": "",
        "evidence_text": "11.3.8.2 The height of a laneway home must not exceed 9.5 m measured from the average grade.",
        "source_stream": "local_text_block",
    },
    {
        "clause_id": "testville_5.7.3.a_002",
        "section": "5.7(3)(a)",
        "page": 12,
        "rule_key": "min_setback",
        "rule_object": "setback",
        "constraint_type": "minimum",
        "subject": "building",
        "operator": ">=",
        "value": "1.2",
        "unit": "m",
        "condition": "",
        "exception": "",
        "evidence_text": "5.7(3)(a) An interior side yard setback shall be provided of at least 1.2 m for each principal building.",
        "source_stream": "local_text_block",
    },
]


_FAKE_TABLE_RESPONSE = [
    {
        "table_title": "Maximum Height",
        "rows": [
            {
                "row_header": "Laneway Home",
                "column_header": "Maximum Height",
                "cell_value": "9.5 m",
                "notes": "",
            },
            # malformed row: cell_value is not a string -> must be dropped
            {"row_header": "Bad Row", "column_header": "Maximum Height", "cell_value": 9.5},
        ],
    },
    # malformed table: rows is not a list -> must be dropped
    {"table_title": "Broken", "rows": "not-a-list"},
]


class _FakeGeminiClient:
    """Injectable fake mirroring the embedding_semantics injectable-backend idea."""

    model = "fake-gemini-flash"
    available = True

    def __init__(self, response: list[dict]) -> None:
        self.calls = 0
        self._response = response

    def generate_table_json(self, *, prompt: str, image_png=None, table_text=None) -> list[dict]:
        self.calls += 1
        assert "JSON" in prompt
        return self._response


class RunExtractionProvenanceTests(unittest.TestCase):
    def test_contiguous_page_match_is_whitespace_normalized_and_1_based(self) -> None:
        match = _best_contiguous_page_match(
            ["  Page A\ntext  ", "Page B   text"],
            ["cover", "page a text", "page b text", "appendix"],
        )
        self.assertEqual(match, (2, 3))

    def test_apply_page_offset_updates_pages_and_table_pages(self) -> None:
        intermediate = {
            "pages": [
                {"page_number": 1, "tables": [{"page": 1}]},
                {"page_number": 2, "tables": [{"page": 2}]},
            ]
        }
        _apply_page_offset(intermediate, 392)
        self.assertEqual([page["page_number"] for page in intermediate["pages"]], [393, 394])
        self.assertEqual([page["tables"][0]["page"] for page in intermediate["pages"]], [393, 394])


class TextStreamTests(unittest.TestCase):
    def test_text_stream_exact_candidates_and_determinism(self) -> None:
        intermediate = _fixture_intermediate()
        first = run_text_stream(intermediate, "Testville")
        second = run_text_stream(json.loads(json.dumps(intermediate)), "Testville")
        self.assertEqual(first, second, "text stream must be deterministic")
        self.assertEqual(first["candidates"], _EXPECTED_TEXT_CANDIDATES)
        self.assertEqual(first["sections_seen"], ["11.3.8.2", "5.7(3)(a)"])

    def test_all_clauses_become_evidence_units_not_only_candidates(self) -> None:
        result = run_text_stream(_fixture_intermediate(), "Testville")
        # both numbered clauses are evidence; the un-numbered intent paragraph
        # has no section anchor so it cannot be cited by id
        ids = [clause["evidence_id"] for clause in result["clauses"]]
        self.assertEqual(ids, ["testville_11.3.8.2_001", "testville_5.7.3.a_002"])
        units = build_evidence_units("Testville", result, {})
        self.assertEqual([unit["evidence_id"] for unit in units], ids)
        self.assertTrue(all(unit["source_stream"] == "local_text_block" for unit in units))

    def test_section_anchor_and_page_preserved_on_candidates(self) -> None:
        result = run_text_stream(_fixture_intermediate(), "Testville")
        for candidate in result["candidates"]:
            self.assertIn(candidate["section"], {"11.3.8.2", "5.7(3)(a)"})
            self.assertEqual(candidate["page"], 12)
            self.assertIn(candidate["section"].split("(")[0], candidate["clause_id"])

    def test_plain_numbers_do_not_anchor_clauses(self) -> None:
        intermediate = {
            "pages": [
                {
                    "page_number": 1,
                    "blocks": [
                        {"text": "6 dwelling units are discussed in 2024 reports.", "kind": "paragraph"}
                    ],
                    "tables": [],
                }
            ]
        }
        result = run_text_stream(intermediate, "Testville")
        self.assertEqual(result["clauses"], [])
        self.assertEqual(result["candidates"], [])


class TableStreamTests(unittest.TestCase):
    def test_fake_client_schema_validated_merge_and_cache_writes(self) -> None:
        intermediate = _fixture_intermediate()
        fake = _FakeGeminiClient(_FAKE_TABLE_RESPONSE)
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            first = run_table_stream(
                intermediate,
                "Testville",
                client=fake,
                cache_dir=cache_dir,
                log=lambda message: None,
                sleep=sleeps.append,
            )
            self.assertTrue(first["available"])
            self.assertEqual(fake.calls, 1)
            self.assertEqual(first["uncached_calls"], 1)
            # schema-validated merge: malformed table and malformed row dropped
            self.assertEqual(len(first["tables"]), 1)
            table = first["tables"][0]
            self.assertEqual(table["table_title"], "Maximum Height")
            self.assertEqual(len(table["rows"]), 1)
            self.assertEqual(table["rows"][0]["cell_value"], "9.5 m")
            self.assertEqual(table["page"], 12)
            # caching mandatory: response JSON persisted under sha256 name
            cached = list(cache_dir.glob("*.json"))
            self.assertEqual(len(cached), 1)
            self.assertEqual(len(cached[0].stem), 64)
            payload = json.loads(cached[0].read_text(encoding="utf-8"))
            self.assertIn("request", payload)
            self.assertIn("response", payload)

            # second run: cache hit, NO new model call, same validated output
            second = run_table_stream(
                intermediate,
                "Testville",
                client=fake,
                cache_dir=cache_dir,
                log=lambda message: None,
                sleep=sleeps.append,
            )
            self.assertEqual(fake.calls, 1, "re-run must hit the cache, not quota")
            self.assertEqual(second["cached_hits"], 1)
            self.assertEqual(second["tables"][0]["rows"], first["tables"][0]["rows"])
        self.assertEqual(sleeps, [], "single uncached call must not rate-limit sleep")

    def test_keyless_graceful_skip(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop("GOOGLE_API_KEY", None)
            result = run_table_stream(
                _fixture_intermediate(), "Testville", log=lambda message: None
            )
        self.assertFalse(result["available"])
        self.assertIn("GOOGLE_API_KEY", result["reason"])
        self.assertEqual(result["tables"], [])
        self.assertEqual(result["uncached_calls"], 0)

    def test_validate_table_payload_rejects_non_list(self) -> None:
        self.assertEqual(validate_table_payload({"rows": []}), [])
        self.assertEqual(validate_table_payload(None), [])

    def test_table_candidates_carry_table_context(self) -> None:
        tables = validate_table_payload(_FAKE_TABLE_RESPONSE)
        tables[0].update({"page": 12, "table_index": 1, "from_cache": False})
        candidates = derive_table_candidates(tables, "Testville")
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["rule_object"], "height")
        self.assertEqual(candidate["operator"], "<=")
        self.assertEqual((candidate["value"], candidate["unit"]), ("9.5", "m"))
        self.assertEqual(candidate["row_header"], "Laneway Home")
        self.assertEqual(candidate["source_stream"], "local_table_image")
        self.assertEqual(
            candidate["evidence_text"], "Maximum Height | Laneway Home | Maximum Height: 9.5 m"
        )


class RegistryRoundTripTests(unittest.TestCase):
    def _registry(self, tmp: Path) -> dict:
        intermediate = _fixture_intermediate()
        text_result = run_text_stream(intermediate, "Testville")
        fake = _FakeGeminiClient(_FAKE_TABLE_RESPONSE)
        table_result = run_table_stream(
            intermediate,
            "Testville",
            client=fake,
            cache_dir=tmp / "cache",
            log=lambda message: None,
            sleep=lambda seconds: None,
        )
        outputs = write_registry_outputs(
            tmp / "out", "Testville", text_result, table_result, source_pdf="fixture.pdf"
        )
        return outputs

    def test_registry_files_and_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            outputs = self._registry(tmp)
            registry = json.loads(Path(outputs["registry_path"]).read_text(encoding="utf-8"))
            self.assertIn("rules", registry)
            self.assertEqual(registry["final_rule_count"], len(registry["rules"]))
            for rule in registry["rules"]:
                for field in (
                    "source_id",
                    "rule_key",
                    "rule_object",
                    "constraint_type",
                    "operator",
                    "value",
                    "unit",
                    "condition",
                    "evidence_text",
                    "source_stream",
                    "rule_id",
                    "merged_rule_id",
                    "applies_to",
                    "review_required",
                    "final_action",
                ):
                    self.assertIn(field, rule, f"missing Pipeline-5 contract field {field}")
                self.assertIn(rule["source_stream"], {"local_text_block", "local_table_image"})
                self.assertRegex(rule["source_id"], r"^page_\d{4}__(text|table)_\d{3}$")
            summary = json.loads(Path(outputs["summary_path"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["counts"]["rules_final"], registry["final_rule_count"])
            self.assertEqual(summary["sections_seen"], ["11.3.8.2", "5.7(3)(a)"])
            evidence_units = json.loads(
                Path(outputs["evidence_units_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(summary["counts"]["evidence_units"], len(evidence_units))
            # sidecar carries ALL clauses plus table rows, not only candidate-bearing
            self.assertIn("testville_11.3.8.2_001", [unit["evidence_id"] for unit in evidence_units])

    def test_round_trip_through_adapt_pipeline5_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            outputs = self._registry(tmp)
            registry = json.loads(Path(outputs["registry_path"]).read_text(encoding="utf-8"))
            adapted = adapt_pipeline5_registry(registry)
            candidates = adapted["rule_candidates"]
            evidence_units = adapted["evidence_units"]
            self.assertEqual(len(candidates), len(registry["rules"]))
            evidence_ids = {unit["evidence_id"] for unit in evidence_units}
            for candidate in candidates:
                self.assertTrue(candidate["candidate_id"])
                self.assertIn(
                    candidate["evidence_id"], evidence_ids, "candidate must link to evidence"
                )
            by_id = {unit["evidence_id"]: unit for unit in evidence_units}
            # the 9.5 m height claim survives adaptation with its evidence intact
            height = next(
                c
                for c in candidates
                if c["rule_object"] == "height" and c["source_stream"] == "local_text_block"
            )
            self.assertEqual(height["operator"], "<=")
            self.assertEqual(height["unit"], "m")
            self.assertEqual(height["constraint_type"], "maximum")
            self.assertIn("must not exceed 9.5 m", by_id[height["evidence_id"]]["evidence_text"])
            self.assertEqual(by_id[height["evidence_id"]]["page"], 12)
            # the 1.2 m setback claim too
            setback = next(c for c in candidates if c["rule_object"] == "setback")
            self.assertEqual((setback["operator"], setback["value"], setback["unit"]), (">=", "1.2", "m"))
            self.assertIn("at least 1.2 m", by_id[setback["evidence_id"]]["evidence_text"])
            # the table-stream claim also survives, linked to its own evidence
            table_candidate = next(
                c for c in candidates if c["source_stream"] == "local_table_image"
            )
            self.assertIn("Laneway Home", by_id[table_candidate["evidence_id"]]["evidence_text"])

    def test_dedupe_collapses_true_repeats_only(self) -> None:
        text_result = run_text_stream(_fixture_intermediate(), "Testville")
        doubled = {
            "clauses": text_result["clauses"],
            "candidates": text_result["candidates"] + text_result["candidates"],
            "sections_seen": text_result["sections_seen"],
        }
        registry = build_registry("Testville", doubled, None, source_pdf="fixture.pdf")
        self.assertEqual(registry["raw_rule_count"], 4)
        self.assertEqual(registry["final_rule_count"], 2)
        merged = registry["rules"][0]
        self.assertEqual(merged["merged_rule_count"], 2)
        self.assertEqual(len(merged["merged_rule_ids"]), 2)


class ImportBoundaryTests(unittest.TestCase):
    def test_extraction_verify_import_boundary_both_directions(self) -> None:
        # Mirrors test_advisory_verify_import_boundary_both_directions:
        # (1) no verify-path module may import the extraction package, so the
        #     diagnostic helper can never feed a verification decision path; and
        # (2) the extraction package may not import the verifier/decision
        #     policy, so it cannot re-run or shadow a decision.
        src_dir = ROOT / "src" / "burnaby_prototype"
        verify_path = (
            "verification",
            "decision_policy",
            "support_checks",
            "text_span_proof",
            "table_natural_logic",
            "consensus",
            "conflict_guard",
            "compliance",
            "normalization",
            "normalization_rules",
            "zihao_adapter",
            "slim_pipeline",
        )
        for module in verify_path:
            source = (src_dir / f"{module}.py").read_text(encoding="utf-8")
            for forbidden in ("from .extraction", "import extraction", "burnaby_prototype.extraction"):
                self.assertNotIn(forbidden, source, f"{module} imports the extraction helper")
        extraction_dir = src_dir / "extraction"
        for module_path in sorted(extraction_dir.glob("*.py")):
            source = module_path.read_text(encoding="utf-8")
            for forbidden in ("verification", "decision_policy"):
                for pattern in (
                    f"from .{forbidden}",
                    f"from ..{forbidden}",
                    f"import {forbidden}",
                    f"from burnaby_prototype.{forbidden}",
                    f"burnaby_prototype.{forbidden}",
                ):
                    self.assertNotIn(
                        pattern, source, f"extraction/{module_path.name} imports {forbidden}"
                    )

    def test_no_api_key_ever_written_to_cache_files(self) -> None:
        # Keys come ONLY from the environment; the request descriptors the
        # table stream persists to its cache must never carry a key field.
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            run_table_stream(
                _fixture_intermediate(),
                "Testville",
                client=_FakeGeminiClient(_FAKE_TABLE_RESPONSE),
                cache_dir=cache_dir,
                log=lambda message: None,
                sleep=lambda seconds: None,
            )
            for cached in cache_dir.glob("*.json"):
                text = cached.read_text(encoding="utf-8")
                self.assertNotIn("api_key", text)
                self.assertNotIn("GOOGLE_API_KEY", text)


class FetchBylawTests(unittest.TestCase):
    def test_fetch_idempotence_over_file_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            source = tmp / "upstream.pdf"
            source.write_bytes(b"%PDF-1.4\nfake bylaw body\n%%EOF\n")
            url = source.as_uri()

            first = fetch_bylaw("Testville", url, root=tmp)
            self.assertEqual(first["status"], "fetched")
            pdf_path = Path(first["pdf_path"])
            self.assertTrue(pdf_path.exists())
            self.assertEqual(pdf_path, tmp / "data" / "bylaws" / "testville" / "source.pdf")

            provenance = json.loads(
                (pdf_path.parent / "provenance.json").read_text(encoding="utf-8")
            )
            for field in ("url", "fetched_at", "sha256", "bytes", "pages"):
                self.assertIn(field, provenance)
            self.assertEqual(provenance["url"], url)
            self.assertEqual(provenance["bytes"], len(source.read_bytes()))
            self.assertEqual(provenance["sha256"], first["sha256"])

            # second fetch of identical content is a no-op
            second = fetch_bylaw("Testville", url, root=tmp)
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(second["sha256"], first["sha256"])

            # PDFs are ignored, provenance is committed
            gitignore = (tmp / "data" / "bylaws" / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("*.pdf", gitignore)

            # changed upstream content is fetched again
            source.write_bytes(b"%PDF-1.4\nrevised bylaw body\n%%EOF\n")
            third = fetch_bylaw("Testville", url, root=tmp)
            self.assertEqual(third["status"], "fetched")
            self.assertNotEqual(third["sha256"], first["sha256"])


if __name__ == "__main__":
    unittest.main()
