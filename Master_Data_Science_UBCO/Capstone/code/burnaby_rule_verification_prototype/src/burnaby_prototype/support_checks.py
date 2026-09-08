"""Deterministic support checks used by the verifier.

This module contains reusable, evidence-facing checks.  It is intentionally
rule-based: these functions do not extract rules and do not promote rules.  They
only answer narrow questions such as "is the candidate value visible in the
cited text?" or "does the evidence wording support a maximum operator?".
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import (
    GENERIC_APPLIES_TO_WORDS,
    KNOWN_RULE_OBJECTS,
    PLAIN_ONLY_RULE_OBJECT_PATTERNS,
    RULE_OBJECT_ALLOWED_UNITS,
    SUPPORTED_OPERATORS,
    TEXT_RULE_OBJECT_PATTERNS,
    text_words,
    to_float,
    numeric_occurrence_is_reference,
    separation_subject_grounded,
    token_visible,
    unit_key,
    unit_visible,
)
from .normalization_rules import (
    generic_applies_to_extra_words,
    get_normalization,
    rule_object_text_cue_extras,
)


def evidence_with_parent_context(evidence_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach parent-clause context to enumerated child bullets.

    Bylaws often express a rule as a parent clause followed by children, for
    example "fire access corridor that:" and then "(b) is clear ... 2.5 m".
    The child has the number, while the parent has the rule family.  This keeps
    the context local and deterministic.
    """
    enriched: list[dict[str, Any]] = []
    for unit in evidence_units:
        current = dict(unit)
        text = str(current.get("evidence_text") or "").strip()
        if _looks_like_list_child(text):
            parent = _nearest_parent_clause(enriched, current)
            if parent:
                original_context = str(current.get("source_context") or text)
                current["inherited_parent_context"] = parent
                current["source_context"] = f"{parent} {original_context}".strip()
        enriched.append(current)
    return enriched


def value_present_on_page(value: Any, page_text: str) -> bool:
    """Return True when the candidate's numeric value really appears on the page.

    The re-anchor mismatch guard uses this in ADDITION to a context-window
    match: a header prefix ("GENERAL RULES:") can anchor the window while the
    value-bearing clause is fabricated, so an anchored window alone must not
    declare the block found on its claimed page. Boundary-aware (shared
    token_visible) and citation-aware (a paren/section-reference occurrence
    does not count), mirroring the verifier's own value check. A value-less
    candidate (use rules) returns True — there is no number to corroborate.
    """
    tokens = [token for token in re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))]
    if not tokens:
        return True
    normalized = str(page_text or "").replace(",", "")
    lowered = normalized.lower()
    token = tokens[0]
    for match in re.finditer(rf"(?<![\d.]){re.escape(token)}(?!\.?\d)", lowered):
        if not numeric_occurrence_is_reference(lowered, match.start(), match.end()):
            return True
    return False


def local_source_context(evidence_text: str, source_context: str, *, radius: int = 80) -> str:
    """Find a short context window around the cited evidence.

    The needle list progressively truncates evidence_text at '|', '(' and ':'
    because extracted evidence is often a re-punctuated table fragment that
    never appears verbatim in the page context — shorter prefixes are tried
    until one anchors. Returning '' on a total miss is deliberate: an
    un-anchorable context must not contribute support text.
    """
    if not evidence_text or not source_context:
        return ""
    source_lower = source_context.lower()
    needles = [
        evidence_text,
        evidence_text.split("|", 1)[0],
        evidence_text.split("(", 1)[0],
        evidence_text.split(":", 1)[0],
    ]
    for needle in needles:
        needle = needle.strip()
        if not needle:
            continue
        index = source_lower.find(needle.lower())
        if index != -1:
            start = max(0, index - radius)
            end = min(len(source_context), index + len(needle) + radius)
            return source_context[start:end]
    return ""


