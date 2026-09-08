#!/usr/bin/env python3
"""Resolve Pipeline 5 merge-review candidates with an auditable Gemini pass."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

from visual_blocks_rule_extractor import DEFAULT_MODEL, call_gemini, clean, read_jsonl, write_csv, write_json


ATOMIC_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rule_key": {"type": "string"},
        "rule_object": {"type": "string"},
        "constraint_type": {"type": "string"},
        "subject": {"type": "string"},
        "operator": {"type": "string"},
        "value": {"type": "string"},
        "unit": {"type": "string"},
        "condition": {"type": "string"},
        "exception": {"type": "string"},
        "evidence_text": {"type": "string"},
    },
    "required": [
        "rule_key",
        "rule_object",
        "constraint_type",
        "subject",
        "operator",
        "value",
        "unit",
        "condition",
        "exception",
        "evidence_text",
    ],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "merged_rule_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["KEEP", "REPLACE", "DROP"]},
                    "reason": {"type": "string"},
                    "replacement_rules": {"type": "array", "items": ATOMIC_RULE_SCHEMA},
                    "resolved_by_rule_ids": {"type": "array", "items": {"type": "string"}},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "merged_rule_id",
                    "action",
                    "reason",
                    "replacement_rules",
                    "resolved_by_rule_ids",
                    "warnings",
                ],
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decisions", "warnings"],
}

REVIEW_PROMPT = """Review and fully resolve zoning-rule candidates flagged by a deterministic merge audit.

This is a municipality-agnostic post-processing task. Use only the supplied inventory.
Do not invent requirements, values, scopes, or cross-reference outcomes.

For every candidate, return exactly one decision:
- KEEP: the candidate is already an atomic, faithful rule. Preserve an exception when it
  is only an applicability qualifier, exclusion, discretionary escape clause, or unresolved
  cross-reference. Copy the candidate into replacement_rules.
- REPLACE: rewrite or split the candidate into faithful atomic replacement_rules. Use this
  for numeric ranges that are actual lower/upper bounds, independently testable exception
  values, alternate requirements, or a candidate already represented more accurately by
  sibling evidence.
- DROP: emit no replacement_rules only when the candidate is incomplete, non-rule context,
  or fully represented by linked sibling rules. Cite those sibling IDs in resolved_by_rule_ids.

Important distinctions:
1. A numeric phrase such as "1 to 3 units" inside a table cell may be an actual permitted
   range and should become >= lower and <= upper endpoint rules.
2. A numeric phrase such as "regulations for lots with 1 to 3 units" inside a cross-reference
   is a scope label, not a new numeric constraint. Keep it intact.
3. Split an exception only when it states an independently testable alternate value or rule.
   Keep exclusions, discretionary approvals, and unresolved references as qualifiers.
4. If a text block ends with wording such as "as follows:" and sibling table rules provide
   the actual values, drop the incomplete text candidate and cite the sibling rule IDs.
5. replacement_rules must be atomic and traceable to visible evidence. Preserve source wording
   where possible. Do not normalize rule keys to a city-specific vocabulary.

