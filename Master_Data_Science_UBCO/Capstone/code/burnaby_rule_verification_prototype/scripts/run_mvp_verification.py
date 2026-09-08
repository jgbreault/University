#!/usr/bin/env python3
"""Build a one-file MVP verification report.

The MVP claim is intentionally narrow and auditable:

    - extractors and RAG propose candidates;
- source repair may restore source context;
- the deterministic verifier decides;
- failed benchmark gates are labelled honestly;
- any false verified rule is unsafe.

The current product path is native extraction/RAG/LLM output plus the
    deterministic verifier. M4 is promoted over V3 only when file-backed
    promotion gates pass. Pipeline 5 is legacy/reference only and must not be
    used as the headline current lane.

By default this script reads existing native V2/V3/M4 artifacts. Use
--refresh-benchmarks to fill missing benchmark_report.json files for native
runs, and --refresh-discovery to rebuild dry V2 source/evidence packs without
calling an LLM.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
PDF_CITIES = ("burnaby_r1", "vancouver_rs", "calgary_rcg")


@dataclass(frozen=True)
class ReportRun:
    label: str
    city: str
    output_dir: Path
    lane: str


V2_PRODUCT_RUNS = [
    ReportRun(
        label="Burnaby native V2 full-bylaw extraction",
        city="burnaby_r1",
        output_dir=OUTPUTS / "v2_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite",
        lane="native_v2",
    ),
    ReportRun(
        label="Vancouver native V2 full-bylaw extraction",
        city="vancouver_rs",
        output_dir=OUTPUTS / "v2_runs" / "vancouver_rs" / "google_gemini_2_5_flash_lite",
        lane="native_v2",
    ),
    ReportRun(
        label="Calgary native V2 full-bylaw extraction",
        city="calgary_rcg",
        output_dir=OUTPUTS / "v2_runs" / "calgary_rcg" / "google_gemini_2_5_flash_lite",
        lane="native_v2",
    ),
]

V3_PRODUCT_RUNS = [
    ReportRun(
        label="Burnaby native V3 full-bylaw extraction",
        city="burnaby_r1",
        output_dir=OUTPUTS / "v3_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite",
        lane="native_v3",
    ),
    ReportRun(
        label="Vancouver native V3 full-bylaw extraction",
        city="vancouver_rs",
        output_dir=OUTPUTS / "v3_runs" / "vancouver_rs" / "google_gemini_2_5_flash_lite",
        lane="native_v3",
    ),
    ReportRun(
        label="Calgary native V3 full-bylaw extraction",
        city="calgary_rcg",
        output_dir=OUTPUTS / "v3_runs" / "calgary_rcg" / "google_gemini_2_5_flash_lite",
        lane="native_v3",
    ),
]

M4_PRODUCT_RUNS = [
    ReportRun(
        label="Burnaby native M4 exhaustive full-bylaw extraction",
        city="burnaby_r1",
        output_dir=OUTPUTS / "m7_runs" / "burnaby_r1" / "google_gemini_2_5_flash_lite",
        lane="native_m4",
    ),
    ReportRun(
        label="Vancouver native M4 exhaustive full-bylaw extraction",
        city="vancouver_rs",
        output_dir=OUTPUTS / "m7_runs" / "vancouver_rs" / "google_gemini_2_5_flash_lite",
        lane="native_m4",
    ),
    ReportRun(
        label="Calgary native M4 exhaustive full-bylaw extraction",
        city="calgary_rcg",
        output_dir=OUTPUTS / "m7_runs" / "calgary_rcg" / "google_gemini_2_5_flash_lite",
        lane="native_m4",
    ),
]

# Preferred current native lane. build_report still falls back to V3/V2 if M4
# artifacts are missing or fail promotion gates.
CURRENT_PRODUCT_RUNS = M4_PRODUCT_RUNS


LEGACY_REFERENCE_RUNS = [
    ReportRun(
        label="Burnaby P5 registry legacy reference",
        city="burnaby_r1",
        output_dir=OUTPUTS / "burnaby_r1_slim_pipeline5_registry_v21",
        lane="legacy_p5",
    ),
    ReportRun(
        label="Vancouver P5 registry legacy reference",
        city="vancouver_rs",
        output_dir=OUTPUTS / "vancouver_rs_slim_pipeline5_registry",
        lane="legacy_p5",
    ),
    ReportRun(
        label="Calgary internal registry legacy reference",
        city="calgary_rcg",
        output_dir=OUTPUTS / "calgary_rcg_slim_pipeline5_registry_v21",
        lane="legacy_internal_registry",
    ),
    ReportRun(
        label="Burnaby P9 graph-RAG upstream reference",
        city="burnaby_r1",
        output_dir=OUTPUTS / "burnaby_r1_p9_v21",
        lane="upstream_p9",
    ),
    ReportRun(
        label="Vancouver P9 graph-RAG upstream reference",
        city="vancouver_rs",
        output_dir=OUTPUTS / "vancouver_rs_p9_v21",
        lane="upstream_p9",
    ),
    ReportRun(
        label="Calgary P9 graph-RAG upstream reference",
        city="calgary_rcg",
        output_dir=OUTPUTS / "calgary_rcg_p9_v21",
        lane="upstream_p9",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-benchmarks",
        action="store_true",
        help="Run benchmark/evaluate_benchmark.py for native V2/V3/M4 outputs with missing benchmark_report.json.",
    )
    parser.add_argument(
        "--refresh-discovery",
        action="store_true",
        help="Rebuild dry V2 discovery packs for Burnaby, Vancouver, and Calgary.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(OUTPUTS / "mvp_verification"),
        help="Directory for mvp_report.json and mvp_report.md.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    commands: list[dict[str, Any]] = []

    if args.refresh_benchmarks:
        for run in [*V2_PRODUCT_RUNS, *V3_PRODUCT_RUNS, *M4_PRODUCT_RUNS]:
            if run.output_dir.exists() and not (run.output_dir / "benchmark_report.json").exists():
                commands.append(run_benchmark(run.city, run.output_dir))

    if args.refresh_discovery:
        for city in PDF_CITIES:
            commands.append(
                run_command(
                    [
                        sys.executable,
                        "scripts/run_v2_bakeoff.py",
                        "--city",
                        city,
                        "--dry-run",
                        "--no-verify",
                        "--no-examiner",
                        "--max-packs",
                        "80" if city != "calgary_rcg" else "400",
                        "--refresh-packs",
                    ]
                )
            )

    report = build_report(commands)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "mvp_report.json", report)
    (out_dir / "mvp_report.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"MVP report written: {out_dir / 'mvp_report.md'}")
    print(f"Overall status: {report['overall_status']}")
    return 0 if report["unsafe_current_rows"] == [] else 1


def run_benchmark(city: str, output_dir: Path) -> dict[str, Any]:
    return run_command(
        [
            sys.executable,
            "benchmark/evaluate_benchmark.py",
            "--city",
            city,
            "--output-dir",
            str(output_dir),
        ]
    )


def run_command(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    record = {
        "command": command,
        "display_command": display_command(command),
        "returncode": result.returncode,
        "stdout_tail": tail(result.stdout),
        "stderr_tail": tail(result.stderr),
    }
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(command)
            + "\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )
    return record


def build_report(commands: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    v2_rows = [run_row(run) for run in V2_PRODUCT_RUNS]
    v3_rows = [run_row(run) for run in V3_PRODUCT_RUNS]
    m4_rows = [run_row(run) for run in M4_PRODUCT_RUNS]
    adversarial = read_json(OUTPUTS / "adversarial_report.json", {})
    v3_promotion = v3_promotion_status(v3_rows, v2_rows, adversarial)
    m4_promotion = m4_promotion_status(m4_rows, v3_rows, adversarial)
    if m4_promotion["promoted"]:
        current_rows = m4_rows
        current_path_version = "native_m4"
    elif v3_promotion["promoted"]:
        current_rows = v3_rows
        current_path_version = "native_v3"
    else:
        current_rows = v2_rows
        current_path_version = "native_v2"
    legacy_rows = [run_row(run) for run in LEGACY_REFERENCE_RUNS]
    unsafe = [
        row["label"]
        for row in current_rows
        if not row.get("missing") and row.get("status_label") == "unsafe / needs fix"
    ]
    false_verified_total = sum(int(row.get("false_verified_count") or 0) for row in current_rows if not row.get("missing"))
    report = {
        "report": "mvp_verification_report",
        "purpose": "MVP comparison for the active Burnaby_prototype verification branch.",
        "safety_contract": "Extractors and RAG propose; deterministic verifier decides; GIS uses only verified rules.",
        "overall_status": overall_status_for_rows(current_rows),
        "current_false_verified_total": false_verified_total,
        "unsafe_current_rows": unsafe,
        "current_path_version": current_path_version,
        "pdf_inventory": pdf_inventory(),
        "current_runs": current_rows,
        "v2_reference_runs": v2_rows,
        "v3_experimental_runs": v3_rows,
        "m4_experimental_runs": m4_rows,
        "v3_promotion": v3_promotion,
        "m4_promotion": m4_promotion,
        "legacy_references": legacy_rows,
        "v2_discovery": discovery_inventory(),
        "m4_discovery": m4_discovery_inventory(),
        "v2_model_runs": v2_model_inventory(),
        "v3_model_runs": native_model_inventory("v3_runs"),
        "m4_model_runs": native_model_inventory("m7_runs"),
        "commands_executed": commands or [],
        "interpretation": interpretation(current_rows, v3_promotion, m4_promotion, current_path_version),
    }
    return report


def run_row(run: ReportRun) -> dict[str, Any]:
    return row_from_output(run.label, run.city, run.output_dir, run.lane)


def row_from_output(label: str, city: str, output_dir: Path, lane: str) -> dict[str, Any]:
    if not output_dir.exists():
        return {"label": label, "city": city, "lane": lane, "output_dir": str(output_dir), "missing": True}
    summary = read_json(output_dir / "slim_summary.json", {})
    extraction_summary = read_json(output_dir / "extraction_summary.json", {})
    source_summary = read_json(output_dir / "source_summary.json", {})
    m4_source = source_summary.get("m4_source_corpus") or {}
    benchmark = read_json(output_dir / "benchmark_report.json", {})
    metrics = benchmark.get("rule_metrics", {})
    proposal = benchmark.get("proposal_metrics", {})
    gates = benchmark.get("quality_gates", {})
    row = {
        "label": label,
        "city": city,
        "lane": lane,
        "output_dir": str(output_dir),
        "missing": False,
        "pipeline": extraction_summary.get("pipeline"),
        "discovery_mode": extraction_summary.get("discovery_mode") or source_summary.get("discovery_mode"),
        "candidate_rule_count": pick(metrics, summary, "candidate_rule_count"),
        "evidence_unit_count": summary.get("evidence_unit_count"),
        "verified_rule_count": pick(metrics, summary, "verified_rule_count"),
        "review_rule_count": pick(metrics, summary, "review_rule_count"),
        "rejected_rule_count": pick(metrics, summary, "rejected_rule_count"),
        "not_used_rule_count": pick(metrics, summary, "not_used_rule_count"),
        "candidate_recall": metrics.get("candidate_recall"),
        "raw_candidate_artifact_recall": metrics.get("raw_candidate_artifact_recall", metrics.get("candidate_recall")),
        "release_candidate_recall": metrics.get(
            "release_candidate_recall",
            metrics.get("extraction_coverage_recall"),
        ),
        "verified_precision": metrics.get("verified_precision"),
        "false_verified_count": metrics.get("false_verified_count"),
        "verified_source_support_failed_count": metrics.get("verified_source_support_failed_count"),
        "false_approval_count": proposal.get("false_approval_count"),
        "verified_or_review_recall": metrics.get("verified_or_review_recall"),
        "extraction_coverage_recall": metrics.get("extraction_coverage_recall"),
        "verifier_retention_rate": metrics.get("verifier_retention_rate"),
        "quality_gate_passed": gates.get("passed"),
        "quality_gates": gates.get("gates", {}),
        "false_verified_rule_ids": metrics.get("false_verified_rule_ids", []),
        "missed_verified_or_review_gold_rule_ids": metrics.get("missed_verified_or_review_gold_rule_ids", []),
        "m4_numeric_clause_count": m4_source.get("numeric_clause_count"),
        "m4_rule_like_numeric_clause_count": m4_source.get("rule_like_numeric_clause_count"),
        "m4_selected_rule_like_numeric_coverage": m4_source.get("selected_rule_like_numeric_coverage"),
        "not_used_summary": not_used_summary(output_dir),
    }
    row["status_label"] = status_label(row)
    return row


def not_used_summary(output_dir: Path) -> dict[str, Any]:
    rules = read_json(output_dir / "not_used.json", [])
    if not isinstance(rules, list) or not rules:
        return {"count": 0, "top_reasons": [], "top_rule_families": [], "plain_explanation": ""}
    reason_counts = Counter(
        str(gap)
        for rule in rules
        for gap in (rule.get("support_gaps") or [])
    )
    family_counts = Counter(str(rule.get("rule_object") or "unknown") for rule in rules)
    return {
        "count": len(rules),
        "top_reasons": [
            {"reason": reason, "label": plain_label(reason), "count": count}
            for reason, count in reason_counts.most_common(6)
        ],
        "top_rule_families": [
            {"rule_family": plain_label(family), "count": count}
            for family, count in family_counts.most_common(6)
        ],
        "plain_explanation": not_used_plain_explanation(reason_counts),
    }


def not_used_plain_explanation(reason_counts: Counter[str]) -> str:
    if reason_counts.get("outside_target_section"):
        return (
            "These are real numeric candidates from the full bylaw, but they are outside "
            "the configured target sections for this product run. They are kept for audit "
            "and review, not exported as verified rules."
        )
    if reason_counts.get("outside_current_rule_contract"):
        return "These candidates are outside the current numeric zoning-rule contract."
    if reason_counts.get("definition_not_rule"):
        return "These candidates came from definitions or navigation text, not enforceable numeric rules."
    if reason_counts.get("cross_reference_only"):
        return "These candidates are cross-references or section pointers, not rules to verify."
    return "These candidates were retained for traceability but are outside the verified-rule output contract."


def plain_label(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().capitalize()


def pick(metrics: dict[str, Any], summary: dict[str, Any], key: str) -> Any:
    return metrics.get(key) if key in metrics else summary.get(key)


def v3_promotion_status(
    v3_rows: list[dict[str, Any]],
    v2_rows: list[dict[str, Any]],
    adversarial: dict[str, Any],
) -> dict[str, Any]:
    v2_by_city = {row.get("city"): row for row in v2_rows if not row.get("missing")}
    v3_visible = [row for row in v3_rows if not row.get("missing")]
    missing_cities = [row.get("city") for row in v3_rows if row.get("missing")]
    safety_ok = len(v3_visible) == len(PDF_CITIES) and all(
        int(row.get("false_verified_count") or 0) == 0
        and int(row.get("verified_source_support_failed_count") or 0) == 0
        for row in v3_visible
    )
    adversarial_ok = adversarial.get("all_blocked") is True
    improved_cities = []
    details = []
    for row in v3_visible:
        city = row.get("city")
        previous = v2_by_city.get(city, {})
        current_recall = row.get("verified_or_review_recall")
        previous_recall = previous.get("verified_or_review_recall")
        current_verified = row.get("verified_rule_count")
        previous_verified = previous.get("verified_rule_count")
        recall_improved = isinstance(current_recall, (int, float)) and isinstance(previous_recall, (int, float)) and current_recall > previous_recall
        verified_improved_without_recall_loss = (
            isinstance(current_verified, (int, float))
            and isinstance(previous_verified, (int, float))
            and isinstance(current_recall, (int, float))
            and isinstance(previous_recall, (int, float))
            and current_verified > previous_verified
            and current_recall >= previous_recall
        )
        improved = recall_improved or verified_improved_without_recall_loss
        if improved:
            improved_cities.append(city)
        details.append(
            {
                "city": city,
                "v2_verified": previous_verified,
                "v3_verified": current_verified,
                "v2_verified_or_review_recall": previous_recall,
                "v3_verified_or_review_recall": current_recall,
                "improved": improved,
            }
        )
    improvement_ok = len(set(improved_cities)) >= 2
    promoted = safety_ok and adversarial_ok and improvement_ok and not missing_cities
    reasons = []
    if missing_cities:
        reasons.append(f"missing_v3_outputs:{','.join(str(city) for city in missing_cities)}")
    if not safety_ok:
        reasons.append("v3_safety_gate_failed")
    if not adversarial_ok:
        reasons.append("adversarial_report_missing_or_failed")
    if not improvement_ok:
        reasons.append("v3_improvement_gate_failed")
    return {
        "promoted": promoted,
        "safety_ok": safety_ok,
        "adversarial_ok": adversarial_ok,
        "improvement_ok": improvement_ok,
        "improved_city_count": len(set(improved_cities)),
        "improved_cities": sorted(set(str(city) for city in improved_cities)),
        "missing_cities": missing_cities,
        "reasons": reasons,
        "details": details,
    }


def m4_promotion_status(
    m4_rows: list[dict[str, Any]],
    v3_rows: list[dict[str, Any]],
    adversarial: dict[str, Any],
) -> dict[str, Any]:
    """Promotion gate for M4 exhaustive native extraction.

    M4's extra value is exhaustive source discovery. It does not need to verify
    more than V3 in every city, but it must not lose verified-or-review recall,
    and every city must have full rule-like numeric source coverage.
    """
    reference_by_city = {row.get("city"): row for row in v3_rows if not row.get("missing")}
    m4_visible = [row for row in m4_rows if not row.get("missing")]
    missing_cities = [row.get("city") for row in m4_rows if row.get("missing")]
    safety_ok = len(m4_visible) == len(PDF_CITIES) and all(
        int(row.get("false_verified_count") or 0) == 0
        and int(row.get("verified_source_support_failed_count") or 0) == 0
        and int(row.get("false_approval_count") or 0) == 0
        for row in m4_visible
    )
    adversarial_ok = adversarial.get("all_blocked") is True
    source_coverage_ok = len(m4_visible) == len(PDF_CITIES) and all(
        isinstance(row.get("m4_selected_rule_like_numeric_coverage"), (int, float))
        and row.get("m4_selected_rule_like_numeric_coverage") >= 0.999
        for row in m4_visible
    )
    no_recall_loss = True
    improved_cities = []
    details = []
    for row in m4_visible:
        city = row.get("city")
        previous = reference_by_city.get(city, {})
        current_recall = row.get("verified_or_review_recall")
        previous_recall = previous.get("verified_or_review_recall")
        current_verified = row.get("verified_rule_count")
        previous_verified = previous.get("verified_rule_count")
        recall_loss = (
            isinstance(current_recall, (int, float))
            and isinstance(previous_recall, (int, float))
            and current_recall < previous_recall
        )
        if recall_loss:
            no_recall_loss = False
        improved = (
            isinstance(current_verified, (int, float))
            and isinstance(previous_verified, (int, float))
            and current_verified > previous_verified
        )
        if improved:
            improved_cities.append(city)
        details.append(
            {
                "city": city,
                "v3_verified": previous_verified,
                "m4_verified": current_verified,
                "v3_verified_or_review_recall": previous_recall,
                "m4_verified_or_review_recall": current_recall,
                "m4_selected_rule_like_numeric_coverage": row.get("m4_selected_rule_like_numeric_coverage"),
                "recall_loss": recall_loss,
                "verified_improved": improved,
            }
        )
    promoted = safety_ok and adversarial_ok and source_coverage_ok and no_recall_loss and not missing_cities
    reasons = []
    if missing_cities:
        reasons.append(f"missing_m4_outputs:{','.join(str(city) for city in missing_cities)}")
    if not safety_ok:
        reasons.append("m4_safety_gate_failed")
    if not adversarial_ok:
        reasons.append("adversarial_report_missing_or_failed")
    if not source_coverage_ok:
        reasons.append("m4_source_coverage_gate_failed")
    if not no_recall_loss:
        reasons.append("m4_recall_loss_against_v3")
    return {
        "promoted": promoted,
        "safety_ok": safety_ok,
        "adversarial_ok": adversarial_ok,
        "source_coverage_ok": source_coverage_ok,
        "no_recall_loss": no_recall_loss,
        "improved_city_count": len(set(improved_cities)),
        "improved_cities": sorted(set(str(city) for city in improved_cities)),
        "missing_cities": missing_cities,
        "reasons": reasons,
        "details": details,
    }


def overall_status_for_rows(rows: list[dict[str, Any]]) -> str:
    visible = [row for row in rows if not row.get("missing")]
    if any(row.get("status_label") == "unsafe / needs fix" for row in visible):
        return "unsafe_needs_fix"
    if any(row.get("status_label") in {"scope mismatch", "fail-closed"} for row in visible):
        return "safety_mvp_extraction_gap"
    if visible:
        return "mvp_safety_ready"
    return "missing_outputs"


def status_label(row: dict[str, Any]) -> str:
    if row.get("missing"):
        return "missing"
    if int(row.get("false_verified_count") or 0) > 0:
        return "unsafe / needs fix"
    if int(row.get("verified_source_support_failed_count") or 0) > 0:
        return "unsafe / needs fix"
    if int(row.get("false_approval_count") or 0) > 0:
        return "unsafe / needs fix"
    if row.get("quality_gate_passed") is True:
        return "pass"
    verified_or_review_recall = row.get("verified_or_review_recall")
    extraction_coverage_recall = row.get("extraction_coverage_recall")
    verification_coverage_ok = (
        isinstance(verified_or_review_recall, (int, float))
        and verified_or_review_recall >= 0.9
        and (
            not isinstance(extraction_coverage_recall, (int, float))
            or extraction_coverage_recall >= 0.9
        )
    )
    if verification_coverage_ok:
        return "needs review"
    release_candidate_recall = row.get("release_candidate_recall")
    if isinstance(release_candidate_recall, (int, float)):
        if release_candidate_recall < 0.95:
            return "scope mismatch"
    else:
        candidate_recall = row.get("raw_candidate_artifact_recall", row.get("candidate_recall"))
        if isinstance(candidate_recall, (int, float)) and candidate_recall < 0.9:
            return "scope mismatch"
    verified = int(row.get("verified_rule_count") or 0)
    review = int(row.get("review_rule_count") or 0)
    if verified == 0 and review > 0:
        return "fail-closed"
    return "needs review"


def pdf_inventory() -> list[dict[str, Any]]:
    rows = []
    for city in PDF_CITIES:
        pdf = ROOT / "data" / "bylaws" / city / "source.pdf"
        if not pdf.exists():
            rows.append({"city": city, "source_pdf": str(pdf), "missing": True})
            continue
        rows.append(
            {
                "city": city,
                "source_pdf": str(pdf),
                "page_count": len(PdfReader(str(pdf)).pages),
                "missing": False,
            }
        )
    return rows


def discovery_inventory() -> list[dict[str, Any]]:
    rows = []
    for city in PDF_CITIES:
        candidates = [
            OUTPUTS / "v2_runs_full_discovery" / city / "source_summary.json",
            OUTPUTS / "v2_runs" / city / "source_summary.json",
        ]
        summary_path = next((path for path in candidates if path.exists()), None)
        if summary_path is None:
            rows.append({"city": city, "missing": True})
            continue
        summary = read_json(summary_path, {})
        rows.append(
            {
                "city": city,
                "missing": False,
                "source": str(summary_path.parent),
                "source_chunk_count": summary.get("source_chunk_count"),
                "evidence_pack_count": summary.get("evidence_pack_count"),
                "page_count_with_chunks": summary.get("page_count"),
                "first_page": summary.get("first_page"),
                "last_page": summary.get("last_page"),
                "discovery_version": summary.get("discovery_version"),
                "advisory_only": summary.get("advisory_only"),
                "lane_counts": summary.get("lane_counts", []),
            }
        )
    return rows


def m4_discovery_inventory() -> list[dict[str, Any]]:
    rows = []
    for city in PDF_CITIES:
        summary_path = OUTPUTS / "m7_runs" / city / "source_summary.json"
        if not summary_path.exists():
            rows.append({"city": city, "missing": True})
            continue
        summary = read_json(summary_path, {})
        m4_source = summary.get("m4_source_corpus") or {}
        manifest = read_json(Path(m4_source.get("path") or "") / "manifest.json", {})
        rows.append(
            {
                "city": city,
                "missing": False,
                "source": str(summary_path.parent),
                "full_pdf_page_count": manifest.get("page_count"),
                "source_chunk_count": summary.get("source_chunk_count"),
                "evidence_pack_count": summary.get("evidence_pack_count"),
                "page_count_with_chunks": summary.get("page_count"),
                "first_page": summary.get("first_page"),
                "last_page": summary.get("last_page"),
                "discovery_version": summary.get("discovery_version"),
                "discovery_mode": summary.get("discovery_mode"),
                "advisory_only": summary.get("advisory_only"),
                "numeric_clause_count": m4_source.get("numeric_clause_count"),
                "rule_like_numeric_clause_count": m4_source.get("rule_like_numeric_clause_count"),
                "selected_rule_like_numeric_coverage": m4_source.get("selected_rule_like_numeric_coverage"),
                "lane_counts": summary.get("lane_counts", []),
            }
        )
    return rows


def v2_model_inventory() -> list[dict[str, Any]]:
    return native_model_inventory("v2_runs")


def native_model_inventory(run_root_name: str) -> list[dict[str, Any]]:
    rows = []
    for summary_path in sorted((OUTPUTS / run_root_name).glob("*/*/extraction_summary.json")):
        output_dir = summary_path.parent
        summary = read_json(summary_path, {})
        slim = read_json(output_dir / "slim_summary.json", {})
        benchmark = read_json(output_dir / "benchmark_report.json", {})
        metrics = benchmark.get("rule_metrics", {})
        cost = read_json(output_dir / "model_cost_report.json", {})
        rows.append(
            {
                "city": output_dir.parent.name,
                "model": summary.get("model") or "dry_run",
                "run_root": run_root_name,
                "output_dir": str(output_dir),
                "packs": summary.get("retrieval_pack_count"),
                "candidates": summary.get("candidate_rule_count"),
                "verified": slim.get("verified_rule_count"),
                "review": slim.get("review_rule_count"),
                "rejected": slim.get("rejected_rule_count"),
                "false_verified": metrics.get("false_verified_count"),
                "verified_or_review_recall": metrics.get("verified_or_review_recall"),
                "estimated_cost_usd": cost.get("estimated_cost_usd"),
            }
        )
    return rows


def interpretation(
    rows: list[dict[str, Any]],
    v3_promotion: dict[str, Any],
    m4_promotion: dict[str, Any],
    current_path_version: str,
) -> list[str]:
    notes = []
    visible = [row for row in rows if not row.get("missing")]
    if visible and all(int(row.get("false_verified_count") or 0) == 0 for row in visible):
        notes.append("Current MVP outputs satisfy the safety target: false_verified_count is 0 wherever benchmarks are present.")
    unsafe = [row for row in visible if row.get("status_label") == "unsafe / needs fix"]
    if unsafe:
        notes.append("At least one current lane is unsafe because a false verified rule, source support failure, or false approval was found.")
    scope_gaps = [row for row in visible if row.get("status_label") == "scope mismatch"]
    if scope_gaps:
        notes.append("Native extraction remains an extraction-coverage gap in at least one city: the verifier is safe, but recall is not complete.")
    elif visible and all(
        isinstance(row.get("verified_or_review_recall"), (int, float))
        and row.get("verified_or_review_recall") >= 0.9
        for row in visible
    ):
        notes.append(f"{current_path_version.upper()} covers the benchmarked gold rules through verified or review dispositions in every current city.")
    review_rows = [row for row in visible if row.get("status_label") == "needs review"]
    if review_rows:
        notes.append("At least one current lane still has non-safety benchmark gates needing review, such as proposal-case field expectations.")
    out_of_scope_rows = [
        row for row in visible if int((row.get("not_used_summary") or {}).get("count") or 0) > 0
    ]
    if out_of_scope_rows:
        cities = ", ".join(str(row.get("city")) for row in out_of_scope_rows)
        notes.append(f"{current_path_version.upper()} keeps out-of-contract full-bylaw candidates in not_used for audit in: {cities}. They are not verified outputs.")
    if current_path_version == "native_m4" and m4_promotion.get("promoted"):
        notes.append("M4 passed promotion gates and is the current product path.")
    elif v3_promotion.get("promoted"):
        notes.append("V3 passed promotion gates and is the current product path.")
    else:
        reasons = ", ".join(m4_promotion.get("reasons") or v3_promotion.get("reasons") or [])
        notes.append(f"The newest native lane is experimental until promotion gates pass. Current blockers: {reasons or 'none reported'}.")
    notes.append("Pipeline 5 and Pipeline 9 rows are legacy/upstream references only; they are not part of the current product-path status.")
    notes.append("This report proves the native-extraction verification handoff state; legacy extractors remain reference rows only.")
    return notes


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# MVP Verification Report",
        "",
        f"Overall status: **{report['overall_status']}**",
        "",
        report["safety_contract"],
        "",
        "## PDF Inventory",
        "",
        "| City | Pages | Source |",
        "|---|---:|---|",
    ]
    for row in report["pdf_inventory"]:
        pages = "missing" if row.get("missing") else row.get("page_count")
        lines.append(f"| {row['city']} | {pages} | `{row['source_pdf']}` |")

    lines.extend(
        [
            "",
            f"## Current Product Path: {report.get('current_path_version')}",
            "",
            "| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in report["current_runs"]:
        lines.append(_table_row(row["label"], row))
    lines.extend(
        [
            "",
            "_Recall verified/review is measured against the curated in-contract benchmark gold set. "
            "It is not a claim that every numeric rule in the full bylaw has been extracted._",
        ]
    )

    lines.extend(not_used_markdown(report["current_runs"]))

    m4_promotion = report.get("m4_promotion") or {}
    v3_promotion = report.get("v3_promotion") or {}
    lines.extend(
        [
            "",
            "## M4 Promotion Gate",
            "",
            f"Promoted: **{m4_promotion.get('promoted')}**",
            "",
            "| Gate | Status |",
            "|---|---|",
            f"| M4 safety | {m4_promotion.get('safety_ok')} |",
            f"| Adversarial all blocked | {m4_promotion.get('adversarial_ok')} |",
            f"| Exhaustive source coverage | {m4_promotion.get('source_coverage_ok')} |",
            f"| No verified/review recall loss vs V3 | {m4_promotion.get('no_recall_loss')} |",
            f"| Improved verified cities | {', '.join(m4_promotion.get('improved_cities') or [])} |",
            f"| Blockers | {', '.join(m4_promotion.get('reasons') or [])} |",
            "",
        ]
    )

    lines.extend(
        [
            "## V3 Promotion Gate",
            "",
            f"Promoted: **{v3_promotion.get('promoted')}**",
            "",
            "| Gate | Status |",
            "|---|---|",
            f"| V3 safety | {v3_promotion.get('safety_ok')} |",
            f"| Adversarial all blocked | {v3_promotion.get('adversarial_ok')} |",
            f"| Improvement in at least 2 cities vs V2 | {v3_promotion.get('improvement_ok')} |",
            f"| Improved cities | {', '.join(v3_promotion.get('improved_cities') or [])} |",
            f"| Blockers | {', '.join(v3_promotion.get('reasons') or [])} |",
            "",
        ]
    )

    secondary_title = "## Previous Native V3 Reference" if report.get("current_path_version") == "native_m4" else (
        "## Previous Native V2 Reference" if report.get("current_path_version") == "native_v3" else "## Experimental Native V3"
    )
    secondary_rows = report["v3_experimental_runs"] if report.get("current_path_version") == "native_m4" else (
        report["v2_reference_runs"] if report.get("current_path_version") == "native_v3" else report["v3_experimental_runs"]
    )
    lines.extend(
        [
            secondary_title,
            "",
            "| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in secondary_rows:
        lines.append(_table_row(row["label"], row))

    if report.get("current_path_version") == "native_m4":
        lines.extend(
            [
                "",
                "## Previous Native V2 Reference",
                "",
                "| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in report["v2_reference_runs"]:
            lines.append(_table_row(row["label"], row))

    lines.extend(
        [
            "",
            "## Legacy / Upstream References",
            "",
            "These rows are retained for comparison only. They are not the current product path.",
            "",
            "| Lane | Candidates | Verified | Review | Rejected | Not used | Precision | False verified | Recall verified/review | Status |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in report["legacy_references"]:
        lines.append(_table_row(row["label"], row))

    lines.extend(["", "## V2 Discovery", "", "| City | Chunks | Packs | Chunked page span | Version |", "|---|---:|---:|---|---|"])
    for row in report["v2_discovery"]:
        if row.get("missing"):
            lines.append(f"| {row['city']} | missing | missing | missing | missing |")
            continue
        span = f"{row.get('first_page')} to {row.get('last_page')} ({row.get('page_count_with_chunks')} pages with chunks)"
        lines.append(
            f"| {row['city']} | {row.get('source_chunk_count')} | {row.get('evidence_pack_count')} | "
            f"{span} | {row.get('discovery_version')} |"
        )

    lines.extend(
        [
            "",
            "## M4 Exhaustive Discovery",
            "",
            "| City | Full PDF pages | Chunks | Packs | Rule-like numeric clauses | Selected coverage | Chunked page span | Version |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in report.get("m4_discovery") or []:
        if row.get("missing"):
            lines.append(f"| {row['city']} | missing | missing | missing | missing | missing | missing | missing |")
            continue
        span = f"{row.get('first_page')} to {row.get('last_page')} ({row.get('page_count_with_chunks')} pages with chunks)"
        lines.append(
            f"| {row['city']} | {row.get('full_pdf_page_count')} | "
            f"{row.get('source_chunk_count')} | {row.get('evidence_pack_count')} | "
            f"{row.get('rule_like_numeric_clause_count')} | {fmt(row.get('selected_rule_like_numeric_coverage'))} | "
            f"{span} | {row.get('discovery_version')} |"
        )

    lines.extend(_model_runs_markdown("V2 Model Runs", report["v2_model_runs"]))
    lines.extend(_model_runs_markdown("V3 Model Runs", report.get("v3_model_runs") or []))
    lines.extend(_model_runs_markdown("M4 Model Runs", report.get("m4_model_runs") or []))

    lines.extend(["", "## Interpretation", ""])
    for note in report["interpretation"]:
        lines.append(f"- {note}")
    if report.get("commands_executed"):
        lines.extend(["", "## Commands Executed", ""])
        for command in report["commands_executed"]:
            lines.append(f"- `{command.get('display_command')}` -> {command.get('returncode')}")
    lines.append("")
    return "\n".join(lines)


def _table_row(label: str, row: dict[str, Any]) -> str:
    if row.get("missing"):
        return f"| {label} | missing | missing | missing | missing | missing | missing | missing | missing | missing |"
    return (
        f"| {label} | {row.get('candidate_rule_count')} | {row.get('verified_rule_count')} | "
        f"{row.get('review_rule_count')} | {row.get('rejected_rule_count')} | {row.get('not_used_rule_count')} | "
        f"{fmt(row.get('verified_precision'))} | {row.get('false_verified_count')} | "
        f"{fmt(row.get('verified_or_review_recall'))} | {row.get('status_label')} |"
    )


def not_used_markdown(rows: list[dict[str, Any]]) -> list[str]:
    summaries = [
        (row, row.get("not_used_summary") or {})
        for row in rows
        if not row.get("missing") and int((row.get("not_used_summary") or {}).get("count") or 0) > 0
    ]
    if not summaries:
        return []
    lines = [
        "",
        "## Out-of-scope / Not-used Explanation",
        "",
        "Not-used candidates are retained for audit but are not verified outputs and are not GIS inputs.",
        "",
        "| City | Not used | Plain explanation | Top reasons | Top rule families |",
        "|---|---:|---|---|---|",
    ]
    for row, summary in summaries:
        reasons = ", ".join(
            f"{item.get('label')} ({item.get('count')})"
            for item in summary.get("top_reasons", [])
        )
        families = ", ".join(
            f"{item.get('rule_family')} ({item.get('count')})"
            for item in summary.get("top_rule_families", [])
        )
        lines.append(
            f"| {row.get('city')} | {summary.get('count')} | {summary.get('plain_explanation')} | "
            f"{reasons} | {families} |"
        )
    return lines


def _model_runs_markdown(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "",
        f"## {title}",
        "",
        "| City | Model | Packs | Candidates | Verified | Review | Rejected | False verified | Recall verified/review | Cost |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['city']} | {row['model']} | {row.get('packs')} | {row.get('candidates')} | "
            f"{row.get('verified')} | {row.get('review')} | {row.get('rejected')} | "
            f"{row.get('false_verified')} | {fmt(row.get('verified_or_review_recall'))} | {row.get('estimated_cost_usd')} |"
        )
    return lines


def fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if value is None:
        return ""
    return str(value)


def display_command(command: list[str]) -> str:
    parts = list(command)
    if parts and Path(parts[0]).name == "python":
        try:
            if Path(parts[0]).resolve() == Path(sys.executable).resolve():
                parts[0] = ".venv/bin/python"
        except OSError:
            pass
    return " ".join(parts)


def tail(text: str, limit: int = 2000) -> str:
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
