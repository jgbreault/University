"""V2 full-bylaw source discovery and evidence-pack construction.

Role: foundational source/discovery layer wrapped by the product M7 pipeline.
It is not a standalone lane; M7 consumes its bounded evidence packs downstream.

This layer is RAG/discovery, not verification. It scans the full source text,
keeps parent/list/table context, and emits bounded evidence packs that any
candidate extractor can read.

Discovery is recall-oriented on purpose: it over-collects plausible evidence
and labels every chunk with auditable selection metadata
(``selected_because`` / ``selection_tier`` / ``drop_risk`` /
``discovery_confidence`` / ``rule_types``, adapted from the team's
pipeline-9 auto-discovery). Nothing here can verify a rule; the deterministic
verifier remains the trust gate.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .bylaw_rag import tokenize
from .extraction.pdf_ingest import ingest_pdf, restrict_intermediate_to_pages
from .extraction.text_stream import extract_clauses
from .v2_store import hash_json


DISCOVERY_VERSION = "v2_discovery_2"

MEASUREMENT_RE = re.compile(
    r"(?i)\b\d+(?:\.\d+)?\s*(?:m²|m2|sq\.?\s?m|square\s+metres?|square\s+meters?|"
    r"metres?|meters?|m|%|per\s?cent|percent|storeys?|stories|units?)\b"
)
RULE_CUE_RE = re.compile(
    r"(?i)\b(?:must|shall|required|requires|minimum|maximum|max|min|not\s+exceed|"
    r"no\s+more\s+than|no\s+less\s+than|setback|separation|height|storeys?|"
    r"floor\s+area|site\s+coverage|lot\s+coverage|parcel\s+area|lot\s+area|parking)\b"
)
USE_CUE_RE = re.compile(r"(?i)\b(?:permitted|discretionary|prohibited|use|uses|dwelling|suite)\b")
LEAD_IN_RE = re.compile(
    r"(?i)\b(?:minimum|maximum|required|following|must\s+be|shall\s+be|setback|height|separation)\b.*:\s*$"
)
LIST_CHILD_RE = re.compile(r"^\s*(?:\([a-z]\)|\(\d+(?:\.\d+)?\)|[a-z]\)|\d+\.)\s+")
# A short section heading ('101.5.1 All Dwelling Units') that introduces the
# numbered children below it. The length cap keeps full paragraphs from ever
# becoming a "parent stem".
HEADING_PARENT_RE = re.compile(r"^\s*\d{1,3}(?:\.\d{1,3})+\s+[A-Z]")
HEADING_PARENT_MAX_CHARS = 160
# Children sometimes carry degenerate subsection ids ('101(1)') that encode no
# dotted hierarchy; they cannot contradict the parent's section.
DEGENERATE_SUBSECTION_RE = re.compile(r"^\d{1,4}\(\d")

# Rule-type classification (adapted from pipeline-9 auto_discovery). Advisory
# labels for lanes/audit only — never a verification signal.
RULE_TYPE_RES: list[tuple[str, re.Pattern[str]]] = [
    ("permission", re.compile(r"(?i)\b(?:permitted|discretionary\s+uses?|not\s+permitted|prohibited)\b")),
    (
        "dimensional_standard",
        re.compile(
            r"(?i)\b(?:minimum|maximum|setback|height|floor\s+area|density|coverage|"
            r"amenity|separation|lot\s+area|parcel\s+area|storeys?)\b"
        ),
    ),
    ("parking", re.compile(r"(?i)\b(?:parking|stall|driveway|loading)\b")),
    ("permit_process", re.compile(r"(?i)\b(?:development\s+permit|building\s+permit|notice|approval|authority)\b")),
    ("definition", re.compile(r"(?i)\bmeans\b|\bdefinitions?\b")),
    ("cross_reference", re.compile(r"(?i)\b(?:see\s+section|subject\s+to\s+section|division\s+\d|section\s+\d+\.\d+)\b")),
]

# Per-lane minimum share of the pack budget. Guarantees every evidence lane is
# represented (a Zihao pipeline-9 idea) so context_only chunks can never crowd
# out table/core rule chunks, and vice versa. Leftover budget backfills by
# score regardless of lane.
LANE_QUOTAS: dict[str, float] = {
    "core_rule": 0.40,
    "table_rule": 0.30,
    "universal_applicable_rule": 0.15,
    "use_permission": 0.10,
    "context_only": 0.05,
}


def discovery_options_hash(*, max_packs: int, max_pack_chars: int) -> str:
    return hash_json(
        {
            "version": DISCOVERY_VERSION,
            "max_packs": max_packs,
            "max_pack_chars": max_pack_chars,
        }
    )


def build_source_chunks_from_pdf(
    *,
    pdf_path: Path,
    city: str,
    config: dict[str, Any],
    prefer_docling: bool = False,
    page_ranges: list[tuple[int, int]] | tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Ingest the bylaw PDF and return source chunks for RAG/discovery.

    ``page_ranges`` scopes ingestion to one or more inclusive, 1-based page spans
    on a multi-district bylaw (a single ``(start, end)`` pair, or a list of them
    for disjoint spans such as the suite block + the R-CG district). The corpus —
    and every consumer built from it (RAG retrieval, the M5 slot denominator) —
    then reflects only the deliverable pages instead of the whole document.
    Original page numbers are preserved (chunks keep ``page=471`` etc.), so source
    citations stay valid. ``None`` ingests the whole PDF (the default).
    """
    intermediate = ingest_pdf(pdf_path, prefer_docling=prefer_docling)
    intermediate = restrict_intermediate_to_pages(intermediate, page_ranges)
    return build_source_chunks_from_intermediate(intermediate, city=city, config=config)


