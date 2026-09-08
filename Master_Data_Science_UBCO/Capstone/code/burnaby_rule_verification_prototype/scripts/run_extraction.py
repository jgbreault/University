#!/usr/bin/env python3
"""Run the legacy INTERNAL extraction helper over a fetched bylaw PDF.

Diagnostic and experimentation only — the current product extraction path is
native M4; no default pipeline path uses this script. It ingests a PDF
(docling when installed, else pdfplumber), runs the deterministic text-clause
stream, optionally the Gemini table-vision stream (skipped with --no-llm or
when GOOGLE_API_KEY is unset), and writes the Pipeline-5 registry contract so
an experimental verify-run needs zero verifier changes:

    .venv/bin/python scripts/run_extraction.py --city calgary
    .venv/bin/python scripts/run_slim_verifier.py --city calgary_rc1 \
        --pipeline5-registry outputs/calgary_extraction/final_rule_registry.json
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.extraction.pdf_ingest import ingest_pdf
from burnaby_prototype.extraction.registry_writer import write_registry_outputs
from burnaby_prototype.extraction.table_stream import run_table_stream
from burnaby_prototype.extraction.text_stream import run_text_stream


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", required=True, help="City slug, e.g. calgary.")
    parser.add_argument(
        "--pdf",
        default=None,
        help="Bylaw PDF path (default: data/bylaws/<city>/source.pdf from fetch_bylaw.py).",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the Gemini table-vision stream (text stream only).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: outputs/<city>_extraction/).",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help=(
            "Deterministic page slice of the SOURCE pdf, 1-based inclusive, e.g. "
            "'393-399'. Replaces hand-made slice PDFs: the slice is derived in "
            "memory every run, evidence keeps FULL-PDF page numbers, and the "
            "output records source sha256 + the page range as provenance."
        ),
    )
    return parser.parse_args()


def _parse_pages(spec: str) -> tuple[int, int]:
    start_text, _, end_text = spec.partition("-")
    start, end = int(start_text), int(end_text or start_text)
    if start < 1 or end < start:
        raise SystemExit(f"bad --pages range: {spec}")
    return start, end


def _slice_pdf(source: Path, start: int, end: int) -> Path:
    """Write a deterministic page slice to a derived, git-ignored temp file."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(source))
    if end > len(reader.pages):
        raise SystemExit(f"--pages {start}-{end} exceeds {len(reader.pages)} pages")
    writer = PdfWriter()
    for index in range(start - 1, end):
        writer.add_page(reader.pages[index])
    sliced = source.parent / f"_slice_{start}_{end}.pdf"
    with open(sliced, "wb") as handle:
        writer.write(handle)
    return sliced


def _normalized_page_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _best_contiguous_page_match(
    slice_page_texts: list[str],
    source_page_texts: list[str],
) -> tuple[int, int] | None:
    """Find a 1-based inclusive full-source page range matching a slice."""
    normalized_slice = [_normalized_page_text(text) for text in slice_page_texts]
    if not normalized_slice or any(not text for text in normalized_slice):
        return None
    normalized_source = [_normalized_page_text(text) for text in source_page_texts]
    slice_len = len(normalized_slice)
    for start_index in range(0, len(normalized_source) - slice_len + 1):
        if normalized_source[start_index : start_index + slice_len] == normalized_slice:
            return start_index + 1, start_index + slice_len
    return None


