"""Deterministic matrix-table geometry recovered from the source PDF.

Development-regulation tables are matrices whose COLUMN dimension (dwelling
type × unit-count bucket) is invisible in linearized evidence text — the
page text contains every column's words, so word overlap can neither prove
nor refute which column a value came from. Only geometry can: pdfplumber's
table finder recovers the column bands (x-ranges under each header), which
cell text sits in which band, and which cells span all bands.

This module is evidence ENRICHMENT, mirroring source_repair.py's trust
model: it reads the city's cached, sha-pinned source.pdf and attaches a
``matrix_anchor`` block to table evidence units. It never decides anything —
the verifier proves or refutes column claims against the anchor, and
evidence without an anchor simply keeps today's behavior (the layer is
inert without a PDF, which is what keeps it additive for prose-only
cities).

Anchor shape attached to evidence units:

    "matrix_anchor": {
      "page": 2,
      "row_label": "Maximum Lot Coverage | All Buildings",
      "bands": [
        {"key": 0, "header_text": "Rowhouse | 1 to 3 Units", "cell_text": "55%",
         "numbers": [55.0], "spans_all": false, "branches": []},
        {"key": 1, "header_text": "Small-Scale Multi-Unit | 1 to 2 Units",
         "cell_text": "Lots < 567 m2: 40%\\nLots > 567 m2: 30%", "numbers": [40.0, 30.0],
         "spans_all": false,
         "branches": [{"condition_text": "Lots < 567 m2", "comparator": "<=",
                        "threshold": 567.0, "value_text": "40%", "numbers": [40.0]}, ...]},
        ...
      ]
    }
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .applicability import _LOT_THRESHOLD_RE, _COMPARATOR_CANON  # shared grammar
from .domain_schema import text_words


# A band-defining header cell: a closed unit range ("1 to 3 Units"). Matrix
# tables are recognized by having >= 2 of these in one header row.
_BAND_HEADER_RE = re.compile(r"\b\d+\s*to\s*\d+\s*units?\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# Words that never discriminate a row ("maximum", "minimum", units...).
_LABEL_NOISE = {"maximum", "minimum", "m", "m2", "all", "for", "the", "of", "on", "and"}


def build_page_matrices(pdf_path: Path) -> dict[int, list[dict[str, Any]]]:
    """Recover matrix tables per 1-based page number. {} when no PDF/parser."""
    try:
        import pdfplumber
    except Exception:
        return {}
    if not Path(pdf_path).exists():
        return {}

    matrices: dict[int, list[dict[str, Any]]] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_tables = []
            for table in page.find_tables():
                matrix = _matrix_from_table(page, table)
                if matrix is not None:
                    matrix["page"] = page_number
                    page_tables.append(matrix)
            if page_tables:
                matrices[page_number] = page_tables
    return matrices


def anchor_evidence(
    evidence_units: list[dict[str, Any]],
    matrices: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Attach matrix_anchor to table evidence with a UNIQUE row match.

    Containment-only matching (every distinctive row_header word must appear
    in the matrix row label) tolerates the fragmented headers observed in
    real evidence; an ambiguous match (0 or 2+ rows) attaches nothing — the
    anchor layer is allowed to be inert, never allowed to guess.
    """
    anchored = 0
    ambiguous = 0
    report_rows: list[dict[str, Any]] = []
    all_rows = [
        (matrix, row)
        for page_tables in matrices.values()
        for matrix in page_tables
        for row in matrix["rows"]
    ]
    for evidence in evidence_units:
        if str(evidence.get("evidence_type") or "") not in {"table_cell", "table_row", "table_evidence"}:
            continue
        wanted = _distinctive_words(
            f"{evidence.get('table_title') or ''} {evidence.get('row_header') or ''}"
        )
        if not wanted:
            continue
        matches = [
            (matrix, row)
            for matrix, row in all_rows
            if wanted <= row["label_words"]
        ]
        if len(matches) > 1:
            # Deterministic tie-break: sibling rows under one section header
            # ("Maximum Height | ... | Height" vs "... | Storeys") share
            # every word the evidence carries. If exactly one of them holds
            # the evidence's own cell number, that row is the source.
            cell_numbers = [
                float(number)
                for number in _NUMBER_RE.findall(str(evidence.get("cell_value") or "").replace(",", ""))
            ]
            if cell_numbers:
                narrowed = [
                    (matrix, row)
                    for matrix, row in matches
                    if any(
                        any(abs(number - candidate) <= 0.01 for number in (cell.get("numbers") or []))
                        for cell in row["cells"].values()
                        for candidate in cell_numbers[:1]
                    )
                ]
                if len(narrowed) == 1:
                    matches = narrowed
        if len(matches) == 1:
            matrix, row = matches[0]
            evidence["matrix_anchor"] = {
                "page": matrix["page"],
                "row_label": row["label"],
                "bands": [
                    {
                        "key": band_key,
                        "header_text": matrix["bands"][band_key]["header_text"],
                        **cell,
                    }
                    for band_key, cell in sorted(row["cells"].items())
                ],
            }
            anchored += 1
            report_rows.append(
                {
                    "evidence_id": evidence.get("evidence_id"),
                    "row_label": row["label"],
                    "page": matrix["page"],
                    "bands": len(row["cells"]),
                }
            )
        elif len(matches) > 1:
            ambiguous += 1
    return {
        "anchored": anchored,
        "ambiguous_skipped": ambiguous,
        "rows": report_rows,
    }


