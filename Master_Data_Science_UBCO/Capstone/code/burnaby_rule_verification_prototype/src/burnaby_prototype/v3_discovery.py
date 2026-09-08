"""V3 evidence discovery and repair-pack construction.

Role: foundational source/discovery layer wrapped by the product M7 pipeline.
It is proposer-tier only and is consumed by M7; it is not a standalone lane.

V3 wraps the V2 full-bylaw source layer. It is still proposer-tier: it can
retrieve and package source text for extraction, but it cannot verify rules and
it never reads evaluation answer files.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .bylaw_rag import tokenize
from .v2_discovery import build_evidence_packs, score_chunk
from .v2_store import hash_json


V3_DISCOVERY_VERSION = "v3_discovery_1"
M4_DISCOVERY_VERSION = "m4_exhaustive_discovery_1"

REPAIR_GAPS = {
    "operator_not_supported",
    "constraint_scope_not_supported",
    "applies_to_not_supported",
    "text_condition_not_supported",
    "value_not_found_in_evidence",
    "enumerated_branch_condition_missing",
    "text_candidate_requires_review",
}

FAMILY_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "height": ("height", "building height", "maximum height"),
    "storeys": ("storeys", "stories", "number of storeys"),
    "setback": ("setback", "yard", "property line", "lot line", "minimum setback"),
    "building_separation": ("separation", "building separation", "distance between buildings"),
    "floor_area": ("floor area", "gross floor area", "maximum floor area"),
    "lot_coverage": ("lot coverage", "site coverage", "coverage"),
    "lot_area": ("lot area", "parcel area", "minimum parcel area"),
    "dwelling_units": ("dwelling units", "units", "maximum units"),
    "impervious_surface": ("impervious surface", "impermeable", "hard surface"),
    "parking_access": ("parking", "access", "driveway", "garage"),
}


def default_v3_max_packs(city: str, numeric_chunk_count: int | None = None) -> int:
    """V3 discovery pack budget, scaled to the corpus's rule-signal volume.

    Derived from the corpus size (rule-like numeric clause count) rather than a
    per-city-slug lookup, which silently under-budgets an unseen large bylaw.
    ``numeric_chunk_count`` comes from the source-corpus manifest
    (``rule_like_numeric_clause_count``); when unknown, a generous district-scale
    default is used. ``city`` is retained for signature compatibility/logging.
    """
    if numeric_chunk_count:
        return max(200, min(900, 4 * int(numeric_chunk_count)))
    return 250


def default_m4_max_packs(city: str, numeric_chunk_count: int | None = None) -> int:
    """M4 discovery pack budget, scaled to the corpus's rule-signal volume.

    Size-proportional (not per-city-slug) so any municipality gets a budget
    matched to its actual bylaw size. ``numeric_chunk_count`` is the source-corpus
    ``rule_like_numeric_clause_count``; unknown -> a generous default.
    """
    if numeric_chunk_count:
        return max(300, min(1600, 6 * int(numeric_chunk_count)))
    return 400


def v3_discovery_options_hash(*, max_packs: int, max_pack_chars: int, mode: str = "v3") -> str:
    return hash_json(
        {
            "version": M4_DISCOVERY_VERSION if mode == "m4" else V3_DISCOVERY_VERSION,
            "mode": mode,
            "max_packs": max_packs,
            "max_pack_chars": max_pack_chars,
            "families": sorted(FAMILY_QUERY_TERMS),
        }
    )


def build_v3_evidence_packs(
    chunks: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    max_packs: int,
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    """Return V3-expanded evidence packs from V2 chunks.

    The pack order is intentional: target-section hits are the most precise
    scope signal, then family-query provenance, V2 seeds, and nearby context.
    Dedupe keeps the first reason a source chunk was selected.
    """
    seed_budget = min(max_packs, max(40, int(max_packs * 0.55)))
    seed = [
        _retag_seed_pack(pack)
        for pack in build_evidence_packs(
            chunks,
            config=config,
            max_packs=seed_budget,
            max_pack_chars=max_pack_chars,
        )
    ]
    selected_chunk_ids = {str(pack.get("chunk_id") or "") for pack in seed}
    family = _family_query_packs(chunks, config=config, max_pack_chars=max_pack_chars)
    target = _target_section_packs(chunks, config=config, max_pack_chars=max_pack_chars)
    neighbor = _neighbor_packs(
        chunks,
        selected_chunk_ids=selected_chunk_ids | {str(pack.get("chunk_id") or "") for pack in family + target},
        max_pack_chars=max_pack_chars,
    )
    return _dedupe_and_reid([*target, *family, *seed, *neighbor], max_packs=max_packs, prefix="v3_pack")


def build_m4_evidence_packs(
    chunks: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    max_packs: int,
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    """Return M4 exhaustive evidence packs for extraction.

    M4 keeps V3's precise target/family/seed lanes, then adds a full rule-signal
    sweep over numeric chunks with rule wording. This gives large bylaws such as
    Calgary an auditable exhaustive path instead of relying on the top-N budget.
    """
    seed_budget = min(max_packs, max(40, int(max_packs * 0.45)))
    seed = [
        _retag_seed_pack(pack)
        for pack in build_evidence_packs(
            chunks,
            config=config,
            max_packs=seed_budget,
            max_pack_chars=max_pack_chars,
        )
    ]
    selected_chunk_ids = {str(pack.get("chunk_id") or "") for pack in seed}
    family = _family_query_packs(chunks, config=config, max_pack_chars=max_pack_chars)
    target = _target_section_packs(chunks, config=config, max_pack_chars=max_pack_chars)
    rule_sweep = _rule_signal_sweep_packs(chunks, config=config, max_pack_chars=max_pack_chars)
    neighbor = _neighbor_packs(
        chunks,
        selected_chunk_ids=selected_chunk_ids | {str(pack.get("chunk_id") or "") for pack in family + target},
        max_pack_chars=max_pack_chars,
    )
    packs = _dedupe_and_reid(
        [*target, *family, *seed, *rule_sweep, *neighbor],
        max_packs=max_packs,
        prefix="m4_pack",
    )
    for pack in packs:
        pack["selection_tier"] = "m4_exhaustive"
        pack.setdefault("v3_discovery", {})["mode"] = "m4"
        pack["m4_discovery"] = {"version": M4_DISCOVERY_VERSION, "advisory_only": True}
    return packs


def build_v3_repair_packs(
    chunks: list[dict[str, Any]],
    *,
    run_output: dict[str, list[dict[str, Any]]],
    max_packs: int,
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    """Build repair packs from current run support gaps only."""
    issues = _repair_issue_rows(run_output)
    candidates: list[dict[str, Any]] = []
    for issue in issues:
        for chunk, score in _rank_chunks_for_issue(chunks, issue)[:3]:
            candidates.append(
                _pack_from_chunk(
                    chunk,
                    lane="review_gap_repair",
                    max_chars=max_pack_chars,
                    retrieval_score=score,
                    retrieval_queries=[issue["query"]],
                    provenance={
                        "repair_rule_id": issue.get("rule_id"),
                        "repair_gaps": issue.get("support_gaps") or [],
                        "repair_rule_object": issue.get("rule_object"),
                    },
                    selected_because=["support_gap_repair", *issue.get("support_gaps", [])[:3]],
                    rule_family=str(issue.get("rule_object") or ""),
                )
            )
    return _dedupe_and_reid(candidates, max_packs=max_packs, prefix="v3_repair_pack")


def v3_source_summary(chunks: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    lanes = Counter(str(pack.get("lane") or "") for pack in packs)
    pages = sorted({int(chunk.get("page") or 0) for chunk in chunks if chunk.get("page")})
    packed_pages = sorted({int(pack.get("page") or 0) for pack in packs if pack.get("page")})
    return {
        "source_layer": "v3_full_bylaw_discovery",
        "discovery_version": V3_DISCOVERY_VERSION,
        "source_chunk_count": len(chunks),
        "evidence_pack_count": len(packs),
        "page_count": len(pages),
        "first_page": pages[0] if pages else None,
        "last_page": pages[-1] if pages else None,
        "packed_page_count": len(packed_pages),
        "lane_counts": [{"name": name, "count": count} for name, count in sorted(lanes.items())],
        "advisory_only": True,
    }


def v3_discovery_audit(chunks: list[dict[str, Any]], packs: list[dict[str, Any]]) -> dict[str, Any]:
    packed_ids = {str(pack.get("chunk_id") or "") for pack in packs}
    lane_counts = Counter(str(pack.get("lane") or "") for pack in packs)
    family_counts = Counter(str(pack.get("rule_family") or "") for pack in packs if pack.get("rule_family"))
    near_misses = []
    for chunk in chunks:
        if str(chunk.get("chunk_id") or "") in packed_ids:
            continue
        metadata = chunk.get("metadata") or {}
        if metadata.get("measurement_count") and metadata.get("rule_cue_count"):
            near_misses.append(
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "page": chunk.get("page"),
                    "section": chunk.get("section"),
                    "text_preview": str(chunk.get("text") or "")[:220],
                    "measurement_count": metadata.get("measurement_count"),
                    "rule_cue_count": metadata.get("rule_cue_count"),
                }
            )
    return {
        "discovery_version": V3_DISCOVERY_VERSION,
        "advisory_only": True,
        "pack_count": len(packs),
        "chunk_count": len(chunks),
        "lane_counts": [{"name": name, "count": count} for name, count in sorted(lane_counts.items())],
        "family_query_counts": [{"name": name, "count": count} for name, count in sorted(family_counts.items())],
        "near_miss_count": len(near_misses),
        "near_misses_dropped_with_rule_signal": near_misses[:50],
    }


def build_family_queries(config: dict[str, Any]) -> list[dict[str, Any]]:
    target = str(config.get("target_concept") or "").strip()
    zone = str(config.get("zone") or "").strip()
    aliases = [target, *[str(alias) for alias in config.get("known_aliases", []) or []]]
    aliases = [alias for alias in _unique(aliases) if alias]
    if not aliases:
        # Neutral fallback: an aliasless config must NOT borrow another city's
        # vocabulary (laneway/backyard-suite), which would pollute a new
        # municipality's retrieval. Use the zone + generic family phrases only.
        aliases = [""]
    rows = []
    for family, phrases in FAMILY_QUERY_TERMS.items():
        for alias in aliases[:6]:
            query = " ".join(part for part in (zone, alias, " ".join(phrases[:3])) if part)
            rows.append({"family": family, "query": query, "tokens": tokenize(query)})
    return rows


def _family_query_packs(
    chunks: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    for query in build_family_queries(config):
        ranked = _rank_chunks_by_tokens(chunks, set(query["tokens"]))
        for chunk, score in ranked[:8]:
            packs.append(
                _pack_from_chunk(
                    chunk,
                    lane="family_query",
                    max_chars=max_pack_chars,
                    retrieval_score=score,
                    retrieval_queries=[query["query"]],
                    provenance={"query_family": query["family"]},
                    selected_because=["family_query", f"rule_family:{query['family']}"],
                    rule_family=query["family"],
                )
            )
    return packs


def _target_section_packs(
    chunks: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    targets = _target_sections(config)
    if not targets:
        return []
    packs = []
    for chunk in chunks:
        section = str(chunk.get("section") or "")
        if any(section == target or section.startswith(f"{target}.") or section.startswith(f"{target}(") for target in targets):
            score, _ = score_chunk(chunk, config)
            packs.append(
                _pack_from_chunk(
                    chunk,
                    lane="target_section_expansion",
                    max_chars=max_pack_chars,
                    retrieval_score=score + 2.0,
                    retrieval_queries=[f"target section {section}"],
                    provenance={"target_sections": targets},
                    selected_because=["target_section_expansion"],
                )
            )
    packs.sort(key=lambda pack: (-(pack.get("retrieval_score") or 0.0), int(pack.get("page") or 0), str(pack.get("chunk_id") or "")))
    return packs[:60]


def _neighbor_packs(
    chunks: list[dict[str, Any]],
    *,
    selected_chunk_ids: set[str],
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    by_id = {str(chunk.get("chunk_id") or ""): index for index, chunk in enumerate(chunks)}
    packs = []
    for chunk_id in sorted(selected_chunk_ids):
        index = by_id.get(chunk_id)
        if index is None:
            continue
        source = chunks[index]
        source_page = source.get("page")
        for neighbor_index in (index - 1, index + 1):
            if neighbor_index < 0 or neighbor_index >= len(chunks):
                continue
            neighbor = chunks[neighbor_index]
            if source_page and neighbor.get("page") != source_page:
                continue
            packs.append(
                _pack_from_chunk(
                    neighbor,
                    lane="section_neighbor",
                    max_chars=max_pack_chars,
                    retrieval_score=1.0,
                    retrieval_queries=[f"neighbor of {chunk_id}"],
                    provenance={"neighbor_of": chunk_id},
                    selected_because=["section_neighbor"],
                )
            )
    return packs


def _rule_signal_sweep_packs(
    chunks: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        if not metadata.get("measurement_count") or not metadata.get("rule_cue_count"):
            continue
        score, signals = score_chunk(chunk, config)
        rule_family = _rule_family_for_chunk(chunk)
        packs.append(
            _pack_from_chunk(
                chunk,
                lane="m4_rule_signal_sweep",
                max_chars=max_pack_chars,
                retrieval_score=max(1.0, score),
                retrieval_queries=[
                    "numeric rule-like clause sweep",
                    *([f"rule family {rule_family}"] if rule_family else []),
                ],
                provenance={
                    "measurement_count": metadata.get("measurement_count"),
                    "rule_cue_count": metadata.get("rule_cue_count"),
                    "rule_types": metadata.get("rule_types") or [],
                    "original_lane": signals.get("lane"),
                },
                selected_because=[
                    "m4_rule_signal_sweep",
                    "measurement_signal",
                    "rule_cue_signal",
                ],
                rule_family=rule_family,
            )
        )
    packs.sort(key=lambda pack: (-(pack.get("retrieval_score") or 0.0), int(pack.get("page") or 0), str(pack.get("chunk_id") or "")))
    return packs


def _repair_issue_rows(run_output: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for bucket in ("review", "rejected", "not_used"):
        for rule in run_output.get(bucket, []) or []:
            gaps = [str(gap) for gap in rule.get("support_gaps", []) or []]
            if not (set(gaps) & REPAIR_GAPS):
                continue
            candidate = rule.get("candidate") or rule
            parts = [
                str(candidate.get("rule_object") or rule.get("rule_object") or ""),
                str(candidate.get("value") or rule.get("value") or ""),
                str(candidate.get("unit") or rule.get("unit") or ""),
                str(candidate.get("applies_to") or rule.get("applies_to") or ""),
                str(candidate.get("condition") or rule.get("condition") or ""),
                " ".join(gaps),
            ]
            rows.append(
                {
                    "rule_id": rule.get("rule_id") or candidate.get("candidate_id"),
                    "rule_object": candidate.get("rule_object") or rule.get("rule_object"),
                    "page": (rule.get("source") or {}).get("page"),
                    "section": (rule.get("source") or {}).get("section") or rule.get("section"),
                    "support_gaps": gaps,
                    "query": " ".join(part for part in parts if part).strip(),
                }
            )
    return rows


def _rank_chunks_for_issue(chunks: list[dict[str, Any]], issue: dict[str, Any]) -> list[tuple[dict[str, Any], float]]:
    query_tokens = set(tokenize(issue.get("query") or ""))
    issue_page = _to_int(issue.get("page"))
    issue_section = str(issue.get("section") or "")
    ranked = []
    for chunk in chunks:
        text_tokens = set(tokenize(_chunk_text(chunk)))
        overlap = len(query_tokens & text_tokens)
        if overlap == 0 and not _near_page(issue_page, chunk.get("page")):
            continue
        score = float(overlap)
        metadata = chunk.get("metadata") or {}
        score += min(2.0, float(metadata.get("measurement_count") or 0))
        score += min(2.0, float(metadata.get("rule_cue_count") or 0) * 0.5)
        if issue_section and str(chunk.get("section") or "").startswith(issue_section.split("(", 1)[0]):
            score += 2.0
        if _near_page(issue_page, chunk.get("page")):
            score += 1.5
        if score > 0:
            ranked.append((chunk, score))
    ranked.sort(key=lambda item: (-item[1], int(item[0].get("page") or 0), str(item[0].get("chunk_id") or "")))
    return ranked


def _rank_chunks_by_tokens(chunks: list[dict[str, Any]], query_tokens: set[str]) -> list[tuple[dict[str, Any], float]]:
    ranked = []
    for chunk in chunks:
        text = _chunk_text(chunk)
        text_tokens = set(tokenize(text))
        overlap = query_tokens & text_tokens
        if not overlap:
            continue
        metadata = chunk.get("metadata") or {}
        score = float(len(overlap))
        score += 2.0 if metadata.get("measurement_count") else 0.0
        score += 1.0 if metadata.get("rule_cue_count") else 0.0
        if str(chunk.get("evidence_type") or "") in {"table_cell", "table_row"}:
            score += 1.0
        ranked.append((chunk, score))
    ranked.sort(key=lambda item: (-item[1], int(item[0].get("page") or 0), str(item[0].get("chunk_id") or "")))
    return ranked


def _retag_seed_pack(pack: dict[str, Any]) -> dict[str, Any]:
    out = dict(pack)
    original_lane = str(out.get("lane") or "")
    out["lane"] = "seed_discovery"
    out["v3_original_lane"] = original_lane
    out["selected_because"] = ["v2_seed", *[str(value) for value in out.get("selected_because", [])]]
    out["v3_discovery"] = {"version": V3_DISCOVERY_VERSION, "advisory_only": True}
    return out


def _pack_from_chunk(
    chunk: dict[str, Any],
    *,
    lane: str,
    max_chars: int,
    retrieval_score: float,
    retrieval_queries: list[str],
    provenance: dict[str, Any] | None = None,
    selected_because: list[str] | None = None,
    rule_family: str = "",
) -> dict[str, Any]:
    return {
        "pack_id": "",
        "chunk_id": chunk.get("chunk_id"),
        "section": chunk.get("section") or "",
        "page": chunk.get("page"),
        "lane": lane,
        "source_text": _pack_text(chunk, max_chars),
        "retrieval_queries": retrieval_queries,
        "retrieval_score": round(float(retrieval_score), 3),
        "retrieval_signals": {"lane": lane, **(provenance or {})},
        "evidence_type": chunk.get("evidence_type") or "clause",
        "heading": chunk.get("heading") or "",
        "parent_text": chunk.get("parent_text") or "",
        "table_title": chunk.get("table_title") or "",
        "row_header": chunk.get("row_header") or "",
        "column_header": chunk.get("column_header") or "",
        "cell_value": chunk.get("cell_value") or "",
        "table_cells": (chunk.get("metadata") or {}).get("cells") or [],
        "selected_because": selected_because or [lane],
        "rule_family": rule_family,
        "rule_types": (chunk.get("metadata") or {}).get("rule_types") or [],
        "selection_tier": "v3_expanded",
        "drop_risk": "medium",
        "discovery_confidence": min(1.0, round(float(retrieval_score) / 10.0, 3)),
        "v3_discovery": {"version": V3_DISCOVERY_VERSION, "advisory_only": True, **(provenance or {})},
    }


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


def _chunk_text(chunk: dict[str, Any]) -> str:
    return " ".join(
        str(chunk.get(field) or "")
        for field in ("heading", "parent_text", "table_title", "row_header", "column_header", "cell_value", "text")
    )


def _rule_family_for_chunk(chunk: dict[str, Any]) -> str:
    text_tokens = set(tokenize(_chunk_text(chunk)))
    best_family = ""
    best_overlap = 0
    for family, phrases in FAMILY_QUERY_TERMS.items():
        family_tokens = set(tokenize(" ".join((family, *phrases))))
        overlap = len(text_tokens & family_tokens)
        if overlap > best_overlap:
            best_family = family
            best_overlap = overlap
    return best_family


def _dedupe_and_reid(packs: list[dict[str, Any]], *, max_packs: int, prefix: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for pack in packs:
        key = str(pack.get("chunk_id") or "").strip()
        if not key:
            key = re.sub(r"\s+", " ", str(pack.get("source_text") or "").lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        item = dict(pack)
        item["pack_id"] = f"{prefix}_{len(out) + 1:04d}"
        out.append(item)
        if len(out) >= max_packs:
            break
    return out


def _target_sections(config: dict[str, Any]) -> list[str]:
    verification = config.get("verification") or {}
    configured = [str(section).strip() for section in verification.get("target_section_ids", []) if str(section).strip()]
    scope_text = " ".join(str(config.get(field) or "") for field in ("bylaw", "source_document"))
    targets = [*configured]
    for raw in re.findall(r"\b\d{2,4}(?:\.\d{1,3})?\b", scope_text):
        first = int(raw.split(".", 1)[0])
        if 1900 <= first <= 2099:
            continue
        targets.append(raw)
    return _unique(targets[:12])


def _near_page(left: Any, right: Any) -> bool:
    a = _to_int(left)
    b = _to_int(right)
    return a is not None and b is not None and abs(a - b) <= 2


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out