def _pdf_page_texts(path: Path) -> list[str]:
    try:
        import pdfplumber  # noqa: PLC0415
    except Exception:
        return []
    with pdfplumber.open(str(path)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _infer_source_slice(
    *,
    city: str,
    pdf_path: Path,
    intermediate: dict[str, Any],
) -> dict[str, Any] | None:
    """Infer whether an arbitrary input PDF is a slice of the city's source.pdf.

    This lets strict reproducibility checks pass when they deliberately create a
    fresh temporary slice from the raw bylaw instead of using ``--pages``.
    Provenance remains source-backed: the match is accepted only when every
    slice page text exactly matches a contiguous full-source page window after
    whitespace normalization.
    """
    full_source = ROOT / "data" / "bylaws" / _slug(city) / "source.pdf"
    if not full_source.exists():
        return None
    try:
        if pdf_path.resolve() == full_source.resolve():
            return None
    except OSError:
        return None
    slice_texts = [str(page.get("text") or "") for page in intermediate.get("pages", [])]
    match = _best_contiguous_page_match(slice_texts, _pdf_page_texts(full_source))
    if match is None:
        return None
    start, end = match
    return {
        "source_pdf": full_source,
        "source_pages": f"{start}-{end}",
        "page_offset": start - 1,
    }


def _apply_page_offset(intermediate: dict[str, Any], page_offset: int) -> None:
    """Shift page numbers in-place from slice-local to full-PDF numbering."""
    if not page_offset:
        return
    for page in intermediate.get("pages", []):
        page["page_number"] = int(page.get("page_number") or 0) + page_offset
        for table in page.get("tables", []) or []:
            table["page"] = int(table.get("page") or 0) + page_offset


def main() -> int:
    args = parse_args()
    city = args.city
    pdf_path = Path(args.pdf) if args.pdf else ROOT / "data" / "bylaws" / _slug(city) / "source.pdf"
    output_dir = Path(args.out) if args.out else ROOT / "outputs" / f"{_slug(city)}_extraction"
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        print(f"Fetch it first: .venv/bin/python scripts/fetch_bylaw.py --city {city} --url <bylaw-pdf-url>")
        return 1

    page_offset = 0
    ingest_target = pdf_path
    registry_source_pdf = pdf_path
    table_pdf_path = pdf_path
    source_pages = args.pages
    if args.pages:
        start, end = _parse_pages(args.pages)
        ingest_target = _slice_pdf(pdf_path, start, end)
        page_offset = start - 1  # evidence keeps FULL-PDF page numbers

    # pdfplumber-first for the TEXT stream: the clause grammar is line-anchored
    # (section numbers, '(n)' subsections, marginal codes at line starts) and
    # docling's reading-order reflow merges those line boundaries away — on
    # Calgary's 1P2007 it dropped sections 351/352 entirely. Docling remains
    # available for table-structure work via ingest_pdf(prefer_docling=True).
    intermediate = ingest_pdf(ingest_target, prefer_docling=False)
    if page_offset:
        _apply_page_offset(intermediate, page_offset)
    elif not args.pages:
        inferred = _infer_source_slice(city=city, pdf_path=pdf_path, intermediate=intermediate)
        if inferred:
            registry_source_pdf = inferred["source_pdf"]
            table_pdf_path = inferred["source_pdf"]
            source_pages = inferred["source_pages"]
            _apply_page_offset(intermediate, int(inferred["page_offset"]))
            print(
                f"Matched input PDF to {Path(registry_source_pdf).name} pages "
                f"{source_pages}; preserving full-PDF page provenance."
            )
    text_result = run_text_stream(intermediate, city)

    if args.no_llm:
        table_result = {"available": False, "reason": "--no-llm", "tables": [], "model": None}
        print("Table stream skipped (--no-llm).")
    else:
        # Keyless runs skip gracefully inside run_table_stream (clear message,
        # text stream output still written). The key is read from the
        # environment only; it is never written to any file.
        table_result = run_table_stream(
            intermediate,
            city,
            pdf_path=table_pdf_path,
            cache_dir=ROOT / "data" / "bylaws" / _slug(city) / "cache",
        )

    outputs = write_registry_outputs(
        output_dir,
        city,
        text_result,
        table_result,
        source_pdf=str(registry_source_pdf),
        source_pages=source_pages,
    )
    if ingest_target != pdf_path:
        ingest_target.unlink(missing_ok=True)  # derived slice is never an artifact
    summary = outputs["summary"]
    counts = summary["counts"]
    print("\nInternal extraction complete (legacy diagnostic helper; native M4 is current)")
    print(f"Ingest backend:   {intermediate.get('ingest_backend')}")
    print(f"Pages read:       {len(intermediate.get('pages', []))}")
    print(f"Clauses:          {counts['clauses']} (sections seen: {len(summary['sections_seen'])})")
    print(f"Text candidates:  {counts['text_candidates']}")
    table_note = "" if summary["table_stream_available"] else f"  [skipped: {summary['table_stream_reason']}]"
    print(f"Tables read:      {counts['tables']}{table_note}")
    print(f"Table candidates: {counts['table_candidates']}")
    print(f"Final rules:      {counts['rules_final']} (raw {counts['rules_raw']})")
    print(f"Registry:         {outputs['registry_path']}")
    print(f"Evidence units:   {outputs['evidence_units_path']} ({counts['evidence_units']})")
    print(f"Summary:          {outputs['summary_path']}")
    print(
        "\nVerify experimentally with:\n"
        f"  .venv/bin/python scripts/run_slim_verifier.py --city <city_zone> "
        f"--pipeline5-registry {outputs['registry_path']}"
    )
    return 0


def _slug(value: str) -> str:
    import re  # noqa: PLC0415

    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


if __name__ == "__main__":
    sys.exit(main())
