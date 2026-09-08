#!/usr/bin/env python3
"""Split a zoning PDF into text blocks and title-inclusive table image crops."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import fitz
import requests
from tqdm.auto import tqdm


DEFAULT_MODEL = "gemini-3.1-pro-preview"
BBOX_KEYS = ("x_min", "y_min", "x_max", "y_max")

PAGE_LAYOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "page_summary": {"type": "string"},
        "text_blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reading_order": {"type": "integer"},
                    "block_type": {
                        "type": "string",
                        "enum": [
                            "heading",
                            "paragraph",
                            "list_item",
                            "footnote",
                            "amendment_note",
                        ],
                    },
                    "section_path": {"type": "array", "items": {"type": "string"}},
                    "text": {"type": "string"},
                    "parent_context": {"type": "string"},
                    "bbox": {
                        "type": "object",
                        "properties": {
                            "x_min": {"type": "integer"},
                            "y_min": {"type": "integer"},
                            "x_max": {"type": "integer"},
                            "y_max": {"type": "integer"},
                        },
                        "required": list(BBOX_KEYS),
                    },
                    "continues_from_previous_page": {"type": "boolean"},
                    "continues_on_next_page": {"type": "boolean"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "reading_order",
                    "block_type",
                    "section_path",
                    "text",
                    "parent_context",
                    "bbox",
                    "continues_from_previous_page",
                    "continues_on_next_page",
                    "warnings",
                ],
            },
        },
        "table_regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reading_order": {"type": "integer"},
                    "section_path": {"type": "array", "items": {"type": "string"}},
                    "section_heading": {"type": "string"},
                    "table_bbox": {
                        "type": "object",
                        "properties": {
                            "x_min": {"type": "integer"},
                            "y_min": {"type": "integer"},
                            "x_max": {"type": "integer"},
                            "y_max": {"type": "integer"},
                        },
                        "required": list(BBOX_KEYS),
                    },
                    "section_heading_bbox": {
                        "type": "object",
                        "properties": {
                            "x_min": {"type": "integer"},
                            "y_min": {"type": "integer"},
                            "x_max": {"type": "integer"},
                            "y_max": {"type": "integer"},
                        },
                        "required": list(BBOX_KEYS),
                    },
                    "crop_bbox": {
                        "type": "object",
                        "properties": {
                            "x_min": {"type": "integer"},
                            "y_min": {"type": "integer"},
                            "x_max": {"type": "integer"},
                            "y_max": {"type": "integer"},
                        },
                        "required": list(BBOX_KEYS),
                    },
                    "continues_from_previous_page": {"type": "boolean"},
                    "continues_on_next_page": {"type": "boolean"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "reading_order",
                    "section_path",
                    "section_heading",
                    "table_bbox",
                    "section_heading_bbox",
                    "crop_bbox",
                    "continues_from_previous_page",
                    "continues_on_next_page",
                    "warnings",
                ],
            },
        },
        "page_warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["page_summary", "text_blocks", "table_regions", "page_warnings"],
}

PAGE_LAYOUT_PROMPT = """Analyze this zoning-bylaw PDF page as a document-layout splitter.

Your job is routing, not rule extraction.

Return:
1. Text blocks for clause-style content outside tables.
2. Bounding boxes for tables so local code can crop table images for a separate table pipeline.

Coordinate contract:
- Use integer coordinates normalized to a 0..1000 page canvas.
- A bbox is {x_min, y_min, x_max, y_max}.

Text-block instructions:
- Transcribe clause-style text faithfully.
- Preserve headings, paragraphs, list items, footnotes, and amendment notes as separate blocks.
- Use section_path to retain visible hierarchy, including section numbers and list markers.
- Put inherited visible context in parent_context, especially for nested list items.
- Mark cross-page continuations when visible or strongly indicated by an incomplete start/end.
- Do not transcribe table rows, table headers, or table cell contents into text_blocks.
- Do not include recurring page headers, page footers, or page numbers.

Table-region instructions:
- Detect each visible table as one table region.
- Do not transcribe, reconstruct, summarize, or interpret table contents.
- table_bbox must tightly cover the visible table.
- section_heading_bbox must cover the nearest visible section heading or table title that establishes
  the table context. Use a zero-area bbox at the top-left of table_bbox only when no heading is visible.
