"""Structured applicability parsed from candidate text fields.

Bylaw development-regulation tables are matrices: every cell is scoped by its
row (the regulation) AND its column (who it applies to — dwelling type ×
unit-count bucket), sometimes further qualified by an overlay ("Frequent
Transit Network Area Only") or a lot-size split ("Lots <= 567 m2: 40%").
Candidates carry that scope only as loose text in ``applies_to`` /
``condition``. This module derives a STRUCTURED, additive block from those
strings so the verifier can bind a claim to its table column and GIS
consumers can ask "600 m² lot, 2 units — which limit applies?".

City-neutral by construction: the unit-range grammar ("N to M units",
"N units only", "N+ units") is generic code; everything city-specific —
dwelling-type names, overlay names — arrives as VOCABULARY via the city's
normalization block (``applicability_vocabulary``). A city with no
vocabulary parses no dwelling types and the whole layer stays inert, which
is what keeps this additive for Vancouver/Calgary today.

Candidates themselves are never mutated; the block is derived, attached to
verifier outputs, and projected into GIS exports.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import to_float


# "1 to 2 Units", "(3 to 4 Units)", "5 to 6 units" — the closed range form.
_UNIT_RANGE_RE = re.compile(r"\b(\d+)\s*(?:to|-|–)\s*(\d+)\s*units?\b", re.IGNORECASE)
# "4 Units Only" — an exact-count qualifier on a cell or column.
_UNITS_ONLY_RE = re.compile(r"\b(\d+)\s*units?\s+only\b", re.IGNORECASE)
# "Lots <= 567 m2", "Lots > 567 m2" — lot-size splits inside conditional
# cells. The source PDF renders ≤ as "<", so both spellings are accepted and
# "<" is read as "<=" ONLY when the bylaw's paired branch uses ">" (the two
# branches partition the lot sizes; verified against 101.4 during gold
# hand-check).
_LOT_THRESHOLD_RE = re.compile(
    r"\blots?\s*(<=|>=|<|>|≤|≥)\s*(\d+(?:\.\d+)?)\s*m2?\b", re.IGNORECASE
)

_COMPARATOR_CANON = {"≤": "<=", "≥": ">=", "<": "<=", ">": ">"}


def vocabulary_from_normalization(normalization: dict[str, Any] | None) -> dict[str, Any]:
    """Read the city's applicability vocabulary (names only, never patterns)."""
    block = (normalization or {}).get("applicability_vocabulary") or {}
    return {
        "dwelling_types": dict(block.get("dwelling_types") or {}),
        "overlays": dict(block.get("overlays") or {}),
    }


def parse_applicability(candidate: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any] | None:
    """Derive the structured applicability block, or None when nothing parses.

    None — not an empty block — for selector-less candidates is load-bearing:
    the verifier adds ZERO new gaps for them, which is what protects every
    currently-verified rule (heights, separations, prose rules) from this
    layer entirely.
    """
    applies_to = str(candidate.get("applies_to") or "")
    condition = str(candidate.get("condition") or "")
    selectors = _parse_selectors(applies_to, vocabulary)
    qualifiers = _parse_qualifiers(f"{applies_to} ; {condition}", vocabulary)
    if not selectors and not qualifiers:
        return None
    return {
        "status": "parsed",
        "selectors": selectors,
        "qualifiers": qualifiers,
        "raw": {"applies_to": applies_to, "condition": condition},
    }


def applicability_slug(applicability: dict[str, Any] | None) -> str:
    """Deterministic short slug for GIS parameter keys, '' when none.

    'Small-Scale Multi-Unit (1 to 2 Units)' -> 'ssmu_1_2u';
    'Rowhouse' (range 1-3) -> 'rowhouse_1_3u'. Initialisms only for
    multi-word dwelling types, so single-word types stay readable.
    """
    if not applicability:
        return ""
    parts: list[str] = []
    for selector in applicability.get("selectors", []):
        dwelling = str(selector.get("dwelling_type") or "")
        if dwelling:
            words = dwelling.split("_")
            parts.append(dwelling if len(words) == 1 else "".join(word[0] for word in words))
        unit_range = selector.get("unit_range") or {}
        if unit_range.get("min") is not None and unit_range.get("max") is not None:
            parts.append(f"{unit_range['min']}_{unit_range['max']}u")
        elif unit_range.get("exact") is not None:
            parts.append(f"{unit_range['exact']}u_only")
    return "_".join(parts)