def _matrix_from_table(page: Any, table: Any) -> dict[str, Any] | None:
    grid = table.extract()
    if not grid or len(grid) < 3:
        return None

    # 1) Band definitions: the row holding >= 2 closed unit-range headers.
    band_row_index, bands = _find_bands(page, table, grid)
    if bands is None:
        return None

    # 2) Band header stacks: per-band crop text (clean per-band content such
    #    as "1 to 2 Units" / "Frequent Transit Network Area Only") plus
    #    gap-split word segments from the header region, assigned to every
    #    band they overlap — that is how a phrase rendered once across three
    #    columns ("Small-Scale Multi-Unit") reaches all three stacks without
    #    glyph clipping.
    header_bottom = _first_data_top(table, band_row_index, grid, bands[0]["x0"])
    _attach_header_stacks(page, table, bands, header_bottom)

    # 3) Data rows below the band header row, with section context and
    #    continuation-row merging (the second branch of a conditional cell
    #    arrives as its own thin row with an empty label).
    rows = _data_rows(table, grid, band_row_index, bands)
    if not rows:
        return None
    return {"bands": bands, "rows": rows}


def _find_bands(page: Any, table: Any, grid: list[list[Any]]) -> tuple[int, list[dict[str, Any]] | None]:
    for row_index, row in enumerate(table.rows):
        candidates = []
        for cell in row.cells:
            if cell is None:
                continue
            text = _cell_text(grid, table, row_index, cell)
            if text and _BAND_HEADER_RE.search(text):
                candidates.append({"x0": float(cell[0]), "x1": float(cell[2])})
        if len(candidates) >= 2:
            candidates.sort(key=lambda band: band["x0"])
            # Close the gaps between adjacent bands (border slivers like
            # [472-477] belong to the band on their right).
            for left, right in zip(candidates, candidates[1:]):
                middle = (left["x1"] + right["x0"]) / 2
                left["x1"] = middle
                right["x0"] = middle
            for key, band in enumerate(candidates):
                band["key"] = key
                band["header_text"] = ""
            return row_index, candidates
    return -1, None


