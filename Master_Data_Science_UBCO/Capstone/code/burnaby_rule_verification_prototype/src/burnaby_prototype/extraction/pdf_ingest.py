"""Layered PDF ingest for the internal extraction helper.

Tries Docling first (richer layout/structure); falls back to pdfplumber when
docling is not installed or fails. Both backends emit the same JSON-serializable
intermediate so the downstream streams never care which backend ran:

    {
      "source_pdf": str,
      "ingest_backend": "docling" | "pdfplumber",
      "pages": [
        {
          "page_number": int,           # 1-based
          "text": str,                  # full page text
          "blocks": [{"text": str, "kind": "heading"|"paragraph"|"list_item"}],
          "tables": [{"title_guess": str, "rows": [[str, ...], ...], "page": int}],
        },
        ...
      ],
    }

Legacy diagnostic helper only — native M4 is the current product extraction.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable


HEADING_CASE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 \-–—.,:()/&']{3,79}$")
SECTION_START_RE = re.compile(r"^\s*\d{1,3}(?:\.\d{1,3})+")
LIST_ITEM_RE = re.compile(r"^\s*(?:\(\d+\)|\([a-z]\)|\d{1,2}\.\s|[•▪‣-]\s)")


def ingest_pdf(
    pdf_path: str | Path,
    *,
    prefer_docling: bool = True,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Read a bylaw PDF into the common intermediate (docling, else pdfplumber)."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if prefer_docling:
        intermediate = _try_docling(path, log)
        if intermediate is not None:
            return intermediate
    return _ingest_with_pdfplumber(path, log)


def page_ranges_from_provenance(
    provenance: dict[str, Any],
) -> list[tuple[int, int]] | None:
    """Read optional inclusive page spans from a bylaw's provenance.json.

    Accepts a single pair (``[465, 478]``), a list of disjoint pairs
    (``[[389, 401], [465, 478]]``), or a ``{"start","end"}`` object; null/absent
    means the whole PDF. Used to scope a multi-district bylaw to one district's
    page span so extraction and the M5 slot denominator reflect the deliverable.
    """
    pages = (provenance or {}).get("pages")
    if not pages:
        return None
    if isinstance(pages, (list, tuple)) and len(pages) == 2 and all(isinstance(x, int) for x in pages):
        return [(int(pages[0]), int(pages[1]))]
    if isinstance(pages, (list, tuple)) and all(
        isinstance(p, (list, tuple)) and len(p) == 2 for p in pages
    ):
        return [(int(a), int(b)) for a, b in pages]
    if isinstance(pages, dict) and pages.get("start") and pages.get("end"):
        return [(int(pages["start"]), int(pages["end"]))]
    return None


def restrict_intermediate_to_pages(
    intermediate: dict[str, Any],
    page_ranges: list[tuple[int, int]] | tuple[int, int] | None,
) -> dict[str, Any]:
    """Return ``intermediate`` keeping only pages within ``page_ranges`` (inclusive).

    Original ``page_number`` values are preserved so downstream citations stay
    valid. ``None`` is a no-op (whole document). Accepts a single ``(start, end)``
    pair or a list of disjoint pairs.
    """
    if page_ranges is None:
        return intermediate
    ranges = [page_ranges] if page_ranges and isinstance(page_ranges[0], int) else list(page_ranges)
    spans = [(int(a), int(b)) for a, b in ranges]
    return {
        **intermediate,
        "pages": [
            page
            for page in (intermediate.get("pages") or [])
            if any(a <= int(page.get("page_number") or 0) <= b for a, b in spans)
        ],
    }


def _try_docling(path: Path, log: Callable[[str], None]) -> dict[str, Any] | None:
    """Docling path behind a lazy import; any failure falls back to pdfplumber.

    OCR is disabled: bylaw PDFs are born-digital, OCR adds heavy model
    dependencies (rapidocr) for nothing, and skipping it keeps the ingest
    deterministic. Scanned documents should be handled upstream.
    """
    try:
        from docling.document_converter import DocumentConverter  # noqa: PLC0415
    except Exception:
        log("docling not installed — using pdfplumber")
        return None
    try:
        converter = _docling_converter(DocumentConverter)
        document = converter.convert(str(path)).document
        return _intermediate_from_docling(document, path)
    except Exception as exc:  # pragma: no cover - depends on optional backend
        log(f"docling ingest failed ({type(exc).__name__}) — using pdfplumber")
        return None


def _docling_converter(converter_class: Any) -> Any:
    """Build a no-OCR PDF converter; plain default if the options API moved."""
    try:
        from docling.datamodel.base_models import InputFormat  # noqa: PLC0415
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # noqa: PLC0415
        from docling.document_converter import PdfFormatOption  # noqa: PLC0415

        options = PdfPipelineOptions(do_ocr=False)
        return converter_class(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
    except Exception:  # pragma: no cover - depends on docling version
        return converter_class()


def _intermediate_from_docling(document: Any, path: Path) -> dict[str, Any]:
    """Map a docling document into the common intermediate."""
    pages: dict[int, dict[str, Any]] = {}

    def _page(page_number: int) -> dict[str, Any]:
        return pages.setdefault(
            page_number,
            {"page_number": page_number, "text": "", "blocks": [], "tables": []},
        )

    for item in getattr(document, "texts", []) or []:
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        page_number = _docling_page(item)
        label = str(getattr(item, "label", "") or "").lower()
        if "page_header" in label or "page_footer" in label:
            continue  # page furniture would pollute clause evidence text
        if "header" in label or "title" in label:
            kind = "heading"
        elif "list" in label:
            kind = "list_item"
        else:
            kind = "paragraph"
        page = _page(page_number)
        page["blocks"].append({"text": text, "kind": kind})
        page["text"] = f"{page['text']}\n{text}" if page["text"] else text

    for table_index, item in enumerate(getattr(document, "tables", []) or [], start=1):
        page_number = _docling_page(item)
        rows = _docling_table_rows(item)
        if not rows:
            continue
        page = _page(page_number)
        title_guess = next(
            (block["text"] for block in page["blocks"] if block["kind"] == "heading"),
            "",
        )
        page["tables"].append({"title_guess": title_guess, "rows": rows, "page": page_number})

    ordered = [pages[number] for number in sorted(pages)]
    return {"source_pdf": str(path), "ingest_backend": "docling", "pages": ordered}


def _docling_page(item: Any) -> int:
    provenance = getattr(item, "prov", None) or []
    for entry in provenance:
        page_no = getattr(entry, "page_no", None)
        if page_no:
            return int(page_no)
    return 1


def _docling_table_rows(item: Any) -> list[list[str]]:
    data = getattr(item, "data", None)
    grid = getattr(data, "grid", None) or []
    rows: list[list[str]] = []
    for grid_row in grid:
        cells = [str(getattr(cell, "text", "") or "").strip() for cell in grid_row]
        if any(cells):
            rows.append(cells)
    return rows


def _ingest_with_pdfplumber(path: Path, log: Callable[[str], None]) -> dict[str, Any]:
    """pdfplumber fallback: line-based block heuristics + extract_tables."""
    try:
        import pdfplumber  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - install guard
        raise RuntimeError(
            "pdfplumber is required for PDF ingest. Install the extraction extra: "
            "pip install -e .[extraction]"
        ) from exc

    pages: list[dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            blocks = blocks_from_text(text)
            tables: list[dict[str, Any]] = []
            try:
                raw_tables = page.extract_tables() or []
            except Exception:  # pragma: no cover - malformed page geometry
                raw_tables = []
            title_guess = next(
                (block["text"] for block in blocks if block["kind"] == "heading"), ""
            )
            for raw in raw_tables:
                rows = [
                    [str(cell or "").strip() for cell in row]
                    for row in raw
                    if any(str(cell or "").strip() for cell in row)
                ]
                if rows:
                    tables.append({"title_guess": title_guess, "rows": rows, "page": page_number})
            pages.append(
                {"page_number": page_number, "text": text, "blocks": blocks, "tables": tables}
            )
    log(f"pdfplumber ingest: {len(pages)} pages from {path.name}")
    return {"source_pdf": str(path), "ingest_backend": "pdfplumber", "pages": pages}


def blocks_from_text(text: str) -> list[dict[str, str]]:
    """Group raw page text into heading/list_item/paragraph blocks.

    Deterministic line heuristics: section-numbered or short ALL-CAPS lines are
    headings, bullet/lettered lines are list items, runs of other lines merge
    into paragraphs. Shared with text_stream's line fallback.
    """
    blocks: list[dict[str, str]] = []
    paragraph: list[str] = []

    def _flush() -> None:
        if paragraph:
            blocks.append({"text": " ".join(paragraph), "kind": "paragraph"})
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            _flush()
            continue
        if SECTION_START_RE.match(line) or HEADING_CASE_RE.match(line):
            _flush()
            blocks.append({"text": line, "kind": "heading"})
        elif LIST_ITEM_RE.match(line):
            _flush()
            blocks.append({"text": line, "kind": "list_item"})
        else:
            paragraph.append(line)
    _flush()
    return blocks
