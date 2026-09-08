"""Shadow reruns for review rules using stronger evidence suggestions.

This module closes the loop between ``evidence_repair.py`` and the verifier. It
does not promote rules by itself. Instead, it takes repair suggestions, swaps a
candidate to the suggested evidence packet, reruns the deterministic verifier,
and writes a report that says whether the rerun is promotion-ready.

The safety rule is simple: a rerun is only promotion-ready if the ordinary
verifier returns ``verified`` with no support gaps. Repair confidence, lexical
similarity, and dashboard scores are never enough.
"""

from __future__ import annotations

import re
from typing import Any

from .decision_policy import REJECTED, REVIEW_NEEDED, VERIFIED
from .domain_schema import token_visible, unresolved_exception_cues
from .support_checks import operator_supported
from .verification import verify_candidates


def run_evidence_reruns(
    config: dict[str, Any],
    evidence_units: list[dict[str, Any]],
    original_candidates: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    repair_report: dict[str, Any],
) -> dict[str, Any]:
    """Rerun repairable candidates against their best alternate evidence.

    ``original_candidates`` are included in the verifier call so normal
    cross-source consensus checks still see the real extraction context. The
    synthetic retry candidates keep the original source stream; this prevents a
    copied candidate from manufacturing fake consensus.
    """
    review_by_rule_id = {str(rule.get("rule_id") or ""): rule for rule in review_rules}
    retry_candidates: list[dict[str, Any]] = []
    retry_metadata: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []

    for suggestion in repair_report.get("suggestions", []):
        if not suggestion.get("can_retry_verification"):
            skipped.append(_skipped_row(suggestion, "repair_suggestion_not_retryable"))
            continue
        top_evidence = _top_evidence(suggestion)
        if not top_evidence:
            skipped.append(_skipped_row(suggestion, "no_alternative_evidence"))
            continue
        original_rule = review_by_rule_id.get(str(suggestion.get("rule_id") or ""))
        if not original_rule:
            skipped.append(_skipped_row(suggestion, "review_rule_not_found"))
            continue

        original_candidate = original_rule.get("candidate", {})
        retry_evidence_id = str(top_evidence.get("evidence_id") or "")
        retry_candidate_id = _retry_candidate_id(original_candidate, retry_evidence_id)
        # The retry candidate is a copy of the original (** spread), so it
        # KEEPS the original's source_stream. That is the anti-collusion
        # property of this rerun: cross-source consensus gates count distinct
        # streams, and a copy that still carries its parent's stream can never
        # be mistaken for an independent second source — a retry can swap
        # evidence, but it cannot fabricate consensus with itself.
        retry_candidate = {
            **original_candidate,
            "candidate_id": retry_candidate_id,
            "evidence_id": retry_evidence_id,
            "original_candidate_id": original_candidate.get("candidate_id"),
            "original_rule_id": original_rule.get("rule_id"),
            "original_evidence_id": suggestion.get("current_evidence_id"),
            "evidence_repair_rerun": True,
        }
        retry_candidates.append(retry_candidate)
        retry_metadata[retry_candidate_id] = {
            "suggestion": suggestion,
            "original_rule": original_rule,
            "top_evidence": top_evidence,
        }

    if retry_candidates:
        # Run one augmented verification pass instead of N isolated passes. That
        # keeps the original extraction context available for consensus gates and
        # is much cheaper for larger bylaw runs.
        verification = verify_candidates(
            config,
            evidence_units,
            [*original_candidates, *retry_candidates],
        )
        verified_by_candidate = {
            rule.get("candidate", {}).get("candidate_id"): rule
            for rule in verification.get("verified_rules", [])
        }
        non_verified_by_candidate = {
            rule.get("candidate", {}).get("candidate_id"): rule
            for rule in verification.get("review_needed", [])
        }
    else:
        verified_by_candidate = {}
        non_verified_by_candidate = {}

    attempts: list[dict[str, Any]] = []
    for retry_candidate in retry_candidates:
        retry_candidate_id = str(retry_candidate.get("candidate_id") or "")
        metadata = retry_metadata[retry_candidate_id]
        result_rule = verified_by_candidate.get(retry_candidate_id) or non_verified_by_candidate.get(retry_candidate_id)
        attempts.append(_attempt_row(retry_candidate, result_rule or {}, metadata))

    verified_after = [item for item in attempts if item["retry_decision"] == VERIFIED]
    promotion_ready = [item for item in attempts if item["promotion_ready"]]
    review_after = [item for item in attempts if item["retry_decision"] == REVIEW_NEEDED]
    rejected_after = [item for item in attempts if item["retry_decision"] == REJECTED]

    return {
        "mode": "shadow_evidence_rerun",
        "notes": [
            "Reruns do not mutate verified_rules.json.",
            "Promotion-ready means the ordinary deterministic verifier returned verified with no risk flags.",
            "Synthetic retry candidates keep the original source_stream so they cannot create fake consensus.",
        ],
        "attempt_count": len(attempts),
        "verified_after_rerun_count": len(verified_after),
        "promotion_ready_count": len(promotion_ready),
        "review_after_rerun_count": len(review_after),
        "rejected_after_rerun_count": len(rejected_after),
        "skipped_count": len(skipped),
        "attempts": attempts,
        "verified_after_rerun": verified_after,
        "promotion_ready": promotion_ready,
        "skipped": skipped,
    }


