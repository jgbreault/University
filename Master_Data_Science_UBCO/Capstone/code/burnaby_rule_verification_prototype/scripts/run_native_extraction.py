#!/usr/bin/env python3
"""Run native RAG + LLM extraction into the verifier contract.

This is a candidate generator only. It writes ``rule_candidates.json`` and
``evidence_units.json`` for ``scripts/run_slim_verifier.py --native-extraction``.
The deterministic verifier remains the authority.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config, resolve_city_paths
from burnaby_prototype.native_extraction import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANK_MODEL,
    load_openrouter_api_key,
    run_native_extraction,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="burnaby_r1", help="City key, e.g. burnaby_r1/calgary_rcg.")
    parser.add_argument("--config", default=None, help="Override configs/<city>.json.")
    parser.add_argument("--pdf", default=None, help="Override data/bylaws/<city>/source.pdf.")
    parser.add_argument("--out", default=None, help="Output dir, default outputs/<city>_native_extraction/.")
    parser.add_argument("--model", default=DEFAULT_CHAT_MODEL, help="OpenRouter chat model for extraction.")
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="OpenRouter embedding model for dense retrieval. Use --no-embeddings to disable.",
    )
    parser.add_argument(
        "--rerank-model",
        default=DEFAULT_RERANK_MODEL,
        help="OpenRouter rerank model. Use --no-rerank to disable.",
    )
    parser.add_argument("--no-embeddings", action="store_true", help="Use BM25 retrieval only.")
    parser.add_argument("--no-rerank", action="store_true", help="Skip reranking retrieved packs.")
    parser.add_argument("--top-k-per-query", type=int, default=8)
    parser.add_argument("--max-packs", type=int, default=40)
    parser.add_argument("--max-pack-chars", type=int, default=3600)
    parser.add_argument(
        "--llm-max-tokens",
        type=int,
        default=1200,
        help="Maximum output tokens per extraction pack.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build retrieval packs only; do not call the LLM. Does not require an API key.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    city_paths = resolve_city_paths(ROOT, args.city)
    config_path = Path(args.config) if args.config else city_paths.config
    config = load_config(config_path)
    pdf_path = Path(args.pdf) if args.pdf else ROOT / "data" / "bylaws" / args.city.lower() / "source.pdf"
    output_dir = Path(args.out) if args.out else ROOT / "outputs" / f"{args.city.lower()}_native_extraction"
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return 1

    api_key = "" if args.dry_run else load_openrouter_api_key(ROOT / ".env")
    if not args.dry_run and not api_key:
        print(
            "OPENROUTER_API_KEY is not set. Put it in your shell environment or in "
            f"{ROOT / '.env'} as OPENROUTER_API_KEY=...; do not commit secrets."
        )
        return 2

    summary = run_native_extraction(
        city=args.city,
        config=config,
        pdf_path=pdf_path,
        output_dir=output_dir,
        api_key=api_key,
        chat_model=args.model,
        embedding_model=None if args.no_embeddings else args.embedding_model,
        rerank_model=None if args.no_rerank else args.rerank_model,
        top_k_per_query=args.top_k_per_query,
        max_packs=args.max_packs,
        max_pack_chars=args.max_pack_chars,
        llm_max_tokens=args.llm_max_tokens,
        dry_run=args.dry_run,
    )

    print("\nNative extraction complete")
    print(f"Output directory: {output_dir}")
    print(f"Source chunks:    {summary['source_chunk_count']}")
    print(f"Retrieval packs:  {summary['retrieval_pack_count']}")
    print(f"Evidence units:   {summary['evidence_unit_count']}")
    print(f"Rule candidates:  {summary['candidate_rule_count']}")
    print(f"Pack errors:      {summary.get('extraction_error_count', 0)}")
    if summary.get("embedding_error"):
        print(f"Embedding warning: {summary['embedding_error']}")
    if summary.get("rerank_error"):
        print(f"Rerank warning:    {summary['rerank_error']}")
    print(
        "\nVerify with:\n"
        f"  .venv/bin/python scripts/run_slim_verifier.py --city {args.city} "
        f"--native-extraction {output_dir} --output-dir outputs/{args.city.lower()}_native_verified --no-cache"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
