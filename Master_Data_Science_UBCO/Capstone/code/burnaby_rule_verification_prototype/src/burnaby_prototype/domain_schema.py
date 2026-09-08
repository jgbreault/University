"""Shared zoning-domain names and normalization helpers.

This module is the small vocabulary layer for the verifier.  The goal is to
keep city-specific extraction cleanup out of the core decision logic while
still giving every module the same names for rule objects, units, and generic
text cues.
"""

from __future__ import annotations

import re
from typing import Any


UNIT_ALIASES = {
    "m": ["m", "metre", "meter", "metres", "meters"],
    # 'sq. m' variants: Vancouver writes areal units as '186 sq. m'.
    "m2": ["m2", "m 2", "m²", "m^2", "square metre", "square meter", "square metres", "square meters", "sq. m", "sq.m", "sq m", "sqm", "square m"],
    # Dimensionless density ratio (FSR/FAR). Deliberately NO 'far' alias: these
    # aliases feed table_natural_logic._visible_units, where a word-bounded
    # 'far' would match ordinary prose ("as far as") and falsely REFUTE other
    # units' table proofs — a correct rule would hard-reject. The FAR spelling
    # lives in RULE_OBJECT_ALIASES instead (exact-equality on the rule_object
    # FIELD, never a prose scan).
    "fsr": ["fsr", "floor space ratio", "floor area ratio"],
    # 'per cent' (spaced) is Calgary's official spelling.
    "%": ["%", "percent", "percentage", "per cent"],
    "storeys": ["storey", "storeys", "stories", "story"],
    "units": ["unit", "units", "dwelling unit", "dwelling units"],
}

RULE_OBJECT_ALLOWED_UNITS = {
    "height": {"m"},
    "setback": {"m"},
    "building_separation": {"m"},
    "automatic_sprinkler": {"m"},
    "fire_access_corridor": {"m"},
    "lot_area": {"m2"},
    # floor_area is m2 ONLY — never add '%'. Bylaws also contain floor-area
    # EXCLUSION clauses ('... does not exceed 8% of the floor area') whose
    # wording matches this family; the unit-compatibility gate is what keeps
    # those percentage clauses from ever verifying as a floor-area cap.
    "floor_area": {"m2"},
    # Dimensionless ratio family (FSR/FAR density caps). Never add '%' (a
    # coverage percent is not an FSR) or 'm2' (an absolute floor-area cap is
    # floor_area). City-specific phrasings such as Vancouver's "multiplied by
    # the site area" stay OUT of the shared vocabulary: they hard-reject on
    # unit incompatibility until a city maps them via its own normalization
    # unit_rewrites — capability without silent activation.
    "floor_space_ratio": {"fsr"},
    "lot_coverage": {"%"},
    "impervious_surface": {"%"},
    "storeys": {"storeys"},
    "dwelling_units": {"units"},
}

NUMERIC_RULE_OBJECTS = set(RULE_OBJECT_ALLOWED_UNITS)

RULE_OBJECT_ALIASES = {
    "permitted_use": "permitted_use",
    "accessory_use": "accessory_use",
    "building_height": "height",
    "height": "height",
    "building_storeys": "storeys",
    "storeys": "storeys",
    "stories": "storeys",
    "lot_coverage": "lot_coverage",
    "impervious_surfaces": "impervious_surface",
    "impervious_surface": "impervious_surface",
    "lot_area": "lot_area",
    "floor_area": "floor_area",
    "gross_floor_area": "floor_area",
    "floor_space_ratio": "floor_space_ratio",
    "floor_area_ratio": "floor_space_ratio",
    "fsr": "floor_space_ratio",
    # 'far' is safe HERE (exact-equality lookup on the normalized rule_object
    # field) but must never become a unit alias or prose cue — substring/word
    # scans would hit "welfare", "farm", "as far as".
    "far": "floor_space_ratio",
    "permitted_dwelling_units": "dwelling_units",
    "dwelling_units": "dwelling_units",
    "setback": "setback",
    "separation": "building_separation",
    "building_separation": "building_separation",
    "automatic_sprinkler": "automatic_sprinkler",
    "fire_access_corridor": "fire_access_corridor",
}

