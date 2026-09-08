"""Source-backed evidence repair before deterministic verification.

This module is deliberately narrow: it may add source text found in the cached
bylaw PDF/page text, and it may flag mismatches. It does not decide whether a
rule is correct, and it does not import RAG, LLM, or verifier modules.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .support_checks import local_source_context, value_present_on_page


_PAGE_CACHE: dict[tuple[str, int], str] = {}
_SOURCE_CONTEXT_RADIUS = 450
_MAX_STEM_CHARS = 240
_LONG_SELF_CONTAINED_CHARS = 320
_CHILD_CLAUSE_RE = re.compile(r"^\s*\(([a-z]|\d+(?:\.\d+)?)\)\s+", re.IGNORECASE)
_LEAD_IN_CUES = (
    "minimum",
    "maximum",
    "must",
    "may",
    "required",
    "permitted",
    "prohibited",
    "not exceed",
    "at least",
    "lesser of",
    "greater of",
)


def source_pdf_for_config(config: dict[str, Any]) -> Path | None:
    """Return the conventional cached source PDF for a loaded city config."""
    config_path = config.get("_config_path")
    if not config_path:
        return None
    root = Path(config_path).resolve().parents[1]
    stem = Path(config_path).stem
    source_pdf = root / "data" / "bylaws" / stem / "source.pdf"
    return source_pdf if source_pdf.exists() else None


def repair_evidence_from_source(
    evidence_units: list[dict[str, Any]],
    rule_candidates: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    source_pdf: Path | None = None,
    source_pages: dict[int, str] | None = None,
    use_config_source_pdf: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return repaired evidence/candidates plus an advisory repair report.

    Repairs are source-backed only. A successful anchor replaces/extends
    ``source_context`` with an authentic page window and may prepend a parent
    lead-in found on the same page. A mismatch forces review only for strict
    upstreams such as Pipeline 9; table/prose extraction formats that do not
    quote PDF text verbatim are reported but not penalized.
    """
    source_pdf = source_pdf or (source_pdf_for_config(config) if use_config_source_pdf else None)
    source_pages = source_pages or {}
    repaired_units: list[dict[str, Any]] = []
    repair_items: list[dict[str, Any]] = []
    strict_mismatch_ids: set[str] = set()

    # Candidate values keyed by evidence id: a re-anchor must corroborate the
    # value on the page, not merely a header prefix (a generic header like
    # "Building Height:" can anchor the window while the value is hallucinated).
    values_by_evidence: dict[str, list[Any]] = {}
    for candidate in rule_candidates:
        values_by_evidence.setdefault(str(candidate.get("evidence_id") or ""), []).append(candidate.get("value"))

    for unit in evidence_units:
        current = dict(unit)
        evidence_id = str(current.get("evidence_id") or "")
        page = _page_number(current)
        page_text = _page_text(page, source_pages, source_pdf)
        item = _repair_one_unit(current, page_text, values_by_evidence.get(evidence_id, []))
        if item["status"] == "source_mismatch" and _strict_reanchor_required(current):
            strict_mismatch_ids.add(evidence_id)
        current["source_repair"] = {
            "status": item["status"],
            "page": page,
            "actions": item["actions"],
            "forced_review": evidence_id in strict_mismatch_ids,
        }
        if item["status"] == "reanchored":
            current["source_context"] = item["source_context"]
            if item.get("parent_context"):
                current["inherited_parent_context"] = item["parent_context"]
            current["reanchored_to_source"] = True
            current.pop("rag_context_mismatch", None)
        elif item["status"] == "source_mismatch":
            current["rag_context_mismatch"] = True
        repaired_units.append(current)
        repair_items.append(
            {
                "evidence_id": evidence_id,
                "page": page,
                "status": item["status"],
                "actions": item["actions"],
                "forced_review": evidence_id in strict_mismatch_ids,
                "quote": _short(current.get("evidence_text")),
                "source_context": _short(current.get("source_context"), limit=520),
                "parent_context": _short(current.get("inherited_parent_context")),
            }
        )

    repaired_candidates = [_repair_candidate(candidate, strict_mismatch_ids) for candidate in rule_candidates]
    status_counts: dict[str, int] = {}
    for item in repair_items:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    report = {
        "purpose": "Source-backed evidence repair before verification. Advisory/debug only; the verifier still decides.",
        "source_pdf": str(source_pdf) if source_pdf else None,
        "attempted": bool(source_pdf or source_pages),
        "evidence_count": len(evidence_units),
        "candidate_count": len(rule_candidates),
        "status_counts": status_counts,
        "forced_review_count": len(strict_mismatch_ids),
        "items": repair_items,
    }
    return repaired_units, repaired_candidates, report