def value_local_window(evidence_text: str, value: Any, *, radius: int = 90) -> str:
    """Find the clause around the candidate value when evidence has many numbers."""
    tokens = [token for token in _value_tokens(value) if re.search(r"\d", token)]
    if not evidence_text or not tokens:
        return ""
    normalized = evidence_text.lower()
    for token in tokens:
        # [\d.] lookbehind: '5' must not anchor the window inside '7.5' or a
        # section reference like '101.5.2'. Lookahead (?!\.?\d): a trailing
        # sentence period does not disqualify ('0.25.'), a decimal tail does.
        # Citation-shaped occurrences (paren-wrapped references, amendment
        # codes like 10P2019, 'section 3.1') are skipped via the shared
        # validator so the window anchors on a real measurement.
        match = None
        for found in re.finditer(rf"(?<![\d.]){re.escape(token.lower())}(?!\.?\d)", normalized):
            if numeric_occurrence_is_reference(normalized, found.start(), found.end()):
                continue
            match = found
            break
        if match:
            start = _nearest_left_clause_boundary(evidence_text, match.start())
            end = _nearest_right_clause_boundary(evidence_text, match.end())
            if start is None:
                start = max(0, match.start() - radius)
            if end is None:
                end = min(len(evidence_text), match.end() + radius)
            return evidence_text[start:end]
    return ""


def has_multiple_numeric_values(evidence_text: str) -> bool:
    # Synthetic evidence bundles prefix each source quote with labels such as
    # ``[pipeline5_merged_rule_0090__api_01]``. Those labels contain digits but
    # are provenance, not legal values. Ignore them before deciding whether to
    # shrink support checks to a numeric value window.
    text = _strip_synthetic_evidence_labels(evidence_text)
    numbers = {
        str(float(number))
        for number in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    }
    return len(numbers) > 1


def contains_value(evidence_text: str, value: Any) -> bool:
    """Check whether every value token appears in the cited evidence text.

    Uses digit-boundary matching (token_visible), not substring containment:
    this check feeds value_not_found_in_evidence, a hard-rejection gap, so a
    candidate value '5' must not be satisfied by evidence that only says '7.5'.
    """
    tokens = _value_tokens(value)
    if not tokens:
        return True
    normalized = evidence_text.replace(",", "")
    return all(token_visible(normalized, token) for token in tokens)


def contains_unit(evidence_text: str, unit: Any) -> bool:
    """Check whether the unit appears in evidence, allowing unit aliases.

    Canonicalizes via unit_key before the alias lookup (shared unit_visible
    helper), so a unit extracted as 'metres' or 'm²' still matches evidence
    written as '7.5 m' instead of hard-rejecting a correct rule.
    """
    if unit in (None, "", "null"):
        return True
    return unit_visible(evidence_text, unit)


def rule_object_unit_compatible(candidate: dict[str, Any]) -> bool:
    """Reject unit/rule-object combinations that cannot be legally meaningful."""
    rule_object = str(candidate.get("rule_object") or "")
    allowed_units = RULE_OBJECT_ALLOWED_UNITS.get(rule_object)
    if not allowed_units:
        return True
    normalized_unit = unit_key(candidate.get("unit"))
    if normalized_unit is None:
        return True
    return normalized_unit in allowed_units


# Recognized imperial / non-metric units. Kept SEPARATE from UNIT_ALIASES (which
# feeds table-proof unit visibility) so listing them here cannot affect metric
# table proofs. Used only to route an imperial-stated rule to REVIEW (honest)
# rather than silently verifying a feet value against a metric threshold -- the
# deterministic verifier never auto-converts units (that would forge source
# fidelity). Many Ontario / older Canadian bylaws state setbacks/heights in feet.
IMPERIAL_UNIT_TOKENS = frozenset(
    {
        "ft", "ft.", "feet", "foot", "'",
        "in", "in.", "inch", "inches", '"',
        "yd", "yard", "yards",
        "sf", "sq ft", "sq. ft", "sq.ft", "square foot", "square feet",
        "acre", "acres", "ac",
        "mile", "miles", "mi",
    }
)
_METRIC_UNIT_KEYS = {"m", "m2"}


def is_imperial_unit(unit: Any) -> bool:
    """True if the unit string is a recognized imperial/non-metric length/area unit."""
    return str(unit or "").strip().lower() in IMPERIAL_UNIT_TOKENS


def family_expects_metric(rule_object: Any) -> bool:
    """True when the rule family's allowed units are metric (m / m2)."""
    allowed = RULE_OBJECT_ALLOWED_UNITS.get(str(rule_object or ""))
    return bool(allowed) and allowed <= _METRIC_UNIT_KEYS


