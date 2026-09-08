"""Deterministic clause extractor over the ingest intermediate.

Detects section-numbered clauses ('11.3.8.2', '5.7(3)(a)', '101.5'), attaches
each clause's section id + page, and derives rule candidates from
numeric-bearing clauses. This stream is a PROPOSER — it may guess rule objects
from a small local keyword map; the deterministic verifier is the gate.

ALL clauses are emitted as evidence units (id scheme: <city>_<section>_<seq>),
not only candidate-bearing ones, so the helper doubles as a gold-set/diagnosis
reading aid. Everything in this module is pure-deterministic: no model calls,
no randomness, no environment reads.
"""

from __future__ import annotations

import re
from typing import Any

from .pdf_ingest import blocks_from_text


# A section anchor needs at least one dot or parenthesis level so bare numbers
# ('6 dwelling units') and years never start a clause: 11.3.8.2 / 5.7(3)(a) /
# 101.5 / Calgary's '352 (1)' and '352 (4.1)' styles (optional single space
# before the subsection parenthesis, decimal subsections allowed — still
# line-start anchored, so prose numbers never qualify).
SECTION_ANCHOR_RE = re.compile(
    r"^\s*(?P<section>\d{1,3}(?:\.\d{1,3})+(?:\s?\(\d{1,2}(?:\.\d{1,2})?\))*(?:\([a-z]\))*"
    r"|\d{1,3}(?:\s?\(\d{1,2}(?:\.\d{1,2})?\))+(?:\([a-z]\))*)\s+"
)

# Calgary prints marginal AMENDMENT CODES at line starts ('10P2019 (3) ...').
# They are provenance, not section numbers — stripped before anchor matching.
AMENDMENT_CODE_RE = re.compile(r"^\s*(?:\d{1,3}P\d{4}[,\s]+)+")

# Bare numbered HEADINGS ('352 Backyard Suite 12P2012, 24P2014'): the number
# establishes the running base section for subsection continuations, but the
# heading itself is a title, not a rule clause. Requires a Capitalized word so
# value lines ('5.0 metres ...') never qualify.
BARE_HEADING_RE = re.compile(r"^\s*(?P<base>\d{1,3})\s+(?=[A-Z][a-z])")

# Subsection CONTINUATION lines ('(3) Unless otherwise referenced ...',
# '(4.1) The maximum building height ...') inherit the running base section.
SUBSECTION_RE = re.compile(r"^\s*\((?P<sub>\d{1,2}(?:\.\d{1,2})?)\)\s+")

# A dotted 'anchor' immediately followed by a unit word is a VALUE line
# ('1.5 metres for any portion ...'), never a section heading.
UNIT_AFTER_ANCHOR_RE = re.compile(
    r"(?i)^(?:square\s+)?(?:metres?|meters?|m2|m²|per\s?cent|percent|%|storeys?|stories|m)\b"
)

# Embedded boundaries inside a MERGED block (PDF reflow glues a clause's tail
# to the next clause's start). Both guards require a sentence boundary or a
# unit word first, so prose references ('in subsections (2.1) and (3)') and
# mid-sentence numbers never split. Optional amendment codes may sit between
# the boundary and the marker ('metres 10P2019 (4) Unless ...').
_BOUNDARY = r"(?:[.;:]|\b(?:metres?|meters?|m2|m²|per\s?cent|percent|storeys?|stories))\s+"
_CODES = r"(?:\d{1,3}P\d{4}[,\s]+)*"
EMBEDDED_SUBSECTION_RE = re.compile(
    _BOUNDARY + _CODES + r"\((?P<sub>\d{1,2}(?:\.\d{1,2})?)\)\s+(?=[A-Z(])"
)
EMBEDDED_HEADING_RE = re.compile(
    _BOUNDARY + _CODES + r"(?P<base>\d{1,3})\s+(?=[A-Z][a-z])"
)

# Page footers ('292.2 LAND USE BYLAW – 1P2007 July 23, 2007') repeat on every
# page and would otherwise register as dotted sections.
FOOTER_RE = re.compile(r"(?i)\bland\s+use\s+bylaw\b.*\d{4}|^\s*page\s+\d+\s*$")

# SMALL local keyword map (proposer-only; deliberately NOT the verifier's
# domain_schema so the extraction package stays outside the verify path).
# Checked in order; first hit wins.
RULE_OBJECT_KEYWORDS: list[tuple[str, str]] = [
    ("floor area", "floor_area"),
    ("site coverage", "lot_coverage"),
    ("lot coverage", "lot_coverage"),
    ("impervious", "impervious_surface"),
    # 'separation' before 'setback': a facade-separation clause often also
    # mentions setback areas in its sub-items; the more specific concept wins.
    ("separation", "building_separation"),
    ("setback", "setback"),
    ("yard", "setback"),
    ("storey", "storeys"),
    ("storeys", "storeys"),
    ("height", "height"),
    ("parking", "parking"),
    ("lot area", "lot_area"),
    ("site area", "lot_area"),
    ("lot width", "lot_width"),
    ("dwelling unit", "dwelling_units"),
]

