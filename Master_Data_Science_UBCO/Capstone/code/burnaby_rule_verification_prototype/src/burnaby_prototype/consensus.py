"""Cross-source consensus and conflict detection (improvements #2 + #3).

Pipeline 5 produces candidates from several streams (table images, text blocks,
deterministic table parsing). When two independent streams describe the *same*
rule, that agreement is strong corroborating evidence. When they describe the
same rule *scope* with different values or directions, that is a conflict a human
should see before anything reaches GIS.

This module never decides verification on its own. It produces:

* a source-agreement lookup used to gate text auto-verification, and
* ``rule_consensus`` / ``rule_conflicts`` report structures for output.

Consensus can only *raise confidence*; it can never override a deterministic
support gap, and a conflict never silently picks a winner.
"""

from __future__ import annotations

import re
from typing import Any


from .domain_schema import to_float as _to_float
from .domain_schema import unit_key


def _direction(operator: Any) -> str:
    text = str(operator or "").lower()
    if any(token in text for token in (">=", "≥", ">", "min", "at_least")):
        return "min"
    if any(token in text for token in ("<=", "≤", "<", "max", "not_exceed")):
        return "max"
    if "allow" in text or "permit" in text:
        return "allowed"
    return "eq"


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def scope_key(candidate: dict[str, Any]) -> str:
    """Identity of a rule's *scope* (rule family + constraint scope).

    Two candidates that share a scope key but disagree on value/direction are a
    conflict. Two that also share value/direction are a consensus. We deliberately
    key on rule_object + constraint_scope only, because the same rule is often
    phrased with different ``applies_to`` wording across extraction streams.
    """
    # When constraint_scope is empty, fall back to applies_to (mirroring the
    # conflict guard): otherwise the key degenerates to the bare rule family
    # and two DIFFERENT rules that happen to share a value (e.g. two distinct
    # 1.5 m setbacks told apart only by applies_to) would corroborate each
    # other across streams — manufactured consensus.
    return "::".join(
        _slug(part)
        for part in (
            candidate.get("rule_object"),
            candidate.get("constraint_scope") or candidate.get("applies_to"),
        )
    )


def consensus_key(candidate: dict[str, Any]) -> str:
    """Full identity of a rule, including value/unit/direction.

    The unit component uses the canonical unit_key, NOT a text slug: slugging
    stripped non-alphanumerics, so 'm²' collapsed to 'm' (a 557 m mis-extraction
    could corroborate a 557 m² lot-area rule across streams) and '%' collapsed
    to '' (indistinguishable from a missing unit).
    """
    value = _to_float(candidate.get("value"))
    value_part = f"{value:.3f}" if value is not None else _slug(candidate.get("value"))
    return "::".join(
        [
            scope_key(candidate),
            value_part,
            str(unit_key(candidate.get("unit")) or "__no_unit__"),
            _direction(candidate.get("operator")),
        ]
    )


def _source_of(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("source_stream")
        or candidate.get("extraction_method")
        or candidate.get("extraction_source")
        or "unknown"
    )


def build_source_agreement(candidates: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Map each full consensus key to the distinct source streams that assert it."""
    agreement: dict[str, set[str]] = {}
    for candidate in candidates:
        agreement.setdefault(consensus_key(candidate), set()).add(_source_of(candidate))
    return agreement


def corroborating_sources(candidate: dict[str, Any], agreement: dict[str, set[str]]) -> set[str]:
    """Return the set of distinct sources that assert this candidate's exact rule."""
    return agreement.get(consensus_key(candidate), set())


def detect_consensus_and_conflicts(
    candidates: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group candidates by scope to report multi-source consensus and conflicts."""
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_scope.setdefault(scope_key(candidate), []).append(candidate)

    consensus: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for scope, group in sorted(by_scope.items()):
        variants: dict[str, dict[str, Any]] = {}
        for candidate in group:
            key = consensus_key(candidate)
            entry = variants.setdefault(
                key,
                {
                    "value": candidate.get("value"),
                    "unit": candidate.get("unit"),
                    "operator": candidate.get("operator"),
                    "direction": _direction(candidate.get("operator")),
                    "sources": set(),
                },
            )
            entry["sources"].add(_source_of(candidate))

        # Consensus: one variant asserted by 2+ distinct sources.
        for key, entry in variants.items():
            if len(entry["sources"]) >= 2:
                consensus.append(
                    {
                        "scope_key": scope,
                        "rule_object": group[0].get("rule_object"),
                        "constraint_scope": group[0].get("constraint_scope"),
                        "applies_to": group[0].get("applies_to"),
                        "value": entry["value"],
                        "unit": entry["unit"],
                        "operator": entry["operator"],
                        "agreeing_sources": sorted(entry["sources"]),
                        "source_count": len(entry["sources"]),
                    }
                )

        # Conflict: the same scope has 2+ distinct *numeric* value/direction
        # variants. We ignore non-numeric "values" (cross-references, measurement
        # prose) so the conflict report stays about genuine value disagreements a
        # human must resolve, not extraction noise.
        numeric_variants = [v for v in variants.values() if _to_float(v["value"]) is not None]
        # The unit belongs in the disagreement tuple: '2 storeys' vs '2 m' on
        # the same scope is a genuine cross-stream conflict, not one variant.
        distinct = {
            (round(_to_float(v["value"]), 3), v["direction"], unit_key(v["unit"]))
            for v in numeric_variants
        }
        if len(distinct) >= 2:
            conflicts.append(
                {
                    "scope_key": scope,
                    "rule_object": group[0].get("rule_object"),
                    "constraint_scope": group[0].get("constraint_scope"),
                    "applies_to": group[0].get("applies_to"),
                    "variants": [
                        {
                            "value": v["value"],
                            "unit": v["unit"],
                            "operator": v["operator"],
                            "direction": v["direction"],
                            "sources": sorted(v["sources"]),
                        }
                        for v in numeric_variants
                    ],
                }
            )

    return {"consensus": consensus, "conflicts": conflicts}
