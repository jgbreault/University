"""Deterministic span proof for Pipeline 5 text evidence.

Pipeline 5 text-block candidates are harder than table cells because a prose
excerpt can contain nearby values, conditions, and exceptions.  This module
builds a small source-span proof without using an LLM.  Later, an LLM can
propose the same span fields, but the verifier should still validate them with
these deterministic checks before promoting a rule.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import LEGAL_EXCEPTION_CUES, UNIT_ALIASES, separation_subject_grounded, text_words, unit_key, unresolved_exception_cues
from .rule_claims import NOT_ENOUGH_INFO, REFUTED, SUPPORTED, proof


TEXT_CONDITION_NOT_SUPPORTED = "text_condition_not_supported"

_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "for",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

_MATERIAL_CONDITION_CUES = {
    "abutting",
    "access",
    "approval",
    "between",
    "clear",
    "covenant",
    "exception",
    "except",
    "flat",
    "front",
    "heritage",
    "lane",
    "located",
    "network",
    "notwithstanding",
    "only",
    "obstruction",
    "projection",
    "rear",
    "register",
    "sloping",
    "street",
    "subject",
    "transit",
    "unless",
}

_DIRECTIONAL_TERMS = {
    "accessory",
    "abutting",
    "end",
    "flat",
    "flanking",
    "front",
    "heritage",
    "interior",
    "lane",
    "rear",
    "register",
    "side",
    "sloping",
    "street",
}

# Words that, on their own, make a "condition" a non-material heading rather
# than a real legal qualifier. This is Burnaby's R1 district label vocabulary
# and is the default when a caller does not pass a city-specific set. Callers
# source the per-city set from the normalization config.
_DEFAULT_NON_MATERIAL_CONDITION_WORDS = {
    "small",
    "scale",
    "multi",
    "unit",
    "housing",
    "district",
    "r1",
}


def text_span_proof_trace(
    candidate: dict[str, Any],
    evidence_text: str,
    non_material_condition_words: set[str] | None = None,
    rule_object_cue_extras: dict[str, tuple[str, ...]] | None = None,
    material_condition_cue_extras: frozenset[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return claim proofs based on explicit spans in prose evidence.

    ``non_material_condition_words`` lets a city supply its own district-label
    vocabulary that should not count as a material condition; it defaults to
    Burnaby's R1 set so existing callers are unchanged. The two ``*_extras``
    params carry per-city ADDITIVE cue vocabulary from the normalization
    config: rule-object extras only widen the SUPPORT side; material-condition
    extras can only make more conditions material (fail-closed). Defaults keep
    every existing caller byte-identical.
    """
    if not evidence_text.strip():
        return {}

    return {
        "rule_object": _prove_rule_object(candidate, evidence_text, rule_object_cue_extras),
        "operator": _prove_operator(candidate, evidence_text),
        "value": _prove_value(candidate.get("value"), evidence_text),
        "unit": _prove_unit(candidate.get("unit"), evidence_text),
        "constraint_scope": _prove_text_claim(
            candidate.get("constraint_scope"),
            evidence_text,
            "scope words appear in text evidence",
            optional=True,
        ),
        "applies_to": _prove_text_claim(
            candidate.get("applies_to"),
            evidence_text,
            "applies_to words appear in text evidence",
            optional=True,
        ),
        "condition": _prove_condition(
            candidate.get("condition"),
            evidence_text,
            non_material_condition_words,
            material_condition_cue_extras,
        ),
        "exception": _prove_exception(candidate.get("exception"), evidence_text),
    }


def text_span_support_gaps(
    candidate: dict[str, Any],
    proof_trace: dict[str, dict[str, Any]],
) -> list[str]:
    """Return support gaps that should block text auto-verification."""
    if not proof_trace:
        return []
    condition = proof_trace.get("condition", {})
    if condition.get("required_for_text_verification") and condition.get("label") != SUPPORTED:
        return [TEXT_CONDITION_NOT_SUPPORTED]
    return []


def text_span_proof_status(proof_trace: dict[str, dict[str, Any]]) -> str:
    """Summarize the deterministic text-span proof."""
    if not proof_trace:
        return "none"
    labels = {item.get("label") for item in proof_trace.values()}
    if REFUTED in labels:
        return "refuted"
    required_items = [
        item
        for item in proof_trace.values()
        if item.get("required_for_text_verification")
    ]
    if any(item.get("label") != SUPPORTED for item in required_items):
        return "partial"
    if NOT_ENOUGH_INFO in labels:
        return "partial"
    return "complete"