def run_evidence_bundle_reruns(
    config: dict[str, Any],
    evidence_units: list[dict[str, Any]],
    original_candidates: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    evidence_intelligence_report: dict[str, Any],
) -> dict[str, Any]:
    """Rerun review candidates against their best evidence bundle.

    Bundle evidence is synthetic but fully traceable and SINGLE-SOURCE: it is
    restricted to the one logical source (same table, else same section/page)
    that actually carries the candidate value, and it keeps that source's real
    ``evidence_type``. Two invariants make promotion defensible:

    * Provenance (C1): the verifier can never stitch a value from one rule with a
      qualifier from another, because every member of the synthetic unit shares
      the value-bearing member's provenance key.
    * Honest typing (C2): the synthetic unit is typed as its value-bearing
      member, so a table cell still faces the table-review gates instead of being
      laundered through a permissive ``evidence_bundle`` type.
    """
    review_by_rule_id = {str(rule.get("rule_id") or ""): rule for rule in review_rules}
    evidence_by_id = {str(unit.get("evidence_id") or ""): unit for unit in evidence_units}
    retry_candidates: list[dict[str, Any]] = []
    bundle_evidence_units: list[dict[str, Any]] = []
    retry_metadata: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []

    for item in evidence_intelligence_report.get("items", []):
        rule_id = str(item.get("rule_id") or "")
        if not item.get("safe_retry"):
            skipped.append(_bundle_skipped_row(item, "evidence_intelligence_not_safe_retry"))
            continue
        original_rule = review_by_rule_id.get(rule_id)
        if not original_rule:
            skipped.append(_bundle_skipped_row(item, "review_rule_not_found"))
            continue
        bundle = item.get("best_evidence_bundle", [])
        if not bundle:
            skipped.append(_bundle_skipped_row(item, "no_evidence_bundle"))
            continue
        original_candidate = original_rule.get("candidate", {})
        # C1: restrict to the single logical source that carries the value.
        same_source, provenance_key, value_member = _single_source_bundle(
            bundle, original_candidate, evidence_by_id
        )
        if value_member is None:
            skipped.append(_bundle_skipped_row(item, "bundle_value_not_in_single_source"))
            continue
        # C2: type the synthetic unit as its value-bearing member -> native gates apply.
        bundle_evidence = _synthetic_bundle_evidence(item, same_source, value_member, provenance_key)
        bundle_evidence_units.append(bundle_evidence)

        retry_candidate_id = _retry_candidate_id(original_candidate, str(bundle_evidence["evidence_id"]))
        retry_candidate = {
            **original_candidate,
            "candidate_id": retry_candidate_id,
            "evidence_id": bundle_evidence["evidence_id"],
            "original_candidate_id": original_candidate.get("candidate_id"),
            "original_rule_id": original_rule.get("rule_id"),
            "original_evidence_id": item.get("current_evidence_id"),
            "evidence_bundle_rerun": True,
        }
        retry_candidates.append(retry_candidate)
        retry_metadata[retry_candidate_id] = {
            "intelligence_item": item,
            "original_rule": original_rule,
            "bundle_evidence": bundle_evidence,
        }

    if retry_candidates:
        verification = verify_candidates(
            config,
            [*evidence_units, *bundle_evidence_units],
            [*original_candidates, *retry_candidates],
        )
        verified_by_candidate = {
            rule.get("candidate", {}).get("candidate_id"): rule
            for rule in verification.get("verified_rules", [])
        }
        non_verified_by_candidate = {
            rule.get("candidate", {}).get("candidate_id"): rule
            for rule in verification.get("review_needed", [])
        }
    else:
        verified_by_candidate = {}
        non_verified_by_candidate = {}

    attempts: list[dict[str, Any]] = []
    for retry_candidate in retry_candidates:
        retry_candidate_id = str(retry_candidate.get("candidate_id") or "")
        metadata = retry_metadata[retry_candidate_id]
        result_rule = verified_by_candidate.get(retry_candidate_id) or non_verified_by_candidate.get(retry_candidate_id)
        attempts.append(_bundle_attempt_row(retry_candidate, result_rule or {}, metadata))

    verified_after = [item for item in attempts if item["retry_decision"] == VERIFIED]
    promotion_ready = [item for item in attempts if item["promotion_ready"]]
    review_after = [item for item in attempts if item["retry_decision"] == REVIEW_NEEDED]
    rejected_after = [item for item in attempts if item["retry_decision"] == REJECTED]
    return {
        "mode": "shadow_evidence_bundle_rerun",
        "notes": [
            "Bundle reruns do not mutate verified_rules.json.",
            "Bundle score and safe_retry are advisory only.",
            "Promotion-ready means the ordinary deterministic verifier returned verified with no support gaps or risk flags.",
        ],
        "attempt_count": len(attempts),
        "verified_after_rerun_count": len(verified_after),
        "promotion_ready_count": len(promotion_ready),
        "review_after_rerun_count": len(review_after),
        "rejected_after_rerun_count": len(rejected_after),
        "skipped_count": len(skipped),
        "attempts": attempts,
        "verified_after_rerun": verified_after,
        "promotion_ready": promotion_ready,
        "skipped": skipped,
    }


