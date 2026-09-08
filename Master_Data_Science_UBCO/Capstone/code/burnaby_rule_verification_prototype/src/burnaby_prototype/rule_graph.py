"""Rule/evidence graph for verifier diagnostics.

The graph makes repeated candidates, evidence reuse, same-rule clusters, and
conflicts visible to the dashboard. It is analysis-only: no graph edge can
promote a rule.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .rule_claims import canonical_rule_key


FIELD_BY_CHECK = {
    "value_supported": "value",
    "unit_supported": "unit",
    "operator_supported": "operator",
    "rule_object_supported": "rule_object",
    "scope_supported": "scope",
    "applies_to_supported": "applies_to",
}

FIELD_BY_GAP = {
    "value_not_found_in_evidence": "value",
    "unit_not_found_in_evidence": "unit",
    "operator_not_supported": "operator",
    "rule_object_not_supported": "rule_object",
    "constraint_scope_not_supported": "scope",
    "applies_to_not_supported": "applies_to",
    "table_condition_not_supported": "condition",
    "text_condition_not_supported": "condition",
}


def build_rule_graph(
    *,
    rule_candidates: list[dict[str, Any]],
    evidence_units: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a graph linking candidates, evidence, keys, and verifier outputs."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for evidence in evidence_units:
        evidence_id = str(evidence.get("evidence_id") or "")
        if not evidence_id:
            continue
        _add_node(
            nodes,
            _node_id("evidence_unit", evidence_id),
            "evidence_unit",
            evidence_id,
            page=evidence.get("page"),
            evidence_type=evidence.get("evidence_type"),
        )

    for candidate in rule_candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        key = canonical_rule_key(candidate)
        candidate_node = _node_id("candidate_rule", candidate_id)
        key_node = _node_id("canonical_rule_key", key)
        _add_node(nodes, candidate_node, "candidate_rule", candidate_id, **_rule_attrs(candidate))
        _add_node(nodes, key_node, "canonical_rule_key", key)
        _add_edge(edges, candidate_node, key_node, "same_canonical_key")
        evidence_id = str(candidate.get("evidence_id") or "")
        if evidence_id:
            _add_edge(edges, candidate_node, _node_id("evidence_unit", evidence_id), "cites")

    for rule in verified_rules:
        _add_rule_output(nodes, edges, rule, "verified_rule")
    for rule in review_rules:
        _add_rule_output(nodes, edges, rule, "review_rule")

    _add_similarity_edges(edges, rule_candidates)
    _add_conflict_edges(edges, rule_candidates)
    edge_counts = Counter(edge["type"] for edge in edges)
    node_counts = Counter(node["type"] for node in nodes.values())
    return {
        "purpose": "Diagnostic graph for rule/evidence relationships. Analysis only; verifier decisions are unchanged.",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges,
        "summary": {
            "node_type_counts": _counter_rows(node_counts),
            "edge_type_counts": _counter_rows(edge_counts),
        },
    }


def _add_rule_output(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    rule: dict[str, Any],
    node_type: str,
) -> None:
    rule_id = str(rule.get("rule_id") or "")
    if not rule_id:
        return
    node = _node_id(node_type, rule_id)
    key = str(rule.get("canonical_rule_key") or canonical_rule_key(rule))
    _add_node(nodes, node, node_type, rule_id, decision=rule.get("verification_decision"), **_rule_attrs(rule))
    _add_node(nodes, _node_id("canonical_rule_key", key), "canonical_rule_key", key)
    _add_edge(edges, node, _node_id("canonical_rule_key", key), "same_canonical_key")
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    evidence_id = str(source.get("evidence_id") or "")
    if evidence_id:
        _add_edge(edges, node, _node_id("evidence_unit", evidence_id), "cites")
    candidate_id = str(rule.get("candidate", {}).get("candidate_id") or "")
    if candidate_id:
        _add_edge(edges, node, _node_id("candidate_rule", candidate_id), "from_candidate")
    checks = rule.get("support_checks", {}) if isinstance(rule.get("support_checks"), dict) else {}
    for check, field in FIELD_BY_CHECK.items():
        if checks.get(check):
            _add_edge(edges, node, _node_id("canonical_rule_key", key), "supports_field", field=field)
    for gap in rule.get("support_gaps", []):
        field = FIELD_BY_GAP.get(str(gap))
        if field:
            _add_edge(edges, node, _node_id("canonical_rule_key", key), "missing_field", field=field, gap=gap)


def _add_similarity_edges(edges: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    # No same_source_page grouping: candidates carry no page/source_page field
    # (pages live on evidence units), so that edge type could never fire.
    by_value_unit: dict[str, list[str]] = defaultdict(list)
    by_scope: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        candidate_node = _node_id("candidate_rule", candidate_id)
        value_unit = "::".join(_slug(part) for part in (candidate.get("value"), candidate.get("unit")) if part not in (None, ""))
        scope = "::".join(_slug(part) for part in (candidate.get("rule_object"), candidate.get("constraint_scope")) if part not in (None, ""))
        if value_unit:
            by_value_unit[value_unit].append(candidate_node)
        if scope:
            by_scope[scope].append(candidate_node)
    for group in by_value_unit.values():
        _connect_group(edges, group, "same_value_unit")
    for group in by_scope.values():
        _connect_group(edges, group, "same_scope")


def _add_conflict_edges(edges: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        scope = "::".join(_slug(part) for part in (candidate.get("rule_object"), candidate.get("constraint_scope")) if part not in (None, ""))
        if scope:
            by_scope[scope].append(candidate)
    for group in by_scope.values():
        variants = {
            (_first_number(candidate.get("value")), _direction(candidate.get("operator")), _slug(candidate.get("unit")))
            for candidate in group
            if _first_number(candidate.get("value")) is not None
        }
        if len(variants) < 2:
            continue
        nodes = [_node_id("candidate_rule", str(candidate.get("candidate_id") or "")) for candidate in group if candidate.get("candidate_id")]
        _connect_group(edges, nodes, "conflicts_with")


def _connect_group(edges: list[dict[str, Any]], group: list[str], edge_type: str) -> None:
    # Complete-graph guard: connecting a group emits len*(len-1)/2 edges, so a
    # large group explodes quadratically. Past ~20 members a shared property
    # (same value/unit, same scope) is a generic clique, not a meaningful
    # relationship — it would only bury the dashboard's edge table in noise.
    if len(group) < 2 or len(group) > 20:
        return
    for index, source in enumerate(group):
        for target in group[index + 1 :]:
            _add_edge(edges, source, target, edge_type)


def _add_node(
    nodes: dict[str, dict[str, Any]],
    node_id: str,
    node_type: str,
    label: str,
    **attrs: Any,
) -> None:
    nodes.setdefault(node_id, {"id": node_id, "type": node_type, "label": label, **attrs})


def _add_edge(edges: list[dict[str, Any]], source: str, target: str, edge_type: str, **attrs: Any) -> None:
    if not source or not target or source == target:
        return
    edges.append({"source": source, "target": target, "type": edge_type, **attrs})


def _node_id(node_type: str, raw_id: str) -> str:
    return f"{node_type}:{_slug(raw_id)}"


def _rule_attrs(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
    }


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or "blank"


def _first_number(value: Any) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else None


def _direction(operator: Any) -> str:
    text = str(operator or "").lower()
    if any(token in text for token in (">=", ">", "minimum", "min", "at_least")):
        return "min"
    if any(token in text for token in ("<=", "<", "maximum", "max", "not_exceed")):
        return "max"
    if "allow" in text or "permit" in text:
        return "allowed"
    return "eq"


def _counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common()]
