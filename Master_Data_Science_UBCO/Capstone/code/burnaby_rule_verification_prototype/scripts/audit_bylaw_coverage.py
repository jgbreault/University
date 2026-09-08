#!/usr/bin/env python3
"""Bylaw coverage audit — RAG corpus as a recall instrument (read-only).

Answers a question the benchmark cannot: "of the bylaw's NUMERIC clauses,
how many did the pipeline even propose a candidate for?" Gold-based recall
measures the verifier against hand-checked truth; THIS measures the
extraction/proposal stage against the bylaw text itself, with no gold needed.

Method: every numeric-bearing chunk in the city's RAG corpus is a clause the
pipeline should have seen. A chunk counts as COVERED when a rule candidate
cites it (same section anchor, or same evidence text). The misses are the
honest extraction-gap list — each one is either a known out-of-contract
family, a proposer gap, or upstream loss.

Writes outputs/<city>.../bylaw_coverage.json + a stdout summary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# A clause is "numeric-bearing" when it states a measurement (number + unit),
# not merely any digit (section references and amendment codes are digits too).
MEASUREMENT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:square\s+)?(?:metres?|meters?|m2|m²|per\s?cent|percent|%|storeys?|stories|m)\b",
    re.IGNORECASE,
)


def _norm_section(value: str) -> str:
    return re.sub(r"[\s]", "", str(value or "")).lower()


def audit_city(city: str) -> dict:
    out_dir = ROOT / "outputs" / f"{city}_slim_pipeline5_registry"
    index_path = out_dir / "bylaw_rag_index.json"
    if not index_path.exists():
        return {"city": city, "error": f"no RAG index at {index_path} — run build_rag_index first"}
    chunks = json.loads(index_path.read_text(encoding="utf-8")).get("chunks", [])

    candidates = json.loads((out_dir / "rule_candidates.json").read_text(encoding="utf-8"))
    evidence_units = json.loads((out_dir / "evidence_units.json").read_text(encoding="utf-8"))
    unit_by_id = {str(u.get("evidence_id") or ""): u for u in evidence_units}

    # The pipeline re-keys evidence ids, so linkage goes candidate ->
    # evidence_unit -> TEXT: a chunk is covered when a cited evidence text and
    # the chunk text share their head (whitespace-normalized, either way).
    def _head(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip().lower()[:100]

    cited_sections: set[str] = set()
    cited_heads: list[str] = []
    cited_evidence_ids = {str(c.get("evidence_id") or "") for c in candidates}
    for candidate in candidates:
        if candidate.get("section"):
            cited_sections.add(_norm_section(candidate["section"]))
        unit = unit_by_id.get(str(candidate.get("evidence_id") or ""), {})
        for field in ("evidence_text", "source_context"):
            head = _head(unit.get(field) or candidate.get(field) or "")
            if head:
                cited_heads.append(head)
        if unit.get("section"):
            cited_sections.add(_norm_section(unit["section"]))

    numeric_chunks = [c for c in chunks if MEASUREMENT_RE.search(c.get("text") or "")]
    covered, misses = [], []
    for chunk in numeric_chunks:
        section = _norm_section(chunk.get("section"))
        chunk_head = _head(chunk.get("text"))
        # Three linkage routes, most direct first: evidence-units corpora share
        # ids with candidates; section-anchored corpora share section numbers;
        # otherwise whitespace-normalized text heads must overlap.
        is_covered = (
            str(chunk.get("chunk_id") or "") in cited_evidence_ids
            or (section and section in cited_sections)
            or any(
                head.startswith(chunk_head[:80]) or chunk_head.startswith(head[:80])
                for head in cited_heads
                if head
            )
        )
        (covered if is_covered else misses).append(
            {
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "section": chunk.get("section"),
                "page": chunk.get("page"),
                "text": (chunk.get("text") or "")[:120],
            }
        )

    rate = len(covered) / len(numeric_chunks) if numeric_chunks else None
    return {
        "city": city,
        "purpose": "Extraction-stage coverage of numeric bylaw clauses (no gold needed). Read-only.",
        "corpus_chunks": len(chunks),
        "numeric_clauses": len(numeric_chunks),
        "covered_by_candidates": len(covered),
        "coverage_rate": round(rate, 3) if rate is not None else None,
        "misses": misses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="+", default=["burnaby_r1", "vancouver_rs", "calgary_rcg"])
    args = parser.parse_args()
    for city in args.cities:
        report = audit_city(city)
        out_dir = ROOT / "outputs" / f"{city}_slim_pipeline5_registry"
        if "error" in report:
            print(f"[coverage] {city}: {report['error']}")
            continue
        (out_dir / "bylaw_coverage.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            f"[coverage] {city}: {report['covered_by_candidates']}/{report['numeric_clauses']} numeric "
            f"clauses have candidates (rate {report['coverage_rate']}) — misses: {len(report['misses'])}"
        )
        for miss in report["misses"][:6]:
            print(f"    MISS [{miss.get('section') or miss['chunk_id']}] {miss['text']}")


if __name__ == "__main__":
    main()
