"""City-configurable normalization literals for candidate cleanup.

Background
----------
Before the verifier runs its support checks it canonicalizes each candidate and
applies a handful of deterministic, jurisdiction-specific rewrites (for example
"1 to 6 dwelling units" -> a maximum of 6 for GIS, or labelling a sprinkler
requirement's ``applies_to``).  Historically those rewrites were hardcoded
Burnaby string literals living inside ``verification.py`` and ``zihao_adapter``.

That made the *logic* hard to reuse for another city even though the *control
flow* (which guards fire, in which order) is generic.  This module separates the
two concerns:

* The control flow / guards stay in the verifier and adapter.
* The literal strings and patterns move into a ``normalization`` config block.

``DEFAULT_NORMALIZATION`` holds exactly today's Burnaby literals and is the
single source of truth for them: it is used whenever a caller passes
``config=None`` or a config without a ``normalization`` block. Burnaby
intentionally relies on this default (its ``configs/burnaby_r1.json`` has no
``normalization`` block, so there is no second copy to keep in sync), which keeps
the adapter tests and Burnaby output byte-for-byte unchanged. Another city makes
itself reusable by adding its OWN ``normalization`` block to its config, which
overrides this default — see ``NormalizationConfigTests`` in the test suite.

The helper functions are deliberately small and pure so they can be unit tested
in isolation.  They reuse :func:`domain_schema.matches_text_pattern` so the
``all_terms``/``any_terms``/``not_terms`` matching semantics stay consistent
with the rest of the config-driven verifier.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import matches_text_pattern


# The literal Burnaby normalization rules -- the single source of truth for the
# defaults. Burnaby's config has no ``normalization`` block and runs on this; a
# new city overrides by supplying its own block. (There is no duplicate copy in
# configs/burnaby_r1.json to keep in sync.)
DEFAULT_NORMALIZATION: dict[str, Any] = {
    # applies_to label rewrites keyed off focused candidate text.  Each entry is
    # tried in order against the focused text for the listed rule_objects; the
    # first match wins (the verifier keeps the elif-chain ordering).
    "applies_to_hints": [
        {
            "rule_objects": ["height", "storeys"],
            "all_terms": ["rear principal"],
            "label": "Rear Principal Buildings",
        },
        {
            "rule_objects": ["height", "storeys"],
            "all_terms": ["front principal"],
            "label": "Front Principal Buildings",
        },
        {
            "rule_objects": ["height", "storeys"],
            "all_terms": ["accessory building"],
            "label": "Accessory Buildings",
        },
        {
            "rule_objects": ["setback"],
            "all_terms": ["all building"],
            "label": "All Buildings",
        },
        {
            "rule_objects": ["building_separation"],
            "all_terms": ["between rear principals"],
            "label": "Rear Principal Buildings",
        },
        {
            "rule_objects": ["building_separation"],
            "any_terms": [
                "between front & rear principals",
                "between front and rear principals",
            ],
            "label": "Front and Rear Principal Buildings",
        },
        {
            "rule_objects": ["building_separation"],
            "all_terms": ["between all other buildings"],
            "label": "All Other Buildings",
        },
    ],
    # Setback scope/condition rewrites.  These read the candidate's own
    # scope/condition fields plus focused text; the verifier supplies the
    # ordering and the interior-rear-yard "not accessory" guard via not_terms.
    "scope_hints": [
        {
            "rule_objects": ["setback"],
            "match": "scope_or_condition",
            "any_terms": ["flanking"],
            "constraint_scope": "street_yard_flanking",
            "condition": "flanking street yard",
        },
        {
            "rule_objects": ["setback"],
            "match": "scope_or_condition",
            "any_terms": ["front"],
            "constraint_scope": "street_yard_front",
            "condition": "front street yard",
        },
        {
            "rule_objects": ["setback"],
            "match": "focused",
            "all_terms": ["street yard", "flanking"],
            "not_terms": ["front"],
            "constraint_scope": "street_yard_flanking",
            "condition": "flanking street yard",
        },
        {
            "rule_objects": ["setback"],
            "match": "focused",
            "all_terms": ["street yard", "front"],
            "constraint_scope": "street_yard_front",
            "condition": "front street yard",
        },
        {
            "rule_objects": ["setback"],
            "match": "focused",
            "all_terms": ["lane yard"],
            "constraint_scope": "lane_yard",
        },
        {
            # Interior rear yard for principal buildings (accessory has its own
            # 1.5 m value, so exclude it via not_terms).
            "rule_objects": ["setback"],
            "match": "focused",
            "all_terms": ["interior rear yard"],
            "not_terms": ["accessory"],
            "constraint_scope": "interior_rear_yard",
            "applies_to": "Rear Principal Buildings",
        },
        {
            # End-unit interior side yard. The original code accepted either an
            # explicit "interior"+"side" or the table heading "minimum lot line
            # setbacks"; two entries express that OR.
            "rule_objects": ["setback"],
            "match": "focused",
            "all_terms": ["end unit", "interior", "side"],
            "constraint_scope": "interior_side_yard",
            "condition": "end unit lots",
        },
        {
            "rule_objects": ["setback"],
            "match": "focused",
            "all_terms": ["end unit", "minimum lot line setbacks"],
            "constraint_scope": "interior_side_yard",
            "condition": "end unit lots",
        },
    ],
    # Distance-threshold parse (the automatic-sprinkler rewrite).
    "distance_rewrites": [
        {
            "rule_objects": ["automatic_sprinkler"],
            "regex": r"more than\s+(\d+(?:\.\d+)?)\s*m",
            "operator": ">",
            "unit": "m",
            "constraint_type": "required",
            "applies_to_template": "Dwelling units more than {value} m from a street lot line",
            "condition": "distance from lot line abutting a street",
        }
    ],
    # "X to Y units" range -> max rewrite.
    "range_rewrites": [
        {
            "rule_objects": ["dwelling_units"],
            # Decimal-boundary guards stop the "X to Y" range from latching onto
            # a dotted section number such as "...101.5 to 6..." and rewriting the
            # dwelling-unit value to a clause reference.
            "pattern": r"(?<!\d\.)\b\d+\s+to\s+\d+\b(?!\.\d)",
            "take": "max",
            "operator": "<=",
            "unit": "units",
            "constraint_type": "maximum",
            "constraint_scope": "lot",
            "applies_to": "lot",
        }
    ],
    # Default conditions/scopes (heritage exception, fire access corridor).
    "condition_defaults": [
        {
            "rule_objects": ["lot_coverage", "impervious_surface", "setback"],
            "all_terms": ["heritage"],
            "condition": "heritage exception",
        },
        {
            "rule_objects": ["fire_access_corridor"],
            "all_terms": ["fire access corridor"],
            "constraint_scope": "corridor_width",
            "condition": "paved or gravel fire access corridor",
        },
    ],
    # Extra words treated as generic (non-distinctive) for applies_to overlap.
    "generic_applies_to_extra_words": ["r1"],
    # Words that, on their own, make a condition non-material (a heading label).
    "non_material_condition_words": [
        "small",
        "scale",
        "multi",
        "unit",
        "housing",
        "district",
        "r1",
    ],
    # Applicability vocabulary: NAMES only, never patterns. The unit-range
    # grammar ("1 to 2 units", "4 units only") is generic code in
    # applicability.py; the city declares which dwelling-type and overlay
    # names exist in its bylaw. A city with no vocabulary parses no
    # selectors and the matrix-applicability layer stays inert.
    "applicability_vocabulary": {
        "dwelling_types": {
            "rowhouse": ["rowhouse"],
            "small_scale_multi_unit": [
                "small-scale multi-unit",
                "small scale multi unit",
                "small-scale multi unit",
            ],
        },
        "overlays": {
            "frequent_transit_network_area": ["frequent transit network area"],
            "community_heritage_register": ["community heritage register"],
        },
    },
}


# A truly neutral normalization block: no dwelling-type vocabulary, no zone
# words, no Burnaby applies_to/scope hints. A NON-Burnaby city that ships no
# normalization block of its own falls back to THIS, never to Burnaby's
# literals — so Burnaby's 'r1' generic word and its applicability_vocabulary
# (Rowhouse/SSMU/FTN) can no longer silently apply to another city and flip
# that city's candidate from review to verified. Confirmed-leak fix.
EMPTY_NORMALIZATION: dict[str, Any] = {
    "applies_to_hints": [],
    "scope_hints": [],
    "distance_rewrites": [],
    "range_rewrites": [],
    "condition_defaults": [],
    "generic_applies_to_extra_words": [],
    "non_material_condition_words": [],
    "applicability_vocabulary": {"dwelling_types": {}, "overlays": {}},
}


def _is_burnaby_config(config: dict[str, Any] | None) -> bool:
    """True only for the config the DEFAULT_NORMALIZATION literals belong to.

    DEFAULT_NORMALIZATION is Burnaby R1's vocabulary; it is the implicit block
    for Burnaby (whose config intentionally omits ``normalization``) and for
    ``config=None`` legacy/test callers. Any other named city must declare its
    own block or get the neutral EMPTY_NORMALIZATION — never Burnaby's.
    """
    if config is None:
        return True
    city = str(config.get("city") or "").strip().lower()
    return city in {"", "burnaby"}


def get_normalization(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return the active normalization block.

    Precedence: an explicit ``normalization`` block on the config wins; a
    Burnaby (or None/legacy) config falls back to :data:`DEFAULT_NORMALIZATION`
    (its own literals); any OTHER city lacking a block gets the neutral
    :data:`EMPTY_NORMALIZATION` so Burnaby vocabulary never leaks across cities.
    """
    if config and config.get("normalization"):
        return config["normalization"]
    if _is_burnaby_config(config):
        return DEFAULT_NORMALIZATION
    return EMPTY_NORMALIZATION


