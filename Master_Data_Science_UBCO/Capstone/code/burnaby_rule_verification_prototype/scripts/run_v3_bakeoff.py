#!/usr/bin/env python3
"""Run V3 native full-bylaw extraction, gap repair, verification, and report.

V3 is an extraction/RAG upgrade only. The deterministic verifier remains the
authority, and benchmark gold is read only by the post-verification evaluator.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config, resolve_city_paths, write_json
from burnaby_prototype.extraction.pdf_ingest import page_ranges_from_provenance
from burnaby_prototype.native_extraction import load_openrouter_api_key
from burnaby_prototype.slim_pipeline import run_slim_verification
from burnaby_prototype.source.corpus import build_m4_source_corpus, write_m4_source_corpus
from burnaby_prototype.v2_bakeoff import model_slug, prompt_template_hash, run_model_extraction
from burnaby_prototype.v2_discovery import DISCOVERY_VERSION as V2_SOURCE_VERSION
from burnaby_prototype.v2_discovery import build_source_chunks_from_pdf
from burnaby_prototype.v2_store import V2Store, default_db_path, hash_file, hash_json
from burnaby_prototype.v3_discovery import (
    M4_DISCOVERY_VERSION,
    V3_DISCOVERY_VERSION,
    build_m4_evidence_packs,
    build_v3_evidence_packs,
    build_v3_repair_packs,
    default_m4_max_packs,
    default_v3_max_packs,
    v3_discovery_audit,
    v3_discovery_options_hash,
    v3_source_summary,
)
from burnaby_prototype.v3_report import build_v3_gap_report, write_v3_gap_report


DEFAULT_V3_MODEL = "google/gemini-2.5-flash-lite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="burnaby_r1")
    parser.add_argument("--config", default=None)
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--out-root", default=str(ROOT / "outputs" / "v3_runs"))
    parser.add_argument("--db", default=None, help="SQLite cache path; defaults to the shared V2 cache.")
    parser.add_argument("--models", default=DEFAULT_V3_MODEL)
    parser.add_argument("--discovery-mode", choices=("v3", "m4"), default="v3")
    parser.add_argument("--max-packs", type=int, default=None)
    parser.add_argument("--max-pack-chars", type=int, default=3600)
    parser.add_argument("--repair-packs", type=int, default=80)
    parser.add_argument("--llm-max-tokens", type=int, default=1200)
    parser.add_argument("--dry-run", action="store_true", help="Build packs and matrix candidates only; no LLM calls.")
    parser.add_argument("--no-verify", action="store_true", help="Skip deterministic verification and benchmark.")
    parser.add_argument("--refresh-source", action="store_true")
    parser.add_argument("--refresh-packs", action="store_true")
    parser.add_argument("--no-model-cache", action="store_true")
    parser.add_argument(
        "--no-source-corpus",
        action="store_true",
        help="Do not write benchmark/source_corpus/<city>/ M4 source artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    city_paths = resolve_city_paths(ROOT, args.city)
    config_path = Path(args.config) if args.config else city_paths.config
    pdf_path = Path(args.pdf) if args.pdf else ROOT / "data" / "bylaws" / args.city.lower() / "source.pdf"
    out_root = Path(args.out_root)
    city_out_root = out_root / args.city.lower()
    db_path = Path(args.db) if args.db else default_db_path(ROOT)
    default_max_packs = default_m4_max_packs(args.city) if args.discovery_mode == "m4" else default_v3_max_packs(args.city)
    max_packs = int(args.max_packs or default_max_packs)

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return 1

    config = load_config(config_path)
    pdf_hash = hash_file(pdf_path)
    # District page-scoping: when provenance pins page spans (e.g. Calgary's R-CG
    # district pages of the 1053-page bylaw), ingest only those pages so the
    # product pipeline's source chunks, packs, and rule sweep follow the
    # deliverable district rather than the whole bylaw. null/absent => whole PDF.
    # page_ranges is part of the cache key so a scoped build never reuses a stale
    # whole-bylaw chunk set.
    provenance_path = pdf_path.parent / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
    page_ranges = page_ranges_from_provenance(provenance)
    source_config_hash = hash_json(
        {
            "config": _clean_config_for_hash(config),
            "source_version": V2_SOURCE_VERSION,
            "page_ranges": page_ranges,
        }
    )
    discovery_hash = v3_discovery_options_hash(
        max_packs=max_packs,
        max_pack_chars=args.max_pack_chars,
        mode=args.discovery_mode,
    )
    store = V2Store(db_path)

    try:
        source_chunks = [] if args.refresh_source else store.get_source_chunks(
            city=args.city,
            pdf_hash=pdf_hash,
            config_hash=source_config_hash,
        )
        if not source_chunks:
            scope_note = f" (scoped to pages {page_ranges})" if page_ranges else " (whole PDF)"
            print(f"[v3] building source cache from {pdf_path.name}{scope_note}")
            source_chunks = build_source_chunks_from_pdf(
                pdf_path=pdf_path, city=args.city, config=config, page_ranges=page_ranges
            )
            store.upsert_source_chunks(
                city=args.city,
                pdf_hash=pdf_hash,
                config_hash=source_config_hash,
                chunks=source_chunks,
            )
        else:
            print(f"[v3] reused {len(source_chunks)} source chunks from SQLite")

        packs = [] if args.refresh_packs else store.get_evidence_packs(
            city=args.city,
            pdf_hash=pdf_hash,
            config_hash=source_config_hash,
            discovery_hash=discovery_hash,
        )
        if not packs:
            if args.discovery_mode == "m4":
                packs = build_m4_evidence_packs(
                    source_chunks,
                    config=config,
                    max_packs=max_packs,
                    max_pack_chars=args.max_pack_chars,
                )
            else:
                packs = build_v3_evidence_packs(
                    source_chunks,
                    config=config,
                    max_packs=max_packs,
                    max_pack_chars=args.max_pack_chars,
                )
            store.upsert_evidence_packs(
                city=args.city,
                pdf_hash=pdf_hash,
                config_hash=source_config_hash,
                discovery_hash=discovery_hash,
                packs=packs,
            )
            print(f"[v3] built {len(packs)} evidence packs")
        else:
            print(f"[v3] reused {len(packs)} evidence packs from SQLite")

        source_report = {
            **v3_source_summary(source_chunks, packs),
            "city": args.city,
            "discovery_mode": args.discovery_mode,
            "source_layer": "m4_exhaustive_bylaw_discovery" if args.discovery_mode == "m4" else "v3_full_bylaw_discovery",
            "discovery_version": M4_DISCOVERY_VERSION if args.discovery_mode == "m4" else V3_DISCOVERY_VERSION,
            "source_pdf": str(pdf_path),
            "pdf_hash": pdf_hash,
            "config_hash": source_config_hash,
            "discovery_hash": discovery_hash,
            "cache_db": str(db_path),
        }
        if not args.no_source_corpus:
            provenance = _read_json(pdf_path.parent / "provenance.json", {})
            page_count = len(PdfReader(str(pdf_path)).pages)
            m4_corpus = build_m4_source_corpus(
                city=args.city,
                pdf_path=pdf_path,
                config=config,
                chunks=source_chunks,
                packs=packs,
                provenance=provenance,
                page_count=page_count,
            )
            m4_out = ROOT / "benchmark" / "source_corpus" / args.city.lower()
            write_m4_source_corpus(m4_corpus, m4_out)
            source_report["m4_source_corpus"] = {
                "path": str(m4_out),
                "corpus_version": m4_corpus["manifest"].get("corpus_version"),
                "numeric_clause_count": m4_corpus["coverage_audit"].get("numeric_clause_count"),
                "rule_like_numeric_clause_count": m4_corpus["coverage_audit"].get("rule_like_numeric_clause_count"),
                "selected_rule_like_numeric_coverage": m4_corpus["coverage_audit"].get("selected_rule_like_numeric_coverage"),
            }
        city_out_root.mkdir(parents=True, exist_ok=True)
        write_json(city_out_root / "source_chunks.json", source_chunks)
        write_json(city_out_root / "evidence_packs.json", packs)
        write_json(city_out_root / "source_summary.json", source_report)
        write_json(city_out_root / "discovery_audit.json", v3_discovery_audit(source_chunks, packs))

        models = ["dry_run"] if args.dry_run else [model.strip() for model in str(args.models or "").split(",") if model.strip()]
        api_key = "" if args.dry_run else load_openrouter_api_key(ROOT / ".env")
        if not args.dry_run and not api_key:
            print("OPENROUTER_API_KEY is required for non-dry V3 extraction.")
            return 2

        run_rows = []
        for model in models:
            model_id = DEFAULT_V3_MODEL if model == "dry_run" else model
            model_dir = city_out_root / model_slug(model)
            pass1_dir = model_dir / "pass1"
            repair_dir = model_dir / "repair_pass"
            print(f"[v3] model={model} output={model_dir}")

            pass1 = run_model_extraction(
                city=args.city,
                config=config,
                packs=packs,
                model_id=model_id,
                api_key=api_key,
                output_dir=pass1_dir,
                store=store,
                pdf_hash=pdf_hash,
                config_hash=source_config_hash,
                dry_run=args.dry_run,
                use_cache=not args.no_model_cache,
                llm_max_tokens=args.llm_max_tokens,
                pdf_path=pdf_path,
                deterministic_clause_candidates=True,
            )
            write_json(pass1_dir / "source_summary.json", source_report)
            verification_summary: dict[str, Any] = {}
            benchmark_metrics: dict[str, Any] = {}
            repair_packs: list[dict[str, Any]] = []
            final_verified = False

            if not args.no_verify and (not args.dry_run or pass1["summary"].get("matrix_candidate_count")):
                verification_summary = _verify_and_benchmark(args.city, config, pass1_dir)
                if not args.dry_run:
                    repair_packs = build_v3_repair_packs(
                        source_chunks,
                        run_output=_run_output(pass1_dir),
                        max_packs=args.repair_packs,
                        max_pack_chars=args.max_pack_chars,
                    )
                    if repair_packs:
                        repair = run_model_extraction(
                            city=args.city,
                            config=config,
                            packs=repair_packs,
                            model_id=model_id,
                            api_key=api_key,
                            output_dir=repair_dir,
                            store=store,
                            pdf_hash=pdf_hash,
                            config_hash=source_config_hash,
                            dry_run=False,
                            use_cache=not args.no_model_cache,
                            llm_max_tokens=args.llm_max_tokens,
                            pdf_path=None,
                            deterministic_clause_candidates=False,
                        )
                        write_json(repair_dir / "source_summary.json", source_report)
                        _merge_final_outputs(
                            model_dir=model_dir,
                            pass1_dir=pass1_dir,
                            repair_dir=repair_dir,
                            packs=packs,
                            repair_packs=repair_packs,
                            city=args.city,
                            model=model_id,
                            dry_run=False,
                            discovery_mode=args.discovery_mode,
                            source_report=source_report,
                        )
                        verification_summary = _verify_and_benchmark(args.city, config, model_dir)
                        final_verified = True
                    else:
                        _merge_final_outputs(
                            model_dir=model_dir,
                            pass1_dir=pass1_dir,
                            repair_dir=None,
                            packs=packs,
                            repair_packs=[],
                            city=args.city,
                            model=model_id,
                            dry_run=False,
                            discovery_mode=args.discovery_mode,
                            source_report=source_report,
                        )
                else:
                    _merge_final_outputs(
                        model_dir=model_dir,
                        pass1_dir=pass1_dir,
                        repair_dir=None,
                        packs=packs,
                        repair_packs=[],
                        city=args.city,
                        model=model_id,
                        dry_run=True,
                        discovery_mode=args.discovery_mode,
                        source_report=source_report,
                    )
            else:
                _merge_final_outputs(
                    model_dir=model_dir,
                    pass1_dir=pass1_dir,
                    repair_dir=None,
                    packs=packs,
                    repair_packs=[],
                    city=args.city,
                    model=model_id,
                    dry_run=args.dry_run,
                    discovery_mode=args.discovery_mode,
                    source_report=source_report,
                )

            final_summary_for_verify = _read_json(model_dir / "extraction_summary.json", {})
            if (
                not final_verified
                and not args.no_verify
                and (not args.dry_run or final_summary_for_verify.get("matrix_candidate_count"))
            ):
                verification_summary = _verify_and_benchmark(args.city, config, model_dir)

            benchmark = _read_json(model_dir / "benchmark_report.json", {})
            benchmark_metrics = benchmark.get("rule_metrics", {})
            gap_report = build_v3_gap_report(
                city=args.city,
                output_dir=model_dir,
                source_summary=source_report,
                v2_reference_dir=ROOT / "outputs" / "v2_runs" / args.city.lower() / model_slug(model_id),
                pdf_page_count=len(PdfReader(str(pdf_path)).pages),
            )
            write_v3_gap_report(gap_report, model_dir)
            cost = _read_json(model_dir / "model_cost_report.json", {})
            summary = _read_json(model_dir / "extraction_summary.json", {})
            row = {
                "model": None if args.dry_run else model,
                "output_dir": str(model_dir),
                "candidate_rule_count": summary.get("candidate_rule_count"),
                "evidence_unit_count": summary.get("evidence_unit_count"),
                "repair_pack_count": len(repair_packs),
                "estimated_cost_usd": cost.get("estimated_cost_usd"),
                "latency_ms": cost.get("latency_ms"),
                "verified_rule_count": verification_summary.get("verified_rule_count"),
                "review_rule_count": verification_summary.get("review_rule_count"),
                "rejected_rule_count": verification_summary.get("rejected_rule_count"),
                "false_verified_count": benchmark_metrics.get("false_verified_count"),
                "verified_precision": benchmark_metrics.get("verified_precision"),
                "verified_or_review_recall": benchmark_metrics.get("verified_or_review_recall"),
            }
            run_rows.append(row)

        bakeoff_report = {
            "pipeline": "m4_full_bylaw_bakeoff" if args.discovery_mode == "m4" else "v3_full_bylaw_bakeoff",
            "city": args.city,
            "discovery_mode": args.discovery_mode,
            "pdf_hash": pdf_hash,
            "config_hash": source_config_hash,
            "prompt_template_hash": prompt_template_hash(),
            "discovery_version": M4_DISCOVERY_VERSION if args.discovery_mode == "m4" else V3_DISCOVERY_VERSION,
            "source": source_report,
            "runs": run_rows,
            "safety_contract": "LLM/RAG propose or explain; deterministic verifier decides.",
        }
        write_json(city_out_root / "bakeoff_summary.json", bakeoff_report)
        print(f"[v3] wrote {city_out_root / 'bakeoff_summary.json'}")
        return 0
    finally:
        store.close()


def _verify_and_benchmark(city: str, config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    summary = run_slim_verification(
        config_path=config,
        output_dir=output_dir,
        evidence_units=_read_json(output_dir / "evidence_units.json", []),
        rule_candidates=_read_json(output_dir / "rule_candidates.json", []),
        input_mode="native_v3_rag_llm",
        use_cache=True,
    )
    _run_benchmark(city, output_dir)
    return summary


def _merge_final_outputs(
    *,
    model_dir: Path,
    pass1_dir: Path,
    repair_dir: Path | None,
    packs: list[dict[str, Any]],
    repair_packs: list[dict[str, Any]],
    city: str,
    model: str,
    dry_run: bool,
    discovery_mode: str,
    source_report: dict[str, Any],
) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    pass1_summary = _read_json(pass1_dir / "extraction_summary.json", {})
    repair_summary = _read_json(repair_dir / "extraction_summary.json", {}) if repair_dir else {}
    pass1_cost = _read_json(pass1_dir / "model_cost_report.json", {})
    repair_cost = _read_json(repair_dir / "model_cost_report.json", {}) if repair_dir else {}
    evidence_units = _dedupe_by_key(
        [
            *_read_json(pass1_dir / "evidence_units.json", []),
            *(_read_json(repair_dir / "evidence_units.json", []) if repair_dir else []),
        ],
        "evidence_id",
    )
    rule_candidates = _dedupe_by_key(
        [
            *_read_json(pass1_dir / "rule_candidates.json", []),
            *(_read_json(repair_dir / "rule_candidates.json", []) if repair_dir else []),
        ],
        "candidate_id",
    )
    _stamp_v3_final(evidence_units, rule_candidates)
    raw_outputs = [
        *_read_json(pass1_dir / "raw_model_outputs.json", []),
        *(_read_json(repair_dir / "raw_model_outputs.json", []) if repair_dir else []),
    ]
    cost_report = _sum_costs(city=city, model=model, dry_run=dry_run, pass1=pass1_cost, repair=repair_cost)
    summary = {
        "pipeline": "native_rag_llm_extraction_m4" if discovery_mode == "m4" else "native_rag_llm_extraction_v3",
        "city": city,
        "model": None if dry_run else model,
        "dry_run": dry_run,
        "discovery_mode": discovery_mode,
        "retrieval_pack_count": len(packs) + len(repair_packs),
        "seed_pack_count": len(packs),
        "repair_pack_count": len(repair_packs),
        "evidence_unit_count": len(evidence_units),
        "candidate_rule_count": len(rule_candidates),
        "pass1_candidate_rule_count": pass1_summary.get("candidate_rule_count"),
        "repair_candidate_rule_count": repair_summary.get("candidate_rule_count", 0),
        "matrix_candidate_count": pass1_summary.get("matrix_candidate_count", 0),
        "cache_hit_count": int(pass1_summary.get("cache_hit_count") or 0) + int(repair_summary.get("cache_hit_count") or 0),
        "extraction_error_count": int(pass1_summary.get("extraction_error_count") or 0) + int(repair_summary.get("extraction_error_count") or 0),
        "safety_contract": f"{discovery_mode.upper()} extraction proposes candidates only. Deterministic verification decides.",
    }
    write_json(model_dir / "evidence_packs.json", [*packs, *repair_packs])
    write_json(model_dir / "raw_model_outputs.json", raw_outputs)
    write_json(model_dir / "evidence_units.json", evidence_units)
    write_json(model_dir / "rule_candidates.json", rule_candidates)
    write_json(model_dir / "extraction_summary.json", summary)
    write_json(model_dir / "model_cost_report.json", cost_report)
    write_json(model_dir / "source_summary.json", source_report)


def _stamp_v3_final(evidence_units: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    for unit in evidence_units:
        unit.setdefault("source_stream", "native_v3_rag_llm")
        unit.setdefault("native_provenance", {})["v3_final"] = True
    for candidate in candidates:
        candidate.setdefault("source_stream", "native_v3_rag_llm")
        method = str(candidate.get("extraction_method") or "")
        if method == "native_v3_clause":
            pass
        elif method.startswith("deterministic_matrix"):
            candidate["extraction_method"] = "deterministic_matrix_v3"
        else:
            candidate["extraction_method"] = "native_rag_llm_v3"
        candidate.setdefault("native_provenance", {})["v3_final"] = True


def _sum_costs(*, city: str, model: str, dry_run: bool, pass1: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    errors = [*(pass1.get("extraction_errors") or []), *(repair.get("extraction_errors") or [])]
    return {
        "city": city,
        "model": None if dry_run else model,
        "dry_run": dry_run,
        "pack_count": int(pass1.get("pack_count") or 0) + int(repair.get("pack_count") or 0),
        "cache_hit_count": int(pass1.get("cache_hit_count") or 0) + int(repair.get("cache_hit_count") or 0),
        "input_chars": int(pass1.get("input_chars") or 0) + int(repair.get("input_chars") or 0),
        "output_chars": int(pass1.get("output_chars") or 0) + int(repair.get("output_chars") or 0),
        "estimated_input_tokens": int(pass1.get("estimated_input_tokens") or 0) + int(repair.get("estimated_input_tokens") or 0),
        "estimated_output_tokens": int(pass1.get("estimated_output_tokens") or 0) + int(repair.get("estimated_output_tokens") or 0),
        "estimated_cost_usd": round(float(pass1.get("estimated_cost_usd") or 0.0) + float(repair.get("estimated_cost_usd") or 0.0), 6),
        "latency_ms": int(pass1.get("latency_ms") or 0) + int(repair.get("latency_ms") or 0),
        "extraction_error_count": len(errors),
        "extraction_errors": errors,
        "pricing_note": "Estimated from character count and planning price table; OpenRouter billing is authoritative.",
    }


def _run_output(output_dir: Path) -> dict[str, list[dict[str, Any]]]:
    return {
        "review": _read_json(output_dir / "review_needed.json", []),
        "rejected": _read_json(output_dir / "rejected_rules.json", []),
        "not_used": _read_json(output_dir / "not_used.json", []),
    }


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


def _read_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe_by_key(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for record in records:
        value = str(record.get(key) or "")
        if value and value not in seen:
            seen.add(value)
            out.append(record)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