def generic_applies_to_words(config: dict[str, Any] | None) -> set[str]:
    """Return generic, non-distinctive applies_to words for this city."""
    return GENERIC_APPLIES_TO_WORDS | generic_applies_to_extra_words(get_normalization(config))


def target_words_from_config(config: dict[str, Any]) -> set[str]:
    """Get distinctive target-building words from config, not hardcoded values."""
    target_text = " ".join(
        str(part or "")
        for part in [
            config.get("target_concept"),
            " ".join(str(alias) for alias in config.get("known_aliases", [])),
        ]
    )
    return text_words(target_text) - generic_applies_to_words(config)


def applies_to_supported(
    candidate: dict[str, Any],
    evidence_text: str,
    config: dict[str, Any] | None = None,
) -> bool:
    """Check whether the evidence supports the candidate's applies_to field."""
    applies_to = str(candidate.get("applies_to") or "").strip()
    if not applies_to:
        return True
    applies_words = text_words(applies_to)
    if "all" in applies_words:
        return True
    distinctive_words = applies_words - generic_applies_to_words(config)
    if candidate.get("rule_object") == "permitted_use" and not distinctive_words:
        return False
    if not distinctive_words:
        return True
    evidence_words = text_words(evidence_text)
    # 'heritage' is distinctive enough that one match suffices — no other R1
    # vocabulary collides with it, and heritage rules change legal limits.
    if "heritage" in applies_words and "heritage" in evidence_words:
        return True
    # A rule stated for "all buildings" covers the rear principal building, so
    # generic all-buildings evidence may support a rear-principal applies_to.
    if {"rear", "principal"} <= applies_words and {"all", "building"} <= evidence_words:
        return True
    matched = distinctive_words & evidence_words
    # Single-word targets must match exactly; multi-word targets need two
    # matches so one shared generic-ish word cannot carry the claim alone.
    required = 1 if len(distinctive_words) == 1 else 2
    return len(matched) >= required


def scope_supported(candidate: dict[str, Any], evidence_text: str) -> bool:
    """Check whether rule scope or condition is grounded in local evidence."""
    scope_text = " ".join(
        str(candidate.get(key) or "") for key in ("rule_object", "constraint_scope", "condition")
    )
    scope_words = {
        word
        for word in text_words(scope_text)
        if len(word) > 2 and word not in {"the", "and", "for", "minimum", "maximum"}
    }
    if not scope_words:
        return True
    evidence_words = text_words(evidence_text)
    if candidate.get("rule_object") == "setback" and not _setback_scope_words_supported(scope_words, evidence_words):
        return False
    if "separation" in scope_words and "between" in evidence_words:
        return True
    if "separation" in scope_words and _from_building_distance_supported(evidence_text):
        return True
    return bool(scope_words & evidence_words)


def operator_supported(candidate: dict[str, Any], evidence_text: str) -> bool:
    """Check whether evidence wording supports the candidate operator."""
    operator = str(candidate.get("operator") or "").strip()
    # Canonicalize unicode comparators first: '≤'/'≥' are in SUPPORTED_OPERATORS,
    # and without this they would fall through every wording branch below to the
    # default — i.e. a '≤' candidate would need NO maximum wording while '<='
    # does. Same legal claim, same evidence requirement.
    operator = {"≤": "<=", "≥": ">="}.get(operator, operator)
    if not operator:
        if candidate.get("value") is None and str(candidate.get("constraint_type") or "").lower() not in {
            "allowed",
            "permitted",
        }:
            return False
        return True
    if operator not in SUPPORTED_OPERATORS:
        return False
    text = evidence_text.lower()
    if operator in {"<=", "max", "maximum", "not_exceed"}:
        if _dwelling_unit_upper_bound_supported(candidate, text):
            return True
        return any(phrase in text for phrase in ["maximum", "not exceed", "up to", "limited to"])
    if operator in {">=", "min", "minimum", "at_least"}:
        return any(
            phrase in text
            for phrase in [
                "minimum",
                "not less",
                "not be less",
                "nor be less",
                "no less",
                "at least",
                "shall have",
            ]
        )
    if operator == ">":
        return any(phrase in text for phrase in ["more than", "greater than", "exceeds"])
    if operator == "<":
        return any(phrase in text for phrase in ["less than", "fewer than", "under"])
    if operator in {"=", "allowed", "permitted"}:
        # \bis\b, not the substring "is": bare containment matched inside
        # "district", "existing", etc., making this branch nearly vacuous.
        return any(phrase in text for phrase in ["permitted", "shall", "must"]) or bool(
            re.search(r"\bis\b", text)
        )
    if operator == "required":
        return any(phrase in text for phrase in ["required", "shall", "must"])
    if operator == "range":
        return bool(re.search(r"\b\d+\s+to\s+\d+\b", text))
    # Default-closed: every member of SUPPORTED_OPERATORS has an explicit
    # wording branch above. If a new operator is added to the vocabulary
    # without one, it must NOT silently verify with zero evidence wording.
    return False