# These are the rule families the current verifier can validate.  Some aliases
# such as accessory_use are recognized for routing/reporting but intentionally
# stay outside this set until there is a support contract for them.
KNOWN_RULE_OBJECTS = set(RULE_OBJECT_ALLOWED_UNITS) | {"permitted_use"}

# Geometry-facing rule families: those a GIS engine can draw as a buildable
# constraint (setbacks, height/storeys, separation, coverage). These are marked
# gis_relevance="direct"; everything else (e.g. floor_area, dwelling_units,
# permitted_use) is "context". This is the single, source-agnostic definition
# shared by every extraction lane (native and the legacy pipeline-5 adapter) so
# the GIS contract is classified identically regardless of how a rule was
# extracted. gis_felt_export still gates gis_ready on a mapped geometry_target +
# numeric value, so this label alone never makes a rule executable.
GIS_DIRECT_RULE_OBJECTS = frozenset(
    {"setback", "building_separation", "height", "storeys", "lot_coverage", "impervious_surface"}
)


def gis_relevance_for_rule_object(rule_object: Any) -> str:
    """Return 'direct' for geometry-facing families, else 'context'."""
    return "direct" if str(rule_object or "") in GIS_DIRECT_RULE_OBJECTS else "context"

SUPPORTED_OPERATORS = {
    "<=",
    "≤",
    ">=",
    "≥",
    ">",
    "<",
    "=",
    "allowed",
    "permitted",
    "required",
    "range",
    "max",
    "maximum",
    "min",
    "minimum",
    "not_exceed",
    "at_least",
}

# Words too generic to be a distinctive applies_to target. City-specific zone
# labels (e.g. Burnaby's "r1") are NOT listed here; a city re-supplies them via
# its normalization config's ``generic_applies_to_extra_words`` so this shared
# constant stays jurisdiction-neutral.
GENERIC_APPLIES_TO_WORDS = {
    "all",
    "building",
    "buildings",
    "district",
    "dwelling",
    "dwellings",
    "lot",
    "unit",
    "units",
}

GENERIC_TABLE_COLUMN_CONDITION_WORDS = {
    "accessory",
    "attached",
    "basement",
    "between",
    "detached",
    "except",
    "exception",
    "exterior",
    "flat",
    "flanking",
    "front",
    "inclusive",
    "interior",
    "lane",
    "lot",
    "maximum",
    "minimum",
    "other",
    "principal",
    "rear",
    "roof",
    "side",
    "sloping",
    "standard",
    "storey",
    "street",
    "value",
    "yard",
}

TEXT_RULE_OBJECT_PATTERNS = [
    ("fire_access_corridor", (("fire access corridor",), ("fire", "corridor"))),
    ("lot_coverage", (("lot coverage",), ("coverage",))),
    ("impervious_surface", (("impervious",),)),
    # floor_space_ratio before floor_area: 'floor area ratio' contains
    # 'floor area' and must claim the ratio family (first match wins).
    ("floor_space_ratio", (("floor space ratio",), ("floor area ratio",), ("fsr",))),
    # floor_area before lot_area: 'floor area' text must claim the floor-area
    # family, never fall through to a bare-'area' style lot_area match.
    ("floor_area", (("floor area",), ("gross floor",))),
    ("lot_area", (("lot area",),)),
    ("dwelling_units", (("dwelling unit",), ("dwelling", "unit"))),
    ("permitted_use", (("permitted use",),)),
    # 'separation' alone is not enough: '1.0 metres ... between retaining
    # walls' verified as building_separation (live Calgary P9 leak). The
    # separation's subject must be a building-like entity.
    ("building_separation", (("separation", "building"), ("separation", "dwelling"), ("separation", "suite"))),
    ("setback", (("setback",), ("yard",))),
    ("storeys", (("storey",), ("storeys",), ("story",))),
    ("height", (("height",),)),
]

PLAIN_ONLY_RULE_OBJECT_PATTERNS = [
    ("automatic_sprinkler", (("automatic sprinkler",), ("sprinkler",))),
]


def normalized_name(value: Any) -> str:
    """Return a lowercase snake-style identifier for extracted text."""
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def plain_text(value: Any) -> str:
    """Return normalized text with spaces, useful for phrase matching."""
    return normalized_name(value).replace("_", " ")


