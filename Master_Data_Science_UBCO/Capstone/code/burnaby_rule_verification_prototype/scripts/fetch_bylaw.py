#!/usr/bin/env python3
"""Fetch-once + cache a bylaw PDF for the internal extraction helper.

Downloads ``--url`` to ``data/bylaws/<city>/source.pdf`` and records
``provenance.json`` (url, fetched_at, sha256, bytes, pages). Idempotent: when
the stored file already has the same sha256, this is a no-op. ``--pages``
(e.g. '100-140') slices the PDF via pypdf when available, else the whole
document is kept.

This script NEVER runs implicitly from any other module — fetching a bylaw is
always an explicit operator action. PDFs are gitignored (we commit provenance
and extracted text, not large binaries). Uses urllib with a polite User-Agent;
no new dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

USER_AGENT = (
    "burnaby-prototype-capstone/0.1 (academic zoning-bylaw research; "
    "single fetch, cached locally)"
)


def fetch_bylaw(
    city: str,
    url: str,
    *,
    pages: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Fetch one bylaw PDF into data/bylaws/<city>/ (idempotent by sha256)."""
    base = (root or ROOT) / "data" / "bylaws" / _slug(city)
    base.mkdir(parents=True, exist_ok=True)
    pdf_path = base / "source.pdf"
    provenance_path = base / "provenance.json"

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        payload = response.read()

    page_range = _parse_page_range(pages)
    if page_range:
        payload, slice_note = _slice_pdf(payload, page_range)
    else:
        slice_note = None

    sha256 = hashlib.sha256(payload).hexdigest()
    if pdf_path.exists() and _file_sha256(pdf_path) == sha256:
        print(f"No change: {pdf_path} already matches sha256 {sha256[:12]}… — skipping write.")
        return {"status": "unchanged", "pdf_path": str(pdf_path), "sha256": sha256}

    pdf_path.write_bytes(payload)
    provenance = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": sha256,
        "bytes": len(payload),
        "pages": pages,
        "page_count": _page_count(payload),
    }
    if slice_note:
        provenance["slice_note"] = slice_note
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    _ensure_gitignore((root or ROOT) / "data" / "bylaws")
    print(f"Fetched {len(payload)} bytes -> {pdf_path} (sha256 {sha256[:12]}…)")
    return {"status": "fetched", "pdf_path": str(pdf_path), "sha256": sha256, **provenance}


def _parse_page_range(pages: str | None) -> tuple[int, int] | None:
    if not pages:
        return None
    try:
        start_text, _, end_text = pages.partition("-")
        start, end = int(start_text), int(end_text or start_text)
    except ValueError as exc:
        raise SystemExit(f"--pages must look like '100-140', got: {pages!r}") from exc
    if start < 1 or end < start:
        raise SystemExit(f"--pages range out of order: {pages!r}")
    return start, end


def _slice_pdf(payload: bytes, page_range: tuple[int, int]) -> tuple[bytes, str]:
    """Slice to a 1-based inclusive page range via pypdf; keep whole on failure."""
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: PLC0415 - optional
    except Exception:
        note = "pypdf not installed — kept whole document"
        print(note)
        return payload, note
    try:
        reader = PdfReader(io.BytesIO(payload))
        writer = PdfWriter()
        start, end = page_range
        end = min(end, len(reader.pages))
        for index in range(start - 1, end):
            writer.add_page(reader.pages[index])
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue(), f"sliced to pages {start}-{end} of {len(reader.pages)}"
    except Exception as exc:
        note = f"pypdf slice failed ({type(exc).__name__}) — kept whole document"
        print(note)
        return payload, note


def _page_count(payload: bytes) -> int | None:
    try:
        from pypdf import PdfReader  # noqa: PLC0415 - optional

        return len(PdfReader(io.BytesIO(payload)).pages)
    except Exception:
        return None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_gitignore(bylaws_dir: Path) -> None:
    gitignore = bylaws_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*.pdf\n", encoding="utf-8")


def _slug(value: str) -> str:
    import re  # noqa: PLC0415

    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", required=True, help="City slug, e.g. calgary (folders key off this).")
    parser.add_argument("--url", required=True, help="Bylaw PDF URL (http(s):// or file://).")
    parser.add_argument(
        "--pages",
        default=None,
        help="Optional 1-based inclusive page range, e.g. '100-140' (needs pypdf; else whole PDF kept).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = fetch_bylaw(args.city, args.url, pages=args.pages)
    if result["status"] == "fetched":
        print(f"Provenance: {Path(result['pdf_path']).parent / 'provenance.json'}")


if __name__ == "__main__":
    sys.exit(main())
