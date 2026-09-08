"""Merge the text and table streams into the Pipeline-5 registry contract.

Emits ``final_rule_registry.json`` shaped exactly like Pipeline 5's deliverable
(top-level ``rules`` array; per-rule fields including rule_object,
constraint_type, operator, value, unit, condition, evidence_text, source_id,
batch_id, rule_id/merged_rule_id, applies_to, merged_rule_ids, dedup_status,
review_required/review_reasons) so ``zihao_adapter.adapt_pipeline5_registry``
consumes it with zero verifier changes. The contract carries evidence inline
(``evidence_text``); an ``evidence_units.json`` sidecar additionally records
ALL clauses (candidate-bearing or not) for gold-set curation and diagnosis.

source_stream values: ``local_text_block`` and ``local_table_image``.
Legacy diagnostic helper only — native M4 is the current product extraction.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _source_fingerprint(source_pdf: str | None) -> tuple[str | None, str | None]:
    """Basename + sha256 of the source PDF (content identity, not path/time)."""
    if not source_pdf:
        return None, None
    path = Path(source_pdf)
    digest = None
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path.name, digest

from .table_stream import derive_table_candidates


def build_registry(
    city: str,
    text_result: dict[str, Any],
    table_result: dict[str, Any] | None = None,
    *,
    source_pdf: str | None = None,
    source_pages: str | None = None,
) -> dict[str, Any]:
    """Assemble the registry dict (pure; no IO) from the two streams."""
    table_result = table_result or {"available": False, "tables": [], "model": None}
    table_candidates = derive_table_candidates(table_result.get("tables", []), city)
    raw_candidates = list(text_result.get("candidates", [])) + table_candidates

    rules: list[dict[str, Any]] = []
    for index, candidate in enumerate(raw_candidates, start=1):
        rules.append(_rule_record(candidate, index))

    deduped = _dedupe_rules(rules)
    for index, rule in enumerate(deduped, start=1):
        rule["merged_rule_id"] = f"local_merged_rule_{index:04d}"

    # Provenance is CONTENT-keyed, never time- or path-keyed: identical input
    # bytes must produce byte-identical outputs (the reproducibility property
    # the whole project leans on — a wall-clock timestamp or an absolute /tmp
    # path here broke `diff`-based reproduction; caught by external review).
    source_name, source_sha = _source_fingerprint(source_pdf)
    return {
        "pipeline": "internal_extraction_helper",
        "contract": "prototype_pipeline_5/final_rule_registry",
        "model": table_result.get("model"),
        "city": city,
        "source_pdf": source_name,
        "source_pdf_sha256": source_sha,
        # 1-based inclusive page range of the FULL source this run processed
        # (None = whole document). Evidence units carry full-PDF page numbers.
        "source_pages": source_pages,
        "raw_rule_count": len(rules),
        "deduplicated_rule_count": len(deduped),
        "final_rule_count": len(deduped),
        "rules": deduped,
    }


def write_registry_outputs(
    output_dir: str | Path,
    city: str,
    text_result: dict[str, Any],
    table_result: dict[str, Any] | None = None,
    *,
    source_pdf: str | None = None,
    source_pages: str | None = None,
) -> dict[str, Any]:
    """Write final_rule_registry.json + evidence_units.json + extraction_summary.json."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    registry = build_registry(
        city, text_result, table_result, source_pdf=source_pdf, source_pages=source_pages
    )
    evidence_units = build_evidence_units(city, text_result, table_result or {})
    summary = {
        "city": city,
        "source_pdf": registry["source_pdf"],
        "source_pdf_sha256": registry["source_pdf_sha256"],
        "source_pages": registry["source_pages"],
        "table_stream_available": bool((table_result or {}).get("available")),
        "table_stream_reason": (table_result or {}).get("reason"),
        "counts": {
            "clauses": len(text_result.get("clauses", [])),
            "text_candidates": len(text_result.get("candidates", [])),
            "tables": len((table_result or {}).get("tables", [])),
            "table_candidates": sum(
                1 for rule in registry["rules"] if rule["source_stream"] == "local_table_image"
            ),
            "rules_raw": registry["raw_rule_count"],
            "rules_final": registry["final_rule_count"],
            "evidence_units": len(evidence_units),
        },
        "rules_by_stream": _count_by(registry["rules"], "source_stream"),
        "rules_by_object": _count_by(registry["rules"], "rule_object"),
        "sections_seen": text_result.get("sections_seen", []),
    }

    _write_json(out / "final_rule_registry.json", registry)
    _write_json(out / "evidence_units.json", evidence_units)
    _write_json(out / "extraction_summary.json", summary)
    return {
        "registry_path": str(out / "final_rule_registry.json"),
        "evidence_units_path": str(out / "evidence_units.json"),
        "summary_path": str(out / "extraction_summary.json"),
        "registry": registry,
        "summary": summary,
    }