def selector_matches_text(selector: dict[str, Any], text: str, vocabulary: dict[str, Any]) -> bool:
    """True when a band header's text names this selector.

    Used by the verifier to resolve a candidate's selector to its table
    column band. Dwelling type matches via the city's alias vocabulary; a
    unit range matches when the SAME closed range appears in the header
    ("1 to 2 Units"). Both present -> both must match; the header stack of a
    band concatenates its parent headers, so "Small-Scale Multi-Unit" +
    "1 to 2 Units" land in one string.
    """
    # Header stacks join their lines with " | " ("Rowhouse | 1 to 3 | Units");
    # flatten the separators so the unit-range grammar sees "1 to 3 Units".
    lowered = " ".join(str(text or "").lower().replace("|", " ").split())
    dwelling = str(selector.get("dwelling_type") or "")
    if dwelling:
        aliases = [str(a).lower() for a in vocabulary.get("dwelling_types", {}).get(dwelling, [])]
        if not any(alias in lowered for alias in aliases):
            return False
    unit_range = selector.get("unit_range") or {}
    if unit_range.get("min") is not None and unit_range.get("max") is not None:
        for match in _UNIT_RANGE_RE.finditer(lowered):
            if int(match.group(1)) == unit_range["min"] and int(match.group(2)) == unit_range["max"]:
                return True
        return False
    if unit_range.get("exact") is not None:
        for match in _UNITS_ONLY_RE.finditer(lowered):
            if int(match.group(1)) == unit_range["exact"]:
                return True
        return False
    return bool(dwelling)


def _parse_selectors(applies_to: str, vocabulary: dict[str, Any]) -> list[dict[str, Any]]:
    # Semicolons join column unions in extracted applies_to text — a cell
    # spanning Rowhouse AND the 5-6 column arrives as
    # "Rowhouse; Small-Scale Multi-Unit (5 to 6 Units)" and must yield TWO
    # selectors, one per column. Each segment parses independently.
    selectors: list[dict[str, Any]] = []
    for segment in str(applies_to or "").split(";"):
        selector = _parse_one_selector(segment.strip(), vocabulary)
        if selector and selector not in selectors:
            selectors.append(selector)
    return selectors


def _parse_one_selector(segment: str, vocabulary: dict[str, Any]) -> dict[str, Any] | None:
    lowered = segment.lower()

    dwelling_type = None
    # Longest alias first: "small-scale multi-unit housing" must win over a
    # hypothetical shorter alias of another type contained inside it.
    candidates = sorted(
        (
            (canonical, alias)
            for canonical, aliases in vocabulary.get("dwelling_types", {}).items()
            for alias in aliases
        ),
        key=lambda pair: -len(str(pair[1])),
    )
    for canonical, alias in candidates:
        if str(alias).lower() in lowered:
            dwelling_type = canonical
            break

    unit_range: dict[str, int] | None = None
    range_match = _UNIT_RANGE_RE.search(lowered)
    if range_match:
        unit_range = {"min": int(range_match.group(1)), "max": int(range_match.group(2))}
    else:
        only_match = _UNITS_ONLY_RE.search(lowered)
        if only_match:
            unit_range = {"exact": int(only_match.group(1))}

    if not dwelling_type and not unit_range:
        return None
    selector: dict[str, Any] = {}
    if dwelling_type:
        selector["dwelling_type"] = dwelling_type
    if unit_range:
        selector["unit_range"] = unit_range
    return selector


def _parse_qualifiers(text: str, vocabulary: dict[str, Any]) -> list[dict[str, Any]]:
    lowered = text.lower()
    qualifiers: list[dict[str, Any]] = []

    for match in _LOT_THRESHOLD_RE.finditer(lowered):
        comparator = _COMPARATOR_CANON.get(match.group(1), match.group(1))
        value = to_float(match.group(2))
        if value is not None:
            qualifiers.append(
                {
                    "type": "lot_area_threshold",
                    "comparator": comparator,
                    "value": value,
                    "unit": "m2",
                    "source": "condition",
                }
            )

    for canonical, aliases in vocabulary.get("overlays", {}).items():
        if any(str(alias).lower() in lowered for alias in aliases):
            qualifiers.append({"type": "overlay", "name": canonical, "source": "condition"})

    return qualifiers
