"""Private advisory shadow examiner for V2 runs.

The examiner can inspect artifacts, bounded source context, and selected code
files. It never writes verifier, benchmark, or GIS authority files.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from .bylaw_rag import BylawIndex, load_corpus_from_sections
from .config import write_json
from .v2_discovery import retrieval_corpus_from_packs
from .v2_store import V2Store, cache_key


DEFAULT_EXAMINER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PROTECTED_OUTPUTS = {
    "verified_rules.json",
    "gis_rule_contract.json",
    "benchmark_report.json",
    "review_needed.json",
    "rejected_rules.json",
    "not_used.json",
}
EXAMINER_OUTPUTS = {
    "llm_examiner_report.json",
    "llm_examiner_suggestions.json",
    "llm_examiner_rerun_plan.json",
}

DEFAULT_CODE_PATHS = [
    "src/burnaby_prototype/verification.py",
    "src/burnaby_prototype/support_checks.py",
    "src/burnaby_prototype/source_repair.py",
    "src/burnaby_prototype/native_extraction.py",
    "src/burnaby_prototype/v2_discovery.py",
    "src/burnaby_prototype/v2_store.py",
    "src/burnaby_prototype/review_router.py",
    "src/burnaby_prototype/table_matrix.py",
    "benchmark/evaluate_benchmark.py",
]


def run_shadow_examiner(
    *,
    output_dir: Path,
    repo_root: Path,
    store: V2Store | None = None,
    run_id: str = "",
    model: str = DEFAULT_EXAMINER_MODEL,
    api_key: str = "",
    offline: bool = False,
    code_paths: list[str] | None = None,
    max_code_chars: int = 18000,
) -> dict[str, Any]:
    """Write advisory examiner outputs and optionally record findings in SQLite."""
    context = build_examiner_context(
        output_dir=output_dir,
        repo_root=repo_root,
        code_paths=code_paths or DEFAULT_CODE_PATHS,
        max_code_chars=max_code_chars,
    )
    if offline or not api_key:
        report = heuristic_examiner_report(context, model=None)
    else:
        report = _llm_examiner_report(context, model=model, api_key=api_key)
    report["advisory_only"] = True
    report["protected_outputs"] = sorted(PROTECTED_OUTPUTS)
    suggestions = {
        "advisory_only": True,
        "items": [
            {
                "finding_id": item.get("finding_id"),
                "category": item.get("category"),
                "suggested_test": item.get("suggested_test"),
                "suggested_fix": item.get("suggestion"),
            }
            for item in report.get("findings", [])
        ],
    }
    rerun_plan = build_rerun_plan(report)
    safe_write_examiner_outputs(output_dir, report, suggestions, rerun_plan)
    if store is not None:
        store.insert_examiner_findings(run_id=run_id or "unknown", findings=report.get("findings", []))
    return report


def build_examiner_context(
    *,
    output_dir: Path,
    repo_root: Path,
    code_paths: list[str],
    max_code_chars: int,
) -> dict[str, Any]:
    artifacts = {
        name: _read_json(output_dir / name, default)
        for name, default in {
            "extraction_summary.json": {},
            "model_cost_report.json": {},
            "source_summary.json": {},
            "evidence_packs.json": [],
            "raw_model_outputs.json": [],
            "rule_candidates.json": [],
            "evidence_units.json": [],
            "source_repair_report.json": {},
            "review_needed.json": [],
            "rejected_rules.json": [],
            "verified_rules.json": [],
            "benchmark_report.json": {},
            "proof_dag_report.json": {},
            "review_router.json": {},
        }.items()
    }
    retrieval_context = retrieve_examiner_context(
        artifacts.get("evidence_packs.json", []),
        _review_queries(artifacts),
        top_k=6,
    )
    code = []
    remaining = max_code_chars
    for rel_path in code_paths:
        path = repo_root / rel_path
        if remaining <= 0 or not path.exists():
            continue
        text = _redact_secrets(path.read_text(encoding="utf-8", errors="replace"))
        snippet = text[:remaining]
        remaining -= len(snippet)
        code.append({"path": rel_path, "text": snippet, "truncated": len(snippet) < len(text)})
    return {
        "output_dir": str(output_dir),
        "artifacts": artifacts,
        "retrieved_context": retrieval_context,
        "code": code,
        "instructions": [
            "Advisory only. Do not claim verification authority.",
            "Flag pipeline failure modes and code logic bugs with evidence.",
            "Findings without concrete source/code evidence must be marked speculative.",
        ],
    }


def retrieve_examiner_context(packs: list[dict[str, Any]], queries: list[str], *, top_k: int = 6) -> list[dict[str, Any]]:
    corpus = retrieval_corpus_from_packs(packs)
    if not corpus:
        return []
    index = BylawIndex(load_corpus_from_sections(corpus))
    seen: set[str] = set()
    results = []
    for query in queries:
        for hit in index.ask(query, top_k=top_k):
            key = str(hit.get("chunk_id") or "")
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "query": query,
                    "chunk_id": key,
                    "section": hit.get("section"),
                    "page": hit.get("page"),
                    "score": hit.get("score"),
                    "text": (hit.get("section_text") or hit.get("text") or "")[:2200],
                }
            )
    return results[:top_k * max(1, len(queries))]


def heuristic_examiner_report(context: dict[str, Any], *, model: str | None) -> dict[str, Any]:
    artifacts = context.get("artifacts", {})
    benchmark = artifacts.get("benchmark_report.json") or {}
    rule_metrics = benchmark.get("rule_metrics") or {}
    extraction_summary = artifacts.get("extraction_summary.json") or {}
    cost = artifacts.get("model_cost_report.json") or {}
    review_rules = artifacts.get("review_needed.json") or []
    rejected_rules = artifacts.get("rejected_rules.json") or []
    findings: list[dict[str, Any]] = []
    if int(rule_metrics.get("false_verified_count") or 0) > 0:
        findings.append(
            _finding(
                "critical",
                "unsafe_verification",
                "Benchmark reports false verified rules.",
                f"false_verified_count={rule_metrics.get('false_verified_count')}",
                "Disqualify this model/run and inspect each false verified proof trace.",
                "Add or update an adversarial regression for the false verified pattern.",
            )
        )
    if rule_metrics and float(rule_metrics.get("verified_or_review_recall") or 0.0) < 0.8:
        findings.append(
            _finding(
                "medium",
                "low_recall",
                "Many gold rules are missing from verified-or-review.",
                f"verified_or_review_recall={rule_metrics.get('verified_or_review_recall')}",
                "Inspect missed gold source sections and widen discovery packs before changing verifier gates.",
                "Add a source-discovery regression for one missed gold section.",
            )
        )
    if int(extraction_summary.get("retrieval_pack_count") or 0) <= 8 and extraction_summary:
        findings.append(
            _finding(
                "medium",
                "retrieval_too_narrow",
                "Extraction used very few evidence packs for a full-bylaw run.",
                f"retrieval_pack_count={extraction_summary.get('retrieval_pack_count')}",
                "Increase V2 discovery budget or inspect why scoring filtered most source chunks.",
                "Assert Calgary full-bylaw discovery produces more than a tiny smoke-test pack count.",
            )
        )
    top_gaps = Counter(gap for rule in review_rules for gap in rule.get("support_gaps", []))
    if top_gaps.get("operator_not_supported", 0) >= 5:
        findings.append(
            _finding(
                "medium",
                "missing_parent_context",
                "Many review items lack supported operator wording.",
                f"operator_not_supported count={top_gaps['operator_not_supported']}",
                "Check whether parent headings like minimum/maximum were separated from child clauses.",
                "Add a source-pack test where a child clause inherits an authentic parent lead-in.",
            )
        )
    if rejected_rules:
        true_rule_like = [
            rule for rule in rejected_rules
            if {"value_not_found_in_evidence", "operator_not_supported"}.isdisjoint(set(rule.get("support_gaps", [])))
        ]
        if true_rule_like:
            findings.append(
                _finding(
                    "low",
                    "rejection_review",
                    "Some rejected rules are not obviously malformed from common field gaps.",
                    f"candidate_count={len(true_rule_like)}",
                    "Manually inspect whether any should fail-closed to review instead of rejection.",
                    "Add a rejection-disposition test for any confirmed true-rule rejection.",
                )
            )
    code_findings = _heuristic_code_findings(context.get("code", []))
    findings.extend(code_findings)
    return {
        "mode": "heuristic" if model is None else "llm_fallback_heuristic",
        "model": model,
        "summary": {
            "finding_count": len(findings),
            "estimated_cost_usd": cost.get("estimated_cost_usd"),
            "candidate_rule_count": extraction_summary.get("candidate_rule_count"),
            "verified_or_review_recall": rule_metrics.get("verified_or_review_recall"),
            "false_verified_count": rule_metrics.get("false_verified_count"),
        },
        "findings": findings,
        "retrieved_context_count": len(context.get("retrieved_context", [])),
    }


def build_rerun_plan(report: dict[str, Any]) -> dict[str, Any]:
    actions = []
    for finding in report.get("findings", []):
        category = finding.get("category")
        if category in {"missing_parent_context", "retrieval_too_narrow", "low_recall"}:
            actions.append(
                {
                    "finding_id": finding.get("finding_id"),
                    "action": "rerun_discovery_then_extraction",
                    "advisory_only": True,
                    "reason": finding.get("claim"),
                }
            )
        elif category in {"logic_contradiction", "unsafe_precedence", "unreachable_branch", "test_gap"}:
            actions.append(
                {
                    "finding_id": finding.get("finding_id"),
                    "action": "write_or_run_deterministic_test_before_code_change",
                    "advisory_only": True,
                    "reason": finding.get("claim"),
                }
            )
    return {
        "advisory_only": True,
        "action_count": len(actions),
        "actions": actions,
        "notes": [
            "Reruns must pass through deterministic source repair and verification.",
            "No examiner action can promote a rule directly.",
        ],
    }


def safe_write_examiner_outputs(output_dir: Path, report: dict[str, Any], suggestions: dict[str, Any], rerun_plan: dict[str, Any]) -> None:
    payloads = {
        "llm_examiner_report.json": report,
        "llm_examiner_suggestions.json": suggestions,
        "llm_examiner_rerun_plan.json": rerun_plan,
    }
    if set(payloads) & PROTECTED_OUTPUTS:
        raise RuntimeError("examiner attempted to write a protected verifier artifact")
    for name, payload in payloads.items():
        write_json(output_dir / name, payload)


def _llm_examiner_report(context: dict[str, Any], *, model: str, api_key: str) -> dict[str, Any]:
    prompt = _examiner_prompt(context)
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 2400,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a private advisory software and pipeline examiner. "
                    "Find extraction, verification-debugging, and Python logic issues. "
                    "You cannot approve zoning rules or modify artifacts. Return JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ubco-mds-2025-labs",
            "X-Title": "Burnaby V2 Shadow Examiner",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_code_fence(content))
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
        report = heuristic_examiner_report(context, model=model)
        report["llm_error"] = f"{type(exc).__name__}: {exc}"
        return report
    findings = parsed.get("findings") if isinstance(parsed, dict) else []
    if not isinstance(findings, list):
        findings = []
    normalized = []
    for item in findings:
        if isinstance(item, dict):
            normalized.append(_normalize_finding(item))
    return {
        "mode": "llm",
        "model": model,
        "summary": {"finding_count": len(normalized)},
        "findings": normalized,
        "retrieved_context_count": len(context.get("retrieved_context", [])),
    }


def _examiner_prompt(context: dict[str, Any]) -> str:
    bounded = {
        "artifacts": {
            name: _bound(value, 5000)
            for name, value in (context.get("artifacts") or {}).items()
        },
        "retrieved_context": context.get("retrieved_context", [])[:10],
        "code": context.get("code", []),
        "required_output": {
            "findings": [
                {
                    "severity": "critical|high|medium|low|info",
                    "category": "logic_contradiction|unsafe_precedence|unreachable_branch|overbroad_regex_or_match|missing_source_grounding|advisory_boundary_risk|silent_failure|test_gap|retrieval_too_narrow|low_recall|missing_parent_context|other",
                    "file_path": "optional path",
                    "line_start": "optional integer",
                    "line_end": "optional integer",
                    "claim": "what is wrong",
                    "evidence": "specific artifact/code evidence",
                    "suggestion": "what to do next",
                    "suggested_test": "deterministic test to add/run",
                    "speculative": False,
                    "advisory_only": True,
                }
            ]
        },
    }
    return json.dumps(bounded, indent=2, ensure_ascii=False)


def _review_queries(artifacts: dict[str, Any]) -> list[str]:
    queries = []
    for rule in (artifacts.get("review_needed.json") or [])[:6]:
        pieces = [
            str(rule.get("rule_object") or ""),
            str(rule.get("operator") or ""),
            str(rule.get("value") or ""),
            " ".join(str(gap) for gap in rule.get("support_gaps", [])[:3]),
        ]
        query = " ".join(piece for piece in pieces if piece)
        if query:
            queries.append(query)
    if not queries:
        queries.append("height setback separation floor area laneway backyard suite")
    return queries[:6]


def _heuristic_code_findings(code_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for item in code_items:
        text = item.get("text") or ""
        path = item.get("path") or ""
        if path.endswith("verification.py") and "verification_decision_from_gaps" not in text[:12000]:
            findings.append(
                _finding(
                    "info",
                    "test_gap",
                    "Verifier decision precedence is hard to audit from the bounded snippet.",
                    path,
                    "Keep property tests covering gap-order independence and critical-gap precedence.",
                    "Run tests/test_property_invariants.py.",
                    file_path=path,
                )
            )
        if "except Exception" in text and "advisory" not in text.lower():
            findings.append(
                _finding(
                    "low",
                    "silent_failure",
                    "Broad exception handler may hide non-advisory failures.",
                    path,
                    "Review whether this fallback should record an explicit error artifact.",
                    "Add a test that malformed input is reported rather than silently swallowed.",
                    file_path=path,
                )
            )
    return findings


def _finding(
    severity: str,
    category: str,
    claim: str,
    evidence: str,
    suggestion: str,
    suggested_test: str,
    *,
    file_path: str | None = None,
) -> dict[str, Any]:
    return _normalize_finding(
        {
            "severity": severity,
            "category": category,
            "claim": claim,
            "evidence": evidence,
            "suggestion": suggestion,
            "suggested_test": suggested_test,
            "file_path": file_path,
            "advisory_only": True,
        }
    )


def _normalize_finding(item: dict[str, Any]) -> dict[str, Any]:
    claim = str(item.get("claim") or "No claim supplied")
    return {
        "finding_id": str(item.get("finding_id") or cache_key(item.get("category"), claim, item.get("evidence"))[:16]),
        "severity": str(item.get("severity") or "info"),
        "category": str(item.get("category") or "other"),
        "file_path": item.get("file_path"),
        "line_start": item.get("line_start"),
        "line_end": item.get("line_end"),
        "claim": claim,
        "evidence": str(item.get("evidence") or ""),
        "suggestion": str(item.get("suggestion") or ""),
        "suggested_test": str(item.get("suggested_test") or ""),
        "speculative": bool(item.get("speculative", False)),
        "advisory_only": True,
    }


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _bound(value: Any, max_chars: int) -> Any:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= max_chars:
        return value
    return {"truncated": True, "preview": text[:max_chars]}


def _strip_code_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value


def _redact_secrets(text: str) -> str:
    openrouter_prefix = "sk-or-" + "v1-"
    text = re.sub(re.escape(openrouter_prefix) + r"[A-Za-z0-9]+", openrouter_prefix + "[REDACTED]", text)
    text = re.sub(r"AIza[A-Za-z0-9_-]+", "AIza[REDACTED]", text)
    text = re.sub(r"(?i)(api[_-]?key\s*=\s*)['\"][^'\"]+['\"]", r"\1'[REDACTED]'", text)
    text = re.sub(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", text)
    return text


def load_openrouter_key(root: Path) -> str:
    existing = os.getenv("OPENROUTER_API_KEY")
    if existing:
        return existing.strip()
    env = root / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""
