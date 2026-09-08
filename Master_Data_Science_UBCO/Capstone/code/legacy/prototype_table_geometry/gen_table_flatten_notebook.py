#!/usr/bin/env python3
"""Generate the geometry-first table-flattening prototype notebook.

Run: python gen_table_flatten_notebook.py
Produces: table_flatten_prototype.ipynb in this directory.

The notebook is deterministic-first: PyMuPDF reconstructs the table grid and
classifies structure, and a local Ollama LLM (qwen3.5:9b by default) is called
only to review ambiguous structure decisions. It never rewrites the table or
invents values.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).resolve().parent / "table_flatten_prototype.ipynb"

cells: list = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(dedent(text).strip("\n")))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(dedent(text).strip("\n")))


# ---------------------------------------------------------------- title
md(
    """
    # Geometry-first table flattening (zoning bylaw tables)

    A debuggable prototype that:
    1. uses **PyMuPDF** to extract table geometry and reconstruct the grid,
    2. **deterministically** classifies row types, builds column/row hierarchy, and
       detects merged / dash / ambiguous cells,
    3. calls a **local Ollama LLM (qwen3.5:9b)** *only* to review uncertain
       structure decisions, and
    4. emits **structured cell facts** (with evidence bbox), not a flat markdown table.

    Design rules: deterministic logic first; the LLM is a reviewer only; it never
    rewrites the table or invents values; dash `-` is preserved as an explicit value;
    every fact keeps its source bbox. Run one table first, then generalize.
    """
)

# ---------------------------------------------------------------- 1. setup
md("## 1. Setup")
code(
    """
    import json
    import re
    from pathlib import Path

    import fitz  # PyMuPDF
    import pandas as pd
    import requests

    try:
        import matplotlib.pyplot as plt
        from matplotlib import patches
        HAS_MPL = True
    except Exception as exc:  # pragma: no cover
        HAS_MPL = False
        print("matplotlib unavailable, overlays will be skipped:", exc)

    pd.set_option("display.max_colwidth", 80)
    pd.set_option("display.max_rows", 200)
    """
)
code(
    """
    # ---- Config -------------------------------------------------------------
    def _first_existing(*candidates):
        for c in candidates:
            p = Path(c)
            if p.exists():
                return p.resolve()
        return Path(candidates[0]).resolve()

    # Default points at the Burnaby R1 Development Regulations table (page index 1).
    PDF_PATH = _first_existing(
        "../prototype_pipeline/pdfs/R1Small-Scale-Multi-Unit-Housing-District.pdf",
        "prototype_pipeline/pdfs/R1Small-Scale-Multi-Unit-Housing-District.pdf",
        "code/prototype_pipeline/pdfs/R1Small-Scale-Multi-Unit-Housing-District.pdf",
    )
    PAGE_INDEX = 1          # 0-based page index
    TABLE_INDEX = 0         # which detected table on the page to flatten
    OUTPUT_DIR = Path("outputs/table_flatten")
    RENDER_SCALE = 3.0      # pixmap scale; bbox(px) = bbox(pt) * RENDER_SCALE

    LOCAL_LLM_ENDPOINT = "http://localhost:11434/api/chat"   # Ollama
    LOCAL_LLM_MODEL = "qwen3.5:9b"
    ENABLE_LLM_REVIEW = True
    LLM_TIMEOUT = 300            # generous: first call also pays model cold-load
    LLM_KEEP_ALIVE = "15m"       # keep the model resident between per-cell calls
    LLM_DISABLE_THINKING = True  # Qwen3 'thinking' is slow & unneeded for JSON review
    LLM_NUM_PREDICT = 768        # cap output tokens; the review JSON is small

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("PDF_PATH       :", PDF_PATH, "(exists:", PDF_PATH.exists(), ")")
    print("PAGE_INDEX     :", PAGE_INDEX, "TABLE_INDEX:", TABLE_INDEX)
    print("OUTPUT_DIR     :", OUTPUT_DIR.resolve())
    print("LOCAL_LLM_MODEL:", LOCAL_LLM_MODEL, "@", LOCAL_LLM_ENDPOINT)
    print("ENABLE_LLM_REVIEW:", ENABLE_LLM_REVIEW)
    """
)

# ---------------------------------------------------------------- 2. render
md(
    """
    ## 2. Page rendering and visual preview
    Render the page so we can manually check whether detected cells align with the
    original table. Bbox coordinates are in PDF points; the image is scaled by
    `RENDER_SCALE`, so `pixel = point * RENDER_SCALE`.
    """
)
code(
    """
    doc = fitz.open(PDF_PATH)
    assert 0 <= PAGE_INDEX < doc.page_count, f"PAGE_INDEX out of range (0..{doc.page_count-1})"
    page = doc[PAGE_INDEX]
    page_rect = page.rect
    print("page size (pt):", round(page_rect.width, 1), "x", round(page_rect.height, 1))

    pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE), alpha=False)
    preview_path = OUTPUT_DIR / "page_preview.png"
    pix.save(preview_path)
    print("saved", preview_path)

    if HAS_MPL:
        img = plt.imread(preview_path)
        plt.figure(figsize=(11, 15))
        plt.imshow(img)
        plt.axis("off")
        plt.title(f"page {PAGE_INDEX}")
        plt.show()
    """
)

# ---------------------------------------------------------------- 3. raw extract
md(
    """
    ## 3. Raw PyMuPDF table extraction
    `page.find_tables()` only — no flattening yet. We print each table's bbox / size
    and preview its raw grid. Note: PyMuPDF returns `None` for cells merged into a
    neighbour (e.g. a dwelling-type header spanning sub-columns).
    """
)
code(
    """
    table_finder = page.find_tables()
    tables = table_finder.tables
    print("tables detected on page:", len(tables))

    for i, t in enumerate(tables):
        data = t.extract()
        n_rows = len(data)
        n_cols = max((len(r) for r in data), default=0)
        print(f"\\n--- table {i} | bbox={tuple(round(v,1) for v in t.bbox)} | "
              f"rows={getattr(t,'row_count',n_rows)} cols={getattr(t,'col_count',n_cols)} ---")
        display(pd.DataFrame(data))

    assert tables, "No tables detected. Try a different PAGE_INDEX or render/inspect the page."
    assert 0 <= TABLE_INDEX < len(tables), f"TABLE_INDEX out of range (0..{len(tables)-1})"
    table = tables[TABLE_INDEX]
    table_bbox = [float(v) for v in table.bbox]
    raw_data = table.extract()
    print("\\nselected TABLE_INDEX:", TABLE_INDEX, "bbox:", [round(v,1) for v in table_bbox])
    """
)

# ---------------------------------------------------------------- 4. geometry
md(
    """
    ## 4. Geometry extraction (text spans)
    Pull every text span with its bbox/font size, then keep the spans that fall
    inside the selected table bbox. This is the raw geometry we fall back to if
    PyMuPDF cell geometry is unreliable.
    """
)
code(
    """
    def _overlaps(b, box, tol=1.0):
        # b = [x0,y0,x1,y1] span; box = table bbox; require centre inside box.
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return (box[0] - tol) <= cx <= (box[2] + tol) and (box[1] - tol) <= cy <= (box[3] + tol)

    spans = []
    raw = page.get_text("dict")
    for bi, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for li, line in enumerate(block.get("lines", [])):
            for si, span in enumerate(line.get("spans", [])):
                bb = [float(v) for v in span["bbox"]]
                spans.append({
                    "text": span.get("text", ""),
                    "x0": bb[0], "y0": bb[1], "x1": bb[2], "y1": bb[3],
                    "bbox": bb,
                    "block": bi, "line": li, "span": si,
                    "size": round(float(span.get("size", 0)), 2),
                })

    spans_df = pd.DataFrame(spans)
    print("total spans on page:", len(spans_df))

    inside_mask = spans_df["bbox"].apply(lambda b: _overlaps(b, table_bbox))
    spans_inside = (spans_df[inside_mask]
                    .sort_values(["y0", "x0"])
                    .reset_index(drop=True))
    print("spans inside table bbox:", len(spans_inside))
    display(spans_inside[["text", "x0", "y0", "x1", "y1", "size"]].head(40))
    """
)

# ---------------------------------------------------------------- 5. grid
md(
    """
    ## 5. Reconstruct grid
    Prefer PyMuPDF cell geometry (`table.rows[r].cells`); fall back to clustering
    span positions into row/column boundaries if cell geometry is missing. Produces
    a rectangular grid with stable `(row, col)` indices. `-` is **not** empty.
    """
)
code(
    """
    DASH_TOKENS = {"-", "\\u2013", "\\u2014", "\\u2212"}  # hyphen, en/em dash, minus

    def _is_dash(text):
        return str(text).strip() in DASH_TOKENS

    def _is_blank(text):
        return text is None or (str(text).strip() == "" and not _is_dash(text))

    def build_grid_from_pymupdf(table):
        # Keep the clean PyMuPDF text grid as canonical; PyMuPDF often omits bbox
        # geometry for merged/empty cells, so we INFER missing bboxes from the
        # row y-band and column x-band of the cells that do carry geometry. This
        # preserves stable (row, col) indices instead of discarding a good grid.
        data = table.extract()
        n_rows = len(data)
        n_cols = max((len(r) for r in data), default=0)
        rows_geo = getattr(table, "rows", None) or []

        raw_bbox = [[None] * n_cols for _ in range(n_rows)]
        for r in range(n_rows):
            rc = getattr(rows_geo[r], "cells", []) if r < len(rows_geo) else []
            for c in range(n_cols):
                if c < len(rc) and rc[c] is not None:
                    raw_bbox[r][c] = [float(v) for v in rc[c]]

        row_y, col_x = {}, {}
        for r in range(n_rows):
            ys = [(b[1], b[3]) for b in raw_bbox[r] if b]
            if ys:
                row_y[r] = (min(a for a, _ in ys), max(b for _, b in ys))
            elif r < len(rows_geo) and getattr(rows_geo[r], "bbox", None):
                bb = rows_geo[r].bbox
                row_y[r] = (float(bb[1]), float(bb[3]))
        for c in range(n_cols):
            xs = [(raw_bbox[r][c][0], raw_bbox[r][c][2]) for r in range(n_rows) if raw_bbox[r][c]]
            if xs:
                col_x[c] = (min(a for a, _ in xs), max(b for _, b in xs))

        cells, filled = [], 0
        for r in range(n_rows):
            for c in range(n_cols):
                text = data[r][c] if c < len(data[r]) else None
                bbox = raw_bbox[r][c]
                if bbox is None and r in row_y and c in col_x:
                    bbox = [col_x[c][0], row_y[r][0], col_x[c][1], row_y[r][1]]
                if bbox:
                    filled += 1
                cells.append({
                    "row": r, "col": c,
                    "bbox": bbox,
                    "text": "" if text is None else str(text),
                    "is_empty": _is_blank(text),
                    "is_dash": _is_dash(text),
                })
        return cells, n_rows, n_cols, filled

    def _cluster(values, tol):
        vals = sorted(values)
        bounds = []
        for v in vals:
            if not bounds or v - bounds[-1] > tol:
                bounds.append(v)
        return bounds

    def build_grid_from_spans(spans_inside, table_bbox, row_tol=4.0, col_tol=8.0):
        # Fallback: cluster span centres into row/col bands. Coarser but resilient.
        ys = _cluster([(s["y0"] + s["y1"]) / 2 for _, s in spans_inside.iterrows()], row_tol)
        xs = _cluster([s["x0"] for _, s in spans_inside.iterrows()], col_tol)
        def band(value, bounds):
            idx = 0
            for i, b in enumerate(bounds):
                if value >= b:
                    idx = i
            return idx
        grid_text = {}
        for _, s in spans_inside.iterrows():
            r = band((s["y0"] + s["y1"]) / 2, ys)
            c = band(s["x0"], xs)
            grid_text.setdefault((r, c), []).append((s["x0"], s["text"], s["bbox"]))
        cells = []
        for r in range(len(ys)):
            for c in range(len(xs)):
                items = sorted(grid_text.get((r, c), []))
                text = " ".join(t for _, t, _ in items).strip()
                bbox = None
                if items:
                    xs0 = [b[0] for _, _, b in items]; ys0 = [b[1] for _, _, b in items]
                    xs1 = [b[2] for _, _, b in items]; ys1 = [b[3] for _, _, b in items]
                    bbox = [min(xs0), min(ys0), max(xs1), max(ys1)]
                cells.append({"row": r, "col": c, "bbox": bbox, "text": text,
                              "is_empty": _is_blank(text), "is_dash": _is_dash(text)})
        return cells, len(ys), len(xs), sum(1 for c in cells if c["bbox"])

    grid_cells, n_rows, n_cols, filled = build_grid_from_pymupdf(table)
    coverage = filled / max(1, n_rows * n_cols)
    print(f"PyMuPDF grid: {n_rows} rows x {n_cols} cols, bbox coverage after inference={coverage:.0%}")
    if n_rows == 0 or n_cols == 0:
        print("PyMuPDF produced no usable grid -> falling back to span-clustered grid.")
        grid_cells, n_rows, n_cols, _ = build_grid_from_spans(spans_inside, table_bbox)
        print(f"Span grid: {n_rows} rows x {n_cols} cols")

    grid_df = pd.DataFrame(grid_cells)
    display(grid_df[["row", "col", "text", "is_empty", "is_dash"]].head(60))
    """
)

# ---------------------------------------------------------------- 6. overlay
md(
    """
    ## 6. Visual cell overlay
    Draw the reconstructed cells over the rendered page so you can debug whether the
    geometry matches the real table. Saves `cell_overlay.png`.
    """
)
code(
    """
    cell_overlay_path = OUTPUT_DIR / "cell_overlay.png"
    if HAS_MPL:
        img = plt.imread(preview_path)
        fig, ax = plt.subplots(figsize=(13, 17))
        ax.imshow(img)
        # table bbox in green
        tx0, ty0, tx1, ty1 = [v * RENDER_SCALE for v in table_bbox]
        ax.add_patch(patches.Rectangle((tx0, ty0), tx1 - tx0, ty1 - ty0,
                                       fill=False, edgecolor="lime", lw=1.5))
        for cell in grid_cells:
            if not cell["bbox"]:
                continue
            x0, y0, x1, y1 = [v * RENDER_SCALE for v in cell["bbox"]]
            ax.add_patch(patches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                                           fill=False, edgecolor="red", lw=0.4))
            ax.text(x0 + 1, y0 + 9, f"{cell['row']},{cell['col']}",
                    fontsize=4.5, color="blue")
        ax.axis("off")
        ax.set_title("green = table bbox, red = reconstructed cells")
        fig.savefig(cell_overlay_path, dpi=150, bbox_inches="tight")
        plt.show()
        print("saved", cell_overlay_path)
    else:
        print("matplotlib unavailable - skipped overlay")
    """
)

# ---------------------------------------------------------------- 7. row types
md(
    """
    ## 7. Detect structural row types (deterministic)
    Classify each row into `column_header`, `section_header`, `row_group_header`,
    `data_row`, or `blank_or_noise`. Low-confidence / ambiguous rows are flagged
    `needs_llm_review`.
    """
)
code(
    """
    SECTION_KEYWORDS = [
        "maximum height", "minimum lot line setbacks", "minimum separation",
        "permitted dwelling units", "minimum lot area", "maximum lot area",
        "maximum lot coverage", "subdivision regulations", "permitted uses",
        "development regulations", "access and fire safety", "impervious",
    ]
    ROW_GROUP_KEYWORDS = [
        "front principal", "rear principal", "accessory building", "all buildings",
        "street yard", "lane yard", "interior rear yard", "interior side yard",
        "principal building", "between", "height", "storeys",
    ]
    HEADER_HINTS = ["dwelling type", "rowhouse", "small-scale", "units", "unit",
                    "transit", "type"]
    COMPLEX_CUES = ["except", "only", "where", "if ", "provided", "unless", "notwithstanding"]

    def _row_texts(grid_df, r):
        cs = grid_df[grid_df["row"] == r].sort_values("col")
        return list(cs["text"]), list(cs["is_dash"])

    def _has_kw(text, kws):
        t = text.lower()
        return any(k in t for k in kws)

    def leading_header_rows(grid_df, n_rows):
        # Matrix-style bylaw tables put column headers in the top rows, whose label
        # column (col 0) is blank; data rows carry a label there. The header band is
        # the leading run of rows with an empty first column.
        band = []
        for r in range(n_rows):
            first = grid_df[(grid_df["row"] == r) & (grid_df["col"] == 0)]
            ft = first.iloc[0]["text"].strip() if len(first) else ""
            if ft == "":
                band.append(r)
            else:
                break
        return band

    def classify_rows(grid_df, n_rows, n_cols):
        header_band = set(leading_header_rows(grid_df, n_rows))
        out = []
        for r in range(n_rows):
            texts, dashes = _row_texts(grid_df, r)
            non_empty = [(i, t) for i, t in enumerate(texts)
                         if (t and t.strip() != "") or (i < len(dashes) and dashes[i])]
            non_empty_count = len(non_empty)
            joined = " | ".join(t for t in texts if t and t.strip())
            first_text = texts[0].strip() if texts else ""
            numeric_cells = sum(1 for t in texts if re.search(r"\\d", t or ""))
            span_pattern = "".join("X" if (t and t.strip()) else "." for t in texts)

            row_type, conf, reason = "data_row", 0.6, "default"
            needs = False

            if r in header_band and non_empty_count > 0:
                # Top band with empty label column -> column header (even if it
                # contains digits, e.g. "1 to 3 Units").
                row_type, conf, reason = "column_header", 0.85, "leading row, empty label column"
            elif non_empty_count == 0:
                row_type, conf, reason = "blank_or_noise", 0.9, "no non-empty cells"
            elif non_empty_count == 1 and numeric_cells == 0:
                # single label spanning the row -> a header of some kind
                if _has_kw(first_text or joined, SECTION_KEYWORDS):
                    row_type, conf, reason = "section_header", 0.85, "section keyword, full-width label"
                elif _has_kw(first_text or joined, ROW_GROUP_KEYWORDS):
                    row_type, conf, reason = "row_group_header", 0.8, "row-group keyword, full-width label"
                else:
                    row_type, conf, reason = "section_header", 0.45, "full-width label, unknown keyword"
                    needs = True
            elif r <= 2 and numeric_cells == 0 and _has_kw(joined, HEADER_HINTS):
                row_type, conf, reason = "column_header", 0.8, "top row, header-like text, no numbers"
            elif first_text and numeric_cells >= 1:
                row_type, conf, reason = "data_row", 0.75, "label + numeric value cells"
                if _has_kw(joined, ROW_GROUP_KEYWORDS) and numeric_cells == 0:
                    row_type, conf = "row_group_header", 0.6
            else:
                # ambiguous: label present but no obvious values, or mixed
                if _has_kw(joined, SECTION_KEYWORDS):
                    row_type, conf, reason = "section_header", 0.6, "section keyword"
                elif _has_kw(joined, ROW_GROUP_KEYWORDS):
                    row_type, conf, reason = "row_group_header", 0.55, "row-group keyword"
                else:
                    row_type, conf, reason = "data_row", 0.4, "ambiguous structure"
                    needs = True

            if _has_kw(joined, COMPLEX_CUES):
                needs = True
                reason += "; contains exception/condition cue"
            if conf < 0.55:
                needs = True

            out.append({
                "row_index": r, "row_text": joined[:160],
                "non_empty_count": non_empty_count, "numeric_cells": numeric_cells,
                "span_pattern": span_pattern,
                "deterministic_row_type": row_type, "confidence": round(conf, 2),
                "needs_llm_review": needs, "reason": reason,
            })
        return pd.DataFrame(out)

    row_class_df = classify_rows(grid_df, n_rows, n_cols)
    display(row_class_df)
    """
)

# ---------------------------------------------------------------- 8. column hierarchy
md(
    """
    ## 8. Detect column hierarchy (multi-level paths)
    Identify the top header rows, then for each leaf column walk the header rows
    top-to-bottom, assigning a header cell to a column when their x-ranges overlap
    (this captures horizontally-merged parent headers). Condition-like header text
    (e.g. *Frequent Transit Network Area Only*) is preserved as a path component.
    """
)
code(
    """
    CONDITION_HEADER_CUES = ["only", "transit", "area", "where", "if ", "except"]

    def column_x_ranges(grid_df, n_rows, n_cols):
        # Per-column x-range from the data row that has the most cell bboxes.
        best_row, best = None, -1
        for r in range(n_rows):
            cs = grid_df[(grid_df["row"] == r)]
            cnt = cs["bbox"].apply(lambda b: b is not None).sum()
            if cnt > best:
                best, best_row = cnt, r
        ranges = {}
        for c in range(n_cols):
            xs0, xs1 = [], []
            for r in range(n_rows):
                cell = grid_df[(grid_df["row"] == r) & (grid_df["col"] == c)]
                if len(cell) and cell.iloc[0]["bbox"]:
                    b = cell.iloc[0]["bbox"]; xs0.append(b[0]); xs1.append(b[2])
            if xs0:
                ranges[c] = (min(xs0), max(xs1))
        return ranges

    def _x_overlap(a, b):
        lo = max(a[0], b[0]); hi = min(a[1], b[1])
        inter = max(0.0, hi - lo)
        return inter / max(1e-6, (b[1] - b[0]))   # fraction of column covered

    def build_column_hierarchy(grid_df, row_class_df, n_rows, n_cols):
        header_rows = list(row_class_df[row_class_df["deterministic_row_type"] == "column_header"]["row_index"])
        if not header_rows:
            header_rows = leading_header_rows(grid_df, n_rows) or [r for r in range(min(3, n_rows))]
        col_ranges = column_x_ranges(grid_df, n_rows, n_cols)

        # which columns actually carry values (skip the label column 0 + empties)
        value_cols = [c for c in range(n_cols) if c in col_ranges]
        hierarchy = []
        for c in value_cols:
            crange = col_ranges[c]
            path = []
            for hr in header_rows:
                # collect header cells in this row that overlap column c
                best_text, best_cov = "", 0.0
                for cc in range(n_cols):
                    cell = grid_df[(grid_df["row"] == hr) & (grid_df["col"] == cc)]
                    if not len(cell):
                        continue
                    cell = cell.iloc[0]
                    txt = (cell["text"] or "").strip()
                    if not txt or not cell["bbox"]:
                        continue
                    cov = _x_overlap((cell["bbox"][0], cell["bbox"][2]), crange)
                    if cov > best_cov and cov > 0.35:
                        best_cov, best_text = cov, txt
                if best_text and (not path or path[-1] != best_text):
                    path.append(best_text)
            hierarchy.append({
                "col": c,
                "x_range": [round(crange[0], 1), round(crange[1], 1)],
                "column_path": path,
                "has_condition_component": any(
                    any(cue in p.lower() for cue in CONDITION_HEADER_CUES) for p in path),
            })
        return hierarchy, header_rows

    column_hierarchy, header_rows = build_column_hierarchy(grid_df, row_class_df, n_rows, n_cols)
    print("header rows:", header_rows)
    display(pd.DataFrame(column_hierarchy))
    col_path_by_index = {h["col"]: h["column_path"] for h in column_hierarchy}
    """
)

# ---------------------------------------------------------------- 9. row hierarchy
md(
    """
    ## 9. Build row hierarchy
    Scan rows top-to-bottom, maintaining `active_section` and `active_row_group`.
    Each data row's `row_path = [active_section, active_row_group, row_label]`
    (dropping empty levels).
    """
)
code(
    """
    def build_row_paths(grid_df, row_class_df):
        active_section, active_group = None, None
        row_paths = {}
        for _, rc in row_class_df.sort_values("row_index").iterrows():
            r = int(rc["row_index"]); rtype = rc["deterministic_row_type"]
            texts, _ = _row_texts(grid_df, r)
            label = next((t.strip() for t in texts if t and t.strip()), "")
            if rtype == "section_header":
                active_section, active_group = label, None
                row_paths[r] = [active_section]
            elif rtype == "row_group_header":
                active_group = label
                row_paths[r] = [x for x in [active_section, active_group] if x]
            elif rtype == "data_row":
                row_paths[r] = [x for x in [active_section, active_group, label] if x]
            else:
                row_paths[r] = [x for x in [active_section, active_group] if x]
        return row_paths

    row_paths = build_row_paths(grid_df, row_class_df)
    display(pd.DataFrame([
        {"row_index": r, "row_type": row_class_df.loc[row_class_df.row_index == r, "deterministic_row_type"].iloc[0],
         "row_path": " > ".join(row_paths.get(r, []))}
        for r in range(n_rows)
    ]))
    """
)

# ---------------------------------------------------------------- 10. cell facts
md(
    """
    ## 10. Candidate cell facts + merged / ambiguous detection
    Build one candidate fact per value cell. We **do not** blindly forward-fill:
    section/group headers are never copied into value columns; `-` is kept; a value
    whose bbox spans several columns is marked `horizontal_merged_value` and
    duplicated only into the columns it actually overlaps; anything uncertain is
    flagged `needs_llm_review`.
    """
)
code(
    """
    def column_for_label(n_cols):
        return 0  # convention: first column holds the row label

    def candidate_cell_facts(grid_df, row_class_df, row_paths, col_path_by_index, n_rows, n_cols):
        col_ranges = column_x_ranges(grid_df, n_rows, n_cols)
        label_col = column_for_label(n_cols)
        # Only treat columns that carry a real header path as value columns; this
        # avoids emitting facts for spacer/empty columns of a wide raw grid.
        value_cols = [c for c, p in col_path_by_index.items() if c != label_col and p]
        if not value_cols:  # fallback: any non-label column with a known x-range
            value_cols = [c for c in col_ranges if c != label_col]
        facts = []
        for _, rc in row_class_df.iterrows():
            r = int(rc["row_index"]); rtype = rc["deterministic_row_type"]
            if rtype != "data_row":
                continue
            rpath = row_paths.get(r, [])
            for c in value_cols:
                cell = grid_df[(grid_df["row"] == r) & (grid_df["col"] == c)]
                if not len(cell):
                    continue
                cell = cell.iloc[0]
                value = (cell["text"] or "").strip()
                is_dash = bool(cell["is_dash"])
                bbox = cell["bbox"]

                span_type = "single_cell"
                needs = bool(rc["needs_llm_review"])
                reason = []

                # horizontal-merged value: this cell's bbox covers >1 column range
                covered = []
                if bbox:
                    for cc, crange in col_ranges.items():
                        if cc == label_col:
                            continue
                        if _x_overlap((bbox[0], bbox[2]), crange) > 0.5:
                            covered.append(cc)
                if len(covered) > 1 and value and not is_dash:
                    span_type = "horizontal_merged_value"
                    reason.append(f"value bbox spans columns {covered}")

                if value == "" and not is_dash:
                    # blank value cell: could be a merge inheritance -> let LLM judge
                    span_type = "blank"
                    needs = True
                    reason.append("blank value cell (possible merge/inherit)")

                if any(cue in value.lower() for cue in COMPLEX_CUES):
                    needs = True
                    reason.append("value contains exception/condition cue")
                if "|" in value:
                    reason.append("multi-condition value (|)")
                if is_dash:
                    reason.append("dash value (explicit, not blank)")

                facts.append({
                    "page": PAGE_INDEX, "table_index": TABLE_INDEX,
                    "row_index": r, "col_index": c,
                    "row_path": rpath,
                    "column_path": col_path_by_index.get(c, []),
                    "value": value,
                    "source_text": cell["text"] or "",
                    "source_bbox": bbox,
                    "span_type": span_type,
                    "is_dash": is_dash,
                    "needs_llm_review": needs,
                    "review_reason": "; ".join(reason) if reason else "deterministic",
                })
        return facts

    candidate_facts = candidate_cell_facts(grid_df, row_class_df, row_paths,
                                           col_path_by_index, n_rows, n_cols)
    print("candidate cell facts:", len(candidate_facts),
          "| flagged for review:", sum(f["needs_llm_review"] for f in candidate_facts))
    cand_df = pd.DataFrame(candidate_facts)
    if len(cand_df):
        cand_df["row_path_str"] = cand_df["row_path"].apply(" > ".join)
        cand_df["column_path_str"] = cand_df["column_path"].apply(" > ".join)
        display(cand_df[["row_index", "col_index", "row_path_str", "column_path_str",
                         "value", "span_type", "is_dash", "needs_llm_review", "review_reason"]].head(60))
    """
)

# ---------------------------------------------------------------- 11. LLM review
md(
    """
    ## 11. Local LLM review (Ollama / qwen3.5:9b)
    The LLM is a **structure reviewer only**: strict JSON out, never invents or
    changes values, preserves `-`. Called only for flagged cases (low confidence,
    full-width rows, merged values, header ambiguity, exception/condition cues,
    ambiguous dash). Run the connectivity check first.
    """
)
code(
    """
    def llm_health_check():
        try:
            tags = requests.get(LOCAL_LLM_ENDPOINT.replace("/api/chat", "/api/tags"), timeout=10)
            tags.raise_for_status()
            models = [m.get("name") for m in tags.json().get("models", [])]
            print("Ollama reachable. Models:", models)
            if LOCAL_LLM_MODEL not in models and f"{LOCAL_LLM_MODEL}:latest" not in models:
                print(f"WARNING: '{LOCAL_LLM_MODEL}' not in installed models. "
                      f"Pull it with:  ollama pull {LOCAL_LLM_MODEL}")
                return False
            return True
        except Exception as exc:
            print("Ollama NOT reachable:", exc)
            print("Start it with `ollama serve` and `ollama pull", LOCAL_LLM_MODEL, "`.")
            return False

    def llm_warm_up():
        # First call also pays the model cold-load; do it once here (timed) so the
        # per-cell review calls are fast. keep_alive holds the model in memory.
        import time as _time
        t0 = _time.time()
        try:
            body = {
                "model": LOCAL_LLM_MODEL,
                "messages": [{"role": "user", "content": 'Reply with JSON {"ok": true} only. /no_think'}],
                "stream": False, "format": "json", "keep_alive": LLM_KEEP_ALIVE,
                "options": {"temperature": 0, "num_predict": 32},
            }
            if LLM_DISABLE_THINKING:
                body["think"] = False
            r = requests.post(LOCAL_LLM_ENDPOINT, json=body, timeout=LLM_TIMEOUT)
            r.raise_for_status()
            print(f"warm-up OK in {_time.time()-t0:.1f}s; model loaded and resident ({LLM_KEEP_ALIVE}).")
            return True
        except Exception as exc:
            print(f"warm-up failed after {_time.time()-t0:.1f}s:", exc)
            print("If this was a timeout, raise LLM_TIMEOUT or pre-load with: "
                  f"`ollama run {LOCAL_LLM_MODEL}` once in a terminal.")
            return False

    LLM_AVAILABLE = False
    if ENABLE_LLM_REVIEW:
        LLM_AVAILABLE = llm_health_check() and llm_warm_up()
    """
)
code(
    '''
    LLM_SYSTEM_PROMPT = (
        "You are a careful table-structure reviewer for municipal zoning bylaw tables.\\n"
        "You are NOT extracting zoning rules yet. You ONLY review table structure.\\n"
        "Rules:\\n"
        "- Return STRICT JSON only. No prose, no markdown.\\n"
        "- Do NOT invent values. Do NOT change any numeric value.\\n"
        "- Preserve a dash '-' as an explicit value; never treat it as blank.\\n"
        "- If a value is exactly '-', you MUST return decision 'data_value' (it is an "
        "explicit not-applicable value), NEVER 'blank'.\\n"
        "- Classify each case as one of: section_header, row_group_header, data_value, "
        "column_header, blank, uncertain.\\n"
        "The user message contains a list of cases under 'cases'; each has a 'case_id'.\\n"
        'Return STRICT JSON {"reviews": [ ... ]} with ONE object per input case, in the '
        "same order, and each object MUST echo its case_id. Each review object is:\\n"
        "{\\n"
        '  "case_id": "<echo the input case_id>",\\n'
        '  "decision": "section_header|row_group_header|data_value|column_header|blank|uncertain",\\n'
        '  "applies_to_columns": [list of column indices this value applies to],\\n'
        '  "should_forward_fill": true/false,\\n'
        '  "should_duplicate_across_columns": true/false,\\n'
        '  "corrected_row_path": [strings] or null,\\n'
        '  "corrected_column_path": [strings] or null,\\n'
        '  "condition": "string or empty",\\n'
        '  "confidence": "high|medium|low",\\n'
        '  "reason": "short explanation"\\n'
        "}"
    )

    def _post_chat(user_content: str, num_predict: int) -> str:
        if LLM_DISABLE_THINKING:
            user_content = user_content + " /no_think"   # Qwen3 prompt switch
        body = {
            "model": LOCAL_LLM_MODEL,
            "messages": [
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False, "format": "json", "keep_alive": LLM_KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": num_predict},
        }
        if LLM_DISABLE_THINKING:
            body["think"] = False   # native flag on recent Ollama thinking models
        resp = requests.post(LOCAL_LLM_ENDPOINT, json=body, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        text = resp.json()["message"]["content"]
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def review_cases_with_local_llm(cases, batch_size=8):
        """Review MANY cases per call. This model is ~100s/call, so batching keeps
        total time sane (a few calls, not one per cell). Each case needs a unique
        'case_id'; returns {case_id: review_dict}."""
        import time as _t
        results = {}
        for start in range(0, len(cases), batch_size):
            chunk = cases[start:start + batch_size]
            t0 = _t.time()
            try:
                text = _post_chat(json.dumps({"cases": chunk}, ensure_ascii=False),
                                  num_predict=160 * len(chunk) + 256)
                reviews = json.loads(text).get("reviews", [])
                got = 0
                for rev in reviews:
                    cid = rev.get("case_id")
                    if cid is not None:
                        results[str(cid)] = rev
                        got += 1
                print(f"  cases {start}..{start+len(chunk)-1}: {got}/{len(chunk)} reviewed in {_t.time()-t0:.0f}s")
            except Exception as exc:
                print(f"  cases {start}..{start+len(chunk)-1} FAILED in {_t.time()-t0:.0f}s: {exc}")
        return results

    def review_table_structure_with_local_llm(case_payload: dict) -> dict:
        """Single-case helper (used by the smoke test); delegates to the batch path."""
        case = dict(case_payload); case.setdefault("case_id", "demo")
        out = review_cases_with_local_llm([case], batch_size=1)
        return out.get("demo", {"decision": "uncertain", "reason": "no review returned"})

    # quick smoke test on one synthetic case (only if reachable)
    if LLM_AVAILABLE:
        demo = {
            "case_id": "demo",
            "row_text": "Maximum Height", "full_width": True, "value": "Maximum Height",
            "neighbouring_rows": ["Front Principal Buildings", "Height"],
            "column_path_guess": [],
            "question": "Is this a section_header, row_group_header, or data_value?",
        }
        try:
            print(json.dumps(review_table_structure_with_local_llm(demo), indent=2, ensure_ascii=False))
        except Exception as exc:
            print("LLM smoke test failed:", exc)
    '''
)

# ---------------------------------------------------------------- 12. apply review
md(
    """
    ## 12. Apply LLM review results
    Collect the flagged cells, review them in **batches** (one call per ~8 cells —
    important because this model is ~100s/call), then merge each decision back by
    `case_id`. Set `final_*` fields + `final_status`. The LLM only adjusts
    *structure*; it never rewrites the value.
    """
)
code(
    """
    LLM_BATCH_SIZE = 8   # cells per LLM call; lower if the model truncates JSON

    def case_id_of(fact):
        return f"{fact['row_index']}_{fact['col_index']}"

    def build_case_payload(fact):
        return {
            "case_id": case_id_of(fact),
            "row_index": fact["row_index"], "col_index": fact["col_index"],
            "row_path": fact["row_path"], "column_path": fact["column_path"],
            "value": fact["value"], "is_dash": fact["is_dash"],
            "span_type": fact["span_type"], "review_reason": fact["review_reason"],
        }

    # 1) gather the cases that actually need review
    to_review = [f for f in candidate_facts if f["needs_llm_review"]]
    print(f"cells flagged for review: {len(to_review)} "
          f"({'LLM enabled' if (ENABLE_LLM_REVIEW and LLM_AVAILABLE) else 'LLM OFF -> manual review'})")

    # 2) one batched LLM pass (not one call per cell)
    review_by_id = {}
    if to_review and ENABLE_LLM_REVIEW and LLM_AVAILABLE:
        import time as _t
        _t0 = _t.time()
        cases = [build_case_payload(f) for f in to_review]
        review_by_id = review_cases_with_local_llm(cases, batch_size=LLM_BATCH_SIZE)
        print(f"LLM review pass done in {_t.time()-_t0:.0f}s; got {len(review_by_id)} decisions")

    # 3) merge decisions back into every candidate fact
    reviewed_facts = []
    for fact in candidate_facts:
        out = dict(fact)
        out.update({
            "llm_reviewed": False, "llm_decision": None, "llm_confidence": None,
            "final_row_path": fact["row_path"], "final_column_path": fact["column_path"],
            "final_value": fact["value"], "final_condition": "",
            "final_status": "accepted",
        })
        if not fact["needs_llm_review"]:
            reviewed_facts.append(out)
            continue

        review = review_by_id.get(case_id_of(fact))
        if review is None:
            # flagged but no LLM decision (LLM off, or not returned) -> manual
            out["final_status"] = "needs_manual_review"
            reviewed_facts.append(out)
            continue

        out["llm_reviewed"] = True
        out["llm_decision"] = review.get("decision")
        out["llm_confidence"] = review.get("confidence")
        if review.get("corrected_row_path"):
            out["final_row_path"] = review["corrected_row_path"]
        if review.get("corrected_column_path"):
            out["final_column_path"] = review["corrected_column_path"]
        if review.get("condition"):
            out["final_condition"] = review["condition"]
        # never let the LLM change the value; only structure
        decision = review.get("decision")
        if decision in ("section_header", "row_group_header", "column_header", "blank"):
            out["final_status"] = "rejected"   # not a data value
        elif review.get("confidence") == "low":
            out["final_status"] = "needs_manual_review"
        else:
            out["final_status"] = "accepted"
        reviewed_facts.append(out)

    print("reviewed facts:", len(reviewed_facts),
          "| llm_reviewed:", sum(f["llm_reviewed"] for f in reviewed_facts))
    from collections import Counter
    print("final_status:", dict(Counter(f["final_status"] for f in reviewed_facts)))
    """
)

# ---------------------------------------------------------------- 13. outputs
md("## 13. Output structured cell facts")
code(
    """
    def _save_json(name, obj):
        p = OUTPUT_DIR / name
        p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
        return p

    def _save_csv(name, rows):
        p = OUTPUT_DIR / name
        pd.DataFrame(rows).to_csv(p, index=False, encoding="utf-8-sig")
        return p

    pd.DataFrame(raw_data).to_csv(OUTPUT_DIR / "raw_table_extract.csv", index=False, encoding="utf-8-sig")
    spans_inside.drop(columns=["bbox"]).to_csv(OUTPUT_DIR / "spans_inside_table.csv", index=False, encoding="utf-8-sig")
    row_class_df.to_csv(OUTPUT_DIR / "row_classification.csv", index=False, encoding="utf-8-sig")
    _save_json("column_hierarchy.json", column_hierarchy)
    _save_json("candidate_cell_facts.json", candidate_facts)
    _save_json("reviewed_cell_facts.json", reviewed_facts)

    flat = []
    for f in reviewed_facts:
        flat.append({
            "row_path": " > ".join(f["final_row_path"]),
            "column_path": " > ".join(f["final_column_path"]),
            "value": f["final_value"], "condition": f["final_condition"],
            "span_type": f["span_type"], "is_dash": f["is_dash"],
            "final_status": f["final_status"], "llm_reviewed": f["llm_reviewed"],
            "review_reason": f["review_reason"],
        })
    _save_csv("reviewed_cell_facts.csv", flat)
    print("wrote outputs to", OUTPUT_DIR.resolve())
    for p in sorted(OUTPUT_DIR.glob("*")):
        print("  ", p.name)
    """
)

# ---------------------------------------------------------------- 14. sanity
md(
    """
    ## 14. Sanity checks
    Non-fatal validations: collect issues and print them so you can eyeball the
    flatten quality before trusting it.
    """
)
code(
    """
    SECTION_OR_GROUP = set(SECTION_KEYWORDS) | set(ROW_GROUP_KEYWORDS)

    issues = []
    def flag(cond, msg, ctx=None):
        if cond:
            issues.append({"check": msg, "context": ctx})

    for f in reviewed_facts:
        v = (f["final_value"] or "").strip()
        rp = f["final_row_path"]; cp = f["final_column_path"]
        if f["final_status"] == "accepted":
            flag(_has_kw(v, SECTION_KEYWORDS), "section_header text used as final_value", v)
            flag(_has_kw(v, ROW_GROUP_KEYWORDS) and not re.search(r"\\d", v),
                 "row_group_header text used as final_value", v)
            flag(not rp, "accepted fact has empty row_path", f["row_index"])
            flag(not cp, "accepted fact has empty column_path", f["col_index"])
        # dash preserved
        if f["is_dash"]:
            flag(f["final_value"].strip() not in {"-", "\\u2013", "\\u2014", "\\u2212"},
                 "dash value was altered", f["final_value"])
        # complex / multi-condition values flagged
        if "except" in v.lower():
            f["span_type"] = "complex_value" if f["span_type"] == "single_cell" else f["span_type"]
        if "|" in v:
            f["span_type"] = "multi_condition_value"
        # column path must not mix dwelling families
        joined_cp = " ".join(cp).lower()
        flag("rowhouse" in joined_cp and "small-scale" in joined_cp,
             "column_path mixes Rowhouse with Small-Scale Multi-Unit", joined_cp)

    # condition headers should survive somewhere
    cond_seen = any("transit" in " ".join(h["column_path"]).lower() for h in column_hierarchy)
    print("Frequent-Transit condition header captured in a column_path:", cond_seen)

    print(f"\\nsanity issues: {len(issues)}")
    for it in issues[:40]:
        print("  -", it["check"], "::", it["context"])
    """
)

# ---------------------------------------------------------------- 15. preview
md("## 15. Preview final flattened facts")
code(
    """
    preview = pd.DataFrame([{
        "row_path_str": " > ".join(f["final_row_path"]),
        "column_path_str": " > ".join(f["final_column_path"]),
        "final_value": f["final_value"],
        "final_condition": f["final_condition"],
        "span_type": f["span_type"],
        "final_status": f["final_status"],
        "llm_reviewed": f["llm_reviewed"],
    } for f in reviewed_facts])
    display(preview)
    """
)

# ---------------------------------------------------------------- 16. rule-ready
md(
    """
    ## 16. Optional rule-ready output
    Re-shape accepted facts into a rule-ready form (metric_path / scope_path / value /
    condition + evidence), ready for the downstream rule layer.
    """
)
code(
    """
    rule_ready = []
    for f in reviewed_facts:
        if f["final_status"] == "rejected":
            continue
        rule_ready.append({
            "metric_path": f["final_row_path"],
            "scope_path": f["final_column_path"],
            "raw_value": f["final_value"],
            "condition": f["final_condition"],
            "evidence": {
                "page": f["page"], "bbox": f["source_bbox"],
                "table_index": f["table_index"],
                "row_index": f["row_index"], "col_index": f["col_index"],
            },
        })
    (OUTPUT_DIR / "rule_ready_facts.json").write_text(
        json.dumps(rule_ready, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print("rule_ready_facts:", len(rule_ready), "->", (OUTPUT_DIR / "rule_ready_facts.json"))
    display(pd.DataFrame([{
        "metric_path": " > ".join(r["metric_path"]),
        "scope_path": " > ".join(r["scope_path"]),
        "raw_value": r["raw_value"], "condition": r["condition"],
    } for r in rule_ready]).head(60))
    """
)

# ---------------------------------------------------------------- write
notebook = nbf.v4.new_notebook()
notebook["cells"] = cells
notebook["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}
NOTEBOOK_PATH.write_text(nbf.writes(notebook) + "\n", encoding="utf-8")
print(f"Wrote {NOTEBOOK_PATH}")
