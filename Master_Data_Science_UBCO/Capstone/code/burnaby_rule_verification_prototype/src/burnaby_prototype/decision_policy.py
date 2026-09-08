"""Decision policy for verified/review/rejected/not-used buckets.

The verifier creates support gaps first; this module is the only place that
turns those gaps into a final bucket.  Keeping this separate makes the safety
policy easy to audit and prevents ad hoc rejection logic from spreading through
the codebase.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import (
    KNOWN_RULE_OBJECTS,
    looks_like_section_reference,
    numeric_occurrence_is_reference,
    value_bound_to_foreign_measure,
)


VERIFIED = "verified"
REVIEW_NEEDED = "review_needed"
REJECTED = "rejected"
NOT_USED = "not_used"

TABLE_REVIEW_GAPS = {
    "deterministic_table_evidence": "table_fallback_candidate_requires_review",
    "table_cell": "table_cell_candidate_requires_review",
    "table_evidence": "table_evidence_candidate_requires_review",
}

# Tiering rationale: scope/applies_to/operator failures land in REVIEW (these
# checks are absence-of-cue heuristics with limited recall — a miss often means
# "wording not recognized", which a human or better evidence can repair), while
# a value or unit absent from the cited evidence is a hard REJECTION below: the
# citation itself is wrong, and no amount of context can make a number that is
# not in the evidence safe to act on.
MISSING_SCOPE_GAPS = {
    "applies_to_not_supported",
    "constraint_scope_not_supported",
    "table_rule_object_not_supported",
    "table_applies_to_not_supported",
    "table_condition_not_supported",
    "table_column_not_target_scope",
    *TABLE_REVIEW_GAPS.values(),
    "rule_object_not_canonical",
    "rule_object_not_supported",
    "text_candidate_requires_review",
    "text_condition_not_supported",
    "unresolved_exception_cue",
    "cross_family_value_collision",
    "rule_family_direction_mismatch",
    # 'no maximum building depth where the minimum setback is 3.0 m' — the
    # 3.0 m is the trigger of an allowance, not a requirement; a human may
    # still decide it is worth recording, so review rather than rejection.
    "allowance_trigger_threshold",
    # Matrix-column binding holds (geometry-aware, additive): the claimed
    # column exists but the claim drops a binding qualifier, names a column
    # the matrix cannot resolve, or sits on a row whose label names another
    # rule family. All are repairable by a human or better extraction.
    "applicability_not_grounded",
    "column_qualifier_not_claimed",
    "conditional_cell_condition_missing",
    "anchored_row_family_mismatch",
    # Prose enumerated multi-branch disjunction ("(a) 5.0 m at a side
    # property line; (b) 3.0 m at a rear property line; (c) ... 7.5 m"): the
    # claimed branch value's discriminating condition is unproven or mispaired.
    # A real rule under the wrong/absent qualifier — repairable, so review.
    "enumerated_branch_condition_missing",
    # LLM-lane leak classes (found by running V2's real model extraction): a
    # ratio coefficient mis-extracted as an absolute cap ("0.25 multiplied by
    # the site area"), and a count range-bound mis-extracted as the lot
    # maximum ("1 to 3 Units" -> lot max 3 when 4 to 6 also listed). Both are
    # real values in the text under the wrong role — review, never reject.
    "coefficient_operand_not_value",
    "range_bound_not_maximum",
    # An imperial/non-metric unit on a metric family. A real rule stated in feet
    # is held for human review/conversion -- never silently verified against a
    # metre threshold and never auto-converted by the verifier. Bylaw-agnostic.
    "non_metric_unit_requires_review",
    # The extraction layer flagged a source-fidelity concern the deterministic
    # gates cannot see on their own (e.g. a re-anchor mismatch / quote not in the
    # retrieved pack: the provided evidence_text may contain a value that is NOT
    # on the real source page). This stays blocking even though the generic
    # extractor review request is advisory. See ADVISORY_GAPS.
    "extraction_source_fidelity_hold",
}

# Hard rejection is reserved for contradictions or unsafe malformed candidates.
# A rule family outside the current contract should be review/not_used, not a
# hard rejection, because future bylaws may add rule families we do not support
# yet.
CRITICAL_REJECTION_GAPS = {
    "source_evidence_id_not_found",
    "value_not_found_in_evidence",
    "unit_not_found_in_evidence",
    "rule_object_unit_not_compatible",
    "table_operator_refuted",
    # The cited number measures something else ('135 degrees' can never be a
    # dwelling-unit count) — same severity as a value that is absent.
    "value_bound_to_foreign_unit",
    # Geometry refutation: the claimed table column does NOT hold the value
    # (55% claimed for the 5-6 unit column whose cell says 45%). The cited
    # column-value pairing is wrong, same severity as a wrong value.
    "column_value_mismatch",
}

NOT_USED_GAPS = {
    "cross_reference_only",
    "outside_current_rule_contract",
    # '"corner parcel" means ... not exceeding 135 degrees' defines
    # vocabulary; definitions are navigation/audit material, not enforceable
    # rules, exactly like section cross-references.
    "definition_not_rule",
    # A narrative/descriptive value under a numeric rule family ('links the
    # fronting street with the parallel lane ...') is a real extracted item
    # that sits outside the numeric GIS contract — not proof the extraction
    # is wrong. It can never verify (the numeric contract requires a numeric
    # value), so routing it to not_used keeps false_verified at zero while
    # reserving hard rejection for contradicted/unsafe candidates.
    "non_numeric_value_for_numeric_rule",
    # True rules from the same full bylaw but outside the configured target
    # sections are useful context, not verified outputs for the current product
    # scope. Example: Calgary P9 can surface R-G/R-Gm section 547 backyard-suite
    # rules while this verifier contract targets sections 351/352/358.
    "outside_target_section",
}


# Advisory gaps inform the audit trail but never block a decision. The
# deterministic verifier is the sole authority (extraction only generates
# candidates), so the extraction layer's review request cannot, by itself, hold
# back a candidate whose every deterministic gate passed. It still rides along
# on reviewed/rejected rules for routing and ranking.
ADVISORY_GAPS = {
    "upstream_extraction_requested_review",
}


def verification_decision_from_gaps(support_gaps: list[str]) -> str:
    """Return the active verifier decision from blocking support gaps only.

    ADVISORY_GAPS (e.g. the extraction layer's review request) are excluded from
    the blocking set: a candidate whose only gaps are advisory, and whose every
    deterministic gate passed, is verified. This does not relax any gate — the
    value/unit/operator/scope/direction/exception checks are unchanged; it only
    stops a non-deterministic upstream label from vetoing the verifier.
    """
    gaps = set(support_gaps)
    blocking = gaps - ADVISORY_GAPS
    if not blocking:
        return VERIFIED
    if CRITICAL_REJECTION_GAPS & blocking:
        return REJECTED
    if NOT_USED_GAPS & blocking:
        return NOT_USED
    return REVIEW_NEEDED


def not_used_gaps_for_candidate(candidate: dict[str, Any], evidence: dict[str, Any] | None) -> list[str]:
    """Classify candidates that are real extraction artifacts but not rules to validate.

    This catches common zoning-table tracebacks such as ``Use-Specific
    Regulations: 101.5.2``.  They are useful for navigation/audit, but they are
    not enforceable numeric or allowed-use rules in this verifier stage.
    """
    if not evidence:
        return []

    gaps: list[str] = []
    rule_object = str(candidate.get("rule_object") or "")
    value = candidate.get("value")
    evidence_text = " ".join(
        str(evidence.get(field) or "")
        for field in ("table_title", "row_header", "column_header", "cell_value", "evidence_text")
    ).lower()

    if looks_like_section_reference(value) and any(
        phrase in evidence_text
        for phrase in ("use-specific regulations", "use specific regulations", "see section", "subject to section")
    ):
        gaps.append("cross_reference_only")

    if rule_object and rule_object not in KNOWN_RULE_OBJECTS:
        gaps.append("outside_current_rule_contract")

    return gaps


def target_scope_gaps_for_candidate(
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None,
    config: dict[str, Any] | None,
) -> list[str]:
    """Return gaps for true-but-out-of-target source sections.

    This is an optional contract guard, driven by
    ``verification.target_section_ids``. It is intentionally section-based, not
    value-based: it does not encode expected rule answers, only which bylaw
    sections are in scope for this verification run.
    """
    targets = _target_section_ids(config)
    if not targets or not evidence:
        return []
    text = _section_search_text(candidate, evidence)
    sections = _source_section_ids(text)
    if not sections:
        if _generic_p9_without_target_hit(candidate, evidence, config, text):
            return ["outside_target_section"]
        return []
    if any(_section_allowed(section, targets) for section in sections):
        return []
    return ["outside_target_section"]


def _target_section_ids(config: dict[str, Any] | None) -> list[str]:
    verification = (config or {}).get("verification") or {}
    raw = verification.get("target_section_ids") or []
    return [str(section).strip() for section in raw if str(section).strip()]


def _section_search_text(candidate: dict[str, Any], evidence: dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            evidence.get("section"),
            evidence.get("heading"),
            evidence.get("evidence_text"),
            evidence.get("source_context"),
            candidate.get("constraint_scope"),
            candidate.get("condition"),
        )
    )


def _generic_p9_without_target_hit(
    candidate: dict[str, Any],
    evidence: dict[str, Any],
    config: dict[str, Any] | None,
    text: str,
) -> bool:
    provenance = {}
    if isinstance(evidence.get("p9_provenance"), dict):
        provenance = evidence.get("p9_provenance") or {}
    elif isinstance(candidate.get("p9_provenance"), dict):
        provenance = candidate.get("p9_provenance") or {}
    if provenance.get("target_filter_action") != "kept_generic_applicable":
        return False
    target_text = " ".join(
        str(value or "")
        for value in (
            text,
            candidate.get("applies_to"),
            candidate.get("constraint_scope"),
            candidate.get("condition"),
        )
    ).lower()
    aliases = _target_aliases(config)
    return bool(aliases) and not any(alias in target_text for alias in aliases)


def _target_aliases(config: dict[str, Any] | None) -> list[str]:
    values = [str((config or {}).get("target_concept") or "")]
    values.extend(str(alias) for alias in ((config or {}).get("known_aliases") or []))
    aliases = []
    for value in values:
        alias = re.sub(r"\s+", " ", value.lower()).strip()
        if alias:
            aliases.append(alias)
    return aliases


_SECTION_HEADING_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<section>\d{2,4}(?:\.\d{1,3})?)\s*(?=\(|[A-Z][A-Za-z])"
)


def _source_section_ids(text: str) -> list[str]:
    seen: set[str] = set()
    sections: list[str] = []
    for match in _SECTION_HEADING_RE.finditer(str(text or "")):
        section = match.group("section")
        if section not in seen:
            seen.add(section)
            sections.append(section)
    return sections


def _section_allowed(section: str, targets: list[str]) -> bool:
    section = str(section or "").strip()
    return any(section == target or section.startswith(f"{target}.") or section.startswith(f"{target}(") for target in targets)


# A defined-term sentence: '"corner parcel" means ...' (straight or curly
# quotes). The span runs from the quoted term to the first sentence-final
# period — the (?!\d) lookahead keeps internal decimals ('0.6 metres above
# grade') from ending the definition early, mirroring the shared
# sentence-period discipline.
_DEFINITION_SENTENCE_RE = re.compile(r"[\"“][^\"”]{1,80}[\"”]\s+means\b.*?\.(?!\d)", re.DOTALL)
# 'no maximum building depth where the minimum building setback ... is 3.0 m'
# — an allowance whose where-clause carries the number.
_ALLOWANCE_TRIGGER_RE = re.compile(r"\bno\s+(?:maximum|minimum)\b[^.;]{0,200}\bwhere\b[^.;]{0,200}$")
# Text immediately AFTER a value that marks it as a ratio/proportion
# coefficient rather than an absolute cap: "0.25 multiplied by the site
# area", "0.5 times the parcel area", "8 % of the floor area".
_COEFFICIENT_AFTER_RE = re.compile(
    r"\s*(?:multiplied\s+by|times\b|x\s|×|(?:per\s?cent|percent|%)\s+of|of\s+the\s+(?:site|parcel|lot|floor))",
    re.IGNORECASE,
)
# A "N to M units" range anywhere in the evidence (groups: low, high). The unit
# noun may be separated from the range by qualifiers ("1 to 3 small-scale
# multi-unit dwelling units"), so the noun is matched via a bounded lookahead
# rather than requiring it immediately after the high bound — otherwise a
# lower-bound count ("1") mis-extracted as the lot maximum escapes the
# range_bound_not_maximum guard (a real false-verify class). The lookahead stops
# at a sentence/clause break so it never spans into an unrelated clause.
_UNIT_RANGE_IN_TEXT_RE = re.compile(
    r"\b(\d+)\s*(?:to|-|–|through)\s*(\d+)\b(?=[^.;:\n]{0,40}\b(?:units?|storeys?|stories|dwellings?|dwelling\s+units?)\b)",
    re.IGNORECASE,
)


def evidence_shape_gaps(candidate: dict[str, Any], evidence: dict[str, Any] | None) -> list[str]:
    """Gaps from the SHAPE of the sentence carrying the candidate's value.

    Three live Calgary P9 leak classes, all field-check-invisible because the
    value, unit, and scope words really are present in the evidence:

    - ``definition_not_rule``: the value sits inside a defined-term sentence
      ('"corner parcel" means a parcel ... not exceeding 135 degrees') —
      vocabulary, not a regulation.
    - ``allowance_trigger_threshold``: the value sits in a 'no
      maximum/minimum ... where ...' clause — the threshold that UNLOCKS an
      allowance, not a requirement.
    - ``value_bound_to_foreign_unit``: every visible occurrence of a
      unit-less candidate's value is glued to a measure of something else
      ('135 degrees' under a dwelling_units claim).
    """
    if not evidence:
        return []

    gaps: list[str] = []
    value = candidate.get("value")
    value_tokens = re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    evidence_text = " ".join(
        str(evidence.get(field) or "")
        for field in ("table_title", "row_header", "column_header", "cell_value", "evidence_text")
    )
    lowered = evidence_text.lower().replace(",", "")
    if not value_tokens or not lowered:
        return gaps
    token = value_tokens[0].lower()

    occurrences = [
        match
        for match in re.finditer(rf"(?<![\d.]){re.escape(token)}(?!\.?\d)", lowered)
        if not numeric_occurrence_is_reference(lowered, match.start(), match.end())
    ]
    if occurrences:
        definition_spans = [match.span() for match in _DEFINITION_SENTENCE_RE.finditer(lowered)]
        if definition_spans and all(
            any(start <= occ.start() < end for start, end in definition_spans) for occ in occurrences
        ):
            gaps.append("definition_not_rule")

        def _sentence_start(position: int) -> int:
            last = 0
            for match in re.finditer(r"\.(?!\d)", lowered[:position]):
                last = match.end()
            return last

        if all(
            _ALLOWANCE_TRIGGER_RE.search(lowered[_sentence_start(occ.start()):occ.start()]) for occ in occurrences
        ):
            gaps.append("allowance_trigger_threshold")

        # A setback value glued to a "private maintenance easement" is the
        # EASEMENT width that UNLOCKS a (zero) setback, not the setback itself
        # (Calgary R-CG s.539(4): "the minimum building setback from a side
        # property line may be reduced to a zero setback where ... a 1.2 metre
        # private maintenance easement"). Verifying it publishes a 1.2 m minimum
        # side setback the bylaw never states. Hold when EVERY occurrence of the
        # value is immediately bound to "easement" — the real correct setbacks
        # (s.538(1)/539(1) "is 1.2 m") are not, so they still verify.
        if str(candidate.get("rule_object") or "") == "setback" and all(
            re.search(r"\beasement\b", lowered[occ.end(): occ.end() + 45]) for occ in occurrences
        ):
            gaps.append("allowance_trigger_threshold")

    if not str(candidate.get("unit") or "").strip() and value_bound_to_foreign_measure(
        evidence_text, value, candidate.get("rule_object")
    ):
        gaps.append("value_bound_to_foreign_unit")

    # The two LLM-lane gates below target FLATTENED CLAUSE evidence only.
    # Structured table cells (matrix_anchor / table_cell) are already proven
    # column-by-column by the matrix binding, which correctly disambiguates
    # the per-column dwelling/storey values — applying a text-shape count gate
    # there wrongly reviews real verified table rules.
    is_structured_table = bool(evidence.get("matrix_anchor")) or str(
        evidence.get("evidence_type") or ""
    ) in {"table_cell", "table_row"}

    # Coefficient operand: every visible occurrence of the value is glued to a
    # ratio phrase ("0.25 multiplied by the site area", "0.5 times the parcel
    # area", "8% of the floor area"). The number is a COEFFICIENT in an
    # FSR/proportion calculation, not an absolute m2/m/count cap — extracting
    # it as one (Vancouver: floor_area <= 0.25 m2 from "the lesser of (a) 0.25
    # multiplied by the site area; (b) 186 m2") is a real LLM-lane false-verify.
    if occurrences and not is_structured_table and all(
        _COEFFICIENT_AFTER_RE.match(lowered[occ.end():]) for occ in occurrences
    ) and not _is_coverage_percent_cap(candidate, lowered, occurrences):
        gaps.append("coefficient_operand_not_value")

    # Range-bound / ambiguous-scope under-count: a count family (dwelling
    # units / storeys) whose value is NOT the largest same-family value the
    # source region offers, under a scope that does not uniquely select it.
    # Two shapes, both from the LLM flattening a multi-cell table into one
    # pack: "1 to 3 Units; 4 to 6 Units" -> dwelling_units <= 3 for the lot
    # (lot max is 6); "Front Principal ... 3 storeys ... Rear Principal ... 2
    # storeys" -> storeys <= 2 for a generic "principal building" (front
    # allows 3). The value is real but belongs to one column; review, never
    # verify, unless the scope carries a disambiguator (front/rear/accessory).
    if str(candidate.get("rule_object") or "") in {"dwelling_units", "storeys"} and value_tokens and not is_structured_table:
        applies = str(candidate.get("applies_to") or "").strip().lower()
        condition = str(candidate.get("condition") or "").lower()
        disambiguators = {"front", "rear", "accessory", "interior", "side", "corner", "end"}
        has_disambiguator = any(word in f"{applies} {condition}" for word in disambiguators)
        if not has_disambiguator:
            try:
                claimed = float(value_tokens[0])
            except ValueError:
                claimed = None
            # The pack source_context carries the sibling columns the flattened
            # evidence_text dropped; include it for this count check only.
            region = f"{lowered} {str(evidence.get('source_context') or '').lower()}"
            same_unit = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:units?|storeys?|stories)\b")
            present = [float(x) for x in same_unit.findall(region)]
            ranges = [float(m.group(2)) for m in _UNIT_RANGE_IN_TEXT_RE.finditer(region)]
            if claimed is not None and any(v > claimed for v in present + ranges):
                gaps.append("range_bound_not_maximum")

    return gaps


def _is_coverage_percent_cap(candidate: dict[str, Any], lowered: str, occurrences: list[re.Match[str]]) -> bool:
    if str(candidate.get("rule_object") or "") not in {"lot_coverage", "impervious_surface"}:
        return False
    if str(candidate.get("unit") or "").strip() not in {"%", "percent", "per cent", "percentage"}:
        return False
    if not any(term in lowered for term in ("maximum", "not exceed", "up to", "coverage")):
        return False
    for occ in occurrences:
        after = lowered[occ.end(): occ.end() + 80]
        if re.match(r"\s*(?:%|per\s?cent|percent)\s+of\s+the\s+(?:site|parcel|lot)\s+area\b", after, re.IGNORECASE):
            return True
    return False