- crop_bbox must include both the visible section heading/title and the table itself, while excluding
  unrelated surrounding prose where possible.
- Keep a table that continues across pages as one region on each page and set continuation flags.

Use warnings for illegible content, uncertain hierarchy, uncertain boundaries, or continuation ambiguity.
Do not infer missing source text and do not use outside knowledge."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Input PDF path.")
    parser.add_argument("output_dir", type=Path, help="Directory for generated artifacts.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name.")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY", help="Environment variable holding the API key.")
    parser.add_argument("--pages", help="Optional 1-based page selection, for example: 1-3,7.")
    parser.add_argument("--scale", type=float, default=3.0, help="Rasterization scale for table crops (quality-critical).")
    parser.add_argument("--layout-scale", type=float, default=None,
                        help="Optional lower scale for the full-page layout image (defaults to --scale).")
    parser.add_argument("--skip-empty-pages", action="store_true",
                        help="Skip the layout API call for pages with no text and no images.")
    parser.add_argument("--crop-padding-points", type=float, default=6.0, help="Padding added around table crops.")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP request timeout in seconds.")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries for transient API failures.")
    parser.add_argument("--retry-base-seconds", type=int, default=20, help="Linear retry backoff base.")
    parser.add_argument("--overwrite", action="store_true", help="Call Gemini again even when cached JSON exists.")
    return parser.parse_args()


def parse_page_selection(raw: str | None, page_count: int) -> list[int]:
    if not raw:
        return list(range(1, page_count + 1))
    pages: set[int] = set()
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        if "-" in token:
            start, end = (int(part.strip()) for part in token.split("-", 1))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(token))
    invalid = sorted(page for page in pages if page < 1 or page > page_count)
    if invalid:
        raise ValueError(f"Page selection outside PDF range 1..{page_count}: {invalid}")
    return sorted(pages)


def call_gemini_layout(
    page_png: bytes,
    *,
    model: str,
    api_key: str,
    timeout: int,
    max_retries: int,
    retry_base_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(page_png).decode("ascii")}},
                {"text": PAGE_LAYOUT_PROMPT},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 32000,
            "responseMimeType": "application/json",
            "responseJsonSchema": PAGE_LAYOUT_SCHEMA,
        },
    }
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        if attempt:
            time.sleep(retry_base_seconds * attempt)
        try:
            response = requests.post(url, params={"key": api_key}, json=payload, timeout=timeout)
            response.raise_for_status()
            raw_response = response.json()
            parts = raw_response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts)
            return json.loads(text), raw_response
        except requests.HTTPError as exc:
            last_error = exc
            status = getattr(exc.response, "status_code", None)
            if status not in {429, 500, 502, 503, 504}:
                raise
        except (requests.Timeout, requests.ConnectionError, json.JSONDecodeError) as exc:
            last_error = exc
    if last_error is None:
        raise RuntimeError("Gemini layout extraction failed without an error.")
    raise last_error


def normalized_bbox(value: Any) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    bbox = {key: max(0, min(1000, int(raw.get(key, 0)))) for key in BBOX_KEYS}
    if bbox["x_max"] < bbox["x_min"]:
        bbox["x_min"], bbox["x_max"] = bbox["x_max"], bbox["x_min"]
    if bbox["y_max"] < bbox["y_min"]:
        bbox["y_min"], bbox["y_max"] = bbox["y_max"], bbox["y_min"]
    return bbox


def union_bbox(*values: Any) -> dict[str, int]:
    boxes = [normalized_bbox(value) for value in values]
    usable = [box for box in boxes if box["x_max"] > box["x_min"] and box["y_max"] > box["y_min"]]
    if not usable:
        return normalized_bbox(values[0] if values else {})
    return {
        "x_min": min(box["x_min"] for box in usable),
        "y_min": min(box["y_min"] for box in usable),
        "x_max": max(box["x_max"] for box in usable),
        "y_max": max(box["y_max"] for box in usable),
    }


