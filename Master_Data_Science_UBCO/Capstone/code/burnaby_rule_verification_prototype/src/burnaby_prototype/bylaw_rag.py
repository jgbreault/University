"""Local hybrid RAG over bylaw text — ADVISORY ONLY.

Retrieval for humans: an "ask the bylaw" panel and grounding context for the
review assistant. It never touches a verification decision (no verify-path
module imports this; pinned by tests), and answers are retrieval artifacts —
the verified rule set remains the only executable output of the project.

Method (proven small-corpus recipe):
* **Hybrid retrieval** — BM25 (rank_bm25, fully deterministic, zero model
  downloads) and optional MiniLM dense vectors (reusing the injectable
  embedding backend from :mod:`embedding_semantics`), fused with
  **reciprocal rank fusion** (RRF, k=60).
* **Parent-section expansion** — a chunk hit returns its WHOLE numbered
  section, so a reader always sees the complete legal context, never a
  fragment.
* Deterministic tie-breaks (fused score desc, then chunk id) so the same
  question always returns the same clauses.

The corpus is section-anchored chunks. ``load_corpus`` accepts either the
extraction helper's section text (when a fetched bylaw exists) or, as a
fallback that works for every city today, the run's own ``evidence_units``.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

RRF_K = 60  # standard reciprocal-rank-fusion constant

# DETERMINISTIC query expansion: BM25 is synonym-blind ('tall' never finds
# 'height'), and the dense leg needs a local model most machines won't have.
# Expansion maps query words into the corpus vocabulary two ways:
# 1. a small curated colloquial map (kept HERE, documented, testable);
# 2. the verifier's own shared vocabulary (domain_schema unit aliases +
#    rule-family text patterns) — the same closed lists the gate trusts.
# Expansion only ADDS terms for ranking; it never changes what a clause says.
_COLLOQUIAL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "tall": ("height",),
    "high": ("height",),
    "taller": ("height",),
    "big": ("floor", "area", "size"),
    "large": ("floor", "area", "size"),
    "size": ("floor", "area"),
    "far": ("setback", "distance"),
    "close": ("setback", "separation", "distance"),
    "distance": ("setback", "separation"),
    "wide": ("width",),
    "floors": ("storeys",),
    "levels": ("storeys",),
    "garage": ("parking",),
}


def _domain_expansions() -> dict[str, tuple[str, ...]]:
    """Word -> related corpus words, derived from the shared verifier vocabulary."""
    try:
        from .domain_schema import TEXT_RULE_OBJECT_PATTERNS, UNIT_ALIASES
    except Exception:  # pragma: no cover - domain_schema is always present in-repo
        return {}
    expansions: dict[str, set[str]] = {}
    for key, aliases in UNIT_ALIASES.items():
        words = {w for alias in [key, *aliases] for w in re.findall(r"[a-z]+", alias)}
        for word in words:
            expansions.setdefault(word, set()).update(words - {word})
    for family, phrase_groups in TEXT_RULE_OBJECT_PATTERNS:
        words = {w for group in phrase_groups for phrase in group for w in re.findall(r"[a-z]+", phrase)}
        words.update(re.findall(r"[a-z]+", family))
        for word in words:
            expansions.setdefault(word, set()).update(words - {word})
    return {word: tuple(sorted(related)) for word, related in expansions.items()}


_DOMAIN_EXPANSIONS = _domain_expansions()


def expand_query_terms(question: str) -> list[str]:
    """Return the question's tokens plus deterministic vocabulary expansions."""
    tokens = tokenize(question)
    expanded = list(tokens)
    seen = set(tokens)
    for token in tokens:
        for extra in (*_COLLOQUIAL_SYNONYMS.get(token, ()), *_DOMAIN_EXPANSIONS.get(token, ())):
            if extra not in seen:
                seen.add(extra)
                expanded.append(extra)
    return expanded


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", str(text or "").lower())


