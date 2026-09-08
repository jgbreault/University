#!/usr/bin/env python3
"""Run V2 full-bylaw discovery, model extraction bakeoff, verification, and examiner.

This script is intentionally an orchestration layer. The deterministic verifier
remains unchanged and JSON artifacts remain the source of truth; SQLite only
caches expensive intermediate work.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config, resolve_city_paths, write_json
from burnaby_prototype.native_extraction import load_openrouter_api_key
from burnaby_prototype.slim_pipeline import run_slim_verification
from burnaby_prototype.v2_bakeoff import (
    DEFAULT_BAKEOFF_MODELS,
    model_slug,
    prompt_template_hash,
    run_model_extraction,
)
from burnaby_prototype.v2_discovery import (
    DISCOVERY_VERSION,
    build_evidence_packs,
    build_source_chunks_from_pdf,
    discovery_audit,
    discovery_options_hash,
    source_summary,
)
from burnaby_prototype.v2_examiner import (
    DEFAULT_EXAMINER_MODEL,
    load_openrouter_key,
    run_shadow_examiner,
)
from burnaby_prototype.v2_store import (
    V2Store,
    default_db_path,
    hash_file,
    hash_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="burnaby_r1", help="City key, e.g. burnaby_r1/calgary_rcg/vancouver_rs.")
    parser.add_argument("--config", default=None, help="Override configs/<city>.json.")
    parser.add_argument("--pdf", default=None, help="Override data/bylaws/<city>/source.pdf.")
    parser.add_argument("--out-root", default=str(ROOT / "outputs" / "v2_runs"))
    parser.add_argument("--db", default=None, help="SQLite path; default outputs/v2_runs/verification_runs.sqlite.")
    parser.add_argument("--models", default=",".join(DEFAULT_BAKEOFF_MODELS), help="Comma-separated model ids.")
    parser.add_argument("--max-packs", type=int, default=80)
    parser.add_argument("--max-pack-chars", type=int, default=3600)
    parser.add_argument("--llm-max-tokens", type=int, default=1200)
    parser.add_argument("--dry-run", action="store_true", help="Build/cache source and evidence packs only; no LLM calls.")
    parser.add_argument("--no-verify", action="store_true", help="Skip deterministic verification/benchmark after extraction.")
    parser.add_argument("--no-examiner", action="store_true", help="Skip advisory shadow examiner.")
    parser.add_argument("--examiner-model", default=DEFAULT_EXAMINER_MODEL)
    parser.add_argument("--examiner-offline", action="store_true", help="Force heuristic examiner mode.")
    parser.add_argument("--refresh-source", action="store_true", help="Ignore cached source chunks and rebuild from PDF.")
    parser.add_argument("--refresh-packs", action="store_true", help="Ignore cached evidence packs and rebuild from chunks.")
    parser.add_argument("--no-model-cache", action="store_true", help="Do not reuse cached LLM outputs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    city_paths = resolve_city_paths(ROOT, args.city)
    config_path = Path(args.config) if args.config else city_paths.config
    pdf_path = Path(args.pdf) if args.pdf else ROOT / "data" / "bylaws" / args.city.lower() / "source.pdf"
    out_root = Path(args.out_root)
    city_out_root = out_root / args.city.lower()
    db_path = Path(args.db) if args.db else default_db_path(ROOT)

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return 1
    config = load_config(config_path)
    pdf_hash = hash_file(pdf_path)
    # Chunk construction logic lives behind DISCOVERY_VERSION; folding it into
    # the config hash invalidates cached source chunks when chunking changes.
    config_hash = hash_json(
        {"config": _clean_config_for_hash(config), "discovery_version": DISCOVERY_VERSION}
    )
    discovery_hash = discovery_options_hash(max_packs=args.max_packs, max_pack_chars=args.max_pack_chars)
    store = V2Store(db_path)

    try:
        source_chunks = [] if args.refresh_source else store.get_source_chunks(
            city=args.city, pdf_hash=pdf_hash, config_hash=config_hash
        )
        if not source_chunks:
            print(f"[v2] building full-bylaw source cache from {pdf_path.name}")
            source_chunks = build_source_chunks_from_pdf(pdf_path=pdf_path, city=args.city, config=config)
            store.upsert_source_chunks(city=args.city, pdf_hash=pdf_hash, config_hash=config_hash, chunks=source_chunks)
        else:
            print(f"[v2] reused {len(source_chunks)} source chunks from SQLite")

        packs = [] if args.refresh_packs else store.get_evidence_packs(
            city=args.city,
            pdf_hash=pdf_hash,
            config_hash=config_hash,
            discovery_hash=discovery_hash,
        )
        if not packs:
            packs = build_evidence_packs(
                source_chunks,
                config=config,
                max_packs=args.max_packs,
                max_pack_chars=args.max_pack_chars,
            )
            store.upsert_evidence_packs(
                city=args.city,
                pdf_hash=pdf_hash,
                config_hash=config_hash,
                discovery_hash=discovery_hash,
                packs=packs,
            )
            print(f"[v2] built {len(packs)} evidence packs")
        else:
            print(f"[v2] reused {len(packs)} evidence packs from SQLite")

        source_report = {
            **source_summary(source_chunks, packs),
            "city": args.city,
            "source_pdf": str(pdf_path),
            "pdf_hash": pdf_hash,
            "config_hash": config_hash,
            "discovery_hash": discovery_hash,
            "cache_db": str(db_path),
        }
        city_out_root.mkdir(parents=True, exist_ok=True)
        write_json(city_out_root / "source_chunks.json", source_chunks)
        write_json(city_out_root / "evidence_packs.json", packs)
        write_json(city_out_root / "source_summary.json", source_report)
        write_json(city_out_root / "discovery_audit.json", discovery_audit(source_chunks, packs))

        models = [model.strip() for model in str(args.models or "").split(",") if model.strip()]
        if args.dry_run:
            models = ["dry_run"]
        api_key = "" if args.dry_run else load_openrouter_api_key(ROOT / ".env")
        if not args.dry_run and not api_key:
            print("OPENROUTER_API_KEY is required for non-dry V2 extraction.")
            return 2

        run_rows = []
        for model in models:
            run_model = "google/gemini-2.5-flash-lite" if model == "dry_run" else model
            model_dir = city_out_root / model_slug(model)
            print(f"[v2] model={model} output={model_dir}")
            result = run_model_extraction(
                city=args.city,
                config=config,
                packs=packs,
                model_id=run_model,
                api_key=api_key,
                output_dir=model_dir,
                store=store,
                pdf_hash=pdf_hash,
                config_hash=config_hash,
                dry_run=args.dry_run,
                use_cache=not args.no_model_cache,
                llm_max_tokens=args.llm_max_tokens,
                pdf_path=pdf_path,
            )
            write_json(model_dir / "source_summary.json", source_report)
            summary = result["summary"]
            cost_report = result["cost_report"]
            verification_summary: dict[str, Any] = {}
            benchmark_metrics: dict[str, Any] = {}
            # Deterministic matrix candidates carry no LLM dependency, so they
            # can (and should) be verified even in dry_run — that is the
            # offline MVP path: real verified table rules with no API key.
            if not args.no_verify and (not args.dry_run or summary.get("matrix_candidate_count")):
                verification_summary = run_slim_verification(
                    config_path=config,
                    output_dir=model_dir,
                    evidence_units=json.loads((model_dir / "evidence_units.json").read_text(encoding="utf-8")),
                    rule_candidates=json.loads((model_dir / "rule_candidates.json").read_text(encoding="utf-8")),
                    input_mode="native_v2_rag_llm",
                    use_cache=True,
                )
                _run_benchmark(args.city, model_dir)
                benchmark = _read_json(model_dir / "benchmark_report.json", {})
                benchmark_metrics = benchmark.get("rule_metrics", {})
            if not args.no_examiner:
                examiner_key = "" if args.examiner_offline else load_openrouter_key(ROOT)
                examiner_report = run_shadow_examiner(
                    output_dir=model_dir,
                    repo_root=ROOT,
                    store=store,
                    run_id=summary.get("run_id") or "",
                    model=args.examiner_model,
                    api_key=examiner_key,
                    offline=args.examiner_offline or args.dry_run or not examiner_key,
                )
                print(f"[v2] examiner findings={examiner_report.get('summary', {}).get('finding_count', 0)}")
            row = {
                "model": None if args.dry_run else model,
                "output_dir": str(model_dir),
                "candidate_rule_count": summary.get("candidate_rule_count"),
                "evidence_unit_count": summary.get("evidence_unit_count"),
                "estimated_cost_usd": cost_report.get("estimated_cost_usd"),
                "latency_ms": cost_report.get("latency_ms"),
                "verified_rule_count": verification_summary.get("verified_rule_count"),
                "review_rule_count": verification_summary.get("review_rule_count"),
                "rejected_rule_count": verification_summary.get("rejected_rule_count"),
                "false_verified_count": benchmark_metrics.get("false_verified_count"),
                "verified_precision": benchmark_metrics.get("verified_precision"),
                "verified_or_review_recall": benchmark_metrics.get("verified_or_review_recall"),
            }
            run_rows.append(row)

        bakeoff_report = {
            "pipeline": "v2_full_bylaw_bakeoff",
            "city": args.city,
            "pdf_hash": pdf_hash,
            "config_hash": config_hash,
            "prompt_template_hash": prompt_template_hash(),
            "source": source_report,
            "runs": run_rows,
            "safety_contract": "LLM/RAG propose or explain; deterministic verifier decides.",
        }
        write_json(city_out_root / "bakeoff_summary.json", bakeoff_report)
        print(f"[v2] wrote {city_out_root / 'bakeoff_summary.json'}")
        return 0
    finally:
        store.close()


def _run_benchmark(city: str, output_dir: Path) -> None:
    result = subprocess.run(
        [sys.executable, "benchmark/evaluate_benchmark.py", "--city", city, "--output-dir", str(output_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"benchmark failed for {city}: {output_dir}")


def _clean_config_for_hash(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if not key.startswith("_")}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
