"""Evidence contract checks for the slim verifier.

The verifier only works well when extraction systems provide precise evidence
packets. These helpers make that contract explicit without adding dependencies.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .domain_schema import looks_like_section_reference, token_visible


REQUIRED_EVIDENCE_FIELDS = ("evidence_id", "evidence_text")
TABLE_EVIDENCE_TYPES = {"table_cell", "table_row"}
TABLE_CONTEXT_FIELDS = ("table_title", "row_header", "column_header", "cell_value")


def annotate_evidence_quality(evidence_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add quality score/issue fields to each evidence unit.

    This does not decide whether a rule is verified. It tells us whether the
    extraction layer gave the verifier enough evidence to work with.
    """
    annotated: list[dict[str, Any]] = []
    for unit in evidence_units:
        item = dict(unit)
        score, issues = evidence_quality(unit)
        item["evidence_quality_score"] = score
        item["evidence_quality_issues"] = issues
        annotated.append(item)
    return annotated


def evidence_quality(unit: dict[str, Any]) -> tuple[float, list[str]]:
    """Score one evidence packet for completeness and traceability."""
    issues: list[str] = []
    for field in REQUIRED_EVIDENCE_FIELDS:
        if not str(unit.get(field) or "").strip():
            issues.append(f"missing_{field}")

    if unit.get("page") in (None, ""):
        issues.append("missing_page")

    evidence_type = str(unit.get("evidence_type") or "")
    if evidence_type in TABLE_EVIDENCE_TYPES:
        # Table evidence needs structure, not just raw text. Row/header/cell
        # fields make it possible to prove table rules deterministically.
        missing_table_fields = [
            field for field in TABLE_CONTEXT_FIELDS if not str(unit.get(field) or "").strip()
        ]
        if missing_table_fields:
            issues.append("incomplete_table_context")
        if unit.get("bbox") in (None, ""):
            issues.append("missing_bbox")

    text = str(unit.get("evidence_text") or "")
    source_context = str(unit.get("source_context") or "")
    # This issue is useful for sentence evidence. For assembled table evidence,
    # the text may be constructed from row/column/cell fields, so treat this as
    # a quality warning rather than a verification failure.
    if text and source_context and text.lower() not in source_context.lower():
        issues.append("evidence_text_not_in_source_context")

    # 0.18 per issue: one issue still leaves a mostly-usable packet (0.82),
    # while ~6 accumulated issues drive the score to the 0.0 floor. The exact
    # slope is a reporting convention, not a verification threshold — nothing
    # gates on this score.
    score = max(0.0, 1.0 - 0.18 * len(issues))
    return round(score, 3), issues


def evidence_quality_summary(evidence_units: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize evidence quality across a full run."""
    evidence_by_id = {str(unit.get("evidence_id") or ""): unit for unit in evidence_units}
    candidate_count = len(candidates)
    evidence_scores = [float(unit.get("evidence_quality_score", evidence_quality(unit)[0])) for unit in evidence_units]
    matched_candidates = [
        candidate for candidate in candidates if str(candidate.get("evidence_id") or "") in evidence_by_id
    ]
    value_grounded = [
        candidate
        for candidate in matched_candidates
        if _candidate_value_supported(candidate, evidence_by_id[str(candidate.get("evidence_id") or "")])
    ]
    unit_grounded = [
        candidate
        for candidate in matched_candidates
        if _candidate_unit_supported(candidate, evidence_by_id[str(candidate.get("evidence_id") or "")])
    ]
    table_units = [
        unit for unit in evidence_units if str(unit.get("evidence_type") or "") in TABLE_EVIDENCE_TYPES
    ]
    complete_table_units = [
        unit
        for unit in table_units
        if any(str(unit.get(field) or "").strip() for field in ("row_header", "column_header"))
        and str(unit.get("cell_value") or "").strip()
    ]
    issues = Counter(
        issue
        for unit in evidence_units
        for issue in unit.get("evidence_quality_issues", evidence_quality(unit)[1])
    )
    return {
        "evidence_unit_count": len(evidence_units),
        "candidate_rule_count": candidate_count,
        "mean_evidence_quality_score": round(sum(evidence_scores) / len(evidence_scores), 3) if evidence_scores else 0.0,
        "candidate_evidence_match_rate": _ratio(len(matched_candidates), candidate_count),
        "candidate_value_grounding_rate": _ratio(len(value_grounded), len(matched_candidates)),
        "candidate_unit_grounding_rate": _ratio(len(unit_grounded), len(matched_candidates)),
        "table_evidence_count": len(table_units),
        "table_context_completion_rate": _ratio(len(complete_table_units), len(table_units)),
        "top_evidence_quality_issues": [
            {"issue": issue, "count": count}
            for issue, count in issues.most_common(10)
        ],
    }


def _candidate_value_supported(candidate: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """Evidence-quality check for candidate value grounding.

    Uses the verifier's boundary-aware token_visible discipline rather than
    bare substring containment: a substring test would count '5' as grounded
    by '1.5' or '50' and quietly inflate the reported grounding rate. Commas
    are stripped from both sides first (token_visible expects callers to
    handle comma grouping).
    """
    value = candidate.get("value")
    if value in (None, ""):
        return True
    text = _evidence_search_text(evidence).replace(",", "")
    if _reference_or_text_value_supported(value, text):
        return True
    tokens = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not tokens:
        tokens = [str(value)]
    return all(token_visible(text, token) for token in tokens)


def _reference_or_text_value_supported(value: Any, text: str) -> bool:
    """Ground non-measurement values by exact normalized phrase presence.

    ``token_visible`` deliberately ignores section references such as 101.5.2
    because they are citations, not measurements. That discipline is correct
    for verifier safety, but the evidence-quality report also sees candidates
    whose "value" is a section reference or free-text condition. For those
    non-measurement values, exact normalized phrase presence is the right
    traceability test.
    """
    value_text = str(value or "").strip()
    if not value_text:
        return True
    is_reference = looks_like_section_reference(value_text) or bool(
        re.search(r"\bsections?\b|\bas per\b|\bsubject to\b", value_text, flags=re.IGNORECASE)
    )
    has_words = bool(re.search(r"[A-Za-z]", value_text))
    if not is_reference and not has_words:
        return False
    normalized_value = _normalized_phrase(value_text)
    normalized_text = _normalized_phrase(text)
    return bool(normalized_value and normalized_value in normalized_text)


def _candidate_unit_supported(candidate: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """Lightweight evidence-quality check for candidate unit grounding."""
    unit = str(candidate.get("unit") or "").lower().strip()
    if not unit:
        return True
    text = _evidence_search_text(evidence).lower()
    if unit in {"%", "percent", "percentage"}:
        return "%" in text or "percent" in text or "percentage" in text
    if unit in {"m2", "m 2", "m²", "square metre", "square meter"}:
        return any(marker in text for marker in ["m2", "m 2", "m²", "square metre", "square meter"])
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(unit)}(?![a-z0-9])", text))


def _evidence_search_text(evidence: dict[str, Any]) -> str:
    """Search all evidence fields that might contain value/unit support."""
    return " ".join(
        str(evidence.get(field) or "")
        for field in ("evidence_text", "source_context", "table_title", "row_header", "column_header", "cell_value")
    )


def _normalized_phrase(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _ratio(numerator: int, denominator: int) -> float:
    """Safe ratio helper used by evidence metrics."""
    return round(numerator / denominator, 3) if denominator else 0.0
