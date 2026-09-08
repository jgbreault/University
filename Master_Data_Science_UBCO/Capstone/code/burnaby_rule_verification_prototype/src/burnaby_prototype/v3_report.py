"""Reviewer-ready V3 gap reports.

The report reads benchmark outputs after verification. Gold-derived missed-rule
fields are evaluation-only and are never used by V3 discovery or extraction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_v3_gap_report(
    *,
    city: str,
    output_dir: Path,
    source_summary: dict[str, Any],
    v2_reference_dir: Path | None = None,
    pdf_page_count: int | None = None,
) -> dict[str, Any]:
    benchmark = _read_json(output_dir / "benchmark_report.json", {})
    metrics = benchmark.get("rule_metrics", {})
    summary = _read_json(output_dir / "extraction_summary.json", {})
    cost = _read_json(output_dir / "model_cost_report.json", {})
    slim = _read_json(output_dir / "slim_summary.json", {})
    v2_metrics = {}
    v2_summary = {}
    m4_source = source_summary.get("m4_source_corpus") or {}
    discovery_mode = source_summary.get("discovery_mode") or "v3"
    if v2_reference_dir:
        v2_benchmark = _read_json(v2_reference_dir / "benchmark_report.json", {})
        v2_metrics = v2_benchmark.get("rule_metrics", {})
        v2_summary = _read_json(v2_reference_dir / "slim_summary.json", {})

    report = {
        "report": "v3_gap_report",
        "city": city,
        "pipeline": f"native_{discovery_mode}_rag_llm",
        "discovery_mode": discovery_mode,
        "advisory_gold_fields": True,
        "safety_contract": f"{str(discovery_mode).upper()} extracts and repairs evidence packs; deterministic verifier decides.",
        "pdf_page_count": pdf_page_count,
        "source_chunk_count": source_summary.get("source_chunk_count"),
        "pack_count": source_summary.get("evidence_pack_count"),
        "m4_source_corpus": {
            "path": m4_source.get("path"),
            "corpus_version": m4_source.get("corpus_version"),
            "numeric_clause_count": m4_source.get("numeric_clause_count"),
            "rule_like_numeric_clause_count": m4_source.get("rule_like_numeric_clause_count"),
            "selected_rule_like_numeric_coverage": m4_source.get("selected_rule_like_numeric_coverage"),
        },
        "model": summary.get("model"),
        "candidate_rule_count": metrics.get("candidate_rule_count", summary.get("candidate_rule_count")),
        "verified_rule_count": metrics.get("verified_rule_count", slim.get("verified_rule_count")),
        "review_rule_count": metrics.get("review_rule_count", slim.get("review_rule_count")),
        "rejected_rule_count": metrics.get("rejected_rule_count", slim.get("rejected_rule_count")),
        "not_used_rule_count": metrics.get("not_used_rule_count", slim.get("not_used_rule_count")),
        "false_verified_count": metrics.get("false_verified_count"),
        "verified_source_support_failed_count": metrics.get("verified_source_support_failed_count"),
        "verified_precision": metrics.get("verified_precision"),
        "verified_or_review_recall": metrics.get("verified_or_review_recall"),
        "extraction_coverage_recall": metrics.get("extraction_coverage_recall"),
        "verifier_retention_rate": metrics.get("verifier_retention_rate"),
        "top_support_gaps": metrics.get("top_review_reasons", []),
        "estimated_cost_usd": cost.get("estimated_cost_usd"),
        "latency_ms": cost.get("latency_ms"),
        "extraction_error_count": summary.get("extraction_error_count", cost.get("extraction_error_count")),
        "extraction_errors": cost.get("extraction_errors", [])[:10],
        "missed_rules": {
            "unextracted_gold_rule_ids": metrics.get("unextracted_gold_rule_ids", []),
            "verifier_rejected_gold_rule_ids": metrics.get("verifier_rejected_gold_rule_ids", []),
            "not_used_gold_rule_ids": metrics.get("not_used_gold_rule_ids", []),
            "missed_verified_or_review_gold_rule_ids": metrics.get("missed_verified_or_review_gold_rule_ids", []),
        },
        "v2_comparison": _comparison(metrics, summary, v2_metrics, v2_summary),
        "interpretation": _interpretation(metrics, v2_metrics, discovery_mode),
    }
    return report


def write_v3_gap_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "v3_gap_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "v3_gap_report.md").write_text(render_v3_gap_markdown(report), encoding="utf-8")


def render_v3_gap_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {str(report.get('discovery_mode') or 'v3').upper()} Gap Report - {report.get('city')}",
        "",
        report.get("safety_contract", ""),
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| PDF pages | {report.get('pdf_page_count')} |",
        f"| Source chunks | {report.get('source_chunk_count')} |",
        f"| Evidence packs | {report.get('pack_count')} |",
        f"| M4 numeric clauses | {(report.get('m4_source_corpus') or {}).get('numeric_clause_count')} |",
        f"| M4 rule-like numeric clauses | {(report.get('m4_source_corpus') or {}).get('rule_like_numeric_clause_count')} |",
        f"| M4 selected rule-like numeric coverage | {_fmt((report.get('m4_source_corpus') or {}).get('selected_rule_like_numeric_coverage'))} |",
        f"| Candidates | {report.get('candidate_rule_count')} |",
        f"| Verified | {report.get('verified_rule_count')} |",
        f"| Review | {report.get('review_rule_count')} |",
        f"| Rejected | {report.get('rejected_rule_count')} |",
        f"| Not used | {report.get('not_used_rule_count')} |",
        f"| False verified | {report.get('false_verified_count')} |",
        f"| Verified/review recall | {_fmt(report.get('verified_or_review_recall'))} |",
        f"| Extraction coverage recall | {_fmt(report.get('extraction_coverage_recall'))} |",
        f"| Verifier retention rate | {_fmt(report.get('verifier_retention_rate'))} |",
        f"| Estimated cost | {report.get('estimated_cost_usd')} |",
        f"| Latency ms | {report.get('latency_ms')} |",
        f"| Extraction errors | {report.get('extraction_error_count')} |",
        "",
        "## V2 Comparison",
        "",
        "| Metric | Delta |",
        "|---|---:|",
    ]
    for key, value in (report.get("v2_comparison") or {}).items():
        lines.append(f"| {key} | {_signed(value)} |")
    lines.extend(["", "## Top Support Gaps", ""])
    gaps = report.get("top_support_gaps") or []
    if not gaps:
        lines.append("No support gaps reported.")
    for gap in gaps[:10]:
        lines.append(f"- {gap.get('reason') or gap.get('name')}: {gap.get('count')}")
    missed = report.get("missed_rules") or {}
    lines.extend(["", "## Missed Rule Categories", ""])
    for key, values in missed.items():
        lines.append(f"- {key}: {len(values or [])}")
    lines.extend(["", "## Interpretation", ""])
    for note in report.get("interpretation") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _comparison(
    metrics: dict[str, Any],
    summary: dict[str, Any],
    v2_metrics: dict[str, Any],
    v2_summary: dict[str, Any],
) -> dict[str, Any]:
    if not v2_metrics and not v2_summary:
        return {}
    return {
        "candidate_rule_count": _delta(
            metrics.get("candidate_rule_count", summary.get("candidate_rule_count")),
            v2_metrics.get("candidate_rule_count", v2_summary.get("candidate_rule_count")),
        ),
        "verified_rule_count": _delta(metrics.get("verified_rule_count"), v2_metrics.get("verified_rule_count")),
        "review_rule_count": _delta(metrics.get("review_rule_count"), v2_metrics.get("review_rule_count")),
        "false_verified_count": _delta(metrics.get("false_verified_count"), v2_metrics.get("false_verified_count")),
        "verified_or_review_recall": _delta(
            metrics.get("verified_or_review_recall"),
            v2_metrics.get("verified_or_review_recall"),
        ),
        "extraction_coverage_recall": _delta(
            metrics.get("extraction_coverage_recall"),
            v2_metrics.get("extraction_coverage_recall"),
        ),
    }


def _interpretation(metrics: dict[str, Any], v2_metrics: dict[str, Any], discovery_mode: str) -> list[str]:
    notes = []
    label = str(discovery_mode or "v3").upper()
    if int(metrics.get("false_verified_count") or 0) == 0:
        notes.append(f"{label} preserved the false_verified_count = 0 safety target for this city.")
    else:
        notes.append(f"{label} is unsafe for this city because at least one false verified rule was found.")
    if v2_metrics:
        current = metrics.get("verified_or_review_recall")
        previous = v2_metrics.get("verified_or_review_recall")
        if isinstance(current, (int, float)) and isinstance(previous, (int, float)):
            if current > previous:
                notes.append(f"{label} improved verified-or-review recall versus V2.")
            elif current == previous:
                notes.append(f"{label} matched V2 verified-or-review recall.")
            else:
                notes.append(f"{label} reduced verified-or-review recall versus V2; keep it experimental.")
    notes.append(f"Missed-rule IDs are evaluation-only and are not used by {label} runtime extraction.")
    return notes


def _delta(current: Any, previous: Any) -> float | int | None:
    if isinstance(current, (int, float)) and isinstance(previous, (int, float)):
        return current - previous
    return None


def _signed(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:+.3f}"
    if isinstance(value, int):
        return f"{value:+d}"
    return ""


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if value is None:
        return ""
    return str(value)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
