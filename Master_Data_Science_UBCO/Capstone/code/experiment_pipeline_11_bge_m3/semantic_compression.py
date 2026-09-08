#!/usr/bin/env python3
"""Compress high-recall discovery blocks before graph/RAG pack building.

Pipeline 11 defaults to a conservative hybrid scorer: lexical and structural
signals still decide most keeps, while local Ollama embeddings rescue/rerank
borderline blocks. This avoids replacing deterministic term evidence with a
black-box semantic score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from auto_discovery import lane_for, read_json, read_jsonl, write_json, write_jsonl


ROOT = Path(__file__).resolve().parent
DEFAULT_DISCOVERY_DIR = ROOT / "outputs" / "calgary" / "02_auto_discovery"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "calgary" / "03_semantic_compression"

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{1,}")

ALWAYS_KEEP_REASONS = {
    "target_term_hit",
    "candidate_window",
    "list_continuation_closure",
}
CONTEXT_REASONS = {
    "same_page_as_target",
    "same_section_as_target",
    "use_section_listing",
    "list_sibling_closure",
}
LANE_BONUS = {
    "target_context": 0.18,
    "permission": 0.12,
    "dimensional_standard": 0.10,
    "parking": 0.08,
    "permit_process": 0.07,
    "cross_reference": 0.04,
    "related_context": 0.02,
    "context_definition": -0.04,
}


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(key, 0.0) for key, value in a.items())


def norm_sparse(vec: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vec.values()))


def cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
    denom = norm_sparse(a) * norm_sparse(b)
    return dot(a, b) / denom if denom else 0.0


def cosine_dense(a: list[float], b: list[float]) -> float:
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / denom if denom else 0.0


def build_query(summary: dict[str, Any], target_terms: list[str], parent_terms: list[str]) -> str:
    config = summary.get("config", {})
    target_description = config.get("target_description", "")
    parts = [
        "zoning bylaw rules for",
        " ".join(target_terms),
        target_description,
        "permission permitted discretionary uses dimensional standards setbacks height floor area density parking permit process exceptions",
        " ".join(parent_terms),
    ]
    return " ".join(part for part in parts if part).strip()


def lexical_scores(blocks: list[dict[str, Any]], query: str) -> dict[str, float]:
    docs = [tokenize(block.get("text_compact") or block.get("text", "")) for block in blocks]
    query_tokens = tokenize(query)
    df = Counter(token for doc in docs for token in set(doc))
    total_docs = max(len(docs), 1)

    def vector(tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        vec: dict[str, float] = {}
        for token, count in counts.items():
            idf = math.log((total_docs + 1) / (df.get(token, 0) + 1)) + 1.0
            vec[token] = (1.0 + math.log(count)) * idf
        return vec

    query_vec = vector(query_tokens)
    scores: dict[str, float] = {}
    for block, tokens in zip(blocks, docs):
        scores[block["block_id"]] = round(cosine_sparse(vector(tokens), query_vec), 4)
    return scores


def ollama_embedding(text: str, model: str, url: str) -> list[float]:
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Ollama embeddings endpoint at {url}: {error}") from error
    embedding = data.get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError(f"Ollama returned no embedding for model {model}.")
    return [float(value) for value in embedding]


def ollama_embeddings_batch(texts: list[str], model: str, url: str) -> list[list[float]]:
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Ollama batch embedding endpoint at {url}: {error}") from error
    embeddings = data.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError(f"Ollama returned invalid batch embeddings for model {model}.")
    return [[float(value) for value in embedding] for embedding in embeddings]


def embedding_cache_key(model: str, text: str) -> str:
    digest = hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()
    return digest


def load_embedding_cache(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {key: [float(value) for value in values] for key, values in raw.items()}


def write_embedding_cache(path: Path, cache: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False) + "\n", encoding="utf-8")


def cached_ollama_embedding(
    text: str,
    model: str,
    url: str,
    cache: dict[str, list[float]],
) -> list[float]:
    key = embedding_cache_key(model, text)
    if key not in cache:
        cache[key] = ollama_embedding(text, model, url)
    return cache[key]


def populate_embedding_cache(
    texts: list[str],
    model: str,
    url: str,
    cache: dict[str, list[float]],
    *,
    batch_size: int,
) -> None:
    missing: list[tuple[str, str]] = []
    seen: set[str] = set()
    for text in texts:
        key = embedding_cache_key(model, text)
        if key in cache or key in seen:
            continue
        seen.add(key)
        missing.append((key, text))

    for start in range(0, len(missing), max(1, batch_size)):
        chunk = missing[start:start + max(1, batch_size)]
        chunk_texts = [text for _, text in chunk]
        try:
            embeddings = ollama_embeddings_batch(chunk_texts, model, url)
        except RuntimeError:
            embeddings = [ollama_embedding(text, model, url) for text in chunk_texts]
        for (key, _), embedding in zip(chunk, embeddings):
            cache[key] = embedding


def ollama_scores(
    blocks: list[dict[str, Any]],
    query: str,
    model: str,
    url: str,
    cache_path: Path | None = None,
    batch_size: int = 16,
) -> tuple[dict[str, float], dict[str, Any]]:
    cache = load_embedding_cache(cache_path) if cache_path else {}
    initial_cache_size = len(cache)
    texts = [query] + [block.get("text_compact") or block.get("text", "") for block in blocks]
    populate_embedding_cache(texts, model, url, cache, batch_size=batch_size)
    query_embedding = cached_ollama_embedding(query, model, url, cache)
    scores: dict[str, float] = {}
    for block in blocks:
        text = block.get("text_compact") or block.get("text", "")
        block_embedding = cached_ollama_embedding(text, model, url, cache)
        scores[block["block_id"]] = round(cosine_dense(block_embedding, query_embedding), 4)
    if cache_path:
        write_embedding_cache(cache_path, cache)
    return scores, {
        "embedding_cache_path": str(cache_path.resolve()) if cache_path else None,
        "embedding_cache_initial_count": initial_cache_size,
        "embedding_cache_final_count": len(cache),
        "embedding_cache_added_count": max(0, len(cache) - initial_cache_size),
        "embedding_batch_size": batch_size,
    }


def structural_score(block: dict[str, Any]) -> float:
    reasons = set(block.get("selected_because", []))
    score = 0.0
    if "target_term_hit" in reasons:
        score += 0.55
    if "candidate_window" in reasons:
        score += 0.25
    if "same_section_as_target" in reasons:
        score += 0.15
    if "same_page_as_target" in reasons:
        score += 0.10
    if "use_section_listing" in reasons:
        score += 0.12
    if "list_continuation_closure" in reasons:
        score += 0.12
    if "list_sibling_closure" in reasons:
        score += 0.05
    if "rule_signal" in reasons:
        score += 0.10
    if "cross_reference" in reasons:
        score += 0.04
    if "parent_term_hit" in reasons:
        score += 0.03
    return min(score, 1.0)


def should_keep(
    block: dict[str, Any],
    final_score: float,
    semantic_score: float,
    threshold: float,
    *,
    provider: str,
    lexical_score: float = 0.0,
    embedding_score: float = 0.0,
) -> bool:
    reasons = set(block.get("selected_because", []))
    if block.get("noise_reasons"):
        return False
    if reasons & ALWAYS_KEEP_REASONS:
        return True
    if "rule_signal" in reasons:
        return True
    if "list_sibling_closure" in reasons:
        return True
    if "use_section_listing" in reasons and ({"same_page_as_target", "same_section_as_target"} & reasons):
        return True
    if "rule_signal" in reasons and ({"same_page_as_target", "same_section_as_target"} & reasons):
        return final_score >= threshold * 0.85
    if reasons & CONTEXT_REASONS:
        return final_score >= threshold
    if provider == "hybrid":
        # Embeddings can rescue semantically close weak blocks, but only when the
        # hybrid score also clears the normal bar. This keeps bge-m3 additive.
        return final_score >= threshold and (
            lexical_score >= threshold * 0.55 or embedding_score >= threshold + 0.10
        )
    return semantic_score >= threshold + 0.08


def compress(args: argparse.Namespace) -> dict[str, Any]:
    discovery_dir = args.discovery_dir.resolve()
    output_dir = args.output_dir.resolve()
    blocks = [
        block for block in read_jsonl(discovery_dir / "discovered_blocks.jsonl")
        if block.get("discovery_selected") and not block.get("noise_reasons")
    ]
    local_summary_path = discovery_dir.parent / "01_local_selection" / "summary.json"
    local_summary = read_json(local_summary_path) if local_summary_path.exists() else {}
    config = local_summary.get("config", {})
    target_terms = args.target_terms or config.get("target_terms") or []
    parent_terms = args.parent_terms or config.get("parent_terms") or []
    query = args.query or build_query(local_summary, target_terms, parent_terms)

    lexical_by_id = lexical_scores(blocks, query)
    embedding_by_id: dict[str, float] = {}
    embedding_cache_summary: dict[str, Any] = {}
    if args.provider == "lexical":
        semantic_scores = lexical_by_id
    elif args.provider == "ollama":
        embedding_by_id, embedding_cache_summary = ollama_scores(
            blocks,
            query,
            args.ollama_model,
            args.ollama_url,
            output_dir / f"ollama_embedding_cache_{args.ollama_model.replace(':', '_')}.json",
            args.embedding_batch_size,
        )
        semantic_scores = embedding_by_id
    elif args.provider == "hybrid":
        embedding_by_id, embedding_cache_summary = ollama_scores(
            blocks,
            query,
            args.ollama_model,
            args.ollama_url,
            output_dir / f"ollama_embedding_cache_{args.ollama_model.replace(':', '_')}.json",
            args.embedding_batch_size,
        )
        semantic_scores = {
            block["block_id"]: round(
                (0.67 * lexical_by_id.get(block["block_id"], 0.0))
                + (0.33 * embedding_by_id.get(block["block_id"], 0.0)),
                4,
            )
            for block in blocks
        }
    else:
        raise ValueError(f"Unsupported provider: {args.provider}")

    compressed: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    scored: list[dict[str, Any]] = []
    for block in blocks:
        sem = semantic_scores.get(block["block_id"], 0.0)
        lexical = lexical_by_id.get(block["block_id"], 0.0)
        embedding = embedding_by_id.get(block["block_id"], 0.0)
        struct = structural_score(block)
        lane = lane_for(block)
        lane_bonus = LANE_BONUS.get(lane, 0.0)
        if args.provider == "hybrid":
            final = round((0.45 * struct) + (0.30 * lexical) + (0.15 * embedding) + lane_bonus, 4)
        else:
            final = round((0.45 * struct) + (0.45 * sem) + lane_bonus, 4)
        updated = {
            **block,
            "semantic_provider": args.provider,
            "semantic_query": query,
            "semantic_score": sem,
            "lexical_score": lexical,
            "embedding_score": embedding,
            "embedding_model": args.ollama_model if args.provider in {"ollama", "hybrid"} else "",
            "structural_score": round(struct, 4),
            "compression_lane": lane,
            "compression_score": final,
        }
        keep = should_keep(
            updated,
            final,
            sem,
            args.threshold,
            provider=args.provider,
            lexical_score=lexical,
            embedding_score=embedding,
        )
        updated["compression_selected"] = keep
        scored.append(updated)
        if keep:
            compressed.append(updated)
        else:
            dropped.append(updated)

    write_jsonl(output_dir / "compressed_blocks.jsonl", compressed)
    write_jsonl(output_dir / "dropped_blocks.jsonl", dropped)
    write_jsonl(output_dir / "scored_blocks.jsonl", sorted(scored, key=lambda row: row["compression_score"], reverse=True))
    summary = {
        "input_discovery_dir": str(discovery_dir),
        "output_dir": str(output_dir),
        "provider": args.provider,
        "query": query,
        "threshold": args.threshold,
        "scoring_policy": (
            "0.45 structural + 0.30 lexical + 0.15 embedding + lane_bonus; "
            "embedding is additive and cannot bypass hard keep/drop rules"
            if args.provider == "hybrid"
            else "0.45 structural + 0.45 semantic + lane_bonus"
        ),
        "ollama_model": args.ollama_model if args.provider in {"ollama", "hybrid"} else "",
        "ollama_url": args.ollama_url if args.provider in {"ollama", "hybrid"} else "",
        "embedding_cache": embedding_cache_summary,
        "input_selected_block_count": len(blocks),
        "compressed_block_count": len(compressed),
        "dropped_block_count": len(dropped),
        "compression_ratio": round(len(compressed) / len(blocks), 3) if blocks else 0.0,
        "compressed_lane_counts": dict(Counter(lane_for(block) for block in compressed)),
        "dropped_lane_counts": dict(Counter(lane_for(block) for block in dropped)),
        "compressed_tier_counts": dict(Counter(block.get("selection_tier", "unknown") for block in compressed)),
        "dropped_tier_counts": dict(Counter(block.get("selection_tier", "unknown") for block in dropped)),
        "compressed_drop_risk_counts": dict(Counter(block.get("drop_risk", "unknown") for block in compressed)),
        "dropped_drop_risk_counts": dict(Counter(block.get("drop_risk", "unknown") for block in dropped)),
        "always_keep_reason_counts": dict(Counter(reason for block in compressed for reason in block.get("selected_because", []))),
        "audit_files": {
            "compressed_blocks": str((output_dir / "compressed_blocks.jsonl").resolve()),
            "dropped_blocks": str((output_dir / "dropped_blocks.jsonl").resolve()),
            "scored_blocks": str((output_dir / "scored_blocks.jsonl").resolve()),
        },
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-dir", type=Path, default=DEFAULT_DISCOVERY_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--provider", choices=["lexical", "ollama", "hybrid"], default="hybrid")
    parser.add_argument("--threshold", type=float, default=0.32)
    parser.add_argument("--query", default="")
    parser.add_argument("--target-terms", nargs="*", default=None)
    parser.add_argument("--parent-terms", nargs="*", default=None)
    parser.add_argument("--ollama-model", default="bge-m3")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--embedding-batch-size", type=int, default=16)
    return parser.parse_args()


def main() -> None:
    print(json.dumps(compress(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