# Wording → operator. Longest phrase at the earliest text position wins.
OPERATOR_PHRASES: list[tuple[str, str]] = [
    ("must not exceed", "<="),
    ("shall not exceed", "<="),
    ("may not exceed", "<="),
    ("does not exceed", "<="),
    ("not exceed", "<="),
    ("no more than", "<="),
    ("no greater than", "<="),
    ("at most", "<="),
    ("maximum", "<="),
    ("shall be at least", ">="),
    ("at least", ">="),
    ("no less than", ">="),
    ("not less than", ">="),
    ("no fewer than", ">="),
    ("minimum", ">="),
]

VALUE_UNIT_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>m²|m2|sq\.?\s?m|square\s+metres?|square\s+meters?|per\s?cent|percent|%"
    r"|storeys?|stories|metres?|meters?|m)(?![A-Za-z0-9])",
    re.IGNORECASE,
)

UNIT_ALIASES: dict[str, str] = {
    "m²": "m2",
    "m2": "m2",
    "sq m": "m2",
    "sq. m": "m2",
    "sqm": "m2",
    "square metre": "m2",
    "square metres": "m2",
    "square meter": "m2",
    "square meters": "m2",
    "%": "%",
    "percent": "%",
    "per cent": "%",
    "storey": "storeys",
    "storeys": "storeys",
    "stories": "storeys",
    "m": "m",
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
}

_SUBJECT_BY_RULE_OBJECT: dict[str, str] = {
    "height": "building",
    "storeys": "building",
    "building_separation": "building",
    "setback": "building",
    "floor_area": "building",
    "lot_coverage": "lot",
    "impervious_surface": "lot",
    "lot_area": "lot",
    "lot_width": "lot",
    "dwelling_units": "lot",
    "parking": "lot",
}


def run_text_stream(intermediate: dict[str, Any], city: str) -> dict[str, Any]:
    """Extract clauses and propose rule candidates from the ingest intermediate.

    Returns {"clauses": [...], "candidates": [...], "sections_seen": [...]}.
    Clauses are the evidence units; candidates cite their clause verbatim.
    """
    city_key = _slug(city)
    clauses = extract_clauses(intermediate, city_key)
    candidates: list[dict[str, Any]] = []
    for clause in clauses:
        candidates.extend(derive_candidates(clause))
    sections_seen = sorted({clause["section"] for clause in clauses})
    return {"clauses": clauses, "candidates": candidates, "sections_seen": sections_seen}


def extract_clauses(intermediate: dict[str, Any], city_key: str) -> list[dict[str, Any]]:
    """Walk page blocks and assemble section-anchored clauses (deterministic).

    Handles two clause grammars with one assembler: dotted sections
    ('11.3.8.2 The floor area ...', Vancouver-style) and bare-number sections
    with parenthesized subsections ('352 Backyard Suite' heading, then
    '352 (1) ...' and code-prefixed continuations '10P2019 (3) ...',
    Calgary-style). Footers and marginal amendment codes are provenance noise
    and are filtered before anchoring.
    """
    clauses: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    sequence = 0
    base_section: str | None = None  # running bare section, e.g. '352'

    def _close() -> None:
        nonlocal current
        if current is not None:
            current["text"] = re.sub(r"\s+", " ", current["text"]).strip()
            clauses.append(current)
            current = None

    def _open(section: str, page_number: int, text: str) -> None:
        nonlocal current, sequence
        _close()
        sequence += 1
        current = {
            "evidence_id": f"{city_key}_{_section_slug(section)}_{sequence:03d}",
            "section": section,
            "page": page_number,
            "text": text,
        }

    def _segments(text: str) -> list[str]:
        """Split a merged block at embedded clause boundaries.

        PDF reflow glues clause tails to the next clause's start; each
        returned segment then starts with whatever marker it carries (full
        anchor, bare heading, or subsection), so the state machine below only
        ever has to look at segment STARTS.
        """
        cuts = [0]
        for pattern, group in ((EMBEDDED_SUBSECTION_RE, "sub"), (EMBEDDED_HEADING_RE, "base")):
            for match in pattern.finditer(text):
                start = match.start(group)
                # Back up to include the '(' for subsection markers.
                if group == "sub":
                    start -= 1
                cuts.append(start)
        cuts = sorted(set(cuts))
        pieces = [text[a:b].strip() for a, b in zip(cuts, cuts[1:] + [len(text)])]
        return [piece for piece in pieces if piece]

    for page in intermediate.get("pages", []):
        page_number = int(page.get("page_number") or 0)
        blocks = page.get("blocks") or blocks_from_text(str(page.get("text") or ""))
        for block in blocks:
            raw = str(block.get("text") or "").strip()
            if not raw or FOOTER_RE.search(raw):
                continue
            raw = AMENDMENT_CODE_RE.sub("", raw).strip()
            if not raw:
                continue
            for text in _segments(raw):
                text = AMENDMENT_CODE_RE.sub("", text).strip()
                if not text:
                    continue
                anchor = SECTION_ANCHOR_RE.match(text)
                if anchor and not UNIT_AFTER_ANCHOR_RE.match(text[anchor.end():]):
                    section = anchor.group("section")
                    base_section = re.match(r"\d{1,3}", section).group(0)
                    _open(section, page_number, text)
                    continue
                heading = BARE_HEADING_RE.match(text)
                if heading:
                    # Title segment establishes the base section. The block
                    # assembler may still have glued the first clause onto the
                    # title ('352 Backyard Suite 12P2012 352 (1) For ...'), so
                    # look for an embedded clause start before discarding the
                    # remainder as a title.
                    base_section = heading.group("base")
                    _close()
                    remainder = text[heading.end():]
                    embedded = re.search(
                        rf"\b{base_section}\s?\((?P<sub>\d{{1,2}}(?:\.\d{{1,2}})?)\)\s+",
                        remainder,
                    )
                    if embedded:
                        _open(
                            f"{base_section}({embedded.group('sub')})",
                            page_number,
                            remainder[embedded.start():],
                        )
                    else:
                        # Unnumbered-body style: '350 Title ... 350 A private
                        # maintenance easement ...' — the repeated bare number
                        # marks where the clause body starts.
                        body = re.search(rf"\b{base_section}\s+(?=[A-Z])", remainder)
                        if body:
                            _open(base_section, page_number, remainder[body.end():])
                    continue
                subsection = SUBSECTION_RE.match(text)
                if subsection and base_section:
                    _open(f"{base_section}({subsection.group('sub')})", page_number, text)
                    continue
                if block.get("kind") == "heading":
                    # A non-numbered heading ends the running clause; clauses
                    # never silently absorb the next topic's title.
                    _close()
                elif current is not None:
                    current["text"] += f" {text}"
        # Close at each page boundary so a clause's single page attribution
        # stays honest (page-spanning continuations are a known, accepted loss
        # for a diagnostic helper).
        _close()
    return clauses


