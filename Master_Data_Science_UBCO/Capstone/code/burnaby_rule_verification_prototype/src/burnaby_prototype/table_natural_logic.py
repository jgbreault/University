"""TabVer-lite proof helpers for zoning table evidence.

The real TabVer task reasons over tables. This lightweight version does the
piece we need: prove rule claims from table title, row header, column header,
and cell value without calling an LLM.
"""

from __future__ import annotations

import re
from typing import Any

from .domain_schema import UNIT_ALIASES, separation_subject_grounded, token_visible, unit_visible, unresolved_exception_cues
from .rule_claims import NOT_ENOUGH_INFO, REFUTED, SUPPORTED, proof


TABLE_EVIDENCE_TYPES = {"table_cell", "table_row"}

# These cues let the table proof layer infer "what kind of rule is this table
# talking about?" from headings such as "Maximum Height" or "Minimum Setbacks".
RULE_OBJECT_CUES = {
    "height": ("height",),
    "storeys": ("storey", "storeys", "story", "stories"),
    "setback": ("setback", "setbacks", "yard", "lot line"),
    # No bare 'between': it matched ordinary prose ('between 2 and 3 storeys')
    # and could falsely support — or falsely refute — unrelated candidates.
    "building_separation": ("separation", "between buildings"),
    "lot_coverage": ("lot coverage", "coverage"),
    "impervious_surface": ("impervious",),
    # floor_space_ratio before floor_area: 'floor area ratio' contains
    # 'floor area' and must claim the ratio family first.
    "floor_space_ratio": ("floor space ratio", "floor area ratio", "fsr"),
    # floor_area before lot_area, and lot_area without its old bare 'area' cue:
    # 'floor area' / 'site area' table text must never count as lot_area proof.
    "floor_area": ("floor area", "gross floor"),
    "lot_area": ("lot area",),
    # No bare 'units': it appears in scope labels like 'Small-Scale Multi-Unit'
    # tables that are not about dwelling-unit counts.
    "dwelling_units": ("dwelling units",),
    "automatic_sprinkler": ("sprinkler",),
    "fire_access_corridor": ("fire access corridor", "corridor"),
    "permitted_use": ("permitted use", "permitted uses", "principal use", "accessory use"),
}

# Operator cues translate table words into mathematical operators. For example,
# a table titled "Minimum Lot Line Setbacks" supports a >= operator.
OPERATOR_CUES = {
    "<=": ("maximum", "max", "not exceed", "up to"),
    ">=": ("minimum", "min", "at least", "not less"),
    ">": ("more than", "greater than", "exceeds"),
    "<": ("less than", "fewer than"),
    "required": ("required", "shall", "must"),
    "allowed": ("permitted", "allowed"),
    "permitted": ("permitted", "allowed"),
}

# Matches an "N unit, except M unit for X" clause, e.g.
# "3.0 m, except 1.5 m for accessory buildings". The base value is the general
# rule; the alt value applies only to the qualifier group X.
_EXCEPT_CLAUSE_RE = re.compile(
    # Unit class allows digits/uppercase so compound units (m2, M2) between the
    # value and the comma do not break the match (which would leave the
    # exception open and silently route the rule to review).
    r"(?P<base>\d+(?:\.\d+)?)\s*[a-zA-Z0-9%²]*\s*,?\s*except\s+"
    r"(?P<alt>\d+(?:\.\d+)?)\s*[a-zA-Z0-9%²]*\s+for\s+(?P<who>[a-z0-9 ,'\-]+)",
    flags=re.IGNORECASE,
)


