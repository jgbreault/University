"""Deterministic support checks for candidate zoning rules.

Read this file as the "trust gate" of the project:

1. Zihao's extraction proposes a candidate rule.
2. The candidate cites one evidence unit.
3. This file checks whether that evidence proves the candidate's value, unit,
   operator, rule object, and scope.
4. Only fully supported candidates become verified rules for GIS.

Important: this file should stay conservative. When the evidence is unclear,
the rule should go to review instead of being verified.
"""

from __future__ import annotations

from typing import Any

from .conflict_guard import build_cross_family_index, cross_family_gaps
from .consensus import build_source_agreement, corroborating_sources
from .decision_policy import (
    ADVISORY_GAPS,
    CRITICAL_REJECTION_GAPS,
    MISSING_SCOPE_GAPS,
    NOT_USED_GAPS,
    TABLE_REVIEW_GAPS,
    VERIFIED,
    evidence_shape_gaps,
    not_used_gaps_for_candidate,
    target_scope_gaps_for_candidate,
    verification_decision_from_gaps,
)
from .domain_schema import (
    GENERIC_TABLE_COLUMN_CONDITION_WORDS,
    KNOWN_RULE_OBJECTS,
    NUMERIC_RULE_OBJECTS,
    text_words,
)
from .domain_schema import matches_text_pattern
from .domain_schema import gis_relevance_for_rule_object
from .normalization_rules import (
    get_normalization,
    material_condition_cue_extras,
    non_material_condition_words,
    rule_object_text_cue_extras,
)
from .applicability import (
    parse_applicability,
    selector_matches_text,
    vocabulary_from_normalization,
)
from .normalization import normalize_candidate as _normalize_candidate, normalization_trace as _normalization_trace
from .rule_claims import (
    canonical_rule_key,
    evidence_strength,
    merge_proof_traces,
    review_priority,
    verification_label_from_gaps,
)
from .table_natural_logic import table_proof_status, table_proof_trace, table_proof_type
from .text_span_proof import (
    text_span_proof_status,
    enumerated_branch_gap as _enumerated_branch_gap,
    text_span_proof_trace,
    text_span_support_gaps,
)
from .support_checks import (
    applies_to_supported as _applies_to_supported,
    contains_unit as _contains_unit,
    contains_value as _contains_value,
    evidence_with_parent_context as _evidence_with_parent_context,
    family_expects_metric as _family_expects_metric,
    generic_applies_to_words as _generic_applies_to_words,
    is_imperial_unit as _is_imperial_unit,
    has_multiple_numeric_values as _has_multiple_numeric_values,
    local_source_context as _local_source_context,
    operator_supported as _operator_supported,
    rule_object_supported as _rule_object_supported,
    rule_object_unit_compatible as _rule_object_unit_compatible,
    scope_supported as _scope_supported,
    target_words_from_config as _target_words_from_config,
    value_local_window as _value_local_window,
)
from .proof_trace import (
    align_proof_trace_with_decision as _align_proof_trace_with_decision,
    apply_table_trace_to_support_checks as _apply_table_trace_to_support_checks,
    has_unresolved_exception_cue as _has_unresolved_exception_cue,
    human_reason as _human_reason,
    proof_decision_mismatches as _proof_decision_mismatches,
    repair_table_context_gaps as _repair_table_context_gaps,
    table_refutation_gaps as _table_refutation_gaps,
    text_proof_trace as _text_proof_trace,
)
from .proof_dag import build_proof_dag


TABLE_EVIDENCE_TYPES = {"table_row", "table_cell"}

# These mappings connect proof_trace claims back to the older support-gap
# system. They let table proof repair exactly the matching gap and no more.
CLAIM_TO_SUPPORT_GAP = {
    "rule_object": "rule_object_not_supported",
    "constraint_scope": "constraint_scope_not_supported",
    "applies_to": "applies_to_not_supported",
    "operator": "operator_not_supported",
    "value": "value_not_found_in_evidence",
    "unit": "unit_not_found_in_evidence",
}


def _text_words(text: str) -> set[str]:
    """Return normalized words used for simple overlap checks."""
    return text_words(text)


from .domain_schema import to_float as _to_float


# Per-family words that must appear in a matrix row/cell for that family to be
# evidenced there. Shared by the row-family check below and the table context
# checks; a row label that names a DIFFERENT family (the "Impervious Surfaces"
# sub-row under the "Maximum Lot Coverage" banner) must refuse candidates of
# the banner's family.
_FAMILY_ROW_TERMS = {
    "height": {"height"},
    "storeys": {"storey"},
    "setback": {"setback", "yard"},
    "building_separation": {"separation", "between"},
    "lot_coverage": {"coverage"},
    "impervious_surface": {"impervious"},
    "lot_area": {"area"},
    "floor_space_ratio": {"ratio", "fsr"},
    "dwelling_units": {"dwelling", "unit"},
}


def _matrix_row_family(row_label: str) -> str | None:
    """Most-specific family named by an anchor row label.

    Segments are checked LAST first: "Maximum Lot Coverage | Impervious
    Surfaces" must resolve to impervious_surface (the sub-row), not to the
    section banner's lot_coverage.
    """
    from .support_checks import _rule_object_from_patterns
    from .domain_schema import PLAIN_ONLY_RULE_OBJECT_PATTERNS, TEXT_RULE_OBJECT_PATTERNS

    patterns = [*PLAIN_ONLY_RULE_OBJECT_PATTERNS, *TEXT_RULE_OBJECT_PATTERNS]
    for segment in reversed([part.strip() for part in str(row_label or "").split("|")]):
        family = _rule_object_from_patterns(segment.lower(), patterns)
        if family:
            return family
    return None


