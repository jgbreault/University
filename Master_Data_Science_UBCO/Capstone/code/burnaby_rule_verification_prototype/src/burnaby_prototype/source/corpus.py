"""M4 source corpus snapshots for exhaustive bylaw discovery.

The source corpus is input data, not an answer key. It stores the official PDF
hash, extracted chunks, table context, and numeric/rule-like source clauses so
RAG and extraction can be audited for coverage. It must never read benchmark
gold files or verifier outputs.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ..bylaw_rag import build_index_payload
from ..config import write_json
from ..v2_store import hash_file, hash_json


M4_SOURCE_CORPUS_VERSION = "m4_source_corpus_1"


def build_m4_source_corpus(
    *,
    city: str,
    pdf_path: Path,
    config: dict[str, Any],
    chunks: list[dict[str, Any]],
    packs: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
    page_count: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic source-corpus payload from already extracted chunks."""
    pdf_path = Path(pdf_path)
    provenance = provenance or {}
    pdf_hash = hash_file(pdf_path) if pdf_path.exists() else None
    config_hash = hash_json(_clean_config(config))
    pack_lookup = _pack_lookup(packs or [])
    rag_chunks = _rag_chunks(chunks)
    table_index = _table_index(chunks)
    numeric_index = _numeric_clause_index(chunks, pack_lookup)
    rule_like_numeric = [row for row in numeric_index if row["rule_signal"]]
    return {
        "manifest": {
            "corpus_version": M4_SOURCE_CORPUS_VERSION,
            "city": city,
            "zone": config.get("zone"),
            "configured_source_document": config.get("source_document") or config.get("bylaw"),
            "configured_source_url": config.get("source_url") or "",
            "provenance_url": provenance.get("url") or "",
            "fetched_at": provenance.get("fetched_at"),
            "source_pdf": str(pdf_path),
            "pdf_sha256": pdf_hash,
            "provenance_sha256": provenance.get("sha256"),
            "pdf_bytes": pdf_path.stat().st_size if pdf_path.exists() else None,
            "page_count": page_count or provenance.get("page_count") or provenance.get("pages"),
            "config_hash": config_hash,
            "source_chunk_count": len(chunks),
            "rag_chunk_count": len(rag_chunks),
            "table_entry_count": len(table_index),
            "numeric_clause_count": len(numeric_index),
            "rule_like_numeric_clause_count": len(rule_like_numeric),
            "gold_leakage_guard": "No benchmark gold, expected dispositions, or verified outputs are stored in this source corpus.",
        },
        "source_chunks": chunks,
        "rag_index": build_index_payload(rag_chunks),
        "table_index": table_index,
        "numeric_clause_index": numeric_index,
        "coverage_audit": _coverage_audit(chunks, numeric_index, table_index),
    }


def write_m4_source_corpus(corpus: dict[str, Any], output_dir: Path) -> None:
    """Write M4 source-corpus artifacts under benchmark/source_corpus/<city>."""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "manifest.json", corpus["manifest"])
    write_json(output_dir / "source_chunks.json", corpus["source_chunks"])
    write_json(output_dir / "rag_index.json", corpus["rag_index"])
    write_json(output_dir / "table_index.json", corpus["table_index"])
    write_json(output_dir / "numeric_clause_index.json", corpus["numeric_clause_index"])
    write_json(output_dir / "coverage_audit.json", corpus["coverage_audit"])


def _rag_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for chunk in chunks:
        text = _source_text(chunk)
        if not text:
            continue
        rows.append(
            {
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "section": str(chunk.get("section") or ""),
                "page": chunk.get("page"),
                "text": text,
                "evidence_type": chunk.get("evidence_type") or "clause",
            }
        )
    return rows


def _table_index(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for chunk in chunks:
        evidence_type = str(chunk.get("evidence_type") or "")
        if evidence_type not in {"table_cell", "table_row"}:
            continue
        cells = (chunk.get("metadata") or {}).get("cells") or []
        if not cells and chunk.get("cell_value"):
            cells = [
                {
                    "column_header": str(chunk.get("column_header") or ""),
                    "cell_value": str(chunk.get("cell_value") or ""),
                }
            ]
        rows.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "page": chunk.get("page"),
                "section": chunk.get("section") or "",
                "table_title": chunk.get("table_title") or chunk.get("heading") or "",
                "row_header": chunk.get("row_header") or "",
                "cells": [
                    {
                        "column_header": str(cell.get("column_header") or ""),
                        "cell_value": str(cell.get("cell_value") or ""),
                    }
                    for cell in cells
                    if str(cell.get("cell_value") or "").strip()
                ],
                "source_text": _source_text(chunk),
            }
        )
    return rows


