"""Pipeline 9 (RAG candidate generator) -> verifier-contract adapter.

PROPOSER-TIER, like zihao_adapter: this module translates upstream output into
the verifier's candidate/evidence contract and may only make the verifier MORE
conservative, never less. The product rule it serves:

    Pipeline 9/RAG proposes.  Verification proves.  GIS consumes only verified.

Upstream labels are honored asymmetrically: ``review_required=True``,
``warnings``, an unjoinable evidence block, or a re-anchor mismatch all force
``extraction_final_action=REVIEW`` (the verifier's upstream-uncertainty hold);
``review_required=False`` grants NOTHING.

Inputs (shapes verified against real runs):
* ``06_rule_extraction*/merged_rules_deduplicated.json`` — rule records with
  ``source_id`` (``<pack>__page_NNNN__local_NNN``), P9-vocabulary
  ``rule_object``, list-shaped ``applies_to``, ``constraint_type``
  ('dimensional'), ``review_required``/``review_reasons``/``warnings``.
* ``05_rag_visual_blocks/text_blocks.jsonl`` — blocks with ``block_id``,
  ``original_source_id``, ``rag_pack_id``, ``rag_lane``, ``rag_applicability``,
  ``original_page_number`` (TRUE bylaw page), pseudo ``page_number``,
  ``target_filter_action``. NOTE: blocks have NO ``source_id`` field — the
  join is rule.source_id -> block.block_id, with a
  (rag_pack_id, original_source_id) fallback.

RE-ANCHORING (evidence repair only — the contract, verbatim):
    Re-anchoring can provide authentic source context.
    It cannot promote a candidate.
    If authentic source text supports all fields, the verifier may verify.
    If condition/scope/operator remains ambiguous, keep review_needed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .support_checks import local_source_context, value_present_on_page

# P9's merger concatenates evidence across blocks with bracketed labels:
# '[<pack>__page_NNNN__local_NNN] text [<pack>__...] text'. Two or more labels
# means the evidence_text is STITCHED ACROSS SOURCES — the exact failure class
# our bundle guards forbid (a neighboring clause can donate an operator or
# qualifier the value's own clause never had), but arriving as a single unit
# that would bypass those guards. Caught live: a ceiling-height COMPUTATION
# threshold (3.1 m) verified as a height cap through stitched context.
# The pack-id character class is deliberately PERMISSIVE (anything but the
# closing bracket / the __page__ delimiter) so labels whose pack id carries a
# hyphen or dot ('r-cg', 'rcg.v2') are still recognized as stitch markers.
# A narrow [A-Za-z0-9_]+ class let '[r-cg__page_0440__local_001]' slip the
# guard, re-opening the cross-source value+operator stitch leak for any
# upstream pack id that is not pure-alnum-underscore (the district label is
# literally 'R-CG', so this is realizable, not hypothetical).
STITCH_LABEL_RE = re.compile(r"\[[^\[\]]+?__page_\d+__local_\d+\]")

# Provenance fields preserved verbatim on every evidence unit and candidate.
PROVENANCE_FIELDS = (
    "original_page_number",
    "pseudo_page",
    "rag_pack_id",
    "rag_lane",
    "rag_applicability",
    "target_filter_action",
    "source_id",
    "block_id",
)

# P9 family vocabulary -> verifier families (city-neutral). Unknown families
# pass through unchanged and land in review/not_used — fail-closed, never
# dropped, never guessed.
P9_FAMILY_ALIASES = {
    "separation_distance": "building_separation",
    "building_separation": "building_separation",
    "setback_distance": "setback",
    "site_coverage": "lot_coverage",
    "floor_area_ratio": "floor_space_ratio",
    "building_height": "height",
}

_MAX_CONTEXT_CHARS = 1600


def adapt_pipeline9_run(
    run_dir: str | Path,
    city: str,
    config: dict[str, Any] | None = None,
    *,
    source_pdf: str | Path | None = None,
) -> dict[str, Any]:
    """Adapt one Pipeline 9 city run into the verifier contract.

    Returns ``{"evidence_units", "rule_candidates", "summary"}``. When
    ``source_pdf`` exists, evidence is re-anchored to the true page text
    (see module docstring contract); otherwise that pass is skipped and
    recorded in the summary.
    """
    run_path = Path(run_dir)
    rules, rules_path = _load_merged_rules(run_path)
    blocks, by_block_id, by_pack_source = _load_blocks(run_path)

    evidence_units: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    unjoined = 0

    for index, rule in enumerate(rules, start=1):
        block = _join_block(rule, by_block_id, by_pack_source)
        if block is None:
            unjoined += 1
        evidence = _evidence_unit(city, rule, block, blocks)
        if evidence["evidence_id"] not in seen_evidence:
            seen_evidence.add(evidence["evidence_id"])
            evidence_units.append(evidence)
        candidates.append(_candidate(city, rule, evidence, block, index))

    reanchor_summary = {"attempted": False}
    if source_pdf and Path(source_pdf).exists():
        reanchor_summary = reanchor_to_source(evidence_units, candidates, Path(source_pdf))

    return {
        "evidence_units": evidence_units,
        "rule_candidates": candidates,
        "summary": {
            "pipeline": "pipeline9_rag",
            "rules_path": rules_path,
            "rule_count": len(candidates),
            "evidence_count": len(evidence_units),
            "unjoined_blocks": unjoined,
            "reanchor": reanchor_summary,
        },
    }


def _load_merged_rules(run_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Find merged_rules_deduplicated.json under any 06_rule_extraction* dir.

    A run dir can hold SEVERAL extraction attempts (full runs, page-subset
    smokes). Deterministic choice: full extraction beats smoke; within a tier
    the file with the MOST rules wins (path as final tiebreak) — and the
    chosen path is returned so the run summary shows exactly which extraction
    fed the verifier.
    """
    found = sorted(set(run_path.glob("06_rule_extraction*/**/merged_rules_deduplicated.json")))
    if not found:
        raise FileNotFoundError(f"no merged_rules_deduplicated.json under {run_path}/06_rule_extraction*")

    def _rules_of(path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else payload.get("rules", [])

    non_smoke = [p for p in found if "smoke" not in str(p)]
    tier = non_smoke or found
    chosen = max(tier, key=lambda p: (len(_rules_of(p)), str(p)))
    return _rules_of(chosen), str(chosen)


def _load_blocks(run_path: Path) -> tuple[list[dict], dict[str, dict], dict[tuple[str, str], dict]]:
    blocks: list[dict[str, Any]] = []
    path = run_path / "05_rag_visual_blocks" / "text_blocks.jsonl"
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    blocks.append(json.loads(line))
    by_block_id = {str(b.get("block_id") or ""): b for b in blocks}
    by_pack_source = {
        (str(b.get("rag_pack_id") or ""), str(b.get("original_source_id") or "")): b
        for b in blocks
    }
    return blocks, by_block_id, by_pack_source


def _join_block(
    rule: dict[str, Any],
    by_block_id: dict[str, dict],
    by_pack_source: dict[tuple[str, str], dict],
) -> dict[str, Any] | None:
    """rule.source_id -> block.block_id, else (pack, original_source_id)."""
    source_id = str(rule.get("source_id") or "")
    if source_id in by_block_id:
        return by_block_id[source_id]
    # source_id pattern: <pack>__page_NNNN__local_NNN
    match = re.match(r"(?P<pack>.+?)__(?P<orig>page_\d+__local_\d+)$", source_id)
    if match:
        return by_pack_source.get((match.group("pack"), match.group("orig")))
    return None


def _pack_context(block: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    """Bounded same-pack context in reading order (RAG pack = retrieval unit)."""
    pack = str(block.get("rag_pack_id") or "")
    if not pack:
        return str(block.get("text") or "")
    siblings = sorted(
        (b for b in blocks if str(b.get("rag_pack_id") or "") == pack),
        key=lambda b: (int(b.get("page_number") or 0), int(b.get("reading_order") or 0)),
    )
    joined = " ".join(str(b.get("text") or "").strip() for b in siblings)
    return re.sub(r"\s+", " ", joined)[:_MAX_CONTEXT_CHARS]


def _evidence_unit(
    city: str,
    rule: dict[str, Any],
    block: dict[str, Any] | None,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    source_id = str(rule.get("source_id") or f"{city}_p9_{rule.get('rule_id')}")
    if block is not None:
        text = re.sub(r"\s+", " ", str(block.get("text") or "")).strip()
        unit = {
            "evidence_id": source_id,
            "page": block.get("original_page_number"),
            "evidence_type": "clause",
            "evidence_text": text or str(rule.get("evidence_text") or ""),
            "source_context": _pack_context(block, blocks),
        }
    else:
        # Unjoinable block: keep the rule's own quoted evidence so the verifier
        # still has SOMETHING to check, and flag the gap (forces REVIEW below).
        unit = {
            "evidence_id": source_id,
            "page": None,
            "evidence_type": "clause",
            "evidence_text": str(rule.get("evidence_text") or ""),
            "source_context": str(rule.get("evidence_text") or ""),
            "p9_block_unjoined": True,
        }
    unit["p9_provenance"] = _provenance(rule, block)
    return unit


def _provenance(rule: dict[str, Any], block: dict[str, Any] | None) -> dict[str, Any]:
    block = block or {}
    return {
        "original_page_number": block.get("original_page_number"),
        "pseudo_page": block.get("page_number") or rule.get("batch_id"),
        "rag_pack_id": block.get("rag_pack_id"),
        "rag_lane": block.get("rag_lane"),
        "rag_applicability": block.get("rag_applicability"),
        "target_filter_action": block.get("target_filter_action"),
        "source_id": rule.get("source_id"),
        "block_id": block.get("block_id"),
    }


def _applies_to_text(rule: dict[str, Any]) -> str:
    """P9 applies_to is a LIST OF DICTS; the human-meaningful target lives in
    ``subject``. Fall back through subject -> applies_to conditions -> ''."""
    subject = str(rule.get("subject") or "").strip()
    if subject:
        return subject
    entries = rule.get("applies_to") or []
    if isinstance(entries, list):
        parts = [str(e.get("condition") or e.get("rule_object") or "") for e in entries if isinstance(e, dict)]
        return "; ".join(p for p in parts if p)
    return str(entries or "")


def _constraint_type(rule: dict[str, Any]) -> str:
    """'dimensional' carries no direction — derive it from the operator."""
    declared = str(rule.get("constraint_type") or "").lower()
    if declared not in ("", "dimensional"):
        return declared
    operator = str(rule.get("operator") or "")
    if operator in (">=", ">", "min", "minimum", "at_least", "≥"):
        return "minimum"
    if operator in ("<=", "<", "max", "maximum", "not_exceed", "≤"):
        return "maximum"
    return declared or ""


def _candidate(
    city: str,
    rule: dict[str, Any],
    evidence: dict[str, Any],
    block: dict[str, Any] | None,
    index: int,
) -> dict[str, Any]:
    family_raw = str(rule.get("rule_object") or "").strip().lower().replace(" ", "_")
    family = P9_FAMILY_ALIASES.get(family_raw, family_raw)

    # Upstream conservatism is honored; upstream confidence is NOT. Any of
    # these forces the verifier's upstream-review hold; review_required=False
    # grants nothing.
    review_reasons = list(rule.get("review_reasons") or [])
    stitched = len(STITCH_LABEL_RE.findall(str(evidence.get("evidence_text") or ""))) >= 2
    if stitched:
        # Single-source discipline, upstream edition: evidence stitched across
        # blocks cannot auto-verify — a human (or a future per-block re-join)
        # must confirm the value and its qualifiers share one source.
        review_reasons.append("p9_stitched_multiblock_evidence")
    needs_review = bool(
        rule.get("review_required")
        or rule.get("warnings")
        or review_reasons
        or evidence.get("p9_block_unjoined")
    )

    return {
        "candidate_id": str(rule.get("merged_rule_id") or rule.get("rule_id") or f"{city}_p9_cand_{index:04d}"),
        "evidence_id": evidence["evidence_id"],
        "rule_object": family,
        "constraint_type": _constraint_type(rule),
        "constraint_scope": str(rule.get("rule_key") or ""),
        "applies_to": _applies_to_text(rule),
        "operator": str(rule.get("operator") or ""),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "condition": rule.get("condition") or "",
        "exception": rule.get("exception") or "",
        "source_stream": str(rule.get("source_stream") or "pipeline9_rag"),
        "extraction_method": "pipeline9_rag",
        "extraction_final_action": "REVIEW" if needs_review else "",
        "extraction_review_reasons": review_reasons,
        "p9_provenance": _provenance(rule, block),
    }


# --- Re-anchoring: evidence repair only (see module docstring contract) -----

_page_text_cache: dict[tuple[str, int], str] = {}


def _true_page_text(source_pdf: Path, page_number: int) -> str:
    key = (str(source_pdf), int(page_number))
    if key not in _page_text_cache:
        import pdfplumber

        with pdfplumber.open(str(source_pdf)) as pdf:
            if 1 <= page_number <= len(pdf.pages):
                _page_text_cache[key] = pdf.pages[page_number - 1].extract_text() or ""
            else:
                _page_text_cache[key] = ""
    return _page_text_cache[key]


def reanchor_to_source(
    evidence_units: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    source_pdf: Path,
) -> dict[str, Any]:
    """Repair RAG-damaged context with the TRUE page text. Repair only:
    a successful re-anchor swaps in authentic source_context; a failed one
    flags ``rag_context_mismatch`` and forces the candidate to REVIEW. The
    verifier still proves every field itself either way."""
    # Candidate values keyed by evidence id: a re-anchor must corroborate the
    # value on the page, not merely a header prefix.
    values_by_evidence: dict[str, list[Any]] = {}
    for candidate in candidates:
        values_by_evidence.setdefault(str(candidate.get("evidence_id")), []).append(candidate.get("value"))

    reanchored = 0
    mismatched = 0
    mismatched_ids: set[str] = set()
    for unit in evidence_units:
        page = (unit.get("p9_provenance") or {}).get("original_page_number") or unit.get("page")
        if not page:
            continue
        page_text = re.sub(r"\s+", " ", _true_page_text(source_pdf, int(page)))
        if not page_text:
            continue
        window = local_source_context(unit.get("evidence_text") or "", page_text, radius=400)
        joined_values = values_by_evidence.get(str(unit.get("evidence_id")), [])
        # A window can anchor on a generic header prefix while the value-bearing
        # clause is hallucinated. Require at least one joined candidate value to
        # actually appear on the claimed page; a value-less candidate (no number)
        # is corroborated by the window alone.
        value_corroborated = (not joined_values) or any(
            value_present_on_page(value, page_text) for value in joined_values
        )
        if window and value_corroborated:
            unit["source_context"] = window
            unit["reanchored_to_source"] = True
            reanchored += 1
        else:
            # The block's text/value is NOT on the page it claims to come from:
            # damaged, misattributed, or hallucinated RAG context. Never trust it.
            unit["rag_context_mismatch"] = True
            mismatched += 1
            mismatched_ids.add(str(unit.get("evidence_id")))
    for candidate in candidates:
        if str(candidate.get("evidence_id")) in mismatched_ids:
            candidate["extraction_final_action"] = "REVIEW"
            reasons = list(candidate.get("extraction_review_reasons") or [])
            reasons.append("rag_context_mismatch")
            candidate["extraction_review_reasons"] = reasons
    return {
        "attempted": True,
        "source_pdf": source_pdf.name,
        "reanchored": reanchored,
        "mismatched": mismatched,
    }