def stem(word: str) -> str:
    """Very small plural normalizer used for transparent word-overlap checks."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "ous")):
        return word[:-1]
    return word


def text_words(text: str) -> set[str]:
    """Return normalized words for deterministic overlap checks."""
    return {stem(word) for word in re.findall(r"[a-z0-9]+", text.lower())}


def unit_key(unit: Any) -> str | None:
    """Canonicalize unit variants such as square metres -> m2."""
    if unit in (None, "", "null"):
        return None
    text = str(unit).lower().strip()
    if text in {"%", "percent", "percentage"}:
        return "%"
    for key, aliases in UNIT_ALIASES.items():
        if text == key or text in aliases:
            return key
    return text


def looks_like_section_reference(value: Any) -> bool:
    """Detect bylaw cross-references such as 101.5.2 or 6.8A."""
    text = str(value or "").strip()
    if not text:
        return False
    pieces = [piece.strip() for piece in re.split(r"[,;/]", text) if piece.strip()]
    if not pieces:
        return False
    return all(re.fullmatch(r"\d+(?:\.\d+)+[a-z]?", piece, flags=re.IGNORECASE) for piece in pieces)


def token_visible(text: str, token: str) -> bool:
    """Boundary-aware containment check for candidate value tokens.

    This is the numeric discipline behind ``value_not_found_in_evidence`` (a
    hard-rejection gap, i.e. part of the false_verified=0 backbone), so it must
    not be a plain substring test: a candidate value '5' must never be "found"
    inside '7.5', '50', or '1.5'. Numeric tokens are matched with digit-and-
    decimal lookarounds; non-numeric tokens (e.g. a zone label) use
    alphanumeric boundaries so 'r1' is not found inside 'r12'. Matching is
    case-insensitive. Commas are NOT stripped here — callers strip comma
    grouping from both sides first when it can occur.
    """
    token = str(token or "").strip().lower()
    if not token:
        return False
    if re.search(r"\d", token):
        lowered = text.lower()
        for match in re.finditer(rf"(?<![\d.]){re.escape(token)}(?!\.?\d)", lowered):
            if numeric_occurrence_is_reference(lowered, match.start(), match.end()):
                continue
            return True
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text.lower()))


# Unit words that may legitimately follow a parenthesized number — '(3.0)
# metres' is a measurement, not a reference.
_UNIT_AFTER_PAREN_RE = re.compile(
    r"^\s*(?:square\s+)?(?:metres?|meters?|m2|m²|per\s?cent|percent|%|storeys?|stories|m)\b"
)
# 'section 3.1' / 'subsection 3.1' / 'clause 3.1' — dotted references named in
# prose rather than parenthesized.
_SECTION_WORD_BEFORE_RE = re.compile(r"(?:sub)?sections?\s*$|clauses?\s*$|\bs\.\s*$")


def numeric_occurrence_is_reference(lowered: str, start: int, end: int) -> bool:
    """True when this numeric occurrence is a citation/code, not a measurement.

    Three shapes, all found by live leaks or external review:
    1. paren-wrapped bare number — 'required in subsection (3.1)' (the Calgary
       352(3.2) leak) — UNLESS a unit word follows the ')' ('(3.0) metres' is
       a real measurement);
    2. a number directly followed by a letter+digit tail — amendment codes
       like '10P2019' must never satisfy value 10;
    3. a dotted number preceded by 'section/subsection/clause/s.' — 'see
       section 3.1' states a location, not 3.1 of anything.
    """
    before = lowered[start - 1] if start > 0 else ""
    after = lowered[end:end + 1]
    if before == "(" and after == ")" and not _UNIT_AFTER_PAREN_RE.match(lowered[end + 1:]):
        return True
    if re.match(r"[a-z]\d", lowered[end:end + 2]):
        return True
    if _SECTION_WORD_BEFORE_RE.search(lowered[max(0, start - 14):start]):
        return True
    return False


# Measurement words that can be glued to a number. 'degrees' deliberately
# belongs to NO rule family: angles appear in definitions ('intersect at an
# angle not exceeding 135 degrees') and must never satisfy a count or a
# dimension value.
_MEASURE_AFTER_VALUE_RE = re.compile(
    r"^\s*(?P<word>degrees?|°|(?:square\s+)?met(?:re|er)s?|m2|m²|sq\.?\s?m\b|per\s?cent|percent|%|"
    r"hectares?|acres?|sq\.?\s?ft\b|feet|ft\b|storeys?|stories|mm\b|cm\b|km\b|m\b)"
)


def separation_subject_grounded(text: str) -> bool:
    """True when a 'separation' mention shares its SENTENCE with a building-like
    subject (building/dwelling/suite).

    Whole-window AND was not enough: a synthetic evidence bundle concatenated
    §1119 ('A minimum horizontal separation of 1.0 metres ... between retaining
    walls') with §1118 ('... buildings, fences, finished grade ...') and the
    two words satisfied the pattern from different sentences, promoting a
    retaining-wall rule as building_separation. Sentence bounds use the shared
    period discipline — ``\\.(?!\\d)`` — so internal decimals ('1.0 metres')
    do not end a sentence early.
    """
    lowered = str(text or "").lower()
    for match in re.finditer(r"separation", lowered):
        start = 0
        for period in re.finditer(r"\.(?!\d)", lowered[: match.start()]):
            start = period.end()
        tail = re.search(r"\.(?!\d)", lowered[match.end():])
        end = match.end() + tail.end() if tail else len(lowered)
        if any(word in lowered[start:end] for word in ("building", "dwelling", "suite")):
            return True
    return False


def value_bound_to_foreign_measure(text: str, value: Any, rule_object: Any) -> bool:
    """True when every visible occurrence of ``value`` is glued to a unit that
    cannot belong to ``rule_object``'s family.

    The live leak (Calgary P9): a unit-less ``dwelling_units <= 135``
    candidate whose only '135' in evidence is 'intersect at an angle not
    exceeding 135 degrees.' — the number is real but MEASURES something else,
    and with no unit claim on the candidate no other gate could see the
    mismatch. Only occurrences glued to a foreign measure are disqualified:
    '135 dwelling units' (no glued measure word) and '10.0 metres' under a
    height rule (family unit) both stay visible. Callers apply this only when
    the candidate claims NO unit — claimed units are covered by the
    unit-visibility and unit-compatibility gates.
    """
    allowed = RULE_OBJECT_ALLOWED_UNITS.get(str(rule_object or ""))
    if allowed is None:
        return False
    tokens = re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    if not tokens:
        return False
    lowered = str(text or "").lower().replace(",", "")
    token = tokens[0].lower()
    saw_occurrence = False
    for match in re.finditer(rf"(?<![\d.]){re.escape(token)}(?!\.?\d)", lowered):
        if numeric_occurrence_is_reference(lowered, match.start(), match.end()):
            continue
        saw_occurrence = True
        measure = _MEASURE_AFTER_VALUE_RE.match(lowered[match.end():])
        if not measure:
            return False
        if unit_key(measure.group("word")) in allowed:
            return False
    return saw_occurrence


def unit_visible(text: str, unit: Any) -> bool:
    """Return True when the unit, in any accepted spelling, is visible in text.

    The unit is canonicalized first (unit_key) so synonym spellings such as
    'metres' or 'm^2' search the shared alias table instead of only their
    literal extracted spelling — previously a correct rule whose unit arrived
    as 'metres' could hard-reject because evidence wrote '7.5 m'. Alias edges
    that are alphanumeric require word boundaries ('m' must not match inside
    'maximum'); symbol edges do not ('%' must match inside '45%').
    """
    key = unit_key(unit)
    if key is None:
        return False
    lowered = text.lower()
    for alias in {key, *UNIT_ALIASES.get(key, [str(unit).lower().strip()])}:
        if not alias:
            continue
        prefix = r"(?<![a-z0-9])" if alias[:1].isalnum() else ""
        suffix = r"(?![a-z0-9])" if alias[-1:].isalnum() else ""
        if re.search(prefix + re.escape(alias) + suffix, lowered):
            return True
    return False


# Canonical legal exception cues. This single constant guards the
# bundle-promotion path: any evidence text containing one of these words may
# encode an exception/override ("except", "notwithstanding", a Section 219
# "covenant", ...) that changes the legal meaning of a numeric limit, so the
# advisory layer (evidence_intelligence, evidence_rerun, review_router,
# semantic_review) must flag it and apply_bundle_promotions must refuse to
# promote. Keep it a frozenset so callers can use both `cue in text` loops and
# set intersection with text_words().
# Wording that signals an exception/exclusion/override is in play. A candidate
# whose evidence carries any of these with NO resolved exception field must be
# held for review: exclusion criteria read like rules ('the ceiling height of
# the total area being excluded does not exceed 3.1 m' — a porch-exclusion
# test, not a height cap; caught live as a P9-fed false verify). The exclud*
# family was the documented fail-open until it bit.
LEGAL_EXCEPTION_CUES = frozenset(
    {"except", "exception", "notwithstanding", "unless", "covenant", "excluding", "excluded", "exclusion"}
)

# "Unless otherwise referenced in subsections (3.1) and (3.2), a minimum
# separation of 5.0 metres is required" (Calgary 1P2007) states the operative
# DEFAULT rule and names where its overrides live — the exception is resolved
# by the clause itself, so its 'unless' must not hold the default for review.
# The preposition is REQUIRED: a bare "unless otherwise specified" (Burnaby
# lane-yard row) names no override target, leaves the override universe open,
# and stays held. Discretionary escapes ("unless approved by the Director")
# also keep their cue.
RESOLVED_EXCEPTION_PREAMBLE_RE = re.compile(
    r"unless\s+otherwise\s+(?:referenced|provided|specified|stated|noted|indicated)\s+(?:in|by|under|on)\b",
    re.IGNORECASE,
)


def unresolved_exception_cues(text: Any) -> set[str]:
    """Return exception cue words that remain after resolved preambles.

    Single source for "does this text carry unresolved exception wording":
    the verify-path hold (proof_trace, text_span_proof), the bundle-promotion
    blockers (evidence_rerun), and the advisory layer (evidence_intelligence,
    semantic_review, review_router) all answer it here so their vocabularies
    cannot drift. 'the ceiling height, excluding roof structure, of the total
    area being excluded does not exceed 3.1 m' keeps its cues (an exclusion
    criterion that reads like a height cap — a live P9-fed false verify);
    'unless otherwise referenced in subsection (4.1), the maximum height is
    7.5 m' loses its 'unless' because the preamble resolves it.
    """
    lowered = str(text or "").lower()
    if not lowered:
        return set()
    stripped = RESOLVED_EXCEPTION_PREAMBLE_RE.sub(" ", lowered)
    return {cue for cue in LEGAL_EXCEPTION_CUES if cue in stripped}


def to_float(value: Any) -> float | None:
    """Best-effort first-number-as-float parser shared across modules.

    Single source of truth: ``verification``, ``compliance``, ``consensus``, and
    ``conflict_guard`` previously each defined a byte-identical ``_to_float``.
    Returns the first numeric token (commas stripped) or ``None``. This is the
    permissive parser used for proposal/consensus comparison; the GIS export's
    ``_value_numeric`` is intentionally stricter (alpha + multi-number guards).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def matches_text_pattern(text: str, pattern: dict) -> bool:
    """Config-driven all/any/not term matcher used by verification + normalization.

    Lived in its own 20-line module (domain_patterns) since the prototype; it
    is vocabulary-adjacent and has exactly two consumers, so it now lives with
    the rest of the shared term logic.
    """
    lower_text = text.lower()
    all_terms = [str(term).lower() for term in pattern.get("all_terms", [])]
    any_terms = [str(term).lower() for term in pattern.get("any_terms", [])]
    not_terms = [str(term).lower() for term in pattern.get("not_terms", [])]
    if not_terms and any(term in lower_text for term in not_terms):
        # An excluded term is present, so this pattern does not apply. Lets a
        # pattern target one variant without catching its siblings, e.g. an
        # "interior side yard 1.2" rule that must NOT match the "end unit" row.
        return False
    if all_terms and not all(term in lower_text for term in all_terms):
        return False
    if any_terms and not any(term in lower_text for term in any_terms):
        return False
    return bool(all_terms or any_terms)