def table_proof_trace(
    candidate: dict[str, Any],
    evidence: dict[str, Any] | None,
    rule_object_cue_extras: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return claim proofs derived from structured table fields.

    ``rule_object_cue_extras`` carries per-city ADDITIVE support phrases from
    the normalization config; they extend only the SUPPORT side of the
    rule-object proof, never the refutation scan (_matching_rule_object).
    Default None keeps every existing caller byte-identical.
    """
    if not evidence or evidence.get("evidence_type") not in TABLE_EVIDENCE_TYPES:
        return {}

    # Keep the table pieces separate. This is the core TabVer-lite idea: title,
    # row, column, and cell each prove different parts of the rule.
    table_title = str(evidence.get("table_title") or "")
    row_header = str(evidence.get("row_header") or "")
    column_header = str(evidence.get("column_header") or "")
    cell_value = str(evidence.get("cell_value") or "")
    evidence_text = str(evidence.get("evidence_text") or "")
    matrix_context = _matrix_anchor_context(candidate, evidence)
    table_text = " | ".join(
        part for part in [table_title, row_header, column_header, cell_value, evidence_text, matrix_context] if part
    )

    value_proof_text = _value_proof_text(candidate, cell_value, evidence_text, table_text)

    return {
        # Table title usually proves the rule family: "Minimum Lot Line Setbacks"
        # -> setback; "Maximum Height" -> height.
        "rule_object": _prove_rule_object(
            candidate, table_title, row_header, evidence_text, rule_object_cue_extras
        ),
        # Row/column usually proves scope: "Lane Yard", "Rear Principal
        # Buildings", "sloping roof", etc.
        "constraint_scope": _prove_text_claim(
            candidate.get("constraint_scope"),
            "row_header/column_header",
            f"{table_title} | {row_header} | {column_header} | {evidence_text} | {matrix_context}",
            "scope words are present in table row/column context",
        ),
        # Applies-to is optional because some table rows are generic and the rule
        # may still be valid without a specific building type.
        "applies_to": _prove_text_claim(
            candidate.get("applies_to"),
            "row_header/column_header",
            f"{table_title} | {row_header} | {column_header} | {cell_value} | {evidence_text} | {matrix_context}",
            "applies_to words are present in table context",
            optional=True,
        ),
        # Operator comes from words like Minimum/Maximum/Required, not from
        # model confidence.
        "operator": _prove_operator(candidate, table_title, row_header, column_header, evidence_text),
        # Cell value is the strongest source for numeric value and unit. The
        # exception is a dwelling-unit range row, where "5 to 6 Units" proves the
        # upper-bound max even if the cell fragment contains only the lower end.
        "value": _prove_value(candidate.get("value"), value_proof_text),
        "unit": _prove_unit(candidate.get("unit"), cell_value or evidence_text),
        "condition": _prove_text_claim(
            candidate.get("condition"),
            "column_header/table_text",
            f"{column_header} | {table_text}",
            "condition words are present in table context",
            optional=True,
        ),
        "exception": _prove_exception(candidate.get("exception"), table_text, candidate),
    }


def table_proof_type(evidence: dict[str, Any] | None, proof_trace: dict[str, dict[str, Any]]) -> str:
    """Classify the table proof source without overstating success.

    Earlier versions returned ``table_natural_logic`` whenever table proof was
    attempted. That made partial/refuted proofs look successful in the output.
    Now the main proof_type is the strongest only when every table claim is
    supported; partial/refuted results are labelled separately.
    """
    if evidence and evidence.get("evidence_type") in TABLE_EVIDENCE_TYPES and proof_trace:
        status = table_proof_status(proof_trace)
        if status == "complete":
            return "table_natural_logic"
        return f"table_natural_logic_{status}"
    return "text_evidence"


def table_proof_status(proof_trace: dict[str, dict[str, Any]]) -> str:
    """Summarize whether table proof is complete, partial, or refuted."""
    if not proof_trace:
        return "none"
    labels = {item.get("label") for item in proof_trace.values()}
    if REFUTED in labels:
        return "refuted"
    if NOT_ENOUGH_INFO in labels:
        return "partial"
    return "complete"


def _prove_rule_object(
    candidate: dict[str, Any],
    table_title: str,
    row_header: str,
    evidence_text: str,
    rule_object_cue_extras: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    rule_object = str(candidate.get("rule_object") or "")
    text = f"{table_title} {row_header} {evidence_text}".lower()
    # Per-city extras are appended AFTER the shared cues, support-side only.
    cues = (
        *RULE_OBJECT_CUES.get(rule_object, ()),
        *(rule_object_cue_extras or {}).get(rule_object, ()),
    )
    for cue in cues:
        if cue in text:
            if rule_object == "building_separation" and not separation_subject_grounded(text):
                # 'separation' alone is not enough: '1.0 metres ... between
                # retaining walls' verified as building_separation (live
                # Calgary P9 leak, prose path; pinned here too so a table row
                # cannot reopen the same hole). The separation's subject must
                # be a building-like entity.
                break
            # Supported: the table context contains a cue for the same canonical
            # rule object as the candidate.
            return proof(SUPPORTED, evidence_field="table_title/row_header", evidence_quote=_quote_for_cue(cue, table_title, row_header, evidence_text), reason=f"table context contains {rule_object} cue")

    other_match = _matching_rule_object(text)
    if other_match and other_match != rule_object:
        # Refuted: the table looks like it is about a different rule family.
        # Example: candidate says setback but table title says lot coverage.
        return proof(REFUTED, evidence_field="table_title/row_header", evidence_quote=_quote_for_cue(other_match.replace("_", " "), table_title, row_header, evidence_text), reason=f"table context points to {other_match}, not {rule_object}")
    return proof(NOT_ENOUGH_INFO, reason="table context does not prove the rule object")


def _prove_operator(
    candidate: dict[str, Any],
    table_title: str,
    row_header: str,
    column_header: str,
    evidence_text: str,
) -> dict[str, Any]:
    operator = _canonical_operator(candidate.get("operator"), candidate.get("constraint_type"))
    if not operator:
        return proof(NOT_ENOUGH_INFO, reason="candidate has no operator to prove")
    text = f"{table_title} {row_header} {column_header} {evidence_text}".lower()
    if operator == "<=" and _dwelling_unit_upper_bound_supported(candidate, text):
        return proof(SUPPORTED, evidence_field="table_text", evidence_quote=table_title or evidence_text, reason="dwelling-unit range proves the upper-bound operator")
    for cue in OPERATOR_CUES.get(operator, ()):
        if cue in text:
            # Supported: table wording implies the same operator as the candidate.
            return proof(SUPPORTED, evidence_field="table_title/row_header", evidence_quote=_quote_for_cue(cue, table_title, row_header, column_header, evidence_text), reason=f"table wording implies {operator}")

    inverse = {">=": "<=", "<=": ">=", ">": "<", "<": ">"}
    inverse_operator = inverse.get(operator)
    if inverse_operator and any(cue in text for cue in OPERATOR_CUES.get(inverse_operator, ())):
        # Refuted: table wording implies the opposite direction. This is safer
        # than sending a maximum/minimum mix-up to GIS.
        return proof(REFUTED, evidence_field="table_title/row_header", evidence_quote=table_title or row_header or evidence_text, reason=f"table wording implies {inverse_operator}, not {operator}")
    return proof(NOT_ENOUGH_INFO, reason="table wording does not prove the operator")


def _prove_value(value: Any, text: str) -> dict[str, Any]:
    tokens = _value_tokens(value)
    if not tokens:
        return proof(SUPPORTED, reason="candidate has no explicit value to prove")
    normalized = text.replace(",", "")
    # Digit-boundary matching (shared token_visible): a candidate value '5'
    # must not be "proven" by a cell containing only '7.5' or '50'.
    if all(token_visible(normalized, token) for token in tokens):
        # Best case: the exact number appears in the table cell.
        return proof(SUPPORTED, evidence_field="cell_value", evidence_quote=text, reason="numeric value appears in table cell")
    if _numbers(text) and _numbers(value):
        # The cell has a number, but not the candidate's number. Treat this as a
        # contradiction rather than a vague missing-proof issue.
        return proof(REFUTED, evidence_field="cell_value", evidence_quote=text, reason="table cell contains a different numeric value")
    return proof(NOT_ENOUGH_INFO, evidence_field="cell_value", evidence_quote=text, reason="table cell does not prove the value")


def _value_proof_text(candidate: dict[str, Any], cell_value: str, evidence_text: str, table_text: str) -> str:
    """Choose the safest text span for proving table values."""
    if _dwelling_unit_upper_bound_supported(candidate, evidence_text or table_text):
        return evidence_text or table_text
    return cell_value or evidence_text


def _matrix_anchor_context(candidate: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Return only matrix bands whose visible value matches this candidate.

    Pipeline 5 table cells often preserve the full matrix under
    ``matrix_anchor``. Using every band would over-prove conditions from sibling
    columns, so this helper exposes only bands or branch conditions whose value
    text contains the candidate's value.
    """
    matrix_anchor = evidence.get("matrix_anchor")
    if not isinstance(matrix_anchor, dict):
        return ""
    bands = matrix_anchor.get("bands")
    if not isinstance(bands, list):
        return ""

    contexts: list[str] = []
    for band in bands:
        if not isinstance(band, dict):
            continue
        header_text = str(band.get("header_text") or "")
        band_text = str(band.get("text") or "")
        matched_branches = _matching_matrix_branches(candidate, band)
        if matched_branches:
            for branch in matched_branches:
                branch_context = " | ".join(
                    part
                    for part in [
                        header_text,
                        str(branch.get("condition_text") or ""),
                        str(branch.get("value_text") or ""),
                    ]
                    if part
                )
                if branch_context:
                    contexts.append(branch_context)
            continue
        if _candidate_value_visible_in_text(candidate, band_text):
            context = " | ".join(part for part in [header_text, band_text] if part)
            if context:
                contexts.append(context)
    return " | ".join(dict.fromkeys(contexts))


def _matching_matrix_branches(candidate: dict[str, Any], band: dict[str, Any]) -> list[dict[str, Any]]:
    branches = band.get("branches")
    if not isinstance(branches, list):
        return []
    return [
        branch
        for branch in branches
        if isinstance(branch, dict) and _candidate_value_visible_in_text(candidate, str(branch.get("value_text") or ""))
    ]


def _candidate_value_visible_in_text(candidate: dict[str, Any], text: str) -> bool:
    tokens = _value_tokens(candidate.get("value"))
    if not tokens:
        return False
    normalized = text.replace(",", "")
    return all(token_visible(normalized, token) for token in tokens)


def _dwelling_unit_upper_bound_supported(candidate: dict[str, Any], text: str) -> bool:
    """Check the narrow case where a unit range proves its maximum value."""
    if candidate.get("rule_object") != "dwelling_units":
        return False
    operator = _canonical_operator(candidate.get("operator"), candidate.get("constraint_type"))
    if operator != "<=":
        return False
    candidate_numbers = _numbers(candidate.get("value"))
    if not candidate_numbers:
        return False
    candidate_value = float(candidate_numbers[0])
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+(?:dwelling\s+)?units?\b", text, flags=re.IGNORECASE):
        upper_bound = float(match.group(2))
        if abs(candidate_value - upper_bound) <= 0.01:
            return True
    return False


def _prove_unit(unit: Any, text: str) -> dict[str, Any]:
    unit_text = str(unit or "").lower().strip()
    if not unit_text:
        return proof(SUPPORTED, reason="candidate has no explicit unit to prove")
    normalized = text.lower()
    # Shared unit_visible helper: canonicalizes via unit_key so 'metres'/'m^2'
    # match, and handles symbol units ('45%' has no word boundary before '%').
    if unit_visible(normalized, unit_text):
        # Accept normal variants like m/metres or %/percent.
        return proof(SUPPORTED, evidence_field="cell_value", evidence_quote=text, reason="unit appears in table cell")
    if _visible_units(normalized):
        # A different visible unit means the extraction likely paired the wrong
        # rule object or cell.
        return proof(REFUTED, evidence_field="cell_value", evidence_quote=text, reason="table cell shows a different unit")
    return proof(NOT_ENOUGH_INFO, evidence_field="cell_value", evidence_quote=text, reason="table cell does not prove the unit")


def _prove_text_claim(
    value: Any,
    evidence_field: str,
    text: str,
    reason: str,
    *,
    optional: bool = False,
) -> dict[str, Any]:
    if value in (None, ""):
        # Optional text claims are considered supported when absent; required
        # text claims become not_enough_info.
        label = SUPPORTED if optional else NOT_ENOUGH_INFO
        return proof(label, evidence_field=evidence_field, evidence_quote=text, reason="candidate has no explicit claim")
    if _phrase_visible(value, text):
        return proof(SUPPORTED, evidence_field=evidence_field, evidence_quote=text, reason=reason)
    claim_words = _content_words(str(value))
    evidence_words = _content_words(text)
    if not claim_words:
        return proof(SUPPORTED if optional else NOT_ENOUGH_INFO, evidence_field=evidence_field, evidence_quote=text, reason="claim has no distinctive words")
    if _enough_overlap(claim_words, evidence_words):
        # Use stricter overlap than "any shared word"; one vague shared word is
        # not enough to prove zoning scope like "front street yard".
        return proof(SUPPORTED, evidence_field=evidence_field, evidence_quote=text, reason=reason)
    return proof(NOT_ENOUGH_INFO, evidence_field=evidence_field, evidence_quote=text, reason="table context does not prove this claim")


def _prove_exception(exception: Any, table_text: str, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    if exception not in (None, ""):
        return _prove_text_claim(exception, "table_text", table_text, "exception words are present in table context")
    # Shared preamble-aware cue detection (incl. the exclud* family) — this
    # tuple was the table path's private copy and silently lacked exclusion
    # wording, so a table cell carrying an exclusion criterion could verify.
    if unresolved_exception_cues(table_text):
        # Exception language can change the legal meaning. But a cell like
        # "3.0 m, except 1.5 m for accessory buildings" is not an *open*
        # exception: it lists two explicit branches, and each branch is its own
        # candidate. If this candidate's value matches one branch, the exception
        # is resolved, not unresolved.
        if candidate is not None and _exception_branch_resolved(candidate, table_text):
            return proof(SUPPORTED, evidence_field="table_text", evidence_quote=table_text, reason="candidate value matches an explicit branch of the except-clause")
        # Otherwise (e.g. "unless otherwise specified" with no numeric branch),
        # the exception stays uncertain and the candidate goes to review.
        return proof(NOT_ENOUGH_INFO, evidence_field="table_text", evidence_quote=table_text, reason="exception or override wording appears but is unresolved")
    return proof(SUPPORTED, reason="no exception claim and no unresolved exception cue")


def _exception_branch_resolved(candidate: dict[str, Any], table_text: str) -> bool:
    """Return True when the candidate value is one explicit branch of an
    ``N, except M for X`` clause, so the exception is resolved rather than open.

    Both branches are gated by the candidate's group: the base (general) value
    resolves only when the candidate does NOT name the ``for X`` exception group,
    and the exception value ``M`` resolves only when it DOES. This is symmetric on
    purpose -- otherwise a candidate claiming "Accessory Buildings" while carrying
    the *base* value (e.g. 3.0 m for a cell that carves out 1.5 m for accessory
    buildings) would verify a rule that contradicts its own evidence. A genuinely
    open exception with no numeric branch (e.g. "unless otherwise specified")
    never resolves here.
    """
    candidate_numbers = _numbers(candidate.get("value"))
    if not candidate_numbers:
        return False
    candidate_value = float(candidate_numbers[0])
    who_words = _content_words(f"{candidate.get('condition') or ''} {candidate.get('applies_to') or ''}")
    for match in _EXCEPT_CLAUSE_RE.finditer(table_text):
        qualifier_words = _content_words(match.group("who"))
        # The two branches need OPPOSITE strictness, so a single overlap test is
        # unsafe either way. Base resolution is guarded by a LOOSE claim (any hint
        # of the exception group blocks taking the general value), while taking
        # the carve-out value requires a STRICT claim (the candidate fully names
        # the exception group). Both choices push ambiguous cases toward review.
        claims_loose = bool(qualifier_words and (qualifier_words & who_words))
        claims_strict = bool(qualifier_words and qualifier_words <= who_words)
        if abs(candidate_value - float(match.group("base"))) <= 0.01:
            # The general rule. Only candidates that do NOT name the exception
            # group at all may take the base value; one that even partially names
            # the exception group is mis-attributing it and must stay in review.
            if not claims_loose:
                return True
        elif abs(candidate_value - float(match.group("alt"))) <= 0.01:
            if claims_strict:
                return True
    return False


def _canonical_operator(operator: Any, constraint_type: Any) -> str:
    """Normalize operator words/symbols before table proof."""
    text = f"{operator or ''} {constraint_type or ''}".lower()
    if any(token in text for token in ("<=", "≤", "maximum", "max", "not_exceed")):
        return "<="
    if any(token in text for token in (">=", "≥", "minimum", "min", "at_least")):
        return ">="
    if ">" in text:
        return ">"
    if "<" in text:
        return "<"
    if "required" in text:
        return "required"
    if "allowed" in text or "permitted" in text:
        return "allowed"
    return str(operator or "").strip()


def _matching_rule_object(text: str) -> str | None:
    """Return the first rule object whose cue appears in table context."""
    for rule_object, cues in RULE_OBJECT_CUES.items():
        if any(cue in text for cue in cues):
            return rule_object
    return None


def _quote_for_cue(cue: str, *parts: str) -> str:
    """Choose the shortest useful table field quote that contains the cue."""
    for part in parts:
        if cue.lower() in str(part).lower():
            return str(part)
    return next((str(part) for part in parts if part), "")


def _phrase_visible(value: Any, text: str) -> bool:
    """Return True when the exact claim phrase is visible in table context.

    This catches short generic claims such as "building" in "Front Principal
    Buildings" or "lot" in "Maximum Lot Coverage" without letting one vague
    shared word prove a longer phrase like "front street yard".
    """
    phrase = _normalized_phrase(value)
    haystack = _normalized_phrase(text)
    if not phrase:
        return False
    variants = {phrase}
    if phrase.endswith("y"):
        variants.add(phrase[:-1] + "ies")
    else:
        variants.add(phrase + "s")
    return any(re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", haystack) for variant in variants)


def _normalized_phrase(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _value_tokens(value: Any) -> list[str]:
    """Extract numeric tokens from a candidate value.

    Mirrors support_checks._value_tokens: comma grouping stripped first, and
    multi-dot numerals like section reference '101.5.2' kept as one token so
    boundary-aware matching can find them verbatim.
    """
    return re.findall(r"\d+(?:\.\d+)*", str(value or "").replace(",", "")) or ([str(value).lower()] if value not in (None, "") else [])


def _numbers(value: Any) -> list[str]:
    """Extract visible numbers for contradiction checks."""
    return re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))


def _visible_units(text: str) -> set[str]:
    """Detect any canonical unit visible in table text.

    Derived from the shared UNIT_ALIASES table (not a private spelling list)
    so this refutation vocabulary cannot drift from what _prove_unit accepts:
    every spelling that can SUPPORT a unit can also REFUTE a different one.
    """
    return {key for key in UNIT_ALIASES if unit_visible(text, key)}


def _content_words(text: str) -> set[str]:
    """Return meaningful words for row/column scope overlap."""
    stopwords = {"all", "the", "and", "or", "of", "to", "for", "minimum", "maximum", "building", "buildings"}
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2 and word not in stopwords}


def _enough_overlap(claim_words: set[str], evidence_words: set[str]) -> bool:
    """Return True only when evidence covers enough distinctive claim words.

    For one- or two-word claims, require all distinctive words. For longer
    claims, allow one missing word but still require at least two matches. This
    keeps table proof useful without letting a single shared word prove the
    wrong scope.
    """
    if not claim_words:
        return False
    if len(claim_words) <= 2:
        return claim_words <= evidence_words
    return len(claim_words & evidence_words) >= max(2, len(claim_words) - 1)