def build_source_chunks_from_intermediate(
    intermediate: dict[str, Any],
    *,
    city: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert PDF intermediate text/tables into context-preserving chunks."""
    city_key = _slug(city)
    chunks: list[dict[str, Any]] = []
    chunks.extend(_clause_chunks(intermediate, city_key))
    chunks.extend(_table_chunks(intermediate, city_key))
    if not chunks:
        chunks.extend(_page_chunks(intermediate, city_key))
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        chunk["metadata"] = {
            **(chunk.get("metadata") or {}),
            "target_alias_hit": bool(_alias_hits(text, config)),
            "measurement_count": len(MEASUREMENT_RE.findall(text)),
            "rule_cue_count": len(RULE_CUE_RE.findall(text)),
            "rule_types": _rule_types(_chunk_search_text(chunk)),
            "source_layer": "v2_full_bylaw_source",
        }
    return chunks


def build_evidence_packs(
    chunks: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    max_packs: int = 80,
    max_pack_chars: int = 3600,
) -> list[dict[str, Any]]:
    """Score chunks and return bounded, lane-quota'd evidence packs."""
    scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for chunk in chunks:
        score, signals = score_chunk(chunk, config)
        if score <= 0:
            _stamp_chunk_discovery(chunk, score=score, signals=signals, packed=False)
            continue
        scored.append((score, signals, chunk))

    selected = _select_with_lane_quotas(scored, max_packs=max_packs)
    selected_ids = {id(chunk) for _, _, chunk in selected}
    for score, signals, chunk in scored:
        _stamp_chunk_discovery(chunk, score=score, signals=signals, packed=id(chunk) in selected_ids)

    packs = []
    for index, (score, signals, chunk) in enumerate(selected, start=1):
        source_text = _pack_text(chunk, max_pack_chars)
        packs.append(
            {
                "pack_id": f"v2_pack_{index:04d}",
                "chunk_id": chunk.get("chunk_id"),
                "section": chunk.get("section") or "",
                "page": chunk.get("page"),
                "lane": signals["lane"],
                "source_text": source_text,
                "retrieval_queries": _pack_queries(config, chunk, signals),
                "retrieval_score": round(score, 3),
                "retrieval_signals": signals,
                "evidence_type": chunk.get("evidence_type") or "clause",
                "heading": chunk.get("heading") or "",
                "parent_text": chunk.get("parent_text") or "",
                "table_title": chunk.get("table_title") or "",
                "row_header": chunk.get("row_header") or "",
                "column_header": chunk.get("column_header") or "",
                "cell_value": chunk.get("cell_value") or "",
                "table_cells": (chunk.get("metadata") or {}).get("cells") or [],
                "selected_because": signals.get("selected_because") or [],
                "rule_types": (chunk.get("metadata") or {}).get("rule_types") or [],
                "selection_tier": _selection_tier(score, signals),
                "drop_risk": _drop_risk(score),
                "discovery_confidence": _discovery_confidence(score),
                "rag_discovery": {
                    "version": DISCOVERY_VERSION,
                    "advisory_only": True,
                    "note": "Evidence pack proposes source context; verifier remains authoritative.",
                },
            }
        )
    return packs


def _select_with_lane_quotas(
    scored: list[tuple[float, dict[str, Any], dict[str, Any]]],
    *,
    max_packs: int,
) -> list[tuple[float, dict[str, Any], dict[str, Any]]]:
    """Reserve a budget share per lane, then backfill leftovers by score."""

    def sort_key(item: tuple[float, dict[str, Any], dict[str, Any]]) -> tuple:
        return (
            -item[0],
            int(item[2].get("page") or 0),
            str(item[2].get("chunk_id") or ""),
        )

    by_lane: dict[str, list[tuple[float, dict[str, Any], dict[str, Any]]]] = {}
    for item in scored:
        by_lane.setdefault(str(item[1].get("lane") or "context_only"), []).append(item)
    for lane_items in by_lane.values():
        lane_items.sort(key=sort_key)

    selected: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    taken: set[int] = set()
    for lane, quota in LANE_QUOTAS.items():
        lane_budget = max(1, int(quota * max_packs)) if by_lane.get(lane) else 0
        for item in by_lane.get(lane, [])[:lane_budget]:
            if len(selected) >= max_packs:
                break
            selected.append(item)
            taken.add(id(item[2]))

    if len(selected) < max_packs:
        leftovers = sorted(
            (item for item in scored if id(item[2]) not in taken),
            key=sort_key,
        )
        for item in leftovers[: max_packs - len(selected)]:
            selected.append(item)

    selected.sort(key=lambda item: (_lane_rank(item[1].get("lane")), *sort_key(item)))
    return selected[:max_packs]


def _stamp_chunk_discovery(
    chunk: dict[str, Any],
    *,
    score: float,
    signals: dict[str, Any],
    packed: bool,
) -> None:
    metadata = chunk.setdefault("metadata", {})
    metadata["discovery_score"] = round(score, 3)
    metadata["discovery_confidence"] = _discovery_confidence(score)
    metadata["lane"] = signals.get("lane")
    metadata["selected_because"] = signals.get("selected_because") or []
    metadata["discovery_selected"] = packed
    metadata["selection_tier"] = _selection_tier(score, signals) if packed else (
        "discarded_low_score" if score <= 0 else "discarded_over_budget"
    )
    metadata["drop_risk"] = _drop_risk(score)


def _selection_tier(score: float, signals: dict[str, Any]) -> str:
    lane = str(signals.get("lane") or "")
    if lane in {"core_rule", "table_rule"} and (signals.get("target_aliases") or signals.get("section_hits")):
        return "core"
    if signals.get("measurement_count") and signals.get("rule_cue_count"):
        return "support"
    return "weak_context"


def _drop_risk(score: float) -> str:
    if score >= 8.0:
        return "low"
    if score >= 4.0:
        return "medium"
    return "high"


def _discovery_confidence(score: float) -> float:
    return round(max(0.0, min(1.0, score / 12.0)), 3)


def _rule_types(text: str) -> list[str]:
    types = [name for name, pattern in RULE_TYPE_RES if pattern.search(text)]
    if not types and RULE_CUE_RE.search(text):
        types = ["general_rule"]
    return types


def score_chunk(chunk: dict[str, Any], config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    text = _chunk_search_text(chunk)
    aliases = _alias_hits(text, config)
    target_count = len(aliases)
    measurements = MEASUREMENT_RE.findall(text)
    rule_cues = RULE_CUE_RE.findall(text)
    use_cues = USE_CUE_RE.findall(text)
    section_hits = _section_hits(chunk.get("section"), config)
    is_table = str(chunk.get("evidence_type") or "") in {"table_cell", "table_row"}
    has_parent = bool(str(chunk.get("parent_text") or "").strip())
    closure = str((chunk.get("metadata") or {}).get("closure") or "")
    score = 0.0
    score += 4.0 * target_count
    score += 3.0 if measurements else 0.0
    score += min(4.0, 0.75 * len(rule_cues))
    score += 2.0 if section_hits else 0.0
    score += 1.5 if is_table and measurements else 0.0
    score += 0.75 if has_parent else 0.0
    if "definition" in text.lower() and not measurements:
        score -= 2.0
    lane = _lane_for_chunk(
        text,
        target_count=target_count,
        has_measurement=bool(measurements),
        has_rule_cue=bool(rule_cues),
        has_use_cue=bool(use_cues),
        is_table=is_table,
        section_hits=section_hits,
    )
    if lane == "context_only" and not aliases:
        score = min(score, 1.0)
    selected_because: list[str] = []
    selected_because.extend(f"target_term_hit:{alias}" for alias in aliases[:3])
    if measurements:
        selected_because.append("measurement_signal")
    if rule_cues:
        selected_because.append("rule_cue_signal")
    if section_hits:
        selected_because.append("target_section_match")
    if is_table and measurements:
        selected_because.append("table_row_with_measurement")
    if has_parent:
        selected_because.append("parent_stem_attached")
    if closure:
        selected_because.append(closure)
    return score, {
        "lane": lane,
        "target_aliases": aliases,
        "measurement_count": len(measurements),
        "rule_cue_count": len(rule_cues),
        "use_cue_count": len(use_cues),
        "section_hits": section_hits,
        "is_table": is_table,
        "has_parent_context": has_parent,
        "selected_because": selected_because,
    }


def retrieval_corpus_from_packs(packs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a BylawIndex-compatible corpus from V2 evidence packs."""
    return [
        {
            "chunk_id": str(pack.get("pack_id") or pack.get("chunk_id") or ""),
            "section": str(pack.get("section") or ""),
            "page": pack.get("page"),
            "text": str(pack.get("source_text") or ""),
        }
        for pack in packs
        if str(pack.get("source_text") or "").strip()
    ]


def _clause_chunks(intermediate: dict[str, Any], city_key: str) -> list[dict[str, Any]]:
    """Clause chunks with multi-child list-continuation closure.

    When a parent clause is a lead-in ("The minimum setback is:"), every
    consecutive child item on the SAME page whose section is compatible with
    the parent's gets the parent stem attached as ``parent_text``. The stem is
    always real extracted clause text from the same page — never invented —
    and the attachment is recorded in chunk metadata for audit.
    """
    clauses = extract_clauses(intermediate, city_key)
    chunks: list[dict[str, Any]] = []
    last_by_page: dict[int, dict[str, Any]] = {}
    # Two-level parent state per page: the section heading / lead-in clause
    # owns numeric children '(1) ...'; a numeric child that itself ends in a
    # lead-in (':') owns the letter children '(a) ...' that follow it.
    heading_parent_by_page: dict[int, dict[str, Any]] = {}
    numeric_child_parent_by_page: dict[int, dict[str, Any]] = {}
    for clause in clauses:
        page = int(clause.get("page") or 0)
        text = str(clause.get("text") or "").strip()
        section = str(clause.get("section") or "")
        previous = last_by_page.get(page)
        parent_text = ""
        child_text = ""
        closure = ""
        is_letter_child = bool(re.match(r"^\s*\(?[a-z]\)\s+", text))
        is_child = _looks_like_child_clause(text)
        if is_child:
            if previous and not _looks_like_child_clause(previous.get("text", "")) and (
                _looks_like_parent_lead_in(previous.get("text", ""))
                or _looks_like_heading_parent(previous.get("text", ""))
            ):
                heading_parent_by_page[page] = {
                    "text": str(previous.get("text") or ""),
                    "section": str(previous.get("section") or ""),
                }
            parent = None
            if is_letter_child:
                parent = numeric_child_parent_by_page.get(page) or heading_parent_by_page.get(page)
            else:
                parent = heading_parent_by_page.get(page)
                if _looks_like_parent_lead_in(text):
                    numeric_child_parent_by_page[page] = {"text": text, "section": section}
                else:
                    numeric_child_parent_by_page.pop(page, None)
            if parent and _section_compatible(parent.get("section", ""), section):
                parent_text = parent["text"]
                child_text = text
                direct = bool(previous) and str(previous.get("text") or "").strip() == str(parent.get("text") or "").strip()
                closure = "direct_parent_lead_in" if direct else "list_continuation_closure"
        else:
            # A non-child clause closes any open list on this page.
            heading_parent_by_page.pop(page, None)
            numeric_child_parent_by_page.pop(page, None)
        metadata: dict[str, Any] = {"source": "extract_clauses"}
        if closure:
            metadata["closure"] = closure
            metadata["closure_parent_section"] = str((parent or {}).get("section") or "")
        chunks.append(
            {
                "chunk_id": clause.get("evidence_id"),
                "section": section,
                "page": page,
                "heading": "",
                "parent_text": parent_text,
                "child_text": child_text,
                "table_title": "",
                "row_header": "",
                "column_header": "",
                "cell_value": "",
                "text": text,
                "evidence_type": "clause",
                "metadata": metadata,
            }
        )
        last_by_page[page] = {"text": text, "section": section}
    return chunks


def _section_compatible(parent_section: str, child_section: str) -> bool:
    """Same-section guard for closure: equal, prefix-related, or unknown."""
    parent = str(parent_section or "").strip()
    child = str(child_section or "").strip()
    if not parent or not child:
        return True
    if DEGENERATE_SUBSECTION_RE.match(child):
        # '101(1)'-style ids encode no dotted hierarchy; page locality and
        # clause order carry the relationship instead.
        return True
    return parent == child or child.startswith(parent) or parent.startswith(child)


def _looks_like_heading_parent(text: str) -> bool:
    value = str(text or "").strip()
    return bool(
        value
        and len(value) <= HEADING_PARENT_MAX_CHARS
        and HEADING_PARENT_RE.match(value)
        and not _looks_like_child_clause(value)
    )


def _table_chunks(intermediate: dict[str, Any], city_key: str) -> list[dict[str, Any]]:
    """One chunk per table ROW, preserving title + row header + every column.

    Burnaby's bylaw is table-heavy; atomizing each cell into its own chunk
    starves the extractor of row context and wastes the pack budget. A row
    chunk carries every (column header, value) pair, so a single pack shows
    the extractor the full row. Cell-level provenance is preserved in
    ``metadata.cells``; single-cell rows keep the legacy cell-level fields.
    """
    chunks: list[dict[str, Any]] = []
    table_index = 0
    for page in intermediate.get("pages", []):
        page_number = int(page.get("page_number") or 0)
        for table in page.get("tables", []) or []:
            rows = table.get("rows") or []
            if not rows:
                continue
            table_index += 1
            headers = [str(cell or "").strip() for cell in rows[0]]
            title = str(table.get("title_guess") or "").strip()
            for row_index, row in enumerate(rows[1:] if len(rows) > 1 else rows, start=1):
                cells = [str(cell or "").strip() for cell in row]
                row_header = cells[0] if cells else ""
                pairs: list[dict[str, str]] = []
                for col_index, cell in enumerate(cells[1:] if len(cells) > 1 else cells, start=1):
                    if not cell:
                        continue
                    column_header = headers[col_index] if col_index < len(headers) else ""
                    pairs.append({"column_header": column_header, "cell_value": cell})
                if not pairs:
                    continue
                pair_text = "; ".join(
                    f"{pair['column_header']}: {pair['cell_value']}" if pair["column_header"] else pair["cell_value"]
                    for pair in pairs
                )
                text = " | ".join(part for part in (title, row_header, pair_text) if part)
                single = pairs[0] if len(pairs) == 1 else None
                chunks.append(
                    {
                        "chunk_id": f"{city_key}_table_{table_index:03d}_r{row_index:03d}",
                        "section": "",
                        "page": page_number,
                        "heading": title,
                        "parent_text": "",
                        "child_text": "",
                        "table_title": title,
                        "row_header": row_header,
                        "column_header": single["column_header"] if single else "",
                        "cell_value": single["cell_value"] if single else "",
                        "text": text,
                        "evidence_type": "table_cell" if single else "table_row",
                        "metadata": {"source": "pdf_table", "table_index": table_index, "cells": pairs},
                    }
                )
    return chunks


def _page_chunks(intermediate: dict[str, Any], city_key: str) -> list[dict[str, Any]]:
    chunks = []
    for page in intermediate.get("pages", []):
        text = re.sub(r"\s+", " ", str(page.get("text") or "")).strip()
        if not text:
            continue
        page_number = int(page.get("page_number") or 0)
        chunks.append(
            {
                "chunk_id": f"{city_key}_page_{page_number:04d}",
                "section": "",
                "page": page_number,
                "heading": "",
                "parent_text": "",
                "child_text": "",
                "table_title": "",
                "row_header": "",
                "column_header": "",
                "cell_value": "",
                "text": text,
                "evidence_type": "page",
                "metadata": {"source": "page_text"},
            }
        )
    return chunks


def _pack_text(chunk: dict[str, Any], max_chars: int) -> str:
    parts = []
    if chunk.get("heading"):
        parts.append(f"Heading: {chunk['heading']}")
    if chunk.get("parent_text"):
        parts.append(f"Parent context: {chunk['parent_text']}")
    if chunk.get("table_title") or chunk.get("row_header") or chunk.get("column_header"):
        parts.append(
            "Table context: "
            + " | ".join(
                str(chunk.get(field) or "")
                for field in ("table_title", "row_header", "column_header")
                if str(chunk.get(field) or "").strip()
            )
        )
    parts.append(str(chunk.get("text") or ""))
    text = re.sub(r"\s+", " ", "\n".join(part for part in parts if part).strip())
    return text[:max_chars]


def _chunk_search_text(chunk: dict[str, Any]) -> str:
    return " ".join(
        str(chunk.get(field) or "")
        for field in ("heading", "parent_text", "table_title", "row_header", "column_header", "cell_value", "text")
    )


def _alias_hits(text: str, config: dict[str, Any]) -> list[str]:
    lowered = str(text or "").lower()
    aliases = [str(config.get("target_concept") or "")]
    aliases.extend(str(alias) for alias in config.get("known_aliases", []) or [])
    hits = []
    for alias in aliases:
        alias = re.sub(r"\s+", " ", alias.lower()).strip()
        if alias and alias in lowered:
            hits.append(alias)
    # Token overlap catches long target concepts without requiring the full
    # sentence to appear verbatim.
    target_words = set(tokenize(str(config.get("target_concept") or "")))
    if len(target_words & set(tokenize(lowered))) >= 2:
        hits.append("target_concept_terms")
    return sorted(set(hits))


def _section_hits(section: Any, config: dict[str, Any]) -> list[str]:
    section_text = str(section or "")
    scope_text = " ".join(str(config.get(field) or "") for field in ("bylaw", "source_document"))
    targets = re.findall(r"\b\d{2,4}(?:\.\d{1,3})?\b", scope_text)
    return [target for target in targets if section_text == target or section_text.startswith(f"{target}.") or section_text.startswith(f"{target}(")]


def _lane_for_chunk(
    text: str,
    *,
    target_count: int,
    has_measurement: bool,
    has_rule_cue: bool,
    has_use_cue: bool,
    is_table: bool,
    section_hits: list[str],
) -> str:
    if is_table and has_measurement:
        return "table_rule"
    if has_measurement and (target_count or section_hits) and has_rule_cue:
        return "core_rule"
    if has_measurement and has_rule_cue:
        return "universal_applicable_rule"
    if target_count and has_use_cue:
        return "use_permission"
    return "context_only"


def _lane_rank(lane: Any) -> int:
    order = {
        "core_rule": 0,
        "table_rule": 1,
        "universal_applicable_rule": 2,
        "use_permission": 3,
        "context_only": 4,
    }
    return order.get(str(lane or ""), 9)


def _pack_queries(config: dict[str, Any], chunk: dict[str, Any], signals: dict[str, Any]) -> list[str]:
    values = [
        str(config.get("target_concept") or ""),
        *[str(alias) for alias in signals.get("target_aliases", [])],
        str(chunk.get("section") or ""),
        str(signals.get("lane") or ""),
    ]
    return [value for value in values if value.strip()]


def _looks_like_child_clause(text: str) -> bool:
    return bool(LIST_CHILD_RE.match(str(text or "")))


def _looks_like_parent_lead_in(text: str) -> bool:
    value = str(text or "").strip()
    return bool(LEAD_IN_RE.search(value) or (value.endswith(":") and RULE_CUE_RE.search(value)))


def source_summary(chunks: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    lanes = Counter(str(pack.get("lane") or "") for pack in packs)
    evidence_types = Counter(str(chunk.get("evidence_type") or "") for chunk in chunks)
    tiers = Counter(str(pack.get("selection_tier") or "") for pack in packs)
    pages = sorted({int(chunk.get("page") or 0) for chunk in chunks if chunk.get("page")})
    packed_pages = sorted({int(pack.get("page") or 0) for pack in packs if pack.get("page")})
    closure_count = sum(1 for chunk in chunks if (chunk.get("metadata") or {}).get("closure"))
    return {
        "source_layer": "v2_full_bylaw_source",
        "discovery_version": DISCOVERY_VERSION,
        "source_chunk_count": len(chunks),
        "evidence_pack_count": len(packs),
        "page_count": len(pages),
        "first_page": pages[0] if pages else None,
        "last_page": pages[-1] if pages else None,
        "packed_page_count": len(packed_pages),
        "list_continuation_closure_count": closure_count,
        "evidence_type_counts": [{"name": name, "count": count} for name, count in sorted(evidence_types.items())],
        "lane_counts": [{"name": name, "count": count} for name, count in sorted(lanes.items())],
        "selection_tier_counts": [{"name": name, "count": count} for name, count in sorted(tiers.items())],
        "advisory_only": True,
    }


def discovery_audit(chunks: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    """Auditable view of what discovery kept and what it left behind.

    Mirrors the team's pipeline-9 audit artifacts: every discarded chunk that
    still carries a rule signal (measurement + rule cue) is listed as a
    near-miss so a human can confirm nothing load-bearing was dropped.
    """
    packed_chunk_ids = {str(pack.get("chunk_id") or "") for pack in packs}
    near_misses = []
    tier_counts: Counter[str] = Counter()
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        tier = str(metadata.get("selection_tier") or "unscored")
        tier_counts[tier] += 1
        if str(chunk.get("chunk_id") or "") in packed_chunk_ids:
            continue
        if metadata.get("measurement_count") and metadata.get("rule_cue_count"):
            near_misses.append(
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "page": chunk.get("page"),
                    "section": chunk.get("section"),
                    "lane": metadata.get("lane"),
                    "selection_tier": tier,
                    "discovery_score": metadata.get("discovery_score"),
                    "drop_risk": metadata.get("drop_risk"),
                    "selected_because": metadata.get("selected_because"),
                    "text_preview": str(chunk.get("text") or "")[:240],
                }
            )
    near_misses.sort(key=lambda row: -(row.get("discovery_score") or 0.0))
    return {
        "discovery_version": DISCOVERY_VERSION,
        "advisory_only": True,
        "pack_count": len(packs),
        "chunk_count": len(chunks),
        "selection_tier_counts": [{"name": name, "count": count} for name, count in sorted(tier_counts.items())],
        "near_miss_count": len(near_misses),
        "near_misses_dropped_with_rule_signal": near_misses[:50],
        "note": "Near-misses are scored chunks with measurement+rule cues that did not fit the pack budget; raise --max-packs if this list is non-empty.",
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