def _matrix_column_binding(
    config: dict[str, Any],
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None,
    raw_candidate: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Bind a column-scoped claim to its table band, or return None (inert).

    The contract is strictly additive: None (no matrix anchor on the
    evidence, or no parsed applicability on the candidate) leaves every
    legacy check exactly as it is today. A binding can:

    - SUPPORT the column claim (the claimed band really holds the value),
      which satisfies the legacy target-scope gate and the table
      applies_to/condition checks;
    - REFUTE it (``column_value_mismatch`` — the value lives in a different
      column: 55% claimed for the 5-6 unit column), a critical rejection;
    - HOLD it for review when the claim drops a binding qualifier
      (``column_qualifier_not_claimed`` — 45% without its Frequent Transit
      condition; ``conditional_cell_condition_missing`` — 40% without its
      "Lots <= 567 m2" branch) or names a column the matrix cannot find
      (``applicability_not_grounded``) or sits on a row whose label names a
      different rule family (``anchored_row_family_mismatch`` — the
      Impervious row extracted as lot_coverage).
    """
    if not evidence:
        return None
    anchor = evidence.get("matrix_anchor")
    if not anchor:
        return None
    vocabulary = vocabulary_from_normalization(get_normalization(config))
    block = parse_applicability(candidate, vocabulary)
    if raw_candidate is not None and not (block or {}).get("selectors"):
        # Normalization hints rewrite applies_to toward GIS vocabulary
        # ("Rowhouse; Small-Scale Multi-Unit (...)" becomes "lot" or
        # "Accessory Buildings"), erasing the column words. The RAW extracted
        # candidate still carries them — geometry binds against the source's
        # own words, so fall back to the raw fields.
        raw_block = parse_applicability(raw_candidate, vocabulary)
        if (raw_block or {}).get("selectors"):
            merged_qualifiers = list((raw_block or {}).get("qualifiers") or [])
            for qualifier in (block or {}).get("qualifiers") or []:
                if qualifier not in merged_qualifiers:
                    merged_qualifiers.append(qualifier)
            block = {**raw_block, "qualifiers": merged_qualifiers}
    selectors = (block or {}).get("selectors") or []
    if not selectors:
        return None

    result: dict[str, Any] = {
        "applicability": block,
        "gaps": [],
        "supports_column": False,
        "supports_applies_to": False,
        "supports_condition": False,
        "range_max_evidenced": False,
        "claimed_bands": [],
    }

    # Row-family discipline: the row label is the regulation. A label naming
    # a different family refuses the bind UNLESS the claimed cells themselves
    # evidence the candidate's family ("4.0 m | 1 storey" carries storeys
    # even though its row resolves to height).
    family = str(candidate.get("rule_object") or "")
    row_family = _matrix_row_family(anchor.get("row_label") or "")
    bands = anchor.get("bands") or []

    claimed: set[int] = set()
    for selector in selectors:
        hit = [band["key"] for band in bands if selector_matches_text(selector, band.get("header_text"), vocabulary)]
        if not hit:
            result["gaps"].append("applicability_not_grounded")
            return result
        claimed.update(hit)
    result["claimed_bands"] = sorted(claimed)
    claimed_bands = [band for band in bands if band["key"] in claimed]

    if row_family and family and row_family != family:
        family_terms = _FAMILY_ROW_TERMS.get(family, set())
        cell_words = _text_words(" ".join(str(band.get("text") or "") for band in claimed_bands))
        if not (family_terms & cell_words):
            result["gaps"].append("anchored_row_family_mismatch")
            return result

    value = _to_float(candidate.get("value"))
    if value is None:
        return result

    def _holds(numbers: list[float] | None) -> bool:
        return any(abs(number - value) <= 0.01 for number in (numbers or []))

    value_bands = {band["key"] for band in bands if _holds(band.get("numbers"))}
    supported = bool(claimed & value_bands)
    if not supported:
        refutable = bool(value_bands) or any(band.get("numbers") for band in claimed_bands)
        if refutable:
            result["gaps"].append("column_value_mismatch")
        return result

    # Conditional cells: a claimed band whose cell splits into branches only
    # supports the claim through the branch that carries the value — and the
    # candidate must CLAIM that branch's condition.
    qualifiers = (block or {}).get("qualifiers") or []
    thresholds = {
        (qualifier.get("comparator"), qualifier.get("value"))
        for qualifier in qualifiers
        if qualifier.get("type") == "lot_area_threshold"
    }
    overlays = {qualifier.get("name") for qualifier in qualifiers if qualifier.get("type") == "overlay"}
    condition_supported = False
    for band in claimed_bands:
        branches = band.get("branches") or []
        if branches and _holds(band.get("numbers")):
            matching = [
                branch
                for branch in branches
                if _holds(branch.get("numbers"))
                and (branch.get("comparator"), branch.get("threshold")) in thresholds
            ]
            value_branches = [branch for branch in branches if _holds(branch.get("numbers"))]
            if value_branches and not matching:
                result["gaps"].append("conditional_cell_condition_missing")
                return result
            if matching:
                condition_supported = True

    # Overlay qualifiers bound to the column header ("Frequent Transit
    # Network Area Only" on the 5-6 column): the overlay must be claimed when
    # every band that ACTUALLY HOLDS THE VALUE carries it. Testing all claimed
    # bands instead let an over-broad selector ("Small-Scale Multi-Unit", no
    # unit range -> bands 1,2,3) dodge the guard for a value present ONLY in
    # the overlay band (45% lives only in band 3): bands 1,2 lack the overlay
    # so "every claimed band" was False and the overlay was not required.
    # Restricting to value-bearing bands keeps the legitimate existential
    # reading for a value available WITHOUT the overlay (impervious 70%, in
    # both Rowhouse band 0 and FTN band 3 -> band 0 has no overlay -> not
    # required) while forcing it when the value's only home is the overlay band.
    vocabulary_overlays = vocabulary.get("overlays", {})
    value_claimed_bands = [band for band in claimed_bands if _holds(band.get("numbers"))]

    def _flat_header(band: dict[str, Any]) -> str:
        # Header stacks join lines with " | " ("Frequent Transit | Network
        # Area Only") — flatten so multi-word overlay names match.
        return " ".join(str(band.get("header_text") or "").lower().replace("|", " ").split())

    for overlay_name, aliases in vocabulary_overlays.items():
        in_every_value_band = bool(value_claimed_bands) and all(
            any(str(alias).lower() in _flat_header(band) for alias in aliases)
            for band in value_claimed_bands
        )
        if in_every_value_band and overlay_name not in overlays:
            result["gaps"].append("column_qualifier_not_claimed")
            return result
        if overlay_name in overlays and in_every_value_band:
            condition_supported = True

    # Dwelling-unit ranges: a closed "N to M Units" band cell whose upper
    # bound IS the claimed value evidences the maximum (the band row label
    # says "Permitted ..." — the range is the permission envelope).
    if family == "dwelling_units":
        for band in claimed_bands:
            numbers = band.get("numbers") or []
            if len(numbers) >= 2 and abs(numbers[-1] - value) <= 0.01:
                result["range_max_evidenced"] = True

    result["supports_column"] = True
    result["supports_applies_to"] = True
    result["supports_condition"] = condition_supported
    return result


def _table_context_gaps(
    config: dict[str, Any],
    candidate: dict[str, Any],
    evidence: dict[str, Any],
    binding: dict[str, Any] | None = None,
) -> list[str]:
    """Return table-specific support gaps for table-cell evidence.

    Table proof needs more than the cell value. The title, row header, and column
    header must also support what the candidate claims. A matrix-column
    ``binding`` (geometry-proven) supersedes the word-overlap applies_to /
    condition checks and the legacy target-scope column gate; its own gaps
    (mismatch / unclaimed qualifier / missing branch condition) are appended.
    """
    if evidence.get("evidence_type") != "table_cell":
        return []

    gaps: list[str] = []
    table_text = " ".join(
        str(evidence.get(key) or "")
        for key in ("table_title", "row_header", "column_header", "cell_value")
    )
    table_words = _text_words(table_text)
    rule_object = candidate.get("rule_object")

    required_by_rule_object = {
        "height": {"height"},
        "storeys": {"storey"},
        "setback": {"setback", "yard"},
        "building_separation": {"separation", "between"},
        "lot_coverage": {"coverage"},
        "impervious_surface": {"impervious"},
        "lot_area": {"area"},
        "floor_space_ratio": {"ratio", "fsr"},
        "dwelling_units": {"dwelling", "unit"},
    }
    required_terms = required_by_rule_object.get(str(rule_object or ""))
    if required_terms and not (required_terms & table_words):
        gaps.append("table_rule_object_not_supported")

    applies_to = str(candidate.get("applies_to") or "").strip()
    if applies_to and not (binding or {}).get("supports_applies_to"):
        applies_words = _text_words(applies_to) - _generic_applies_to_words(config)
        table_scope_words = _text_words(
            " ".join(
                str(evidence.get(key) or "")
                for key in ("row_header", "column_header", "table_title", "evidence_text")
            )
        )
        if applies_words and not (applies_words & table_scope_words):
            gaps.append("table_applies_to_not_supported")

    condition = str(candidate.get("condition") or "").strip()
    column_header = str(evidence.get("column_header") or "").strip()
    if (
        condition
        and column_header
        and not (binding or {}).get("supports_condition")
        and not (_text_words(condition) & _text_words(column_header + " " + table_text))
    ):
        gaps.append("table_condition_not_supported")

    if not (binding or {}).get("supports_column") and not _table_column_in_target_scope(config, evidence, candidate):
        gaps.append("table_column_not_target_scope")

    gaps.extend((binding or {}).get("gaps") or [])

    return gaps


def _table_column_in_target_scope(
    config: dict[str, Any],
    evidence: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> bool:
    """Check whether a table column is relevant to the configured target concept."""
    if (
        candidate
        and candidate.get("source_stream") == "deterministic_table"
        and candidate.get("relevance_category") in {"direct", "generic_applicable"}
    ):
        return True
    column_header = str(evidence.get("column_header") or "").strip()
    if not column_header or _contains_value(column_header, evidence.get("cell_value")):
        return True
    column_words = _text_words(column_header)
    if not column_words:
        return True
    if column_words & GENERIC_TABLE_COLUMN_CONDITION_WORDS:
        return True

    target_words = _target_words_from_config(config)
    if not target_words:
        return True
    matched_words = column_words & target_words
    required_matches = 1 if len(column_words) == 1 else 2
    return len(matched_words) >= required_matches


def _table_review_gaps(
    config: dict[str, Any],
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None,
    binding: dict[str, Any] | None = None,
) -> list[str]:
    """Apply the conservative table auto-verification gate.

    If structured table proof is incomplete, the candidate is sent to review.
    This protects us from trusting table cells without enough row/column context.
    """
    verification_config = config.get("verification", {})
    if (
        evidence
        and bool(verification_config.get("structured_table_verification", True))
        and _table_has_verifiable_structure(config, candidate, evidence, binding)
    ):
        return []

    gaps: list[str] = []
    if (
        candidate.get("extraction_method") == "deterministic_table_evidence"
        and not bool(verification_config.get("auto_verify_table_fallback_candidates", False))
    ):
        gaps.append(TABLE_REVIEW_GAPS["deterministic_table_evidence"])
    if (
        evidence
        and evidence.get("evidence_type") == "table_cell"
        and not bool(verification_config.get("auto_verify_table_cell_candidates", False))
    ):
        gaps.append(TABLE_REVIEW_GAPS["table_cell"])
    if (
        evidence
        and evidence.get("evidence_type") in TABLE_EVIDENCE_TYPES
        and not bool(verification_config.get("auto_verify_table_evidence_candidates", False))
    ):
        gaps.append(TABLE_REVIEW_GAPS["table_evidence"])
    return gaps


def _table_has_verifiable_structure(
    config: dict[str, Any],
    candidate: dict[str, Any],
    evidence: dict[str, Any],
    binding: dict[str, Any] | None = None,
) -> bool:
    """Return True only when a table cell has enough structured proof to verify."""
    if evidence.get("evidence_type") not in TABLE_EVIDENCE_TYPES:
        return False
    table_text = " ".join(
        str(evidence.get(key) or "")
        for key in ("table_title", "row_header", "column_header", "cell_value")
    )
    table_context_text = " ".join(
        part
        for part in [
            table_text,
            str(evidence.get("evidence_text") or ""),
            str(evidence.get("source_context") or ""),
        ]
        if part
    )
    if not table_text.strip():
        return False
    if candidate.get("value") is not None and not evidence.get("cell_value") and not _contains_value(table_text, candidate.get("value")):
        return False
    if not _contains_unit(table_text, candidate.get("unit")):
        return False
    if candidate.get("rule_object") not in KNOWN_RULE_OBJECTS:
        return False
    if not _rule_object_unit_compatible(candidate):
        return False
    binding_supports = bool((binding or {}).get("supports_column"))
    if (binding or {}).get("gaps"):
        # A binding that found a problem (cross-column value, dropped
        # qualifier, missing branch condition, row-family mismatch) must not
        # auto-verify regardless of what the legacy word checks think.
        return False
    if not binding_supports and not _table_column_in_target_scope(config, evidence, candidate):
        return False
    if not _table_scope_allowed(config, candidate, evidence, table_context_text):
        return False
    if (
        candidate.get("rule_object") == "dwelling_units"
        and str(candidate.get("operator") or "") in {"<=", "max", "maximum"}
        and "maximum" not in table_text.lower()
        and not str(candidate.get("rule_key") or "").lower().startswith("max")
        # A geometry-bound closed range ("1 to 3 Units") whose upper bound IS
        # the claimed value states the permission envelope's maximum.
        and not (binding or {}).get("range_max_evidenced")
    ):
        # A range such as "5 to 6 Units" can explain the upper bound, but it is
        # not enough by itself for the final GIS contract unless the table/rule
        # explicitly marks the value as a maximum.
        return False
    return True


def _table_scope_allowed(
    config: dict[str, Any],
    candidate: dict[str, Any],
    evidence: dict[str, Any],
    table_text: str,
) -> bool:
    """Decide whether table scope context permits auto-verification.

    Two modes, set by ``verification.table_scope_pattern_mode``:

    * ``allow_list`` (legacy): a structurally-proven cell may verify ONLY if it
      matches a hand-written scope pattern. This makes the patterns a per-rule
      whitelist -- safe for one tuned bylaw, but it sends a correct, fully
      proven cell to review whenever no human pre-wrote a pattern for it, and it
      does not transfer to a new city.
    * ``deny_ambiguous`` (default): structural proof alone permits the cell;
      patterns are consulted only to *quarantine* a column a human has flagged
      as ambiguous, via an optional ``"action": "review"`` on the pattern.

    Either way this check sits BEHIND the full structural gate in
    :func:`_table_has_verifiable_structure` (value/unit/rule_object/unit-compat/
    target-scope) and the TabVer refutations, so it can only move an
    already-proven cell out of review -- never admit an unproven one.
    """
    verification_config = config.get("verification", {})
    mode = str(verification_config.get("table_scope_pattern_mode", "deny_ambiguous"))
    patterns = verification_config.get("structured_table_scope_patterns", [])
    candidate_text = " ".join(
        str(part)
        for part in [
            f"{candidate.get('constraint_type') or ''} {candidate.get('rule_object') or ''}",
            candidate.get("rule_object"),
            candidate.get("constraint_type"),
            candidate.get("constraint_scope"),
            candidate.get("applies_to"),
            candidate.get("condition"),
            candidate.get("exception"),
            candidate.get("value"),
            candidate.get("unit"),
            candidate.get("rule_key"),
            evidence.get("table_title"),
            evidence.get("row_header"),
            evidence.get("column_header"),
            evidence.get("cell_value"),
        ]
        if part is not None
    ).lower()
    match_text = f"{table_text} {candidate_text}"
    rule_object = str(candidate.get("rule_object") or "")
    any_match = False
    matched_review = False
    for pattern in patterns:
        rule_objects = pattern.get("rule_objects") or pattern.get("rule_object")
        if isinstance(rule_objects, str):
            rule_objects = [rule_objects]
        if rule_objects and rule_object not in {str(item) for item in rule_objects}:
            continue
        if matches_text_pattern(match_text, pattern):
            any_match = True
            if str(pattern.get("action") or "allow") == "review":
                matched_review = True

    if mode == "allow_list":
        # Legacy whitelist behavior: no patterns means allow-all; otherwise the
        # cell must match a pattern.
        return True if not patterns else any_match
    # deny_ambiguous: structural proof is sufficient. A matched pattern carrying
    # "action": "review" quarantines a known-ambiguous column back to review.
    return not matched_review


def _verification_status(support_gaps: list[str], slim_decision: str) -> str:
    """Return the legacy verification_status field used by older outputs.

    Derived FROM the active decision instead of re-implementing the gap
    precedence: the two used to order NOT_USED vs CRITICAL gaps differently,
    so a candidate carrying both could report status='not_used' next to
    decision='rejected' in the same record.
    """
    if slim_decision == "verified":
        return "verified"
    if slim_decision == "not_used":
        return "not_used"
    if slim_decision == "rejected":
        return "unsupported"
    if MISSING_SCOPE_GAPS & set(support_gaps):
        return "missing_scope"
    return "needs_human_review"


DIRECTIONAL_MIN_OPERATORS = {">=", "≥", ">", "min", "minimum", "at_least"}
DIRECTIONAL_MAX_OPERATORS = {"<=", "≤", "<", "max", "maximum", "not_exceed"}

# Extractor review reasons the DETERMINISTIC verifier now fully covers on its
# own, so they make the extractor's review request advisory rather than
# blocking. ``operator_missing_from_extraction`` is resolved by family-direction
# normalization plus the operator_supported + direction gates, which validate
# the filled operator against the evidence wording. Source-fidelity reasons
# (e.g. rag_context_mismatch, source_quote_not_in_retrieved_pack) are NOT here:
# the gates cannot see real-source fidelity, so those keep blocking.
SOFT_EXTRACTION_REVIEW_REASONS = {"operator_missing_from_extraction"}


def _value_is_absolute_lesser_of_branch(candidate: dict[str, Any], support_text: str) -> bool:
    if str(candidate.get("rule_object") or "") != "floor_area":
        return False
    if str(candidate.get("operator") or "") not in DIRECTIONAL_MAX_OPERATORS:
        return False
    if str(candidate.get("unit") or "") not in {"m2", "m²", "sq m", "square metres", "square meters"}:
        return False
    lowered = str(support_text or "").lower()
    if "must not exceed" not in lowered or "lesser of" not in lowered:
        return False
    token = str(candidate.get("value") or "").strip()
    if not token:
        return False
    index = lowered.find(token.lower())
    if index < 0:
        return False
    after = lowered[index + len(token): index + len(token) + 40]
    return any(unit in after for unit in ("m2", "m²", "sq. m", "sq m", "square metre", "square meter"))


def _value_has_same_sentence_operator_parent(
    candidate: dict[str, Any],
    support_text: str,
    value_window: str = "",
) -> bool:
    token = str(candidate.get("value") or "").strip()
    if not token:
        return False
    lowered = str(support_text or "").lower()
    token_l = token.lower()
    # Anchor on the SAME value occurrence the scope window selected, not merely
    # the first textual hit. Otherwise, when a page repeats a value, a
    # neighbouring rule's occurrence (which may sit inside a 'maximum ...'
    # sentence) could lend its operator wording to this candidate and ground an
    # operator the candidate's own clause never states.
    window = str(value_window or "")
    base = lowered.find(window.lower()) if window else -1
    if base >= 0:
        local = window.lower().find(token_l)
        index = base + local if local >= 0 else lowered.find(token_l)
    else:
        index = lowered.find(token_l)
    if index < 0:
        return False
    sentence_start = lowered.rfind(".", 0, index) + 1
    prefix = lowered[sentence_start:index]
    operator = str(candidate.get("operator") or "")
    if operator in DIRECTIONAL_MAX_OPERATORS:
        return any(phrase in prefix for phrase in ("maximum", "not exceed", "up to", "limited to"))
    if operator in DIRECTIONAL_MIN_OPERATORS:
        return any(phrase in prefix for phrase in ("minimum", "not less", "no less", "at least"))
    return False


# Directional cue vocabulary for the filled-operator safety check (mirrors the
# phrases support_checks.operator_supported keys on).
_MAX_DIRECTION_CUES = ("maximum", "not exceed", "up to", "limited to", "no more than", "at most")
_MIN_DIRECTION_CUES = ("minimum", "not less", "no less", "at least")


def _filled_operator_direction_confirmed(
    candidate: dict[str, Any], support_text: str, value_window: str = ""
) -> bool:
    """Confirm a FAMILY-FILLED operator's direction in the value's own sentence.

    When the operator was synthesized from the rule family's direction (the
    extractor left it blank), it was NOT read from the clause, so before trusting
    it the verifier must see the matching direction word UNAMBIGUOUSLY in the
    value's own sentence. Returns False when that sentence states the OPPOSITE
    direction, carries BOTH directions (ambiguous), or NEITHER. This closes the
    inversion hole where a stray sibling-clause 'maximum'/'minimum' on the same
    line grounds a filled operator (e.g. a 'minimum gross floor area is 37 m2'
    clause mis-verified as a <= maximum cap). Applied only to filled operators,
    so extractor-provided operators keep their existing grounding behavior.
    """
    token = str(candidate.get("value") or "").strip().lower()
    if not token:
        return False
    lowered = str(support_text or "").lower()
    window = str(value_window or "")
    base = lowered.find(window.lower()) if window else -1
    if base >= 0:
        local = window.lower().find(token)
        index = base + local if local >= 0 else lowered.find(token)
    else:
        index = lowered.find(token)
    if index < 0:
        return False
    sentence_start = lowered.rfind(".", 0, index) + 1
    sentence_end = lowered.find(".", index)
    sentence = lowered[sentence_start: sentence_end if sentence_end >= 0 else len(lowered)]
    operator = str(candidate.get("operator") or "")
    if operator in DIRECTIONAL_MAX_OPERATORS:
        matching, opposite = _MAX_DIRECTION_CUES, _MIN_DIRECTION_CUES
    elif operator in DIRECTIONAL_MIN_OPERATORS:
        matching, opposite = _MIN_DIRECTION_CUES, _MAX_DIRECTION_CUES
    else:
        return False
    has_match = any(cue in sentence for cue in matching)
    has_opposite = any(cue in sentence for cue in opposite)
    return has_match and not has_opposite


def _family_direction_mismatch(config: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Return True when the operator contradicts the rule family's fixed direction.

    Each zoning family has a stable direction: dwelling_units is a maximum,
    setback/separation a minimum, etc. A candidate claiming the opposite
    direction -- e.g. a "3+ Bedroom Units" minimum-count row mis-typed as
    ``dwelling_units >= 1`` -- is an extraction error, not a real rule. This is
    config-driven via ``rule_family_direction`` and therefore reusable across
    cities; it replaces part of the safety work the hand-written table-scope
    whitelist used to do implicitly.
    """
    rule_object = str(candidate.get("rule_object") or "")
    direction = config.get("verification", {}).get("rule_family_direction", {}).get(rule_object)
    if direction not in {"min", "max"}:
        return False
    operator = str(candidate.get("operator") or "").strip()
    if not operator:
        return False
    if direction == "max" and operator in DIRECTIONAL_MIN_OPERATORS:
        return True
    if direction == "min" and operator in DIRECTIONAL_MAX_OPERATORS:
        return True
    return False


