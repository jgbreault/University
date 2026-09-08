#!/usr/bin/env python3
"""Ask Gemini to refine and assess locally recalled zoning-bylaw windows."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from tqdm.auto import tqdm

from local_candidate_block_selector import CITY_CONFIGS, write_json, write_jsonl


DEFAULT_MODEL = "gemini-3.1-pro-preview"

WINDOW_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "string", "enum": ["relevant", "context_only", "irrelevant"]},
        "relevance_score": {"type": "integer"},
        "reason": {"type": "string"},
        "table_likelihood": {"type": "string", "enum": ["none", "possible", "likely"]},
        "should_process_page_visually": {"type": "boolean"},
        "refined_blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "block_type": {
                        "type": "string",
                        "enum": ["heading", "clause", "list_item", "table_reference", "context"],
                    },
                    "section_path": {"type": "array", "items": {"type": "string"}},
                    "source_line_start": {"type": "integer"},
                    "source_line_end": {"type": "integer"},
                    "text": {"type": "string"},
                    "relevance": {"type": "string", "enum": ["relevant", "context_only", "irrelevant"]},
                },
                "required": [
                    "block_type",
                    "section_path",
                    "source_line_start",
                    "source_line_end",
                    "text",
                    "relevance",
                ],
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "relevance",
        "relevance_score",
        "reason",
        "table_likelihood",
        "should_process_page_visually",
        "refined_blocks",
        "warnings",
    ],
}

WINDOW_PROMPT = """Assess and split a small text window recalled from a zoning bylaw.

This is a municipality-agnostic routing task, not rule extraction.
Use only the supplied numbered lines and target description.

Instructions:
1. Decide whether the window is relevant, context_only, or irrelevant for the stated target.
2. Split useful text into the smallest faithful headings, clauses, list items, table references,
   and inherited-context blocks. Preserve visible hierarchy in section_path.
3. Cite source line boundaries exactly. Do not invent missing source text.
4. Set should_process_page_visually when the page may contain a relevant table, when text extraction
   appears structurally incomplete, or when visible layout is likely needed for faithful routing.
5. table_likelihood describes whether a relevant regulatory table may be present on the source page.
6. Keep parent provisions only when they may apply to the target. Reject mere keyword collisions.
7. Do not extract or normalize rules in this stage.

Input JSON:
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city", choices=sorted(CITY_CONFIGS))
    parser.add_argument("local_selection_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def call_gemini(
    payload_json: dict[str, Any],
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
            "parts": [{"text": WINDOW_PROMPT + json.dumps(payload_json, ensure_ascii=False)}],
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 12000,
            "responseMimeType": "application/json",
            "responseJsonSchema": WINDOW_SCHEMA,
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
            return json.loads("".join(part.get("text", "") for part in parts)), raw_response
        except requests.HTTPError as exc:
            last_error = exc
            if getattr(exc.response, "status_code", None) not in {429, 500, 502, 503, 504}:
                raise
        except (requests.Timeout, requests.ConnectionError, json.JSONDecodeError) as exc:
            last_error = exc
    if last_error is None:
        raise RuntimeError("Gemini window refinement failed without an error.")
    raise last_error


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


def process_window_refinement(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"{args.api_key_env} is not set.")
    local_dir = args.local_selection_dir.resolve()
    output_dir = args.output_dir.resolve()
    raw_dir = output_dir / "api_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_summary = read_json(local_dir / "summary.json")
    windows = read_jsonl(local_dir / "candidate_windows.jsonl")

    def _refine_window(window: dict[str, Any]) -> dict[str, Any]:
        parsed_path = raw_dir / f"{window['window_id']}_refinement.json"
        response_path = raw_dir / f"{window['window_id']}_api_response.json"
        if parsed_path.exists() and not args.overwrite:
            refinement = read_json(parsed_path)
        else:
            refinement, raw_response = call_gemini(
                {
                    "target": CITY_CONFIGS[args.city]["target_description"],
                    "window_id": window["window_id"],
                    "page_number": window["page_number"],
                    "candidate_line_range": [window["candidate_line_start"], window["candidate_line_end"]],
                    "numbered_lines": window["numbered_lines"],
                },
                model=args.model,
                api_key=api_key,
                timeout=args.timeout,
                max_retries=args.max_retries,
                retry_base_seconds=args.retry_base_seconds,
            )
            write_json(parsed_path, refinement)
            write_json(response_path, raw_response)
        return {**window, "api_refinement": refinement}

    refined_windows: list[dict[str, Any]] = _map_batches(
        windows, _refine_window,
        max_workers=getattr(args, "max_workers", 1),
        desc="Window refinement", unit="window",
    )
    accepted = [
        window for window in refined_windows
        if window["api_refinement"].get("relevance") in {"relevant", "context_only"}
    ]
    accepted_pages = sorted({window["page_number"] for window in accepted})
    requested_visual_pages = {
        window["page_number"]
        for window in accepted
        if window["api_refinement"].get("should_process_page_visually")
    }
    # Preserve adjacent-page recall for cross-page tables and incomplete clauses.
    local_visual_pages = set(local_summary["recommended_visual_pages"])
    visual_pages = sorted(requested_visual_pages | {
        page
        for accepted_page in accepted_pages
        for page in (accepted_page - 1, accepted_page, accepted_page + 1)
        if page in local_visual_pages
    })
    summary = {
        "city": args.city,
        "model": args.model,
        "candidate_window_count": len(windows),
        "accepted_window_count": len(accepted),
        "relevant_window_count": sum(
            window["api_refinement"].get("relevance") == "relevant" for window in refined_windows
        ),
        "context_only_window_count": sum(
            window["api_refinement"].get("relevance") == "context_only" for window in refined_windows
        ),
        "irrelevant_window_count": sum(
            window["api_refinement"].get("relevance") == "irrelevant" for window in refined_windows
        ),
        "accepted_pages": accepted_pages,
        "recommended_visual_pages": visual_pages,
    }
    write_jsonl(output_dir / "refined_windows.jsonl", refined_windows)
    write_jsonl(output_dir / "accepted_windows.jsonl", accepted)
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    args = parse_args()
    summary = process_window_refinement(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
