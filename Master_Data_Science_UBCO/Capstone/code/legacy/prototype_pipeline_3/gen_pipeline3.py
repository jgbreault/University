import textwrap
from pathlib import Path

import nbformat as nbf


OUT = Path(__file__).with_name("pipeline3_integrated_rule_extraction.ipynb")


def md(text: str):
    return nbf.v4.new_markdown_cell(textwrap.dedent(text).strip())


def code(text: str):
    # Some cells contain prompt literals with intentionally unindented text, which
    # prevents textwrap.dedent from seeing the notebook-code indentation. Remove one
    # generator indentation level line-by-line instead.
    raw = text.strip("\n")
    lines = raw.splitlines()
    fixed = "\n".join(line[8:] if line.startswith("        ") else line for line in lines)
    return nbf.v4.new_code_cell(fixed.strip())


nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "pygments_lexer": "ipython3"},
}

nb.cells = [
    md(
        """
        # Pipeline 3 - Integrated Rule Extraction

        This notebook assembles the current best prototype into one run:

        1. Local PDF page/block extraction.
        2. Local keyword + optional local LLM block selection.
        3. Non-table evidence extraction with Gemini/API.
        4. Table extraction from recovered cell grids, with optional API semantic review.
        5. Deterministic merge, normalization, de-duplication, and verification.

        The key design is still object/value/evidence based: every rule must keep a
        regulated object, constraint/operator/value/unit, and an evidence source that
        explains why the value exists.
        """
    ),
    md("## 0. Configuration"),
    code(
        r'''
        import json
        import os
        import re
        import sys
        import time
        from pathlib import Path

        import pandas as pd
        import requests
        from tqdm.auto import tqdm

        import fitz
        import pymupdf4llm

        def _noop_get_layout(self):
            self.layout_information = None

        fitz.Page.get_layout = _noop_get_layout
        pymupdf4llm._use_layout = False

        def locate_repo_root():
            cwd = Path.cwd()
            for d in [cwd, *cwd.parents]:
                if (d / ".git").exists() and (d / "code").exists():
                    return d.resolve()
            return cwd.resolve()

        REPO_ROOT = locate_repo_root()
        PROTOTYPE_DIR = REPO_ROOT / "code" / "prototype_pipeline"
        PIPELINE3_DIR = REPO_ROOT / "code" / "prototype_pipeline_3"
        PDF_DIR = PROTOTYPE_DIR / "pdfs"
        os.chdir(PIPELINE3_DIR)

        if str(PROTOTYPE_DIR) not in sys.path:
            sys.path.insert(0, str(PROTOTYPE_DIR))
        import prototype_target_aware_helpers as helpers

        TARGET_CITY = "burnaby"
        RUN_BLOCK_SELECTION_LLM = False
        RUN_API_NON_TABLE_EXTRACTION = True
        RUN_API_TABLE_SEMANTIC_REVIEW = True

        # API settings. Keep calls low: non-table is grouped by block, table semantic
        # review is one compact call over deterministic table rules.
        API_PROVIDER = "gemini"
        GEMINI_MODEL = "gemini-2.5-flash-lite"
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        REQUEST_TIMEOUT = 180
        TEMPERATURE = 0.0
        MAX_OUTPUT_TOKENS = 12000
        GEMINI_MAX_RETRIES = 3
        GEMINI_RETRY_BASE_SECONDS = 20

        # Optional local selector settings.
        MODEL_NAME = "qwen35-rules"
        OLLAMA_URL = "http://localhost:11434/api/generate"
        LOCAL_REQUEST_TIMEOUT = 180

        TOP_K_CANDIDATES = 15
        SCORE_THRESHOLD = 0.5

        CITY_CONFIGS = {
            "burnaby": {
                "doc_id": "burnaby_r1",
                "pdf": "R1Small-Scale-Multi-Unit-Housing-District.pdf",
                "city": "Burnaby",
                "province": "BC",
                "zone": "R1",
                "building_type": "Rear Principal Building",
                "target_terms": ["rear principal building", "rear principal"],
                "primary_keywords": ["rear principal building", "rear principal"],
                "parent_terms": [
                    "all buildings", "principal buildings", "dwelling units",
                    "building", "lot", "yard", "parking", "access", "separation",
                ],
                "description": "Burnaby R1 Rear Principal Building plus generic R1 development regulations.",
            },
            "vancouver": {
                "doc_id": "vancouver_section_11_2026_02",
                "pdf": "zoning-by-law-section-11.pdf",
                "city": "Vancouver",
                "province": "BC",
                "zone": "RS",
                "building_type": "Laneway House",
                "target_terms": ["laneway house"],
                "primary_keywords": ["laneway house"],
                "parent_terms": ["site", "building", "yard", "accessory building", "parking", "floor area"],
                "description": "Vancouver laneway-house context plus generic applicable RS/site regulations.",
            },
            "surrey": {
                "doc_id": "surrey_zoning_12000",
                "pdf": "BYL_Zoning_12000.pdf",
                "city": "Surrey",
                "province": "BC",
                "zone": "R1",
                "building_type": "Coach House",
                "target_terms": ["coach house", "garden suite"],
                "primary_keywords": ["coach house", "garden suite"],
                "parent_terms": ["lot", "building", "yard", "accessory", "parking", "floor area"],
                "description": "Surrey R1 Coach House/Garden Suite plus generic applicable rules.",
            },
        }

        TARGET = CITY_CONFIGS[TARGET_CITY]
        PDF_PATH = PDF_DIR / TARGET["pdf"]
        RUN_ID = f"pipeline3_{TARGET_CITY}_rule_pipeline"
        OUTPUT_DIR = PIPELINE3_DIR / "outputs" / TARGET_CITY / RUN_ID
        BLOCK_DIR = OUTPUT_DIR / "01_blocks"
        SELECT_DIR = OUTPUT_DIR / "02_selected_blocks"
        EVIDENCE_DIR = OUTPUT_DIR / "03_evidence"
        API_DIR = OUTPUT_DIR / "04_api_raw"
        RULE_DIR = OUTPUT_DIR / "05_rules"
        for d in [OUTPUT_DIR, BLOCK_DIR, SELECT_DIR, EVIDENCE_DIR, API_DIR, RULE_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        print("REPO_ROOT:", REPO_ROOT)
        print("PIPELINE3_DIR:", PIPELINE3_DIR)
        print("TARGET_CITY:", TARGET_CITY)
        print("PDF_PATH:", PDF_PATH, "exists" if PDF_PATH.exists() else "MISSING")
        print("OUTPUT_DIR:", OUTPUT_DIR)
        print("Gemini key set:", bool(GEMINI_API_KEY))
        '''
    ),
    md(
        """
        ## 1. Local PDF Block Extraction

        This is the same local-first idea as notebook 07: convert the official PDF
        into page-level markdown blocks. Blocks preserve page number, section hints,
        and full markdown for downstream evidence extraction.
        """
    ),
    code(
        r'''
        def clean(value):
            if value is None:
                return ""
            try:
                if pd.isna(value):
                    return ""
            except Exception:
                pass
            return str(value).strip()

        def norm(value):
            return re.sub(r"\s+", " ", clean(value).lower()).strip()

        def compact_key(value):
            return re.sub(r"[^a-z0-9]+", "_", norm(value)).strip("_")

        def detect_section(text):
            for pat in [r"(?m)^\s*(\d+(?:\.\d+){1,4})\s+", r"(?m)^#+\s*(\d+(?:\.\d+){1,4})"]:
                m = re.search(pat, text or "")
                if m:
                    return m.group(1)
            return ""

        def page_number_from_meta(meta, fallback):
            raw = meta.get("page", meta.get("page_number", fallback))
            try:
                return int(raw)
            except Exception:
                return fallback

        all_blocks = []
        pages = pymupdf4llm.to_markdown(str(PDF_PATH), page_chunks=True)
        for idx, chunk in enumerate(pages, start=1):
            if isinstance(chunk, dict):
                markdown = chunk.get("text") or chunk.get("markdown") or ""
                meta = chunk.get("metadata") or {}
                page_number = page_number_from_meta(meta, idx)
            else:
                markdown = str(chunk)
                page_number = idx
            block = {
                "doc_id": TARGET["doc_id"],
                "city": TARGET["city"],
                "province": TARGET["province"],
                "zone": TARGET["zone"],
                "block_id": f"{TARGET['doc_id']}__page_{page_number:04d}",
                "page_number": page_number,
                "section": detect_section(markdown),
                "text": markdown[:500],
                "markdown": markdown,
                "char_count": len(markdown),
            }
            all_blocks.append(block)

        with (BLOCK_DIR / "blocks.jsonl").open("w", encoding="utf-8") as f:
            for b in all_blocks:
                f.write(json.dumps(b, ensure_ascii=False) + "\n")

        print("blocks:", len(all_blocks))
        display(pd.DataFrame(all_blocks)[["block_id", "page_number", "section", "char_count", "text"]].head(30))
        '''
    ),
    md(
        """
        ## 2. Local Block Scoring and Selection

        Selection is intentionally recall-friendly. We score target terms, parent
        object terms, and universal development-regulation terms, then keep high
        scoring pages plus nearby pages. Optional local LLM selection can remove only
        obviously irrelevant blocks.
        """
    ),
    code(
        r'''
        UNIVERSAL_TERMS = [
            "development regulations", "lot coverage", "impervious", "height",
            "storeys", "setback", "yard", "separation", "parking", "access",
            "floor area", "dwelling units", "permitted", "minimum", "maximum",
            "sprinkler", "fire access", "lane", "driveway",
        ]

        def score_block(block):
            text = norm(block.get("markdown") or block.get("text"))
            score = 0.0
            hits = []
            for term in TARGET.get("primary_keywords", []):
                if term.lower() in text:
                    score += 10
                    hits.append(term)
            for term in TARGET.get("parent_terms", []):
                if term.lower() in text:
                    score += 3
                    hits.append(term)
            for term in UNIVERSAL_TERMS:
                if term.lower() in text:
                    score += 1
                    hits.append(term)
            # Burnaby R1 has generic page-2 development regulations that do not
            # mention the target type explicitly; keep these strongly.
            if TARGET_CITY == "burnaby" and any(k in text for k in ["maximum lot coverage", "minimum lot line setbacks", "minimum separation", "development regulations"]):
                score += 12
            return score, sorted(set(hits))

        scored = []
        for b in all_blocks:
            score, hits = score_block(b)
            x = dict(b)
            x["selection_score"] = score
            x["selection_hits"] = hits
            scored.append(x)

        eligible = [b for b in scored if b["selection_score"] >= SCORE_THRESHOLD]
        eligible = sorted(eligible, key=lambda b: (-b["selection_score"], b["page_number"]))[:TOP_K_CANDIDATES]

        # Recall expansion: include adjacent pages around strong hits.
        pages_by_num = {b["page_number"]: b for b in scored}
        selected_by_id = {b["block_id"]: b for b in eligible}
        for b in list(eligible):
            if b["selection_score"] >= 10:
                for pn in [b["page_number"] - 1, b["page_number"] + 1]:
                    if pn in pages_by_num:
                        selected_by_id.setdefault(pages_by_num[pn]["block_id"], pages_by_num[pn])

        selected_blocks = sorted(selected_by_id.values(), key=lambda b: b["page_number"])

        def call_local_selector(block):
            text = (block.get("markdown") or "")[:4000]
            prompt = f"""Return JSON only: {{"keep": true/false, "reason": "..."}}.
Target: {TARGET['description']}
Keep blocks containing direct, parent, or generic applicable zoning/development rules.
Block:
{text}
"""
            try:
                resp = requests.post(
                    OLLAMA_URL,
                    json={
                        "model": MODEL_NAME,
                        "prompt": "/no_think\n" + prompt,
                        "stream": False,
                        "options": {"temperature": 0.0, "num_ctx": 8192, "num_predict": 600},
                    },
                    timeout=LOCAL_REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "")
                obj, err = helpers.parse_llm_json_response(raw)
                if isinstance(obj, dict):
                    return bool(obj.get("keep", False)), clean(obj.get("reason"))
            except Exception as exc:
                return True, f"selector_error_keep_by_default: {type(exc).__name__}: {exc}"
            return True, "selector_parse_failed_keep_by_default"

        if RUN_BLOCK_SELECTION_LLM:
            kept = []
            for b in tqdm(selected_blocks, desc="local block selector"):
                keep, reason = call_local_selector(b)
                x = dict(b)
                x["llm_selector_keep"] = keep
                x["llm_selector_reason"] = reason
                if keep:
                    kept.append(x)
            selected_blocks = kept

        with (SELECT_DIR / "selected_blocks.jsonl").open("w", encoding="utf-8") as f:
            for b in selected_blocks:
                f.write(json.dumps(b, ensure_ascii=False) + "\n")

        print("selected blocks:", len(selected_blocks))
        display(pd.DataFrame(selected_blocks)[["block_id", "page_number", "selection_score", "selection_hits"]])
        '''
    ),
    md(
        """
        ## 3. Evidence Split: Non-Table Clauses and Table Pages

        Non-table evidence is split into legal clauses/sentences from selected block
        markdown. Table extraction is handled separately because flattened text loses
        row/column meaning.
        """
    ),
    code(
        r'''
        def split_non_table_text(text):
            lines = []
            for line in (text or "").splitlines():
                s = line.strip()
                if not s:
                    continue
                if s.startswith("|"):
                    continue
                if re.match(r"^\s*[-:|]{3,}\s*$", s):
                    continue
                lines.append(re.sub(r"\s+", " ", s))
            merged = []
            buf = ""
            for line in lines:
                if len(buf) + len(line) < 450 and not re.search(r"[.;:]$", buf):
                    buf = (buf + " " + line).strip()
                else:
                    if buf:
                        merged.append(buf)
                    buf = line
            if buf:
                merged.append(buf)
            clauses = []
            for item in merged:
                parts = re.split(r"(?<=[.;])\s+(?=(?:[A-Z]|\(\w+\)|\d))", item)
                clauses.extend([p.strip() for p in parts if len(p.strip()) > 25])
            return clauses

        RULE_HINTS = [
            "must", "shall", "may", "required", "permitted", "not permitted",
            "minimum", "maximum", "not exceed", "at least", "setback", "yard",
            "height", "coverage", "separation", "parking", "access", "floor area",
            "sprinkler", "fire access", "lane", "driveway", "except", "subject to",
        ]

        non_table_evidence = []
        for block in selected_blocks:
            for i, clause in enumerate(split_non_table_text(block.get("markdown", "")), start=1):
                low = clause.lower()
                if not any(h in low for h in RULE_HINTS):
                    continue
                non_table_evidence.append({
                    "evidence_id": f"{block['block_id']}__nt_{i:03d}",
                    "source_block_id": block["block_id"],
                    "evidence_type": "clause",
                    "city": block.get("city"),
                    "province": block.get("province"),
                    "zone": block.get("zone"),
                    "page_number": block.get("page_number"),
                    "section": block.get("section"),
                    "text": clause,
                })

        pd.DataFrame(non_table_evidence).to_csv(EVIDENCE_DIR / "non_table_evidence.csv", index=False, encoding="utf-8-sig")
        (EVIDENCE_DIR / "non_table_evidence.json").write_text(json.dumps(non_table_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print("non-table evidence:", len(non_table_evidence))
        display(pd.DataFrame(non_table_evidence).head(50))
        '''
    ),
    md(
        """
        ## 4. Structured Table Cell Facts

        This stage tries PyMuPDF native table detection first and falls back to a word
        grid. It then propagates group titles, row labels, column headers, and emits
        one `cell fact` per value-bearing table cell.
        """
    ),
    code(
        r'''
        VALUE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|m2|sq\.?\s*m|m\b|storeys?|persons?|units?)", flags=re.I)
        UNIT_RANGE_RE = re.compile(r"\d+(?:\.\d+)?\s*to\s*\d+(?:\.\d+)?(?:\s*units?)?", flags=re.I)
        HEADER_HINT_RE = re.compile(r"dwelling type|rowhouse|small-scale|multi-unit|frequent transit|network area|lot type|building type|zone", flags=re.I)
        SUBJECT_CONTEXT_RE = re.compile(r"front principal buildings?|rear principal buildings?|accessory buildings?", flags=re.I)
        GROUP_PATTERNS = [
            "Development Regulations", "Maximum Lot Coverage", "Height",
            "Minimum Lot Line Setbacks", "Minimum Separation",
            "Use-Specific Regulations", "General Regulations",
        ]

        def clean_cell(x):
            return re.sub(r"\s+", " ", "" if x is None else str(x).replace("\n", " / ")).strip()

        def row_text(vals):
            return " | ".join(clean_cell(x) for x in vals if clean_cell(x))

        def looks_like_group(text):
            low = clean_cell(text).lower()
            if VALUE_RE.search(low):
                return None
            for pat in GROUP_PATTERNS:
                if pat.lower() in low:
                    return pat
            return None

        def cell_has_value(text):
            s = clean_cell(text)
            return bool(VALUE_RE.search(s) or UNIT_RANGE_RE.search(s) or re.search(r"permitted|required|not permitted", s, flags=re.I))

        def is_value_only(text):
            s = clean_cell(text)
            return bool(
                re.fullmatch(r"[-:]+", s)
                or re.fullmatch(r"\d+(?:\.\d+)?\s*(?:%|m2|sq\.?\s*m|m\b|storeys?|units?)", s, flags=re.I)
                or UNIT_RANGE_RE.fullmatch(s)
            )

        def group_title_from_row(vals):
            text = row_text(vals)
            if VALUE_RE.search(text):
                return None
            return looks_like_group(text)

        def nonempty_cells(vals):
            return [(i, clean_cell(v)) for i, v in enumerate(vals) if clean_cell(v) and clean_cell(v).lower() != "nan"]

        def row_is_header_provider(vals, before_first_rule_group=False):
            text = row_text(vals)
            if not text or group_title_from_row(vals):
                return False
            if "permitted dwelling units" in text.lower():
                return True
            # Do not let value-bearing rule rows become column headers. This was
            # the source of condition pollution such as carrying `281 m2` into the
            # 5-to-6-unit column.
            if any(cell_has_value(v) for _, v in nonempty_cells(vals)):
                return bool(before_first_rule_group and UNIT_RANGE_RE.search(text))
            if HEADER_HINT_RE.search(text):
                return True
            if before_first_rule_group and UNIT_RANGE_RE.search(text):
                return True
            return False

        def build_header_paths(df, header_row_indices):
            ncols = df.shape[1]
            paths = {c: [] for c in range(ncols)}
            for ridx in header_row_indices:
                vals = [clean_cell(v) for v in df.iloc[ridx].tolist()]
                usable = []
                for c, v in nonempty_cells(vals):
                    low = v.lower()
                    if c <= 1 and any(k in low for k in ["permitted dwelling units", "minimum lot area", "maximum lot area"]):
                        continue
                    if not re.fullmatch(r"[-:]+", v):
                        usable.append((c, v))
                for idx, (start_col, value) in enumerate(usable):
                    end_col = usable[idx + 1][0] - 1 if idx + 1 < len(usable) else ncols - 1
                    low = value.lower()
                    if re.search(r"frequent transit|network area only", low):
                        target_cols = range(max(0, start_col - 1), ncols)
                    elif UNIT_RANGE_RE.search(value) and start_col > 0:
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
                out, seen = [], set()
                for part in parts:
                    key = part.lower()
                    if part and key not in seen and not re.fullmatch(r"[-:]+", part):
                        out.append(part)
                        seen.add(key)
                range_pos = [i for i, p in enumerate(out) if UNIT_RANGE_RE.search(p)]
                if len(range_pos) > 1:
                    keep = range_pos[-1]
                    out = [p for i, p in enumerate(out) if i not in range_pos[:-1] or i == keep]
                cleaned[col] = out
            return cleaned

        def infer_row_label(vals, subject_context=""):
            for c, v in nonempty_cells(vals):
                if c > 2:
                    break
                if "permitted dwelling units" in v.lower():
                    return "Permitted Dwelling Units"
                if not is_value_only(v) and not HEADER_HINT_RE.search(v):
                    if subject_context and v.lower() in {"height", "storeys (basement inclusive)", "storeys"}:
                        return f"{subject_context} / {v}"
                    return v
            return subject_context

        def local_condition_and_value(text):
            s = clean_cell(text)
            m = re.search(r"(.+?):\s*(\d+(?:\.\d+)?\s*%)", s, flags=re.I)
            if m:
                return clean_cell(m.group(1)), clean_cell(m.group(2))
            return "", s

        def build_structured_cell_facts_from_df(df, source_name, page_number):
            df = df.copy().applymap(clean_cell)
            group_by_row, header_rows = {}, []
            first_rule_group_idx = None
            for ridx in range(df.shape[0]):
                vals = df.iloc[ridx].tolist()
                group = group_title_from_row(vals)
                if group:
                    group_by_row[ridx] = group
                    if first_rule_group_idx is None and group != "Development Regulations":
                        first_rule_group_idx = ridx
                    continue
                if row_is_header_provider(vals, first_rule_group_idx is None or ridx < first_rule_group_idx):
                    header_rows.append(ridx)
            header_paths = build_header_paths(df, header_rows)
            facts = []
            current_group, subject_context = "", ""
            for ridx in range(df.shape[0]):
                vals = df.iloc[ridx].tolist()
                text = row_text(vals)
                if not text:
                    continue
                if ridx in group_by_row:
                    current_group = group_by_row[ridx]
                    subject_context = ""
                    continue
                nonempty = nonempty_cells(vals)
                if len(nonempty) == 1 and SUBJECT_CONTEXT_RE.fullmatch(nonempty[0][1]):
                    subject_context = nonempty[0][1]
                    continue
                row_label = infer_row_label(vals, subject_context)
                if row_is_header_provider(vals, first_rule_group_idx is None or ridx < first_rule_group_idx):
                    if "permitted dwelling units" not in text.lower():
                        continue
                for cidx, cell_text in nonempty:
                    if not cell_has_value(cell_text):
                        continue
                    if row_label and cell_text == row_label:
                        continue
                    if cidx <= 1 and row_label and cell_text in row_label:
                        continue
                    local_condition, value_text = local_condition_and_value(cell_text)
                    column_path = " / ".join(header_paths.get(cidx, []))
                    warnings = []
                    confidence = 1.0
                    if not row_label:
                        warnings.append("missing_row_label")
                        confidence -= 0.25
                    if cidx > 2 and not column_path:
                        warnings.append("missing_column_header")
                        confidence -= 0.2
                    facts.append({
                        "fact_id": f"{source_name}__p{page_number:03d}__sr{ridx:03d}__c{cidx:03d}",
                        "source_table": source_name,
                        "page_number": page_number,
                        "group_title": current_group,
                        "row_index": int(ridx),
                        "column_index": int(cidx),
                        "row_label_path": row_label,
                        "column_header_path": column_path,
                        "local_condition": local_condition,
                        "cell_text": cell_text,
                        "value_text": value_text,
                        "row_text": text,
                        "mapping_confidence": round(max(0, min(1, confidence)), 3),
                        "mapping_warnings": warnings,
                    })
            return facts

        def table_score(df):
            text = " ".join(clean_cell(x).lower() for x in df.to_numpy().ravel())
            hits = sum(k in text for k in ["maximum lot coverage", "height", "minimum lot line", "minimum separation", "dwelling units"])
            numeric = len(VALUE_RE.findall(text)) + len(UNIT_RANGE_RE.findall(text))
            return hits * 100 + numeric + df.shape[0]

        table_facts = []
        table_logs = []
        doc = fitz.open(PDF_PATH)
        selected_pages = sorted({int(b["page_number"]) for b in selected_blocks if b.get("page_number")})
        for page_number in selected_pages:
            page = doc[page_number - 1]
            candidates = []
            try:
                if hasattr(page, "find_tables"):
                    finder = page.find_tables()
                    for i, table in enumerate(finder.tables):
                        df = pd.DataFrame(table.extract()).fillna("")
                        candidates.append((table_score(df), f"pymupdf_find_tables_{page_number}_{i}", df))
            except Exception as exc:
                table_logs.append({"page_number": page_number, "engine": "pymupdf_find_tables", "error": repr(exc)})
            if not candidates:
                continue
            candidates.sort(reverse=True, key=lambda x: x[0])
            score, name, best_df = candidates[0]
            facts = build_structured_cell_facts_from_df(best_df, name, page_number)
            table_facts.extend(facts)
            best_df.to_csv(EVIDENCE_DIR / f"{name}_table.csv", index=False, encoding="utf-8-sig")
            table_logs.append({"page_number": page_number, "selected_table": name, "score": score, "shape": list(best_df.shape), "facts": len(facts)})

        table_facts_df = pd.DataFrame(table_facts)
        table_facts_df.to_csv(EVIDENCE_DIR / "structured_cell_facts.csv", index=False, encoding="utf-8-sig")
        (EVIDENCE_DIR / "structured_cell_facts.json").write_text(json.dumps(table_facts, indent=2, ensure_ascii=False), encoding="utf-8")
        (EVIDENCE_DIR / "table_extraction_logs.json").write_text(json.dumps(table_logs, indent=2, ensure_ascii=False), encoding="utf-8")

        print("table facts:", len(table_facts_df))
        display(table_facts_df.head(100))
        '''
    ),
    md(
        """
        ## 5. API Helpers

        Gemini is used economically: grouped non-table extraction and one optional
        table semantic review over deterministic table rules. The table values are
        not left to the model; deterministic cell facts provide the values.
        """
    ),
    code(
        r'''
        def call_gemini_once(prompt):
            if not GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY is not set.")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": TEMPERATURE,
                    "maxOutputTokens": MAX_OUTPUT_TOKENS,
                    "responseMimeType": "application/json",
                },
            }
            resp = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts), data

        def call_gemini(prompt):
            last = None
            for attempt in range(GEMINI_MAX_RETRIES + 1):
                if attempt:
                    time.sleep(GEMINI_RETRY_BASE_SECONDS * attempt)
                try:
                    return call_gemini_once(prompt)
                except requests.HTTPError as exc:
                    last = exc
                    status = getattr(exc.response, "status_code", None)
                    if status not in {429, 500, 502, 503, 504}:
                        raise
                except (requests.Timeout, requests.ConnectionError) as exc:
                    last = exc
            raise last

        def parse_json(raw):
            obj, err = helpers.parse_llm_json_response(raw)
            if obj is None:
                raise ValueError(f"JSON parse failed: {err}")
            return obj
        '''
    ),
    md("## 6. Non-Table API Rule Extraction"),
    code(
        r'''
        def compact_evidence(ev):
            return {
                "evidence_id": ev.get("evidence_id"),
                "source_block_id": ev.get("source_block_id"),
                "page_number": ev.get("page_number"),
                "section": ev.get("section"),
                "text": ev.get("text"),
            }

        def chunk_non_table_by_block(evidence, max_items=30):
            by_block = {}
            for ev in evidence:
                by_block.setdefault(ev["source_block_id"], []).append(ev)
            chunks = []
            for block_id, evs in by_block.items():
                for i in range(0, len(evs), max_items):
                    chunks.append((f"{block_id}__chunk_{i // max_items + 1:02d}", evs[i:i + max_items]))
            return chunks

        def build_non_table_prompt(chunk_id, evidence_list):
            inventory = json.dumps([compact_evidence(ev) for ev in evidence_list], ensure_ascii=False)
            return f"""Extract target-relevant zoning rules from non-table legal clauses. Return JSON only.

Target context: {TARGET['description']}

Policy:
- Extract direct, parent-category, generic-applicable, definition/reference, and ambiguous-but-plausible rules.
- Do not extract pure context, table headers, page artifacts, or unrelated sibling-only rules.
- Every rule must cite one evidence_id.
- Split multiple values into atomic rules.
- Keep exception/discretion language in condition/exception.

Schema:
{{
  "chunk_id": "{chunk_id}",
  "rules": [
    {{
      "evidence_id": "...",
      "rule_key": "...",
      "rule_object": "...",
      "constraint_type": "min/max/required/permitted/not_permitted/exception/other",
      "subject": "...",
      "operator": "<=/>=/=/required/permitted/not_permitted",
      "value": "...",
      "unit": "...",
      "condition": "...",
      "exception": null,
      "relevance_category": "direct/indirect/generic_applicable/definition_or_reference/ambiguous"
    }}
  ],
  "skipped_evidence": [{{"evidence_id": "...", "reason": "no_rule/context_only/unrelated/duplicate"}}]
}}

Evidence:
{inventory}
"""

        non_table_raw_rules = []
        non_table_api_logs = []
        if RUN_API_NON_TABLE_EXTRACTION:
            chunks = chunk_non_table_by_block(non_table_evidence)
            for chunk_id, evs in tqdm(chunks, desc="non-table API chunks"):
                prompt = build_non_table_prompt(chunk_id, evs)
                started = time.time()
                raw = ""
                try:
                    raw, _ = call_gemini(prompt)
                    obj = parse_json(raw)
                    rules = obj.get("rules", []) if isinstance(obj, dict) else []
                    for r in rules:
                        if isinstance(r, dict):
                            r["chunk_id"] = chunk_id
                            r["source_stream"] = "api_non_table"
                            non_table_raw_rules.append(r)
                    non_table_api_logs.append({"chunk_id": chunk_id, "evidence": len(evs), "rules": len(rules), "status": "ok", "seconds": time.time() - started, "raw_response": raw})
                except Exception as exc:
                    non_table_api_logs.append({"chunk_id": chunk_id, "evidence": len(evs), "rules": 0, "status": "error", "error": repr(exc), "seconds": time.time() - started, "raw_response": raw})
        else:
            print("RUN_API_NON_TABLE_EXTRACTION=False; skipping API calls.")

        non_table_raw_df = pd.DataFrame(non_table_raw_rules)
        pd.DataFrame(non_table_api_logs).to_csv(API_DIR / "non_table_api_logs.csv", index=False, encoding="utf-8-sig")
        non_table_raw_df.to_csv(API_DIR / "non_table_rules_raw.csv", index=False, encoding="utf-8-sig")
        (API_DIR / "non_table_rules_raw.json").write_text(json.dumps(non_table_raw_rules, indent=2, ensure_ascii=False), encoding="utf-8")

        print("non-table raw rules:", len(non_table_raw_df))
        display(non_table_raw_df.head(80))
        '''
    ),
    md(
        """
        ## 7. Deterministic Table Rule Extraction

        The table path does not ask the API to read flattened rows. It converts each
        structured cell fact into atomic object/value rules, then the API may only
        review semantics/relevance.
        """
    ),
    code(
        r'''
        def normalize_unit(unit):
            u = norm(unit)
            if u in {"%", "percent", "percentage"}:
                return "percent"
            if u in {"m", "meter", "meters", "metre", "metres"}:
                return "m"
            if u in {"m2", "m [2]", "m[2]", "sq m", "sq. m", "square metre", "square metres", "square meter", "square meters"}:
                return "sq. m"
            if "storey" in u or "story" in u:
                return "storeys"
            if "unit" in u:
                return "units"
            if "person" in u:
                return "persons"
            return u

        def parse_number_unit(text):
            s = clean(text).replace(",", "")
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*(%|m2|sq\.?\s*m|square metres?|square meters?|metres?|meters?|m\b|storeys?|stories?|units?|persons?)?", s, flags=re.I)
            if not m:
                return "", ""
            return m.group(1), normalize_unit(m.group(2) or "")

        def split_range_units(text):
            m = re.search(r"(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)(?:\s*/?\s*(units?))?", clean(text), flags=re.I)
            if not m:
                return []
            return [
                {"value": m.group(1), "unit": "units", "operator": ">=", "range_min": m.group(1), "range_max": m.group(2)},
                {"value": m.group(2), "unit": "units", "operator": "<=", "range_min": m.group(1), "range_max": m.group(2)},
            ]

        def clean_condition_path(text):
            parts = [clean(p) for p in re.split(r"\s*/\s*", clean(text)) if clean(p)]
            out = []
            for part in parts:
                low = part.lower()
                if low in {"dwelling type", "unit", "units"}:
                    continue
                if re.fullmatch(r"\d+(?:\.\d+)?\s*to\s*\d+(?:\.\d+)?", part, flags=re.I):
                    part = f"{part} Units"
                if not out or out[-1].lower() != part.lower():
                    out.append(part)
            return " / ".join(out)

        def table_key(group, row_label, value, unit, condition, cell_text):
            g, r, c = norm(group), norm(row_label), norm(condition)
            if "permitted dwelling units" in r:
                return "permitted_dwelling_units"
            if "minimum lot area" in r:
                return "min_lot_area"
            if "maximum lot area" in r:
                return "max_lot_area"
            if "lot coverage" in g and "impervious" in r:
                return "max_impervious_surface"
            if "lot coverage" in g:
                return "max_lot_coverage_all_buildings"
            if g == "height":
                subject = "front_principal_building"
                if "rear principal" in r:
                    subject = "rear_principal_building"
                if "accessory" in r:
                    subject = "accessory_building"
                if normalize_unit(unit) == "storeys":
                    return f"max_{subject}_storeys"
                if "flat roof" in c:
                    return f"max_{subject}_height_flat_roof"
                if "sloping roof" in c or "sloped roof" in c:
                    return f"max_{subject}_height_sloped_roof"
                return f"max_{subject}_height"
            if "setback" in g or "yard" in r:
                if "street yard" in r:
                    return "min_street_yard_setback"
                if "lane yard" in r:
                    return "min_lane_yard_setback"
                if "interior rear" in r:
                    return "min_interior_rear_yard_setback"
                if "interior side" in r:
                    return "min_interior_side_yard_setback"
            if "separation" in g or "between" in r:
                if "front & rear" in r or "front and rear" in r:
                    return "min_separation_between_front_and_rear_principals"
                if "rear principals" in r:
                    return "min_separation_between_rear_principals"
                if "front principals" in r:
                    return "min_separation_between_front_principals"
                if "all other buildings" in r:
                    return "min_separation_between_all_other_buildings"
            return compact_key(f"{group}_{row_label}") or "unknown_table_rule"

        def table_operator(group, key):
            g = norm(group)
            if "maximum" in g or key.startswith("max_"):
                return "<="
            if "minimum" in g or key.startswith("min_"):
                return ">="
            if key == "permitted_dwelling_units":
                return "="
            return "="

        def add_table_rule(fact, value, unit, operator="", condition="", exception="", value_source="cell_fact"):
            group = clean(fact.get("group_title"))
            row_label = clean(fact.get("row_label_path") or fact.get("row_label"))
            cell_text = clean(fact.get("cell_text"))
            col_cond = clean_condition_path(fact.get("column_header_path"))
            local_condition = clean_condition_path(fact.get("local_condition"))
            parts = [p for p in [col_cond, local_condition, clean(condition)] if p]
            full_condition = clean_condition_path(" / ".join(dict.fromkeys(parts)))
            key = table_key(group, row_label, value, unit, full_condition, cell_text)
            return {
                "rule_id": f"table_{clean(fact.get('fact_id'))}_{compact_key(str(value)+'_'+normalize_unit(unit)+'_'+full_condition)}",
                "evidence_id": clean(fact.get("fact_id")),
                "source_stream": "deterministic_table",
                "page_number": fact.get("page_number"),
                "group_title": group,
                "row_label": row_label,
                "column_header": clean(fact.get("column_header_path")),
                "normalized_rule_key": key,
                "rule_object": row_label,
                "operator": operator or table_operator(group, key),
                "value": clean(value),
                "unit": normalize_unit(unit),
                "condition": full_condition,
                "exception": clean(exception),
                "evidence_text": clean(fact.get("row_text")),
                "cell_text": cell_text,
                "value_text": clean(fact.get("value_text") or cell_text),
                "mapping_confidence": fact.get("mapping_confidence", ""),
                "mapping_warnings": json.dumps(fact.get("mapping_warnings", []), ensure_ascii=False) if isinstance(fact.get("mapping_warnings"), list) else clean(fact.get("mapping_warnings")),
                "value_source": value_source,
            }

        def rules_from_cell_fact(fact):
            text = clean(fact.get("value_text") or fact.get("cell_text"))
            row = norm(fact.get("row_label_path") or fact.get("row_label"))
            group = norm(fact.get("group_title"))
            out = []
            warnings = norm(fact.get("mapping_warnings"))
            if "missing_row_label" in warnings or not text or text in {"-", ":"}:
                return out
            if not re.search(r"\d|%|m\b|m2|storey|unit|person", text, flags=re.I):
                return out
            if re.fullmatch(r"\d+\s*units?\s*only:?", text, flags=re.I):
                return out
            if "permitted dwelling units" in row:
                for item in split_range_units(text):
                    rule = add_table_rule(fact, item["value"], item["unit"], item["operator"], value_source="range_endpoint")
                    rule.update({"range_min": item["range_min"], "range_max": item["range_max"], "range_unit": "units", "range_pair_id": f"{rule['normalized_rule_key']}|{rule['condition']}|{item['range_min']}|{item['range_max']}|units"})
                    out.append(rule)
                return out
            exc = re.search(r"(?P<base>\d+(?:\.\d+)?)\s*(?P<unit>m|m2|sq\.?\s*m|%|storeys?)\s*,?\s*except\s*(?P<exc>\d+(?:\.\d+)?)\s*(?P<exc_unit>m|m2|sq\.?\s*m|%|storeys?)?\s*(?:/)?\s*(?:for\s*)?(?P<scope>.*)", text, flags=re.I)
            if exc:
                scope = clean(exc.group("scope"))
                unit = exc.group("unit")
                out.append(add_table_rule(fact, exc.group("base"), unit, exception=f"{exc.group('exc')} {normalize_unit(exc.group('exc_unit') or unit)} for {scope}".strip()))
                out.append(add_table_rule(fact, exc.group("exc"), exc.group("exc_unit") or unit, condition=scope, value_source="derived_from_exception"))
                return out
            pct_condition = re.search(r"(.+?):\s*(\d+(?:\.\d+)?)\s*%", text, flags=re.I)
            if pct_condition:
                out.append(add_table_rule(fact, pct_condition.group(2), "percent", "<=", condition=pct_condition.group(1)))
                return out
            for roof_label, value in re.findall(r"(sloping roof|flat roof)\s*:\s*(\d+(?:\.\d+)?)\s*m", text, flags=re.I):
                out.append(add_table_rule(fact, value, "m", "<=", condition=roof_label.lower()))
            if out:
                return out
            if "accessory" in row:
                for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(m|storeys?|stories?)", text, flags=re.I):
                    out.append(add_table_rule(fact, value, unit, "<="))
                return out
            for label, value in re.findall(r"(front|flanking)\s*:\s*(\d+(?:\.\d+)?)\s*m", text, flags=re.I):
                out.append(add_table_rule(fact, value, "m", ">=", condition=label.lower()))
            bare = re.sub(r"(front|flanking)\s*:\s*\d+(?:\.\d+)?\s*m", "", text, flags=re.I)
            if not out or re.search(r"\d", bare):
                value, unit = parse_number_unit(bare)
                if value:
                    out.insert(0, add_table_rule(fact, value, unit or "m"))
            return out

        table_rules = []
        for fact in table_facts:
            table_rules.extend(rules_from_cell_fact(fact))
        table_rules_df = pd.DataFrame(table_rules)
        table_rules_df.to_csv(RULE_DIR / "table_rules_deterministic.csv", index=False, encoding="utf-8-sig")
        print("deterministic table rules:", len(table_rules_df))
        display(table_rules_df.head(120))
        '''
    ),
    md("## 8. Optional API Table Semantic Review"),
    code(
        r'''
        table_semantic_reviews = []

        def build_table_semantic_prompt(rules_df):
            cols = ["rule_id", "normalized_rule_key", "rule_object", "operator", "value", "unit", "condition", "exception", "group_title", "row_label", "column_header", "cell_text"]
            records = rules_df[cols].fillna("").to_dict("records") if not rules_df.empty else []
            compact = json.dumps(records, ensure_ascii=False)
            return f"""Review these deterministic table-derived zoning rules. Do not change values.

Target context: {TARGET['description']}

For each rule_id, classify:
- relevance_category: direct / indirect / generic_applicable / definition_or_reference / unrelated / ambiguous
- final_action_hint: ACCEPT / REVIEW / REJECT
- reason: short reason

Return JSON only:
{{"reviews": [{{"rule_id": "...", "relevance_category": "...", "final_action_hint": "...", "reason": "..."}}]}}

Rules:
{compact}
"""

        if RUN_API_TABLE_SEMANTIC_REVIEW and not table_rules_df.empty:
            prompt = build_table_semantic_prompt(table_rules_df)
            raw = ""
            try:
                raw, _ = call_gemini(prompt)
                obj = parse_json(raw)
                table_semantic_reviews = obj.get("reviews", []) if isinstance(obj, dict) else []
                (API_DIR / "table_semantic_review_raw.json").write_text(raw, encoding="utf-8")
            except Exception as exc:
                print("table semantic API review failed:", repr(exc))
                (API_DIR / "table_semantic_review_error.txt").write_text(repr(exc) + "\n\n" + raw, encoding="utf-8")
        else:
            print("Skipping table semantic API review.")

        reviews_df = pd.DataFrame(table_semantic_reviews)
        reviews_df.to_csv(API_DIR / "table_semantic_reviews.csv", index=False, encoding="utf-8-sig")
        print("table semantic reviews:", len(reviews_df))
        display(reviews_df.head(80))
        '''
    ),
    md("## 9. Normalize Non-Table Rules and Merge"),
    code(
        r'''
        non_table_lookup = {ev["evidence_id"]: ev for ev in non_table_evidence}

        def normalize_non_table_key(rule):
            text = norm(" ".join(clean(rule.get(k)) for k in ["rule_key", "rule_object", "subject", "condition", "value"]))
            raw_key = norm(rule.get("rule_key"))
            if raw_key in {"101.1", "101_1"} or ("maximum number of dwelling units" in text and "6" in text):
                return "max_dwelling_units"
            if raw_key in {"101.3.2", "101_3_2"} or ("panhandle" in text and "not" in text and "permitted" in text):
                return "not_permitted_panhandle_or_irregular_lot"
            if raw_key in {"101.3.3", "101_3_3"} or ("rowhouse" in text and "280" in text and ("may exceed" in text or "subject to" in text)):
                return "max_rowhouse_lot_area_exception"
            if "garage" in text and "carport" in text and ("above" in text or "1.2" in text) and ("height" in text or "surface" in text or "surrounding ground" in text):
                return "max_garage_carport_above_grade_height"
            if "garage" in text and "carport" in text and ("lot line" in text or "setback" in text):
                return "min_garage_carport_lot_line_setback"
            if "sprinkler" in text:
                return "required_automatic_sprinkler_system"
            if "fire access corridor" in text and ("width" in text or "1.0" in text):
                return "min_fire_access_corridor_width"
            if "clear" in text and "height" in text:
                return "min_clear_height"
            if "panhandle" in text and "width" in text:
                return "min_panhandle_width"
            if "walkway" in text and ("wide" in text or "width" in text):
                return "min_pedestrian_walkway_width"
            if "walkway" in text and ("spaced" in text or "spacing" in text):
                return "max_pedestrian_walkway_spacing"
            if "main entrance" in text:
                return "required_main_entrance_orientation"
            if "floor area" in text:
                return "min_floor_area"
            if "impervious" in text:
                return "max_impervious_surface_exception"
            if "lot coverage" in text:
                return "max_lot_coverage_exception"
            if "street yard" in text and ("setback" in text or "2.0" in text):
                return "min_street_yard_setback_exception"
            if "parking" in text and ("not required" in text or "not_permitted" in text):
                return "not_required_off_street_parking"
            if "parking" in text:
                return "parking_location_permission"
            if "separation" in text and ("6.0" in text or "front and rear" in text or "front & rear" in text):
                return "min_separation_between_front_and_rear_principals"
            if "separation" in text and "2.4" in text:
                return "min_separation_between_other_principals"
            return compact_key(rule.get("rule_key")) or "unknown_non_table_rule"

        UNRELATED_NON_TABLE_TERMS = [
            "boarding", "lodging", "rooming house", "supportive housing",
            "child care", "group home", "home occupation", "urban agriculture",
        ]

        def classify_non_table_route(rule, ev):
            hay = norm(" ".join(clean(rule.get(k)) for k in ["rule_key", "rule_object", "subject", "condition", "exception", "relevance_category"]))
            evidence = norm(ev.get("text", ""))
            text = hay + " " + evidence
            key = normalize_non_table_key(rule)
            if any(term in text for term in UNRELATED_NON_TABLE_TERMS):
                return "REJECT", "not_target_relevant_use_specific"
            if key.startswith("101_") or re.fullmatch(r"101(?:_\d+)+.*", key):
                return "REVIEW", "section_id_key_needs_object_normalization"
            if any(term in text for term in ["heritage", "director", "comprehensive development district"]):
                return "REVIEW", "special_approval_or_external_scope"
            if "definition_or_reference" in text or any(term in key for term in ["measurement", "projection", "applicability"]):
                return "REVIEW", "definition_or_reference_scope"
            return "", ""

        def normalize_non_table_rule(rule):
            ev = non_table_lookup.get(clean(rule.get("evidence_id")), {})
            key = normalize_non_table_key(rule)
            unit = normalize_unit(rule.get("unit"))
            value = clean(rule.get("value"))
            op = clean(rule.get("operator"))
            evidence_text = clean(ev.get("text", ""))
            if key == "max_pedestrian_walkway_spacing":
                # Gemini sometimes returns the whole phrase
                # "spaced every 100 m or less..." as the value. Make this an
                # atomic numeric rule before the verification handoff.
                m = re.search(r"spaced\s+every\s+(\d+(?:\.\d+)?)\s*m\s+or\s+less", evidence_text, flags=re.I)
                if not m:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*m\s+or\s+less", evidence_text, flags=re.I)
                if m:
                    value = m.group(1)
                    unit = "m"
                    op = "<="
            if value.endswith("%") and unit in {"", "percent"}:
                value = value[:-1].strip()
                unit = "percent"
            if key.startswith("min_") and not op:
                op = ">="
            if key.startswith("max_") and not op:
                op = "<="
            if key.startswith("required_") and not op:
                op = "required"
            route_hint, route_reason = classify_non_table_route(rule, ev)
            return {
                "rule_id": f"nt_{clean(rule.get('evidence_id'))}_{compact_key(key+'_'+value)}",
                "evidence_id": clean(rule.get("evidence_id")),
                "source_stream": "api_non_table",
                "page_number": ev.get("page_number", ""),
                "group_title": "",
                "row_label": clean(rule.get("rule_object") or rule.get("subject")),
                "column_header": "",
                "normalized_rule_key": key,
                "rule_object": clean(rule.get("rule_object") or rule.get("subject")),
                "operator": op,
                "value": value,
                "unit": unit,
                "condition": clean(rule.get("condition")),
                "exception": clean(rule.get("exception")),
                "relevance_category": clean(rule.get("relevance_category")),
                "target_route_hint": route_hint,
                "target_route_reason": route_reason,
                "evidence_text": evidence_text,
                "cell_text": "",
                "value_text": value,
                "value_source": "api_non_table",
            }

        non_table_rules_df = pd.DataFrame([normalize_non_table_rule(r) for r in non_table_raw_rules])

        if not table_rules_df.empty and not reviews_df.empty:
            review_map = reviews_df.set_index("rule_id").to_dict("index")
            for col in ["relevance_category", "final_action_hint", "semantic_review_reason"]:
                if col not in table_rules_df.columns:
                    table_rules_df[col] = ""
            table_rules_df["relevance_category"] = table_rules_df.apply(lambda r: clean(review_map.get(r["rule_id"], {}).get("relevance_category")) or clean(r.get("relevance_category")) or "generic_applicable", axis=1)
            table_rules_df["final_action_hint"] = table_rules_df.apply(lambda r: clean(review_map.get(r["rule_id"], {}).get("final_action_hint")), axis=1)
            table_rules_df["semantic_review_reason"] = table_rules_df.apply(lambda r: clean(review_map.get(r["rule_id"], {}).get("reason")), axis=1)
        elif not table_rules_df.empty:
            table_rules_df["relevance_category"] = "generic_applicable"
            table_rules_df["final_action_hint"] = ""
            table_rules_df["semantic_review_reason"] = ""

        combined_df = pd.concat([table_rules_df, non_table_rules_df], ignore_index=True, sort=False)
        combined_df.to_csv(RULE_DIR / "all_rules_merged_raw.csv", index=False, encoding="utf-8-sig")
        print("non-table normalized:", len(non_table_rules_df))
        print("combined raw:", len(combined_df))
        display(combined_df.head(120))
        '''
    ),
    md(
        """
        ## 10. Verification, Deduplication, and Final Registry

        This borrows the old sentence/evidence verification idea, but keeps table
        support table-aware: table operators can come from group titles, and table
        rule types can come from row/column headers.
        """
    ),
    code(
        r'''
        REVIEW_WORDS = {
            "except": "exception_scope",
            "subject to": "cross_reference_or_condition",
            "may": "discretionary_or_optional",
            "provided that": "condition_scope",
            "director": "discretionary_language",
        }

        def value_visible(value, evidence_text):
            v = clean(value)
            if not v:
                return True
            text = norm(evidence_text)
            variants = {norm(v)}
            try:
                num = float(v)
                variants.add(str(int(num)) if num.is_integer() else str(num))
            except Exception:
                pass
            return any(x and x in text for x in variants)

        def operator_supported(row):
            op = clean(row.get("operator"))
            if clean(row.get("normalized_rule_key")) == "permitted_dwelling_units" and op in {"<=", ">=", "=", "range"}:
                return True
            if row.get("source_stream") == "deterministic_table":
                g = norm(row.get("group_title"))
                if op == "<=" and ("maximum" in g or str(row.get("normalized_rule_key", "")).startswith("max_")):
                    return True
                if op == ">=" and ("minimum" in g or str(row.get("normalized_rule_key", "")).startswith("min_")):
                    return True
                if op == "=":
                    return True
            text = norm(row.get("evidence_text"))
            if op == "<=":
                return any(k in text for k in ["maximum", "not exceed", "up to", "less than", "or less"])
            if op == ">=":
                return any(k in text for k in ["minimum", "at least", "not less", "greater than"])
            return True

        def verify_row(row):
            evidence_text = clean(row.get("evidence_text")) or clean(row.get("cell_text"))
            gaps = []
            reasons = []
            if not value_visible(row.get("value"), evidence_text):
                gaps.append("value_not_visible_in_evidence")
            if not operator_supported(row):
                gaps.append("operator_not_supported")
            text = norm(" ".join(clean(row.get(c)) for c in ["evidence_text", "cell_text", "condition", "exception"]))
            for word, reason in REVIEW_WORDS.items():
                if word in text and reason not in reasons:
                    reasons.append(reason)
            hint = clean(row.get("final_action_hint"))
            target_route_hint = clean(row.get("target_route_hint"))
            target_route_reason = clean(row.get("target_route_reason"))
            if target_route_reason:
                reasons.append(target_route_reason)
            if target_route_hint == "REJECT" or hint == "REJECT":
                final = "REJECT"
            elif target_route_hint == "REVIEW":
                final = "REVIEW"
            elif gaps:
                final = "REVIEW"
            elif hint == "REVIEW" or reasons:
                final = "REVIEW"
            else:
                final = "ACCEPT"
            status = "verified" if not gaps else "possible_sentence_match"
            return pd.Series({
                "verification_status": status,
                "support_gaps": json.dumps(gaps, ensure_ascii=False),
                "review_reasons": json.dumps(reasons, ensure_ascii=False),
                "final_action": final,
            })

        if combined_df.empty:
            verified_df = combined_df.copy()
        else:
            verified_df = pd.concat([combined_df.reset_index(drop=True), combined_df.apply(verify_row, axis=1)], axis=1)

        def specificity_score(row):
            score = 0
            for col in ["condition", "column_header", "exception", "semantic_review_reason"]:
                if clean(row.get(col)):
                    score += 1
            if row.get("verification_status") == "verified":
                score += 2
            if row.get("final_action") == "ACCEPT":
                score += 1
            return score

        if not verified_df.empty:
            verified_df["dedup_key"] = verified_df.apply(lambda r: "|".join(norm(r.get(c)) for c in ["source_stream", "normalized_rule_key", "operator", "value", "unit", "condition", "exception"]), axis=1)
            verified_df["specificity_score"] = verified_df.apply(specificity_score, axis=1)
            deduped_df = (
                verified_df.sort_values(["dedup_key", "specificity_score"], ascending=[True, False])
                .drop_duplicates("dedup_key", keep="first")
                .reset_index(drop=True)
            )
        else:
            deduped_df = verified_df.copy()

        accepted_df = deduped_df[deduped_df.get("final_action", "") == "ACCEPT"].copy() if not deduped_df.empty else deduped_df.copy()
        review_df = deduped_df[deduped_df.get("final_action", "") == "REVIEW"].copy() if not deduped_df.empty else deduped_df.copy()
        rejected_df = deduped_df[deduped_df.get("final_action", "") == "REJECT"].copy() if not deduped_df.empty else deduped_df.copy()
        warning_df = deduped_df[deduped_df.get("support_gaps", "[]") != "[]"].copy() if not deduped_df.empty else deduped_df.copy()

        print("verified raw:", len(verified_df))
        print("deduped:", len(deduped_df))
        print("accepted:", len(accepted_df), "review:", len(review_df), "rejected:", len(rejected_df))
        if not deduped_df.empty:
            display(deduped_df[["source_stream", "normalized_rule_key", "operator", "value", "unit", "condition", "exception", "final_action", "support_gaps", "review_reasons"]].head(160))
        '''
    ),
    md("## 11. Save Outputs and Summary"),
    code(
        r'''
        verified_df.to_csv(RULE_DIR / "all_rules_verified_raw.csv", index=False, encoding="utf-8-sig")
        deduped_df.to_csv(RULE_DIR / "final_registry.csv", index=False, encoding="utf-8-sig")
        deduped_df.to_json(RULE_DIR / "final_registry.json", orient="records", force_ascii=False, indent=2)
        accepted_df.to_csv(RULE_DIR / "accepted_rules.csv", index=False, encoding="utf-8-sig")
        review_df.to_csv(RULE_DIR / "review_queue.csv", index=False, encoding="utf-8-sig")
        rejected_df.to_csv(RULE_DIR / "rejected_candidates.csv", index=False, encoding="utf-8-sig")
        warning_df.to_csv(RULE_DIR / "verification_warnings.csv", index=False, encoding="utf-8-sig")

        HANDOFF_DIR = OUTPUT_DIR / "06_teammate_verification_handoff"
        HANDOFF_DIR.mkdir(parents=True, exist_ok=True)

        def row_to_handoff_candidate(row):
            return {
                "candidate_id": clean(row.get("rule_id")),
                "municipality": TARGET["city"],
                "province": TARGET["province"],
                "zone": TARGET["zone"],
                "target_building_type": TARGET["building_type"],
                "rule_key": clean(row.get("normalized_rule_key")),
                "rule_object": clean(row.get("rule_object") or row.get("row_label")),
                "operator": clean(row.get("operator")),
                "value": clean(row.get("value")),
                "unit": clean(row.get("unit")),
                "condition": clean(row.get("condition")),
                "exception": clean(row.get("exception")),
                "relevance_category": clean(row.get("relevance_category")),
                "source_stream": clean(row.get("source_stream")),
                "source_block_id": clean(row.get("source_block_id")),
                "source_evidence_id": clean(row.get("evidence_id")),
                "source_evidence_text": clean(row.get("evidence_text") or row.get("cell_text")),
                "page_number": clean(row.get("page_number")),
                "extraction_final_action": clean(row.get("final_action")),
                "extraction_support_gaps": clean(row.get("support_gaps")),
                "extraction_review_reasons": clean(row.get("review_reasons")),
            }

        candidate_df = deduped_df[deduped_df.get("final_action", "") != "REJECT"].copy() if not deduped_df.empty else deduped_df.copy()
        handoff_candidates = [row_to_handoff_candidate(r) for _, r in candidate_df.iterrows()]
        handoff_accepted = [row_to_handoff_candidate(r) for _, r in accepted_df.iterrows()]
        handoff_review = [row_to_handoff_candidate(r) for _, r in review_df.iterrows()]

        table_evidence_units = []
        for fact in table_facts:
            table_evidence_units.append({
                "evidence_id": clean(fact.get("fact_id")),
                "evidence_type": "table_cell",
                "source_stream": "deterministic_table",
                "municipality": TARGET["city"],
                "province": TARGET["province"],
                "zone": TARGET["zone"],
                "page_number": fact.get("page_number"),
                "group_title": clean(fact.get("group_title")),
                "row_label": clean(fact.get("row_label_path")),
                "column_header": clean(fact.get("column_header_path")),
                "cell_text": clean(fact.get("cell_text")),
                "text": clean(fact.get("row_text")),
            })
        handoff_evidence_units = list(non_table_evidence) + table_evidence_units

        pd.DataFrame(handoff_candidates).to_csv(HANDOFF_DIR / "rule_candidates.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(handoff_accepted).to_csv(HANDOFF_DIR / "accepted_rule_candidates.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(handoff_review).to_csv(HANDOFF_DIR / "review_rule_candidates.csv", index=False, encoding="utf-8-sig")
        (HANDOFF_DIR / "rule_candidates.json").write_text(json.dumps(handoff_candidates, indent=2, ensure_ascii=False), encoding="utf-8")
        (HANDOFF_DIR / "accepted_rule_candidates.json").write_text(json.dumps(handoff_accepted, indent=2, ensure_ascii=False), encoding="utf-8")
        (HANDOFF_DIR / "review_rule_candidates.json").write_text(json.dumps(handoff_review, indent=2, ensure_ascii=False), encoding="utf-8")
        (HANDOFF_DIR / "evidence_units.json").write_text(json.dumps(handoff_evidence_units, indent=2, ensure_ascii=False), encoding="utf-8")

        expected_burnaby_keys = [
            "max_dwelling_units",
            "permitted_dwelling_units", "min_lot_area", "max_lot_area",
            "max_lot_coverage_all_buildings", "max_impervious_surface",
            "max_front_principal_building_height_sloped_roof", "max_front_principal_building_height_flat_roof", "max_front_principal_building_storeys",
            "max_rear_principal_building_height_sloped_roof", "max_rear_principal_building_height_flat_roof", "max_rear_principal_building_storeys",
            "max_accessory_building_height", "max_accessory_building_storeys",
            "min_street_yard_setback", "min_lane_yard_setback", "min_interior_rear_yard_setback", "min_interior_side_yard_setback",
            "min_separation_between_front_principals", "min_separation_between_rear_principals", "min_separation_between_front_and_rear_principals", "min_separation_between_all_other_buildings",
            "required_main_entrance_orientation", "max_pedestrian_walkway_spacing", "min_pedestrian_walkway_width", "min_clear_height",
            "min_floor_area", "required_automatic_sprinkler_system", "min_fire_access_corridor_width", "min_panhandle_width",
            "max_lot_coverage_exception", "max_impervious_surface_exception", "min_street_yard_setback_exception", "not_required_off_street_parking",
        ]
        found = set(deduped_df["normalized_rule_key"]) if not deduped_df.empty and "normalized_rule_key" in deduped_df else set()
        coverage_df = pd.DataFrame([{"expected_key": k, "found": k in found} for k in expected_burnaby_keys])
        coverage_df.to_csv(RULE_DIR / "expected_key_coverage.csv", index=False, encoding="utf-8-sig")

        summary = [
            "# Pipeline 3 Summary",
            "",
            f"target_city: {TARGET_CITY}",
            f"blocks: {len(all_blocks)}",
            f"selected_blocks: {len(selected_blocks)}",
            f"non_table_evidence: {len(non_table_evidence)}",
            f"structured_cell_facts: {len(table_facts_df)}",
            f"non_table_raw_rules: {len(non_table_raw_df)}",
            f"table_rules_deterministic: {len(table_rules_df)}",
            f"combined_rules_raw: {len(combined_df)}",
            f"deduped_final_registry: {len(deduped_df)}",
            f"accepted_rules: {len(accepted_df)}",
            f"review_rules: {len(review_df)}",
            f"rejected_rules: {len(rejected_df)}",
            f"verification_warnings: {len(warning_df)}",
            f"expected_keys_found: {int(coverage_df['found'].sum())}/{len(coverage_df)}",
            f"handoff_rule_candidates: {len(handoff_candidates)}",
            f"handoff_evidence_units: {len(handoff_evidence_units)}",
            f"handoff_dir: {HANDOFF_DIR}",
            "",
            "## Counts By Stream/Action",
            deduped_df.groupby(["source_stream", "final_action"]).size().to_string() if not deduped_df.empty else "(none)",
            "",
            "## Counts By Key",
            deduped_df["normalized_rule_key"].value_counts().sort_index().to_string() if not deduped_df.empty else "(none)",
        ]
        (RULE_DIR / "pipeline3_summary.md").write_text("\n".join(summary), encoding="utf-8")
        print((RULE_DIR / "pipeline3_summary.md").read_text(encoding="utf-8"))
        print("Saved outputs:", OUTPUT_DIR)
        '''
    ),
]

nbf.write(nb, OUT)
print(f"Wrote {OUT}")