def derive_candidates(clause: dict[str, Any]) -> list[dict[str, Any]]:
    """Propose rule candidates for one numeric-bearing clause.

    One candidate per distinct value+unit match, all citing the full clause as
    evidence_text with the section anchor and page preserved. Clauses with no
    keyword-mapped rule object propose nothing (they remain evidence units).
    """
    text = clause["text"]
    operator = operator_from_wording(text)
    matches = list(VALUE_UNIT_RE.finditer(text))
    if not matches or operator is None:
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for match in matches:
        value = match.group("value")
        unit = normalize_unit(match.group("unit"))
        if (value, unit) in seen:
            continue
        seen.add((value, unit))
        rule_object = rule_object_from_keywords(text, unit)
        if rule_object is None:
            continue
        constraint_type = "maximum" if operator == "<=" else "minimum"
        candidates.append(
            {
                "clause_id": clause["evidence_id"],
                "section": clause["section"],
                "page": clause["page"],
                "rule_key": f"{'max' if operator == '<=' else 'min'}_{rule_object}",
                "rule_object": rule_object,
                "constraint_type": constraint_type,
                "subject": _SUBJECT_BY_RULE_OBJECT.get(rule_object, rule_object),
                "operator": operator,
                "value": value,
                "unit": unit,
                "condition": "",
                "exception": "",
                "evidence_text": text,
                "source_stream": "local_text_block",
            }
        )
    return candidates


def operator_from_wording(text: str) -> str | None:
    """Map clause wording to an operator: earliest phrase wins, longest on ties."""
    lowered = text.lower()
    best: tuple[int, int, str] | None = None
    for phrase, operator in OPERATOR_PHRASES:
        index = lowered.find(phrase)
        if index < 0:
            continue
        key = (index, -len(phrase), operator)
        if best is None or key < best:
            best = key
    return best[2] if best else None


def rule_object_from_keywords(text: str, unit: str | None = None) -> str | None:
    """First keyword hit wins; the UNIT disambiguates combined height/storeys text.

    Keywords match on WORD BOUNDARIES: 'yard' must not fire inside Calgary's
    'Backyard Suite' (which would type every backyard-suite clause as a
    setback regardless of what it regulates).
    """
    lowered = text.lower()
    if unit == "storeys":
        return "storeys"
    for keyword, rule_object in RULE_OBJECT_KEYWORDS:
        if rule_object == "storeys" and unit not in (None, "", "storeys"):
            continue  # a metres/% value in mixed height-and-storeys wording is not a storey count
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return rule_object
    return None


def normalize_unit(raw: str) -> str:
    key = re.sub(r"\s+", " ", str(raw or "").lower().replace(".", "")).strip()
    return UNIT_ALIASES.get(key, key)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _section_slug(section: str) -> str:
    """'5.7(3)(a)' -> '5.7.3.a' so evidence ids stay filename/id friendly."""
    return re.sub(r"\.+", ".", re.sub(r"[()]+", ".", section)).strip(".")
