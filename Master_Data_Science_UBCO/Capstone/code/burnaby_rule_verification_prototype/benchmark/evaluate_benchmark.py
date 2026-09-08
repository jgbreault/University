#!/usr/bin/env python3
"""Evaluate Burnaby R1 extraction, verification, and proposal safety."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import resolve_city_paths
from burnaby_prototype.compliance import evaluate_cases, summarize_case_results
from burnaby_prototype.domain_schema import RULE_OBJECT_ALIASES, unit_key, unit_visible
from burnaby_prototype.evidence_contract import evidence_quality_summary
from burnaby_prototype.rule_claims import count_claim_labels, proof_trace_completion_rate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--city",
        default="burnaby_r1",
        help="City/zone key. Resolves gold/proposal files and output dir by convention.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Pipeline output directory to evaluate (defaults to outputs/<city>_slim_pipeline5_registry/).",
    )
    parser.add_argument(
        "--gold-rules",
        default=None,
        help="Gold rule JSON file (defaults to benchmark/gold/<city>_gold_rules.json).",
    )
    parser.add_argument(
        "--proposal-cases",
        default=None,
        help="Gold proposal-case JSON file (defaults to benchmark/gold/<city>_proposal_cases.json).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    city = resolve_city_paths(ROOT, args.city)
    output_dir = Path(args.output_dir) if args.output_dir else city.output_dir
    gold_rules = _read_json(Path(args.gold_rules) if args.gold_rules else city.gold_rules, [])
    proposal_cases = _read_json(
        Path(args.proposal_cases) if args.proposal_cases else city.proposal_cases, []
    )

    candidates = _read_json(output_dir / "rule_candidates.json", [])
    evidence_units = _read_json(output_dir / "evidence_units.json", [])
    verified_rules = _read_json(output_dir / "verified_rules.json", [])
    review_rules = _read_json(output_dir / "review_needed.json", [])
    rejected_rules = _read_json(output_dir / "rejected_rules.json", [])
    not_used_rules = _read_json(output_dir / "not_used.json", [])
    retrieval = _read_json(output_dir / "retrieved_blocks.json", {})
    # The GIS contract is a deduped SLIM export (no source.evidence_text / proof
    # detail), so proposal compliance reads the rich verified_rules audit trail.
    # Contract dedupe is external-facing only and cannot move proposal metrics.
    rule_metrics = evaluate_rule_outputs(
        gold_rules=gold_rules,
        evidence_units=evidence_units,
        candidates=candidates,
        verified_rules=verified_rules,
        review_rules=review_rules,
        rejected_rules=rejected_rules,
        not_used_rules=not_used_rules,
        retrieval=retrieval,
    )
    case_results = evaluate_cases(proposal_cases, verified_rules, review_rules)
    proposal_metrics = summarize_case_results(case_results)
    report = {
        "benchmark": args.city,
        "outputs_evaluated": _display_path(output_dir),
        "rule_metrics": rule_metrics,
        "proposal_metrics": proposal_metrics,
        "proposal_results": case_results,
        "quality_gates": _quality_gates(rule_metrics, proposal_metrics),
    }

    _write_json(output_dir / "benchmark_report.json", report)
    _write_markdown(output_dir / "benchmark_report.md", report)
    _write_diagram(output_dir / "benchmark_diagram.mmd")

    print("Benchmark complete")
    print(f"Report: {output_dir / 'benchmark_report.md'}")
    print(f"Verified precision: {rule_metrics['verified_precision']:.2f}")
    print(f"Extraction coverage recall: {rule_metrics['extraction_coverage_recall']:.2f}")
    print(f"Raw candidate artifact recall: {rule_metrics['raw_candidate_artifact_recall']:.2f}")
    print(f"Retrieval recall: {_format_metric(rule_metrics['retrieval_recall'])}")
    print(f"False verified: {rule_metrics['false_verified_count']}")
    print(f"Source support failures: {rule_metrics['verified_source_support_failed_count']}")
    print(f"False approvals: {proposal_metrics['false_approval_count']}")


def evaluate_rule_outputs(
    *,
    gold_rules: list[dict[str, Any]],
    evidence_units: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    rejected_rules: list[dict[str, Any]],
    not_used_rules: list[dict[str, Any]],
    retrieval: dict[str, Any],
) -> dict[str, Any]:
    retrieved_blocks = retrieval.get("deduped_blocks_for_llm", [])
    # Pipeline-5 candidates arrive pre-extracted from the upstream teammate
    # repo, so there is no in-repo retrieval stage to measure; without this
    # skip the retrieval-recall gate would fail vacuously on every run.
    retrieval_applicable = retrieval.get("retrieval_backend") not in {"not_applicable", "external_input"}
    candidate_matches = _match_gold_rules(gold_rules, candidates)
    verified_matches = _match_gold_rules(gold_rules, verified_rules)
    review_matches = _match_gold_rules(gold_rules, review_rules)
    rejected_matches = _match_gold_rules(gold_rules, rejected_rules)
    not_used_matches = _match_gold_rules(gold_rules, not_used_rules)

    matched_candidate_ids = {match["gold_id"] for match in candidate_matches}
    matched_verified_ids = {match["gold_id"] for match in verified_matches}
    matched_review_ids = {match["gold_id"] for match in review_matches}
    matched_rejected_ids = {match["gold_id"] for match in rejected_matches}
    matched_not_used_ids = {match["gold_id"] for match in not_used_matches}
    matched_verified_or_review_ids = matched_verified_ids | matched_review_ids

    # Improvement #1: decompose recall into an *extraction ceiling* and a
    # *verifier retention rate*. The verifier is only responsible for gold rules
    # that extraction actually surfaced (matched by any output rule, normalized).
    # A gold rule that no candidate produced is an upstream coverage gap, not a
    # verifier failure. This separates "we never saw it" from "we saw it and
    # dropped it", which is the honest way to read the recall number.
    extracted_gold_ids = matched_verified_or_review_ids | matched_rejected_ids | matched_not_used_ids
    verifier_rejected_gold_ids = sorted(extracted_gold_ids - matched_verified_or_review_ids)
    unextracted_gold_ids = sorted({gold["gold_id"] for gold in gold_rules} - extracted_gold_ids)

    false_verified = [
        _rule_identifier(rule)
        for rule in verified_rules
        if not _best_gold_match(rule, gold_rules)
    ]
    support_failures = _source_support_failures_from_rules(verified_rules, gold_rules)
    retrieval_hits = _retrieval_hits(gold_rules, retrieved_blocks) if retrieval_applicable else set()
    evidence_metrics = evidence_quality_summary(evidence_units, candidates)

    # Proof metrics evaluate the new verification-explanation layer. They do not
    # replace precision/recall; they tell us whether each decision carries an
    # inspectable proof trace and how much uncertainty remains.
    all_output_rules = [*verified_rules, *review_rules, *rejected_rules, *not_used_rules]
    claim_counts = count_claim_labels(all_output_rules)
    evidence_strengths = [
        float(rule.get("evidence_strength"))
        for rule in all_output_rules
        if isinstance(rule.get("evidence_strength"), (int, float))
    ]
    # Table proof status separates "attempted" from "complete". This avoids
    # counting a refuted/partial table proof as a successful table proof.
    table_status_counts = Counter(str(rule.get("table_proof_status") or "none") for rule in all_output_rules)
    table_proof_count = sum(table_status_counts.get(status, 0) for status in ("complete", "partial", "refuted"))
    proof_mismatch_count = sum(1 for rule in all_output_rules if rule.get("proof_decision_mismatch"))
    high_priority_review_count = sum(1 for rule in review_rules if rule.get("review_priority") == "high")

    gold_count = len(gold_rules)
    verified_count = len(verified_rules)
    raw_candidate_artifact_recall = _safe_ratio(len(matched_candidate_ids), gold_count)
    extraction_coverage_recall = _safe_ratio(len(extracted_gold_ids), gold_count)
    return {
        "gold_rule_count": gold_count,
        "candidate_rule_count": len(candidates),
        "verified_rule_count": verified_count,
        "review_rule_count": len(review_rules),
        "rejected_rule_count": len(rejected_rules),
        "not_used_rule_count": len(not_used_rules),
        # M6 naming: raw candidates are only one artifact bucket. The release
        # extraction gate uses all surfaced extraction outputs, because a gold
        # rule routed directly to review/rejected/not_used was still extracted
        # and seen by the verifier.
        "candidate_recall": raw_candidate_artifact_recall,
        "raw_candidate_artifact_recall": raw_candidate_artifact_recall,
        "release_candidate_recall": extraction_coverage_recall,
        "verified_gold_recall": _safe_ratio(len(matched_verified_ids), gold_count),
        "verified_or_review_recall": _safe_ratio(len(matched_verified_or_review_ids), gold_count),
        # Recall decomposition (improvement #1): ceiling vs verifier retention.
        "extraction_coverage_recall": extraction_coverage_recall,
        "verifier_retention_rate": _safe_ratio(len(matched_verified_or_review_ids), len(extracted_gold_ids)),
        "verifier_rejected_gold_rule_ids": verifier_rejected_gold_ids,
        "not_used_gold_rule_ids": sorted(matched_not_used_ids),
        "unextracted_gold_rule_ids": unextracted_gold_ids,
        "verified_precision": _safe_ratio(verified_count - len(false_verified), verified_count),
        "false_verified_count": len(false_verified),
        "false_verified_rule_ids": false_verified,
        "verified_source_support_failed_count": len(support_failures),
        "verified_source_support_failures": support_failures,
        "retrieval_recall": _safe_ratio(len(retrieval_hits), gold_count) if retrieval_applicable else None,
        "retrieval_recall_applicable": retrieval_applicable,
        "retrieved_gold_rule_ids": sorted(retrieval_hits),
        "missed_candidate_gold_rule_ids": _missing_gold_ids(gold_rules, matched_candidate_ids),
        "missed_verified_gold_rule_ids": _missing_gold_ids(gold_rules, matched_verified_ids),
        "missed_verified_or_review_gold_rule_ids": _missing_gold_ids(gold_rules, matched_verified_or_review_ids),
        "top_review_reasons": _top_support_gaps([*review_rules, *rejected_rules, *not_used_rules]),
        "evidence_quality": evidence_metrics,
        "proof_metrics": {
            # A completion rate of 1.0 means every output rule has basic claim
            # proof fields for value/unit/operator.
            "proof_trace_completion_rate": proof_trace_completion_rate(all_output_rules),
            "supported_claim_count": claim_counts["supported"],
            "refuted_claim_count": claim_counts["refuted"],
            "not_enough_info_claim_count": claim_counts["not_enough_info"],
            # Mean evidence strength is Bayesian-lite triage, not a verification
            # override. Safety is still measured by false_verified/false_approval.
            "mean_evidence_strength": _mean(evidence_strengths),
            "high_priority_review_count": high_priority_review_count,
            "table_proof_count": table_proof_count,
            "table_proof_complete_count": table_status_counts.get("complete", 0),
            "table_proof_partial_count": table_status_counts.get("partial", 0),
            "table_proof_refuted_count": table_status_counts.get("refuted", 0),
            "proof_decision_mismatch_count": proof_mismatch_count,
        },
        "matched_candidates": candidate_matches,
        "matched_verified": verified_matches,
        "matched_review": review_matches,
        "matched_not_used": not_used_matches,
    }


def _match_gold_rules(gold_rules: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for gold in gold_rules:
        match = _best_rule_match(gold, rules)
        if match:
            matches.append(
                {
                    "gold_id": gold["gold_id"],
                    "rule_id": _rule_identifier(match["rule"]),
                    "score": match["score"],
                    "source_page": _rule_source_page(match["rule"]),
                }
            )
    return matches


def _best_gold_match(rule: dict[str, Any], gold_rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = [_score_match(gold, rule) for gold in gold_rules]
    scored = [item for item in scored if item["matches"]]
    if not scored:
        return None
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[0]


def _best_rule_match(gold: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = [_score_match(gold, rule) for rule in rules]
    scored = [item for item in scored if item["matches"]]
    if not scored:
        return None
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[0]


def _score_match(gold: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    # This function underwrites verified_precision: a verified rule only counts
    # as gold-matched (and so escapes false_verified) if it survives the HARD
    # gates below — rule family, numeric value (±0.01), unit, bound direction,
    # and the gold's required terms. Softer signals (exact operator spelling,
    # extra matched terms) only adjust the score used to pick the best match.
    score = 0
    if _match_rule_object(gold) != _match_rule_object(rule):
        return {"matches": False, "score": 0, "rule": rule}
    score += 4

    gold_value = _to_float(gold.get("value"))
    rule_value = _to_float(rule.get("value"))
    if gold_value is not None:
        if rule_value is None or abs(gold_value - rule_value) > 0.01:
            return {"matches": False, "score": 0, "rule": rule}
        score += 3

    if gold.get("unit") is not None:
        if _normalize_unit(gold.get("unit")) != _normalize_unit(rule.get("unit")):
            return {"matches": False, "score": 0, "rule": rule}
        score += 2

    gold_direction = _canonical_operator(gold.get("operator"), gold.get("constraint_type"))
    rule_direction = _canonical_operator(rule.get("operator"), rule.get("constraint_type"))
    # Hard gate on bound direction: a rule with the right value but an inverted
    # bound (gold "max 9 m" vs rule "min 9 m") asserts a different legal claim
    # and must count as false_verified, not as a match. 'gt' and 'min' are both
    # lower bounds, 'lt' and 'max' are both upper bounds, so neither pair
    # contradicts; 'eq'/'allowed' stay lenient because direction is unknown
    # rather than opposite.
    lower, upper = {"min", "gt"}, {"max", "lt"}
    if (gold_direction in lower and rule_direction in upper) or (
        gold_direction in upper and rule_direction in lower
    ):
        return {"matches": False, "score": 0, "rule": rule}
    if gold_direction == rule_direction:
        score += 1

    terms = {_normalize_token(term) for term in gold.get("required_rule_terms", [])}
    words = _rule_words(rule)
    matched_terms = terms & words
    # Require ALL discriminator terms to be present. The old len(terms)-1
    # tolerance for >3 terms let a rule that shared family/value/unit but missed
    # one distinctive term count as a gold match, which could mask a borderline
    # false-verify. Verified across cities: this keeps false_verified at 0 and
    # verified_or_review_recall above the 0.90 gate while being stricter.
    if len(matched_terms) < len(terms):
        return {"matches": False, "score": 0, "rule": rule}
    score += len(matched_terms)
    return {"matches": True, "score": score, "rule": rule}


def _retrieval_hits(gold_rules: list[dict[str, Any]], retrieved_blocks: list[dict[str, Any]]) -> set[str]:
    hits: set[str] = set()
    block_text_by_id = {
        block.get("block_id"): str(block.get("text") or "").lower()
        for block in retrieved_blocks
    }
    combined_retrieved_text = "\n".join(block_text_by_id.values())
    retrieved_words = {_normalize_token(token) for token in re.findall(r"[a-z0-9]+", combined_retrieved_text)}
    for gold in gold_rules:
        source_block_id = gold.get("source_block_id")
        if source_block_id in block_text_by_id:
            hits.add(gold["gold_id"])
            continue
        terms = {_normalize_token(term) for term in gold.get("required_evidence_terms", [])}
        if terms and len(terms & retrieved_words) >= max(1, len(terms) - 1):
            hits.add(gold["gold_id"])
    return hits


def _source_support_failures_from_rules(
    verified_rules: list[dict[str, Any]],
    gold_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Audit that each verified rule's OWN cited evidence states the gold facts.

    The verifier already gates on evidence, so this re-check exists to catch a
    different failure mode: "right answer from the wrong evidence" — a rule that
    matches gold by luck while citing text that never states the required terms,
    value, or unit. That would be invisible to precision/recall alone.
    """
    failures: list[dict[str, Any]] = []
    for rule in verified_rules:
        gold = _best_gold_for_rule(rule, gold_rules)
        if not gold:
            continue
        source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
        evidence_text = "\n".join(
            str(source.get(key) or "") for key in ("evidence_text", "source_context")
        ).lower()
        evidence_words = {_normalize_token(token) for token in re.findall(r"[a-z0-9]+", evidence_text)}
        missing_terms = [
            term
            for term in gold.get("required_evidence_terms", [])
            if _normalize_token(term) not in evidence_words and str(term).lower() not in evidence_text
        ]
        value_missing = gold.get("value") is not None and not _value_present_in_evidence(
            gold.get("value"), evidence_text
        )
        unit_missing = _unit_missing_from_evidence(gold.get("unit"), evidence_text)
        if missing_terms or value_missing or unit_missing:
            failures.append(
                {
                    "rule_id": _rule_identifier(rule),
                    "gold_id": gold.get("gold_id"),
                    "missing_evidence_terms": missing_terms,
                    "value_missing": value_missing,
                    "unit_missing": unit_missing,
                    "evidence_text": source.get("evidence_text"),
                    "has_source_context": bool(source.get("source_context")),
                }
            )
    return failures


