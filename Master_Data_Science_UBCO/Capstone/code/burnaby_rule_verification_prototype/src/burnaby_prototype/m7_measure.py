"""M7 benchmark-driven measurement helpers (formerly the M5/M6 measurement layer).

This is a measurement layer around the existing verifier. It does not change
verification decisions; it copies existing run artifacts into a fresh run
folder, evaluates them, and explains the next bottleneck to improve. Many
internal names retain their historical M5 spelling (the measurement math is
unchanged); the current generation identity is M7 and measurement runs land
under outputs/m7_measure while native product runs land under outputs/m7_runs.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bylaw_rag import BylawIndex
from .config import load_config, normalize_city_key, resolve_city_paths, upstream_city_segment, write_json
from .domain_schema import token_visible, unit_visible


DEFAULT_M5_CITIES = ("burnaby_r1", "vancouver_rs", "calgary_rcg")
# M4 native-lane model dirs, in preference order. The native extractor's default
# model was upgraded to gemini-3.1-flash-lite (2026-06-16 A/B: higher recall, same
# safety); prefer its output dir when present and fall back to the prior
# gemini-2.5 dir per city so a city not yet re-run still resolves.
M7_MODEL_PREFERENCE = ("google_gemini_3_1_flash_lite", "google_gemini_2_5_flash_lite")
DEFAULT_M7_MODEL = M7_MODEL_PREFERENCE[0]
M5_RUNTIME_LIMIT_SECONDS = 300.0
DEFAULT_TOP_K = 6

RUN_ARTIFACTS_TO_COPY = (
    "rule_candidates.json",
    "evidence_units.json",
    "verified_rules.json",
    "review_needed.json",
    "rejected_rules.json",
    "not_used.json",
    "retrieved_blocks.json",
    "gis_rule_contract.json",
    "slim_summary.json",
    "bylaw_rag_index.json",
)

M55_ARTIFACTS_TO_COPY = (
    "rule_slot_ledger.json",
    "slot_audit.json",
    "m4_m55_reconciliation.json",
)

COUNTED_RULE_ARTIFACTS = {
    "rule_candidates.json": "candidate_rule_count",
    "verified_rules.json": "verified_rule_count",
    "review_needed.json": "review_rule_count",
    "rejected_rules.json": "rejected_rule_count",
    "not_used.json": "not_used_rule_count",
}


@dataclass(frozen=True)
class M5RunSpec:
    run_id: str
    city: str
    source_output_dir: Path
    output_dir: Path
    changed_component: str
    model: str


def utc_run_id(prefix: str = "m5") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}"


def run_m7_measurement(
    *,
    root: Path,
    cities: Iterable[str] = DEFAULT_M5_CITIES,
    run_id: str | None = None,
    out_root: Path | None = None,
    changed_component: str = "measurement_baseline",
    model: str = "existing_outputs",
    overwrite: bool = False,
    top_k: int = DEFAULT_TOP_K,
    refresh_verifier: bool = False,
) -> dict[str, Any]:
    """Create a fresh M5 measurement run from existing verifier artifacts."""
    root = root.resolve()
    run_id = run_id or utc_run_id()
    out_root = out_root or root / "outputs" / "m7_measure"
    run_root = out_root / run_id
    if run_root.exists() and not overwrite:
        raise FileExistsError(f"M5 run already exists: {run_root}")
    if run_root.exists() and overwrite:
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)

    normalized_cities = [normalize_city_key(city) for city in cities]
    source_registry = build_source_registry(root=root, cities=normalized_cities)
    write_json(run_root / "source_registry.json", source_registry)

    scoreboard_path = run_root / "scoreboard.jsonl"
    city_reports: list[dict[str, Any]] = []
    for city in normalized_cities:
        spec = M5RunSpec(
            run_id=run_id,
            city=city,
            source_output_dir=resolve_m5_source_output_dir(root=root, city=city),
            output_dir=run_root / city,
            changed_component=changed_component,
            model=model,
        )
        city_report = run_city_measurement(
            root=root,
            spec=spec,
            top_k=top_k,
            refresh_verifier=refresh_verifier,
        )
        city_reports.append(city_report)
        append_jsonl(scoreboard_path, city_report["scoreboard_row"])
        append_jsonl(run_root / "m55_scoreboard.jsonl", city_report["m55_scoreboard_row"])

    summary = {
        "run_id": run_id,
        "created_at": now_iso(),
        "purpose": "M5 benchmark-driven measurement run; verifier behavior unchanged.",
        "changed_component": changed_component,
        "model": model,
        "refresh_verifier": refresh_verifier,
        "cities": normalized_cities,
        "run_root": str(run_root),
        "hard_gates_passed": all(row["scoreboard_row"]["accepted"] for row in city_reports),
        "city_reports": [
            {
                "city": report["city"],
                "accepted": report["scoreboard_row"]["accepted"],
                "top_bottleneck": report["diagnosis"]["bottlenecks"][0]
                if report["diagnosis"]["bottlenecks"]
                else None,
                "report_path": report["report_path"],
            }
            for report in city_reports
        ],
        "external_inspiration": {
            "LegalBench-RAG": "precise legal retrieval evaluation",
            "RAGAS": "separate retrieval quality from answer quality",
            "PIBC Intelligent Inventory": "planner-facing bylaw search and comparison",
            "National Zoning Atlas": "consistent zoning-rule categories",
            "BC zoning guidance": "source authority and provenance",
            "ColPali": "shadow-only visual/layout retrieval for table-heavy PDFs",
            "DSPy": "benchmark-driven prompt/program optimization, never a safety bypass",
            "DocETL": "bounded document-pipeline optimization and source traceability",
        },
    }
    write_json(run_root / "m5_summary.json", summary)
    return summary


def run_city_measurement(
    *,
    root: Path,
    spec: M5RunSpec,
    top_k: int = DEFAULT_TOP_K,
    refresh_verifier: bool = False,
) -> dict[str, Any]:
    setup_record = (
        run_verifier(
            root=root,
            city=spec.city,
            output_dir=spec.output_dir,
            source_output_dir=spec.source_output_dir,
        )
        if refresh_verifier
        else copy_run_artifacts(spec.source_output_dir, spec.output_dir)
    )
    started = time.perf_counter()
    command_record = run_benchmark(root=root, city=spec.city, output_dir=spec.output_dir)
    elapsed_seconds = round(time.perf_counter() - started, 3)
    benchmark_report = read_json(spec.output_dir / "benchmark_report.json", {})
    rag_report = evaluate_rag_retrieval(root=root, city=spec.city, top_k=top_k)
    write_json(spec.output_dir / "rag_retrieval_report.json", rag_report)
    source_record = build_source_registry(root=root, cities=[spec.city])["sources"][0]
    baseline_counts = m4_baseline_counts(root=root, city=spec.city)
    rule_count_audit = audit_rule_counts(root=root, city=spec.city, output_dir=spec.output_dir)
    write_json(spec.output_dir / "rule_count_audit.json", rule_count_audit)
    # One corpus-derived base ledger (the de-circularized denominator) shared by
    # both the current run and the M4 baseline. Each run then supplements it with
    # observed slots from ITS OWN output dir — never the other run's — so the
    # baseline reconciliation is not measured against the current run's outputs.
    base_rule_slot_ledger = build_rule_slot_ledger(root=root, city=spec.city)
    rule_slot_ledger = augment_rule_slot_ledger_from_outputs(
        base_rule_slot_ledger,
        output_dir=spec.output_dir,
    )
    write_json(spec.output_dir / "rule_slot_ledger.json", rule_slot_ledger)
    slot_audit = audit_rule_slots(
        root=root,
        city=spec.city,
        output_dir=spec.output_dir,
        rule_slot_ledger=rule_slot_ledger,
    )
    write_json(spec.output_dir / "slot_audit.json", slot_audit)
    baseline_output_dir = m4_baseline_output_dir(root=root, city=spec.city)
    baseline_rule_slot_ledger = augment_rule_slot_ledger_from_outputs(
        base_rule_slot_ledger,
        output_dir=baseline_output_dir,
    )
    baseline_slot_audit = audit_rule_slots(
        root=root,
        city=spec.city,
        output_dir=baseline_output_dir,
        rule_slot_ledger=baseline_rule_slot_ledger,
    )
    reconciliation = reconcile_m4_m55(
        baseline_slot_audit=baseline_slot_audit,
        current_slot_audit=slot_audit,
    )
    write_json(spec.output_dir / "m4_m55_reconciliation.json", reconciliation)
    diagnosis = diagnose_city_run(
        benchmark_report=benchmark_report,
        rag_report=rag_report,
        source_record=source_record,
        benchmark_runtime_seconds=elapsed_seconds,
        baseline_counts=baseline_counts,
        rule_count_audit=rule_count_audit,
        slot_audit=slot_audit,
        reconciliation=reconciliation,
    )
    write_json(spec.output_dir / "m5_diagnosis.json", diagnosis)

    scoreboard_row = make_scoreboard_row(
        spec=spec,
        benchmark_report=benchmark_report,
        rag_report=rag_report,
        diagnosis=diagnosis,
        benchmark_runtime_seconds=elapsed_seconds,
        command_record=command_record,
        baseline_counts=baseline_counts,
        rule_count_audit=rule_count_audit,
        slot_audit=slot_audit,
        reconciliation=reconciliation,
    )
    m55_scoreboard_row = make_m55_scoreboard_row(scoreboard_row, slot_audit, reconciliation)
    report = {
        "city": spec.city,
        "run_id": spec.run_id,
        "output_dir": str(spec.output_dir),
        "report_path": str(spec.output_dir / "m5_diagnosis.json"),
        "benchmark_report": benchmark_report,
        "rag_retrieval_report": rag_report,
        "diagnosis": diagnosis,
        "scoreboard_row": scoreboard_row,
        "setup": setup_record,
        "m4_baseline": baseline_counts,
        "rule_count_audit": rule_count_audit,
        "rule_slot_ledger": rule_slot_ledger,
        "slot_audit": slot_audit,
        "m4_m55_reconciliation": reconciliation,
        "m55_scoreboard_row": m55_scoreboard_row,
    }
    write_json(spec.output_dir / "m5_city_report.json", report)
    return report


def copy_run_artifacts(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    if not source_dir.exists():
        raise FileNotFoundError(f"Source verifier output is missing: {source_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in RUN_ARTIFACTS_TO_COPY:
        source = source_dir / name
        if source.exists():
            shutil.copy2(source, output_dir / name)
            copied.append(name)
    return {
        "mode": "copy_existing_outputs",
        "source_dir": str(source_dir),
        "copied_artifacts": copied,
    }


def run_verifier(*, root: Path, city: str, output_dir: Path, source_output_dir: Path) -> dict[str, Any]:
    mode, command = verifier_refresh_command(
        root=root,
        city=city,
        output_dir=output_dir,
        source_output_dir=source_output_dir,
    )
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    record = {
        "mode": mode,
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": tail(result.stdout),
        "stderr_tail": tail(result.stderr),
    }
    if result.returncode != 0:
        raise RuntimeError(
            "Verifier refresh failed:\n"
            + " ".join(command)
            + "\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )
    return record


def verifier_refresh_command(
    *,
    root: Path,
    city: str,
    output_dir: Path,
    source_output_dir: Path,
) -> tuple[str, list[str]]:
    """Resolve a fresh verifier command for M5 without requiring stale registry paths."""
    base = [
        sys.executable,
        "scripts/run_slim_verifier.py",
        "--city",
        city,
        "--output-dir",
        str(output_dir),
        "--no-cache",
    ]
    if verifier_input_artifacts_available(source_output_dir):
        return (
            "refresh_verifier_existing_candidates",
            [
                *base,
                "--native-extraction",
                str(source_output_dir),
            ],
        )
    if any(path.exists() for path in pipeline5_registry_candidates(root=root, city=city)):
        return "refresh_verifier_pipeline5_registry", base
    return "refresh_verifier_pipeline5_registry_missing", base


def verifier_input_artifacts_available(source_output_dir: Path) -> bool:
    return (source_output_dir / "evidence_units.json").exists() and (
        source_output_dir / "rule_candidates.json"
    ).exists()


def resolve_m5_source_output_dir(*, root: Path, city: str) -> Path:
    """Prefer native M4 artifacts as the M5 measurement source.

    M5 is an improvement layer for the current native M4 product path. Older
    slim/Pipeline-5 folders remain useful fallbacks, but choosing them first
    hides verified-count regressions against M4.
    """
    key = normalize_city_key(city)
    for model_dir_name in M7_MODEL_PREFERENCE:
        m4_dir = root / "outputs" / "m7_runs" / key / model_dir_name
        if verifier_input_artifacts_available(m4_dir):
            return m4_dir
    city_paths = resolve_city_paths(root, key)
    return city_paths.output_dir


def m4_baseline_output_dir(*, root: Path, city: str) -> Path:
    key = normalize_city_key(city)
    for model_dir_name in M7_MODEL_PREFERENCE:
        m4_dir = root / "outputs" / "m7_runs" / key / model_dir_name
        if verifier_input_artifacts_available(m4_dir):
            return m4_dir
    return root / "outputs" / "m7_runs" / key / DEFAULT_M7_MODEL


def m4_baseline_counts(*, root: Path, city: str) -> dict[str, Any]:
    baseline_dir = m4_baseline_output_dir(root=root, city=city)
    counts = output_artifact_counts(baseline_dir)
    verified = read_json(baseline_dir / "verified_rules.json", [])
    if not isinstance(verified, list):
        verified = []
    verified_duplicates = duplicate_rule_summary(verified)
    verified_exact_duplicate_count = verified_duplicates["source_aware_duplicate_rule_count"]
    verified_count = counts.get("verified_rule_count") or 0
    return {
        "baseline_name": "native_m4",
        "baseline_output_dir": str(baseline_dir),
        "baseline_available": verifier_input_artifacts_available(baseline_dir),
        "verified_exact_duplicate_count": verified_exact_duplicate_count,
        "effective_verified_rule_count": max(0, verified_count - verified_exact_duplicate_count),
        **counts,
    }


def output_artifact_counts(output_dir: Path) -> dict[str, int | None]:
    return {
        count_key: json_list_count(output_dir / artifact_name)
        for artifact_name, count_key in COUNTED_RULE_ARTIFACTS.items()
    }


def json_list_count(path: Path) -> int | None:
    payload = read_json(path, None)
    return len(payload) if isinstance(payload, list) else None


def audit_rule_counts(*, root: Path, city: str, output_dir: Path) -> dict[str, Any]:
    """Audit output volume against source-derived ceilings and duplicate keys.

    This is deliberately a loose overcount audit, not a claim that the source
    corpus contains exactly this many legal rules. Prose rule-like clauses and
    table cells are source slots; a table cell can produce more than one rule
    (for example height and storeys), while several columns can repeat the same
    legal value. The audit catches obvious overextraction/oververification
    without turning source discovery into a hidden answer key.
    """
    key = normalize_city_key(city)
    manifest = read_json(root / "benchmark" / "source_corpus" / key / "manifest.json", {})
    coverage = read_json(root / "benchmark" / "source_corpus" / key / "coverage_audit.json", {})
    city_paths = resolve_city_paths(root, key)
    config = load_config(city_paths.config) if city_paths.config.exists() else {}
    contract_families = {
        normalize_family(family)
        for family in ((config.get("verification") or {}).get("gis_text_rule_contract") or [])
    }
    counts = output_artifact_counts(output_dir)
    candidates = read_json(output_dir / "rule_candidates.json", [])
    verified = read_json(output_dir / "verified_rules.json", [])
    if not isinstance(candidates, list):
        candidates = []
    if not isinstance(verified, list):
        verified = []

    rule_like_numeric = int(
        manifest.get("rule_like_numeric_clause_count")
        or coverage.get("rule_like_numeric_clause_count")
        or 0
    )
    table_cell_count = int(coverage.get("table_cell_count") or 0)
    loose_source_rule_slot_ceiling = rule_like_numeric + table_cell_count
    verified_duplicate_summary = duplicate_rule_summary(verified)
    candidate_duplicate_summary = duplicate_rule_summary(candidates)
    verified_family_counts = family_count_rows(verified)
    candidate_family_counts = family_count_rows(candidates)
    verified_out_of_contract = [
        _rule_identifier(rule)
        for rule in verified
        if contract_families and normalize_family(rule.get("rule_object")) not in contract_families
    ]
    candidate_out_of_contract = [
        _rule_identifier(rule)
        for rule in candidates
        if contract_families and normalize_family(rule.get("rule_object")) not in contract_families
    ]
    candidate_count = counts.get("candidate_rule_count") or 0
    verified_count = counts.get("verified_rule_count") or 0
    verified_exact_duplicate_count = verified_duplicate_summary["source_aware_duplicate_rule_count"]
    effective_verified_rule_count = max(0, verified_count - verified_exact_duplicate_count)
    counts["effective_verified_rule_count"] = effective_verified_rule_count
    return {
        "city": key,
        "created_at": now_iso(),
        "advisory_note": (
            "Loose ceiling = source rule-like numeric clauses + table cells. "
            "It is an overcount guardrail, not an exact legal-rule total."
        ),
        "source_counts": {
            "rule_like_numeric_clause_count": rule_like_numeric,
            "table_cell_count": table_cell_count,
            "loose_source_rule_slot_ceiling": loose_source_rule_slot_ceiling,
            "numeric_clause_count": manifest.get("numeric_clause_count")
            or coverage.get("numeric_clause_count"),
            "table_entry_count": manifest.get("table_entry_count")
            or coverage.get("table_entry_count"),
            "source_chunk_count": manifest.get("source_chunk_count")
            or coverage.get("source_chunk_count"),
        },
        "output_counts": counts,
        "ratios": {
            "candidate_to_loose_ceiling": ratio(candidate_count, loose_source_rule_slot_ceiling),
            "verified_to_loose_ceiling": ratio(verified_count, loose_source_rule_slot_ceiling),
        },
        "flags": {
            "candidate_count_exceeds_loose_source_ceiling": (
                loose_source_rule_slot_ceiling > 0 and candidate_count > loose_source_rule_slot_ceiling
            ),
            "verified_count_exceeds_loose_source_ceiling": (
                loose_source_rule_slot_ceiling > 0 and verified_count > loose_source_rule_slot_ceiling
            ),
            "verified_exact_duplicate_count": verified_exact_duplicate_count,
            "candidate_exact_duplicate_count": candidate_duplicate_summary["source_aware_duplicate_rule_count"],
            "verified_out_of_contract_count": len(verified_out_of_contract),
            "candidate_out_of_contract_count": len(candidate_out_of_contract),
        },
        "contract_families": sorted(contract_families),
        "verified_family_counts": verified_family_counts,
        "candidate_family_counts": candidate_family_counts,
        "verified_out_of_contract_rule_ids": verified_out_of_contract[:100],
        "candidate_out_of_contract_rule_ids": candidate_out_of_contract[:100],
        "verified_duplicates": verified_duplicate_summary,
        "candidate_duplicates": candidate_duplicate_summary,
    }


def build_rule_slot_ledger(*, root: Path, city: str) -> dict[str, Any]:
    """Build the M5.5 source-derived denominator for over/under verification.

    A slot is smaller than a source chunk. Clause chunks and table cells can
    contain multiple legal values, so M5.5 creates one slot per visible
    measurement signal. The ledger is a measurement denominator, not a hidden
    verification answer key.
    """
    key = normalize_city_key(city)
    city_paths = resolve_city_paths(root, key)
    config = load_config(city_paths.config) if city_paths.config.exists() else {}
    contract_families = {
        normalize_family(family)
        for family in ((config.get("verification") or {}).get("gis_text_rule_contract") or [])
    }
    source_root = root / "benchmark" / "source_corpus" / key
    numeric_clauses = read_json(source_root / "numeric_clause_index.json", [])
    table_rows = read_json(source_root / "table_index.json", [])
    slots: list[dict[str, Any]] = []

    if not isinstance(numeric_clauses, list):
        numeric_clauses = []
    for clause in numeric_clauses:
        text = str(clause.get("text_preview") or "")
        family = infer_rule_family(text)
        for index, measurement in enumerate(extract_measurements(text), start=1):
            slot = {
                "slot_id": f"{key}:clause:{clause.get('chunk_id')}:m{index:03d}",
                "city": key,
                "source_type": "clause",
                "source_chunk_id": clause.get("chunk_id"),
                "page": clause.get("page"),
                "section": clause.get("section"),
                "table_title": "",
                "row_header": "",
                "column_header": "",
                "cell_value": "",
                "value": measurement["value"],
                "unit": measurement["unit"],
                "value_text": measurement["value_text"],
                "measurement_ordinal": index,
                "rule_family_signal": family,
                "scope_signal": source_scope_signal(text),
                "operator_signal": operator_signal(text),
                "source_text": text,
                "slot_origin": "source_corpus",
                "gis_contract_relevance": gis_contract_relevance(family, contract_families),
                "extractability_status": (
                    "expected_extractable" if clause.get("rule_signal") else "observed_numeric_clause"
                ),
            }
            slots.append(slot)

    if not isinstance(table_rows, list):
        table_rows = []
    for row in table_rows:
        cells = row.get("cells") if isinstance(row.get("cells"), list) else []
        row_header = str(row.get("row_header") or "")
        table_title = str(row.get("table_title") or "")
        for cell_index, cell in enumerate(cells, start=1):
            cell_value = str(cell.get("cell_value") or "")
            if not meaningful_cell_value(cell_value):
                continue
            column_header = str(cell.get("column_header") or "")
            source_text = " | ".join(
                part
                for part in (table_title, row_header, column_header, cell_value)
                if str(part or "").strip()
            )
            measurements = extract_measurements(cell_value)
            if not measurements:
                measurements = [{"value": "", "unit": "", "value_text": normalized_text(cell_value)}]
            for measurement_index, measurement in enumerate(measurements, start=1):
                family = infer_rule_family(" ".join((row_header, column_header, cell_value, table_title)))
                slot = {
                    "slot_id": (
                        f"{key}:table:{row.get('chunk_id')}:c{cell_index:02d}:"
                        f"m{measurement_index:03d}"
                    ),
                    "city": key,
                    "source_type": "table_cell",
                    "source_chunk_id": row.get("chunk_id"),
                    "page": row.get("page"),
                    "section": row.get("section"),
                    "table_title": table_title,
                    "row_header": row_header,
                    "column_header": column_header,
                    "cell_value": cell_value,
                    "value": measurement["value"],
                    "unit": measurement["unit"],
                    "value_text": measurement["value_text"],
                    "measurement_ordinal": measurement_index,
                    "rule_family_signal": family,
                    "scope_signal": source_scope_signal(source_text),
                    "operator_signal": operator_signal(source_text),
                    "source_text": source_text,
                    "slot_origin": "source_corpus",
                    "gis_contract_relevance": gis_contract_relevance(family, contract_families),
                    "extractability_status": "expected_extractable",
                }
                slots.append(slot)

    return {
        "created_at": now_iso(),
        "city": key,
        "purpose": (
            "M5.5 source-derived rule slot ledger. This is the count denominator "
            "for over/under verification; it does not promote rules."
        ),
        "slot_count": len(slots),
        "clause_slot_count": sum(1 for slot in slots if slot["source_type"] == "clause"),
        "table_slot_count": sum(1 for slot in slots if slot["source_type"] == "table_cell"),
        "gis_contract_slot_count": sum(
            1 for slot in slots if slot["gis_contract_relevance"] == "in_gis_contract"
        ),
        "contract_families": sorted(contract_families),
        "slots": slots,
    }


def augment_rule_slot_ledger_from_outputs(
    rule_slot_ledger: dict[str, Any],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Add run-observed source-coordinate slots that the source corpus missed.

    This is mainly for table-heavy PDFs where a deterministic matrix extractor
    carries richer row/column/cell coordinates than the generic PDF table index.
    These slots are still source-derived, but their origin is the verifier's
    cited source packet rather than the static source-corpus table index.
    """
    slots = list(rule_slot_ledger.get("slots") or [])
    existing = {slot_signature(slot) for slot in slots}
    evidence_units = read_json(output_dir / "evidence_units.json", [])
    if not isinstance(evidence_units, list):
        evidence_units = []
    evidence_by_id = {
        str(unit.get("evidence_id")): unit
        for unit in evidence_units
        if isinstance(unit, dict) and unit.get("evidence_id")
    }
    rows: list[dict[str, Any]] = []
    for name in COUNTED_RULE_ARTIFACTS:
        payload = read_json(output_dir / name, [])
        if isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, dict))
    added = []
    for rule in rows:
        source = rule_source_record(rule, evidence_by_id)
        if not source.get("page"):
            continue
        value = normalized_number(rule.get("value"))
        if not value:
            continue
        unit = normalize_unit(rule.get("unit"))
        family = normalize_family(rule.get("rule_object")) or infer_rule_family(
            " ".join(str(source.get(part) or "") for part in ("row_header", "column_header", "cell_value", "source_context"))
        )
        source_type = source.get("evidence_type") or "observed_source"
        candidate_slot = {
            "city": rule_slot_ledger.get("city"),
            "source_type": source_type,
            "source_chunk_id": source.get("chunk_id"),
            "page": source.get("page"),
            "section": source.get("section"),
            "table_title": source.get("table_title") or "",
            "row_header": source.get("row_header") or "",
            "column_header": source.get("column_header") or "",
            "cell_value": source.get("cell_value") or "",
            "value": value,
            "unit": unit,
            "value_text": " ".join(str(part) for part in (value, unit) if part),
            "measurement_ordinal": 1,
            "rule_family_signal": family,
            "scope_signal": source_scope_signal(
                " ".join(str(source.get(part) or "") for part in ("row_header", "column_header", "cell_value", "source_context"))
            ),
            "operator_signal": canonical_operator(rule.get("operator"), rule.get("constraint_type")),
            "source_text": source.get("source_context") or source.get("evidence_text") or "",
            "slot_origin": "output_observed",
            "gis_contract_relevance": "run_observed",
            "extractability_status": "observed_output_source_slot",
        }
        signature = slot_signature(candidate_slot)
        if signature in existing:
            continue
        candidate_slot["slot_id"] = f"{rule_slot_ledger.get('city')}:observed:{stable_short_hash(signature)}"
        slots.append(candidate_slot)
        added.append(candidate_slot["slot_id"])
        existing.add(signature)
    return {
        **rule_slot_ledger,
        "slot_count": len(slots),
        "observed_output_slot_count": len(added),
        "slots": slots,
    }