def rule_object_supported(
    config: dict[str, Any],
    candidate: dict[str, Any],
    evidence_text: str,
) -> bool:
    """Check whether the cited evidence actually talks about this rule family."""
    rule_object = str(candidate.get("rule_object") or "")
    if not rule_object or rule_object not in KNOWN_RULE_OBJECTS:
        return False
    if not evidence_text.strip():
        return False

    text = evidence_text.lower()
    plain_rule_object = rule_object.replace("_", " ")
    if (
        rule_object == "height"
        and any(term in text for term in ["clear to a height", "clear of", "projection", "obstruction"])
        and "building" not in text
    ):
        return False
    if rule_object in text or plain_rule_object in text:
        return True
    evidence_words = text_words(text)
    if rule_object == "lot_area" and {"lot", "area"} <= evidence_words:
        return True
    matched = _rule_object_from_patterns(text, [*PLAIN_ONLY_RULE_OBJECT_PATTERNS, *TEXT_RULE_OBJECT_PATTERNS])
    if matched == rule_object:
        # building_separation needs its subject in the SAME SENTENCE as the
        # separation cue: a bundle once joined a retaining-wall separation
        # clause with a neighboring provision that said 'buildings' and the
        # whole-window pattern verified it (live Calgary P9 leak).
        if rule_object == "building_separation":
            return separation_subject_grounded(text)
        return True
    if rule_object in {"height", "storeys"} and matched in {"height", "storeys"}:
        return True
    is_v3_clause = str(candidate.get("extraction_method") or "") == "native_v3_clause"
    if is_v3_clause and rule_object == "setback" and _property_line_distance_supported(text):
        return True
    if is_v3_clause and rule_object == "building_separation" and _from_building_distance_supported(text):
        return True
    if rule_object == "permitted_use":
        target_words = target_words_from_config(config)
        if target_words and target_words & evidence_words:
            return True
        return bool({"permitted", "allow", "allowed"} & evidence_words)
    # Per-city ADDITIVE cues (same trust level as known_aliases): a city's
    # normalization config may declare extra support phrases for a family —
    # e.g. prose setbacks phrased "0.9 m from the ultimate rear property
    # line". Extras can only flip this review-tier check to True for the
    # configured city; they never join the refutation vocabulary and never
    # touch the critical value/unit gates.
    for cue in rule_object_text_cue_extras(get_normalization(config)).get(rule_object, ()):
        if cue and cue in text:
            return True
    return False


def _property_line_distance_supported(text: str) -> bool:
    words = text_words(text)
    return "from" in words and "property" in words and "line" in words


def _from_building_distance_supported(text: str) -> bool:
    words = text_words(text)
    if "from" not in words:
        return False
    if not ({"least", "minimum"} & words):
        return False
    building_words = {"building", "dwelling", "suite", "house"}
    return len(words & building_words) >= 2 or (
        bool(words & {"house", "dwelling", "suite"}) and bool(words & {"detached", "principal", "main"})
    )


def _looks_like_list_child(text: str) -> bool:
    """Return True for enumerated child clauses such as "(a)" or "(iii)"."""
    return bool(re.match(r"\s*\([a-zivx0-9]+\)\s+", text.lower()))