def _prove_value(value: Any, text: str) -> dict[str, Any]:
    tokens = _value_tokens(value)
    if not tokens:
        return proof(SUPPORTED, reason="candidate has no explicit value to prove")
    quote = _quote_for_tokens(text, tokens)
    if quote:
        return proof(SUPPORTED, evidence_field="evidence_text", evidence_quote=quote, reason="value appears in text evidence")
    # REFUTED (not NOT_ENOUGH_INFO) on competing numbers: evidence that has
    # numbers but not the candidate's number signals the extractor grabbed the
    # wrong clause, not that context is missing — and REFUTED is deliberately
    # the strongest label in merge_proof_traces so this cannot be hidden.
    if _numbers(text) and _numbers(value):
        return proof(REFUTED, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="text evidence contains numeric values but not the candidate value")
    return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="value is not visible in text evidence")


def _prove_unit(unit: Any, text: str) -> dict[str, Any]:
    unit_key_value = unit_key(unit)
    if unit_key_value is None:
        return proof(SUPPORTED, reason="candidate has no explicit unit to prove")
    normalized = text.lower()
    aliases = UNIT_ALIASES.get(unit_key_value, [str(unit or "").lower()])
    for alias in aliases:
        match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized)
        if match:
            return proof(SUPPORTED, evidence_field="evidence_text", evidence_quote=text[match.start() : match.end()], reason="unit appears in text evidence")
    return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="unit is not visible in text evidence")


def _prove_operator(candidate: dict[str, Any], text: str) -> dict[str, Any]:
    operator = str(candidate.get("operator") or "").strip().lower()
    constraint_type = str(candidate.get("constraint_type") or "").strip().lower()
    direction_text = f"{operator} {constraint_type}"
    evidence = text.lower()
    if any(token in direction_text for token in ("<=", "≤", "max", "maximum", "not_exceed")):
        return _prove_operator_cues(text, evidence, ("maximum", "not exceed", "up to", "limited to"), "<= / maximum")
    if any(token in direction_text for token in (">=", "≥", "min", "minimum", "at_least")):
        return _prove_operator_cues(
            text,
            evidence,
            ("minimum", "not less", "not be less", "nor be less", "no less", "at least", "shall have", "must have"),
            ">= / minimum",
        )
    if ">" in direction_text:
        return _prove_operator_cues(text, evidence, ("more than", "greater than", "exceeds"), ">")
    if "<" in direction_text:
        return _prove_operator_cues(text, evidence, ("less than", "fewer than", "under"), "<")
    if "allowed" in direction_text or "permitted" in direction_text:
        return _prove_operator_cues(text, evidence, ("permitted", "allowed"), "allowed")
    if "required" in direction_text:
        return _prove_operator_cues(text, evidence, ("required", "shall", "must", "contain"), "required")
    return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="operator wording is not proven by text evidence")


def _prove_operator_cues(text: str, evidence: str, cues: tuple[str, ...], label: str) -> dict[str, Any]:
    for cue in cues:
        index = evidence.find(cue)
        if index != -1:
            return proof(SUPPORTED, evidence_field="evidence_text", evidence_quote=text[index : index + len(cue)], reason=f"text wording supports {label}")
    return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason=f"text wording does not prove {label}")


def _prove_rule_object(
    candidate: dict[str, Any],
    text: str,
    rule_object_cue_extras: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    rule_object = str(candidate.get("rule_object") or "")
    evidence = text.lower()
    cue_groups = {
        "automatic_sprinkler": ("automatic sprinkler", "sprinkler"),
        "building_separation": ("separation",),
        "dwelling_units": ("dwelling units", "dwelling unit"),
        "fire_access_corridor": ("fire access corridor", "corridor"),
        "height": ("height",),
        "impervious_surface": ("impervious surface", "impervious"),
        # Without this entry the fallback rule_object.replace('_',' ') would
        # only match the 'floor space ratio' spelling, missing 'floor area
        # ratio' and 'fsr'.
        "floor_space_ratio": ("floor space ratio", "floor area ratio", "fsr"),
        "lot_area": ("lot area", "area"),
        "lot_coverage": ("lot coverage", "coverage"),
        "permitted_use": ("permitted use", "permitted"),
        "setback": ("setback", "yard"),
        "storeys": ("storeys", "storey", "stories", "story"),
    }
    cues = (
        *cue_groups.get(rule_object, (rule_object.replace("_", " "),)),
        # Per-city additive support phrases (normalization config) — support
        # side only, appended after the shared vocabulary.
        *(rule_object_cue_extras or {}).get(rule_object, ()),
    )
    for cue in cues:
        index = evidence.find(cue)
        if index != -1:
            if rule_object == "building_separation" and not separation_subject_grounded(evidence):
                # 'separation' alone is not enough: '1.0 metres ... between
                # retaining walls' verified as building_separation (live
                # Calgary P9 leak). The separation's subject must be a
                # building-like entity IN THE SAME SENTENCE — bundled evidence
                # once satisfied a whole-window check with 'buildings' from a
                # neighboring provision.
                break
            return proof(SUPPORTED, evidence_field="evidence_text", evidence_quote=text[index : index + len(cue)], reason="rule-object cue appears in text evidence")
    return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="rule object is not explicit in text evidence")