def _rule_object_matches(hint: dict[str, Any], rule_object: Any) -> bool:
    """Return True when the hint targets this rule_object (empty list = any)."""
    rule_objects = hint.get("rule_objects")
    if not rule_objects:
        return True
    return str(rule_object or "") in {str(item) for item in rule_objects}


def applies_to_hint(rule_object: Any, focused_text: str, hints: list[dict[str, Any]]) -> str | None:
    """Return the first matching applies_to label for ``rule_object``.

    Tries each hint in order against ``focused_text`` so the caller can keep the
    original first-match-wins ordering of the elif chain.  ``None`` means no hint
    applied and the caller should leave applies_to untouched.
    """
    for hint in hints or []:
        if not _rule_object_matches(hint, rule_object):
            continue
        if matches_text_pattern(focused_text, hint):
            return hint.get("label")
    return None


def scope_hint(
    rule_object: Any,
    scope_text: str,
    focused_text: str,
    scope_hints: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first matching setback scope/condition rewrite.

    ``match`` selects which text the pattern is tested against:

    * ``"scope_or_condition"`` -> the candidate's existing scope+condition text;
    * ``"focused"`` -> the focused candidate/evidence text.

    Returns a dict with ``constraint_scope`` and optionally ``condition``; the
    caller applies it (and decides whether ``condition`` is a default that must
    not overwrite an existing value).
    """
    for hint in scope_hints or []:
        if not _rule_object_matches(hint, rule_object):
            continue
        target = scope_text if hint.get("match") == "scope_or_condition" else focused_text
        if matches_text_pattern(target, hint):
            result: dict[str, Any] = {"constraint_scope": hint.get("constraint_scope")}
            if "condition" in hint:
                result["condition"] = hint.get("condition")
            if "applies_to" in hint:
                result["applies_to"] = hint.get("applies_to")
            return result
    return None


# Canonical setback scope tokens (mirror geometry_operator.AXIS_BY_SCOPE keys).
# A setback only becomes a drawable GIS constraint (gis_felt_export geometry_target)
# when its constraint_scope is one of these.
CANONICAL_SETBACK_SCOPES = frozenset(
    {"street_yard_front", "street_yard_flanking", "lane_yard", "interior_rear_yard", "interior_side_yard"}
)


def universal_setback_scope(text: str) -> str | None:
    """Map the UNIVERSAL Canadian lot-line setback vocabulary to a canonical scope.

    Zoning setbacks across Canadian municipalities reference front/side/rear/lane
    lot lines with near-universal wording ("minimum setback from a rear property
    line", "side yard", "shared with a street" for a corner/flanking lot line,
    "from a lane"). This is bylaw-agnostic terminology, so deriving the canonical
    axis scope here lets gis_felt_export produce a geometry_target for ANY city's
    setbacks, not just Burnaby's (whose city-specific "street yard"/"end unit"
    phrasing lives in DEFAULT_NORMALIZATION). Order matters: the more specific
    flanking/corner-street and explicit lot-line cases come before plain side.
    Returns None when the lot line cannot be identified (never guesses).
    """
    t = re.sub(r"\s+", " ", str(text or "")).lower()
    if not t:
        return None
    # A lot-line noun must be present so we only fire on genuine setback context.
    _NOUN = ("property line", "lot line", "yard", "setback")
    has_noun = any(noun in t for noun in _NOUN)
    # Corner / flanking: a side lot line shared with a street.
    if "flanking" in t or (
        "side" in t and ("shared with a street" in t or "abutting a street" in t)
    ) or ("corner" in t and "street" in t and "side" in t and "rear" not in t and "front" not in t):
        return "street_yard_flanking"
    if has_noun and "front" in t:
        return "street_yard_front"
    # Lane requires explicit lane-setback wording -- "laned parcel" (a parcel
    # type) must NOT be read as a lane setback, so we never match bare "lane".
    if any(
        phrase in t
        for phrase in ("lane property line", "lane lot line", "from a lane", "abutting a lane", "lane yard", "laneway")
    ):
        return "lane_yard"
    if has_noun and "rear" in t:
        return "interior_rear_yard"
    if has_noun and ("side" in t or "interior" in t):
        return "interior_side_yard"
    return None


def parse_distance_rewrite(rule_object: Any, text: str, specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Parse a distance threshold such as "more than 4.5 m" into rule fields.

    Returns a dict of the fields to set (value/unit/operator/constraint_type/
    applies_to/condition) when the regex matches, otherwise ``None``.  The
    ``applies_to`` is rendered from ``applies_to_template`` using ``{value}``.
    """
    for spec in specs or []:
        if not _rule_object_matches(spec, rule_object):
            continue
        match = re.search(spec["regex"], text)
        if not match:
            continue
        number = float(match.group(1))
        value: float | int = int(number) if number.is_integer() else number
        result: dict[str, Any] = {
            "value": value,
            "unit": spec.get("unit"),
            "operator": spec.get("operator"),
            "constraint_type": spec.get("constraint_type"),
        }
        template = spec.get("applies_to_template")
        if template:
            result["applies_to"] = template.format(value=value)
        if "condition" in spec:
            result["condition"] = spec.get("condition")
        return result
    return None