def apply_bundle_promotions(
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    bundle_rerun_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Move promotion-ready bundle reruns into verified output.

    This is the only place where bundle rerun can reduce review count. The
    promotion source must be a full deterministic verifier result, not a score.
    """
    promoted_by_original_id: dict[str, dict[str, Any]] = {}
    rejected_promotions: list[dict[str, Any]] = []
    for attempt in bundle_rerun_report.get("attempts", []):
        original_rule_id = str(attempt.get("original_rule_id") or "")
        promoted_rule = attempt.get("verified_rule") if isinstance(attempt.get("verified_rule"), dict) else {}
        blockers = _bundle_promotion_blockers(attempt, promoted_rule)
        if blockers:
            if attempt.get("promotion_ready"):
                rejected_promotions.append(
                    {
                        "original_rule_id": original_rule_id,
                        "blockers": blockers,
                        "retry_decision": attempt.get("retry_decision"),
                    }
                )
            continue
        promoted_by_original_id[original_rule_id] = _promoted_bundle_rule(promoted_rule, attempt)

    promoted_original_ids = set(promoted_by_original_id)
    remaining_review_rules = [
        rule for rule in review_rules if str(rule.get("rule_id") or "") not in promoted_original_ids
    ]
    promoted_rules = [promoted_by_original_id[rule_id] for rule_id in sorted(promoted_original_ids)]
    updated_verified_rules = [*verified_rules, *promoted_rules]
    report = {
        "mode": "guarded_bundle_promotion",
        "promotion_count": len(promoted_rules),
        "review_removed_count": len(review_rules) - len(remaining_review_rules),
        "rejected_promotion_count": len(rejected_promotions),
        "promoted_rule_ids": [rule.get("rule_id") for rule in promoted_rules],
        "promoted_rules": promoted_rules,
        "rejected_promotions": rejected_promotions,
        "notes": [
            "Promotion requires deterministic bundle rerun to return verified.",
            "Bundle score alone cannot promote a rule.",
            "Rules with support gaps, proof mismatches, or exception/covenant language stay in review.",
        ],
    }
    return updated_verified_rules, remaining_review_rules, report


def evidence_bundle_rerun_markdown(report: dict[str, Any], *, limit: int = 25) -> str:
    """Render a compact markdown report for bundle reruns."""
    lines = [
        "# Evidence Bundle Rerun Report",
        "",
        "Shadow reruns test the best evidence bundle through the normal verifier. They do not automatically promote rules.",
        "",
        f"- Attempts: {report.get('attempt_count', 0)}",
        f"- Verified after bundle rerun: {report.get('verified_after_rerun_count', 0)}",
        f"- Promotion ready: {report.get('promotion_ready_count', 0)}",
        f"- Still review: {report.get('review_after_rerun_count', 0)}",
        f"- Rejected: {report.get('rejected_after_rerun_count', 0)}",
        f"- Skipped: {report.get('skipped_count', 0)}",
        "",
        f"## Top {limit} Attempts",
        "",
    ]
    for item in report.get("attempts", [])[:limit]:
        lines.append(
            f"- `{item['original_rule_id']}` -> `{item['retry_decision']}` "
            f"ready={item['promotion_ready']} bundle=`{item['bundle_evidence_id']}` "
            f"gaps={', '.join(item.get('retry_support_gaps', [])) or 'none'}"
        )
    return "\n".join(lines) + "\n"


def bundle_promotion_markdown(report: dict[str, Any]) -> str:
    """Render a compact bundle promotion report."""
    lines = [
        "# Guarded Bundle Promotion Report",
        "",
        "This report lists review rules promoted only after deterministic bundle rerun passed.",
        "",
        f"- Promoted rules: {report.get('promotion_count', 0)}",
        f"- Review rows removed: {report.get('review_removed_count', 0)}",
        f"- Rejected promotion candidates: {report.get('rejected_promotion_count', 0)}",
        "",
        "## Promoted Rules",
        "",
    ]
    for rule in report.get("promoted_rules", []):
        lines.append(
            f"- `{rule.get('rule_id')}` {rule.get('rule_object')} "
            f"{rule.get('operator')} {rule.get('value')} {rule.get('unit')}"
        )
    return "\n".join(lines) + "\n"


def evidence_rerun_markdown(report: dict[str, Any], *, limit: int = 25) -> str:
    """Render a compact markdown report for shadow reruns."""
    lines = [
        "# Evidence Rerun Report",
        "",
        "Shadow reruns test stronger evidence through the normal verifier. They do not automatically promote rules.",
        "",
        f"- Attempts: {report.get('attempt_count', 0)}",
        f"- Verified after rerun: {report.get('verified_after_rerun_count', 0)}",
        f"- Promotion ready: {report.get('promotion_ready_count', 0)}",
        f"- Still review: {report.get('review_after_rerun_count', 0)}",
        f"- Rejected: {report.get('rejected_after_rerun_count', 0)}",
        f"- Skipped: {report.get('skipped_count', 0)}",
        "",
        f"## Top {limit} Attempts",
        "",
    ]
    for item in report.get("attempts", [])[:limit]:
        lines.append(
            f"- `{item['original_rule_id']}` -> `{item['retry_decision']}` "
            f"ready={item['promotion_ready']} evidence=`{item['retry_evidence_id']}` "
            f"gaps={', '.join(item.get('retry_support_gaps', [])) or 'none'}"
        )
    return "\n".join(lines) + "\n"


def _provenance_key(unit: dict[str, Any]) -> str:
    """Logical-source key for an evidence unit.

    A table is one logical source (key on its title), else a bylaw section, else
    the page. Two members with the same key may be safely composed (they are the
    same rule instance); members with different keys must not be stitched.
    """
    table_title = str(unit.get("table_title") or "").strip().lower()
    if table_title:
        # Deliberately title-only (no page): Burnaby's "Minimum Lot Area"
        # table CONTINUES across pages, and its cross-page members carry the
        # conditional column wording ('4 Units Only') a legitimate bundle
        # needs. The residual risk — two same-titled but different tables —
        # is mitigated downstream: the value must anchor in one member and
        # the operator must be grounded in that same member, so a wrong-table
        # sibling can no longer flip a bound or donate a value.
        return f"table:{table_title}"
    section = str(unit.get("section") or "").strip().lower()
    if section:
        return f"section:{section}"
    return f"page:{unit.get('page')}"


def _bundle_value_tokens(value: Any) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))


def _single_source_bundle(
    bundle: list[dict[str, Any]],
    candidate: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """Return ``(members, provenance_key, value_member)`` for the single logical
    source that carries the candidate value.

    The value-bearing member is the highest-scored bundle packet whose OWN
    evidence text contains the candidate value; the returned members are exactly
    the bundle packets sharing that member's provenance key. This forbids
    cross-table / cross-section stitching at construction time, so the verifier
    can never assemble field support from packets that describe different rules.
    """
    value_tokens = _bundle_value_tokens(candidate.get("value"))
    if not value_tokens:
        # The bundle path is value-anchored: provenance and the value-bearing
        # member are defined by the candidate's concrete numeric value. A
        # value-less candidate (e.g. height with no number) has nothing to anchor
        # and must never be bundle-promoted.
        return [], None, None
    ordered = sorted(bundle, key=lambda e: (-float(e.get("raw_score") or 0.0), str(e.get("evidence_id") or "")))
    value_member: dict[str, Any] | None = None
    for entry in ordered:
        unit = evidence_by_id.get(str(entry.get("evidence_id") or ""))
        if not unit:
            continue
        text = " ".join(
            str(unit.get(field) or "") for field in ("evidence_text", "cell_value", "source_context")
        ).replace(",", "")
        # Boundary-aware value anchoring (shared token_visible): '4.5' must not
        # anchor inside '14.5'. Comma grouping is stripped from the text above
        # and value tokens never contain commas.
        if all(token_visible(text, token) for token in value_tokens):
            value_member = unit
            break
    if value_member is None:
        return [], None, None
    # The OPERATOR must be grounded in the value member ITSELF: a value and
    # its bound direction are inseparable parts of one legal sentence. Without
    # this, a sibling clause sharing the provenance key (same page/section)
    # can supply opposite wording — e.g. the value member says 'exceeds 3.7 m'
    # (a floor-area computation trigger) while a neighbouring exclusion clause
    # says 'does not exceed' — and the stitched text manufactures support for
    # a flipped operator. Caught live on vancouver_rs_027.
    value_member_text = " ".join(
        str(value_member.get(field) or "")
        for field in (
            "evidence_text",
            "cell_value",
            "source_context",
            "table_title",
            "row_header",
            "column_header",
        )
    )
    if not operator_supported(candidate, value_member_text):
        return [], None, None
    key = _provenance_key(value_member)
    members = [
        unit
        for entry in ordered
        if (unit := evidence_by_id.get(str(entry.get("evidence_id") or ""))) is not None
        and _provenance_key(unit) == key
    ]
    return members, key, value_member


def _synthetic_bundle_evidence(
    item: dict[str, Any],
    members: list[dict[str, Any]],
    value_member: dict[str, Any],
    provenance_key: str | None,
) -> dict[str, Any]:
    """Build a SINGLE-SOURCE synthetic evidence unit, typed as the value-bearing
    member so it faces that evidence type's native gates (C2)."""
    ordered = sorted(members, key=lambda u: str(u.get("evidence_id") or ""))
    parts = [
        f"[{u.get('evidence_id')}] {u.get('evidence_text') or u.get('cell_value')}"
        for u in ordered
        if (u.get("evidence_text") or u.get("cell_value"))
    ]
    combined = "\n".join(parts)
    return {
        "evidence_id": f"bundle::{item.get('rule_id')}",
        "page": value_member.get("page"),
        "evidence_type": value_member.get("evidence_type") or "clause",
        "evidence_text": combined,
        "source_context": combined,
        "table_title": value_member.get("table_title"),
        "row_header": value_member.get("row_header"),
        "column_header": value_member.get("column_header"),
        "cell_value": value_member.get("cell_value"),
        "section": value_member.get("section"),
        "bundle_evidence_ids": [u.get("evidence_id") for u in ordered],
        "bundle_provenance_key": provenance_key,
        "bundle_rule_id": item.get("rule_id"),
    }


def _bundle_attempt_row(
    retry_candidate: dict[str, Any],
    result_rule: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    intelligence_item = metadata["intelligence_item"]
    original_rule = metadata["original_rule"]
    bundle_evidence = metadata["bundle_evidence"]
    retry_decision = str(result_rule.get("verification_decision") or REVIEW_NEEDED)
    retry_gaps = list(result_rule.get("support_gaps", []))
    risk_flags = _bundle_promotion_risk_flags(original_rule, result_rule, intelligence_item, bundle_evidence)
    promotion_ready = retry_decision == VERIFIED and not retry_gaps and not risk_flags
    recommendation = (
        "Candidate can be considered for manual promotion after benchmark/adversarial checks."
        if promotion_ready
        else "Keep in review; inspect bundle gaps and legal-risk flags before changing verifier behavior."
    )
    return {
        "original_rule_id": original_rule.get("rule_id"),
        "original_candidate_id": retry_candidate.get("original_candidate_id"),
        "retry_candidate_id": retry_candidate.get("candidate_id"),
        "rule_object": retry_candidate.get("rule_object"),
        "constraint_scope": retry_candidate.get("constraint_scope"),
        "applies_to": retry_candidate.get("applies_to"),
        "condition": retry_candidate.get("condition"),
        "operator": retry_candidate.get("operator"),
        "value": retry_candidate.get("value"),
        "unit": retry_candidate.get("unit"),
        "original_evidence_id": retry_candidate.get("original_evidence_id"),
        "bundle_evidence_id": bundle_evidence.get("evidence_id"),
        "bundle_evidence_ids": list(bundle_evidence.get("bundle_evidence_ids", [])),
        "bundle_provenance_key": bundle_evidence.get("bundle_provenance_key"),
        "bundle_evidence_type": bundle_evidence.get("evidence_type"),
        "bundle_score": intelligence_item.get("bundle_score"),
        "bundle_missing_fields": list(intelligence_item.get("bundle_missing_fields", [])),
        "bundle_sentence": intelligence_item.get("bundle_sentence"),
        "retry_decision": retry_decision,
        "retry_support_gaps": retry_gaps,
        "retry_support_checks": result_rule.get("support_checks", {}),
        "retry_proof_type": result_rule.get("proof_type"),
        "promotion_ready": promotion_ready,
        "promotion_risk_flags": risk_flags,
        "promotion_recommendation": recommendation,
        "bundle_evidence_quote": bundle_evidence.get("evidence_text"),
        "verified_rule": result_rule if promotion_ready else None,
    }


def _bundle_promotion_risk_flags(
    original_rule: dict[str, Any],
    result_rule: dict[str, Any],
    intelligence_item: dict[str, Any],
    bundle_evidence: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    original_gaps = set(original_rule.get("support_gaps", []))
    if original_gaps & {"cross_family_value_collision", "unresolved_exception_cue", "rule_family_direction_mismatch"}:
        flags.append("original_rule_had_conflict_exception_or_direction_mismatch")
    # An exception-typed candidate encodes an exception/computation provision,
    # not a standalone cap — promoting one as a plain limit is semantically
    # wrong even when every field check passes.
    if str(original_rule.get("constraint_type") or original_rule.get("candidate", {}).get("constraint_type") or "").lower() == "exception":
        flags.append("exception_typed_rule_must_not_bundle_promote")
    if intelligence_item.get("blocked_by"):
        flags.append("evidence_intelligence_blocked")
    if result_rule.get("proof_decision_mismatch"):
        flags.append("proof_decision_mismatch")
    if result_rule.get("verification_decision") == VERIFIED and result_rule.get("support_gaps"):
        flags.append("verified_with_support_gaps")
    if unresolved_exception_cues(bundle_evidence.get("evidence_text")):
        flags.append("bundle_contains_exception_or_covenant_language")
    return flags


def _bundle_promotion_blockers(attempt: dict[str, Any], promoted_rule: dict[str, Any]) -> list[str]:
    # Almost every blocker below re-checks a condition that promotion_ready
    # already implies (retry verified, no gaps, no risk flags, exception scan).
    # That redundancy is DELIBERATE, not an accident: apply_bundle_promotions is
    # the ONLY door through which the advisory layer can reach
    # verified_rules.json, so this gate re-derives every safety condition from
    # the attempt itself instead of trusting an upstream boolean. A bug (or a
    # future edit) that wrongly sets promotion_ready=True upstream is then still
    # caught here, and each rejected promotion lists exactly which re-derived
    # condition failed.
    blockers: list[str] = []
    if not attempt.get("promotion_ready"):
        blockers.append("attempt_not_promotion_ready")
    if not attempt.get("bundle_provenance_key"):
        # Defensive: construction already restricts to one source; never promote a
        # bundle whose evidence spans more than one logical source.
        blockers.append("bundle_not_single_source")
    if not _bundle_value_tokens(attempt.get("value")):
        # Defense in depth: never promote a value-less candidate via a bundle.
        blockers.append("promoted_rule_has_no_anchored_value")
    if attempt.get("retry_decision") != VERIFIED:
        blockers.append("retry_not_verified")
    if attempt.get("retry_support_gaps"):
        blockers.append("retry_has_support_gaps")
    if attempt.get("promotion_risk_flags"):
        blockers.append("promotion_risk_flags_present")
    if attempt.get("bundle_missing_fields"):
        blockers.append("bundle_missing_fields_present")
    if not promoted_rule:
        blockers.append("missing_verified_rule_snapshot")
    if promoted_rule.get("proof_decision_mismatch"):
        blockers.append("proof_decision_mismatch")
    if unresolved_exception_cues(attempt.get("bundle_evidence_quote")):
        blockers.append("bundle_contains_exception_or_covenant_language")
    return blockers


def _promoted_bundle_rule(promoted_rule: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
    rule = dict(promoted_rule)
    original_rule_id = str(attempt.get("original_rule_id") or rule.get("rule_id") or "")
    rule["rule_id"] = original_rule_id
    rule["promotion_source"] = "evidence_bundle_rerun"
    rule["bundle_promotion"] = {
        "original_rule_id": original_rule_id,
        "retry_candidate_id": attempt.get("retry_candidate_id"),
        "bundle_evidence_id": attempt.get("bundle_evidence_id"),
        "bundle_evidence_ids": list(attempt.get("bundle_evidence_ids", [])),
        "bundle_score": attempt.get("bundle_score"),
        "bundle_sentence": attempt.get("bundle_sentence"),
        "original_support_gaps": list(attempt.get("bundle_missing_fields", [])),
    }
    rule["review_reason"] = "verified after guarded evidence bundle rerun"
    return rule


def _attempt_row(
    retry_candidate: dict[str, Any],
    result_rule: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    suggestion = metadata["suggestion"]
    original_rule = metadata["original_rule"]
    top_evidence = metadata["top_evidence"]
    retry_decision = str(result_rule.get("verification_decision") or REVIEW_NEEDED)
    retry_gaps = list(result_rule.get("support_gaps", []))
    risk_flags = _promotion_risk_flags(original_rule, result_rule, top_evidence)
    promotion_ready = retry_decision == VERIFIED and not retry_gaps and not risk_flags
    recommendation = (
        "Candidate can be considered for manual promotion after benchmark/adversarial checks."
        if promotion_ready
        else "Keep in review; inspect rerun gaps and cited evidence before changing verifier behavior."
    )
    source = result_rule.get("source", {}) if isinstance(result_rule.get("source"), dict) else {}
    return {
        "original_rule_id": original_rule.get("rule_id"),
        "original_candidate_id": retry_candidate.get("original_candidate_id"),
        "retry_candidate_id": retry_candidate.get("candidate_id"),
        "rule_object": retry_candidate.get("rule_object"),
        "constraint_scope": retry_candidate.get("constraint_scope"),
        "applies_to": retry_candidate.get("applies_to"),
        "condition": retry_candidate.get("condition"),
        "operator": retry_candidate.get("operator"),
        "value": retry_candidate.get("value"),
        "unit": retry_candidate.get("unit"),
        "original_evidence_id": retry_candidate.get("original_evidence_id"),
        "retry_evidence_id": retry_candidate.get("evidence_id"),
        "retry_evidence_page": top_evidence.get("page"),
        "retry_evidence_type": top_evidence.get("evidence_type"),
        "retry_evidence_quote": top_evidence.get("evidence_quote") or source.get("evidence_text"),
        "repairable_fields": list(suggestion.get("repairable_fields", [])),
        "best_repair_confidence": suggestion.get("best_repair_confidence"),
        "original_support_gaps": list(original_rule.get("support_gaps", [])),
        "retry_decision": retry_decision,
        "retry_support_gaps": retry_gaps,
        "retry_support_checks": result_rule.get("support_checks", {}),
        "retry_proof_type": result_rule.get("proof_type"),
        "retry_table_proof_status": result_rule.get("table_proof_status"),
        "promotion_ready": promotion_ready,
        "promotion_risk_flags": risk_flags,
        "promotion_recommendation": recommendation,
    }


def _promotion_risk_flags(
    original_rule: dict[str, Any],
    result_rule: dict[str, Any],
    top_evidence: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    original_gaps = set(original_rule.get("support_gaps", []))
    if original_gaps & {"cross_family_value_collision", "unresolved_exception_cue"}:
        flags.append("original_rule_had_legal_conflict_or_exception")
    if result_rule.get("proof_decision_mismatch"):
        flags.append("proof_decision_mismatch")
    if result_rule.get("verification_decision") == VERIFIED and result_rule.get("support_gaps"):
        flags.append("verified_with_support_gaps")
    if not top_evidence.get("evidence_id"):
        flags.append("missing_retry_evidence")
    return flags


def _top_evidence(suggestion: dict[str, Any]) -> dict[str, Any]:
    top = suggestion.get("top_evidence") or []
    return top[0] if top else {}


def _retry_candidate_id(original_candidate: dict[str, Any], retry_evidence_id: str) -> str:
    original_id = str(original_candidate.get("candidate_id") or "candidate")
    safe_evidence = re.sub(r"[^a-zA-Z0-9_]+", "_", retry_evidence_id).strip("_")
    return f"{original_id}__rerun__{safe_evidence}"


def _skipped_row(suggestion: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "rule_id": suggestion.get("rule_id"),
        "candidate_id": suggestion.get("candidate_id"),
        "reason": reason,
        "best_repair_confidence": suggestion.get("best_repair_confidence"),
    }


def _bundle_skipped_row(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "rule_id": item.get("rule_id"),
        "candidate_id": item.get("candidate_id"),
        "reason": reason,
        "bundle_score": item.get("bundle_score"),
        "blocked_by": list(item.get("blocked_by", [])),
    }