def _value_present_in_evidence(value: Any, evidence_text: str) -> bool:
    """Return True when the gold value literally appears in the evidence text.

    The previous check used str(value).rstrip("0").rstrip(".") which corrupted
    integers ending in zero ('60' -> '6', '0' -> ''), silently disabling the
    value gate for 6 of 21 Burnaby gold values. Here we try the raw spelling and
    the trailing-'.0'-stripped spelling, each with digit-boundary lookarounds so
    '5' cannot be "found" inside '7.5' or '50'.
    """
    raw = str(value).strip()
    stripped = re.sub(r"\.0+$", "", raw)
    for token in dict.fromkeys([raw, stripped]):
        # (?!\.?\d) mirrors the verifier's token_visible: sentence-final
        # periods do not hide a value; decimal tails still disqualify.
        if token and re.search(rf"(?<![\d.]){re.escape(token)}(?!\.?\d)", evidence_text):
            return True
    return False


def _best_gold_for_rule(rule: dict[str, Any], gold_rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored: list[tuple[int, dict[str, Any]]] = []
    for gold in gold_rules:
        match = _score_match(gold, rule)
        if match["matches"]:
            scored.append((match["score"], gold))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _quality_gates(rule_metrics: dict[str, Any], proposal_metrics: dict[str, Any]) -> dict[str, Any]:
    has_proposal_cases = proposal_metrics.get("proposal_case_count", 0) > 0
    gates = {
        "verified_precision_is_1": rule_metrics["verified_precision"] == 1.0,
        "false_verified_is_0": rule_metrics["false_verified_count"] == 0,
        "false_approval_is_0": proposal_metrics["false_approval_count"] == 0,
        "retrieval_recall_at_least_0_95": (
            True
            if not rule_metrics.get("retrieval_recall_applicable", True)
            else rule_metrics["retrieval_recall"] >= 0.95
        ),
        "extraction_coverage_recall_at_least_0_95": rule_metrics.get("extraction_coverage_recall", 0.0) >= 0.95,
        "verified_or_review_recall_at_least_0_90": rule_metrics["verified_or_review_recall"] >= 0.90,
        "verified_source_support_failures_is_0": rule_metrics["verified_source_support_failed_count"] == 0,
    }
    # Some holdout cities currently benchmark only rule verification, not
    # proposal compliance. Do not fail a city-level verification run just because
    # no proposal cases exist yet; the proposal gates apply when cases are
    # present.
    if has_proposal_cases:
        gates.update(
            {
                "proposal_decision_accuracy_is_1": proposal_metrics.get("proposal_decision_accuracy") == 1.0,
                "proposal_case_accuracy_is_1": proposal_metrics.get("proposal_case_accuracy", 0.0) == 1.0,
                "proposal_field_expectations_match": proposal_metrics.get("field_expectation_mismatch_count", 0) == 0,
            }
        )
    return {"passed": all(gates.values()), "gates": gates}


def _missing_gold_ids(gold_rules: list[dict[str, Any]], matched_ids: set[str]) -> list[str]:
    return [gold["gold_id"] for gold in gold_rules if gold["gold_id"] not in matched_ids]


def _rule_identifier(rule: dict[str, Any]) -> str:
    return str(rule.get("rule_id") or rule.get("candidate_id") or rule.get("gold_id") or "<unknown>")


def _rule_source_page(rule: dict[str, Any]) -> int | None:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    return source.get("page")


def _rule_text(rule: dict[str, Any]) -> str:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    parts = [
        rule.get("rule_key"),
        rule.get("rule_object"),
        rule.get("constraint_type"),
        rule.get("constraint_scope"),
        rule.get("applies_to"),
        rule.get("subject"),
        rule.get("condition"),
        rule.get("exception"),
        rule.get("value"),
        rule.get("unit"),
        rule.get("original_excerpt"),
        rule.get("evidence_text"),
        rule.get("source_evidence_text"),
        source.get("evidence_text"),
        source.get("source_context"),
        source.get("row_header"),
        source.get("column_header"),
        source.get("cell_value"),
    ]
    return " ".join(str(part) for part in parts if part is not None).lower()


def _rule_words(rule: dict[str, Any]) -> set[str]:
    return {_normalize_token(token) for token in re.findall(r"[a-z0-9]+", _rule_text(rule))}


def _canonical_operator(operator: Any, constraint_type: Any = None) -> str:
    # Mirrors compliance._canonical_operator: '<=' classifies before bare '<',
    # and strict '<' gets its own 'lt' class instead of folding into 'max'.
    text = f"{operator or ''} {constraint_type or ''}".lower()
    if any(token in text for token in ["<=", "maximum", "max", "not_exceed", "not exceed", "≤"]):
        return "max"
    if any(token in text for token in [">=", "minimum", "min", "at_least", "at least", "≥"]):
        return "min"
    if ">" in text:
        return "gt"
    if "<" in text:
        return "lt"
    if "allowed" in text or "permitted" in text:
        return "allowed"
    return "eq"


def _normalize_name(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return RULE_OBJECT_ALIASES.get(normalized, normalized)


def _match_rule_object(rule: dict[str, Any]) -> str:
    """Return the rule family used by benchmark matching.

    Upstream extractors sometimes emit a combined phrase such as "building
    height ... 2 storeys" as a height candidate. The verifier safely projects
    the storey-count claim from the unit, so the benchmark should credit the
    surfaced candidate fact while still hard-gating on value, unit, and bound
    direction.
    """
    if _normalize_unit(rule.get("unit")) == "storeys":
        return "storeys"
    return _normalize_name(rule.get("rule_object"))


def _normalize_unit(value: Any) -> str:
    # Canonicalize through the shared unit_key so the oracle recognizes the
    # same spellings the verifier does (e.g. Vancouver's 'sq. m' == m2). A
    # private alias list here would drift and report spurious unit mismatches.
    return str(unit_key(value) or "")


def _unit_missing_from_evidence(unit: Any, evidence_text: str) -> bool:
    # Shared unit_visible helper, NOT a private spelling list: the old m2
    # branch hardcoded six spellings and missed Vancouver's 'sq. m', so the
    # source-support gate flagged correct floor-area rules whose cited
    # evidence literally states the unit.
    if unit is None:
        return False
    return not unit_visible(evidence_text, unit)


def _normalize_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _top_support_gaps(rules: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for rule in rules:
        for gap in rule.get("support_gaps", []):
            counts[gap] = counts.get(gap, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _format_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _display_path(path: Path) -> str:
    """Return a stable report path without committing local absolute paths."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    rule_metrics = report["rule_metrics"]
    proposal_metrics = report["proposal_metrics"]
    gates = report["quality_gates"]["gates"]
    evidence_quality = rule_metrics.get("evidence_quality", {})
    proof_metrics = rule_metrics.get("proof_metrics", {})
    lines = [
        f"# {report.get('benchmark', 'benchmark')} Benchmark Report",
        "",
        "## Quality Gates",
        "",
    ]
    for name, passed in gates.items():
        status = "PASS" if passed else "FAIL"
        lines.append(f"- {status}: `{name}`")
    lines.extend(
        [
            "",
            "## Rule Metrics",
            "",
            f"- Gold rules: {rule_metrics['gold_rule_count']}",
            f"- Candidate rules: {rule_metrics['candidate_rule_count']}",
            f"- Verified rules: {rule_metrics['verified_rule_count']}",
            f"- Review rules: {rule_metrics['review_rule_count']}",
            f"- Rejected rules: {rule_metrics['rejected_rule_count']}",
            f"- Not-used / traceability-only rules: {rule_metrics.get('not_used_rule_count', 0)}",
            f"- Release candidate recall (all surfaced outputs): {rule_metrics['release_candidate_recall']:.2f}",
            f"- Raw candidate artifact recall: {rule_metrics['raw_candidate_artifact_recall']:.2f}",
            f"- Verified recall: {rule_metrics['verified_gold_recall']:.2f}",
            f"- Verified or review recall: {rule_metrics['verified_or_review_recall']:.2f}",
            f"- Extraction coverage recall (ceiling): {rule_metrics['extraction_coverage_recall']:.2f}",
            f"- Verifier retention rate: {rule_metrics['verifier_retention_rate']:.2f}",
            f"- Verifier-rejected gold rules: {', '.join(rule_metrics['verifier_rejected_gold_rule_ids']) or 'none'}",
            f"- Not-used gold rules: {', '.join(rule_metrics.get('not_used_gold_rule_ids', [])) or 'none'}",
            f"- Unextracted gold rules (upstream gap): {', '.join(rule_metrics['unextracted_gold_rule_ids']) or 'none'}",
            f"- Verified precision: {rule_metrics['verified_precision']:.2f}",
            f"- Retrieval recall: {_format_metric(rule_metrics['retrieval_recall'])}",
            f"- False verified rules: {rule_metrics['false_verified_count']}",
            f"- Source support failures: {rule_metrics['verified_source_support_failed_count']}",
            "",
            "## Top Review / Rejection Reasons",
            "",
            *[
                f"- `{item['reason']}`: {item['count']}"
                for item in rule_metrics.get("top_review_reasons", [])
            ],
            "",
            "## Evidence Quality",
            "",
            f"- Evidence units: {evidence_quality.get('evidence_unit_count', 0)}",
            f"- Mean evidence quality score: {evidence_quality.get('mean_evidence_quality_score', 0):.2f}",
            f"- Candidate/evidence match rate: {evidence_quality.get('candidate_evidence_match_rate', 0):.2f}",
            f"- Candidate value grounding rate: {evidence_quality.get('candidate_value_grounding_rate', 0):.2f}",
            f"- Candidate unit grounding rate: {evidence_quality.get('candidate_unit_grounding_rate', 0):.2f}",
            f"- Table context completion rate: {evidence_quality.get('table_context_completion_rate', 0):.2f}",
            "",
            "## Proof / Bayesian-Lite Triage",
            "",
            f"- Proof trace completion rate: {proof_metrics.get('proof_trace_completion_rate', 0):.2f}",
            f"- Supported claims: {proof_metrics.get('supported_claim_count', 0)}",
            f"- Refuted claims: {proof_metrics.get('refuted_claim_count', 0)}",
            f"- Not-enough-info claims: {proof_metrics.get('not_enough_info_claim_count', 0)}",
            f"- Mean evidence strength: {proof_metrics.get('mean_evidence_strength', 0):.2f}",
            f"- High-priority review rules: {proof_metrics.get('high_priority_review_count', 0)}",
            f"- Table proof rules: {proof_metrics.get('table_proof_count', 0)}",
            f"- Complete table proofs: {proof_metrics.get('table_proof_complete_count', 0)}",
            f"- Partial table proofs: {proof_metrics.get('table_proof_partial_count', 0)}",
            f"- Refuted table proofs: {proof_metrics.get('table_proof_refuted_count', 0)}",
            f"- Proof/decision mismatches: {proof_metrics.get('proof_decision_mismatch_count', 0)}",
            "",
            "### Top Evidence Quality Issues",
            "",
            *[
                f"- `{item['issue']}`: {item['count']}"
                for item in evidence_quality.get("top_evidence_quality_issues", [])
            ],
            "",
            "## Proposal Metrics",
            "",
            f"- Proposal cases: {proposal_metrics['proposal_case_count']}",
            f"- Decision accuracy: {proposal_metrics['proposal_decision_accuracy']:.2f}",
            f"- Case accuracy including expected fields: {proposal_metrics.get('proposal_case_accuracy', 0):.2f}",
            f"- False approvals: {proposal_metrics['false_approval_count']}",
            f"- False rejections: {proposal_metrics['false_rejection_count']}",
            f"- Field expectation mismatches: {proposal_metrics.get('field_expectation_mismatch_count', 0)}",
            f"- Needs review decisions: {proposal_metrics['needs_review_count']}",
            "",
            "## Missed Gold Rules",
            "",
        ]
    )
    for gold_id in rule_metrics["missed_verified_or_review_gold_rule_ids"]:
        lines.append(f"- `{gold_id}`")
    lines.extend(["", "## Proposal Results", ""])
    for result in report["proposal_results"]:
        status = "PASS" if result["matches_expected"] else "FAIL"
        lines.append(
            f"- {status}: `{result['case_id']}` -> {result['decision']} "
            f"(expected {result['expected_decision']})"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_diagram(path: Path) -> None:
    path.write_text(
        """flowchart LR
  A[Burnaby R1 PDF] --> B[Extraction Pipeline]
  B --> C[Rule Candidates]
  C --> D[Verification Layer]
  D --> E[GIS Rule Contract]
  D --> F[Review]
  G[Gold Rule Benchmark] --> H[Benchmark Evaluator]
  C --> H
  D --> H
  I[Proposal Cases] --> J[Tri-state Compliance Checker]
  E --> J
  F --> J
  J --> H
  H --> K[benchmark_report.md]
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