def _attach_header_stacks(page: Any, table: Any, bands: list[dict[str, Any]], header_bottom: float) -> None:
    top = float(table.bbox[1])
    page_x0 = max(float(table.bbox[0]), float(page.bbox[0]))
    page_x1 = min(float(table.bbox[2]), float(page.bbox[2]))
    try:
        region = page.crop((page_x0, max(top, float(page.bbox[1])), page_x1, header_bottom))
        words = region.extract_words()
    except Exception:
        words = []

    # Group words into y-lines, split each line into segments at x-gaps.
    lines: list[tuple[float, list[dict[str, Any]]]] = []
    for word in sorted(words, key=lambda w: float(w["top"])):
        top = float(word["top"])
        if lines and abs(lines[-1][0] - top) <= 3:
            lines[-1][1].append(word)
        else:
            lines.append((top, [word]))
    segments: list[dict[str, Any]] = []
    for _, line_words in lines:
        line_words.sort(key=lambda w: float(w["x0"]))
        current: list[dict[str, Any]] = []
        for word in line_words:
            if current and float(word["x0"]) - float(current[-1]["x1"]) > 15:
                segments.append(_segment(current))
                current = []
            current.append(word)
        if current:
            segments.append(_segment(current))

    for segment in segments:
        touched = []
        for band in bands:
            overlap = min(band["x1"], segment["x1"]) - max(band["x0"], segment["x0"])
            if overlap > 5:
                touched.append((band, overlap))
        if not touched:
            continue
        if len(touched) >= 2:
            # A phrase rendered once across several columns ("Small-Scale
            # Multi-Unit" spanning three unit buckets) belongs to every band
            # it touches — narrow per-band thresholds would drop it from the
            # edge bands and break selector->band resolution there.
            recipients = [band for band, _ in touched]
        else:
            band, overlap = touched[0]
            width = segment["x1"] - segment["x0"]
            recipients = (
                [band]
                if overlap >= 0.5 * width or overlap >= 0.5 * (band["x1"] - band["x0"])
                else []
            )
        for band in recipients:
            band["_parts"] = [*band.get("_parts", []), segment["text"]]
    for band in bands:
        band["header_text"] = " | ".join(band.pop("_parts", []))


def _segment(words: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "text": " ".join(str(word["text"]) for word in words),
        "x0": float(words[0]["x0"]),
        "x1": float(words[-1]["x1"]),
    }


def _first_data_top(table: Any, band_row_index: int, grid: list[list[Any]], label_limit: float) -> float:
    # The header region extends past the band row: stacked header lines
    # ("Frequent Transit / Network Area Only") render as their own thin rows
    # with no label. Data starts at the first row that has a non-empty
    # LABEL-column cell.
    for row_index in range(band_row_index + 1, len(table.rows)):
        for cell, text in zip(table.rows[row_index].cells, grid[row_index]):
            if cell is None or not str(text or "").strip():
                continue
            if float(cell[2]) <= label_limit + 1:
                return float(cell[1])
    return float(table.bbox[3])