def _prove_text_claim(value: Any, text: str, reason: str, *, optional: bool = False) -> dict[str, Any]:
    if value in (None, ""):
        return proof(SUPPORTED if optional else NOT_ENOUGH_INFO, reason="candidate has no explicit claim")
    claim_words = _claim_words(value)
    if not claim_words:
        return proof(SUPPORTED if optional else NOT_ENOUGH_INFO, reason="claim has no distinctive words")
    evidence_words = text_words(text)
    if _claim_supported_by_words(claim_words, evidence_words):
        return proof(SUPPORTED, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason=reason)
    return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="claim words are not sufficiently visible in text evidence")


def _prove_condition(
    condition: Any,
    text: str,
    non_material_condition_words: set[str] | None = None,
    material_condition_cue_extras: frozenset[str] | None = None,
) -> dict[str, Any]:
    if condition in (None, ""):
        return proof(SUPPORTED, reason="candidate has no explicit condition claim")
    if not _material_condition(condition, non_material_condition_words, material_condition_cue_extras):
        return proof(SUPPORTED, reason="condition looks like a heading or non-material label")
    item = _prove_text_claim(condition, text, "material condition words appear in text evidence")
    # Condition is the ONLY claim that hard-blocks text auto-verification: an
    # unproven material condition means the rule may quote the right number
    # under the wrong legal qualifier — the one error class where the value,
    # unit, and operator all check out and the rule is still legally wrong.
    item["required_for_text_verification"] = True
    if item["label"] == SUPPORTED and not _directional_terms_supported(_claim_words(condition), text_words(text)):
        item["label"] = NOT_ENOUGH_INFO
        item["reason"] = "material directional/exception terms are missing from text evidence"
    return item


def _prove_exception(exception: Any, text: str) -> dict[str, Any]:
    # Shared cue detection (incl. the exclud* family): exclusion criteria read
    # like rules; an unresolved exclusion cue in the evidence keeps the
    # uncertainty visible (NEI), feeding the unresolved_exception_cue review
    # hold. Resolved default-rule preambles ("unless otherwise referenced in
    # (4.1)...") are already discounted by domain_schema.unresolved_exception_cues.
    cues = unresolved_exception_cues(text)
    if exception not in (None, ""):
        # A DECLARED exception only resolves the evidence's exclusion cue when
        # it carries distinctive (non-cue) substance that actually appears in
        # the evidence. Echoing the bare cue token ("excluding") — or any text
        # whose only words ARE cue tokens — does NOT resolve it: that was a
        # gate dodge that re-verified exclusion carve-out values (e.g. the
        # stairway/landing 2.5 m² carve-out) as if they were caps.
        if cues:
            distinctive = _claim_words(exception) - set(LEGAL_EXCEPTION_CUES)
            if not (distinctive and distinctive & text_words(text)):
                return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="declared exception only echoes the cue and does not resolve the evidence's exclusion wording")
        return _prove_text_claim(exception, text, "exception words appear in text evidence")
    if cues:
        return proof(NOT_ENOUGH_INFO, evidence_field="evidence_text", evidence_quote=_short_quote(text), reason="exception wording appears but candidate has no resolved exception")
    return proof(SUPPORTED, reason="no explicit exception claim and no unresolved exception cue")


def _material_condition(
    condition: Any,
    non_material_condition_words: set[str] | None = None,
    material_condition_cue_extras: frozenset[str] | None = None,
) -> bool:
    words = _claim_words(condition)
    if not words:
        return False
    # None means "city did not configure the key" -> Burnaby defaults. An
    # explicitly-configured empty set is honored as empty (no silent fallback).
    non_material = (
        _DEFAULT_NON_MATERIAL_CONDITION_WORDS
        if non_material_condition_words is None
        else non_material_condition_words
    )
    if words <= non_material:
        return False
    # KNOWN FAIL-OPEN: a condition whose words contain none of the cue list
    # below is treated as a non-material heading and auto-supported. A material
    # qualifier phrased with unlisted vocabulary would not block text
    # auto-verification. Kept deliberately (fail-closed here would send most
    # benign table headers to review); the cue list is the lever to extend —
    # per-city via material_condition_cue_extras, which can only make MORE
    # conditions material (more review pressure, never more verification).
    return bool(words & (_MATERIAL_CONDITION_CUES | (material_condition_cue_extras or frozenset())))