def bbox_to_page_rect(bbox: dict[str, int], page: fitz.Page, padding: float = 0.0) -> fitz.Rect:
    rect = page.rect
    result = fitz.Rect(
        rect.x0 + rect.width * bbox["x_min"] / 1000,
        rect.y0 + rect.height * bbox["y_min"] / 1000,
        rect.x0 + rect.width * bbox["x_max"] / 1000,
        rect.y0 + rect.height * bbox["y_max"] / 1000,
    )
    result = fitz.Rect(result.x0 - padding, result.y0 - padding, result.x1 + padding, result.y1 + padding)
    return result & rect


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_or_extract_page(
    *,
    page: fitz.Page,
    page_number: int,
    args: argparse.Namespace,
    api_key: str,
    pages_dir: Path,
    raw_dir: Path,
) -> dict[str, Any]:
    page_png_path = pages_dir / f"page_{page_number:04d}.png"
    extraction_path = raw_dir / f"page_{page_number:04d}_layout.json"
    api_path = raw_dir / f"page_{page_number:04d}_api_response.json"
    # The full-page image is used only for layout/bbox + clause-text transcription;
    # table VALUES are read from the high-res crop (args.scale) later. So an optional
    # lower layout_scale saves image tokens without touching table-read quality.
    # Defaults to args.scale, keeping existing pipelines unchanged.
    layout_scale = getattr(args, "layout_scale", None) or args.scale
    pixmap = page.get_pixmap(matrix=fitz.Matrix(layout_scale, layout_scale), alpha=False)
    page_png = pixmap.tobytes("png")
    page_png_path.write_bytes(page_png)
    if extraction_path.exists() and not args.overwrite:
        return json.loads(extraction_path.read_text(encoding="utf-8"))
    extraction, raw_response = call_gemini_layout(
        page_png,
        model=args.model,
        api_key=api_key,
        timeout=args.timeout,
        max_retries=args.max_retries,
        retry_base_seconds=args.retry_base_seconds,
    )
    write_json(extraction_path, extraction)
    write_json(api_path, raw_response)
    return extraction


def _rect_to_1000(rect: fitz.Rect, page: fitz.Page) -> dict[str, int]:
    """Convert a page-coordinate rect to the 0..1000 normalized bbox the pipeline uses."""
    pr = page.rect
    w = pr.width or 1.0
    h = pr.height or 1.0

    def n(value: float, lo: float, span: float) -> int:
        return max(0, min(1000, round((value - lo) / span * 1000)))

    return {
        "x_min": n(rect.x0, pr.x0, w), "y_min": n(rect.y0, pr.y0, h),
        "x_max": n(rect.x1, pr.x0, w), "y_max": n(rect.y1, pr.y0, h),
    }


_LIST_ITEM_RE = re.compile(r"^\(?[a-zA-Z0-9]{1,3}\)\s|^[•–—\-\*]\s")
_SECTION_NUM_RE = re.compile(r"^\d+(?:\.\d+)*\b")