def _repair_one_unit(unit: dict[str, Any], page_text: str, joined_values: list[Any] | None = None) -> dict[str, Any]:
    text = _squash(unit.get("evidence_text"))
    if not text:
        return {"status": "no_evidence_text", "actions": [], "source_context": unit.get("source_context") or "", "parent_context": ""}
    if not page_text:
        return {"status": "no_source_page", "actions": [], "source_context": unit.get("source_context") or text, "parent_context": ""}

    page_text = _squash(page_text)
    window = local_source_context(text, page_text, radius=_SOURCE_CONTEXT_RADIUS)
    if not window:
        return {"status": "source_mismatch", "actions": ["source_text_not_found_on_claimed_page"], "source_context": unit.get("source_context") or text, "parent_context": ""}

    # A window can anchor on a generic header prefix while the value-bearing
    # clause is fabricated. Require at least one joined candidate value to
    # actually appear on the page; a value-less candidate is corroborated by
    # the window alone. A hallucinated value -> source_mismatch -> forced review.
    joined_values = joined_values or []
    if joined_values and not any(value_present_on_page(value, page_text) for value in joined_values):
        return {"status": "source_mismatch", "actions": ["candidate_value_not_found_on_claimed_page"], "source_context": unit.get("source_context") or text, "parent_context": ""}

    actions = ["reanchored_to_source_page"]
    anchor = _anchor_index(text, page_text)
    parent = ""
    if _is_long_self_contained(text):
        repaired_context = text
        actions.append("long_evidence_context_limited")
    else:
        parent = _parent_stem(page_text, anchor) if anchor is not None and _needs_parent_stem(text) else ""
        repaired_context = window
        if parent:
            actions.append("parent_lead_in_attached")
            repaired_context = f"{parent} {text}".strip()
    if _has_table_context(unit):
        actions.append("table_context_preserved")
    return {"status": "reanchored", "actions": actions, "source_context": repaired_context, "parent_context": parent}


def _repair_candidate(candidate: dict[str, Any], strict_mismatch_ids: set[str]) -> dict[str, Any]:
    current = dict(candidate)
    if str(current.get("evidence_id") or "") not in strict_mismatch_ids:
        return current
    current["extraction_final_action"] = "REVIEW"
    reasons = list(current.get("extraction_review_reasons") or [])
    if "rag_context_mismatch" not in reasons:
        reasons.append("rag_context_mismatch")
    current["extraction_review_reasons"] = reasons
    return current


def _page_number(unit: dict[str, Any]) -> int | None:
    value = (unit.get("p9_provenance") or {}).get("original_page_number") if isinstance(unit.get("p9_provenance"), dict) else None
    value = value or unit.get("page")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_text(page: int | None, source_pages: dict[int, str], source_pdf: Path | None) -> str:
    if not page:
        return ""
    if page in source_pages:
        return source_pages[page]
    if not source_pdf or not source_pdf.exists():
        return ""
    key = (str(source_pdf.resolve()), int(page))
    if key not in _PAGE_CACHE:
        try:
            import pdfplumber

            with pdfplumber.open(str(source_pdf)) as pdf:
                _PAGE_CACHE[key] = pdf.pages[page - 1].extract_text() or "" if 1 <= page <= len(pdf.pages) else ""
        except Exception:
            _PAGE_CACHE[key] = ""
    return _PAGE_CACHE[key]


def _strict_reanchor_required(unit: dict[str, Any]) -> bool:
    provenance = unit.get("p9_provenance")
    return bool(provenance or unit.get("adapter_source") == "pipeline9" or unit.get("table_parser") == "pipeline9_visual_blocks")


def _anchor_index(evidence_text: str, source_text: str) -> int | None:
    for needle in _needles(evidence_text):
        index = source_text.lower().find(needle.lower())
        if index != -1:
            return index
    return None


def _needles(text: str) -> list[str]:
    text = _squash(text)
    return [needle for needle in [text, text.split("|", 1)[0], text.split("(", 1)[0], text.split(":", 1)[0]] if needle.strip()]


def _needs_parent_stem(text: str) -> bool:
    lowered = text.lower()
    return bool(_CHILD_CLAUSE_RE.search(text)) or not any(cue in lowered for cue in _LEAD_IN_CUES)


def _is_long_self_contained(text: str) -> bool:
    return len(text) >= _LONG_SELF_CONTAINED_CHARS and bool(re.search(r"\d+(?:\.\d+)?\s*(?:m|metres?|%)\b", text, re.IGNORECASE))


def _parent_stem(source_text: str, anchor: int | None) -> str:
    if anchor is None or anchor <= 0:
        return ""
    left = source_text[max(0, anchor - 700):anchor].strip()
    if not left:
        return ""
    # Prefer explicit lead-ins ending with a colon, then fall back to the last
    # nearby sentence containing operator/legal cue words.
    colon = left.rfind(":")
    if colon != -1:
        candidate = left[max(0, colon - _MAX_STEM_CHARS): colon + 1].strip()
        if _has_lead_in_cue(candidate):
            return _trim_to_clause(candidate)
    for segment in reversed(re.split(r"(?<=[.;])\s+", left)):
        segment = segment.strip()
        if _has_lead_in_cue(segment):
            return _trim_to_clause(segment)
    tail = _trim_to_clause(left[-_MAX_STEM_CHARS:])
    return tail if _has_lead_in_cue(tail) else ""


def _has_lead_in_cue(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in _LEAD_IN_CUES)


def _trim_to_clause(text: str) -> str:
    text = _squash(text)
    if len(text) <= _MAX_STEM_CHARS:
        return text
    return text[-_MAX_STEM_CHARS:].lstrip(" ,;:-")


def _has_table_context(unit: dict[str, Any]) -> bool:
    return any(unit.get(field) for field in ("table_title", "row_header", "column_header", "cell_value"))


def _squash(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _short(value: Any, *, limit: int = 260) -> str:
    text = _squash(value)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
