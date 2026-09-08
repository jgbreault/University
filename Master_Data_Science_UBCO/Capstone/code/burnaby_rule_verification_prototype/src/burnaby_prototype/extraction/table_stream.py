"""Gemini Flash vision pass over detected table regions.

Reads table regions from the ingest intermediate and asks Gemini
(``gemini-2.5-flash`` by default, overridable via ``GEMINI_MODEL``) for a
structured JSON read of each table. Design rules:

- The API key comes ONLY from the environment (``GOOGLE_API_KEY``) and is
  never written to any file. With no key and no injected client, the stream
  skips gracefully with a clear message.
- The client is a thin wrapper class with an injectable fake for tests
  (mirroring the injectable-backend pattern in embedding_semantics.py), so the
  test suite needs no network and no key.
- RESPONSE CACHING is mandatory: every model response is cached under
  ``data/bylaws/<city>/cache/<sha256-of-request>.json``; re-runs hit the cache
  instead of quota. Uncached calls are rate-limited (~6s apart, free tier 10 RPM).

Legacy diagnostic helper only — native M4 is the current product extraction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from .text_stream import (
    normalize_unit,
    operator_from_wording,
    rule_object_from_keywords,
    VALUE_UNIT_RE,
)


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
UNCACHED_CALL_SLEEP_SECONDS = 6.0

TABLE_PROMPT = (
    "You are reading one table from a municipal zoning bylaw. Return ONLY the "
    "table content as JSON matching the response schema: a list of tables, each "
    "with table_title and rows of {row_header, column_header, cell_value, notes}. "
    "Copy values verbatim (keep units like m, m2, %, storeys). Do not infer or "
    "summarize; one entry per data cell."
)

TABLE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "table_title": {"type": "string"},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "row_header": {"type": "string"},
                        "column_header": {"type": "string"},
                        "cell_value": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["row_header", "column_header", "cell_value"],
                },
            },
        },
        "required": ["table_title", "rows"],
    },
}


class GeminiTableClient:
    """Thin Gemini wrapper with an injectable raw client for tests.

    A fake only needs ``models.generate_content(...)`` returning an object with
    a ``.text`` JSON payload — or tests can bypass this class entirely by
    passing any object with ``available``/``model``/``generate_table_json`` to
    ``run_table_stream``.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self._api_key = api_key if api_key is not None else os.environ.get("GOOGLE_API_KEY", "")
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None or bool(self._api_key)

    def _genai_client(self) -> Any:
        if self._client is None:
            from google import genai  # noqa: PLC0415 - lazy optional dependency

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_table_json(
        self,
        *,
        prompt: str,
        image_png: bytes | None = None,
        table_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """One structured-JSON table read (image part when available, else text)."""
        from google.genai import types  # noqa: PLC0415 - lazy optional dependency

        contents: list[Any] = []
        if image_png is not None:
            contents.append(types.Part.from_bytes(data=image_png, mime_type="image/png"))
        if table_text:
            contents.append(f"Raw text grid of the same table (may be imperfect):\n{table_text}")
        contents.append(prompt)
        response = self._genai_client().models.generate_content(
            model=self.model,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": TABLE_RESPONSE_SCHEMA,
            },
        )
        return json.loads(response.text or "[]")


