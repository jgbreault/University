"""Learned review-queue ranker — ADVISORY, auditable, gold-free at runtime.

Predicts "would a human confirm this review rule as correct?" from the
deterministic features the verifier already emits. Three design rules keep it
defensible:

1. **The model is plain JSON** (feature names + linear coefficients), scored
   by pure-Python dot product here. No pickle, no runtime scikit-learn — the
   exact model is human-readable and diffable in git.
2. **This module never sees gold labels.** Training (and the only gold use)
   lives in ``scripts/train_review_ranker.py``, the same trust tier as the
   benchmark. The runtime scorer consumes only the trained JSON.
3. **Advisory only**: scores ORDER the human review queue; they cannot verify,
   reject, or promote anything (no verify-path module imports this — pinned
   by tests).

Calibration: the trainer wraps scores in split-conformal quantiles so the
dashboard can say "items above this score were correct >=90% of the time on
held-out data" — a distribution-free statement, honestly caveated by n.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

# The closed feature vocabulary. Deterministic, derived ONLY from fields the
# verifier already writes on every review rule.
SUPPORT_CHECKS = (
    "value_supported",
    "unit_supported",
    "operator_supported",
    "applies_to_supported",
    "scope_supported",
    "rule_object_supported",
    "table_context_supported",
    "table_review_gate_passed",
)
GAP_VOCAB = (
    "text_candidate_requires_review",
    "applies_to_not_supported",
    "operator_not_supported",
    "constraint_scope_not_supported",
    "rule_object_not_supported",
    "text_condition_not_supported",
    "rule_family_direction_mismatch",
    "cross_family_value_collision",
    "unresolved_exception_cue",
    "table_cell_candidate_requires_review",
    "table_evidence_candidate_requires_review",
    "table_fallback_candidate_requires_review",
    "table_applies_to_not_supported",
    "table_column_not_target_scope",
    "upstream_extraction_requested_review",
)
PROOF_LABELS = ("supported", "refuted", "not_enough_info")


def feature_names() -> list[str]:
    names = [f"check::{name}" for name in SUPPORT_CHECKS]
    names += [f"gap::{name}" for name in GAP_VOCAB]
    names += [f"proof::{label}" for label in PROOF_LABELS]
    names += ["evidence_strength", "gap_count", "has_condition", "is_table_evidence"]
    return names


def extract_features(rule: dict[str, Any]) -> dict[str, float]:
    """Deterministic feature vector for one review rule."""
    checks = rule.get("support_checks", {}) or {}
    gaps = set(rule.get("support_gaps", []) or [])
    proof = rule.get("proof_trace", {}) or {}
    label_counts = {label: 0.0 for label in PROOF_LABELS}
    for item in proof.values():
        label = str(item.get("label") or "")
        if label in label_counts:
            label_counts[label] += 1.0

    features: dict[str, float] = {}
    for name in SUPPORT_CHECKS:
        features[f"check::{name}"] = 1.0 if checks.get(name) else 0.0
    for name in GAP_VOCAB:
        features[f"gap::{name}"] = 1.0 if name in gaps else 0.0
    for label in PROOF_LABELS:
        features[f"proof::{label}"] = label_counts[label]
    features["evidence_strength"] = float(rule.get("evidence_strength") or 0.0)
    features["gap_count"] = float(len(gaps))
    features["has_condition"] = 1.0 if rule.get("condition") else 0.0
    features["is_table_evidence"] = 1.0 if str(rule.get("proof_type") or "").startswith("table") else 0.0
    return features


def score_rule(rule: dict[str, Any], model: dict[str, Any]) -> float:
    """Pure-Python logistic score from the JSON model. No sklearn at runtime."""
    features = extract_features(rule)
    coefficients = model.get("coefficients", {})
    z = float(model.get("intercept", 0.0))
    for name, weight in coefficients.items():
        z += float(weight) * features.get(name, 0.0)
    return 1.0 / (1.0 + math.exp(-z))


def rank_review_rules(rules: list[dict[str, Any]], model: dict[str, Any]) -> list[dict[str, Any]]:
    """Return rules sorted by learned confidence (desc), with annotations.

    Adds ``ranker_score`` and, when the model carries a conformal threshold,
    ``ranker_calibrated_confident`` — both advisory fields for the dashboard.
    """
    threshold = model.get("conformal", {}).get("score_threshold")
    annotated = []
    for rule in rules:
        score = score_rule(rule, model)
        extra: dict[str, Any] = {"ranker_score": round(score, 4)}
        if threshold is not None:
            extra["ranker_calibrated_confident"] = bool(score >= float(threshold))
        annotated.append({**rule, **extra})
    annotated.sort(key=lambda r: (-r["ranker_score"], str(r.get("rule_id") or "")))
    return annotated


def load_model(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