def build_evidence_units(
    city: str, text_result: dict[str, Any], table_result: dict[str, Any]
) -> list[dict[str, Any]]:
    """ALL clauses (id scheme <city>_<section>_<seq>) plus structured table rows."""
    units: list[dict[str, Any]] = [
        {
            "evidence_id": clause["evidence_id"],
            "section": clause["section"],
            "page": clause["page"],
            "evidence_text": clause["text"],
            "source_stream": "local_text_block",
        }
        for clause in text_result.get("clauses", [])
    ]
    for table in table_result.get("tables", []):
        title = str(table.get("table_title") or "")
        page = int(table.get("page") or 0)
        table_index = int(table.get("table_index") or 0)
        for row_index, row in enumerate(table.get("rows", []), start=1):
            units.append(
                {
                    "evidence_id": f"{_slug(city)}_table_p{page:04d}_t{table_index:02d}_r{row_index:03d}",
                    "section": "",
                    "page": page,
                    "evidence_text": (
                        f"{title} | {row['row_header']} | {row['column_header']}: {row['cell_value']}"
                    ).strip(" |"),
                    "table_title": title,
                    "row_header": row["row_header"],
                    "column_header": row["column_header"],
                    "cell_value": row["cell_value"],
                    "notes": row.get("notes") or "",
                    "source_stream": "local_table_image",
                }
            )
    return units


def _rule_record(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    """One candidate -> one Pipeline-5-contract rule record."""
    rule_id = f"local_rule_{index:04d}"
    page = int(candidate.get("page") or 0)
    is_table = candidate.get("source_stream") == "local_table_image"
    source_kind = "table" if is_table else "text"
    source_seq = int(candidate.get("table_index") or index)
    review_reasons = _review_reasons(candidate)
    record: dict[str, Any] = {
        "source_id": f"page_{page:04d}__{source_kind}_{source_seq:03d}",
        "rule_key": candidate.get("rule_key") or "",
        "rule_object": candidate.get("rule_object") or "",
        "constraint_type": candidate.get("constraint_type") or "",
        "subject": candidate.get("subject") or "",
        "operator": candidate.get("operator") or "",
        "value": str(candidate.get("value") if candidate.get("value") is not None else ""),
        "unit": candidate.get("unit") or "",
        "condition": candidate.get("condition") or "",
        "exception": candidate.get("exception") or "",
        "evidence_text": candidate.get("evidence_text") or "",
        "section": candidate.get("section") or "",
        "page": page,
        "warnings": [],
        "source_stream": candidate.get("source_stream") or "local_text_block",
        "batch_id": f"{source_kind}_page_{page:04d}",
        "rule_id": rule_id,
        "applies_to": [
            {
                "rule_id": rule_id,
                "rule_object": candidate.get("rule_object") or "",
                "condition": candidate.get("condition") or "",
            }
        ],
        "applies_to_objects": [candidate.get("rule_object") or ""],
        "scope_count": 1,
        "scope_mode": "single_scope",
        "merged_rule_ids": [rule_id],
        "merged_rule_count": 1,
        "dedup_status": "kept",
        "review_reasons": review_reasons,
        "review_required": bool(review_reasons),
        "final_action": "REVIEW" if review_reasons else "ACCEPT",
    }
    if is_table:
        record["table_title"] = candidate.get("table_title") or ""
        record["row_header"] = candidate.get("row_header") or ""
        record["column_header"] = candidate.get("column_header") or ""
        record["cell_value"] = candidate.get("cell_value") or ""
    else:
        record["clause_id"] = candidate.get("clause_id") or ""
    return record


def _review_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not candidate.get("rule_object"):
        reasons.append("rule_object_unmapped")
    if not candidate.get("operator"):
        reasons.append("operator_missing")
    if candidate.get("operator") in {"<=", ">="} and not candidate.get("unit"):
        reasons.append("unit_missing")
    return reasons


def _dedupe_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse true repeats only; the merged record keeps every source rule_id.

    The key deliberately includes the table context (row/column headers): a
    side-yard and a rear-yard setback can share rule_object/operator/value, and
    collapsing those would hide a claim from the verifier's consensus checks.
    """
    deduped: list[dict[str, Any]] = []
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for rule in rules:
        key = tuple(
            str(rule.get(field) or "").lower()
            for field in (
                "rule_object",
                "constraint_type",
                "operator",
                "value",
                "unit",
                "condition",
                "row_header",
                "column_header",
                "section",
            )
        )
        kept = by_key.get(key)
        if kept is None:
            kept = dict(rule)
            kept["merged_rule_ids"] = list(rule["merged_rule_ids"])
            by_key[key] = kept
            deduped.append(kept)
        else:
            kept["merged_rule_ids"].extend(rule["merged_rule_ids"])
            kept["merged_rule_count"] = len(kept["merged_rule_ids"])
    return deduped


def _count_by(rules: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rule in rules:
        key = str(rule.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
