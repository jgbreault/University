"""Optional embedding support for semantic review.

This module is advisory only. It can rank review rules against verified rules
using MiniLM-style sentence embeddings, but it never changes verifier decisions
or clears support gaps.
"""

from __future__ import annotations

import math
import os
from typing import Any


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def rule_meaning_text(rule: dict[str, Any]) -> str:
    """Render a compact sentence from normalized rule fields.

    Keep this deliberately field-based. We do not include gold labels, benchmark
    answers, or broad source context because embeddings are used for review
    prioritization, not proof.
    """
    parts = [
        rule.get("rule_object"),
        rule.get("constraint_type"),
        rule.get("operator"),
        rule.get("value"),
        rule.get("unit"),
        rule.get("constraint_scope"),
        rule.get("applies_to"),
        rule.get("condition"),
        rule.get("exception"),
    ]
    return " ".join(str(part).strip() for part in parts if part not in (None, "")).lower()


def embedding_similarity_lookup(
    review_rules: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    *,
    backend: Any | None = None,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> dict[str, Any]:
    """Return pairwise review-vs-verified embedding similarities.

    ``backend`` is injectable for tests. A real backend only needs an
    ``encode(list[str])`` method. With no backend, this function attempts to load
    ``SentenceTransformer`` in local-files-only mode so ordinary verifier runs
    do not unexpectedly download a model.
    """
    if not review_rules or not verified_rules:
        return _unavailable("no_rules_to_compare", model_name)

    loaded_backend = backend
    load_error = ""
    if loaded_backend is None:
        loaded_backend, load_error = _load_sentence_transformer(model_name)
    if loaded_backend is None:
        return _unavailable(load_error or "embedding_backend_unavailable", model_name)

    review_texts = [rule_meaning_text(rule) for rule in review_rules]
    verified_texts = [rule_meaning_text(rule) for rule in verified_rules]
    try:
        vectors = loaded_backend.encode([*review_texts, *verified_texts])
    except Exception as exc:  # pragma: no cover - depends on optional backend
        return _unavailable(f"embedding_encode_failed:{type(exc).__name__}", model_name)

    review_vectors = [_as_float_list(vector) for vector in vectors[: len(review_rules)]]
    verified_vectors = [_as_float_list(vector) for vector in vectors[len(review_rules) :]]
    scores: dict[tuple[str, str], float] = {}
    for review_rule, review_vector in zip(review_rules, review_vectors):
        review_id = str(review_rule.get("rule_id") or "")
        for verified_rule, verified_vector in zip(verified_rules, verified_vectors):
            verified_id = str(verified_rule.get("rule_id") or "")
            scores[(review_id, verified_id)] = round(_cosine(review_vector, verified_vector), 3)

    return {
        "available": True,
        "model": getattr(loaded_backend, "model_name", model_name),
        "mode": "embedding",
        "scores": scores,
        "review_texts": {str(rule.get("rule_id") or ""): text for rule, text in zip(review_rules, review_texts)},
        "verified_texts": {str(rule.get("rule_id") or ""): text for rule, text in zip(verified_rules, verified_texts)},
        "notes": [
            "Embedding scores are advisory and cannot verify rules.",
            "Deterministic support checks remain the only promotion path.",
        ],
    }


def _load_sentence_transformer(model_name: str) -> tuple[Any | None, str]:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - optional dependency
        return None, f"sentence_transformers_unavailable:{type(exc).__name__}"

    local_only = os.environ.get("BURNABY_EMBEDDING_LOCAL_ONLY", "1") != "0"
    try:
        # local_files_only avoids surprise network downloads during verification
        # runs. To download intentionally, set BURNABY_EMBEDDING_LOCAL_ONLY=0.
        return SentenceTransformer(model_name, local_files_only=local_only), ""
    except TypeError:  # pragma: no cover - older sentence-transformers versions
        try:
            return SentenceTransformer(model_name), ""
        except Exception as exc:
            return None, f"embedding_model_unavailable:{type(exc).__name__}"
    except Exception as exc:  # pragma: no cover - optional dependency/cache state
        return None, f"embedding_model_unavailable:{type(exc).__name__}"


def _unavailable(reason: str, model_name: str) -> dict[str, Any]:
    return {
        "available": False,
        "model": model_name,
        "mode": "structured_only",
        "reason": reason,
        "scores": {},
        "review_texts": {},
        "verified_texts": {},
        "notes": [
            "Embedding backend unavailable; semantic review used structured signatures only.",
            "Install/cache sentence-transformers/all-MiniLM-L6-v2 to enable embedding ranking.",
        ],
    }


def _as_float_list(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))