def _text_candidate_can_verify(
    config: dict[str, Any],
    candidate: dict[str, Any],
    support_checks: dict[str, bool],
    corroborating_source_count: int,
    text_span_gaps: list[str],
) -> bool:
    """Decide whether a Pipeline 5 *text* candidate may be auto-verified.

    Improvements #2 + #3. Text rules used to be blanket-routed to review. We now
    allow a text candidate into the GIS contract ONLY when:

    1. text verification is enabled in config;
    2. the rule object is in the configured ``gis_text_rule_contract``;
    3. every deterministic support check already passed (no relaxation -- this is
       the same gate table rules face);
    4. for numeric families, the value is numeric, the unit is compatible, and the
       operator direction matches the rule family (``min``/``max``);
    5. an independent source corroborates the exact rule (cross-source consensus),
       unless the rule family is explicitly listed in
       ``single_source_text_rule_contract``.

    Rule 4 filters projection/encroachment allowances mis-typed as setbacks.
    Rule 5 is the precision guard: single-source text rules can carry value/scope
    pairing errors (e.g. impervious 60% vs lot-coverage 60%) that no single-source
    check can catch, so most text rules still need another stream. The
    single-source allow-list is reserved for compact clause families where the
    same sentence normally carries the whole legal claim.
    """
    verification_config = config.get("verification", {})
    if not bool(verification_config.get("verify_text_candidates", False)):
        return False
    if text_span_gaps:
        return False
    rule_object = str(candidate.get("rule_object") or "")
    contract = {str(item) for item in verification_config.get("gis_text_rule_contract", [])}
    if rule_object not in contract:
        return False
    required_checks = (
        "value_supported",
        "unit_supported",
        "operator_supported",
        "rule_object_supported",
        "applies_to_supported",
        "scope_supported",
    )
    if not all(support_checks.get(check) for check in required_checks):
        return False
    if rule_object in NUMERIC_RULE_OBJECTS:
        if _to_float(candidate.get("value")) is None:
            return False
        if not _rule_object_unit_compatible(candidate):
            return False
        direction = verification_config.get("rule_family_direction", {}).get(rule_object)
        operator = str(candidate.get("operator") or "").strip()
        if direction == "min" and operator not in DIRECTIONAL_MIN_OPERATORS:
            return False
        if direction == "max" and operator not in DIRECTIONAL_MAX_OPERATORS:
            return False
    single_source_contract = {
        str(item)
        for item in verification_config.get("single_source_text_rule_contract", [])
    }
    requires_consensus = (
        bool(verification_config.get("require_text_consensus", True))
        and rule_object not in single_source_contract
    )
    if requires_consensus:
        # corroborating_source_count includes this candidate's own stream, so a
        # genuinely independent corroboration requires at least two streams.
        # (M7 NOTE: an in-clause co-location "association proof" was trialled to
        # promote single-source text candidates without a 2nd stream. It was
        # REVERTED — it introduced real false-verifies on Burnaby, e.g.
        # dwelling_units<=1 read from a "1 to 3 units" range, and
        # building_separation from a "greater than 1.0 m above grade" projection
        # clause. The consensus requirement is doing genuine safety work against
        # single-source mis-pairing; do not relax it without a stronger guard.)
        if corroborating_source_count < 2:
            return False
    return True