def range_upper_bound_rewrite(rule_object: Any, text: str, specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the upper-bound rewrite for an "X to Y" range when ``text`` has one.

    Only the literals/pattern live here; the caller still owns the guard that
    this rewrite fires only for candidates that already claim a range/maximum.
    Returns a dict of fields (value/operator/constraint_type/unit/
    constraint_scope/applies_to) or ``None`` when no range is present.
    """
    for spec in specs or []:
        if not _rule_object_matches(spec, rule_object):
            continue
        match = re.search(spec["pattern"], text)
        if not match:
            continue
        # Compute the bound over the MATCHED range only, never the whole text
        # blob: real Burnaby evidence contains '... 101.5.1 All Dwelling Units
        # ... 4 to 6 Units ...' — a whole-text max() would pick the section
        # number 101.5 as the "upper bound" instead of 6.
        numbers = [float(token) for token in re.findall(r"\d+(?:\.\d+)?", match.group(0).replace(",", ""))]
        if not numbers:
            continue
        chosen = max(numbers) if spec.get("take", "max") == "max" else min(numbers)
        value: float | int = int(chosen) if chosen.is_integer() else chosen
        return {
            "value": value,
            "operator": spec.get("operator"),
            "constraint_type": spec.get("constraint_type"),
            "unit": spec.get("unit"),
            "constraint_scope": spec.get("constraint_scope"),
            "applies_to": spec.get("applies_to"),
        }
    return None


def condition_default(rule_object: Any, text: str, defaults: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return default scope/condition fields for the first matching default.

    Used for the heritage-exception and fire-access-corridor defaults.  Returns
    a dict that may carry ``condition`` and/or ``constraint_scope``; the caller
    applies these as defaults (only when the candidate has no existing value).
    """
    for default in defaults or []:
        if not _rule_object_matches(default, rule_object):
            continue
        if matches_text_pattern(text, default):
            result: dict[str, Any] = {}
            if "condition" in default:
                result["condition"] = default.get("condition")
            if "constraint_scope" in default:
                result["constraint_scope"] = default.get("constraint_scope")
            return result
    return None


def generic_applies_to_extra_words(norm: dict[str, Any]) -> set[str]:
    """Return extra words to treat as generic (non-distinctive) for this city."""
    return {str(word).lower() for word in norm.get("generic_applies_to_extra_words", [])}


def non_material_condition_words(norm: dict[str, Any]) -> set[str] | None:
    """Return the word set that, alone, marks a condition as non-material.

    Returns None when the key is ABSENT (consumer falls back to the Burnaby
    defaults) versus an empty set when a city explicitly configures [] —
    previously both were falsy, so a city could never truly opt out: the
    Burnaby vocabulary silently re-enabled itself through the `or default`
    fallback in text_span_proof.
    """
    if "non_material_condition_words" not in norm:
        return None
    return {str(word).lower() for word in norm.get("non_material_condition_words", [])}


def rule_object_text_cue_extras(norm: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Per-city ADDITIVE rule-object support phrases, keyed by family.

    Example (a future city whose bylaw phrases setbacks as plain prose):
    ``{"setback": ["from the ultimate rear property line", "property line"]}``.
    Same trust level as ``known_aliases`` — deliberate, reviewed config. The
    extras can only flip ``rule_object_supported`` (a review-tier gap) from
    False to True for the configured city; they never enter the refutation
    vocabulary and never touch the critical value/unit gates. Absent or empty
    config means exactly the current shared behavior.
    """
    extras = norm.get("rule_object_text_cue_extras", {}) or {}
    return {
        str(family): tuple(str(phrase).lower() for phrase in (phrases or []) if str(phrase).strip())
        for family, phrases in extras.items()
    }


def material_condition_cue_extras(norm: dict[str, Any]) -> frozenset[str]:
    """Per-city ADDITIVE material-condition cue words.

    Fail-closed by construction: extra cues make MORE conditions count as
    material, which can only push that city's own candidates toward review
    (``text_condition_not_supported``), never toward verification.
    """
    return frozenset(
        str(word).lower() for word in norm.get("material_condition_cue_extras", []) if str(word).strip()
    )


def unit_rewrite(
    rule_object: Any,
    unit_text: str,
    focused_text: str,
    specs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a per-city unit rewrite for verbatim jurisdiction phrasing.

    This is the activation lever for city wordings like Vancouver's
    "multiplied by the site area" -> unit "fsr" (optionally also re-typing the
    family via ``set_rule_object``). Safe because the rewrite runs in
    normalization, BEFORE verification: the rewritten unit must still pass
    contains_unit / unit-compatibility against the cited evidence, so a wrong
    rewrite cannot verify — it can only fail support checks.
    """
    for spec in specs or []:
        if not _rule_object_matches(spec, rule_object):
            continue
        target = focused_text if spec.get("match") == "focused" else unit_text
        if not matches_text_pattern(target, spec):
            continue
        result: dict[str, Any] = {"unit": spec.get("unit")}
        if spec.get("set_rule_object"):
            result["rule_object"] = spec["set_rule_object"]
        return result
    return None