def _nearest_parent_clause(
    prior_units: list[dict[str, Any]],
    child: dict[str, Any],
) -> str:
    """Find the nearest same-page parent clause that can legally govern a child.

    The backward scan stops at the first same-page unit that is neither a list
    child nor a qualifying colon-parent: inheritance may only cross a
    contiguous enumeration block. Without the stop, a stale ':' clause from
    earlier on the page could be attached to an unrelated '(x)' bullet, and the
    inherited text would then feed the support windows as if it governed it.
    """
    for parent in reversed(prior_units):
        if parent.get("page") != child.get("page"):
            continue
        if parent.get("evidence_type") != child.get("evidence_type"):
            continue
        parent_text = str(parent.get("evidence_text") or "").strip()
        parent_lower = parent_text.lower()
        if parent_text.endswith(":") and any(
            cue in parent_lower
            for cue in (" that:", "following:", "subject to the following:")
        ):
            return parent_text
        if not _looks_like_list_child(parent_text):
            # Ordinary prose or a heading between the child and any earlier
            # parent breaks the enumeration — stop rather than inherit across it.
            return ""
    return ""


def _value_tokens(value: Any) -> list[str]:
    """Extract comparable value tokens, usually numbers, from a candidate value."""
    if value is None:
        return []
    if isinstance(value, list):
        tokens = []
        for item in value:
            tokens.extend(_value_tokens(item))
        return tokens
    if isinstance(value, dict):
        tokens = []
        for item in value.values():
            tokens.extend(_value_tokens(item))
        return tokens
    value_text = str(value).strip()
    if not value_text:
        return []
    # Strip comma grouping BEFORE extracting numbers so '1,200' yields the
    # single token '1200' (matching comma-stripped evidence), not '1' + '200'.
    # The (?:\.\d+)* tail keeps section references like '101.5.2' as ONE token:
    # splitting them into '101.5' + '2' would make the digit-boundary check in
    # contains_value fail on text that literally states the reference.
    numbers = re.findall(r"\d+(?:\.\d+)*", value_text.replace(",", ""))
    return numbers or [value_text.lower()]


def _strip_synthetic_evidence_labels(text: str) -> str:
    """Remove bundle provenance labels before numeric evidence counting."""
    return re.sub(r"\[[^\]]+\]", " ", text)


def _dwelling_unit_upper_bound_supported(candidate: dict[str, Any], evidence_text: str) -> bool:
    """Return True when range evidence supports a dwelling-unit maximum."""
    if candidate.get("rule_object") != "dwelling_units":
        return False
    operator_text = f"{candidate.get('operator') or ''} {candidate.get('constraint_type') or ''}".lower()
    if not any(token in operator_text for token in ("<=", "≤", "maximum", "max")):
        return False
    candidate_value = to_float(candidate.get("value"))
    if candidate_value is None:
        return False
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+(?:dwelling\s+)?units?\b", evidence_text, flags=re.IGNORECASE):
        upper_bound = float(match.group(2))
        if abs(candidate_value - upper_bound) <= 0.01:
            return True
    return False


def _nearest_left_clause_boundary(text: str, index: int) -> int | None:
    candidates: list[int] = []
    for pattern in [r"\.\s+", r";\s+", r",\s+and\s+", r",\s+or\s+"]:
        for match in re.finditer(pattern, text[:index], flags=re.IGNORECASE):
            candidates.append(match.end())
    return max(candidates) if candidates else None


def _nearest_right_clause_boundary(text: str, index: int) -> int | None:
    candidates: list[int] = []
    for pattern in [r"\.\s+", r";\s+", r",\s+and\s+", r",\s+or\s+"]:
        match = re.search(pattern, text[index:], flags=re.IGNORECASE)
        if match:
            candidates.append(index + match.start())
    return min(candidates) if candidates else None


def _setback_scope_words_supported(scope_words: set[str], evidence_words: set[str]) -> bool:
    """Require the directional part of setback scopes to match locally."""
    if "front" in scope_words and "front" not in evidence_words:
        return False
    if "flanking" in scope_words and "flanking" not in evidence_words:
        return False
    if "lane" in scope_words and "lane" not in evidence_words:
        return False
    if "rear" in scope_words and "rear" not in evidence_words:
        return False
    if "side" in scope_words and "side" not in evidence_words:
        return False
    if "interior" in scope_words and "interior" not in evidence_words:
        return False
    return True


def _phrase_match(text: str, phrase_groups: tuple[tuple[str, ...], ...]) -> bool:
    return any(all(phrase in text for phrase in group) for group in phrase_groups)


def _rule_object_from_patterns(text: str, patterns: list[tuple[str, tuple[tuple[str, ...], ...]]]) -> str | None:
    for rule_object, phrase_groups in patterns:
        if _phrase_match(text, phrase_groups):
            return rule_object
    return None