def _claim_supported_by_words(claim_words: set[str], evidence_words: set[str]) -> bool:
    if not claim_words:
        return False
    if not _directional_terms_supported(claim_words, evidence_words):
        return False
    matched = claim_words & evidence_words
    if len(claim_words) <= 2:
        return claim_words <= evidence_words
    return len(matched) >= max(2, len(claim_words) - 1)


def _directional_terms_supported(claim_words: set[str], evidence_words: set[str]) -> bool:
    required_terms = claim_words & _DIRECTIONAL_TERMS
    return required_terms <= evidence_words


def _claim_words(value: Any) -> set[str]:
    return {word for word in text_words(str(value or "")) if len(word) > 2 and word not in _STOPWORDS}


def _value_tokens(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    # (?:\.\d+)* keeps section references like '101.5.2' as one token,
    # mirroring support_checks/table_natural_logic.
    return re.findall(r"\d+(?:\.\d+)*", str(value).replace(",", "")) or [str(value).lower()]


def _quote_for_tokens(text: str, tokens: list[str]) -> str:
    # Search the ORIGINAL lowercased text (same length as `text`) with a
    # comma-tolerant pattern instead of searching a comma-stripped copy:
    # stripping changes offsets, so every comma before the match shifted the
    # quote window left and could push the proven value out of its own quote.
    lowered = text.lower()
    for token in tokens:
        token = token.lower()
        body = "".join(
            re.escape(ch) + ",?" if ch.isdigit() else re.escape(ch) for ch in token
        )
        # (?!\.?\d) lookahead: sentence-final periods do not hide the value.
        match = re.search(rf"(?<![\d.]){body}(?!\.?\d)", lowered)
        if match:
            start = max(0, match.start() - 45)
            end = min(len(text), match.end() + 45)
            return text[start:end].strip()
    return ""


def _numbers(value: Any) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))


ENUMERATED_BRANCH_CONDITION_MISSING = "enumerated_branch_condition_missing"

# Branch markers: lettered "(a)" / roman "(ii)" sub-clauses.
_BRANCH_MARKER_RE = re.compile(r"\((?:[a-z]|[ivx]{1,4})\)", re.IGNORECASE)
# Words that never discriminate one branch from another.
_BRANCH_GENERIC = {
    "the", "a", "an", "and", "or", "of", "for", "is", "are", "to", "in", "at",
    "metres", "metre", "meters", "meter", "m", "square", "sq", "m2",
    "maximum", "minimum", "building", "buildings", "height", "setback",
    "area", "floor", "any", "portion", "from", "shared", "with", "parcel",
    "property", "line", "grade", "measured", "designated",
}


def _branch_discriminator(segment: str) -> set[str]:
    """Distinctive words of a branch segment (its 'for X' / 'at Y' qualifier)."""
    return {
        word
        for word in text_words(segment)
        if word not in _BRANCH_GENERIC and not word.isdigit() and len(word) > 2
    }