Inventory JSON:
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("visual_blocks_dir", type=Path)
    parser.add_argument("extraction_output_dir", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--benchmark", type=Path, help="Optional gold fixture for prompt evaluation.")
    return parser.parse_args()


def page_number(source_id: Any) -> int:
    parts = clean(source_id).split("__", 1)[0].split("_")
    return int(parts[-1]) if parts and parts[-1].isdigit() else 0


def compact_rule(rule: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "merged_rule_id",
        "rule_id",
        "source_id",
        "rule_key",
        "rule_object",
        "constraint_type",
        "subject",
        "operator",
        "value",
        "unit",
        "condition",
        "exception",
        "evidence_text",
        "review_reasons",
    ]
    return {key: rule.get(key, "") for key in keys}


def build_inventory(
    visual_blocks_dir: Path,
    output_dir: Path,
    review_queue: list[dict[str, Any]],
    merged_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    text_blocks = read_jsonl(visual_blocks_dir / "text_blocks.jsonl")
    review_pages = {page_number(rule.get("source_id")) for rule in review_queue}
    sibling_rules = [
        compact_rule(rule)
        for rule in merged_rules
        if page_number(rule.get("source_id")) in review_pages
    ]
    relevant_text_blocks = [
        {
            "source_id": block.get("block_id"),
            "page_number": block.get("page_number"),
            "block_type": block.get("block_type"),
            "section_path": block.get("section_path", []),
            "parent_context": block.get("parent_context", ""),
            "text": block.get("text", ""),
        }
        for block in text_blocks
        if int(block.get("page_number", 0)) in review_pages
        and block.get("block_type") != "amendment_note"
    ]
    return {
        "review_candidates": [compact_rule(rule) for rule in review_queue],
        "same_page_sibling_rules": sibling_rules,
        "same_page_text_blocks": relevant_text_blocks,
    }


def enrich_replacement(
    replacement: dict[str, Any],
    *,
    candidate: dict[str, Any],
    decision: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    rule = dict(replacement)
    rule["source_id"] = candidate.get("source_id", "")
    rule["source_stream"] = candidate.get("source_stream", "")
    rule["batch_id"] = candidate.get("batch_id", "")
    rule["applies_to"] = candidate.get("applies_to", [])
    rule["applies_to_objects"] = candidate.get("applies_to_objects", [])
    rule["scope_count"] = candidate.get("scope_count", 0)
    rule["scope_mode"] = candidate.get("scope_mode", "")
    if rule["scope_mode"] == "multiple_explicit_scopes":
        rule["rule_object"] = "Multiple explicit scopes; see applies_to_objects"
    rule["api_review_parent_id"] = candidate.get("merged_rule_id", "")
    rule["api_review_action"] = decision.get("action", "")
    rule["api_review_reason"] = decision.get("reason", "")
    rule["api_review_warnings"] = decision.get("warnings", [])
    rule["resolved_by_rule_ids"] = decision.get("resolved_by_rule_ids", [])
    rule["rule_id"] = f"{candidate.get('merged_rule_id', 'reviewed_rule')}__api_{index:02d}"
    return rule


def apply_decisions(
    merged_rules: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    decision_by_id = {clean(decision.get("merged_rule_id")): decision for decision in decisions}
    reviewed_registry: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for candidate in merged_rules:
        if not candidate.get("review_required"):
            reviewed_registry.append(candidate)
            continue
        candidate_id = clean(candidate.get("merged_rule_id"))
        decision = decision_by_id.get(candidate_id)
        if not decision:
            unresolved.append({"merged_rule_id": candidate_id, "reason": "missing_api_decision"})
            continue
        action = clean(decision.get("action"))
        replacements = decision.get("replacement_rules", [])
        if action == "DROP":
            continue
        if action not in {"KEEP", "REPLACE"} or not replacements:
            unresolved.append({"merged_rule_id": candidate_id, "reason": "invalid_api_decision", "decision": decision})
            continue
        reviewed_registry.extend(
            enrich_replacement(replacement, candidate=candidate, decision=decision, index=index)
            for index, replacement in enumerate(replacements, start=1)
        )
    return reviewed_registry, unresolved


def normalized_words(value: Any) -> set[str]:
    words = re.findall(r"[a-z0-9]+", clean(value).lower())
    return {
        word[:-1] if len(word) > 3 and word.endswith("s") else word
        for word in words
        if word not in {"a", "an", "the", "in", "of", "or", "and", "for", "to"}
    }


def semantic_signature(rule: dict[str, Any]) -> tuple[str, ...]:
    """Match equivalent atomic rules even when Gemini chose a different rule key."""
    return tuple(
        clean(rule.get(key)).lower()
        for key in [
            "rule_object",
            "constraint_type",
            "subject",
            "operator",
            "value",
            "unit",
            "condition",
            "exception",
            "evidence_text",
        ]
    )


def preferred_rule(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer an original extracted sibling over a reviewer-generated duplicate."""
    return sorted(
        rules,
        key=lambda rule: (
            bool(rule.get("api_review_parent_id")),
            clean(rule.get("rule_id")),
        ),
    )[0]


def clear_redundant_covered_exceptions(
    rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cleaned_rules = [dict(rule) for rule in rules]
    audit_rows: list[dict[str, Any]] = []
    for rule in cleaned_rules:
        exception = clean(rule.get("exception"))
        exception_words = normalized_words(exception)
        if not exception_words or not rule.get("api_review_parent_id"):
            continue
        for sibling in cleaned_rules:
            if sibling is rule or clean(sibling.get("source_id")) != clean(rule.get("source_id")):
                continue
            if any(
                clean(sibling.get(key)).lower() != clean(rule.get(key)).lower()
                for key in ["operator", "value", "unit"]
            ):
                continue
            sibling_scope_words = normalized_words(
                f"{sibling.get('condition', '')} {sibling.get('evidence_text', '')}"
            )
            if not exception_words.issubset(sibling_scope_words):
                continue
            old_exception = rule["exception"]
            rule["exception"] = ""
            audit_rows.append({
                "action": "clear_redundant_exception",
                "kept_rule_id": rule.get("rule_id", ""),
                "covered_by_rule_id": sibling.get("rule_id", ""),
                "removed_exception": old_exception,
                "reason": "alternate scope is already represented by a same-source sibling rule",
            })
            break
    return cleaned_rules, audit_rows


def consolidate_reviewed_registry(
    reviewed_registry: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove reviewer-generated sibling duplicates and redundant qualifiers."""
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for rule in reviewed_registry:
        grouped.setdefault(semantic_signature(rule), []).append(rule)

    deduplicated: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for rules in grouped.values():
        kept = preferred_rule(rules)
        deduplicated.append(dict(kept))
        for dropped in rules:
            if dropped is kept:
                continue
            audit_rows.append({
                "action": "drop_semantic_duplicate",
                "kept_rule_id": kept.get("rule_id", ""),
                "dropped_rule_id": dropped.get("rule_id", ""),
                "kept_rule_key": kept.get("rule_key", ""),
                "dropped_rule_key": dropped.get("rule_key", ""),
                "reason": "same atomic semantics and evidence after API review",
            })

    cleaned, qualifier_audit = clear_redundant_covered_exceptions(deduplicated)
    return cleaned, [*audit_rows, *qualifier_audit]


def evaluate_against_gold(
    decisions: list[dict[str, Any]],
    benchmark_path: Path,
) -> dict[str, Any]:
    gold_rows = json.loads(benchmark_path.read_text(encoding="utf-8"))
    decisions_by_id = {clean(row.get("merged_rule_id")): row for row in decisions}
    checks: list[dict[str, Any]] = []
    for gold in gold_rows:
        merged_rule_id = clean(gold.get("merged_rule_id"))
        decision = decisions_by_id.get(merged_rule_id, {})
        action_match = clean(decision.get("action")) == clean(gold.get("expected_action"))
        replacement_count = len(decision.get("replacement_rules", []))
        count_match = replacement_count == int(gold.get("expected_replacement_count", 0))
        actual_numeric_rules = {
            (
                clean(rule.get("operator")),
                clean(rule.get("value")),
                clean(rule.get("unit")).lower(),
            )
            for rule in decision.get("replacement_rules", [])
            if clean(rule.get("value"))
        }
        expected_numeric_rules = {
            (clean(operator), clean(value), clean(unit).lower())
            for operator, value, unit in gold.get("expected_numeric_rules", [])
        }
        numeric_rules_match = expected_numeric_rules.issubset(actual_numeric_rules)
        checks.append({
            "merged_rule_id": merged_rule_id,
            "expected_action": gold.get("expected_action", ""),
            "actual_action": decision.get("action", ""),
            "expected_replacement_count": gold.get("expected_replacement_count", 0),
            "actual_replacement_count": replacement_count,
            "action_match": action_match,
            "replacement_count_match": count_match,
            "expected_numeric_rules": sorted(expected_numeric_rules),
            "actual_numeric_rules": sorted(actual_numeric_rules),
            "numeric_rules_match": numeric_rules_match,
            "standard_answer": gold.get("standard_answer", ""),
        })
    numeric_checks = [row for row in checks if row["expected_numeric_rules"]]
    return {
        "benchmark_path": str(benchmark_path.resolve()),
        "gold_rule_count": len(gold_rows),
        "action_accuracy": sum(row["action_match"] for row in checks) / len(checks) if checks else 0,
        "action_and_count_accuracy": (
            sum(row["action_match"] and row["replacement_count_match"] for row in checks) / len(checks)
            if checks else 0
        ),
        "numeric_endpoint_accuracy": (
            sum(row["numeric_rules_match"] for row in numeric_checks) / len(numeric_checks)
            if numeric_checks else 0
        ),
        "full_check_accuracy": (
            sum(
                row["action_match"]
                and row["replacement_count_match"]
                and row["numeric_rules_match"]
                for row in checks
            )
            / len(checks)
            if checks else 0
        ),
        "checks": checks,
    }


def run_api_review(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"{args.api_key_env} is not set.")
    visual_dir = args.visual_blocks_dir.resolve()
    output_dir = args.extraction_output_dir.resolve()
    review_queue = json.loads((output_dir / "merge_review_queue.json").read_text(encoding="utf-8"))
    merged_rules = json.loads((output_dir / "merged_rules_deduplicated.json").read_text(encoding="utf-8"))
    inventory = build_inventory(visual_dir, output_dir, review_queue, merged_rules)
    parsed_path = output_dir / "merge_review_api_response.json"
    raw_path = output_dir / "api_raw" / "merge_review_api_raw_response.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if parsed_path.exists() and not args.overwrite:
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    else:
        parsed, raw = call_gemini(
            prompt=REVIEW_PROMPT + json.dumps(inventory, ensure_ascii=False),
            api_key=api_key,
            model=args.model,
            timeout=args.timeout,
            max_retries=args.max_retries,
            retry_base_seconds=args.retry_base_seconds,
            response_schema=REVIEW_SCHEMA,
        )
        write_json(parsed_path, parsed)
        write_json(raw_path, raw)
    reviewed_registry, unresolved = apply_decisions(merged_rules, parsed.get("decisions", []))
    consolidated_registry, consolidation_audit = consolidate_reviewed_registry(reviewed_registry)
    write_json(output_dir / "final_rules_api_reviewed.json", reviewed_registry)
    write_csv(output_dir / "final_rules_api_reviewed.csv", reviewed_registry)
    write_json(output_dir / "post_review_consolidation_audit.json", consolidation_audit)
    write_csv(output_dir / "post_review_consolidation_audit.csv", consolidation_audit)
    write_json(output_dir / "merge_review_api_unresolved.json", unresolved)
    write_csv(output_dir / "merge_review_api_unresolved.csv", unresolved)
    benchmark_result: dict[str, Any] | None = None
    if args.benchmark:
        benchmark_result = evaluate_against_gold(parsed.get("decisions", []), args.benchmark)
        write_json(output_dir / "merge_review_benchmark_result.json", benchmark_result)
        write_csv(output_dir / "merge_review_benchmark_checks.csv", benchmark_result["checks"])
    summary = {
        "model": args.model,
        "input_review_rule_count": len(review_queue),
        "api_decision_count": len(parsed.get("decisions", [])),
        "api_reviewed_rule_count": len(reviewed_registry),
        "final_rule_count": len(consolidated_registry),
        "post_review_consolidation_action_count": len(consolidation_audit),
        "unresolved_rule_count": len(unresolved),
        "action_counts": pd.Series(
            [decision.get("action", "") for decision in parsed.get("decisions", [])]
        ).value_counts().to_dict(),
        "warnings": parsed.get("warnings", []),
    }
    if benchmark_result:
        summary["benchmark_action_accuracy"] = benchmark_result["action_accuracy"]
        summary["benchmark_action_and_count_accuracy"] = benchmark_result["action_and_count_accuracy"]
        summary["benchmark_numeric_endpoint_accuracy"] = benchmark_result["numeric_endpoint_accuracy"]
        summary["benchmark_full_check_accuracy"] = benchmark_result["full_check_accuracy"]
    write_json(output_dir / "merge_review_api_summary.json", summary)
    write_json(output_dir / "final_rule_registry.json", {
        "pipeline": "prototype_pipeline_5",
        "model": args.model,
        "source_visual_blocks_dir": str(visual_dir),
        "raw_rule_count": len(json.loads((output_dir / "combined_rules_raw.json").read_text(encoding="utf-8"))),
        "deduplicated_rule_count": len(merged_rules),
        "api_review_candidate_count": len(review_queue),
        "api_reviewed_rule_count": len(reviewed_registry),
        "final_rule_count": len(consolidated_registry),
        "post_review_consolidation_action_count": len(consolidation_audit),
        "unresolved_rule_count": len(unresolved),
        "rules": consolidated_registry,
    })
    return summary


def main() -> None:
    summary = run_api_review(parse_args())
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
