"""Optional NLI entailment scoring — an advisory SECOND OPINION.

Fact-verification's standard method (FEVER/TabVer lineage — the same
literature behind table_natural_logic): a small cross-encoder NLI model
scores "the cited evidence ENTAILS the rule sentence". Two advisory surfaces:

* review items with HIGH entailment are strong human-promotion candidates;
* verified rules with LOW entailment get an extra audit flag.

Boundary identical to embedding_semantics: never changes a verifier decision,
never clears a support gap; a flag can only ADD review attention. The backend
is injectable for tests; the real loader is local-files-only so ordinary runs
never download a model. With no backend and no local model, every call
returns an honest "unavailable" — byte-identical pipeline outputs.
"""

from __future__ import annotations

from typing import Any

DEFAULT_NLI_MODEL = "cross-encoder/nli-MiniLM2-L6-H768"

# Cross-encoder NLI heads order logits (contradiction, entailment, neutral).
_ENTAILMENT_INDEX = 1


def rule_hypothesis(rule: dict[str, Any]) -> str:
    """Render the rule as a natural-language hypothesis for NLI.

    Field-based on purpose (no gold, no benchmark text): the hypothesis states
    exactly the legal claim the verifier checked, nothing more.
    """
    parts = [
        str(rule.get("applies_to") or "the building"),
        str(rule.get("rule_object") or "").replace("_", " "),
        str(rule.get("constraint_type") or ""),
        str(rule.get("operator") or ""),
        str(rule.get("value") or ""),
        str(rule.get("unit") or ""),
    ]
    condition = str(rule.get("condition") or "").strip()
    sentence = " ".join(part for part in parts if part.strip())
    return f"{sentence} when {condition}" if condition else sentence


def entailment_lookup(
    rules: list[dict[str, Any]],
    *,
    backend: Any | None = None,
    model_name: str = DEFAULT_NLI_MODEL,
) -> dict[str, Any]:
    """Score evidence->rule entailment for each rule. Advisory only.

    ``backend`` needs one method: ``predict(list[tuple[premise, hypothesis]])``
    returning per-pair logits/probabilities (sequence of sequences). With no
    backend, attempts a local-files-only CrossEncoder load; on any failure
    returns ``{"available": False, ...}`` so callers degrade silently.
    """
    if not rules:
        return _unavailable("no_rules", model_name)
    loaded = backend
    load_error = ""
    if loaded is None:
        loaded, load_error = _load_cross_encoder(model_name)
    if loaded is None:
        return _unavailable(load_error or "backend_unavailable", model_name)

    pairs = []
    for rule in rules:
        source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
        premise = " ".join(
            str(source.get(field) or "")
            for field in ("evidence_text", "table_title", "row_header", "column_header", "cell_value")
        ).strip()
        pairs.append((premise, rule_hypothesis(rule)))
    try:
        raw = loaded.predict(pairs)
    except Exception as error:  # pragma: no cover - backend-specific failures
        return _unavailable(f"predict_failed: {error}", model_name)

    items = []
    for rule, scores in zip(rules, raw):
        probabilities = _softmax([float(s) for s in scores])
        entailment = probabilities[_ENTAILMENT_INDEX] if len(probabilities) > _ENTAILMENT_INDEX else None
        items.append(
            {
                "rule_id": rule.get("rule_id"),
                "entailment_probability": round(entailment, 4) if entailment is not None else None,
                "advisory_only": True,
            }
        )
    return {
        "available": True,
        "model": model_name,
        "purpose": "Advisory NLI second opinion. Never changes a verification decision.",
        "items": items,
    }


def audit_flags(report: dict[str, Any], verified_rules: list[dict[str, Any]], *, low: float = 0.2) -> list[dict[str, Any]]:
    """Verified rules whose evidence the NLI model does NOT see as entailing.

    A LOW score is an attention flag for a human auditor — by construction it
    cannot un-verify anything (the deterministic proof already passed); it can
    only point a reviewer at the rule.
    """
    if not report.get("available"):
        return []
    by_id = {item.get("rule_id"): item for item in report.get("items", [])}
    flags = []
    for rule in verified_rules:
        item = by_id.get(rule.get("rule_id"))
        if item and item.get("entailment_probability") is not None and item["entailment_probability"] < low:
            flags.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "entailment_probability": item["entailment_probability"],
                    "note": "NLI second opinion is weak; deterministic proof stands — flagged for human audit only.",
                }
            )
    return flags


def _softmax(values: list[float]) -> list[float]:
    import math

    if not values:
        return []
    peak = max(values)
    exps = [math.exp(v - peak) for v in values]
    total = sum(exps) or 1.0
    return [v / total for v in exps]


def _load_cross_encoder(model_name: str) -> tuple[Any | None, str]:
    try:
        from sentence_transformers import CrossEncoder
    except Exception as error:
        return None, f"sentence-transformers unavailable: {error}"
    try:
        # local_files_only: ordinary verifier runs must never hit the network.
        return CrossEncoder(model_name, local_files_only=True), ""
    except Exception as error:
        return None, f"local model not present: {error}"


def _unavailable(reason: str, model_name: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "model": model_name, "items": []}