def _data_rows(
    table: Any,
    grid: list[list[Any]],
    band_row_index: int,
    bands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    label_limit = bands[0]["x0"]
    rows: list[dict[str, Any]] = []
    section: list[str] = []
    first_data_top = _first_data_top(table, band_row_index, grid, label_limit)

    # The band-definition row is ALSO a data row: "Permitted Dwelling Units |
    # 1 to 3 Units | 1 to 2 Units | ..." states the per-column dwelling-unit
    # ranges. Synthesize it so unit-count candidates can anchor and bind.
    band_row_label = " ".join(
        str(text).strip()
        for cell, text in zip(table.rows[band_row_index].cells, grid[band_row_index])
        if cell is not None and str(text or "").strip() and float(cell[2]) <= label_limit + 1
    ).replace("\n", " ")
    if band_row_label:
        band_cells: dict[int, dict[str, Any]] = {}
        for cell, text in zip(table.rows[band_row_index].cells, grid[band_row_index]):
            if cell is None or not str(text or "").strip():
                continue
            if float(cell[2]) <= label_limit + 1:
                continue
            for key in _bands_for_cell(float(cell[0]), float(cell[2]), bands):
                band_cells.setdefault(key, {"text": str(text).strip(), "spans_all": False})
        if band_cells:
            entry = {
                "label": band_row_label,
                "label_words": _distinctive_words(band_row_label),
                "cells": band_cells,
            }
            _finalize_cells(entry)
            rows.append(entry)

    for row_index in range(band_row_index + 1, len(table.rows)):
        row_tops = [float(cell[1]) for cell in table.rows[row_index].cells if cell]
        if row_tops and min(row_tops) < first_data_top - 1:
            # Header-tail row (stacked column-header lines like "Frequent
            # Transit / Network Area Only") — already in the band stacks.
            continue
        row = table.rows[row_index]
        label_parts: list[str] = []
        banner_parts: list[str] = []
        band_cells: dict[int, dict[str, Any]] = {}
        for cell, text in zip(row.cells, grid[row_index]):
            if cell is None or not str(text or "").strip():
                continue
            cell_text = str(text).strip()
            x0, x1 = float(cell[0]), float(cell[2])
            if x0 < label_limit - 20 and x1 >= bands[0]["x1"]:
                # Full-width section banner ("Maximum Lot Coverage"): becomes
                # row context for the rows beneath, never a data cell.
                banner_parts.append(cell_text)
                continue
            if x1 <= label_limit + 1:
                if cell_text not in label_parts:
                    label_parts.append(cell_text)
                continue
            keys = _bands_for_cell(x0, x1, bands)
            if not keys:
                continue
            spans_all = len(keys) == len(bands)
            for key in keys:
                existing = band_cells.get(key)
                if existing:
                    existing["text"] = f"{existing['text']}\n{cell_text}"
                else:
                    band_cells[key] = {"text": cell_text, "spans_all": spans_all}

        if banner_parts and not band_cells and not label_parts:
            banner = " ".join(banner_parts).strip()
            section = [banner] if not _looks_like_subsection(banner) else (section[:1] + [banner])
            continue

        label = " ".join(label_parts).strip()
        if label and not band_cells:
            # Section header row ("Maximum Lot Coverage", "Front Principal
            # Buildings"): becomes context for the rows beneath it.
            section = [label] if not _looks_like_subsection(label) else (section[:1] + [label])
            continue
        if not band_cells:
            continue
        if not label and rows:
            # Continuation row: merge into the previous data row's cells
            # (the second branch of a conditional cell).
            for key, cell in band_cells.items():
                target = rows[-1]["cells"].get(key)
                if target:
                    target["text"] = f"{target['text']}\n{cell['text']}"
                else:
                    rows[-1]["cells"][key] = cell
            _finalize_cells(rows[-1])
            continue

        full_label = " | ".join([*section, label]) if label else " | ".join(section)
        entry = {
            "label": full_label,
            "label_words": _distinctive_words(full_label) | _distinctive_words(label),
            "cells": band_cells,
        }
        _finalize_cells(entry)
        rows.append(entry)
    return rows


def _finalize_cells(row: dict[str, Any]) -> None:
    for cell in row["cells"].values():
        text = cell["text"]
        cell["numbers"] = [float(number) for number in _NUMBER_RE.findall(text.replace(",", ""))]
        cell["branches"] = _branches(text)


def _branches(cell_text: str) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    for line in cell_text.splitlines():
        match = _LOT_THRESHOLD_RE.search(line)
        if not match:
            continue
        tail = line[match.end() :].lstrip(" :")
        branches.append(
            {
                "condition_text": line[: match.end()].strip(),
                "comparator": _COMPARATOR_CANON.get(match.group(1), match.group(1)),
                "threshold": float(match.group(2)),
                "value_text": tail.strip(),
                "numbers": [float(number) for number in _NUMBER_RE.findall(tail)],
            }
        )
    return branches


def _bands_for_cell(x0: float, x1: float, bands: list[dict[str, Any]]) -> list[int]:
    keys = []
    for band in bands:
        overlap = min(band["x1"], x1) - max(band["x0"], x0)
        band_width = band["x1"] - band["x0"]
        cell_width = max(x1 - x0, 1.0)
        if overlap > 0 and (overlap >= 0.5 * band_width or overlap >= 0.8 * cell_width):
            keys.append(band["key"])
    return keys


def _looks_like_subsection(label: str) -> bool:
    # "Front Principal Buildings" under "Maximum Height" — heuristically, a
    # subsection names a building/feature rather than starting with a
    # Maximum/Minimum regulation phrase.
    first = label.split()[0].lower() if label.split() else ""
    return first not in {"maximum", "minimum", "permitted", "impervious"}


def _distinctive_words(text: str) -> set[str]:
    return {word for word in text_words(text) if word not in _LABEL_NOISE and not word.isdigit()}


def _cell_text(grid: list[list[Any]], table: Any, row_index: int, cell: tuple) -> str:
    try:
        column_index = table.rows[row_index].cells.index(cell)
    except ValueError:
        return ""
    value = grid[row_index][column_index] if column_index < len(grid[row_index]) else None
    return str(value or "")
