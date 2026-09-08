"""Dashboard v2 gates: multi-city loading, review UI, and 3D/SVG utility.

These tests pin the v2 dashboard surface without running Streamlit:
1. dashboard/streamlit_app.py stays parseable and importable with base deps.
2. load_output_data works for every city output dir discovered on disk.
3. City-dir discovery returns verifier outputs that contain verified_rules.json:
   P5/P9 city dirs plus native model-run dirs under outputs/m7_runs,
   outputs/v3_runs, and outputs/v2_runs.
4. scripts/build_envelope_3d.py emits a self-contained html viewer carrying the
   governing Burnaby rule ids and numeric values, and degrades by refusing to
   write anything when a city has no buildable_envelope.json.
5. The SVG plan-view utility is well-formed XML with setback values + rule ids,
   while the dashboard itself stays focused on verification review.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "dashboard" / "streamlit_app.py"
BUILDER_PATH = ROOT / "scripts" / "build_envelope_3d.py"
BURNABY_DIR = ROOT / "outputs" / "burnaby_r1_slim_pipeline5_registry"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DashboardImportTests(unittest.TestCase):
    def test_dashboard_source_parses(self) -> None:
        ast.parse(DASHBOARD_PATH.read_text(encoding="utf-8"))

    def test_dashboard_imports_with_base_deps(self) -> None:
        module = _load_module("dashboard_v2_smoke", DASHBOARD_PATH)
        for attribute in (
            "main",
            "load_output_data",
            "discover_city_output_dirs",
            "city_key_from_dir",
            "highlight_evidence",
        ):
            self.assertTrue(hasattr(module, attribute), attribute)

    def test_status_colors_are_strict(self) -> None:
        module = _load_module("dashboard_v2_colors", DASHBOARD_PATH)
        self.assertEqual(
            module.STATUS_COLORS,
            {"verified": "#1a7f37", "review": "#9a6700", "rejected": "#cf222e", "not_used": "#57606a"},
        )


class CityDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module("dashboard_v2_cities", DASHBOARD_PATH)

    def test_discovers_existing_city_dirs(self) -> None:
        dirs = self.module.discover_city_output_dirs()
        self.assertIn(BURNABY_DIR, dirs)
        for path in dirs:
            is_standard = path.name.endswith(self.module.REFERENCE_DIR_SUFFIXES)
            is_native = path.parent.parent.name in {"m7_runs", "v3_runs", "v2_runs"}
            is_m55 = path.parent.parent.name == "m7_measure"
            self.assertTrue(is_standard or is_native or is_m55, path)
            self.assertTrue((path / "verified_rules.json").exists(), path.name)

    def test_discovers_p9_runs_alongside_p5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs_root = Path(tmp)
            p5 = outputs_root / "vancouver_rs_slim_pipeline5_registry"
            p9 = outputs_root / "vancouver_rs_p9"
            for path in (p5, p9):
                path.mkdir()
                (path / "verified_rules.json").write_text("[]", encoding="utf-8")
            self.assertEqual(self.module.discover_city_output_dirs(outputs_root), [p9, p5])

    def test_city_stem_and_index_resolution(self) -> None:
        self.assertEqual(self.module.city_stem_from_dir(BURNABY_DIR), "burnaby_r1")
        self.assertEqual(self.module.city_stem_from_dir(Path("outputs/vancouver_rs_p9")), "vancouver_rs")
        self.assertEqual(
            self.module.city_label_from_dir(Path("outputs/vancouver_rs_p9")), "Vancouver RS — Pipeline 9"
        )
        # A P9 run borrows the sibling P5 registry's index (same bylaw corpus);
        # the old short-city_key path never matched a real directory.
        p9_dir = self.module.OUTPUTS_ROOT / "vancouver_rs_p9"
        if p9_dir.is_dir():
            resolved = self.module.bylaw_index_path(p9_dir)
            self.assertIsNotNone(resolved)
            self.assertTrue(str(resolved).endswith("vancouver_rs_slim_pipeline5_registry/bylaw_rag_index.json"))
        resolved_p5 = self.module.bylaw_index_path(BURNABY_DIR)
        self.assertIsNotNone(resolved_p5)
        self.assertEqual(resolved_p5, BURNABY_DIR / "bylaw_rag_index.json")

    def test_p9_provenance_summary_shapes(self) -> None:
        # P5 rules carry no provenance -> None (the lane stays hidden).
        self.assertIsNone(self.module.p9_provenance_summary({"candidate": {}}, {}))
        rule = {
            "candidate": {
                "evidence_id": "pack_007__page_0008__local_012",
                "p9_provenance": {
                    "rag_pack_id": "pack_007",
                    "rag_lane": "graph",
                    "rag_applicability": "laneway",
                    "pseudo_page": 8,
                    "original_page_number": 184,
                    "target_filter_action": "keep",
                    "block_id": "pack_007__page_0008__local_012",
                },
            }
        }
        evidence_by_id = {
            "pack_007__page_0008__local_012": {
                "evidence_id": "pack_007__page_0008__local_012",
                "evidence_text": "The building height for a laneway house must not exceed 8.5 m.",
                "source_context": "11.3.8.4 The building height for a laneway house must not exceed 8.5 m and 2 storeys.",
                "reanchored_to_source": True,
            }
        }
        lane = self.module.p9_provenance_summary(rule, evidence_by_id)
        self.assertEqual(lane["pack"], "pack_007")
        self.assertEqual(lane["original_page"], 184)
        self.assertTrue(lane["reanchored"])
        self.assertFalse(lane["mismatched"])
        self.assertIn("11.3.8.4", lane["source_window"])
        # A mismatched block keeps its warning and exposes no source window.
        evidence_by_id["pack_007__page_0008__local_012"] = {
            "evidence_text": "damaged text",
            "rag_context_mismatch": True,
        }
        lane = self.module.p9_provenance_summary(rule, evidence_by_id)
        self.assertTrue(lane["mismatched"])
        self.assertFalse(lane["reanchored"])
        self.assertEqual(lane["source_window"], "")

    def test_discovery_requires_verified_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs_root = Path(tmp)
            good = outputs_root / "calgary_rc_slim_pipeline5_registry"
            good.mkdir()
            (good / "verified_rules.json").write_text("[]", encoding="utf-8")
            (outputs_root / "calgary_empty_slim_pipeline5_registry").mkdir()
            (outputs_root / "not_a_registry").mkdir()
            self.assertEqual(self.module.discover_city_output_dirs(outputs_root), [good])

    def test_discovers_m55_run_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs_root = Path(tmp)
            m55 = outputs_root / "m7_measure" / "m55_demo" / "burnaby_r1"
            m55.mkdir(parents=True)
            (m55 / "verified_rules.json").write_text("[]", encoding="utf-8")

            self.assertEqual(self.module.discover_city_output_dirs(outputs_root), [m55])
            self.assertEqual(self.module.city_stem_from_dir(m55), "burnaby_r1")
            self.assertEqual(self.module.city_key_from_dir(m55), "burnaby")
            self.assertEqual(self.module.city_label_from_dir(m55), "M5.5 m55_demo — Burnaby R1")

    def test_discovery_handles_missing_root(self) -> None:
        self.assertEqual(self.module.discover_city_output_dirs(Path("/nonexistent/outputs")), [])

    def test_city_key_and_label(self) -> None:
        self.assertEqual(self.module.city_key_from_dir(BURNABY_DIR), "burnaby")
        self.assertEqual(
            self.module.city_key_from_dir(Path("outputs/vancouver_rs_slim_pipeline5_registry")), "vancouver"
        )
        self.assertEqual(self.module.city_label_from_dir(BURNABY_DIR), "Burnaby R1")
        native = Path("outputs/m7_runs/vancouver_rs/google_gemini_2_5_flash_lite")
        self.assertEqual(self.module.city_key_from_dir(native), "vancouver")
        self.assertEqual(self.module.city_stem_from_dir(native), "vancouver_rs")
        self.assertEqual(self.module.city_label_from_dir(native), "Current M7 — Vancouver RS")

    def test_product_output_dirs_keep_only_m4_and_v3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs_root = Path(tmp)
            paths = [
                outputs_root / "m7_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite",
                outputs_root / "v3_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite",
                outputs_root / "v2_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite",
                outputs_root / "burnaby_r1_slim_pipeline5_registry",
                outputs_root / "burnaby_r1_p9",
            ]
            for path in paths:
                path.mkdir(parents=True)
                (path / "verified_rules.json").write_text("[]", encoding="utf-8")
            rows = self.module.discover_product_output_dirs(outputs_root)
        self.assertEqual(
            [path.parent.parent.name for path in rows],
            ["m7_runs", "v3_runs"],
        )

    def test_load_output_data_for_each_city(self) -> None:
        dirs = self.module.discover_city_output_dirs()
        self.assertGreaterEqual(len(dirs), 1)
        for path in dirs:
            data = self.module.load_output_data(path)
            self.assertEqual(data["output_dir"], path)
            self.assertIsInstance(data["verified"], list)
            self.assertIsInstance(data["review"], list)
            # Review/dashboard additive keys must always exist (possibly empty).
            self.assertIn("source_repair", data)
            self.assertIn("review_assistant_packets", data)
            self.assertIn("coverage_report", data)
            self.assertIn("slot_audit", data)
            self.assertIn("rule_slot_ledger", data)
            self.assertIn("m55_reconciliation", data)


class PipelineComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module("dashboard_v2_pipeline_compare", DASHBOARD_PATH)

    def test_pipeline_gate_status_labels_are_honest(self) -> None:
        status = self.module.pipeline_gate_status(
            {"candidate_rule_count": 4, "verified_rule_count": 4, "review_rule_count": 0},
            {"quality_gates": {"passed": True}, "rule_metrics": {"false_verified_count": 0}},
        )
        self.assertEqual(status, "pass")
        status = self.module.pipeline_gate_status(
            {"candidate_rule_count": 4, "verified_rule_count": 1, "review_rule_count": 2},
            {"quality_gates": {"passed": False}, "rule_metrics": {"false_verified_count": 1}},
        )
        self.assertEqual(status, "unsafe / needs fix")
        status = self.module.pipeline_gate_status(
            {"candidate_rule_count": 4, "verified_rule_count": 0, "review_rule_count": 3},
            {"quality_gates": {"passed": False}, "rule_metrics": {"false_verified_count": 0}},
        )
        self.assertEqual(status, "fail-closed")
        status = self.module.pipeline_gate_status(
            {
                "candidate_rule_count": 10,
                "verified_rule_count": 1,
                "review_rule_count": 2,
                "rejected_rule_count": 1,
                "not_used_rule_count": 5,
            },
            {"quality_gates": {"passed": False}, "rule_metrics": {"false_verified_count": 0}},
        )
        self.assertEqual(status, "scope mismatch")

    def test_pipeline_comparison_rows_ignore_legacy_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs_root = Path(tmp)
            p5 = outputs_root / "burnaby_r1_slim_pipeline5_registry"
            p9 = outputs_root / "burnaby_r1_p9"
            p5.mkdir()
            p9.mkdir()
            (p5 / "slim_summary.json").write_text(
                json.dumps({"candidate_rule_count": 2, "evidence_unit_count": 2, "verified_rule_count": 2}),
                encoding="utf-8",
            )
            (p5 / "benchmark_report.json").write_text(
                json.dumps({"quality_gates": {"passed": True}, "rule_metrics": {"verified_precision": 1.0}}),
                encoding="utf-8",
            )
            (p9 / "slim_summary.json").write_text(
                json.dumps({"candidate_rule_count": 3, "evidence_unit_count": 3, "verified_rule_count": 0, "review_rule_count": 3}),
                encoding="utf-8",
            )
            (p9 / "benchmark_report.json").write_text(
                json.dumps({"quality_gates": {"passed": False}, "rule_metrics": {"false_verified_count": 0}}),
                encoding="utf-8",
            )
            previous_root = self.module.OUTPUTS_ROOT
            self.module.OUTPUTS_ROOT = outputs_root
            try:
                rows = self.module.pipeline_comparison_rows(p9)
            finally:
                self.module.OUTPUTS_ROOT = previous_root
        self.assertEqual(rows, [])

    def test_pipeline_comparison_rows_include_native_m4_first_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs_root = Path(tmp)
            m4 = outputs_root / "m7_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite"
            v3 = outputs_root / "v3_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite"
            p5 = outputs_root / "burnaby_r1_slim_pipeline5_registry"
            for path in (m4, v3, p5):
                path.mkdir(parents=True)
                (path / "slim_summary.json").write_text(
                    json.dumps({"candidate_rule_count": 2, "evidence_unit_count": 2, "verified_rule_count": 2}),
                    encoding="utf-8",
                )
                (path / "benchmark_report.json").write_text(
                    json.dumps({"quality_gates": {"passed": True}, "rule_metrics": {"verified_precision": 1.0}}),
                    encoding="utf-8",
                )
            previous_root = self.module.OUTPUTS_ROOT
            self.module.OUTPUTS_ROOT = outputs_root
            try:
                rows = self.module.pipeline_comparison_rows(m4)
            finally:
                self.module.OUTPUTS_ROOT = previous_root
        self.assertEqual(rows[0]["pipeline"], "Native M7")
        self.assertEqual(rows[1]["pipeline"], "Native V3")
        self.assertEqual(len(rows), 2)

    def test_assistant_prompt_is_advisory_only(self) -> None:
        packet = {
            "candidate_rule": {"rule_object": "height", "operator": "<=", "value": "8.5"},
            "support_gaps": ["operator_not_supported"],
            "source": {"original_evidence": "8.5 m", "repaired_context": "The maximum height is 8.5 m."},
            "suggested_next_action": "Find source support.",
        }
        prompt = self.module._assistant_prompt(packet, "Can this be approved?")
        self.assertIn("Advisory only", prompt)
        self.assertIn("Do not say this rule is approved or verified", prompt)
        self.assertIn("operator_not_supported", prompt)


class EnvelopeSvgTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module("build_envelope_svg", BUILDER_PATH)
        self.dashboard = _load_module("dashboard_v2_highlight", DASHBOARD_PATH)
        self.envelope = json.loads((BURNABY_DIR / "buildable_envelope.json").read_text(encoding="utf-8"))

    def test_svg_is_well_formed_and_annotated(self) -> None:
        svg = self.module.build_envelope_svg(self.envelope)
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        governing = self.module.envelope_governing_setbacks(self.envelope)
        self.assertIn("front_lot_line", governing)
        for entry in governing.values():
            self.assertIn(str(entry["rule_id"]), svg)
            self.assertIn(str(entry["value_numeric"]), svg)
        self.assertIn("not a real parcel", svg)

    def test_svg_handles_empty_envelope(self) -> None:
        svg = self.module.build_envelope_svg({})
        ET.fromstring(svg)
        self.assertIn("<svg", svg)

    def test_highlight_evidence_marks_substring(self) -> None:
        markup, hit = self.dashboard.highlight_evidence(
            "Setbacks  shall be a minimum of 4.0 m from the front lot line.",
            "minimum of 4.0 m from the front",
        )
        self.assertTrue(hit)
        self.assertIn("<mark class='evidence-hit'>", markup)
        markup, hit = self.dashboard.highlight_evidence("Completely unrelated section text here.", "minimum of 4.0 m")
        self.assertFalse(hit)
        self.assertNotIn("<mark", markup)


class Envelope3dBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = _load_module("build_envelope_3d_test", BUILDER_PATH)

    def test_builder_writes_html_with_rules_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "envelope_3d.html"
            written = self.builder.build(BURNABY_DIR, target)
            self.assertEqual(written, target)
            text = target.read_text(encoding="utf-8")
            # Governing Burnaby rules: front setback, max height, max storeys.
            for needle in (
                "burnaby_r1_048",
                "burnaby_r1_038",
                "burnaby_r1_040",
                "4.0",
                "10.0",
                "3.0",
                "OrbitControls",
                "three",
                "not a real parcel",
            ):
                self.assertIn(needle, text, needle)

    def test_builder_refuses_city_without_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                self.builder.build(Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_summary_uses_local_helpers(self) -> None:
        envelope = json.loads((BURNABY_DIR / "buildable_envelope.json").read_text(encoding="utf-8"))
        summary = self.builder.summarize_envelope(envelope)
        self.assertEqual(summary["insets"], {"front": 4.0, "rear": 3.0, "side": 3.0})
        self.assertEqual(summary["height"]["rule_id"], "burnaby_r1_038")
        self.assertEqual(summary["storeys"]["rule_id"], "burnaby_r1_040")


class BylawSectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module("dashboard_v2_bylaw", DASHBOARD_PATH)

    def test_extract_sections_from_common_shapes(self) -> None:
        extract = self.module.extract_bylaw_sections
        self.assertEqual(
            extract({"sections": [{"section": "6.4", "title": "Setbacks", "text": "Front yard 4.0 m."}]}),
            [{"title": "6.4 — Setbacks", "text": "Front yard 4.0 m."}],
        )
        prose = "A front yard setback of not less than 4.0 m shall be provided."
        self.assertEqual(extract({"6.4": prose}), [{"title": "6.4", "text": prose}])
        self.assertEqual(extract("plain body"), [{"title": "Extracted text", "text": "plain body"}])
        self.assertEqual(extract({"sections": []}), [])
        self.assertEqual(extract(None), [])

    def test_extract_rejects_metadata_payloads(self) -> None:
        # Loose {key: value} shapes only count as sections when prose-like, so
        # provenance metadata (urls, hashes) never renders as bylaw text.
        payload = {"url": "file:///some/long/path/to/source.pdf", "sha256": "ab" * 32, "fetched_at": "2026-06-10"}
        self.assertEqual(self.module.extract_bylaw_sections(payload), [])

    def test_standalone_rag_hits_expand_section_without_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "bylaw_rag_index.json"
            index.write_text(
                json.dumps(
                    {
                        "chunks": [
                            {
                                "chunk_id": "c1",
                                "section": "10.1",
                                "page": 7,
                                "text": "The maximum height of a backyard suite is 8.5 metres.",
                            },
                            {
                                "chunk_id": "c2",
                                "section": "10.1",
                                "page": 7,
                                "text": "The maximum number of storeys is 2.",
                            },
                            {
                                "chunk_id": "c3",
                                "section": "10.2",
                                "page": 8,
                                "text": "Parking spaces are regulated separately.",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            hits = self.module._standalone_rag_hits(index, "how tall can the backyard suite be?", top_k=2)
        self.assertEqual(hits[0]["section"], "10.1")
        self.assertIn("8.5 metres", hits[0]["section_text"])
        self.assertIn("2", hits[0]["section_text"])

    def test_grounded_prompt_and_retrieval_answer_are_advisory(self) -> None:
        hits = [{"section": "10.1", "text": "The maximum height is 8.5 metres."}]
        prompt = self.module._grounded_bylaw_prompt("what is the height?", hits)
        self.assertIn("Do not approve, verify, or reject rules", prompt)
        self.assertIn("[10.1]", prompt)
        answer = self.module._retrieval_only_bylaw_answer("what is the height?", hits)
        self.assertIn("no deployed LLM key", answer)
        self.assertIn("[10.1]", answer)

    def test_llm_chat_returns_none_without_secrets(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            status = self.module._bylaw_llm_status(None)
            self.assertFalse(status["available"])
            self.assertIsNone(self.module._optional_bylaw_llm_answer("prompt", None))


if __name__ == "__main__":
    unittest.main()