def _local_block_type(text: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    if _LIST_ITEM_RE.match(first):
        return "list_item"
    # Short, title-like or section-numbered line with no terminal punctuation -> heading.
    if first and len(first) <= 70 and not re.search(r"[.;:]$", first) and (
        _SECTION_NUM_RE.match(first) or first.isupper() or first.istitle()
    ):
        return "heading"
    return "paragraph"


def _local_layout(page: fitz.Page, page_number: int, args: argparse.Namespace, pages_dir: Path) -> dict[str, Any]:
    """Produce a vision-compatible page layout from the digital text layer +
    PyMuPDF table detection, with NO API call.

    Returns the same dict shape as ``call_gemini_layout`` so the block-assembly and
    table-crop code in ``process_pdf`` is reused unchanged. Used for digital PDFs;
    callers fall back to the vision layout for pages with no extractable text.
    """
    layout_scale = getattr(args, "layout_scale", None) or args.scale
    pixmap = page.get_pixmap(matrix=fitz.Matrix(layout_scale, layout_scale), alpha=False)
    (pages_dir / f"page_{page_number:04d}.png").write_bytes(pixmap.tobytes("png"))

    try:
        table_rects = [fitz.Rect(t.bbox) for t in page.find_tables().tables]
    except Exception:
        table_rects = []

    def _in_table(rect: fitz.Rect) -> bool:
        center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
        return any(tr.contains(center) for tr in table_rects)

    prose: list[tuple[fitz.Rect, str]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:  # skip image blocks
            continue
        rect = fitz.Rect(block["bbox"])
        lines = []
        for line in block.get("lines", []):
            txt = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if txt:
                lines.append(txt)
        text = "\n".join(lines).strip()
        if text and not _in_table(rect):
            prose.append((rect, text))
    prose.sort(key=lambda rt: (round(rt[0].y0, 1), round(rt[0].x0, 1)))

    text_blocks = []
    current_heading = ""
    for order, (rect, text) in enumerate(prose, start=1):
        btype = _local_block_type(text)
        if btype == "heading":
            current_heading = text.strip().splitlines()[0]
        text_blocks.append({
            "reading_order": order,
            "block_type": btype,
            "section_path": [current_heading] if current_heading else [],
            "text": text,
            "parent_context": current_heading,
            "bbox": _rect_to_1000(rect, page),
            "continues_from_previous_page": False,
            "continues_on_next_page": False,
            "warnings": [],
        })

    # Associate each table with the nearest heading line above it; only fold the
    # heading into the crop when it sits close above (else the crop would balloon).
    headings = [(rect, text) for rect, text in prose if _local_block_type(text) == "heading"]
    near_gap = page.rect.height * 0.12
    table_regions = []
    for order, tr in enumerate(sorted(table_rects, key=lambda r: r.y0), start=1):
        above = [(rect, text) for rect, text in headings if rect.y1 <= tr.y0 + 2]
        section_heading = ""
        heading_bbox = _rect_to_1000(tr, page)
        if above:
            head_rect, head_text = max(above, key=lambda rt: rt[0].y1)
            section_heading = head_text.strip().splitlines()[0]
            if tr.y0 - head_rect.y1 <= near_gap:
                heading_bbox = _rect_to_1000(head_rect, page)
        table_bbox = _rect_to_1000(tr, page)
        table_regions.append({
            "reading_order": order,
            "section_path": [section_heading] if section_heading else [],
            "section_heading": section_heading,
            "table_bbox": table_bbox,
            "section_heading_bbox": heading_bbox,
            "crop_bbox": table_bbox,
        })

    return {"page_summary": "", "text_blocks": text_blocks, "table_regions": table_regions}


def _map_batches(items, work, *, max_workers, desc, unit):
    """Run ``work(item)`` over ``items``, returning results in input order.

    ``max_workers <= 1`` keeps the original sequential loop (unchanged for
    existing callers); otherwise the independent per-item API calls run on a
    bounded thread pool and results are reassembled in the original order.
    """
    items = list(items)
    if not items:
        return []
    if max_workers is None or max_workers <= 1 or len(items) == 1:
        return [work(item) for item in tqdm(items, desc=desc, unit=unit)]
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[Any] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(work, item): index for index, item in enumerate(items)}
        for future in tqdm(as_completed(futures), total=len(items), desc=desc, unit=unit):
            results[futures[future]] = future.result()
    return results


def process_pdf(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"{args.api_key_env} is not set.")
    output_dir = args.output_dir.resolve()
    pages_dir = output_dir / "page_images"
    table_dir = output_dir / "table_images"
    raw_dir = output_dir / "api_raw"
    for directory in (output_dir, pages_dir, table_dir, raw_dir):
        directory.mkdir(parents=True, exist_ok=True)

    document = fitz.open(args.pdf)
    selected_pages = parse_page_selection(args.pages, document.page_count)
    text_blocks: list[dict[str, Any]] = []
    table_regions: list[dict[str, Any]] = []
    document_order: list[dict[str, Any]] = []
    page_reports: list[dict[str, Any]] = []

    skip_empty = getattr(args, "skip_empty_pages", False)
    # Local-first layout: derive blocks + tables from the digital text layer instead
    # of a per-page vision call. Off by default -> existing pipelines unchanged.
    # Pages with no extractable text (scanned) fall back to the vision layout.
    local_visual = getattr(args, "local_visual", False)
    max_workers = getattr(args, "max_workers", 1)
    # PyMuPDF is not safe for concurrent access to one Document across threads,
    # so each worker opens its own document when running in parallel; the
    # sequential path reuses the already-open shared document unchanged.
    parallel = bool(max_workers and max_workers > 1)

    def _extract_page(page_number: int) -> dict[str, Any]:
        doc = fitz.open(args.pdf) if parallel else document
        try:
            page = doc[page_number - 1]
            local_text_blocks: list[dict[str, Any]] = []
            local_table_regions: list[dict[str, Any]] = []
            local_order: list[dict[str, Any]] = []
            # Opt-in safe saver: skip the layout API call for pages with no text and no
            # images (they cannot yield rules). Off by default -> existing pipelines unchanged.
            has_text = bool(page.get_text("text").strip())
            if skip_empty and not has_text and not page.get_images():
                return {"text_blocks": [], "table_regions": [], "document_order": [],
                        "page_report": {"page_number": page_number, "status": "skipped_empty"}}
            if local_visual and has_text:
                extraction = _local_layout(page, page_number, args, pages_dir)
            else:
                extraction = load_or_extract_page(
                    page=page,
                    page_number=page_number,
                    args=args,
                    api_key=api_key,
                    pages_dir=pages_dir,
                    raw_dir=raw_dir,
                )
            for index, source_block in enumerate(extraction.get("text_blocks", []), start=1):
                block = dict(source_block)
                block["bbox"] = normalized_bbox(block.get("bbox"))
                block["block_id"] = f"page_{page_number:04d}__text_{index:03d}"
                block["page_number"] = page_number
                block["source_page_image"] = str((pages_dir / f"page_{page_number:04d}.png").relative_to(output_dir))
                local_text_blocks.append(block)
                local_order.append({
                    "reading_order": int(block.get("reading_order", index)),
                    "page_number": page_number,
                    "item_type": "text_block",
                    "item_id": block["block_id"],
                })

            for index, source_region in enumerate(extraction.get("table_regions", []), start=1):
                region = dict(source_region)
                region_id = f"page_{page_number:04d}__table_{index:03d}"
                region["table_bbox"] = normalized_bbox(region.get("table_bbox"))
                region["section_heading_bbox"] = normalized_bbox(region.get("section_heading_bbox"))
                region["model_crop_bbox"] = normalized_bbox(region.get("crop_bbox"))
                region["crop_bbox"] = union_bbox(
                    region["table_bbox"],
                    region["section_heading_bbox"],
                    region["model_crop_bbox"],
                )
                crop_path = table_dir / f"{region_id}.png"
                crop_rect = bbox_to_page_rect(region["crop_bbox"], page, args.crop_padding_points)
                crop_pixmap = page.get_pixmap(matrix=fitz.Matrix(args.scale, args.scale), clip=crop_rect, alpha=False)
                crop_path.write_bytes(crop_pixmap.tobytes("png"))
                region["region_id"] = region_id
                region["page_number"] = page_number
                region["image_path"] = str(crop_path.relative_to(output_dir))
                region["source_page_image"] = str((pages_dir / f"page_{page_number:04d}.png").relative_to(output_dir))
                local_table_regions.append(region)
                local_order.append({
                    "reading_order": int(region.get("reading_order", index)),
                    "page_number": page_number,
                    "item_type": "table_image",
                    "item_id": region_id,
                    "image_path": region["image_path"],
                })

            return {
                "text_blocks": local_text_blocks,
                "table_regions": local_table_regions,
                "document_order": local_order,
                "page_report": {
                    "page_number": page_number,
                    "summary": extraction.get("page_summary", ""),
                    "text_block_count": len(extraction.get("text_blocks", [])),
                    "table_region_count": len(extraction.get("table_regions", [])),
                    "warnings": extraction.get("page_warnings", []),
                },
            }
        finally:
            if doc is not document:
                doc.close()

    for result in _map_batches(
        selected_pages, _extract_page,
        max_workers=max_workers, desc="Visual blocks: pages", unit="page",
    ):
        text_blocks.extend(result["text_blocks"])
        table_regions.extend(result["table_regions"])
        document_order.extend(result["document_order"])
        page_reports.append(result["page_report"])

    document_order.sort(key=lambda row: (row["page_number"], row["reading_order"], row["item_type"]))
    write_jsonl(output_dir / "text_blocks.jsonl", text_blocks)
    write_jsonl(output_dir / "table_regions.jsonl", table_regions)
    write_jsonl(output_dir / "document_order.jsonl", document_order)
    summary = {
        "source_pdf": str(args.pdf.resolve()),
        "model": args.model,
        "selected_pages": selected_pages,
        "text_block_count": len(text_blocks),
        "table_region_count": len(table_regions),
        "page_reports": page_reports,
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    args = parse_args()
    summary = process_pdf(args)
    print(f"Saved text blocks: {summary['text_block_count']}")
    print(f"Saved table crops: {summary['table_region_count']}")
    print(f"Output directory: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