def _enumerated_branches(evidence_text: str, family_unit: str | None) -> list[dict[str, Any]]:
    """Split an enumerated clause into branches carrying DISTINCT values.

    Returns [] unless the clause is a genuine multi-branch disjunction — two
    or more lettered/roman sub-clauses each stating a numeric value, with at
    least two DIFFERENT values among them. Each branch is
    {value: float, discriminator: set[str], segment: str}. City-neutral: it
    keys only on the enumeration punctuation and numbers, never on bylaw text.
    """
    # "lesser of (a) ...; and (b) ..." / "greater of ..." are MIN/MAX
    # aggregations: every operand is a co-applicable one-sided bound on the
    # SAME quantity (floor area <= the lesser of 0.25*site and 186 m^2 is
    # always <= 186), so each listed value is a genuinely valid — if not
    # tight — rule and must NOT be branch-gated. This is mathematical, not a
    # bylaw-specific carve-out, so it stays city-neutral. Exclusive
    # condition/part splits ("(a) X at a side line; (b) Y at a rear line",
    # "(a) 1.5 for the suite portion; (b) 0.6 for the garage portion") have
    # no such aggregator and remain gated.
    markers = list(_BRANCH_MARKER_RE.finditer(evidence_text))
    if len(markers) < 2:
        return []
    # The aggregation cue must introduce the list — it lives in the STEM,
    # before the first branch marker. Scanning the whole clause wrongly fired
    # on "(c) increases ... to a maximum of 7.5 metres", where "maximum of" is
    # branch (c)'s own bound, not an aggregator. Only true aggregators count:
    # 'lesser/greater/least/greatest of' (a min/max over the operands);
    # 'minimum/maximum' alone are ordinary bound words, never aggregators.
    stem = evidence_text[: markers[0].start()]
    if re.search(r"\b(?:lesser|greater|least|greatest)\s+of\b", stem, re.IGNORECASE):
        return []
    branches: list[dict[str, Any]] = []
    seen_values: set[float] = set()
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(evidence_text)
        # Bound the segment at its OWN sentence-final period so it never runs
        # into a neighbouring branch or a duplicated copy of the clause (the
        # verifier may pass evidence_text + source_context concatenated). The
        # (?!\d) keeps internal decimals ('7.5 m') from ending the sentence.
        period = re.search(r"\.(?!\d)", evidence_text[start:end])
        if period:
            end = start + period.end()
        segment = evidence_text[start:end]
        nums = _numbers(segment)
        if not nums:
            continue
        # Dedupe repeated branch values (a doubled clause yields a/b/c twice);
        # the discriminator is identical, so one copy per distinct value is
        # enough and keeps sibling comparisons clean.
        if float(nums[0]) in seen_values:
            continue
        seen_values.add(float(nums[0]))
        # The branch's own value is the FIRST number in its segment; later
        # numbers (e.g. a '45 degree' modifier, a '2.5 m2' carve-out) are not
        # the branch cap. A unit filter is intentionally NOT applied — prose
        # branches rarely repeat the unit per sub-clause.
        branches.append(
            {
                "value": float(nums[0]),
                "discriminator": _branch_discriminator(segment),
                "segment": segment,
            }
        )
    distinct_values = {branch["value"] for branch in branches}
    if len(branches) < 2 or len(distinct_values) < 2:
        return []
    return branches


def enumerated_branch_gap(candidate: dict[str, Any], evidence_text: str) -> str | None:
    """Hold a branch value whose discriminating condition is unproven.

    The prose analogue of the table conditional-cell / overlay gate. An
    enumerated disjunction ("(a) 5.0 m at a side property line; (b) 3.0 m at
    a rear property line; (c) ... 7.5 m") states several values, each gated
    by its own qualifier. A candidate that claims one branch's value must
    prove THAT branch's discriminator (via condition or applies_to) and must
    NOT match a sibling (different-value) branch better — otherwise the
    verified rule asserts an unconditional cap the bylaw never states, or
    mispairs a value with the wrong qualifier. Returns the review gap or None.

    Returns None (gate inert) when: the clause is not multi-branch, the
    candidate has no numeric value, or the candidate's value is not one of
    the competing branch values (other gates handle those).
    """
    value = _value_tokens(candidate.get("value"))
    if not value:
        return None
    try:
        claimed_value = float(_numbers(candidate.get("value"))[0])
    except (IndexError, ValueError):
        return None
    branches = _enumerated_branches(evidence_text, candidate.get("unit"))
    if not branches:
        return None
    value_branches = [b for b in branches if abs(b["value"] - claimed_value) <= 0.01]
    if not value_branches:
        return None  # the claimed value is not a competing branch value here

    # The candidate's discriminator: distinctive words from condition AND
    # applies_to (applies_to legitimately carries the branch subject, e.g.
    # "Backyard Suite" vs "private garage").
    disc = _branch_discriminator(str(candidate.get("condition") or "")) | _branch_discriminator(
        str(candidate.get("applies_to") or "")
    )
    sibling_branches = [b for b in branches if abs(b["value"] - claimed_value) > 0.01]
    best_sibling = max((len(disc & b["discriminator"]) for b in sibling_branches), default=0)

    # Resolved iff the discriminator matches one of the candidate's
    # value-branches STRICTLY better than any different-value sibling. No
    # discriminator (own == 0) never resolves; a tie with a sibling
    # (mispairing risk) never resolves.
    for value_branch in value_branches:
        own = len(disc & value_branch["discriminator"])
        if own > 0 and own > best_sibling:
            return None
    return ENUMERATED_BRANCH_CONDITION_MISSING


def _short_quote(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
