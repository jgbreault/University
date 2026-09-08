"""V2.1 deterministic matrix-table candidate emitter (recall fix).

V2's LLM examiner extracts almost nothing from a table-heavy bylaw: the
Burnaby 101.4 development-regulations matrix arrives FLATTENED to a text blob
("Maximum Lot Coverage Lots < 567 m2: 40% All Buildings 55% 40% 45%"), so the
model cannot associate a value with its column and returns ``{"rules": []}``
for the table pack (observed: pack_0001 -> 0 rules, whole-city V2 -> 4
candidates vs the production path's 142).

This module reuses the production ``table_matrix.build_page_matrices`` (band
geometry that recovers the matrix the flattener destroys) to PROPOSE one
candidate per (row x column-band) cell, in the verifier's table-cell contract
with a ``matrix_anchor`` attached. These are PROPOSALS only — the deterministic
verifier still proves each against its cell, exactly as it does the Pipeline-5
candidates, so false_verified stays 0 and noise (a stray threshold number, a
cross-column value) is held/rejected by the existing matrix binding.

No LLM, no network, no gold: it runs offline and is fully deterministic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .domain_schema import RULE_OBJECT_ALLOWED_UNITS
from .table_matrix import build_page_matrices
from .verification import _matrix_row_family


# A row label that does not name Maximum/Minimum but whose family is a count
# (dwelling units, storeys) still implies an upper-bound permission envelope.
_COUNT_FAMILIES = {"dwelling_units", "storeys"}

# Per-family unit for a deterministic proposal (the verifier re-checks unit
# visibility/compatibility against the cell, so this only needs to be the
# family's canonical unit).
_FAMILY_UNIT = {
    "height": "m", "setback": "m", "building_separation": "m",
    "lot_area": "m2", "floor_area": "m2", "lot_coverage": "%",
    "impervious_surface": "%", "storeys": "storeys", "dwelling_units": "units",
    "floor_space_ratio": "fsr",
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_METRE_VALUE_TOKEN_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)(?!\s*(?:2|²))\b",
    re.IGNORECASE,
)
_AREA_VALUE_TOKEN_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:m2|m²|sq\.?\s*m|square\s+metres?|square\s+meters?)\b",
    re.IGNORECASE,
)
_PERCENT_VALUE_TOKEN_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:%|per\s?cent|percent)(?=$|\W)",
    re.IGNORECASE,
)
_STOREY_VALUE_TOKEN_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:storeys?|stories?)\b",
    re.IGNORECASE,
)
_UNIT_VALUE_TOKEN_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:dwelling\s+)?units?\b",
    re.IGNORECASE,
)
_UNIT_RANGE_TOKEN_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s+to\s+(?P<value>\d+(?:\.\d+)?)\s+(?:dwelling\s+)?units?\b",
    re.IGNORECASE,
)
_LABELED_SEGMENT_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z /-]{1,45}?)\s*:\s*(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>m|metres?|meters?|m2|m²|sq\.?\s*m|square\s+metres?|square\s+meters?|%|per\s?cent|percent|storeys?|stories?)(?=$|\W)",
    re.IGNORECASE,
)


def _direction(row_label: str) -> str | None:
    lowered = row_label.lower()
    if "maximum" in lowered or "max " in lowered:
        return "maximum"
    if "minimum" in lowered or "min " in lowered:
        return "minimum"
    return None


def _operator(direction: str | None, family: str) -> tuple[str, str] | None:
    if direction == "maximum":
        return "<=", "maximum"
    if direction == "minimum":
        return ">=", "minimum"
    if family in _COUNT_FAMILIES:
        # "Permitted Dwelling Units ... 1 to 3" — the envelope is an upper bound.
        return "<=", "maximum"
    return None


def _band_applies_to(header_text: str) -> str:
    # "Dwelling Type | Small-Scale Multi-Unit | 1 to 2 | Units" ->
    # "Small-Scale Multi-Unit 1 to 2 Units" (the applicability parser flattens
    # pipes itself; this just drops the generic "Dwelling Type" lead-in).
    parts = [p.strip() for p in str(header_text or "").split("|") if p.strip()]
    parts = [p for p in parts if p.lower() not in {"dwelling type"}]
    return " ".join(parts)


# A number glued to "unit(s)" is a dwelling-COUNT qualifier ("4 Units Only:
# 281 m2"), not a dimensional value. For a non-count family the first numeric
# token of the cell is then the WRONG value (4, not 281), which would
# false-verify. Drop count-glued numbers for non-count families.
_COUNT_GLUED_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*units?\b", re.IGNORECASE)


def _family_plausible_number_tokens(text: str, family: str) -> list[str]:
    lowered = str(text or "").lower()
    if family in {"height", "setback", "building_separation", "automatic_sprinkler", "fire_access_corridor"}:
        return [match.group("value") for match in _METRE_VALUE_TOKEN_RE.finditer(lowered)]
    if family in {"lot_area", "floor_area"}:
        return [match.group("value") for match in _AREA_VALUE_TOKEN_RE.finditer(lowered)]
    if family in {"lot_coverage", "impervious_surface"}:
        return [match.group("value") for match in _PERCENT_VALUE_TOKEN_RE.finditer(lowered)]
    if family == "storeys":
        return [match.group("value") for match in _STOREY_VALUE_TOKEN_RE.finditer(lowered)]
    if family == "dwelling_units":
        range_tokens = [match.group("value") for match in _UNIT_RANGE_TOKEN_RE.finditer(lowered)]
        if range_tokens:
            return range_tokens
        return [match.group("value") for match in _UNIT_VALUE_TOKEN_RE.finditer(lowered)]

    count_glued = {match.group(1) for match in _COUNT_GLUED_RE.finditer(lowered)}
    out: list[str] = []
    for match in _NUMBER_RE.finditer(lowered):
        token = match.group(0)
        # Skip a number glued to a preceding letter ("m2"/"m²" -> the "2"
        # is a unit suffix, not a value) and dwelling-count qualifiers under a
        # non-count family ("4 Units Only" -> the 4 is not a dimension).
        before = lowered[match.start() - 1] if match.start() > 0 else " "
        if before.isalpha():
            continue
        if family not in _COUNT_FAMILIES and token in count_glued:
            continue
        out.append(token)
    return out


def _family_plausible_numbers(text: str, family: str) -> list[float]:
    return [float(token) for token in _family_plausible_number_tokens(text, family)]


def _labeled_value_emissions(cell_text: str, family: str) -> list[tuple[float, str, str]]:
    out: list[tuple[float, str, str]] = []
    for segment in re.split(r"\s*\|\s*|\n+", str(cell_text or "")):
        match = _LABELED_SEGMENT_RE.search(segment.strip())
        if not match:
            continue
        label = " ".join(match.group("label").lower().split())
        unit = match.group("unit").lower().replace(" ", "")
        token = match.group("value")
        if family in {"height", "setback", "building_separation"} and unit in {"m", "metre", "metres", "meter", "meters"}:
            out.append((float(token), label, token))
        elif family in {"lot_area", "floor_area"} and unit in {"m2", "m²", "sq.m", "sqm", "squaremetre", "squaremetres", "squaremeter", "squaremeters"}:
            out.append((float(token), label, token))
        elif family in {"lot_coverage", "impervious_surface"} and unit in {"%", "percent"}:
            out.append((float(token), label, token))
        elif family == "storeys" and unit in {"storey", "storeys", "story", "stories"}:
            out.append((float(token), label, token))
    return out


def _cell_value_emissions(cell: dict[str, Any], family: str) -> list[tuple[float, str, str]]:
    """Return (value, condition) pairs to propose from one band cell.

    Conditional cells ("Lots < 567 m2: 40% / Lots > 567 m2: 30%") emit one
    proposal per branch carrying the branch condition; a plain cell emits its
    first family-PLAUSIBLE number (skipping dwelling-count qualifiers like the
    "4" in "4 Units Only: 281 m2"). Bare threshold-only numbers (the 567 in a
    branch label) are never proposed on their own.
    """
    branches = cell.get("branches") or []
    if branches:
        out: list[tuple[float, str, str]] = []
        for branch in branches:
            tokens = _family_plausible_number_tokens(branch.get("value_text") or "", family)
            if not tokens:
                # value_text empty -> fall back to the branch's own numbers
                # minus the threshold (first number is the threshold).
                raw = branch.get("numbers") or []
                tokens = [f"{float(raw[-1]):g}"] if raw else []
            for token in tokens[:1]:
                out.append((float(token), str(branch.get("condition_text") or "").strip(), token))
        if out:
            return out
    labeled = _labeled_value_emissions(cell.get("text") or "", family)
    if labeled:
        return labeled
    tokens = _family_plausible_number_tokens(cell.get("text") or "", family)
    return [(float(tokens[0]), "", tokens[0])] if tokens else []


def _families_for_cell(row_family: str, cell: dict[str, Any]) -> list[str]:
    families = [row_family]
    text = str(cell.get("text") or "")
    if row_family == "height" and _STOREY_VALUE_TOKEN_RE.search(text):
        families.append("storeys")
    return families


def build_matrix_candidate_set(
    pdf_path: str | Path,
    city: str,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (evidence_units, candidates) proposed from the source matrices.

    Deterministic and offline. Every record carries a ``matrix_anchor`` so the
    verifier's column binding proves/holds/refutes it exactly as for the
    production table path. ``config`` is accepted for symmetry but not required
    (the verifier supplies its own normalization at verify time).
    """
    pdf_path = Path(pdf_path)
    matrices = build_page_matrices(pdf_path)
    evidence_units: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seq = 0

    for page, tables in sorted(matrices.items()):
        for table_index, matrix in enumerate(tables):
            bands = matrix["bands"]
            band_by_key = {band["key"]: band for band in bands}
            for row in matrix["rows"]:
                family = _matrix_row_family(row["label"])
                if not family:
                    continue
                if _operator(_direction(row["label"]), family) is None:
                    continue
                # Anchor shared by every cell of this row (the binding reads
                # the whole row's bands to prove/refute the claimed column).
                anchor = {
                    "page": page,
                    "row_label": row["label"],
                    "bands": [
                        {
                            "key": band_key,
                            "header_text": band_by_key.get(band_key, {}).get("header_text", ""),
                            **cell,
                        }
                        for band_key, cell in sorted(row["cells"].items())
                    ],
                }
                for band_key, cell in sorted(row["cells"].items()):
                    band = band_by_key.get(band_key, {})
                    applies_to = _band_applies_to(band.get("header_text", ""))
                    for emitted_family in _families_for_cell(family, cell):
                        emitted_operator = _operator(_direction(row["label"]), emitted_family)
                        if emitted_operator is None:
                            continue
                        emitted_op, emitted_constraint_type = emitted_operator
                        emitted_unit = _FAMILY_UNIT.get(emitted_family, "")
                        for value, condition, value_text in _cell_value_emissions(cell, emitted_family):
                            seq += 1
                            evidence_id = f"{city}_matrix_p{page}_t{table_index}_b{band_key}_{seq:03d}"
                            candidate_id = f"{city}_v2matrix_{seq:03d}"
                            evidence_units.append(
                                {
                                    "evidence_id": evidence_id,
                                    "page": page,
                                    "section": "",
                                    "evidence_type": "table_cell",
                                    "evidence_text": f"{row['label']} | {applies_to} | {cell.get('text') or value_text}",
                                    "source_context": f"{row['label']} | {applies_to} | {cell.get('text') or value_text}",
                                    "table_title": row["label"].split("|")[0].strip(),
                                    "row_header": row["label"].split("|")[-1].strip(),
                                    "column_header": applies_to,
                                    "cell_value": str(cell.get("text") or value_text),
                                    "matrix_anchor": anchor,
                                    "source_stream": "native_v2_matrix",
                                }
                            )
                            candidates.append(
                                {
                                    "candidate_id": candidate_id,
                                    "evidence_id": evidence_id,
                                    "rule_object": emitted_family,
                                    "constraint_type": emitted_constraint_type,
                                    "constraint_scope": emitted_family,
                                    "applies_to": applies_to,
                                    "operator": emitted_op,
                                    "value": value_text,
                                    "unit": emitted_unit,
                                    "condition": condition,
                                    "exception": "",
                                    "source_stream": "native_v2_matrix",
                                    "extraction_method": "deterministic_matrix_v2",
                                    "native_provenance": {
                                        "page": page,
                                        "row_label": row["label"],
                                        "band_key": band_key,
                                        "discovery_confidence": 0.9,
                                        "selected_because": ["matrix_cell"],
                                        "rule_types": ["dimensional_standard"],
                                        "lane": "table_rule",
                                    },
                                }
                            )
    return evidence_units, candidates
