"""Stable verification cache metadata.

The verifier currently runs fast for Burnaby, but future multi-bylaw runs need
incremental visibility: which candidates/evidence changed, and which previous
results are eligible for reuse.

Safety note:
This module reports cache hits/misses and stores full result snapshots. It does
not skip ``verify_candidates()`` yet because current verification depends on
run-level context such as source agreement and cross-family collisions. Skipping
will be safe only after those dependencies are included in the cache contract
and covered by tests.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


# Bump whenever the shared vocabulary or verify path changes semantics, so
# stale cached decisions can never mask a newly-supported family (the cache
# is stale-conservative, but hiding a recovery is still a wrong answer).
VERIFIER_VERSION = "llm-lane-shape-gates-v7"

CORE_CANDIDATE_FIELDS = (
    "candidate_id",
    "rule_object",
    "constraint_type",
    "constraint_scope",
    "applies_to",
    "operator",
    "value",
    "unit",
    "condition",
    "exception",
    "evidence_id",
    "source_stream",
    "extraction_method",
)


def build_verification_cache_report(
    *,
    config: dict[str, Any],
    evidence_units: list[dict[str, Any]],
    rule_candidates: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    previous_cache: dict[str, Any] | None = None,
    cache_enabled: bool = True,
) -> dict[str, Any]:
    """Return cache metadata and hit/miss diagnostics for this run."""
    evidence_by_id = {str(unit.get("evidence_id") or ""): unit for unit in evidence_units}
    result_by_candidate = _result_by_candidate(verified_rules, review_rules)
    # The run-context hash is stored ONCE at report level, never inside the
    # per-candidate keys: baking it into every key made hit/miss all-or-nothing
    # (changing one candidate changed the run context, which invalidated every
    # other candidate's key too). Per-candidate keys stay local; the run-level
    # dependency is checked separately when judging safe_to_reuse.
    run_context_hash = _run_context_hash(rule_candidates)
    previous_run_context_hash = (previous_cache or {}).get("run_context_hash")
    run_context_unchanged = previous_run_context_hash == run_context_hash
    previous_entries = {
        str(entry.get("cache_key") or ""): entry
        for entry in (previous_cache or {}).get("entries", [])
    }
    entries: list[dict[str, Any]] = []
    for candidate in rule_candidates:
        evidence = evidence_by_id.get(str(candidate.get("evidence_id") or ""), {})
        key_parts = _key_parts(config, candidate, evidence)
        cache_key = _stable_hash(key_parts)
        previous = previous_entries.get(cache_key)
        result = result_by_candidate.get(str(candidate.get("candidate_id") or ""), {})
        cache_hit = bool(cache_enabled and previous)
        # safe_to_reuse is computed AFTER this run's verification on purpose:
        # it measures "would skipping verification have been safe for this
        # candidate" (previous decision == fresh decision, with the run-level
        # context unchanged). It is a diagnostic for the future incremental
        # runner, NOT a reuse mechanism — nothing is skipped based on it.
        entries.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "evidence_id": candidate.get("evidence_id"),
                "cache_key": cache_key,
                "cache_hit": cache_hit,
                "safe_to_reuse": bool(
                    cache_hit
                    and run_context_unchanged
                    and previous.get("decision") == result.get("verification_decision")
                ),
                "previous_decision": previous.get("decision") if previous else None,
                "decision": result.get("verification_decision"),
                "rule_id": result.get("rule_id"),
                "support_gaps": list(result.get("support_gaps", [])),
                "key_parts": key_parts,
            }
        )
    hit_count = sum(1 for item in entries if item["cache_hit"])
    safe_reuse_count = sum(1 for item in entries if item["safe_to_reuse"])
    # Skipping verification on safe_to_reuse is intentionally NOT implemented:
    # verify_candidates() still depends on run-level signals (cross-source
    # agreement, cross-family collisions) that live outside the per-candidate
    # key, so a skip could silently reuse a decision whose run-level inputs
    # changed. The report-level run_context_hash captures that dependency; a
    # future incremental runner may skip only when it matches AND tests cover
    # those run-level paths.
    return {
        "cache_enabled": cache_enabled,
        "cache_mode": "diagnostic_reuse_ready",
        "verifier_version": VERIFIER_VERSION,
        "run_context_hash": run_context_hash,
        "entry_count": len(entries),
        "cache_hit_count": hit_count,
        "safe_reuse_count": safe_reuse_count,
        "cache_miss_count": len(entries) - hit_count,
        "entries": entries,
        "notes": [
            "Cache keys include candidate core fields, cited evidence text, config hash, and verifier version.",
            "The run-level candidate context is hashed once at report level (run_context_hash), not inside per-candidate keys, so one changed candidate cannot invalidate every other entry.",
            "safe_to_reuse requires a cache hit, an unchanged report-level run_context_hash, and a matching decision; it is computed after verification as a would-skipping-have-been-safe diagnostic.",
            "This report identifies reusable results but does not skip deterministic verification yet.",
            "Skipping requires additional tests for run-level source agreement and cross-family collision dependencies.",
        ],
    }


def cache_key_for_candidate(config: dict[str, Any], candidate: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Return the stable key used by tests and future incremental runners."""
    return _stable_hash(_key_parts(config, candidate, evidence))


def _result_by_candidate(
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for rule in [*verified_rules, *review_rules]:
        candidate_id = str(rule.get("candidate", {}).get("candidate_id") or "")
        if candidate_id:
            result[candidate_id] = rule
    return result


def _key_parts(
    config: dict[str, Any],
    candidate: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    core = {field: candidate.get(field) for field in CORE_CANDIDATE_FIELDS}
    evidence_text = " ".join(
        str(evidence.get(field) or "")
        for field in (
            "evidence_text",
            "source_context",
            "table_title",
            "row_header",
            "column_header",
            "cell_value",
        )
    )
    return {
        "candidate_core": core,
        "evidence_id": evidence.get("evidence_id"),
        "evidence_text_hash": _text_hash(evidence_text),
        "config_hash": _text_hash(_stable_json(_cache_relevant_config(config))),
        "verifier_version": VERIFIER_VERSION,
    }


def _run_context_hash(candidates: list[dict[str, Any]]) -> str:
    """Hash run-level candidate context used by consensus/collision checks."""
    context_rows = [
        {
            "candidate_id": candidate.get("candidate_id"),
            "rule_object": candidate.get("rule_object"),
            "constraint_scope": candidate.get("constraint_scope"),
            "operator": candidate.get("operator"),
            "value": candidate.get("value"),
            "unit": candidate.get("unit"),
            "source_stream": candidate.get("source_stream"),
        }
        for candidate in candidates
    ]
    return _stable_hash(context_rows)


def _cache_relevant_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "city": config.get("city"),
        "zone": config.get("zone"),
        "known_aliases": config.get("known_aliases", []),
        "verification": config.get("verification", {}),
        "normalization": config.get("normalization", {}),
    }


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
