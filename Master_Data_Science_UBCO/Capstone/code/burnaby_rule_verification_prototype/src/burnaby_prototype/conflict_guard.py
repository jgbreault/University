"""Cross-family value-collision guard (deterministic safety check).

Consensus (consensus.py) confirms that two *independent sources* assert the same
rule. But it cannot catch an error that BOTH sources make identically -- e.g.
both the table-image stream and the text stream label a ``60 %`` value as
``impervious_surface`` when it actually belongs to ``lot_coverage``. Consensus
keys on ``rule_object`` inside the scope key, so two different families never
collide there; they look like two confidently-agreed rules.

This guard is the deterministic complement. For a configured group of *sibling*
rule families on the same scale (e.g. lot_coverage and impervious_surface, both
percent-of-lot), if the same value+unit is claimed on the same scope anchor by
two or more families in the group, every colliding candidate is flagged with
``cross_family_value_collision`` and held for review. It never rejects (the value
may be right for one family) and it never verifies -- it only defers ambiguity to
a human. Purely deterministic; no scores, no embeddings.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import normalized_name, unit_key

CROSS_FAMILY_VALUE_COLLISION = "cross_family_value_collision"


from .domain_schema import to_float as _to_float


def _scope_anchor(candidate: dict[str, Any]) -> str:
    """The shared anchor two families would compete on (scope, else applies_to)."""
    return normalized_name(candidate.get("constraint_scope") or candidate.get("applies_to") or "")


def _family_lookup(config: dict[str, Any]) -> dict[str, frozenset[str]]:
    groups = config.get("verification", {}).get("cross_family_sibling_groups", [])
    lookup: dict[str, frozenset[str]] = {}
    for group in groups:
        frozen = frozenset(str(item) for item in group)
        for family in frozen:
            lookup[family] = frozen
    return lookup


def build_cross_family_index(
    candidates: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[tuple[float, str | None, str], set[str]]:
    """Map (value, unit, scope_anchor) -> set of sibling rule families claiming it."""
    lookup = _family_lookup(config)
    index: dict[tuple[float, str | None, str], set[str]] = {}
    for candidate in candidates:
        rule_object = str(candidate.get("rule_object") or "")
        if rule_object not in lookup:
            continue
        value = _to_float(candidate.get("value"))
        if value is None:
            continue
        key = (round(value, 3), unit_key(candidate.get("unit")), _scope_anchor(candidate))
        index.setdefault(key, set()).add(rule_object)
    return index


def cross_family_gaps(
    candidate: dict[str, Any],
    index: dict[tuple[float, str | None, str], set[str]],
    config: dict[str, Any],
) -> list[str]:
    """Return [cross_family_value_collision] when a sibling family claims the same value."""
    lookup = _family_lookup(config)
    rule_object = str(candidate.get("rule_object") or "")
    group = lookup.get(rule_object)
    if not group:
        return []
    value = _to_float(candidate.get("value"))
    if value is None:
        return []
    key = (round(value, 3), unit_key(candidate.get("unit")), _scope_anchor(candidate))
    families_here = index.get(key, set()) & group
    if len(families_here) >= 2:
        return [CROSS_FAMILY_VALUE_COLLISION]
    return []