def run_table_stream(
    intermediate: dict[str, Any],
    city: str,
    *,
    client: Any | None = None,
    cache_dir: str | Path | None = None,
    pdf_path: str | Path | None = None,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Read every detected table region through Gemini (cache-first).

    Returns {"available": bool, "model": str|None, "reason": str|None,
    "tables": [...], "uncached_calls": int, "cached_hits": int}. Each table is
    {"table_title", "rows", "page", "table_index", "from_cache"} with rows
    schema-validated against TABLE_RESPONSE_SCHEMA's row shape.
    """
    if client is None:
        client = GeminiTableClient()
    if not getattr(client, "available", False):
        reason = "GOOGLE_API_KEY not set — skipping Gemini table pass (text stream only)"
        log(reason)
        return {
            "available": False,
            "model": getattr(client, "model", None),
            "reason": reason,
            "tables": [],
            "uncached_calls": 0,
            "cached_hits": 0,
        }

    cache_root = Path(cache_dir) if cache_dir else Path("data") / "bylaws" / _slug(city) / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    model = getattr(client, "model", DEFAULT_GEMINI_MODEL)

    tables: list[dict[str, Any]] = []
    uncached_calls = 0
    cached_hits = 0
    for page in intermediate.get("pages", []):
        page_number = int(page.get("page_number") or 0)
        page_image: bytes | None = None
        page_tables = page.get("tables") or []
        if page_tables and pdf_path:
            page_image = _render_page_png(pdf_path, page_number, log)
        for table_index, region in enumerate(page_tables, start=1):
            table_text = _rows_as_text(region.get("rows") or [])
            request = {
                "model": model,
                "prompt": TABLE_PROMPT,
                "city": _slug(city),
                "page": page_number,
                "table_index": table_index,
                "content_sha256": _content_fingerprint(page_image, table_text),
            }
            cache_path = cache_root / f"{_request_sha256(request)}.json"
            if cache_path.exists():
                raw_tables = json.loads(cache_path.read_text(encoding="utf-8")).get("response", [])
                from_cache = True
                cached_hits += 1
            else:
                if uncached_calls > 0:
                    sleep(UNCACHED_CALL_SLEEP_SECONDS)
                raw_tables = client.generate_table_json(
                    prompt=TABLE_PROMPT, image_png=page_image, table_text=table_text
                )
                uncached_calls += 1
                cache_path.write_text(
                    json.dumps({"request": request, "response": raw_tables}, indent=2),
                    encoding="utf-8",
                )
                from_cache = False
            for parsed in validate_table_payload(raw_tables):
                parsed.update({"page": page_number, "table_index": table_index, "from_cache": from_cache})
                if not parsed["table_title"]:
                    parsed["table_title"] = str(region.get("title_guess") or "")
                tables.append(parsed)

    log(
        f"table stream: {len(tables)} tables ({cached_hits} cache hits, "
        f"{uncached_calls} model calls, model={model})"
    )
    return {
        "available": True,
        "model": model,
        "reason": None,
        "tables": tables,
        "uncached_calls": uncached_calls,
        "cached_hits": cached_hits,
    }


def validate_table_payload(payload: Any) -> list[dict[str, Any]]:
    """Schema-validate a model/cache payload; malformed tables/rows are dropped."""
    validated: list[dict[str, Any]] = []
    if not isinstance(payload, list):
        return validated
    for table in payload:
        if not isinstance(table, dict) or not isinstance(table.get("rows"), list):
            continue
        rows: list[dict[str, str]] = []
        for row in table["rows"]:
            if not isinstance(row, dict):
                continue
            if not all(isinstance(row.get(key), str) for key in ("row_header", "column_header", "cell_value")):
                continue
            rows.append(
                {
                    "row_header": row["row_header"].strip(),
                    "column_header": row["column_header"].strip(),
                    "cell_value": row["cell_value"].strip(),
                    "notes": str(row.get("notes") or "").strip(),
                }
            )
        if rows:
            validated.append({"table_title": str(table.get("table_title") or "").strip(), "rows": rows})
    return validated


def derive_table_candidates(tables: list[dict[str, Any]], city: str) -> list[dict[str, Any]]:
    """Propose rule candidates from structured table rows (deterministic).

    Mirrors the upstream pipe style: evidence_text =
    'Title | Row Header | Column Header: Cell Value'. Headers drive the
    operator (Minimum/Maximum) and the rule-object guess; the verifier remains
    the gate.
    """
    candidates: list[dict[str, Any]] = []
    for table in tables:
        title = str(table.get("table_title") or "")
        page = int(table.get("page") or 0)
        for row in table.get("rows", []):
            row_header = row["row_header"]
            column_header = row["column_header"]
            cell_value = row["cell_value"]
            header_text = f"{title} {row_header} {column_header}"
            evidence_text = f"{title} | {row_header} | {column_header}: {cell_value}".strip(" |")
            value_match = VALUE_UNIT_RE.search(cell_value)
            operator = operator_from_wording(header_text)
            if value_match and operator:
                value = value_match.group("value")
                unit = normalize_unit(value_match.group("unit"))
                rule_object = rule_object_from_keywords(header_text, unit) or row_header
                constraint_type = "maximum" if operator == "<=" else "minimum"
                rule_key = f"{'max' if operator == '<=' else 'min'}_{_slug(str(rule_object))}"
            elif cell_value.strip().lower() in {"permitted", "allowed", "-"}:
                value, unit, operator = cell_value.strip(), "", "=="
                rule_object, constraint_type, rule_key = row_header, "allowed", _slug(row_header)
            else:
                continue
            candidates.append(
                {
                    "section": "",
                    "page": page,
                    "table_index": int(table.get("table_index") or 0),
                    "rule_key": rule_key,
                    "rule_object": rule_object,
                    "constraint_type": constraint_type,
                    "subject": row_header,
                    "operator": operator,
                    "value": value,
                    "unit": unit,
                    "condition": row.get("notes") or "",
                    "exception": "",
                    "evidence_text": evidence_text,
                    "table_title": title,
                    "row_header": row_header,
                    "column_header": column_header,
                    "cell_value": cell_value,
                    "source_stream": "local_table_image",
                }
            )
    return candidates


def _render_page_png(pdf_path: str | Path, page_number: int, log: Callable[[str], None]) -> bytes | None:
    """Render one page as PNG bytes via pdfplumber when possible."""
    try:
        import io  # noqa: PLC0415

        import pdfplumber  # noqa: PLC0415 - lazy optional dependency

        with pdfplumber.open(str(pdf_path)) as pdf:
            page = pdf.pages[page_number - 1]
            buffer = io.BytesIO()
            page.to_image(resolution=150).original.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception as exc:
        log(f"page {page_number}: image render unavailable ({type(exc).__name__}) — sending text grid")
        return None


def _rows_as_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(str(cell or "") for cell in row) for row in rows)


def _content_fingerprint(image_png: bytes | None, table_text: str) -> str:
    digest = hashlib.sha256()
    digest.update(image_png or b"")
    digest.update(table_text.encode("utf-8"))
    return digest.hexdigest()


def _request_sha256(request: dict[str, Any]) -> str:
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
