"""Native RAG + LLM candidate extraction for the verifier contract.

This is proposer-tier code. It retrieves source-backed bylaw text and asks an
LLM to produce candidate rules, but it cannot verify anything. The output is
the same ``rule_candidates`` + ``evidence_units`` shape consumed by
``slim_pipeline.py``; source repair and ``verification.py`` remain the trust
gate.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .bylaw_rag import BylawIndex, load_corpus_from_sections
from .extraction.pdf_ingest import (
    ingest_pdf,
    page_ranges_from_provenance,
    restrict_intermediate_to_pages,
)
from .extraction.text_stream import extract_clauses


# Adopted after a Calgary R-CG A/B (2026-06-16): gemini-3.1-flash-lite verified
# 16 R-CG rules at precision 1.00 / recall 0.84 vs gpt-oss-120b's 8 at 0.68,
# with adversarial ALL BLOCKED and zero source-support failures for both. The
# deterministic verifier is model-agnostic, so the swap raises recall without
# touching the safety contract.
DEFAULT_CHAT_MODEL = "google/gemini-3.1-flash-lite"
DEFAULT_EMBEDDING_MODEL = "baai/bge-m3"
DEFAULT_RERANK_MODEL = "cohere/rerank-4-fast"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_RULE_OBJECT_ALIASES = {
    "separation_distance": "building_separation",
    "building separation": "building_separation",
    "building_separation": "building_separation",
    "setback_distance": "setback",
    "setback": "setback",
    "site coverage": "lot_coverage",
    "site_coverage": "lot_coverage",
    "lot coverage": "lot_coverage",
    "lot_coverage": "lot_coverage",
    "floor area": "floor_area",
    "floor_area": "floor_area",
    "floor space ratio": "floor_space_ratio",
    "floor_space_ratio": "floor_space_ratio",
    "height": "height",
    "building_height": "height",
    "storeys": "storeys",
    "stories": "storeys",
    "lot area": "lot_area",
    "lot_area": "lot_area",
    "dwelling units": "dwelling_units",
    "dwelling_units": "dwelling_units",
    "impervious surface": "impervious_surface",
    "impervious_surface": "impervious_surface",
}

_UNIT_ALIASES = {
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    "m": "m",
    "m2": "m2",
    "m²": "m2",
    "sq m": "m2",
    "sq. m": "m2",
    "square metre": "m2",
    "square metres": "m2",
    "square meter": "m2",
    "square meters": "m2",
    "%": "%",
    "percent": "%",
    "per cent": "%",
    "storey": "storeys",
    "storeys": "storeys",
    "story": "storeys",
    "stories": "storeys",
    "unit": "units",
    "units": "units",
    "dwelling unit": "units",
    "dwelling units": "units",
}

_QUERY_TEMPLATES = (
    "{target}",
    "{alias} setback minimum rear side yard property line",
    "{alias} building separation minimum principal building",
    "{alias} height maximum storeys",
    "{alias} floor area maximum gross floor area",
    "{alias} site coverage lot coverage maximum",
    "{alias} lot area parcel area minimum",
    "{alias} dwelling units maximum permitted",
)


class OpenRouterError(RuntimeError):
    """OpenRouter call failed with a useful, secret-free message."""


class OpenRouterChatClient:
    """Small OpenRouter chat-completions client with JSON response support."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_CHAT_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: int = 90,
        max_tokens: int = 1200,
    ) -> None:
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is required for LLM extraction")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens

    def extract_rules(self, prompt: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract zoning rule candidates from quoted bylaw text. "
                        "Return only valid JSON. Do not decide whether a rule is correct."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        payload = self._post_json("/chat/completions", body)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter response did not include message content") from exc
        return _loads_json_object(content)

    def _post_json(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/ubco-mds-2025-labs",
                "X-Title": "Burnaby Prototype Verification",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            raise OpenRouterError(f"OpenRouter request timed out after {self.timeout}s") from exc
        except urllib.error.URLError as exc:
            raise OpenRouterError(f"OpenRouter request failed: {exc.reason}") from exc
        except OSError as exc:
            raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc


class OpenRouterEmbeddingBackend:
    """Embedding backend matching ``BylawIndex``'s ``encode(list[str])`` contract."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
        batch_size: int = 96,
        timeout: int = 90,
    ) -> None:
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is required for OpenRouter embeddings")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self.timeout = timeout

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            payload = self._post_json("/embeddings", {"model": self.model, "input": batch})
            rows = payload.get("data") or []
            rows = sorted(rows, key=lambda row: int(row.get("index", 0)))
            vectors.extend([[float(v) for v in row.get("embedding", [])] for row in rows])
        if len(vectors) != len(texts):
            raise OpenRouterError("embedding response count did not match input count")
        return vectors

    def _post_json(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise OpenRouterError(f"OpenRouter embedding HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            raise OpenRouterError(f"OpenRouter embedding request timed out after {self.timeout}s") from exc
        except urllib.error.URLError as exc:
            raise OpenRouterError(f"OpenRouter embedding request failed: {exc.reason}") from exc
        except OSError as exc:
            raise OpenRouterError(f"OpenRouter embedding request failed: {exc}") from exc


class OpenRouterReranker:
    """Optional reranker for retrieved source packs."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_RERANK_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: int = 90,
    ) -> None:
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is required for OpenRouter rerank")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def rerank(self, query: str, packs: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
        if not packs:
            return []
        body = {
            "model": self.model,
            "query": query,
            "documents": [{"text": _pack_rerank_text(pack)} for pack in packs],
            "top_n": min(top_n, len(packs)),
        }
        request = urllib.request.Request(
            f"{self.base_url}/rerank",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise OpenRouterError(f"OpenRouter rerank HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            raise OpenRouterError(f"OpenRouter rerank request timed out after {self.timeout}s") from exc
        except urllib.error.URLError as exc:
            raise OpenRouterError(f"OpenRouter rerank request failed: {exc.reason}") from exc
        except OSError as exc:
            raise OpenRouterError(f"OpenRouter rerank request failed: {exc}") from exc
        ranked = []
        for result in payload.get("results", []):
            index = int(result.get("index", -1))
            if 0 <= index < len(packs):
                pack = dict(packs[index])
                pack["rerank_score"] = result.get("relevance_score")
                ranked.append(pack)
        return ranked


def load_openrouter_api_key(env_path: Path | None = None) -> str:
    """Load an API key from the environment or a git-ignored .env file.

    The key is intentionally not stored in Python source or generated outputs.
    """
    existing = os.getenv("OPENROUTER_API_KEY")
    if existing:
        return existing.strip()
    env_path = env_path or Path.cwd() / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def run_native_extraction(
    *,
    city: str,
    config: dict[str, Any],
    pdf_path: Path,
    output_dir: Path,
    api_key: str,
    chat_model: str = DEFAULT_CHAT_MODEL,
    embedding_model: str | None = DEFAULT_EMBEDDING_MODEL,
    rerank_model: str | None = DEFAULT_RERANK_MODEL,
    top_k_per_query: int = 8,
    max_packs: int = 40,
    max_pack_chars: int = 3600,
    llm_max_tokens: int = 1200,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Retrieve source packs, optionally run LLM extraction, and write artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate = ingest_pdf(pdf_path, prefer_docling=False)
    # Scope extraction to the deliverable district's pages when provenance pins a
    # range, so RAG retrieval doesn't pull cross-district noise from a large
    # multi-district bylaw. Mirrors the source-corpus page scope; original page
    # numbers are preserved so citations stay valid.
    provenance_path = pdf_path.parent / "provenance.json"
    provenance = (
        json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance_path.exists()
        else {}
    )
    intermediate = restrict_intermediate_to_pages(
        intermediate, page_ranges_from_provenance(provenance)
    )
    chunks = build_source_chunks(intermediate, city)
    retrieval_queries = build_retrieval_queries(config)

    embedding_backend = None
    embedding_error = None
    if embedding_model and api_key:
        try:
            embedding_backend = OpenRouterEmbeddingBackend(api_key, model=embedding_model)
        except OpenRouterError as exc:
            embedding_error = str(exc)
    index = BylawIndex(load_corpus_from_sections(chunks), embedding_backend=embedding_backend)
    packs = retrieve_packs(
        index,
        retrieval_queries,
        top_k_per_query=top_k_per_query,
        max_packs=max_packs,
        max_pack_chars=max_pack_chars,
    )

    rerank_error = None
    if rerank_model and api_key and packs:
        try:
            reranker = OpenRouterReranker(api_key, model=rerank_model)
            packs = reranker.rerank(" ".join(retrieval_queries[:6]), packs, top_n=max_packs)
        except OpenRouterError as exc:
            rerank_error = str(exc)

    model_outputs: list[dict[str, Any]] = []
    extraction_errors: list[dict[str, Any]] = []
    evidence_units: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    llm_error = None
    if not dry_run:
        client = OpenRouterChatClient(api_key, model=chat_model, max_tokens=llm_max_tokens)
        for pack in packs:
            prompt = extraction_prompt(config, pack)
            try:
                payload = client.extract_rules(prompt)
            except OpenRouterError as exc:
                extraction_errors.append(
                    {
                        "pack_id": pack.get("pack_id"),
                        "chunk_id": pack.get("chunk_id"),
                        "section": pack.get("section"),
                        "page": pack.get("page"),
                        "error": str(exc),
                    }
                )
                model_outputs.append(
                    {
                        "pack_id": pack["pack_id"],
                        "error": str(exc),
                        "model_output": {"rules": []},
                    }
                )
                continue
            model_outputs.append({"pack_id": pack["pack_id"], "model_output": payload})
            new_units, new_candidates = candidate_set_from_model_rules(city, pack, payload, config=config)
            evidence_units.extend(new_units)
            candidates.extend(new_candidates)
    else:
        llm_error = "dry_run: retrieval packs written; no LLM extraction attempted"

    evidence_units = _dedupe_by_key(evidence_units, "evidence_id")
    candidates = _dedupe_by_key(candidates, "candidate_id")
    summary = {
        "pipeline": "native_rag_llm_extraction_v1",
        "city": city,
        "source_pdf": pdf_path.name,
        "chat_model": None if dry_run else chat_model,
        "embedding_model": embedding_model,
        "rerank_model": rerank_model,
        "dry_run": dry_run,
        "source_chunk_count": len(chunks),
        "retrieval_query_count": len(retrieval_queries),
        "retrieval_pack_count": len(packs),
        "evidence_unit_count": len(evidence_units),
        "candidate_rule_count": len(candidates),
        "extraction_error_count": len(extraction_errors),
        "extraction_errors": extraction_errors,
        "embedding_error": embedding_error,
        "rerank_error": rerank_error,
        "llm_error": llm_error,
        "safety_contract": (
            "Native extraction proposes candidates only. Source repair and deterministic "
            "verification decide verified/review/rejected/not_used."
        ),
    }

    _write_json(output_dir / "retrieval_packs.json", packs)
    _write_json(output_dir / "raw_model_outputs.json", model_outputs)
    _write_json(output_dir / "evidence_units.json", evidence_units)
    _write_json(output_dir / "rule_candidates.json", candidates)
    _write_json(output_dir / "extraction_summary.json", summary)
    return summary


def build_source_chunks(intermediate: dict[str, Any], city: str) -> list[dict[str, Any]]:
    """Build section/page chunks for retrieval from the PDF ingest intermediate."""
    city_key = _slug(city)
    clauses = extract_clauses(intermediate, city_key)
    chunks = [
        {
            "chunk_id": clause["evidence_id"],
            "section": clause["section"],
            "page": clause["page"],
            "text": clause["text"],
        }
        for clause in clauses
        if str(clause.get("text") or "").strip()
    ]
    if chunks:
        return chunks
    # Fallback for PDFs with weak section anchoring: one chunk per page.
    page_chunks = []
    for page in intermediate.get("pages", []):
        text = re.sub(r"\s+", " ", str(page.get("text") or "")).strip()
        if text:
            page_no = int(page.get("page_number") or 0)
            page_chunks.append(
                {
                    "chunk_id": f"{city_key}_page_{page_no:04d}",
                    "section": "",
                    "page": page_no,
                    "text": text,
                }
            )
    return page_chunks


def build_retrieval_queries(config: dict[str, Any]) -> list[str]:
    # Neutral default: do not assume a laneway/suite bylaw when target_concept is
    # absent -- fall back to a jurisdiction-neutral phrase so a new city is not
    # biased toward another municipality's rule type.
    target = str(config.get("target_concept") or "zoning district dimensional rules")
    scope_text = " ".join(
        str(config.get(field) or "")
        for field in ("city", "zone", "bylaw", "source_document", "target_concept")
    )
    aliases = [str(alias) for alias in config.get("known_aliases", []) if str(alias).strip()]
    if not aliases:
        # Neutral fallback: an aliasless config must NOT borrow another city's
        # vocabulary (laneway/backyard-suite). Fall back to the rule families this
        # verifier supports (jurisdiction-neutral) so a new municipality's
        # retrieval is still rule-oriented without importing foreign terms.
        aliases = ["setback", "building height", "lot coverage", "floor area", "dwelling units"]
    queries: list[str] = [scope_text]
    zone = str(config.get("zone") or "").strip()
    if zone:
        queries.extend([f"{zone} {target}", f"{_zone_with_hyphen(zone)} {target}"])
    section_ids = _section_ids_from_text(scope_text)
    for alias in aliases[:6]:
        for template in _QUERY_TEMPLATES:
            queries.append(template.format(target=target, alias=alias))
        for section_id in section_ids:
            queries.append(f"{section_id} {alias} {target}")
    return _unique(queries)


def retrieve_packs(
    index: BylawIndex,
    queries: list[str],
    *,
    top_k_per_query: int,
    max_packs: int,
    max_pack_chars: int,
) -> list[dict[str, Any]]:
    by_chunk: dict[str, dict[str, Any]] = {}
    for query in queries:
        for hit in index.ask(query, top_k=top_k_per_query):
            chunk_id = str(hit.get("chunk_id") or "")
            existing = by_chunk.get(chunk_id)
            if existing is None:
                by_chunk[chunk_id] = {
                    "pack_id": f"native_pack_{len(by_chunk) + 1:04d}",
                    "chunk_id": chunk_id,
                    "section": hit.get("section") or "",
                    "page": hit.get("page"),
                    "source_text": _bounded(hit.get("section_text") or hit.get("text") or "", max_pack_chars),
                    "retrieval_queries": [query],
                    "retrieval_score": hit.get("score"),
                    "retrieval_signals": hit.get("signals") or {},
                }
            else:
                existing["retrieval_queries"].append(query)
    ordered = sorted(
        by_chunk.values(),
        key=lambda pack: (
            -len(pack.get("retrieval_queries") or []),
            -(float(pack.get("retrieval_score") or 0.0)),
            str(pack.get("chunk_id") or ""),
        ),
    )
    # Drop byte-identical duplicate chunks (same whitespace-normalized text)
    # before the budget cut: distinct chunk_ids sometimes carry identical text
    # and would each consume a pack slot, displacing rule-bearing chunks and
    # lowering extraction recall. Keep the highest-ranked occurrence. Zero
    # information loss; bylaw-agnostic.
    deduped: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    for pack in ordered:
        key = " ".join(str(pack.get("source_text") or "").split()).lower()
        if key and key in seen_text:
            continue
        seen_text.add(key)
        deduped.append(pack)
    return deduped[:max_packs]


def extraction_prompt(config: dict[str, Any], pack: dict[str, Any]) -> str:
    allowed = (config.get("verification") or {}).get("gis_text_rule_contract") or []
    directions = (config.get("verification") or {}).get("rule_family_direction") or {}
    aliases = ", ".join(str(alias) for alias in (config.get("known_aliases") or [])[:8])
    return (
        "Extract only numeric zoning rule CANDIDATES from the source text below.\n"
        "Do not infer missing values. Do not use outside knowledge.\n"
        f"The extraction target is: {config.get('target_concept')} (vocabulary used by this bylaw: {aliases}).\n"
        f"Extract every rule that regulates the target or a generally applicable development standard in zone {config.get('zone')}. If the text regulates none of these, return an empty rules array.\n"
        f"If the source text explicitly belongs to a different district or parcel designation than {config.get('zone')}, return an empty rules array.\n"
        "Include a rule whenever the regulated object and its numeric value are visible in this exact source text.\n"
        "If the operator/direction wording is not visible, set operator to \"\" instead of guessing or dropping the rule; incomplete candidates go to review downstream.\n"
        "Allowed rule_object values: " + ", ".join(map(str, allowed)) + "\n"
        "Expected family directions: " + json.dumps(directions, sort_keys=True) + "\n"
        "Operators must be one of <=, >=, <, >, =, or \"\" when the direction wording is not in the text.\n"
        "Units should be one of m, m2, %, storeys, units, or blank only when the source truly has no unit.\n"
        "Keep source_quote short: the exact value-bearing sentence fragment only, at most 40 words.\n"
        "Return this JSON shape exactly and nothing else: {\"rules\":[{\"rule_object\":\"height\",\"operator\":\"<=\",\"value\":\"8.5\",\"unit\":\"m\",\"applies_to\":\"principal building\",\"condition\":\"\",\"exception\":\"\",\"source_quote\":\"building height ... must not exceed 8.5 m\"}]}.\n\n"
        f"CITY: {config.get('city')}\n"
        f"ZONE: {config.get('zone')}\n"
        f"TARGET CONCEPT: {config.get('target_concept')}\n"
        f"SECTION: {pack.get('section')}\n"
        f"PAGE: {pack.get('page')}\n"
        f"SOURCE TEXT:\n{pack.get('source_text')}\n"
    )


def candidate_set_from_model_rules(
    city: str,
    pack: dict[str, Any],
    payload: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rules = payload.get("rules") if isinstance(payload, dict) else []
    if not isinstance(rules, list):
        rules = []
    evidence_units: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for index, raw_rule in enumerate(rules, start=1):
        if not isinstance(raw_rule, dict):
            continue
        rule_object = _normalize_rule_object(raw_rule.get("rule_object"))
        operator = _normalize_operator(raw_rule.get("operator"))
        value = _normalize_value(raw_rule.get("value"))
        # Recall-oriented: a missing operator routes the candidate to review
        # (operator_not_supported), it must not silently drop the rule here.
        if not (rule_object and value):
            continue
        source_text = str(pack.get("source_text") or "")
        outside_target_zone = _outside_target_zone_context(config, source_text)
        outside_target_section = _outside_target_section_context(config, pack.get("section"))
        quote = re.sub(r"\s+", " ", str(raw_rule.get("source_quote") or "")).strip()
        quote_supported = bool(quote and _contains_normalized(source_text, quote))
        evidence_text = quote if quote_supported else source_text
        evidence_id = f"{pack['pack_id']}_ev_{index:03d}"
        candidate_id = f"{_slug(city)}_native_{pack['pack_id']}_{index:03d}"
        review_reasons = []
        if not operator:
            review_reasons.append("operator_missing_from_extraction")
        if not quote_supported:
            review_reasons.append("source_quote_not_in_retrieved_pack")
        if outside_target_zone:
            review_reasons.append("outside_target_zone_context")
        if outside_target_section:
            review_reasons.append("outside_target_section_context")
        evidence_units.append(
            {
                "evidence_id": evidence_id,
                "page": pack.get("page"),
                "section": pack.get("section") or "",
                "evidence_type": "clause",
                "evidence_text": evidence_text,
                "source_context": source_text,
                "source_stream": "native_rag_llm",
                "native_provenance": {
                    "pack_id": pack.get("pack_id"),
                    "chunk_id": pack.get("chunk_id"),
                    "retrieval_queries": pack.get("retrieval_queries") or [],
                    "retrieval_score": pack.get("retrieval_score"),
                    "rerank_score": pack.get("rerank_score"),
                },
            }
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "evidence_id": evidence_id,
                "rule_object": rule_object,
                "constraint_type": _constraint_type(operator),
                "constraint_scope": str(raw_rule.get("constraint_scope") or rule_object),
                "applies_to": str(raw_rule.get("applies_to") or ""),
                "operator": operator,
                "value": value,
                "unit": _normalize_unit(raw_rule.get("unit")),
                "condition": str(raw_rule.get("condition") or ""),
                "exception": str(raw_rule.get("exception") or ""),
                "source_stream": "native_rag_llm",
                "extraction_method": "native_rag_llm_v1",
                "extraction_final_action": "REVIEW" if review_reasons else "",
                "extraction_review_reasons": review_reasons,
                "native_provenance": {
                    "pack_id": pack.get("pack_id"),
                    "chunk_id": pack.get("chunk_id"),
                    "source_quote_supported": quote_supported,
                },
            }
        )
    return evidence_units, candidates


def _loads_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenRouterError("model did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise OpenRouterError("model JSON response was not an object")
    return payload


def _pack_rerank_text(pack: dict[str, Any]) -> str:
    return (
        f"section: {pack.get('section')}\n"
        f"page: {pack.get('page')}\n"
        f"text: {pack.get('source_text')}"
    )


def _normalize_rule_object(value: Any) -> str:
    key = re.sub(r"\s+", " ", str(value or "").strip().lower())
    key = key.replace("-", "_")
    return _RULE_OBJECT_ALIASES.get(key, key.replace(" ", "_"))


def _normalize_operator(value: Any) -> str:
    text = str(value or "").strip().lower()
    return {
        "≤": "<=",
        "maximum": "<=",
        "max": "<=",
        "not exceed": "<=",
        "at most": "<=",
        "≥": ">=",
        "minimum": ">=",
        "min": ">=",
        "at least": ">=",
    }.get(text, text if text in {"<=", ">=", "<", ">", "="} else "")


def _constraint_type(operator: str) -> str:
    if operator in {"<=", "<"}:
        return "maximum"
    if operator in {">=", ">"}:
        return "minimum"
    return "dimensional"


def _normalize_unit(value: Any) -> str:
    # Treat '.' and whitespace as the same separator so 'sq.m', 'sq. m' and
    # 'sq m' all canonicalize identically (the period-without-space form used to
    # collapse to 'sqm', which no alias matched).
    key = re.sub(r"[.\s]+", " ", str(value or "").lower()).strip()
    return _UNIT_ALIASES.get(key, key)


def _normalize_value(value: Any) -> str:
    # Strip thousands separators before extracting the number; otherwise
    # '1,234.5' silently truncates to '1' and the real value is lost.
    text = str(value if value is not None else "").strip().replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def _contains_normalized(haystack: str, needle: str) -> bool:
    return re.sub(r"\s+", " ", needle).lower() in re.sub(r"\s+", " ", haystack).lower()


def _outside_target_zone_context(config: dict[str, Any] | None, source_text: str) -> bool:
    """Return True when source text names a different explicit parcel designation.

    This is a generic fail-closed guard, not a Calgary-specific gold rule. If a
    retrieved source pack says "Parcels designated R-Gm" while the active config
    is ``RCG``, the extractor can still surface the candidate, but it must not
    be allowed to auto-verify for the wrong district.
    """
    zone = str((config or {}).get("zone") or "").strip()
    if not zone:
        return False
    target = _compact_zone(zone)
    if not target:
        return False
    for match in re.finditer(r"(?i)\bparcels?\s+designated\s+([A-Z][A-Z0-9-]*)", source_text):
        found = _compact_zone(match.group(1))
        if found and found != target:
            return True
    return False


def _outside_target_section_context(config: dict[str, Any] | None, section: Any) -> bool:
    verification = (config or {}).get("verification") or {}
    targets = [str(item).strip() for item in verification.get("target_section_ids", []) if str(item).strip()]
    scope_text = " ".join(
        str((config or {}).get(field) or "")
        for field in ("bylaw", "source_document")
    )
    targets = _unique([*targets, *_section_ids_from_text(scope_text)])
    if not targets:
        return False
    current_match = re.match(r"\s*(\d{1,4}(?:\.\d{1,3})?)", str(section or ""))
    if not current_match:
        return False
    current = current_match.group(1)
    return not any(current == target or current.startswith(f"{target}.") for target in targets)


def _compact_zone(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _zone_with_hyphen(value: str) -> str:
    text = str(value or "").strip()
    if "-" in text or len(text) < 3:
        return text
    # RCG -> R-CG, RS -> RS. Useful for Calgary-style district labels while
    # staying harmless for cities whose zones already have the printed form.
    return f"{text[0]}-{text[1:]}"


def _section_ids_from_text(text: str) -> list[str]:
    ids = []
    for raw in re.findall(r"\b\d{2,4}(?:\.\d{1,3})?\b", str(text or "")):
        first = int(raw.split(".", 1)[0])
        if 1900 <= first <= 2099:
            continue
        ids.append(raw)
    return _unique(ids[:12])


def _bounded(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def _dedupe_by_key(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for record in records:
        value = str(record.get(key) or "")
        if value and value not in seen:
            seen.add(value)
            out.append(record)
    return out


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