def verify_candidates(
    config: dict[str, Any],
    evidence_units: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Verify every candidate against its cited evidence unit.

    This is the main function to study. It does four things:
    1. look up the candidate's evidence;
    2. normalize the candidate into our contract;
    3. run support checks and collect support_gaps;
    4. split rules into verified or review/rejected output.
    """
    evidence_units = _evidence_with_parent_context(evidence_units)
    # Defensive lookup: a malformed unit without an evidence_id must not crash
    # the whole run (the citing candidate will hit source_evidence_id_not_found
    # instead), and on duplicate IDs the FIRST unit wins so a later duplicate
    # cannot silently swap the evidence a candidate is checked against.
    evidence_lookup: dict[str, dict[str, Any]] = {}
    for unit in evidence_units:
        evidence_id = str(unit.get("evidence_id") or "")
        if evidence_id and evidence_id not in evidence_lookup:
            evidence_lookup[evidence_id] = unit
    verified_rules: list[dict[str, Any]] = []
    review_rules: list[dict[str, Any]] = []

    # City-specific non-material condition vocabulary (district labels that are
    # not real legal qualifiers). Sourced from the normalization config so text
    # span proofs are reusable; defaults to Burnaby's R1 set.
    norm = get_normalization(config)
    non_material_words = non_material_condition_words(norm)
    # Per-city ADDITIVE cue vocabulary (capability knobs; absent config means
    # byte-identical behavior). Computed once per run, threaded into the three
    # proof layers exactly like non_material_words.
    cue_extras = rule_object_text_cue_extras(norm)
    material_cue_extras = material_condition_cue_extras(norm)

    # Cross-source consensus index (improvements #2/#3). Built from normalized
    # candidates so a table-image rule and a text-block rule describing the same
    # constraint share a key. Used only to *gate* text auto-verification; it never
    # overrides a deterministic support gap.
    normalized_candidates = [
        _normalize_candidate(candidate, evidence_lookup.get(candidate.get("evidence_id", "")), config)
        for candidate in candidates
    ]
    source_agreement = build_source_agreement(normalized_candidates)
    # Cross-family value-collision index: catches errors both streams share, which
    # consensus cannot (a sibling family claiming the same value+unit+scope).
    cross_family_index = build_cross_family_index(normalized_candidates, config)

    # Reuse the normalized candidates computed for the consensus index above —
    # normalize_candidate does the heaviest regex/text work per candidate, and
    # re-running it here with identical arguments doubled the hot path.
    for index, (candidate, candidate_for_checks) in enumerate(
        zip(candidates, normalized_candidates), start=1
    ):
        # Every candidate must cite one evidence unit. If the evidence ID cannot
        # be found, the rule cannot be trusted.
        evidence = evidence_lookup.get(candidate.get("evidence_id", ""))
        normalization_trace = _normalization_trace(candidate, candidate_for_checks, evidence)
        support_gaps: list[str] = []
        if not evidence:
            support_gaps.append("source_evidence_id_not_found")
            evidence_text = ""
            source_context = ""
        else:
            evidence_text = evidence.get("evidence_text", "")
            source_context = evidence.get("source_context", "")
        if str(candidate_for_checks.get("extraction_method") or "") == "native_v3_clause":
            source_context = evidence_text
        # Build different support windows for different checks. Value/unit checks
        # can use the direct evidence/cell value; scope checks use a tighter local
        # window so unrelated page text cannot accidentally prove the rule.
        local_context = _local_source_context(evidence_text, source_context)
        support_text = "\n".join(part for part in [evidence_text, source_context] if part)
        table_support_text = "\n".join(
            str(evidence.get(key) or "")
            for key in ("table_title", "row_header", "column_header", "cell_value")
        ) if evidence else ""
        local_support_text = "\n".join(part for part in [evidence_text, table_support_text, local_context] if part)
        value_support_text = "\n".join(
            part
            for part in [evidence_text, str(evidence.get("cell_value") or "") if evidence else ""]
            if part
        )
        text_span_trace: dict[str, dict[str, Any]] = {}
        text_span_gaps: list[str] = []
        table_condition_trace: dict[str, dict[str, Any]] = {}
        table_condition_gaps: list[str] = []
        if evidence and evidence.get("evidence_type") not in TABLE_EVIDENCE_TYPES:
            text_span_trace = text_span_proof_trace(
                candidate_for_checks,
                support_text,
                non_material_words,
                cue_extras,
                material_cue_extras,
            )
            text_span_gaps = text_span_support_gaps(candidate_for_checks, text_span_trace)
            # Prose multi-branch disjunction gate: an enumerated clause
            # ("(a) 5.0 m at a side property line; (b) 3.0 m at a rear ...")
            # states several values, each gated by its own qualifier. A
            # candidate claiming one branch's value without proving THAT
            # branch's discriminator (or mispairing it with a sibling's) must
            # not verify — the prose analogue of the table conditional-cell
            # gate. Uses the value-window when the clause is one of several
            # on the page, else the full support text.
            # Uses the FULL clause text (not the value-window): the gate must
            # see EVERY branch of the enumeration to know the value is one of
            # several competing branch values. A narrowed window would isolate
            # a single branch and silently disable the gate.
            branch_support_text = (
                evidence_text
                if str(candidate_for_checks.get("extraction_method") or "") == "native_v3_clause"
                else support_text
            )
            branch_gap = _enumerated_branch_gap(candidate_for_checks, branch_support_text)
            if branch_gap:
                text_span_gaps = [*text_span_gaps, branch_gap]
        elif evidence and evidence.get("evidence_type") in TABLE_EVIDENCE_TYPES:
            # Table cells often prove value/unit/operator, but their row/column
            # text may omit a legal qualifier such as "4 units only" or
            # "frequent transit network area only". Reuse the text-span
            # condition proof for table context so a cleaner alternate evidence
            # packet cannot accidentally verify a different conditional rule.
            table_condition_text = "\n".join(
                part for part in [support_text, table_support_text] if part
            )
            condition_trace = text_span_proof_trace(
                candidate_for_checks,
                table_condition_text,
                non_material_words,
                cue_extras,
                material_cue_extras,
            )
            if condition_trace:
                table_condition_trace = {"condition": condition_trace["condition"]}
                table_condition_gaps = text_span_support_gaps(
                    candidate_for_checks, table_condition_trace
                )

        # Support checks below use a double-negative idiom — `not (evidence and
        # not check(...))` — so each check defaults to True when evidence is
        # MISSING. That is safe, not lenient: the missing-evidence case is
        # already a hard rejection via source_evidence_id_not_found above, so
        # these flags only ever matter when evidence exists; defaulting True
        # keeps the missing-evidence rule from drowning in redundant gaps.
        # Critical check 1: the extracted value must be visible in the evidence.
        value_supported = not (
            evidence
            and candidate_for_checks.get("value") is not None
            and not _contains_value(value_support_text, candidate_for_checks.get("value"))
        )
        # Critical check 2: the extracted unit must be visible in the evidence.
        unit_supported = not (
            evidence
            and not _contains_unit(value_support_text or evidence_text, candidate_for_checks.get("unit"))
        )
        # If evidence has several numbers, use only the clause around this value
        # for scope/applies_to checks. This prevents wrong-scope verification.
        value_window = _value_local_window(support_text, candidate_for_checks.get("value"))
        scope_support_text = (
            value_window
            if value_window
            and evidence
            and evidence.get("evidence_type") not in TABLE_EVIDENCE_TYPES
            and _has_multiple_numeric_values(support_text)
            else local_support_text
        )
        if value_window and _value_is_absolute_lesser_of_branch(candidate_for_checks, support_text):
            scope_support_text = support_text
        if str(candidate_for_checks.get("extraction_method") or "") == "native_v3_clause":
            scope_support_text = local_support_text
        # Matrix-column binding (geometry recovered from the source PDF),
        # computed once for this candidate. Geometry-proven column membership
        # IS applies_to support: "55% | Rowhouse column" proves the claim
        # applies to Rowhouse even though the word never appears in the cell.
        column_binding = _matrix_column_binding(config, candidate_for_checks, evidence, raw_candidate=candidate)
        applies_to_supported = bool((column_binding or {}).get("supports_applies_to")) or not (
            evidence
            and not _applies_to_supported(candidate_for_checks, scope_support_text, config)
        )
        scope_supported = not (
            evidence
            and not _scope_supported(candidate_for_checks, scope_support_text)
        )
        operator_support_text = support_text
        if evidence and evidence.get("evidence_type") in TABLE_EVIDENCE_TYPES:
            operator_support_text = "\n".join(
                part
                for part in [
                    support_text,
                    table_support_text,
                ]
                if part
            )
        elif (
            value_window
            and evidence
            and _has_multiple_numeric_values(support_text)
        ):
            # Mirror the scope/applies_to narrowing above: when non-table
            # evidence carries several numbers, the operator wording must come
            # from the clause around THIS value — 'maximum' appearing anywhere
            # in the surrounding page (e.g. in a neighbouring rule's sentence)
            # must not ground this candidate's operator.
            operator_support_text = value_window
            if _value_is_absolute_lesser_of_branch(candidate_for_checks, support_text) or _value_has_same_sentence_operator_parent(
                candidate_for_checks, support_text, value_window
            ):
                operator_support_text = support_text
        # Critical check 3: the legal wording must support the operator.
        operator_supported = not (
            evidence
            and not _operator_supported(candidate_for_checks, operator_support_text)
        )
        # Safety: a FAMILY-FILLED operator (extractor left it blank) was not read
        # from the clause, so the loose operator_supported window can be satisfied
        # by a stray 'maximum'/'minimum' in a sibling clause on the same line and
        # INVERT the rule (a 'minimum ... is X' verified as a <= cap). Require the
        # filled direction to be stated unambiguously in the value's own sentence;
        # otherwise withhold support (-> operator_not_supported -> review).
        if (
            operator_supported
            and evidence
            and candidate_for_checks.get("operator_filled_from_family_direction")
            and not _filled_operator_direction_confirmed(
                candidate_for_checks, support_text, value_window
            )
        ):
            operator_supported = False
        # Critical check 4: evidence must support the rule family itself
        # (height, setback, lot coverage, etc.).
        rule_object_supported = (
            candidate_for_checks.get("rule_object") in KNOWN_RULE_OBJECTS
            and (not evidence or _rule_object_supported(config, candidate_for_checks, local_support_text or support_text))
        )

        # TabVer-lite runs before support gaps are finalized. This lets
        # structured table proof actually satisfy field checks instead of only
        # explaining the result after the fact. Letting a SUPPORTED table claim
        # flip a failed text-window check back to True is safe by design: for
        # table_cell evidence the structured fields (title/row/column/cell) are
        # the authoritative serialization and the flat text windows are noisy
        # re-renderings of the same cells — and the rescue is claim-for-claim
        # (a value proof can only repair the value check, never a scope gap).
        table_trace = table_proof_trace(candidate_for_checks, evidence, cue_extras)
        support_checks = _apply_table_trace_to_support_checks(
            table_trace,
            {
                "source_evidence_present": bool(evidence),
                "value_supported": value_supported,
                "unit_supported": unit_supported,
                "operator_supported": operator_supported,
                "applies_to_supported": applies_to_supported,
                "scope_supported": scope_supported,
                "rule_object_supported": rule_object_supported,
            },
        )
        value_supported = support_checks["value_supported"]
        unit_supported = support_checks["unit_supported"]
        operator_supported = support_checks["operator_supported"]
        applies_to_supported = support_checks["applies_to_supported"]
        scope_supported = support_checks["scope_supported"]
        rule_object_supported = support_checks["rule_object_supported"]

        # The extraction layer's review request is ADVISORY by default: the
        # deterministic verifier is the sole authority, so a generic "I'm not
        # sure" from the extractor cannot veto a candidate whose every gate
        # passes (upstream_extraction_requested_review is in ADVISORY_GAPS).
        # EXCEPTION: source-fidelity reasons the deterministic gates cannot see
        # on their own -- a re-anchor mismatch, or a quote absent from the
        # retrieved pack, where the provided evidence_text may contain a value
        # that is not actually on the source page -- must stay BLOCKING.
        if str(candidate.get("extraction_final_action") or "").upper() == "REVIEW":
            support_gaps.append("upstream_extraction_requested_review")
            review_reasons = {
                str(reason) for reason in (candidate.get("extraction_review_reasons") or [])
            }
            if not review_reasons or (review_reasons - SOFT_EXTRACTION_REVIEW_REASONS):
                support_gaps.append("extraction_source_fidelity_hold")
        corroborating_source_count = len(
            corroborating_sources(candidate_for_checks, source_agreement)
        )
        # The text-candidate gate (contract + consensus guard) is keyed on what
        # the EVIDENCE actually is, not on provenance strings. The old key —
        # extraction_method == 'pipeline5_final_registry' and source_stream !=
        # 'gemini_table_image' — was default-open: any unknown or misspelled
        # method string bypassed the gate entirely (Vancouver's
        # 'vancouver_prototype' candidates did exactly that). Now every
        # candidate is covered by exactly one gate family: table-typed evidence
        # goes through the structured table gates (table context, scope
        # patterns, TabVer proof), and everything else must pass the text gate.
        is_table_evidence = bool(evidence) and str(
            (evidence or {}).get("evidence_type") or ""
        ) in TABLE_EVIDENCE_TYPES
        if not is_table_evidence and not _text_candidate_can_verify(
            config,
            candidate_for_checks,
            support_checks,
            corroborating_source_count,
            text_span_gaps,
        ):
            support_gaps.append("text_candidate_requires_review")
        support_gaps.extend(text_span_gaps)
        support_gaps.extend(table_condition_gaps)
        if (
            candidate_for_checks.get("rule_object") in NUMERIC_RULE_OBJECTS
            and candidate_for_checks.get("operator") not in {"allowed", "permitted"}
            and candidate_for_checks.get("value") not in (None, "")
            and _to_float(candidate_for_checks.get("value")) is None
        ):
            support_gaps.append("non_numeric_value_for_numeric_rule")
        if _family_direction_mismatch(config, candidate_for_checks):
            support_gaps.append("rule_family_direction_mismatch")
        if not value_supported:
            support_gaps.append("value_not_found_in_evidence")
        if not unit_supported:
            support_gaps.append("unit_not_found_in_evidence")
        if not applies_to_supported:
            support_gaps.append("applies_to_not_supported")
        if not scope_supported:
            support_gaps.append("constraint_scope_not_supported")
        if not operator_supported:
            support_gaps.append("operator_not_supported")
        if not rule_object_supported:
            support_gaps.append("rule_object_not_supported")
        support_gaps.extend(_table_refutation_gaps(table_trace))
        # Pass whichever trace proved this evidence: the table trace for table
        # evidence, the TEXT-SPAN trace for prose. Consulting only the table
        # trace left prose evidence with unresolved exception wording free to
        # verify (the P9-fed ceiling-height exclusion leak).
        if _has_unresolved_exception_cue(evidence, table_trace or text_span_trace):
            support_gaps.append("unresolved_exception_cue")
        if not _rule_object_unit_compatible(candidate_for_checks):
            if _is_imperial_unit(candidate_for_checks.get("unit")) and _family_expects_metric(
                candidate_for_checks.get("rule_object")
            ):
                # Imperial-stated rule for a metric family: a real rule in feet is
                # not a unit ERROR (%-for-height is). Never silently verify a
                # feet/inch value against a metre threshold and never auto-convert
                # (that would forge source fidelity); surface it for human
                # review/conversion instead of hard-rejecting it. Bylaw-agnostic.
                support_gaps.append("non_metric_unit_requires_review")
            else:
                support_gaps.append("rule_object_unit_not_compatible")
        # Table candidates need row/column/title checks in addition to value/unit.
        # The matrix-column binding computed above threads through both gates:
        # support satisfies the legacy column/applies_to/condition word
        # checks, refutation and dropped qualifiers add their own gaps.
        table_context_gaps: list[str] = []
        if evidence:
            table_context_gaps = _table_context_gaps(config, candidate_for_checks, evidence, column_binding)
            table_context_gaps = _repair_table_context_gaps(table_context_gaps, table_trace)
            support_gaps.extend(table_context_gaps)
        table_review_gaps = _table_review_gaps(
            config,
            candidate,
            evidence,
            column_binding,
        )
        support_gaps.extend(table_review_gaps)
        # Cross-family value collision: a sibling family claims the same
        # value+unit+scope (e.g. lot_coverage 60% vs impervious_surface 60%).
        # Held for review because the value may be correct for only one family.
        support_gaps.extend(cross_family_gaps(candidate_for_checks, cross_family_index, config))
        # Some candidates are useful extraction artifacts but not validation
        # rules: section tracebacks, use-regulation references, or rule families
        # outside the current contract. Keep them for audit in not_used.json
        # instead of counting them as hard verifier failures.
        support_gaps.extend(not_used_gaps_for_candidate(candidate_for_checks, evidence))
        # Optional city/config target-section contract. Full-bylaw extraction
        # intentionally over-collects; true rules from out-of-target sections
        # must be retained for audit but not verified for this product scope.
        support_gaps.extend(target_scope_gaps_for_candidate(candidate_for_checks, evidence, config))
        # Sentence-shape gates: definitions, allowance triggers, and
        # foreign-unit-bound numbers all pass every per-field check (the words
        # and the number really are present) — the SHAPE of the sentence is
        # the only signal they are not rules. Live Calgary P9 leak classes.
        support_gaps.extend(evidence_shape_gaps(candidate_for_checks, evidence))

        if not support_gaps:
            # Defensive invariant, believed unreachable: any rule_object outside
            # KNOWN_RULE_OBJECTS already fails rule_object_supported above (the
            # table trace has no cues for unknown families, so it cannot rescue
            # one). Kept as belt-and-braces so a future cue/vocabulary change
            # cannot silently verify an unknown family.
            if candidate_for_checks.get("rule_object") not in KNOWN_RULE_OBJECTS:
                support_gaps.append("rule_object_not_canonical")

        # support_gaps is the whole reason for the decision. No probability,
        # confidence score, or upstream label can override these gaps.
        slim_decision = verification_decision_from_gaps(support_gaps)
        # The extractor's review request is advisory (it rode along in
        # support_gaps but is excluded from the blocking set). A VERIFIED rule
        # must carry a clean gap ledger so proof/decision alignment and the
        # "verified => no support_gaps" invariant hold, so strip advisory gaps
        # here and record them as an explicit flag for audit. Non-verified rules
        # keep the gap so review routing/ranking still see it.
        extractor_requested_review = "upstream_extraction_requested_review" in support_gaps
        if slim_decision == VERIFIED:
            support_gaps = [gap for gap in support_gaps if gap not in ADVISORY_GAPS]
        status = _verification_status(support_gaps, slim_decision)
        support_checks["table_context_supported"] = not table_context_gaps
        support_checks["table_review_gate_passed"] = not table_review_gaps
        text_trace = _text_proof_trace(
            candidate_for_checks,
            evidence,
            support_checks,
            support_gaps,
            local_support_text or support_text,
        )
        proof_trace = merge_proof_traces(text_trace, text_span_trace, table_trace, table_condition_trace)
        proof_trace = _align_proof_trace_with_decision(proof_trace, support_checks, support_gaps)
        proof_dag = build_proof_dag(
            candidate=candidate_for_checks,
            evidence=evidence,
            proof_trace=proof_trace,
            support_gaps=support_gaps,
            decision=slim_decision,
            support_checks=support_checks,
            matrix_binding=column_binding,
        )
        verification_label = verification_label_from_gaps(support_gaps)
        strength = evidence_strength(proof_trace, support_checks, support_gaps, slim_decision)
        priority = review_priority(slim_decision, strength, support_gaps)
        proof_kind = table_proof_type(evidence, table_trace)
        proof_mismatches = _proof_decision_mismatches(proof_trace, support_gaps)
        # Preserve both the normalized fields used by GIS and the original
        # candidate/evidence details used for audit/debugging.
        rule = {
            "rule_id": f"{config['city'].lower()}_{config['zone'].lower()}_{index:03d}",
            "rule_object": candidate_for_checks.get("rule_object"),
            "constraint_type": candidate_for_checks.get("constraint_type"),
            "constraint_scope": candidate_for_checks.get("constraint_scope"),
            "applies_to": candidate_for_checks.get("applies_to"),
            "value": candidate_for_checks.get("value"),
            "unit": candidate_for_checks.get("unit"),
            "operator": candidate_for_checks.get("operator"),
            "condition": candidate_for_checks.get("condition"),
            "exception": candidate_for_checks.get("exception"),
            "gis_relevance": candidate_for_checks.get("gis_relevance")
            or gis_relevance_for_rule_object(candidate_for_checks.get("rule_object")),
            "verification_status": status,
            "verification_decision": slim_decision,
            "verification_label": verification_label,
            "extractor_requested_review": extractor_requested_review,
            "canonical_rule_key": canonical_rule_key(candidate_for_checks),
            "proof_type": proof_kind,
            "table_proof_status": table_proof_status(table_trace),
            "text_span_proof_status": text_span_proof_status(text_span_trace),
            "proof_trace": proof_trace,
            "proof_dag": proof_dag,
            # Keep source-specific traces for debugging. The merged proof_trace
            # is convenient, but separate traces show whether text or table
            # logic produced each claim label.
            "text_proof_trace": text_trace,
            "text_span_proof_trace": text_span_trace,
            "table_proof_trace": table_trace,
            "merged_proof_trace": proof_trace,
            "proof_decision_mismatch": bool(proof_mismatches),
            "proof_decision_mismatches": proof_mismatches,
            "evidence_strength": strength,
            "review_priority": priority,
            "support_gaps": support_gaps,
            "support_checks": support_checks,
            # Structured applicability (dwelling type x unit range +
            # qualifiers) derived from the candidate text, plus the matrix
            # bands the claim was geometry-bound to (None / absent when the
            # layer was inert for this candidate).
            "applicability": (column_binding or {}).get("applicability"),
            "matrix_bands": (column_binding or {}).get("claimed_bands") or None,
            "normalization_trace": normalization_trace,
            "review_reason": _human_reason(support_gaps),
            "source": {
                "document": config.get("source_document"),
                "url": config.get("source_url"),
                "page": evidence.get("page") if evidence else None,
                "section": None,
                "evidence_id": candidate.get("evidence_id") or "",
                "evidence_type": evidence.get("evidence_type") if evidence else None,
                "evidence_text": evidence_text,
                "source_context": source_context,
                "inherited_parent_context": evidence.get("inherited_parent_context") if evidence else None,
                "local_context": local_context,
                "source_section": evidence.get("section") if evidence else None,
                "source_heading": evidence.get("heading") if evidence else None,
                "table_title": evidence.get("table_title") if evidence else None,
                "row_header": evidence.get("row_header") if evidence else None,
                "column_header": evidence.get("column_header") if evidence else None,
                "cell_value": evidence.get("cell_value") if evidence else None,
                "bbox": evidence.get("bbox") if evidence else None,
                "table_parser": evidence.get("table_parser") if evidence else None,
            },
            "candidate": candidate,
        }
        if status == "verified":
            verified_rules.append(rule)
        else:
            review_rules.append(rule)

    return {"verified_rules": verified_rules, "review_needed": review_rules}