def audit_rule_slots(
    *,
    root: Path,
    city: str,
    output_dir: Path,
    rule_slot_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map verifier artifacts to M5.5 rule slots and diagnose count quality."""
    key = normalize_city_key(city)
    rule_slot_ledger = rule_slot_ledger or build_rule_slot_ledger(root=root, city=key)
    slots = rule_slot_ledger.get("slots") if isinstance(rule_slot_ledger, dict) else []
    if not isinstance(slots, list):
        slots = []
    evidence_units = read_json(output_dir / "evidence_units.json", [])
    if not isinstance(evidence_units, list):
        evidence_units = []
    evidence_by_id = {
        str(unit.get("evidence_id")): unit
        for unit in evidence_units
        if isinstance(unit, dict) and unit.get("evidence_id")
    }
    buckets = {
        "candidate": read_json(output_dir / "rule_candidates.json", []),
        "verified": read_json(output_dir / "verified_rules.json", []),
        "review": read_json(output_dir / "review_needed.json", []),
        "rejected": read_json(output_dir / "rejected_rules.json", []),
        "not_used": read_json(output_dir / "not_used.json", []),
    }
    for name, rows in list(buckets.items()):
        if not isinstance(rows, list):
            buckets[name] = []

    mappings_by_bucket: dict[str, list[dict[str, Any]]] = {
        name: map_rules_to_slots(rows, slots, evidence_by_id, bucket=name)
        for name, rows in buckets.items()
    }
    slot_status = summarize_slot_status(slots, mappings_by_bucket)
    slots_by_id = {str(slot.get("slot_id")): slot for slot in slots if slot.get("slot_id")}
    scored_metrics = compute_scored_slot_metrics(slots_by_id, slot_status)
    duplicate_summary = slot_duplicate_summary(mappings_by_bucket["verified"])
    verified_count = len(buckets["verified"])
    mapped_verified = sum(1 for item in mappings_by_bucket["verified"] if item.get("slot_id"))
    unsupported_verified = [
        item
        for item in mappings_by_bucket["verified"]
        if not item.get("slot_id")
    ]
    metrics = {
        "total_rule_slots": len(slots),
        "verified_rule_count": verified_count,
        "verified_mapped_rule_count": mapped_verified,
        "verified_slot_mapping_rate": ratio(mapped_verified, verified_count) if verified_count else 1.0,
        "effective_verified_slot_count": len(slot_status["verified_slot_ids"]),
        "review_slot_count": len(slot_status["review_slot_ids"]),
        "candidate_slot_count": len(slot_status["candidate_slot_ids"]),
        "candidate_only_slot_count": len(slot_status["candidate_only_slot_ids"]),
        "missed_slot_count": len(slot_status["missed_slot_ids"]),
        "unsupported_verified_rule_count": len(unsupported_verified),
        "raw_duplicate_verified_slot_count": duplicate_summary["raw_duplicate_verified_slot_count"],
        "duplicate_merged_count": duplicate_summary["duplicate_merged_count"],
        "duplicate_verified_slot_count": duplicate_summary["unresolved_duplicate_verified_slot_count"],
        **scored_metrics,
    }
    return {
        "created_at": now_iso(),
        "city": key,
        "purpose": "M5.6 slot confusion matrix for too-much/too-little verification.",
        "slot_metrics": metrics,
        "scored_slot_metrics": scored_metrics,
        "slot_confusion_matrix": {
            "verified_slots": len(slot_status["verified_slot_ids"]),
            "review_slots": len(slot_status["review_slot_ids"]),
            "candidate_only_slots": len(slot_status["candidate_only_slot_ids"]),
            "missed_slots": len(slot_status["missed_slot_ids"]),
            "duplicate_verified_slots": metrics["duplicate_verified_slot_count"],
            "unsupported_verified_rules": len(unsupported_verified),
        },
        "scored_slot_confusion_matrix": {
            "distinct_legal_slots": scored_metrics["distinct_scored_legal_slot_count"],
            "verified_slots": scored_metrics["scored_verified_slot_count"],
            "review_only_slots": scored_metrics["scored_review_slot_count"],
            "missed_slots": scored_metrics["scored_missed_slot_count"],
            "verified_coverage": scored_metrics["scored_verified_coverage"],
            "active_coverage": scored_metrics["scored_active_coverage"],
        },
        "slot_status": {
            "verified_slot_ids": sorted(slot_status["verified_slot_ids"]),
            "review_slot_ids": sorted(slot_status["review_slot_ids"]),
            "candidate_only_slot_ids": sorted(slot_status["candidate_only_slot_ids"])[:500],
            "missed_slot_ids": sorted(slot_status["missed_slot_ids"])[:500],
        },
        "mappings": {
            f"{bucket}_rule_mappings": mappings
            for bucket, mappings in mappings_by_bucket.items()
        },
        "unsupported_verified_rules": unsupported_verified,
        "duplicate_verified_slots": duplicate_summary["duplicate_verified_slots"],
        "duplicate_merged_rules": duplicate_summary["duplicate_merged_rules"],
        "frontier_shadow_lanes": [
            {
                "lane": "visual_layout_retrieval",
                "status": "shadow_only",
                "purpose": "Evaluate table/footnote page-image retrieval without promoting rules.",
            },
            {
                "lane": "benchmark_driven_optimizer",
                "status": "shadow_only",
                "purpose": "Try extraction prompt/decomposition variants under M5.5 gates.",
            },
        ],
    }


def reconcile_m4_m55(
    *,
    baseline_slot_audit: dict[str, Any],
    current_slot_audit: dict[str, Any],
) -> dict[str, Any]:
    baseline_mappings = (baseline_slot_audit.get("mappings") or {}).get("verified_rule_mappings", [])
    current_mappings = (current_slot_audit.get("mappings") or {}).get("verified_rule_mappings", [])
    current_slots = {item.get("slot_id") for item in current_mappings if item.get("slot_id")}
    seen_baseline_slots: set[str] = set()
    rows = []
    for mapping in baseline_mappings:
        slot_id = mapping.get("slot_id")
        rule_id = mapping.get("rule_id")
        if not slot_id:
            status = "unsupported_baseline"
        elif slot_id in seen_baseline_slots:
            status = "duplicate_merged"
        elif slot_id in current_slots:
            status = "kept"
            seen_baseline_slots.add(slot_id)
        else:
            status = "missing_from_current"
            seen_baseline_slots.add(slot_id)
        rows.append(
            {
                "baseline_rule_id": rule_id,
                "slot_id": slot_id,
                "status": status,
                "mapping_confidence": mapping.get("mapping_confidence"),
                "reason": reconciliation_reason(status),
            }
        )
    baseline_slots = {
        item.get("slot_id") for item in baseline_mappings if item.get("slot_id")
    }
    new_current_slots = sorted(slot for slot in current_slots if slot not in baseline_slots)
    status_counts = sorted_counts(row["status"] for row in rows)
    baseline_effective = len(baseline_slots)
    current_effective = len(current_slots)
    return {
        "created_at": now_iso(),
        "purpose": "M4-to-M5.5 verified-slot reconciliation.",
        "baseline_effective_verified_slot_count": baseline_effective,
        "current_effective_verified_slot_count": current_effective,
        "effective_verified_slot_count_delta": current_effective - baseline_effective,
        "status_counts": status_counts,
        "rows": rows,
        "new_current_slot_ids": new_current_slots,
    }


def map_rules_to_slots(
    rules: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    *,
    bucket: str,
) -> list[dict[str, Any]]:
    return [
        {
            "bucket": bucket,
            "rule_id": _rule_identifier(rule),
            "slot_id": match.get("slot_id"),
            "mapping_confidence": match.get("confidence"),
            "mapping_score": match.get("score"),
            "mapping_reason": match.get("reason"),
            "rule_object": rule.get("rule_object"),
            "value": rule.get("value"),
            "unit": rule.get("unit"),
            "source": match.get("source"),
        }
        for rule in rules
        for match in [map_rule_to_slot(rule, slots, evidence_by_id)]
    ]


def map_rule_to_slot(
    rule: dict[str, Any],
    slots: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = rule_source_record(rule, evidence_by_id)
    rule_value = normalized_number(rule.get("value"))
    rule_unit = normalize_unit(rule.get("unit"))
    rule_family = normalize_family(rule.get("rule_object"))
    if not rule_value:
        return {"slot_id": None, "confidence": "none", "score": 0, "reason": "rule_has_no_value", "source": source}

    scored = []
    for slot in slots:
        slot_value = normalized_number(slot.get("value"))
        if slot_value and slot_value != rule_value:
            continue
        if not slot_value and not value_visible(slot.get("source_text", ""), rule_value):
            continue
        score = 0
        reasons: list[str] = []
        if source.get("chunk_id") and source.get("chunk_id") == slot.get("source_chunk_id"):
            score += 8
            reasons.append("chunk")
        if source.get("page") not in (None, "") and source.get("page") == slot.get("page"):
            score += 3
            reasons.append("page")
        if source.get("evidence_type") and source.get("evidence_type") == slot.get("source_type"):
            score += 2
            reasons.append("source_type")
        if normalized_text(source.get("row_header")) and normalized_text(source.get("row_header")) == normalized_text(slot.get("row_header")):
            score += 5
            reasons.append("row")
        if normalized_text(source.get("column_header")) and normalized_text(source.get("column_header")) == normalized_text(slot.get("column_header")):
            score += 5
            reasons.append("column")
        if normalized_text(source.get("cell_value")) and normalized_text(source.get("cell_value")) == normalized_text(slot.get("cell_value")):
            score += 4
            reasons.append("cell")
        if slot_value == rule_value:
            score += 6
            reasons.append("value")
        if unit_compatible(rule_unit, normalize_unit(slot.get("unit"))):
            score += 2
            reasons.append("unit")
        if rule_family and rule_family == normalize_family(slot.get("rule_family_signal")):
            score += 2
            reasons.append("family")
        overlap = source_text_overlap(source.get("evidence_text") or source.get("source_context"), slot.get("source_text"))
        if overlap:
            score += min(3, overlap)
            reasons.append("text")
        if score:
            scored.append((score, reasons, slot))

    if not scored:
        return {"slot_id": None, "confidence": "none", "score": 0, "reason": "no_source_slot_match", "source": source}
    scored.sort(key=lambda item: (-item[0], str(item[2].get("slot_id"))))
    score, reasons, slot = scored[0]
    confidence = "exact" if score >= 14 else "probable" if score >= 9 else "weak"
    if score < 7:
        return {"slot_id": None, "confidence": "none", "score": score, "reason": "best_match_too_weak", "source": source}
    return {
        "slot_id": slot.get("slot_id"),
        "confidence": confidence,
        "score": score,
        "reason": "+".join(reasons),
        "source": {
            "page": source.get("page"),
            "chunk_id": source.get("chunk_id"),
            "evidence_type": source.get("evidence_type"),
            "slot_source_type": slot.get("source_type"),
        },
    }


def rule_source_record(
    rule: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = dict(rule.get("source") or {}) if isinstance(rule.get("source"), dict) else {}
    candidate = rule.get("candidate") if isinstance(rule.get("candidate"), dict) else rule
    evidence_id = (
        source.get("evidence_id")
        or rule.get("evidence_id")
        or (candidate.get("evidence_id") if isinstance(candidate, dict) else None)
    )
    evidence = evidence_by_id.get(str(evidence_id), {}) if evidence_id else {}
    native = {}
    if isinstance(candidate, dict) and isinstance(candidate.get("native_provenance"), dict):
        native = candidate["native_provenance"]
    elif isinstance(rule.get("native_provenance"), dict):
        native = rule["native_provenance"]
    elif isinstance(evidence.get("native_provenance"), dict):
        native = evidence["native_provenance"]
    return {
        "page": source.get("page") or evidence.get("page") or native.get("page"),
        "section": source.get("source_section") or source.get("section") or evidence.get("section"),
        "evidence_id": evidence_id,
        "evidence_type": source.get("evidence_type") or evidence.get("evidence_type"),
        "evidence_text": source.get("evidence_text") or evidence.get("evidence_text"),
        "source_context": source.get("source_context") or evidence.get("source_context"),
        "table_title": source.get("table_title"),
        "row_header": source.get("row_header") or native.get("row_label"),
        "column_header": source.get("column_header"),
        "cell_value": source.get("cell_value"),
        "chunk_id": native.get("chunk_id"),
    }


def summarize_slot_status(
    slots: list[dict[str, Any]],
    mappings_by_bucket: dict[str, list[dict[str, Any]]],
) -> dict[str, set[str]]:
    all_slot_ids = {str(slot.get("slot_id")) for slot in slots if slot.get("slot_id")}
    candidate_slots = mapped_slot_ids(mappings_by_bucket.get("candidate", []))
    verified_slots = mapped_slot_ids(mappings_by_bucket.get("verified", []))
    review_slots = mapped_slot_ids(mappings_by_bucket.get("review", []))
    active_slots = candidate_slots | verified_slots | review_slots
    return {
        "all_slot_ids": all_slot_ids,
        "candidate_slot_ids": candidate_slots,
        "verified_slot_ids": verified_slots,
        "review_slot_ids": review_slots,
        "candidate_only_slot_ids": candidate_slots - verified_slots - review_slots,
        "missed_slot_ids": all_slot_ids - active_slots,
    }


def mapped_slot_ids(mappings: list[dict[str, Any]]) -> set[str]:
    return {str(mapping.get("slot_id")) for mapping in mappings if mapping.get("slot_id")}


def _legal_keys(slots_by_id: dict[str, dict[str, Any]], slot_ids: set[str]) -> set[tuple[str, ...]]:
    return {legal_slot_key(slots_by_id[sid]) for sid in slot_ids if sid in slots_by_id}


def compute_scored_slot_metrics(
    slots_by_id: dict[str, dict[str, Any]],
    slot_status: dict[str, set[str]],
) -> dict[str, Any]:
    """M5.6 honest denominator: scored, de-circularized, semantically deduped.

    The raw ledger over-counts on purpose (every numeric signal is a slot) so it
    can never hide over-extraction. These metrics report coverage against the
    *defensible* denominator instead: corpus-derived, recognized-family,
    in-GIS-contract slots, collapsed to distinct legal (family, value, unit,
    scope) keys so the same value repeated across matrix columns counts once.

    Coverage is credited by legal identity, not slot id. A verified rule that the
    generic corpus table index could only pin to an output-observed coordinate
    still credits the corpus slot it legally matches, so excluding output-derived
    slots from the *denominator* (to break circularity) never silently zeroes the
    *numerator*. Slot-id counts are kept alongside for transparency.
    """
    all_ids = set(slots_by_id)
    source_ids = {sid for sid, slot in slots_by_id.items() if is_source_denominator_slot(slot)}
    scored_ids = {sid for sid, slot in slots_by_id.items() if slot_is_scored(slot)}

    verified_ids = slot_status["verified_slot_ids"]
    review_ids = slot_status["review_slot_ids"]
    candidate_ids = slot_status["candidate_slot_ids"]
    active_ids = verified_ids | review_ids | candidate_ids

    scored_keys = _legal_keys(slots_by_id, scored_ids)
    verified_keys = _legal_keys(slots_by_id, verified_ids)
    review_keys = _legal_keys(slots_by_id, review_ids)
    active_keys = _legal_keys(slots_by_id, active_ids)

    covered_verified = scored_keys & verified_keys
    covered_review_only = (scored_keys & review_keys) - verified_keys
    covered_active = scored_keys & active_keys
    missed_keys = scored_keys - active_keys

    # Slot-id view (corpus-only) kept for transparency; coverage uses legal keys.
    scored_verified_slots = verified_ids & scored_ids
    scored_review_slots = review_ids & scored_ids
    return {
        "raw_total_rule_slots": len(all_ids),
        "source_denominator_slot_count": len(source_ids),
        "observed_supplement_slot_count": len(all_ids - source_ids),
        "scored_total_slots": len(scored_ids),
        "distinct_scored_legal_slot_count": len(scored_keys),
        # Legal-key coverage (the M5.6 headline): de-circularized + deduped.
        "scored_verified_slot_count": len(covered_verified),
        "scored_review_slot_count": len(covered_review_only),
        "scored_missed_slot_count": len(missed_keys),
        "scored_verified_coverage": ratio(len(covered_verified), len(scored_keys)),
        "scored_active_coverage": ratio(len(covered_active), len(scored_keys)),
        # Slot-id transparency counts (corpus-derived scored slots only).
        "scored_verified_slot_id_count": len(scored_verified_slots),
        "scored_review_slot_id_count": len(scored_review_slots),
        "scored_candidate_only_slot_id_count": len((candidate_ids - verified_ids - review_ids) & scored_ids),
    }


def slot_signature(slot: dict[str, Any]) -> str:
    return "|".join(
        normalized_text(slot.get(part))
        for part in (
            "source_type",
            "source_chunk_id",
            "page",
            "section",
            "table_title",
            "row_header",
            "column_header",
            "cell_value",
            "value",
            "unit",
            "rule_family_signal",
        )
    )


def stable_short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


# M5.6: the raw slot ledger is a loose over-count ceiling (one slot per visible
# numeric signal). It is deliberately noisy so it can never hide an
# over-extraction. For honest coverage reporting we score a tighter denominator:
# only corpus-derived slots (never the verifier's own outputs, which would make
# the denominator a function of the numerator), with a recognized rule family,
# that fall inside the city's GIS text-rule contract.
NOISE_FAMILIES = {"", "unknown"}


def is_source_denominator_slot(slot: dict[str, Any]) -> bool:
    """True for slots derived from the static source corpus, not run outputs."""
    return str(slot.get("slot_origin") or "source_corpus") == "source_corpus"


def slot_is_scored(slot: dict[str, Any]) -> bool:
    """M5.6 scored-denominator membership: corpus-derived, known family, in-contract."""
    if not is_source_denominator_slot(slot):
        return False
    if normalize_family(slot.get("rule_family_signal")) in NOISE_FAMILIES:
        return False
    return slot.get("gis_contract_relevance") == "in_gis_contract"


def legal_slot_key(slot: dict[str, Any]) -> tuple[str, ...]:
    """Identity of a distinct *legal* rule slot for semantic dedup.

    A single legal value repeated across matrix columns/rows or restated in
    prose is one legal slot, not many. Collapsing on (family, value, unit) turns
    the raw per-signal ceiling into a defensible legal-rule count.

    Scope is deliberately NOT part of this key. Source-inferred scope
    (``source_scope_signal``) is greedy on table-cell context — a cell that sits
    in a multi-column yard row picks up "front" from a neighbouring column — so
    keying on it would both fracture true matches and mislabel slots. Scope
    *correctness* is enforced where it must be (the verifier's deterministic
    scope/column-binding gates), not in this measurement denominator. The cost
    is that two genuinely different scopes sharing one value collapse to a single
    legal slot, which is a conservative (coverage-deflating is preferred, this is
    mildly coverage-inflating) and clearly-documented approximation.
    """
    return (
        normalize_family(slot.get("rule_family_signal")),
        normalized_number(slot.get("value")),
        normalize_unit(slot.get("unit")),
    )


def slot_duplicate_summary(verified_mappings: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for mapping in verified_mappings:
        slot_id = mapping.get("slot_id")
        if slot_id:
            groups.setdefault(str(slot_id), []).append(mapping)
    duplicate_slots = []
    duplicate_merged_rules = []
    for slot_id, members in sorted(groups.items()):
        if len(members) <= 1:
            continue
        # Deterministic keeper: pick the lowest rule_id, not whatever happened to
        # arrive first. Otherwise two runs over differently-ordered verified lists
        # would attribute the same slot to different keeper rules and the
        # reconciliation rows would flap between runs.
        members = sorted(members, key=lambda item: str(item.get("rule_id") or ""))
        keeper = members[0]
        merged = members[1:]
        duplicate_slots.append(
            {
                "slot_id": slot_id,
                "keeper_rule_id": keeper.get("rule_id"),
                "duplicate_rule_ids": [item.get("rule_id") for item in merged],
                "count": len(members),
                "resolution": "duplicate_merged",
            }
        )
        duplicate_merged_rules.extend(
            {
                "rule_id": item.get("rule_id"),
                "slot_id": slot_id,
                "status": "duplicate_merged",
                "kept_rule_id": keeper.get("rule_id"),
            }
            for item in merged
        )
    return {
        "raw_duplicate_verified_slot_count": len(duplicate_slots),
        "duplicate_merged_count": len(duplicate_merged_rules),
        "unresolved_duplicate_verified_slot_count": 0,
        "duplicate_verified_slots": duplicate_slots,
        "duplicate_merged_rules": duplicate_merged_rules,
    }


# Words that, when they immediately precede a unit-less number, mark it as a
# cross-reference (e.g. "section 6", "Table 3") rather than a measurement.
_SECTION_CUE_WORDS = {
    "section", "sections", "clause", "clauses", "subsection", "subsections",
    "part", "parts", "division", "article", "schedule", "table", "figure",
    "no", "item", "paragraph", "sentence", "appendix", "bylaw", "page",
}


def _is_reference_number(raw: str, start: int, end: int, unit: str) -> bool:
    """True for unit-less numbers that are document references, not measurements.

    A number carrying a measurement unit is always treated as real. Without a
    unit, we drop numbers that are part of a dotted numbering (``6.2.3``), an
    enumerator (``(1)``), or that follow a section/table cue word. This keeps the
    raw slot ledger from inflating on legal cross-references and clause numbers.
    """
    if unit:
        return False
    if re.match(r"\.\d", raw[end:end + 2]):
        return True
    before_char = raw[start - 1] if start > 0 else ""
    after_char = raw[end] if end < len(raw) else ""
    if before_char == "(" and after_char == ")":
        return True
    prefix_word = re.search(r"([A-Za-z]+)\W*$", raw[:start])
    return bool(prefix_word and prefix_word.group(1).lower() in _SECTION_CUE_WORDS)


def extract_measurements(text: Any) -> list[dict[str, str]]:
    raw = str(text or "")
    rows = []
    for match in re.finditer(
        r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)(?:\s*)(%|m2|m²|m|metres?|meters?|storeys?|stories?|units?|spaces?)?",
        raw,
        flags=re.IGNORECASE,
    ):
        value = normalized_number(match.group(1))
        unit = normalize_unit(match.group(2) or "")
        if not value:
            continue
        if _is_reference_number(raw, match.start(1), match.end(1), unit):
            continue
        rows.append({"value": value, "unit": unit, "value_text": match.group(0).strip()})
    return rows


def meaningful_cell_value(value: Any) -> bool:
    return normalized_text(value) not in {"", "-", "—", "–", "n/a", "na", "none"}


def infer_rule_family(text: Any) -> str:
    lowered = str(text or "").lower()
    patterns = [
        ("fire_access_corridor", ("fire access corridor",)),
        ("automatic_sprinkler", ("sprinkler",)),
        ("building_separation", ("separation", "between front", "between rear", "between all other")),
        ("impervious_surface", ("impervious",)),
        ("lot_coverage", ("lot coverage", "coverage")),
        ("dwelling_units", ("dwelling units", "units", "unit count")),
        ("lot_area", ("lot area", "parcel area")),
        ("lot_width", ("lot width", "parcel width")),
        ("floor_area", ("floor area", "floor space", "gross floor")),
        ("setback", ("setback", "yard", "front:", "flanking:", "rear", "side")),
        ("storeys", ("storey", "storeys", "stories")),
        ("height", ("height", "roof")),
        ("parking", ("parking", "spaces")),
    ]
    for family, needles in patterns:
        if any(needle in lowered for needle in needles):
            return family
    return "unknown"


def source_scope_signal(text: Any) -> str:
    lowered = str(text or "").lower()
    if "front" in lowered:
        return "front"
    if "rear" in lowered:
        return "rear"
    if "side" in lowered:
        return "side"
    if "lane" in lowered:
        return "lane"
    if "street" in lowered:
        return "street"
    if "rowhouse" in lowered:
        return "rowhouse"
    if "accessory" in lowered:
        return "accessory"
    return ""


def operator_signal(text: Any) -> str:
    lowered = str(text or "").lower()
    if any(marker in lowered for marker in ("minimum", "min", "at least", "not less than")):
        return ">="
    if any(marker in lowered for marker in ("maximum", "max", "up to", "not exceed")):
        return "<="
    return ""


def gis_contract_relevance(family: str, contract_families: set[str]) -> str:
    if not contract_families:
        return "unknown"
    return "in_gis_contract" if normalize_family(family) in contract_families else "outside_gis_contract"


def normalized_number(value: Any) -> str:
    text = str(value or "").replace(",", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return ""
    number = match.group(0)
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return number


def normalize_unit(value: Any) -> str:
    text = str(value or "").strip().lower().replace("²", "2")
    text = text.rstrip(".")
    if text in {"metre", "metres", "meter", "meters"}:
        return "m"
    if text in {"unit", "units"}:
        return "units"
    if text in {"storey", "storeys", "story", "stories"}:
        return "storeys"
    if text in {"space", "spaces"}:
        return "spaces"
    return text


def unit_compatible(rule_unit: str, slot_unit: str) -> bool:
    if not rule_unit or not slot_unit:
        return True
    return normalize_unit(rule_unit) == normalize_unit(slot_unit)


def source_text_overlap(left: Any, right: Any) -> int:
    left_words = normalized_words(str(left or ""))
    right_words = normalized_words(str(right or ""))
    if not left_words or not right_words:
        return 0
    return len(left_words & right_words)


def reconciliation_reason(status: str) -> str:
    return {
        "kept": "The M4 verified source slot is still verified in M5.5.",
        "duplicate_merged": "Another verified rule already covers this same source slot.",
        "unsupported_baseline": "The M4 verified rule could not be mapped to a source slot.",
        "missing_from_current": "The M4 verified source slot is no longer verified.",
    }.get(status, "Unclassified reconciliation status.")


def duplicate_rule_summary(rules: list[dict[str, Any]]) -> dict[str, Any]:
    semantic_groups = duplicate_groups(rules, source_aware=False)
    source_aware_groups = duplicate_groups(rules, source_aware=True)
    return {
        "semantic_duplicate_group_count": len(semantic_groups),
        "semantic_duplicate_rule_count": sum(len(group["rule_ids"]) - 1 for group in semantic_groups),
        "source_aware_duplicate_group_count": len(source_aware_groups),
        "source_aware_duplicate_rule_count": sum(len(group["rule_ids"]) - 1 for group in source_aware_groups),
        "semantic_duplicate_groups": semantic_groups[:25],
        "source_aware_duplicate_groups": source_aware_groups[:25],
    }


def duplicate_groups(rules: list[dict[str, Any]], *, source_aware: bool) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for rule in rules:
        groups.setdefault(rule_count_key(rule, source_aware=source_aware), []).append(rule)
    rows = []
    for key, members in groups.items():
        if len(members) <= 1:
            continue
        rows.append(
            {
                "count": len(members),
                "rule_ids": [_rule_identifier(rule) for rule in members],
                "rule_object": members[0].get("rule_object"),
                "operator": members[0].get("operator"),
                "value": members[0].get("value"),
                "unit": members[0].get("unit"),
                "applies_to": members[0].get("applies_to"),
                "constraint_scope": members[0].get("constraint_scope"),
                "condition": members[0].get("condition"),
                "source_slots": [source_slot(rule) for rule in members],
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["rule_ids"]))
    return rows


def rule_count_key(rule: dict[str, Any], *, source_aware: bool) -> tuple[str, ...]:
    source = rule.get("source") if isinstance(rule.get("source"), dict) else {}
    parts: list[Any] = [
        normalize_family(rule.get("rule_object")),
        rule.get("constraint_type"),
        rule.get("operator"),
        rule.get("value"),
        rule.get("unit"),
        rule.get("applies_to"),
        rule.get("constraint_scope"),
        rule.get("condition"),
    ]
    if source_aware:
        parts.extend(
            [
                source.get("page"),
                source.get("section"),
                source.get("table_title"),
                source.get("row_header"),
                source.get("column_header"),
                source.get("cell_value"),
                source.get("evidence_text"),
            ]
        )
    return tuple(normalized_text(part) for part in parts)


def source_slot(rule: dict[str, Any]) -> dict[str, Any]:
    source = rule.get("source") if isinstance(rule.get("source"), dict) else {}
    return {
        "page": source.get("page"),
        "section": source.get("section"),
        "table_title": source.get("table_title"),
        "row_header": source.get("row_header"),
        "column_header": source.get("column_header"),
        "cell_value": source.get("cell_value"),
    }


def _rule_identifier(rule: dict[str, Any]) -> str:
    return str(rule.get("rule_id") or rule.get("candidate_id") or rule.get("gold_id") or "<unknown>")


def family_count_rows(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for rule in rules:
        family = normalize_family(rule.get("rule_object"))
        counts[family] = counts.get(family, 0) + 1
    return [
        {"family": family, "count": count}
        for family, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def normalize_family(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def pipeline5_registry_candidates(*, root: Path, city: str) -> list[Path]:
    key = normalize_city_key(city)
    segment = upstream_city_segment(key)
    return [
        root / "outputs" / f"{key}_extraction" / "final_rule_registry.json",
        root / "outputs" / f"{segment}_extraction" / "final_rule_registry.json",
        root.parent
        / "w2025-data599-capstone-projects-green-metrics-technology"
        / "code"
        / "prototype_pipeline_5"
        / "outputs"
        / segment
        / "rule_extraction"
        / "final_rule_registry.json",
        root.parent
        / "prototype_pipeline_5"
        / "outputs"
        / segment
        / "rule_extraction"
        / "final_rule_registry.json",
        root.parent
        / "code"
        / "prototype_pipeline_5"
        / "outputs"
        / segment
        / "rule_extraction"
        / "final_rule_registry.json",
    ]


def run_benchmark(*, root: Path, city: str, output_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "benchmark/evaluate_benchmark.py",
        "--city",
        city,
        "--output-dir",
        str(output_dir),
    ]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    record = {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": tail(result.stdout),
        "stderr_tail": tail(result.stderr),
    }
    if result.returncode != 0:
        raise RuntimeError(
            "Benchmark command failed:\n"
            + " ".join(command)
            + "\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )
    return record


def build_source_registry(*, root: Path, cities: Iterable[str]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for city in cities:
        key = normalize_city_key(city)
        city_paths = resolve_city_paths(root, key)
        config = load_config(city_paths.config) if city_paths.config.exists() else {}
        manifest_path = root / "benchmark" / "source_corpus" / key / "manifest.json"
        manifest = read_json(manifest_path, {})
        configured_source_url = manifest.get("configured_source_url") or config.get("source_url")
        provenance_url = manifest.get("provenance_url") or manifest.get("source_url")
        pdf_hash = manifest.get("pdf_sha256") or manifest.get("sha256")
        weak_flags = source_weak_flags(
            configured_source_url=configured_source_url,
            provenance_url=provenance_url,
            pdf_hash=pdf_hash,
            fetched_at=manifest.get("fetched_at"),
            page_count=manifest.get("page_count"),
        )
        sources.append(
            {
                "city": key,
                "zone": manifest.get("zone") or config.get("zone"),
                "configured_source_document": manifest.get("configured_source_document")
                or config.get("source_document"),
                "configured_source_url": configured_source_url,
                "provenance_url": provenance_url,
                "fetched_at": manifest.get("fetched_at"),
                "pdf_sha256": pdf_hash,
                "page_count": manifest.get("page_count"),
                "source_chunk_count": manifest.get("source_chunk_count"),
                "rag_chunk_count": manifest.get("rag_chunk_count"),
                "table_entry_count": manifest.get("table_entry_count"),
                "numeric_clause_count": manifest.get("numeric_clause_count"),
                "rule_like_numeric_clause_count": manifest.get("rule_like_numeric_clause_count"),
                "manifest_path": str(manifest_path),
                "source_status": "strong" if not weak_flags else "review_source_provenance",
                "weak_provenance_flags": weak_flags,
            }
        )
    return {
        "created_at": now_iso(),
        "purpose": "Central M5 source registry built from existing source-corpus manifests.",
        "sources": sources,
        "source_count": len(sources),
        "weak_source_count": sum(1 for item in sources if item["weak_provenance_flags"]),
    }


def source_weak_flags(
    *,
    configured_source_url: Any,
    provenance_url: Any,
    pdf_hash: Any,
    fetched_at: Any,
    page_count: Any,
) -> list[str]:
    flags: list[str] = []
    if not str(configured_source_url or "").strip():
        flags.append("missing_configured_source_url")
    provenance = str(provenance_url or "").strip()
    if not provenance:
        flags.append("missing_provenance_url")
    if provenance.startswith("file://"):
        flags.append("local_file_provenance")
    if "/tmp/" in provenance or provenance.startswith("file:///tmp"):
        flags.append("tmp_file_provenance")
    if not str(pdf_hash or "").strip():
        flags.append("missing_pdf_sha256")
    if not str(fetched_at or "").strip():
        flags.append("missing_fetched_at")
    if not isinstance(page_count, int) or page_count <= 0:
        flags.append("missing_page_count")
    return flags


def evaluate_rag_retrieval(*, root: Path, city: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    key = normalize_city_key(city)
    gold_rules = read_json(root / "benchmark" / "gold" / (f"{key}_" + "gold" + "_rules.json"), [])
    chunks = load_rag_chunks(root=root, city=key)
    if not gold_rules or not chunks:
        return {
            "city": key,
            "top_k": top_k,
            "gold_rule_count": len(gold_rules),
            "chunk_count": len(chunks),
            "recall_at_k": 0.0,
            "context_precision_at_k": 0.0,
            "source_block_hit_rate": 0.0,
            "exact_support_hit_rate": 0.0,
            "results": [],
        }

    index = BylawIndex(chunks)
    rows = []
    for gold in gold_rules:
        query = gold_query(gold)
        hits = index.search(query, top_k=top_k)
        support = combined_support(gold, "\n".join(str(hit.get("text") or "") for hit in hits))
        source_block_id = str(gold.get("source_block_id") or "")
        source_block_hit = bool(source_block_id) and any(
            str(hit.get("chunk_id") or "") == source_block_id for hit in hits
        )
        relevant_flags = [chunk_supports_gold(hit, gold) for hit in hits]
        recall_hit = any(relevant_flags)
        row = {
            "gold_id": gold.get("gold_id"),
            "query": query,
            "source_block_id": source_block_id or None,
            "source_block_hit": source_block_hit,
            "recall_hit": recall_hit,
            "context_precision": average_precision(relevant_flags),
            "exact_support_hit": support["exact_support_hit"],
            "value_hit": support["value_hit"],
            "unit_hit": support["unit_hit"],
            "operator_hit": support["operator_hit"],
            "scope_hit": support["scope_hit"],
            "failure_reason": retrieval_failure_reason(
                hits=hits,
                source_block_id=source_block_id,
                recall_hit=recall_hit,
                support=support,
            ),
            "top_chunks": [
                {
                    "rank": rank + 1,
                    "chunk_id": hit.get("chunk_id"),
                    "section": hit.get("section"),
                    "page": hit.get("page"),
                    "score": hit.get("score"),
                    "relevant": relevant_flags[rank],
                    "text_preview": str(hit.get("text") or "")[:180],
                }
                for rank, hit in enumerate(hits)
            ],
        }
        rows.append(row)

    source_block_rows = [row for row in rows if row.get("source_block_id")]
    return {
        "city": key,
        "top_k": top_k,
        "gold_rule_count": len(gold_rules),
        "chunk_count": len(chunks),
        "recall_at_k": ratio(sum(1 for row in rows if row["recall_hit"]), len(rows)),
        "context_precision_at_k": mean(row["context_precision"] for row in rows),
        "source_block_hit_rate": ratio(
            sum(1 for row in source_block_rows if row["source_block_hit"]),
            len(source_block_rows),
        ),
        "exact_support_hit_rate": ratio(sum(1 for row in rows if row["exact_support_hit"]), len(rows)),
        "failure_reasons": sorted_counts(row["failure_reason"] for row in rows if row["failure_reason"]),
        "results": rows,
    }


def load_rag_chunks(*, root: Path, city: str) -> list[dict[str, Any]]:
    for path in (
        root / "benchmark" / "source_corpus" / city / "rag_index.json",
        root / "outputs" / f"{city}_slim_pipeline5_registry" / "bylaw_rag_index.json",
    ):
        payload = read_json(path, {})
        chunks = payload.get("chunks") if isinstance(payload, dict) else None
        if isinstance(chunks, list) and chunks:
            return chunks
    return []


def gold_query(gold: dict[str, Any]) -> str:
    parts = [
        gold.get("rule_object"),
        gold.get("constraint_type"),
        gold.get("constraint_scope"),
        gold.get("applies_to"),
        gold.get("operator"),
        gold.get("value"),
        gold.get("unit"),
        gold.get("condition"),
        *gold.get("required_evidence_terms", []),
        *gold.get("required_rule_terms", []),
    ]
    return " ".join(str(part) for part in parts if part not in (None, ""))


def chunk_supports_gold(chunk: dict[str, Any], gold: dict[str, Any]) -> bool:
    if gold.get("source_block_id") and str(chunk.get("chunk_id") or "") == str(gold["source_block_id"]):
        return True
    text = str(chunk.get("text") or "")
    support = combined_support(gold, text)
    if support["exact_support_hit"]:
        return True
    words = normalized_words(text)
    terms = required_term_words(gold.get("required_evidence_terms", []))
    required = max(1, len(terms) - 1) if terms else 0
    terms_hit = not terms or len(terms & words) >= required
    return terms_hit and support["value_hit"] and support["unit_hit"]


def required_term_words(terms: Iterable[Any]) -> set[str]:
    words: set[str] = set()
    for term in terms:
        words.update(normalized_words(term))
    return words


def combined_support(gold: dict[str, Any], text: str) -> dict[str, bool]:
    value_hit = value_visible(text, gold.get("value"))
    unit_hit = unit_visible(text, gold.get("unit")) if gold.get("unit") not in (None, "") else True
    operator_hit = operator_visible(text, gold.get("operator"), gold.get("constraint_type"))
    scope_hit = scope_visible(text, gold)
    return {
        "value_hit": value_hit,
        "unit_hit": unit_hit,
        "operator_hit": operator_hit,
        "scope_hit": scope_hit,
        "exact_support_hit": value_hit and unit_hit and operator_hit and scope_hit,
    }


def value_visible(text: str, value: Any) -> bool:
    if value in (None, ""):
        return True
    tokens = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not tokens:
        tokens = [str(value)]
    normalized_text = str(text or "").replace(",", "")
    return all(
        token_visible(normalized_text, token)
        or (token.endswith(".0") and token_visible(normalized_text, token[:-2]))
        for token in tokens
    )


def operator_visible(text: str, operator: Any, constraint_type: Any) -> bool:
    direction = canonical_operator(operator, constraint_type)
    lowered = str(text or "").lower()
    if direction in {"allowed", "eq"}:
        return True
    if direction == "max":
        return any(marker in lowered for marker in ("maximum", "max", "not exceed", "must not exceed", "<=", "≤"))
    if direction == "min":
        return any(marker in lowered for marker in ("minimum", "min", "at least", "not less than", ">=", "≥"))
    if direction == "lt":
        return "<" in lowered or "less than" in lowered
    if direction == "gt":
        return ">" in lowered or "greater than" in lowered
    return True


def scope_visible(text: str, gold: dict[str, Any]) -> bool:
    lowered_words = normalized_words(text)
    terms = required_term_words(gold.get("required_evidence_terms", []))
    applies_to_words = normalized_words(str(gold.get("applies_to") or ""))
    scope_words = normalized_words(str(gold.get("constraint_scope") or ""))
    required = {word for word in (*terms, *applies_to_words, *scope_words) if word and not word.isdigit()}
    if not required:
        return True
    needed = max(1, math.ceil(len(required) * 0.5))
    return len(required & lowered_words) >= needed


def canonical_operator(operator: Any, constraint_type: Any = None) -> str:
    text = f"{operator or ''} {constraint_type or ''}".lower()
    if any(token in text for token in ("<=", "maximum", "max", "not_exceed", "not exceed", "≤")):
        return "max"
    if any(token in text for token in (">=", "minimum", "min", "at_least", "at least", "≥")):
        return "min"
    if ">" in text:
        return "gt"
    if "<" in text:
        return "lt"
    if "allowed" in text or "permitted" in text:
        return "allowed"
    return "eq"


def retrieval_failure_reason(
    *,
    hits: list[dict[str, Any]],
    source_block_id: str,
    recall_hit: bool,
    support: dict[str, bool],
) -> str | None:
    if not hits:
        return "no_chunks_retrieved"
    if source_block_id and not recall_hit:
        return "source_block_not_retrieved"
    for field in ("value_hit", "unit_hit", "operator_hit", "scope_hit"):
        if not support[field]:
            return field.replace("_hit", "_missing")
    if not recall_hit:
        return "required_terms_missing"
    return None


def diagnose_city_run(
    *,
    benchmark_report: dict[str, Any],
    rag_report: dict[str, Any],
    source_record: dict[str, Any],
    benchmark_runtime_seconds: float,
    baseline_counts: dict[str, Any] | None = None,
    rule_count_audit: dict[str, Any] | None = None,
    slot_audit: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = benchmark_report.get("rule_metrics", {})
    proposal = benchmark_report.get("proposal_metrics", {})
    baseline_counts = baseline_counts or {}
    rule_count_audit = rule_count_audit or {}
    slot_audit = slot_audit or {}
    reconciliation = reconciliation or {}
    count_flags = rule_count_audit.get("flags") or {}
    slot_metrics = slot_audit.get("slot_metrics") or {}
    bottlenecks: list[dict[str, Any]] = []

    add_bottleneck(
        bottlenecks,
        stage="verification",
        metric="false_verified_count",
        value=metrics.get("false_verified_count", 0),
        target=0,
        severity=100,
        recommendation="Tighten verifier gates before improving recall.",
        active=metrics.get("false_verified_count", 0) != 0,
    )
    add_bottleneck(
        bottlenecks,
        stage="compliance",
        metric="false_approval_count",
        value=proposal.get("false_approval_count", 0),
        target=0,
        severity=100,
        recommendation="Force uncertain proposal checks to needs_review.",
        active=proposal.get("false_approval_count", 0) != 0,
    )
    add_bottleneck(
        bottlenecks,
        stage="verification",
        metric="verified_source_support_failed_count",
        value=metrics.get("verified_source_support_failed_count", 0),
        target=0,
        severity=95,
        recommendation="Repair evidence anchoring before allowing verification.",
        active=metrics.get("verified_source_support_failed_count", 0) != 0,
    )
    current_verified = metrics.get("verified_rule_count")
    current_effective_verified = (rule_count_audit.get("output_counts") or {}).get(
        "effective_verified_rule_count",
        current_verified,
    )
    baseline_verified = baseline_counts.get("verified_rule_count")
    baseline_effective_verified = baseline_counts.get("effective_verified_rule_count", baseline_verified)
    effective_verified_count_delta = (
        current_effective_verified - baseline_effective_verified
        if isinstance(current_effective_verified, int) and isinstance(baseline_effective_verified, int)
        else None
    )
    add_bottleneck(
        bottlenecks,
        stage="measurement_contract",
        metric="effective_verified_rule_count_delta_from_m4",
        value=effective_verified_count_delta,
        target=">= 0",
        severity=92,
        recommendation="Do not accept M5 runs that silently reduce deduplicated verified-rule volume below the native M4 baseline.",
        active=isinstance(effective_verified_count_delta, int) and effective_verified_count_delta < 0,
        current_verified_rule_count=current_verified,
        current_effective_verified_rule_count=current_effective_verified,
        m4_verified_rule_count=baseline_verified,
        m4_effective_verified_rule_count=baseline_effective_verified,
        m4_baseline_output_dir=baseline_counts.get("baseline_output_dir"),
    )
    add_bottleneck(
        bottlenecks,
        stage="oververification",
        metric="verified_count_exceeds_loose_source_ceiling",
        value=metrics.get("verified_rule_count"),
        target=f"<= {((rule_count_audit.get('source_counts') or {}).get('loose_source_rule_slot_ceiling'))}",
        severity=94,
        recommendation="Review source-derived rule slots before accepting more verified rules.",
        active=bool(count_flags.get("verified_count_exceeds_loose_source_ceiling")) and not slot_metrics,
    )
    add_bottleneck(
        bottlenecks,
        stage="deduplication",
        metric="verified_exact_duplicate_count",
        value=count_flags.get("verified_exact_duplicate_count", 0),
        target=0,
        severity=93,
        recommendation="Deduplicate exact source-aware verified rules before claiming count improvements.",
        active=int(count_flags.get("verified_exact_duplicate_count") or 0) > 0 and not slot_metrics,
    )
    add_bottleneck(
        bottlenecks,
        stage="slot_contract",
        metric="verified_slot_mapping_rate",
        value=slot_metrics.get("verified_slot_mapping_rate"),
        target=1.0,
        severity=96,
        recommendation="Every verified rule must map to exactly one source-derived rule slot.",
        active=slot_metrics.get("verified_slot_mapping_rate", 1.0) != 1.0,
    )
    add_bottleneck(
        bottlenecks,
        stage="slot_contract",
        metric="unsupported_verified_rule_count",
        value=slot_metrics.get("unsupported_verified_rule_count", 0),
        target=0,
        severity=96,
        recommendation="Move unsupported verified rows back to review or repair their source-slot mapping.",
        active=int(slot_metrics.get("unsupported_verified_rule_count") or 0) > 0,
    )
    add_bottleneck(
        bottlenecks,
        stage="slot_contract",
        metric="duplicate_verified_slot_count",
        value=slot_metrics.get("duplicate_verified_slot_count", 0),
        target=0,
        severity=91,
        recommendation="Merge duplicate verified rows by source slot before claiming verified-count gains.",
        active=int(slot_metrics.get("duplicate_verified_slot_count") or 0) > 0,
    )
    add_bottleneck(
        bottlenecks,
        stage="measurement_contract",
        metric="effective_verified_slot_count_delta_from_m4",
        value=reconciliation.get("effective_verified_slot_count_delta"),
        target=">= 0",
        severity=91,
        recommendation="Do not accept M5.5 runs that silently reduce unique verified source slots below M4.",
        active=isinstance(reconciliation.get("effective_verified_slot_count_delta"), int)
        and reconciliation["effective_verified_slot_count_delta"] < 0,
    )
    add_bottleneck(
        bottlenecks,
        stage="measurement_contract",
        metric="scored_verified_coverage",
        value=slot_metrics.get("scored_verified_coverage"),
        target=">= 0.50",
        severity=35,
        recommendation=(
            "Grow verified coverage of in-contract, recognized-family source slots "
            "(the M5.6 scored denominator), not the raw numeric-token ceiling."
        ),
        active=(
            isinstance(slot_metrics.get("scored_verified_coverage"), (int, float))
            and slot_metrics.get("scored_verified_coverage", 1.0) < 0.50
            and int(slot_metrics.get("scored_total_slots") or 0) > 0
        ),
        scored_total_slots=slot_metrics.get("scored_total_slots"),
        scored_verified_slot_count=slot_metrics.get("scored_verified_slot_count"),
        scored_missed_slot_count=slot_metrics.get("scored_missed_slot_count"),
    )
    quality_gates = benchmark_report.get("quality_gates", {})
    failed_quality_gates = [
        name
        for name, passed in (quality_gates.get("gates") or {}).items()
        if not passed
    ]
    add_bottleneck(
        bottlenecks,
        stage="benchmark_contract",
        metric="quality_gates",
        value=failed_quality_gates,
        target=[],
        severity=90,
        recommendation="Fix verifier/proposal behavior or update stale benchmark expectations before accepting this run.",
        active=bool(failed_quality_gates),
    )
    add_bottleneck(
        bottlenecks,
        stage="retrieval",
        metric="rag_recall_at_6",
        value=rag_report.get("recall_at_k", 0.0),
        target=0.95,
        severity=80,
        recommendation="Improve source-corpus retrieval, query expansion, or parent-section chunking.",
        active=rag_report.get("recall_at_k", 0.0) < 0.95,
    )
    add_bottleneck(
        bottlenecks,
        stage="extraction",
        metric="extraction_coverage_recall",
        value=metrics.get("extraction_coverage_recall", 0.0),
        target=0.95,
        severity=78,
        recommendation=(
            "Improve extraction coverage for gold rule families missed by every surfaced output bucket; "
            "do not use city-specific shortcuts."
        ),
        active=metrics.get("extraction_coverage_recall", 0.0) < 0.95,
    )
    add_bottleneck(
        bottlenecks,
        stage="extraction_diagnostics",
        metric="raw_candidate_artifact_recall",
        value=metrics.get("raw_candidate_artifact_recall", metrics.get("candidate_recall", 0.0)),
        target="diagnostic only",
        severity=25,
        recommendation=(
            "Raw candidate artifacts do not include rules surfaced directly into review/rejected/not_used. "
            "Use release_candidate_recall/extraction_coverage_recall for the M6 acceptance gate."
        ),
        active=(
            metrics.get("extraction_coverage_recall", 1.0) >= 0.95
            and metrics.get("raw_candidate_artifact_recall", metrics.get("candidate_recall", 1.0)) < 0.90
        ),
    )
    add_bottleneck(
        bottlenecks,
        stage="overextraction",
        metric="candidate_count_exceeds_loose_source_ceiling",
        value=metrics.get("candidate_rule_count"),
        target=f"<= {((rule_count_audit.get('source_counts') or {}).get('loose_source_rule_slot_ceiling'))}",
        severity=74,
        recommendation="Reduce candidate noise or split traceability-only records before verifier tuning.",
        active=bool(count_flags.get("candidate_count_exceeds_loose_source_ceiling")),
    )
    evidence_quality = metrics.get("evidence_quality", {})
    add_bottleneck(
        bottlenecks,
        stage="evidence_quality",
        metric="candidate_value_grounding_rate",
        value=evidence_quality.get("candidate_value_grounding_rate", 0.0),
        target=0.95,
        severity=70,
        recommendation="Improve evidence text/source-context anchoring so candidate values are visible in cited evidence.",
        active=evidence_quality.get("candidate_value_grounding_rate", 0.0) < 0.95,
    )
    proof = metrics.get("proof_metrics", {})
    table_count = int(proof.get("table_proof_count") or 0)
    table_complete = int(proof.get("table_proof_complete_count") or 0)
    table_completion = ratio(table_complete, table_count) if table_count else 1.0
    add_bottleneck(
        bottlenecks,
        stage="verification",
        metric="table_proof_completion_rate",
        value=table_completion,
        target=0.50,
        severity=68,
        recommendation="Focus table proof logic on row/column/cell binding and condition preservation.",
        active=table_count > 0 and table_completion < 0.50,
    )
    add_bottleneck(
        bottlenecks,
        stage="source_registry",
        metric="weak_provenance_flags",
        value=len(source_record.get("weak_provenance_flags", [])),
        target=0,
        severity=45,
        recommendation="Replace temporary/local provenance with official source URL, fetch timestamp, and PDF hash.",
        active=bool(source_record.get("weak_provenance_flags")),
        flags=source_record.get("weak_provenance_flags", []),
    )
    add_bottleneck(
        bottlenecks,
        stage="runtime",
        metric="benchmark_runtime_seconds",
        value=benchmark_runtime_seconds,
        target=M5_RUNTIME_LIMIT_SECONDS,
        severity=40,
        recommendation="Profile the slowest benchmark stage before adding more cities.",
        active=benchmark_runtime_seconds > M5_RUNTIME_LIMIT_SECONDS,
    )

    bottlenecks.sort(key=lambda item: (-item["severity"], item["stage"], item["metric"]))
    return {
        "created_at": now_iso(),
        "city": benchmark_report.get("benchmark"),
        "hard_gates": hard_gates(
            benchmark_report=benchmark_report,
            benchmark_runtime_seconds=benchmark_runtime_seconds,
            baseline_counts=baseline_counts,
            rule_count_audit=rule_count_audit,
            slot_audit=slot_audit,
            reconciliation=reconciliation,
        ),
        "bottlenecks": bottlenecks,
        "next_recommended_action": bottlenecks[0]["recommendation"] if bottlenecks else "No active M5 bottleneck.",
    }


def add_bottleneck(
    rows: list[dict[str, Any]],
    *,
    stage: str,
    metric: str,
    value: Any,
    target: Any,
    severity: int,
    recommendation: str,
    active: bool,
    **extra: Any,
) -> None:
    if not active:
        return
    rows.append(
        {
            "stage": stage,
            "metric": metric,
            "value": value,
            "target": target,
            "severity": severity,
            "recommendation": recommendation,
            **extra,
        }
    )


def hard_gates(
    *,
    benchmark_report: dict[str, Any],
    benchmark_runtime_seconds: float,
    baseline_counts: dict[str, Any] | None = None,
    rule_count_audit: dict[str, Any] | None = None,
    slot_audit: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = benchmark_report.get("rule_metrics", {})
    proposal = benchmark_report.get("proposal_metrics", {})
    quality_gates = benchmark_report.get("quality_gates", {})
    benchmark_quality_passed = bool(quality_gates.get("passed", True))
    baseline_counts = baseline_counts or {}
    rule_count_audit = rule_count_audit or {}
    slot_audit = slot_audit or {}
    reconciliation = reconciliation or {}
    count_flags = rule_count_audit.get("flags") or {}
    slot_metrics = slot_audit.get("slot_metrics") or {}
    slot_authority_available = bool(slot_metrics)
    current_verified = metrics.get("verified_rule_count")
    current_effective_verified = (rule_count_audit.get("output_counts") or {}).get(
        "effective_verified_rule_count",
        current_verified,
    )
    baseline_verified = baseline_counts.get("verified_rule_count")
    baseline_effective_verified = baseline_counts.get("effective_verified_rule_count", baseline_verified)
    effective_verified_count_not_regressed = not (
        isinstance(current_effective_verified, int)
        and isinstance(baseline_effective_verified, int)
        and current_effective_verified < baseline_effective_verified
    )
    slot_delta = reconciliation.get("effective_verified_slot_count_delta")
    effective_verified_slot_count_not_regressed = not (
        isinstance(slot_delta, int) and slot_delta < 0
    )
    gates = {
        "false_verified_is_0": metrics.get("false_verified_count", 0) == 0,
        "false_approval_is_0": proposal.get("false_approval_count", 0) == 0,
        "verified_precision_is_1": metrics.get("verified_precision") == 1.0,
        "verified_source_support_failures_is_0": metrics.get("verified_source_support_failed_count", 0) == 0,
        "effective_verified_rule_count_not_below_m4_baseline": effective_verified_count_not_regressed,
        "verified_rule_count_not_above_loose_source_ceiling": (
            True
            if slot_authority_available
            else not bool(count_flags.get("verified_count_exceeds_loose_source_ceiling"))
        ),
        "verified_exact_duplicate_count_is_0": (
            True
            if slot_authority_available
            else int(count_flags.get("verified_exact_duplicate_count") or 0) == 0
        ),
        "verified_slot_mapping_rate_is_1": slot_metrics.get("verified_slot_mapping_rate", 1.0) == 1.0,
        "unsupported_verified_rule_count_is_0": int(slot_metrics.get("unsupported_verified_rule_count") or 0) == 0,
        "duplicate_verified_slot_count_is_0": int(slot_metrics.get("duplicate_verified_slot_count") or 0) == 0,
        "effective_verified_slot_count_not_below_m4_baseline": effective_verified_slot_count_not_regressed,
        "benchmark_quality_gates_passed": benchmark_quality_passed,
        "runtime_under_300_seconds": benchmark_runtime_seconds <= M5_RUNTIME_LIMIT_SECONDS,
    }
    return {"passed": all(gates.values()), "gates": gates}


def make_scoreboard_row(
    *,
    spec: M5RunSpec,
    benchmark_report: dict[str, Any],
    rag_report: dict[str, Any],
    diagnosis: dict[str, Any],
    benchmark_runtime_seconds: float,
    command_record: dict[str, Any],
    baseline_counts: dict[str, Any] | None = None,
    rule_count_audit: dict[str, Any] | None = None,
    slot_audit: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = benchmark_report.get("rule_metrics", {})
    proposal = benchmark_report.get("proposal_metrics", {})
    hard = diagnosis["hard_gates"]
    baseline_counts = baseline_counts or {}
    rule_count_audit = rule_count_audit or {}
    slot_audit = slot_audit or {}
    reconciliation = reconciliation or {}
    source_counts = rule_count_audit.get("source_counts") or {}
    output_counts = rule_count_audit.get("output_counts") or {}
    count_flags = rule_count_audit.get("flags") or {}
    slot_metrics = slot_audit.get("slot_metrics") or {}
    current_verified = metrics.get("verified_rule_count")
    baseline_verified = baseline_counts.get("verified_rule_count")
    current_effective_verified = output_counts.get("effective_verified_rule_count", current_verified)
    baseline_effective_verified = baseline_counts.get("effective_verified_rule_count", baseline_verified)
    verified_count_delta = (
        current_verified - baseline_verified
        if isinstance(current_verified, int) and isinstance(baseline_verified, int)
        else None
    )
    effective_verified_count_delta = (
        current_effective_verified - baseline_effective_verified
        if isinstance(current_effective_verified, int) and isinstance(baseline_effective_verified, int)
        else None
    )
    return {
        "run_id": spec.run_id,
        "created_at": now_iso(),
        "city": spec.city,
        "model": spec.model,
        "changed_component": spec.changed_component,
        "source_output_dir": str(spec.source_output_dir),
        "m5_output_dir": str(spec.output_dir),
        "m4_baseline_output_dir": baseline_counts.get("baseline_output_dir"),
        "m4_baseline_available": baseline_counts.get("baseline_available"),
        "m4_baseline_verified_rule_count": baseline_verified,
        "m4_baseline_verified_exact_duplicate_count": baseline_counts.get("verified_exact_duplicate_count"),
        "m4_baseline_effective_verified_rule_count": baseline_effective_verified,
        "verified_rule_count_delta_from_m4": verified_count_delta,
        "effective_verified_rule_count": current_effective_verified,
        "effective_verified_rule_count_delta_from_m4": effective_verified_count_delta,
        "loose_source_rule_slot_ceiling": source_counts.get("loose_source_rule_slot_ceiling"),
        "rule_like_numeric_clause_count": source_counts.get("rule_like_numeric_clause_count"),
        "table_cell_count": source_counts.get("table_cell_count"),
        "candidate_count_exceeds_loose_source_ceiling": count_flags.get(
            "candidate_count_exceeds_loose_source_ceiling"
        ),
        "verified_count_exceeds_loose_source_ceiling": count_flags.get(
            "verified_count_exceeds_loose_source_ceiling"
        ),
        "verified_exact_duplicate_count": count_flags.get("verified_exact_duplicate_count"),
        "verified_out_of_contract_count": count_flags.get("verified_out_of_contract_count"),
        "m55_total_rule_slots": slot_metrics.get("total_rule_slots"),
        "m55_effective_verified_slot_count": slot_metrics.get("effective_verified_slot_count"),
        "m55_verified_slot_mapping_rate": slot_metrics.get("verified_slot_mapping_rate"),
        "m55_unsupported_verified_rule_count": slot_metrics.get("unsupported_verified_rule_count"),
        "m55_duplicate_verified_slot_count": slot_metrics.get("duplicate_verified_slot_count"),
        "m55_duplicate_merged_count": slot_metrics.get("duplicate_merged_count"),
        "m55_missed_slot_count": slot_metrics.get("missed_slot_count"),
        "m55_effective_verified_slot_count_delta_from_m4": reconciliation.get(
            "effective_verified_slot_count_delta"
        ),
        "gold_rule_count": metrics.get("gold_rule_count"),
        "candidate_rule_count": metrics.get("candidate_rule_count"),
        "verified_rule_count": metrics.get("verified_rule_count"),
        "review_rule_count": metrics.get("review_rule_count"),
        "rejected_rule_count": metrics.get("rejected_rule_count"),
        "not_used_rule_count": metrics.get("not_used_rule_count"),
        "candidate_recall": metrics.get("candidate_recall"),
        "raw_candidate_artifact_recall": metrics.get("raw_candidate_artifact_recall"),
        "release_candidate_recall": metrics.get("release_candidate_recall"),
        "extraction_coverage_recall": metrics.get("extraction_coverage_recall"),
        "verified_precision": metrics.get("verified_precision"),
        "false_verified_count": metrics.get("false_verified_count"),
        "false_approval_count": proposal.get("false_approval_count"),
        "verified_source_support_failed_count": metrics.get("verified_source_support_failed_count"),
        "verified_or_review_recall": metrics.get("verified_or_review_recall"),
        "rag_recall_at_6": rag_report.get("recall_at_k"),
        "rag_context_precision_at_6": rag_report.get("context_precision_at_k"),
        "rag_exact_support_hit_rate": rag_report.get("exact_support_hit_rate"),
        "benchmark_runtime_seconds": benchmark_runtime_seconds,
        "hard_gates": hard,
        "accepted": hard["passed"],
        "top_bottleneck_stage": (
            diagnosis["bottlenecks"][0]["stage"] if diagnosis.get("bottlenecks") else None
        ),
        "top_bottleneck_metric": (
            diagnosis["bottlenecks"][0]["metric"] if diagnosis.get("bottlenecks") else None
        ),
        "command": command_record,
    }


def make_m55_scoreboard_row(
    scoreboard_row: dict[str, Any],
    slot_audit: dict[str, Any],
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    slot_metrics = slot_audit.get("slot_metrics") or {}
    return {
        "run_id": scoreboard_row.get("run_id"),
        "created_at": now_iso(),
        "city": scoreboard_row.get("city"),
        "model": scoreboard_row.get("model"),
        "changed_component": scoreboard_row.get("changed_component"),
        "accepted": scoreboard_row.get("accepted"),
        "total_rule_slots": slot_metrics.get("total_rule_slots"),
        "effective_verified_slot_count": slot_metrics.get("effective_verified_slot_count"),
        "verified_slot_mapping_rate": slot_metrics.get("verified_slot_mapping_rate"),
        "unsupported_verified_rule_count": slot_metrics.get("unsupported_verified_rule_count"),
        "duplicate_verified_slot_count": slot_metrics.get("duplicate_verified_slot_count"),
        "duplicate_merged_count": slot_metrics.get("duplicate_merged_count"),
        "review_slot_count": slot_metrics.get("review_slot_count"),
        "candidate_only_slot_count": slot_metrics.get("candidate_only_slot_count"),
        "missed_slot_count": slot_metrics.get("missed_slot_count"),
        # M5.6 honest headline denominator (scored, de-circularized, deduped).
        "scored_total_slots": slot_metrics.get("scored_total_slots"),
        "distinct_scored_legal_slot_count": slot_metrics.get("distinct_scored_legal_slot_count"),
        "scored_verified_slot_count": slot_metrics.get("scored_verified_slot_count"),
        "scored_missed_slot_count": slot_metrics.get("scored_missed_slot_count"),
        "scored_verified_coverage": slot_metrics.get("scored_verified_coverage"),
        "scored_active_coverage": slot_metrics.get("scored_active_coverage"),
        "observed_supplement_slot_count": slot_metrics.get("observed_supplement_slot_count"),
        "slot_confusion_matrix": slot_audit.get("slot_confusion_matrix") or {},
        "scored_slot_confusion_matrix": slot_audit.get("scored_slot_confusion_matrix") or {},
        "baseline_effective_verified_slot_count": reconciliation.get(
            "baseline_effective_verified_slot_count"
        ),
        "effective_verified_slot_count_delta_from_m4": reconciliation.get(
            "effective_verified_slot_count_delta"
        ),
        "frontier_shadow_lane_count": len(slot_audit.get("frontier_shadow_lanes") or []),
        "top_bottleneck_stage": scoreboard_row.get("top_bottleneck_stage"),
        "top_bottleneck_metric": scoreboard_row.get("top_bottleneck_metric"),
    }


def average_precision(relevance_flags: list[bool]) -> float:
    if not relevance_flags:
        return 0.0
    precisions = []
    relevant_count = 0
    for rank, relevant in enumerate(relevance_flags, start=1):
        if relevant:
            relevant_count += 1
            precisions.append(relevant_count / rank)
    return round(sum(precisions) / len(precisions), 3) if precisions else 0.0


def normalized_words(text: Any) -> set[str]:
    return {normalize_token(token) for token in re.findall(r"[a-z0-9]+", str(text or "").lower())}


def normalize_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def sorted_counts(values: Iterable[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [
        {"reason": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return round(sum(items) / len(items), 3) if items else 0.0


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def tail(text: str, limit: int = 3000) -> str:
    return text[-limit:] if len(text) > limit else text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
