#!/usr/bin/env python3
"""Build M4 source-corpus snapshots from official local bylaw PDFs.

This script writes benchmark/source_corpus/<city>/ artifacts used by RAG and
coverage audits. It does not read benchmark gold files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config, normalize_city_key, resolve_city_paths
from burnaby_prototype.source.corpus import build_m4_source_corpus, write_m4_source_corpus
from burnaby_prototype.extraction.pdf_ingest import page_ranges_from_provenance
from burnaby_prototype.v2_discovery import build_source_chunks_from_pdf
from burnaby_prototype.v2_store import hash_file


DEFAULT_CITIES = ("burnaby_r1", "vancouver_rs", "calgary_rcg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", action="append", help="City key; repeatable. Defaults to all M4 cities.")
    parser.add_argument("--out-root", default=str(ROOT / "benchmark" / "source_corpus"))
    parser.add_argument("--refresh-source", action="store_true", help="Ignore existing V3 source_chunks cache.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cities = [normalize_city_key(city) for city in (args.city or DEFAULT_CITIES)]
    out_root = Path(args.out_root)
    rows = []
    for city in cities:
        row = build_city_corpus(city=city, out_root=out_root, refresh_source=args.refresh_source)
        rows.append(row)
        print(
            f"[m4-source] {city}: {row['source_chunk_count']} chunks, "
            f"{row['numeric_clause_count']} numeric clauses, "
            f"{row['rule_like_numeric_clause_count']} rule-like numeric clauses"
        )
    print(f"[m4-source] wrote {out_root}")
    return 0


def build_city_corpus(*, city: str, out_root: Path, refresh_source: bool = False) -> dict[str, Any]:
    city_paths = resolve_city_paths(ROOT, city)
    config = load_config(city_paths.config)
    pdf_path = ROOT / "data" / "bylaws" / city / "source.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing source PDF for {city}: {pdf_path}")
    provenance = _read_json(pdf_path.parent / "provenance.json", {})
    page_count = len(PdfReader(str(pdf_path)).pages)
    # District-scoped corpus: when provenance pins a page range (e.g. the R-CG
    # district pages of a multi-district bylaw), ingest only those pages so the
    # corpus, RAG retrieval, and the M5 slot denominator reflect the deliverable
    # district rather than the whole bylaw. null/absent => whole PDF.
    page_ranges = page_ranges_from_provenance(provenance)
    chunks = _load_existing_chunks(city=city, pdf_path=pdf_path) if not refresh_source else []
    if not chunks:
        chunks = build_source_chunks_from_pdf(
            pdf_path=pdf_path, city=city, config=config, page_ranges=page_ranges
        )
    packs = _load_existing_packs(city=city, pdf_path=pdf_path) if not refresh_source else []
    corpus = build_m4_source_corpus(
        city=city,
        pdf_path=pdf_path,
        config=config,
        chunks=chunks,
        packs=packs,
        provenance=provenance,
        page_count=page_count,
    )
    write_m4_source_corpus(corpus, out_root / city)
    manifest = corpus["manifest"]
    audit = corpus["coverage_audit"]
    return {
        "city": city,
        "pdf_sha256": manifest.get("pdf_sha256"),
        "source_chunk_count": manifest.get("source_chunk_count"),
        "numeric_clause_count": audit.get("numeric_clause_count"),
        "rule_like_numeric_clause_count": audit.get("rule_like_numeric_clause_count"),
        "selected_rule_like_numeric_coverage": audit.get("selected_rule_like_numeric_coverage"),
    }


def _load_existing_chunks(*, city: str, pdf_path: Path) -> list[dict[str, Any]]:
    # Prefer M4's own source cache when it exists. V3 source chunks are a valid
    # fallback because M4 wraps the same full-PDF source layer, but M4 artifacts
    # should win when this script is run after an M4 bakeoff.
    for run_root in ("m7_runs", "v3_runs"):
        chunks = _load_cached_list_artifact(
            city=city,
            pdf_path=pdf_path,
            run_root=run_root,
            artifact_name="source_chunks.json",
        )
        if chunks:
            return chunks
    return []


def _load_existing_packs(*, city: str, pdf_path: Path) -> list[dict[str, Any]]:
    # Packs define selected source coverage. Using V3 packs here would make a
    # rebuilt M4 source corpus report V3 selection coverage, not M4 coverage.
    for run_root in ("m7_runs", "v3_runs"):
        packs = _load_cached_list_artifact(
            city=city,
            pdf_path=pdf_path,
            run_root=run_root,
            artifact_name="evidence_packs.json",
        )
        if packs:
            return packs
    return []


def _load_cached_list_artifact(
    *,
    city: str,
    pdf_path: Path,
    run_root: str,
    artifact_name: str,
) -> list[dict[str, Any]]:
    artifact_path = ROOT / "outputs" / run_root / city / artifact_name
    summary_path = ROOT / "outputs" / run_root / city / "source_summary.json"
    if not artifact_path.exists() or not summary_path.exists():
        return []
    summary = _read_json(summary_path, {})
    if summary.get("pdf_hash") != hash_file(pdf_path):
        return []
    artifact = _read_json(artifact_path, [])
    return artifact if isinstance(artifact, list) else []


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