def _numeric_clause_index(
    chunks: list[dict[str, Any]],
    pack_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        chunk_id = str(chunk.get("chunk_id") or "")
        pack = pack_lookup.get(chunk_id, {})
        measurement_count = int(metadata.get("measurement_count") or 0)
        if measurement_count <= 0:
            continue
        rule_cue_count = int(metadata.get("rule_cue_count") or 0)
        rule_types = [str(value) for value in metadata.get("rule_types") or []]
        rows.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "page": chunk.get("page"),
                "section": chunk.get("section") or "",
                "evidence_type": chunk.get("evidence_type") or "clause",
                "measurement_count": measurement_count,
                "rule_cue_count": rule_cue_count,
                "rule_signal": bool(rule_cue_count),
                "rule_types": rule_types,
                "selected_by_discovery": bool(pack or metadata.get("discovery_selected")),
                "selected_pack_id": pack.get("pack_id") or "",
                "selected_pack_lane": pack.get("lane") or metadata.get("lane") or "",
                "selection_tier": pack.get("selection_tier") or metadata.get("selection_tier") or "",
                "drop_risk": pack.get("drop_risk") or metadata.get("drop_risk") or "",
                "text_preview": _source_text(chunk)[:320],
            }
        )
    rows.sort(key=lambda row: (int(row.get("page") or 0), str(row.get("chunk_id") or "")))
    return rows


def _coverage_audit(
    chunks: list[dict[str, Any]],
    numeric_index: list[dict[str, Any]],
    table_index: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence_types = Counter(str(chunk.get("evidence_type") or "unknown") for chunk in chunks)
    rule_like_numeric = [row for row in numeric_index if row.get("rule_signal")]
    selected_rule_like = [row for row in rule_like_numeric if row.get("selected_by_discovery")]
    pages = sorted({int(chunk.get("page") or 0) for chunk in chunks if chunk.get("page")})
    packed_pages = sorted(
        {
            int(row.get("page") or 0)
            for row in numeric_index
            if row.get("selected_by_discovery") and row.get("page")
        }
    )
    return {
        "corpus_version": M4_SOURCE_CORPUS_VERSION,
        "advisory_only": True,
        "source_chunk_count": len(chunks),
        "page_count_with_chunks": len(pages),
        "first_chunk_page": pages[0] if pages else None,
        "last_chunk_page": pages[-1] if pages else None,
        "evidence_type_counts": _counter_rows(evidence_types),
        "table_entry_count": len(table_index),
        "table_cell_count": sum(len(row.get("cells") or []) for row in table_index),
        "numeric_clause_count": len(numeric_index),
        "rule_like_numeric_clause_count": len(rule_like_numeric),
        "selected_rule_like_numeric_clause_count": len(selected_rule_like),
        "selected_rule_like_numeric_coverage": _ratio(len(selected_rule_like), len(rule_like_numeric)),
        "packed_numeric_page_count": len(packed_pages),
        "near_miss_rule_like_numeric": [
            row for row in rule_like_numeric if not row.get("selected_by_discovery")
        ][:100],
        "note": "Coverage audit measures source discovery only; benchmark gold is scored separately after verification.",
    }


def _pack_lookup(packs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup = {}
    for pack in packs:
        chunk_id = str(pack.get("chunk_id") or "")
        if chunk_id and chunk_id not in lookup:
            lookup[chunk_id] = pack
    return lookup


def _source_text(chunk: dict[str, Any]) -> str:
    parts = []
    if chunk.get("heading"):
        parts.append(f"Heading: {chunk['heading']}")
    if chunk.get("parent_text"):
        parts.append(f"Parent context: {chunk['parent_text']}")
    if chunk.get("table_title") or chunk.get("row_header") or chunk.get("column_header"):
        parts.append(
            "Table context: "
            + " | ".join(
                str(chunk.get(field) or "")
                for field in ("table_title", "row_header", "column_header")
                if str(chunk.get(field) or "").strip()
            )
        )
    parts.append(str(chunk.get("text") or ""))
    return " ".join(part.strip() for part in parts if str(part or "").strip())


def _counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in sorted(counter.items())]


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _clean_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if not str(key).startswith("_")}