def load_corpus_from_evidence_units(evidence_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback corpus: one chunk per evidence unit (works for every city)."""
    chunks: list[dict[str, Any]] = []
    for unit in evidence_units:
        text = " ".join(
            str(unit.get(field) or "")
            for field in ("table_title", "row_header", "column_header", "cell_value", "evidence_text")
        ).strip()
        if not text:
            continue
        chunks.append(
            {
                "chunk_id": str(unit.get("evidence_id") or f"chunk_{len(chunks):04d}"),
                "section": str(unit.get("section") or _section_from_text(text) or ""),
                "page": unit.get("page"),
                "text": text,
            }
        )
    return chunks


def load_corpus_from_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preferred corpus: the extraction helper's section-anchored text."""
    chunks: list[dict[str, Any]] = []
    for item in sections:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        chunks.append(
            {
                "chunk_id": str(item.get("chunk_id") or item.get("section") or f"chunk_{len(chunks):04d}"),
                "section": str(item.get("section") or ""),
                "page": item.get("page"),
                "text": text,
            }
        )
    return chunks


def _section_from_text(text: str) -> str | None:
    match = re.match(r"\s*(\d+(?:\.\d+)+)", text)
    return match.group(1) if match else None


class BylawIndex:
    """Hybrid BM25 + optional-dense index with RRF fusion.

    ``embedding_backend`` follows the embedding_semantics contract: an object
    with ``encode(list[str]) -> vectors``. None (the default) means BM25-only —
    fully deterministic with zero model downloads, matching the project's
    offline-first philosophy.
    """

    def __init__(self, chunks: list[dict[str, Any]], embedding_backend: Any | None = None) -> None:
        from rank_bm25 import BM25Okapi

        self.chunks = list(chunks)
        self._token_sets = [set(tokenize(chunk["text"])) for chunk in self.chunks]
        self._bm25 = BM25Okapi([tokenize(chunk["text"]) for chunk in self.chunks]) if self.chunks else None
        self._backend = embedding_backend
        self._dense_vectors = None
        if self._backend is not None and self.chunks:
            self._dense_vectors = [
                _normalized(vector) for vector in self._backend.encode([c["text"] for c in self.chunks])
            ]

    def search(self, question: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        """Return top-k chunks with RRF-fused scores and per-signal ranks."""
        if not self.chunks:
            return []
        bm25_rank = self._bm25_ranks(question)
        dense_rank = self._dense_ranks(question)
        fused: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for index, chunk in enumerate(self.chunks):
            score = 0.0
            signals: dict[str, Any] = {}
            if index in bm25_rank:
                score += 1.0 / (RRF_K + bm25_rank[index])
                signals["bm25_rank"] = bm25_rank[index]
            if dense_rank is not None and index in dense_rank:
                score += 1.0 / (RRF_K + dense_rank[index])
                signals["dense_rank"] = dense_rank[index]
            if score > 0.0:
                fused.append((score, chunk, signals))
        fused.sort(key=lambda item: (-item[0], str(item[1]["chunk_id"])))
        return [
            {**chunk, "score": round(score, 6), "signals": signals}
            for score, chunk, signals in fused[:top_k]
        ]

    def ask(self, question: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        """search() + parent-section expansion: full legal context per hit.

        Siblings are grouped by EXACT section label and expanded only when there
        is more than one. (A parent-key grouping was tried to reunite distinctly
        labelled subsections like 539(1)/539(2), but it makes every sibling's
        ``section_text`` identical to the full parent, which then collapses under
        the byte-identical pack dedup in ``retrieve_packs`` and starves the pack
        budget -- a net recall LOSS. Subsection-level recall is better addressed
        by making each subsection individually retrievable, not by bloating one
        hit with the whole parent.)
        """
        hits = self.search(question, top_k=top_k)
        by_section: dict[str, list[dict[str, Any]]] = {}
        for chunk in self.chunks:
            if chunk.get("section"):
                by_section.setdefault(chunk["section"], []).append(chunk)
        results = []
        for hit in hits:
            section = hit.get("section") or ""
            siblings = by_section.get(section, [])
            expanded = (
                "\n".join(sib["text"] for sib in siblings) if len(siblings) > 1 else hit["text"]
            )
            results.append({**hit, "section_text": expanded})
        return results

    def _bm25_ranks(self, question: str) -> dict[int, int]:
        # Deterministic expansion closes BM25's synonym gap ('tall'->'height')
        # using the curated colloquial map + the verifier's own vocabulary.
        query_tokens = expand_query_terms(question)
        scores = self._bm25.get_scores(query_tokens)
        query_set = set(query_tokens)
        # Eligibility by token OVERLAP, not score>0: on tiny/degenerate corpora
        # BM25's IDF goes negative for common terms, which would silently drop
        # genuinely matching chunks. No shared token at all = no signal.
        eligible = [index for index, tokens in enumerate(self._token_sets) if tokens & query_set]
        order = sorted(eligible, key=lambda i: (-scores[i], str(self.chunks[i]["chunk_id"])))
        return {index: rank + 1 for rank, index in enumerate(order)}

    def _dense_ranks(self, question: str) -> dict[int, int] | None:
        if self._backend is None or self._dense_vectors is None:
            return None
        query = _normalized(self._backend.encode([question])[0])
        sims = [
            sum(q * d for q, d in zip(query, vector))
            for vector in self._dense_vectors
        ]
        order = sorted(range(len(sims)), key=lambda i: (-sims[i], str(self.chunks[i]["chunk_id"])))
        return {index: rank + 1 for rank, index in enumerate(order)}


def _normalized(vector: Any) -> list[float]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def build_index_payload(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Serializable index artifact (chunks only — BM25 rebuilds in ms)."""
    return {
        "purpose": "Advisory bylaw retrieval corpus. Never read by the verifier.",
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def load_index(path: Path, embedding_backend: Any | None = None) -> BylawIndex:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BylawIndex(payload.get("chunks", []), embedding_backend=embedding_backend)


def grounded_answer_prompt(question: str, results: list[dict[str, Any]]) -> str:
    """Prompt for the OPTIONAL LLM answer: cite-only-the-retrieved-clauses.

    Kept here (not in the assistant) so the grounding contract is testable:
    the model is instructed to answer ONLY from the provided sections and to
    cite section numbers; anything else must be declared unanswerable.
    """
    sections = "\n\n".join(
        f"[{res.get('section') or res.get('chunk_id')}] {res.get('section_text') or res.get('text')}"
        for res in results
    )
    return (
        "Answer the question using ONLY the bylaw sections below. Cite the "
        "section number in brackets for every claim. If the sections do not "
        "answer the question, say exactly that — do not speculate.\n\n"
        f"SECTIONS:\n{sections}\n\nQUESTION: {question}"
    )
