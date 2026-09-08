import nbformat as nbf
import textwrap
from pathlib import Path


OUT = Path(__file__).with_name("table_structure_probe.ipynb")


def md(text: str):
    return nbf.v4.new_markdown_cell(textwrap.dedent(text).strip())


def code(text: str):
    return nbf.v4.new_code_cell(textwrap.dedent(text).strip())


nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {"name": "python", "pygments_lexer": "ipython3"},
}

nb.cells = [
    md(
        """
        # Burnaby Table Structure Probe

        This notebook tests whether we can recover the 2D table structure before sending
        rules to an LLM. The goal is to produce row/cell facts like:

        ```json
        {
          "group_title": "Maximum Lot Coverage",
          "row_label": "All Buildings",
          "column_header": "1 to 3 Units",
          "cell_text": "55%"
        }
        ```

        This is intentionally separate from the main pipeline. It uses no LLM/API calls.
        """
    ),
    code(
        r'''
        import json
        import re
        import sys
        from pathlib import Path

        import pandas as pd
        import fitz  # PyMuPDF

        def locate_prototype_dir() -> Path:
            cwd = Path.cwd()
            for d in [cwd, *cwd.parents]:
                candidate = d / "code" / "prototype_pipeline"
                if (candidate / "prototype_rule_extraction_pipeline.ipynb").exists():
                    return candidate.resolve()
                if (d / "prototype_rule_extraction_pipeline.ipynb").exists():
                    return d.resolve()
            return cwd

        PROTOTYPE_DIR = locate_prototype_dir()
        PDF_PATH = PROTOTYPE_DIR / "pdfs" / "R1Small-Scale-Multi-Unit-Housing-District.pdf"
        OUT_DIR = PROTOTYPE_DIR / "outputs" / "burnaby" / "prototype_burnaby_rule_pipeline" / "08_table_structure_probe"
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        # Burnaby page 2 in the PDF viewer is zero-index page 1.
        TARGET_PAGES_1_INDEXED = "2"
        TARGET_PAGE_INDEX = 1

        print("PROTOTYPE_DIR:", PROTOTYPE_DIR)
        print("PDF_PATH     :", PDF_PATH, "exists" if PDF_PATH.exists() else "MISSING")
        print("OUT_DIR      :", OUT_DIR)
        '''
    ),
    md(
        """
        ## Optional Dependencies

        Recommended install, if missing:

        ```bash
        pip install pdfplumber camelot-py[cv]
        ```

        Camelot may also need a working image/PDF backend depending on environment. The
        notebook still runs the PyMuPDF fallback if Camelot/pdfplumber are unavailable.
        """
    ),
    code(
        r'''
        def optional_import(name):
            try:
                return __import__(name), None
            except Exception as exc:
                return None, repr(exc)

        camelot, camelot_err = optional_import("camelot")
        pdfplumber, pdfplumber_err = optional_import("pdfplumber")

        print("camelot   :", "available" if camelot else f"missing ({camelot_err})")
        print("pdfplumber:", "available" if pdfplumber else f"missing ({pdfplumber_err})")
        '''
    ),
    md("## Page Preview With PyMuPDF"),
    code(
        r'''
        doc = fitz.open(PDF_PATH)
        page = doc[TARGET_PAGE_INDEX]
        print("page size:", page.rect)
        text = page.get_text("text")
        print(text[:4000])

        (OUT_DIR / "page2_text_preview.txt").write_text(text, encoding="utf-8")
        '''
    ),
    md(
        """
        ## Camelot Attempt

        We try both `lattice` and `stream`. `lattice` is good when ruled lines exist;
        `stream` is useful when columns are implied by text alignment. The best result
        should have a sensible grid and low whitespace.
        """
    ),
    code(
        r'''
        camelot_tables = []
        camelot_logs = []

        if camelot:
            for flavor in ["lattice", "stream"]:
                kwargs = {"pages": TARGET_PAGES_1_INDEXED, "flavor": flavor, "strip_text": "\n"}
                # Stream often needs a little row tolerance for wrapped legal table text.
                if flavor == "stream":
                    kwargs.update({"row_tol": 8, "edge_tol": 500})
                try:
                    tables = camelot.read_pdf(str(PDF_PATH), **kwargs)
                    print(f"{flavor}: {len(tables)} tables")
                    for i, table in enumerate(tables):
                        df = table.df
                        report = getattr(table, "parsing_report", {})
                        item = {
                            "engine": f"camelot_{flavor}",
                            "table_index": i,
                            "shape": list(df.shape),
                            "parsing_report": report,
                        }
                        camelot_logs.append(item)
                        camelot_tables.append((f"camelot_{flavor}_{i}", df, item))
                        df.to_csv(OUT_DIR / f"camelot_{flavor}_{i}.csv", index=False)
                        print(item)
                        display(df.head(20))
                except Exception as exc:
                    camelot_logs.append({"engine": f"camelot_{flavor}", "error": repr(exc)})
                    print(f"{flavor} failed:", repr(exc))
        else:
            print("Camelot is not installed; skipping.")

        (OUT_DIR / "camelot_logs.json").write_text(json.dumps(camelot_logs, indent=2), encoding="utf-8")
        '''
    ),
    md(
        """
        ## pdfplumber Attempt

        pdfplumber can either auto-detect tables or expose words/lines so we can build
        our own column map. This is often a good fallback for text PDFs.
        """
    ),
    code(
        r'''
        pdfplumber_tables = []
        pdfplumber_logs = []

        if pdfplumber:
            try:
                with pdfplumber.open(PDF_PATH) as pdf:
                    p = pdf.pages[TARGET_PAGE_INDEX]
                    settings_list = [
                        {
                            "vertical_strategy": "lines",
                            "horizontal_strategy": "lines",
                            "snap_tolerance": 4,
                            "join_tolerance": 4,
                            "intersection_tolerance": 6,
                        },
                        {
                            "vertical_strategy": "text",
                            "horizontal_strategy": "text",
                            "snap_tolerance": 4,
                            "join_tolerance": 4,
                            "intersection_tolerance": 6,
                            "min_words_vertical": 2,
                            "min_words_horizontal": 1,
                        },
                    ]
                    for idx, settings in enumerate(settings_list):
                        tables = p.extract_tables(table_settings=settings)
                        print(f"pdfplumber settings {idx}: {len(tables)} tables")
                        pdfplumber_logs.append({"settings_index": idx, "settings": settings, "table_count": len(tables)})
                        for j, table in enumerate(tables):
                            df = pd.DataFrame(table)
                            pdfplumber_tables.append((f"pdfplumber_{idx}_{j}", df, {"settings_index": idx}))
                            df.to_csv(OUT_DIR / f"pdfplumber_{idx}_{j}.csv", index=False)
                            display(df.head(20))
            except Exception as exc:
                pdfplumber_logs.append({"error": repr(exc)})
                print("pdfplumber failed:", repr(exc))
        else:
            print("pdfplumber is not installed; skipping.")

        (OUT_DIR / "pdfplumber_logs.json").write_text(json.dumps(pdfplumber_logs, indent=2), encoding="utf-8")
        '''
    ),
    md(
        """
        ## PyMuPDF Native Table Finder

        Newer PyMuPDF includes `page.find_tables()`. This is a useful local baseline
        because it can recover a real grid without Camelot/pdfplumber.
        """
    ),
    code(
        r'''
        pymupdf_tables = []
        pymupdf_table_logs = []

        if hasattr(page, "find_tables"):
            try:
                finder = page.find_tables()
                print("PyMuPDF find_tables count:", len(finder.tables))
                for i, table in enumerate(finder.tables):
                    data = table.extract()
                    df = pd.DataFrame(data).fillna("")
                    name = f"pymupdf_find_tables_{i}"
                    meta = {
                        "engine": "pymupdf_find_tables",
                        "table_index": i,
                        "shape": list(df.shape),
                        "bbox": list(getattr(table, "bbox", []) or []),
                    }
                    pymupdf_table_logs.append(meta)
                    pymupdf_tables.append((name, df, meta))
                    df.to_csv(OUT_DIR / f"{name}.csv", index=False)
                    print(meta)
                    display(df.head(35))
            except Exception as exc:
                pymupdf_table_logs.append({"error": repr(exc)})
                print("PyMuPDF find_tables failed:", repr(exc))
        else:
            print("This PyMuPDF version does not expose page.find_tables().")

        (OUT_DIR / "pymupdf_find_tables_logs.json").write_text(
            json.dumps(pymupdf_table_logs, indent=2), encoding="utf-8"
        )
        '''
    ),
    md(
        """
        ## PyMuPDF Word-BBox Fallback

        This fallback clusters words into rows using y coordinates, then derives rough
        columns from x coordinates. It is less precise than a true table extractor, but
        it lets us inspect whether the PDF text geometry is enough to recover columns.
        """
    ),
    code(
        r'''
        def words_to_rows(page, y_tol=4):
            words = page.get_text("words")
            items = [
                {
                    "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3],
                    "text": w[4], "block": w[5], "line": w[6], "word": w[7],
                }
                for w in words
            ]
            items.sort(key=lambda r: (r["y0"], r["x0"]))
            rows = []
            for item in items:
                placed = False
                cy = (item["y0"] + item["y1"]) / 2
                for row in rows:
                    if abs(row["cy"] - cy) <= y_tol:
                        row["items"].append(item)
                        row["cy"] = (row["cy"] * (len(row["items"]) - 1) + cy) / len(row["items"])
                        placed = True
                        break
                if not placed:
                    rows.append({"cy": cy, "items": [item]})
            for row in rows:
                row["items"].sort(key=lambda r: r["x0"])
                row["text"] = " ".join(i["text"] for i in row["items"])
                row["x0"] = min(i["x0"] for i in row["items"])
                row["x1"] = max(i["x1"] for i in row["items"])
            return rows

        rows = words_to_rows(page, y_tol=4)
        row_records = [{"row_index": i, "y": r["cy"], "x0": r["x0"], "x1": r["x1"], "text": r["text"]} for i, r in enumerate(rows)]
        rows_df = pd.DataFrame(row_records)
        rows_df.to_csv(OUT_DIR / "pymupdf_rows.csv", index=False)
        display(rows_df.head(80))
        '''
    ),
    code(
        r'''
        def infer_x_columns(rows, min_x=35, max_x=590, gap_threshold=22):
            xs = []
            for row in rows:
                for item in row["items"]:
                    if min_x <= item["x0"] <= max_x:
                        xs.append(item["x0"])
            xs = sorted(xs)
            clusters = []
            for x in xs:
                if not clusters or abs(clusters[-1][-1] - x) > gap_threshold:
                    clusters.append([x])
                else:
                    clusters[-1].append(x)
            centers = [sum(c) / len(c) for c in clusters if len(c) >= 2]
            return centers

        def assign_row_to_columns(row, centers):
            cells = [[] for _ in centers]
            for item in row["items"]:
                if not centers:
                    continue
                idx = min(range(len(centers)), key=lambda i: abs(item["x0"] - centers[i]))
                cells[idx].append(item["text"])
            return [" ".join(c).strip() for c in cells]

        centers = infer_x_columns(rows, gap_threshold=18)
        print("rough column centers:", [round(x, 1) for x in centers])
        grid = []
        for i, row in enumerate(rows):
            cells = assign_row_to_columns(row, centers)
            grid.append({"row_index": i, "y": row["cy"], **{f"col_{j}": cell for j, cell in enumerate(cells)}})
        grid_df = pd.DataFrame(grid)
        grid_df.to_csv(OUT_DIR / "pymupdf_rough_grid.csv", index=False)
        display(grid_df.head(80))
        '''
    ),
    md(
        """
        ## Convert Best Table Candidate to Cell Facts

        This section uses a simple heuristic candidate selector. If Camelot/pdfplumber
        works, use the best extracted DataFrame; otherwise use the PyMuPDF rough grid.
        The generated cell facts are meant to feed an LLM/postprocessor later.
        """
    ),
    code(
        r'''
        def clean_cell(x):
            if pd.isna(x):
                return ""
            return re.sub(r"\s+", " ", str(x).replace("\n", " / ")).strip()

        def score_table_df(df):
            if df is None or df.empty:
                return -1
            text = " ".join(clean_cell(x).lower() for x in df.to_numpy().ravel())
            hits = sum(k in text for k in [
                "maximum lot coverage", "impervious", "height", "storeys",
                "minimum lot line", "separation", "dwelling units"
            ])
            numeric = len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|m|sq\.?\s*m|storey|units?)", text))
            return hits * 100 + numeric + df.shape[0]

        candidates = []
        for name, df, meta in camelot_tables + pdfplumber_tables + pymupdf_tables:
            # Prefer real table extractors over the rough word-grid fallback.
            candidates.append((score_table_df(df) + 1000, name, df, meta))
        candidates.append((score_table_df(grid_df) - 1000, "pymupdf_rough_grid", grid_df, {"engine": "pymupdf"}))
        candidates = sorted(candidates, reverse=True, key=lambda x: x[0])

        print("Candidates:")
        for score, name, df, meta in candidates[:10]:
            print(score, name, df.shape)

        best_score, best_name, best_df, best_meta = candidates[0]
        best_df = best_df.applymap(clean_cell)
        best_df.to_csv(OUT_DIR / "best_table_candidate.csv", index=False)
        print("Selected:", best_name, best_df.shape, "score", best_score)
        display(best_df.head(80))
        '''
    ),
    code(
        r'''
        GROUP_PATTERNS = [
            "Development Regulations",
            "Maximum Lot Coverage",
            "Height",
            "Minimum Lot Line Setbacks",
            "Minimum Separation",
            "Use-Specific Regulations",
            "General Regulations",
        ]

        def row_text(row):
            return " | ".join(clean_cell(x) for x in row if clean_cell(x))

        def looks_like_group(text):
            low = text.lower()
            # A data row such as "Height | sloping roof: 10 m" contains the word
            # "Height" but is not a group title. Group titles usually do not carry
            # actual value units.
            if re.search(r"\d+(?:\.\d+)?\s*(?:%|m2|m\b|sq\.?\s*m|storey|units?)", low):
                return None
            for pat in GROUP_PATTERNS:
                if pat.lower() in low:
                    return pat
            return None

        def normalized_row_values(row):
            return [clean_cell(v) for v in row.tolist()]

        def nearest_header_for_col(header_rows, col_idx, max_distance=2):
            parts = []
            for _ridx, vals in header_rows:
                candidates = []
                for i, val in enumerate(vals):
                    if not val:
                        continue
                    dist = abs(i - col_idx)
                    if dist <= max_distance and not looks_like_group(val):
                        candidates.append((dist, i, val))
                if candidates:
                    candidates.sort(key=lambda x: (x[0], x[1]))
                    parts.append(candidates[0][2])
            seen = set()
            clean_parts = []
            for p in parts:
                key = p.lower()
                if key not in seen:
                    clean_parts.append(p)
                    seen.add(key)
            return " / ".join(clean_parts)

        def is_headerish(vals):
            text = row_text(vals).lower()
            if looks_like_group(text):
                return True
            if not re.search(r"\d|%|m2|m\b|storey|permitted|required", text, flags=re.I):
                return True
            if any(k in text for k in ["dwelling type", "rowhouse", "small-scale", "frequent transit", "network area"]):
                return True
            return False

        def first_label(vals):
            for val in vals:
                if val and not re.fullmatch(r"[-:]+", val):
                    return val
            return ""

        def build_cell_facts_from_df(df, source_name):
            facts = []
            current_group = ""
            subject_context = ""
            header_rows = []
            for ridx, row in df.iterrows():
                vals = normalized_row_values(row)
                text = row_text(vals)
                if not text:
                    continue
                group = looks_like_group(text)
                if group:
                    current_group = group
                    header_rows = []
                    subject_context = ""
                    continue

                # Rows that only describe the table columns or subgroup subject should
                # be retained as context, not emitted as value facts.
                if any(k.lower() in text.lower() for k in ["front principal buildings", "rear principal buildings"]):
                    subject_context = text
                    continue

                if is_headerish(vals):
                    header_rows.append((ridx, vals))
                    continue

                # First non-empty cell is the row label. Remaining cells are values.
                non_empty = [(i, v) for i, v in enumerate(vals) if v]
                if not non_empty:
                    continue
                row_label_idx, row_label = non_empty[0]
                if subject_context and row_label.lower() in {"height", "storeys (basement inclusive)"}:
                    row_label = f"{subject_context} / {row_label}"
                for cidx, cell_text in non_empty[1:]:
                    if not re.search(r"\d|%|permitted|required|storey|m\b", cell_text, flags=re.I):
                        continue
                    facts.append({
                        "fact_id": f"{source_name}__r{ridx:03d}__c{cidx:03d}",
                        "source_table": source_name,
                        "group_title": current_group,
                        "row_index": int(ridx),
                        "column_index": int(cidx),
                        "row_label": row_label,
                        "column_header": nearest_header_for_col(header_rows, cidx),
                        "cell_text": cell_text,
                        "row_text": text,
                    })
            return facts

        cell_facts = build_cell_facts_from_df(best_df, best_name)
        facts_df = pd.DataFrame(cell_facts)
        facts_df.to_csv(OUT_DIR / "cell_facts.csv", index=False)
        (OUT_DIR / "cell_facts.json").write_text(json.dumps(cell_facts, indent=2), encoding="utf-8")
        display(facts_df.head(100))
        print("cell facts:", len(cell_facts))
        '''
    ),
    md(
        """
        ## Robust Header Propagation

        This version treats table extraction as a grid problem. It keeps early
        dwelling-type/unit rows as reusable column headers, propagates subgroup rows
        like `Front Principal Buildings` downward, and emits confidence/warnings for
        every value cell.
        """
    ),
    code(
        r'''
        VALUE_RE = re.compile(
            r"\d+(?:\.\d+)?\s*(?:%|m2|sq\.?\s*m|m\b|storeys?|persons?)",
            flags=re.I,
        )
        HEADER_HINT_RE = re.compile(
            r"dwelling type|rowhouse|small-scale|multi-unit|frequent transit|network area|lot type|building type|zone",
            flags=re.I,
        )
        UNIT_RANGE_RE = re.compile(r"\d+(?:\.\d+)?\s*to\s*\d+(?:\.\d+)?(?:\s*units?)?", flags=re.I)
        SUBJECT_CONTEXT_RE = re.compile(
            r"front principal buildings?|rear principal buildings?|accessory buildings?",
            flags=re.I,
        )

        def grid_clean_df(df):
            return df.copy().applymap(clean_cell)

        def row_values(df, ridx):
            return [clean_cell(v) for v in df.iloc[ridx].tolist()]

        def nonempty_cells(vals):
            return [(i, v) for i, v in enumerate(vals) if v and v.lower() != "nan"]

        def cell_has_value(text):
            return bool(VALUE_RE.search(clean_cell(text))) or bool(UNIT_RANGE_RE.search(clean_cell(text))) or bool(re.search(r"permitted|required|not permitted", clean_cell(text), flags=re.I))

        def is_value_only(text):
            t = clean_cell(text)
            if not t:
                return False
            if re.fullmatch(r"[-:]+", t):
                return True
            if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:%|m2|sq\.?\s*m|m\b|storeys?|units?)", t, flags=re.I):
                return True
            if UNIT_RANGE_RE.fullmatch(t):
                return True
            return False

        def group_title_from_row(vals):
            text = row_text(vals)
            if VALUE_RE.search(text):
                return None
            return looks_like_group(text)

        def row_is_header_provider(vals, before_first_rule_group=False):
            text = row_text(vals)
            if not text:
                return False
            if group_title_from_row(vals):
                return False
            if HEADER_HINT_RE.search(text):
                return True
            # The permitted-dwelling-units row is both a rule row and the unit-count
            # column header row for later development regulation values.
            if "permitted dwelling units" in text.lower():
                return True
            if before_first_rule_group and UNIT_RANGE_RE.search(text):
                return True
            return False

        def build_header_paths(df, header_row_indices):
            ncols = df.shape[1]
            paths = {c: [] for c in range(ncols)}
            for ridx in header_row_indices:
                vals = row_values(df, ridx)
                cells = nonempty_cells(vals)
                if not cells:
                    continue

                # Ignore left-side row labels when the row doubles as a rule/header row.
                usable = []
                for c, v in cells:
                    low = v.lower()
                    if c <= 1 and any(k in low for k in ["permitted dwelling units", "minimum lot area", "maximum lot area"]):
                        continue
                    if re.fullmatch(r"[-:]+", v):
                        continue
                    usable.append((c, v))
                if not usable:
                    continue

                for idx, (start_col, value) in enumerate(usable):
                    end_col = (usable[idx + 1][0] - 1) if idx + 1 < len(usable) else ncols - 1
                    low = value.lower()

                    # A rightmost qualifier like Frequent Transit / Network Area Only
                    # belongs to the rightmost unit-count columns, not every column.
                    if re.search(r"frequent transit|network area only", low):
                        target_cols = range(max(0, start_col - 1), ncols)
                    elif UNIT_RANGE_RE.search(value) and start_col > 0:
                        # Some extractors place a merged rightmost header one column
                        # to the right of its data cells. Attach it to the immediate
                        # left column too, then clean conflicting unit ranges below.
                        target_cols = range(start_col - 1, end_col + 1)
                    elif re.search(r"dwelling type", low):
                        target_cols = range(0, ncols)
                    elif start_col == end_col:
                        target_cols = [start_col]
                    else:
                        target_cols = range(start_col, end_col + 1)

                    for col in target_cols:
                        if 0 <= col < ncols:
                            paths[col].append(value)

            cleaned = {}
            for col, parts in paths.items():
                out = []
                seen = set()
                for part in parts:
                    part = re.sub(r"\s+", " ", part.replace("\n", " / ")).strip()
                    key = part.lower()
                    if part and key not in seen and not re.fullmatch(r"[-:]+", part):
                        out.append(part)
                        seen.add(key)
                unit_range_positions = [i for i, part in enumerate(out) if UNIT_RANGE_RE.search(part)]
                if len(unit_range_positions) > 1:
                    keep_idx = unit_range_positions[-1]
                    out = [
                        part for i, part in enumerate(out)
                        if i not in unit_range_positions[:-1] or i == keep_idx
                    ]
                cleaned[col] = out
            return cleaned

        def infer_row_label(vals, subject_context=""):
            cells = nonempty_cells(vals)
            for c, v in cells:
                if c > 2:
                    break
                if not is_value_only(v) and not HEADER_HINT_RE.search(v):
                    label = v
                    if subject_context and label.lower() in {"height", "storeys (basement inclusive)", "storeys"}:
                        label = f"{subject_context} / {label}"
                    return label
            for c, v in cells:
                if not is_value_only(v) and not HEADER_HINT_RE.search(v):
                    label = v
                    if subject_context and label.lower() in {"height", "storeys (basement inclusive)", "storeys"}:
                        label = f"{subject_context} / {label}"
                    return label
            return subject_context

        def local_condition_and_value(text):
            t = clean_cell(text)
            m = re.search(r"(.+?):\s*(\d+(?:\.\d+)?\s*%)", t, flags=re.I)
            if m:
                return clean_cell(m.group(1)), clean_cell(m.group(2))
            return "", t

        def structured_score(df, facts):
            if df is None or df.empty:
                return -9999
            text = " ".join(clean_cell(x).lower() for x in df.to_numpy().ravel())
            group_hits = sum(k in text for k in ["maximum lot coverage", "maximum height", "minimum lot line", "minimum separation"])
            label_hits = sum(bool(clean_cell(f.get("row_label_path"))) and not is_value_only(f.get("row_label_path")) for f in facts)
            header_hits = sum(bool(clean_cell(f.get("column_header_path"))) for f in facts)
            warning_count = sum(len(f.get("mapping_warnings", [])) for f in facts)
            # Prefer sensible facts over merely many facts.
            return group_hits * 100 + label_hits * 5 + header_hits * 2 - warning_count

        def build_structured_cell_facts_from_df(df, source_name):
            df = grid_clean_df(df)
            nrows, ncols = df.shape
            group_by_row = {}
            first_rule_group_idx = None
            header_row_indices = []

            for ridx in range(nrows):
                vals = row_values(df, ridx)
                group = group_title_from_row(vals)
                if group:
                    group_by_row[ridx] = group
                    if first_rule_group_idx is None and group != "Development Regulations":
                        first_rule_group_idx = ridx
                    continue
                before_first = first_rule_group_idx is None
                if row_is_header_provider(vals, before_first_rule_group=before_first):
                    header_row_indices.append(ridx)

            header_paths = build_header_paths(df, header_row_indices)
            facts = []
            current_group = ""
            subject_context = ""

            for ridx in range(nrows):
                vals = row_values(df, ridx)
                text = row_text(vals)
                if not text:
                    continue
                if ridx in group_by_row:
                    current_group = group_by_row[ridx]
                    subject_context = ""
                    continue

                nonempty = nonempty_cells(vals)
                if not nonempty:
                    continue

                if len(nonempty) == 1 and SUBJECT_CONTEXT_RE.fullmatch(nonempty[0][1].strip()):
                    subject_context = nonempty[0][1]
                    continue

                row_label = infer_row_label(vals, subject_context=subject_context)
                if row_is_header_provider(vals, before_first_rule_group=(first_rule_group_idx is None or ridx < first_rule_group_idx)):
                    # If it is the permitted-dwelling-units rule row, still emit
                    # facts. Other pure header rows are context only.
                    if "permitted dwelling units" not in text.lower():
                        continue

                for cidx, cell_text in nonempty:
                    if not cell_has_value(cell_text):
                        continue
                    if row_label and clean_cell(cell_text) == clean_cell(row_label):
                        continue
                    if cidx <= 1 and row_label and clean_cell(cell_text) in clean_cell(row_label):
                        continue

                    local_condition, value_text = local_condition_and_value(cell_text)
                    column_path_parts = header_paths.get(cidx, [])
                    column_header_path = " / ".join(column_path_parts)
                    warnings = []
                    confidence = 1.0
                    if not row_label:
                        warnings.append("missing_row_label")
                        confidence -= 0.25
                    if cidx > 2 and not column_header_path:
                        warnings.append("missing_column_header")
                        confidence -= 0.20
                    if len(nonempty) == 1 and current_group:
                        warnings.append("single_cell_row")
                        confidence -= 0.10
                    if local_condition:
                        confidence += 0.05

                    facts.append({
                        "fact_id": f"{source_name}__sr{ridx:03d}__c{cidx:03d}",
                        "source_table": source_name,
                        "group_title": current_group,
                        "row_index": int(ridx),
                        "column_index": int(cidx),
                        "row_label_path": row_label,
                        "column_header_path": column_header_path,
                        "local_condition": local_condition,
                        "cell_text": cell_text,
                        "value_text": value_text,
                        "row_text": text,
                        "mapping_confidence": round(max(0.0, min(1.0, confidence)), 3),
                        "mapping_warnings": warnings,
                    })
            return facts

        structured_candidates = []
        for name, df, meta in camelot_tables + pdfplumber_tables + pymupdf_tables:
            facts = build_structured_cell_facts_from_df(df, name)
            structured_candidates.append((structured_score(df, facts), name, df, facts))
        if not structured_candidates:
            facts = build_structured_cell_facts_from_df(grid_df, "pymupdf_rough_grid")
            structured_candidates.append((structured_score(grid_df, facts), "pymupdf_rough_grid", grid_df, facts))

        structured_candidates = sorted(structured_candidates, reverse=True, key=lambda x: x[0])
        print("Structured candidates:")
        for score, name, df, facts in structured_candidates:
            print(score, name, df.shape, "facts", len(facts))

        structured_score_value, structured_source_name, structured_df, structured_cell_facts = structured_candidates[0]
        structured_df.to_csv(OUT_DIR / "structured_best_table_candidate.csv", index=False)
        structured_facts_df = pd.DataFrame(structured_cell_facts)
        structured_facts_df.to_csv(OUT_DIR / "structured_cell_facts.csv", index=False, encoding="utf-8-sig")
        (OUT_DIR / "structured_cell_facts.json").write_text(
            json.dumps(structured_cell_facts, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        print("Selected structured source:", structured_source_name, "score", structured_score_value)
        print("structured cell facts:", len(structured_cell_facts))
        display(structured_facts_df.head(120))
        '''
    ),
    md("## Summary"),
    code(
        r'''
        summary = {
            "pdf": str(PDF_PATH),
            "page": TARGET_PAGES_1_INDEXED,
            "camelot_available": bool(camelot),
            "pdfplumber_available": bool(pdfplumber),
            "camelot_table_count": len(camelot_tables),
            "pdfplumber_table_count": len(pdfplumber_tables),
            "selected_candidate": best_name,
            "selected_shape": list(best_df.shape),
            "cell_fact_count": len(cell_facts),
            "structured_selected_candidate": structured_source_name,
            "structured_cell_fact_count": len(structured_cell_facts),
            "outputs": str(OUT_DIR),
        }
        print(json.dumps(summary, indent=2))
        (OUT_DIR / "table_structure_probe_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        '''
    ),
]

nbf.write(nb, OUT)
print(f"Wrote {OUT}")
