"""V2 model bakeoff helpers.

The bakeoff keeps every model on the same evidence packs, writes the normal
candidate/evidence JSON contract, and records cost/latency in the SQLite cache.
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from .config import write_json
from .native_extraction import (
    OpenRouterChatClient,
    OpenRouterError,
    candidate_set_from_model_rules,
    extraction_prompt,
)
from .v3_clause_candidates import build_clause_candidate_set
from .v2_matrix_candidates import build_matrix_candidate_set
from .v2_store import V2Store, hash_text, model_params_hash


PROMPT_TEMPLATE_VERSION = "native_extraction_prompt_v2_2"
SOURCE_REPAIR_VERSION = "source_repair_current"
VERIFIER_VERSION = "slim_verification_current"

DEFAULT_BAKEOFF_MODELS = [
    "openai/gpt-oss-120b",
    "mistralai/mistral-small-3.2-24b-instruct",
    "google/gemini-2.5-flash-lite",
    "google/gemini-2.5-flash",
    "openai/gpt-5-mini",
    "qwen/qwen3.5-plus-20260420",
]

FALLBACK_MODELS = ["anthropic/claude-sonnet-4.6"]

# USD per 1M tokens, current planning snapshot. These are estimates, not billing
# authority; the real OpenRouter invoice wins.
MODEL_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.039, 0.18),
    "mistralai/mistral-small-3.2-24b-instruct": (0.075, 0.20),
    "google/gemini-2.5-flash-lite": (0.10, 0.40),
    "google/gemini-3.1-flash-lite": (0.25, 1.50),
    "google/gemini-2.5-flash": (0.30, 2.50),
    "openai/gpt-5-mini": (0.25, 2.00),
    "qwen/qwen3.5-plus-20260420": (0.30, 1.80),
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.0, 0.0),
}


def prompt_template_hash() -> str:
    return hash_text(PROMPT_TEMPLATE_VERSION)


def model_slug(model_id: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", model_id).strip("_").lower()
    return text[:80] or "model"


def estimate_tokens(chars: int) -> int:
    return max(1, math.ceil(chars / 4))


def estimate_cost(model_id: str, *, input_chars: int, output_chars: int) -> float:
    input_price, output_price = MODEL_PRICING_PER_MILLION.get(model_id, (0.0, 0.0))
    return round(
        estimate_tokens(input_chars) / 1_000_000 * input_price
        + estimate_tokens(output_chars) / 1_000_000 * output_price,
        8,
    )


def run_model_extraction(
    *,
    city: str,
    config: dict[str, Any],
    packs: list[dict[str, Any]],
    model_id: str,
    api_key: str,
    output_dir: Path,
    store: V2Store,
    pdf_hash: str,
    config_hash: str,
    dry_run: bool = False,
    use_cache: bool = True,
    llm_max_tokens: int = 1200,
    pdf_path: Path | None = None,
    deterministic_clause_candidates: bool = False,
) -> dict[str, Any]:
    """Run one model over fixed packs and write native verifier inputs.

    When ``pdf_path`` is given, deterministic matrix-table candidates (from the
    source bands, no LLM) are merged in — the recall fix for table-heavy
    bylaws whose flattened table packs the model returns empty. They are
    PROPOSALS like every other candidate; the verifier still proves each.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    params = {"temperature": 0, "max_tokens": llm_max_tokens, "response_format": "json_object"}
    params_hash = model_params_hash(params)
    template_hash = prompt_template_hash()
    run_id = f"{_slug(city)}_{model_slug(model_id)}_{hash_text(pdf_hash + config_hash + template_hash + params_hash)[:12]}"
    store.record_run(
        run_id=run_id,
        city=city,
        output_dir=output_dir,
        pdf_hash=pdf_hash,
        config_hash=config_hash,
        prompt_hash=template_hash,
        model_id=model_id if not dry_run else "dry_run",
        model_params_hash=params_hash,
        source_repair_version=SOURCE_REPAIR_VERSION,
        verifier_version=VERIFIER_VERSION,
        metadata={"dry_run": dry_run, "pack_count": len(packs)},
    )

    client = None if dry_run else OpenRouterChatClient(api_key, model=model_id, max_tokens=llm_max_tokens)
    raw_outputs: list[dict[str, Any]] = []
    evidence_units: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    cache_hits = 0
    extraction_errors: list[dict[str, Any]] = []
    total_input_chars = 0
    total_output_chars = 0
    total_latency_ms = 0
    total_cost = 0.0

    # Deterministic matrix-table candidates (recall fix), built first so we can
    # route table content away from the LLM when geometry covers it.
    matrix_units: list[dict[str, Any]] = []
    matrix_candidates: list[dict[str, Any]] = []
    if pdf_path is not None and Path(pdf_path).exists():
        matrix_units, matrix_candidates = build_matrix_candidate_set(pdf_path, city, config)
        _stamp_v2_records(matrix_units, matrix_candidates, model_id=model_id, run_id=run_id)
        for candidate in matrix_candidates:
            candidate["source_stream"] = "native_v2_matrix"
            candidate["extraction_method"] = "deterministic_matrix_v2"

    clause_units: list[dict[str, Any]] = []
    clause_candidates: list[dict[str, Any]] = []
    if deterministic_clause_candidates:
        clause_units, clause_candidates = build_clause_candidate_set(city, packs, config)
        _stamp_v2_records(clause_units, clause_candidates, model_id=model_id, run_id=run_id)

    # Table-first routing: when the matrix lane owns the tables, the LLM does
    # NOT process flattened table packs — sending it the column-mangled table
    # blob is exactly what produced generic-scope mislabels ("principal
    # building <= 2 storeys" from the rear-principal row). The LLM keeps the
    # prose lanes (core_rule / use_permission / universal / context). With no
    # matrix coverage (prose cities) it still sees every pack.
    llm_packs = packs
    if matrix_candidates:
        llm_packs = [pack for pack in packs if not _looks_like_table_pack(pack)]

    for pack in llm_packs:
        prompt = extraction_prompt(config, pack)
        actual_prompt_hash = hash_text(f"{PROMPT_TEMPLATE_VERSION}\n{prompt}")
        input_chars = len(prompt)
        payload: dict[str, Any]
        latency_ms = 0
        cached = (
            store.get_model_output(
                city=city,
                model_id=model_id,
                params_hash=params_hash,
                prompt_hash=actual_prompt_hash,
                pack_id=str(pack.get("pack_id") or ""),
            )
            if use_cache and not dry_run
            else None
        )
        if cached:
            cache_hits += 1
            payload = cached.get("model_output") or {"rules": []}
            latency_ms = int(cached.get("latency_ms") or 0)
            output_chars = int(cached.get("output_chars") or len(json.dumps(payload)))
            cost = float(cached.get("cost_estimate") or 0.0)
            source = "sqlite_cache"
            if not cached.get("parsed_ok", True):
                extraction_errors.append(
                    {
                        "pack_id": pack.get("pack_id"),
                        "chunk_id": pack.get("chunk_id"),
                        "section": pack.get("section"),
                        "page": pack.get("page"),
                        "error": (cached.get("metadata") or {}).get("error") or "cached model output was not valid JSON",
                        "source": "sqlite_cache",
                    }
                )
        elif dry_run:
            payload = {"rules": []}
            output_chars = 0
            cost = 0.0
            source = "dry_run"
        else:
            assert client is not None
            started = time.perf_counter()
            try:
                payload = client.extract_rules(prompt)
                parsed_ok = True
                error = ""
            except OpenRouterError as exc:
                payload = {"rules": []}
                parsed_ok = False
                error = str(exc)
                extraction_errors.append(
                    {
                        "pack_id": pack.get("pack_id"),
                        "chunk_id": pack.get("chunk_id"),
                        "section": pack.get("section"),
                        "page": pack.get("page"),
                        "error": error,
                    }
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            output_chars = len(json.dumps(payload, ensure_ascii=False))
            cost = estimate_cost(model_id, input_chars=input_chars, output_chars=output_chars)
            source = "openrouter"
            store.upsert_model_output(
                run_id=run_id,
                city=city,
                model_id=model_id,
                params_hash=params_hash,
                prompt_hash=actual_prompt_hash,
                pack_id=str(pack.get("pack_id") or ""),
                raw=payload,
                parsed_ok=parsed_ok,
                latency_ms=latency_ms,
                input_chars=input_chars,
                output_chars=output_chars,
                cost_estimate=cost,
                metadata={"error": error, "source": source},
            )

        raw_outputs.append(
            {
                "pack_id": pack.get("pack_id"),
                "model": None if dry_run else model_id,
                "source": source,
                "latency_ms": latency_ms,
                "estimated_cost_usd": cost,
                "model_output": payload,
            }
        )
        new_units, new_candidates = candidate_set_from_model_rules(city, pack, payload, config=config)
        _stamp_v2_records(new_units, new_candidates, model_id=model_id, run_id=run_id)
        evidence_units.extend(new_units)
        candidates.extend(new_candidates)
        total_input_chars += input_chars
        total_output_chars += output_chars
        total_latency_ms += latency_ms
        total_cost += cost

    # Merge the deterministic matrix candidates (built above, before the LLM
    # loop) BEFORE dedup so they stand on their own.
    evidence_units.extend(matrix_units)
    candidates.extend(matrix_candidates)
    matrix_candidate_count = len(matrix_candidates)
    evidence_units.extend(clause_units)
    candidates.extend(clause_candidates)
    clause_candidate_count = len(clause_candidates)

    evidence_units = _dedupe_by_key(evidence_units, "evidence_id")
    candidates = _dedupe_by_key(candidates, "candidate_id")
    cost_report = {
        "run_id": run_id,
        "city": city,
        "model": None if dry_run else model_id,
        "dry_run": dry_run,
        "pack_count": len(packs),
        "cache_hit_count": cache_hits,
        "input_chars": total_input_chars,
        "output_chars": total_output_chars,
        "estimated_input_tokens": estimate_tokens(total_input_chars) if total_input_chars else 0,
        "estimated_output_tokens": estimate_tokens(total_output_chars) if total_output_chars else 0,
        "estimated_cost_usd": round(total_cost, 6),
        "latency_ms": total_latency_ms,
        "extraction_error_count": len(extraction_errors),
        "extraction_errors": extraction_errors,
        "pricing_note": "Estimated from character count and planning price table; OpenRouter billing is authoritative.",
    }
    summary = {
        "pipeline": "native_rag_llm_extraction_v2",
        "city": city,
        "model": None if dry_run else model_id,
        "dry_run": dry_run,
        "run_id": run_id,
        "retrieval_pack_count": len(packs),
        "evidence_unit_count": len(evidence_units),
        "candidate_rule_count": len(candidates),
        "matrix_candidate_count": matrix_candidate_count,
        "clause_candidate_count": clause_candidate_count,
        "cache_hit_count": cache_hits,
        "extraction_error_count": len(extraction_errors),
        "safety_contract": "V2 extraction proposes candidates only. Source repair and deterministic verification decide.",
    }
    write_json(output_dir / "evidence_packs.json", packs)
    write_json(output_dir / "raw_model_outputs.json", raw_outputs)
    write_json(output_dir / "evidence_units.json", evidence_units)
    write_json(output_dir / "rule_candidates.json", candidates)
    write_json(output_dir / "extraction_summary.json", summary)
    write_json(output_dir / "model_cost_report.json", cost_report)

    for artifact_name in (
        "evidence_packs.json",
        "raw_model_outputs.json",
        "evidence_units.json",
        "rule_candidates.json",
        "extraction_summary.json",
        "model_cost_report.json",
    ):
        store.record_artifact(run_id=run_id, artifact_name=artifact_name, path=output_dir / artifact_name)
    store.record_metrics(
        run_id=run_id,
        metrics={
            "candidate_rule_count": len(candidates),
            "evidence_unit_count": len(evidence_units),
            "estimated_cost_usd": round(total_cost, 6),
            "latency_ms": total_latency_ms,
            "cache_hit_count": cache_hits,
            "extraction_error_count": len(extraction_errors),
        },
    )
    return {"summary": summary, "cost_report": cost_report}


def _stamp_v2_records(evidence_units: list[dict[str, Any]], candidates: list[dict[str, Any]], *, model_id: str, run_id: str) -> None:
    for unit in evidence_units:
        unit.setdefault("source_stream", "native_v2_rag_llm")
        unit.setdefault("native_provenance", {})["v2_run_id"] = run_id
        unit.setdefault("native_provenance", {})["model"] = model_id
    for candidate in candidates:
        candidate.setdefault("source_stream", "native_v2_rag_llm")
        candidate.setdefault("extraction_method", "native_rag_llm_v2")
        candidate.setdefault("native_provenance", {})["v2_run_id"] = run_id
        candidate.setdefault("native_provenance", {})["model"] = model_id


def _looks_like_table_pack(pack: dict[str, Any]) -> bool:
    if str(pack.get("lane") or "") == "table_rule":
        return True
    chunk_id = str(pack.get("chunk_id") or "").lower()
    if "_table_" in chunk_id or chunk_id.startswith("table_"):
        return True
    provenance = pack.get("provenance") or {}
    return bool(isinstance(provenance, dict) and provenance.get("is_table"))


def _dedupe_by_key(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for record in records:
        value = str(record.get(key) or "")
        if value and value not in seen:
            seen.add(value)
            out.append(record)
    return out


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
