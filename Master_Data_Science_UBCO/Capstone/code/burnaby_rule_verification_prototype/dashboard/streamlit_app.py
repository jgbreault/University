"""Streamlit dashboard for Burnaby verifier outputs."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Load ``KEY=VALUE`` pairs from a local ``.env`` into ``os.environ``.

    The verifier's extraction layer reads ``OPENROUTER_API_KEY`` from ``.env``;
    the dashboard's bylaw chatbot reuses the SAME key so the chat works out of
    the box locally with no extra setup. Never overrides an already-set
    environment variable or a Streamlit secret, and never raises.
    """
    try:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:  # pragma: no cover - dotenv loading must never break the app
        pass


_load_dotenv(ROOT / ".env")

# Default chat model for the bylaw assistant when OpenRouter is the provider.
# google/gemini-3.1-flash-lite is fast, cheap, and confirmed available on
# OpenRouter; override with the BYLAW_RAG_MODEL secret/env var.
DEFAULT_BYLAW_CHAT_MODEL = "google/gemini-3.1-flash-lite"

OUTPUTS_ROOT = ROOT / "outputs"
OUTPUT_DIR_SUFFIX = "_slim_pipeline5_registry"
NATIVE_RUN_ROOTS = ("m7_runs", "v3_runs", "v2_runs")
NATIVE_RUN_LABELS = {"m7_runs": "M7", "v3_runs": "V3", "v2_runs": "V2"}
PRODUCT_RUN_ROOTS = ("m7_runs", "v3_runs")
# Pipeline 9 (graph-RAG extraction) verifier outputs sit next to the P5
# registries as <city>_p9/. Same verifier, second upstream — the dashboard
# treats them as another selectable "city" so reviewers see the P9 lane.
P9_DIR_SUFFIX = "_p9"
DEFAULT_OUTPUT_DIR = OUTPUTS_ROOT / "m7_runs" / "burnaby_r1" / "google_gemini_3_1_flash_lite"
MVP_REPORT_PATH = OUTPUTS_ROOT / "mvp_verification" / "mvp_report.json"
M4_SOURCE_AUDIT_PATH = OUTPUTS_ROOT / "topdown_validation" / "m4_source_pdf_audit.json"
REFERENCE_DIR_SUFFIXES = (
    OUTPUT_DIR_SUFFIX,
    f"{OUTPUT_DIR_SUFFIX}_v21",
    P9_DIR_SUFFIX,
    f"{P9_DIR_SUFFIX}_v21",
)
SOURCE_DOCUMENT_URL = "https://www.burnaby.ca/sites/default/files/acquiadam/2024-07/R1Small-Scale-Multi-Unit-Housing-District.pdf"
SOURCE_DOCUMENT_URLS = {
    "burnaby_r1": SOURCE_DOCUMENT_URL,
    "calgary_rcg": "https://www.calgary.ca/content/dam/www/pda/pd/documents/calgary-land-use-bylaw-1p2007/land-use-bylaw-1p2007.pdf",
    "vancouver_rs": "https://former.vancouver.ca/commsvcs/BYLAWS/zoning/sec11.pdf",
}

# Color semantics used across the whole dashboard. Presentation only.
STATUS_COLORS = {
    "verified": "#1a7f37",
    "review": "#9a6700",
    "rejected": "#cf222e",
    "not_used": "#57606a",
}

# Active source-document URL for the selected city (module-level so the
# many detail panels stay simple). Falls back to the Burnaby PDF.
_ACTIVE_SOURCE = {"url": SOURCE_DOCUMENT_URL, "label": "source bylaw PDF"}


PLAIN_LABELS = {
    "verified": "Verified",
    "review": "Needs review",
    "review_needed": "Needs review",
    "rejected": "Rejected",
    "not_used": "Not used",
    "human_legal_review": "Needs legal review",
    "operator_review": "Check direction words",
    "rerun_with_evidence_bundle": "Try stronger evidence",
    "retry_with_better_evidence": "Try stronger evidence",
    "condition_evidence_needed": "Find condition evidence",
    "scope_review": "Check legal scope",
    "semantic_guardrail_review": "Meaning looks close, but support is missing",
    "semantic_duplicate_review": "Possible duplicate",
    "fix_candidate_or_rule_family_mapping": "Fix extracted rule type",
    "defer_low_priority": "Lower priority",
    "missing_applies_to": "Missing what the rule applies to",
    "missing_condition_evidence": "Missing condition evidence",
    "missing_scope_evidence": "Missing scope evidence",
    "general_review": "General review",
    "operator_uncertain": "Direction word is unclear",
    "near_verified_table_context": "Near verified table wording",
    "text_candidate_needs_consensus": "Only one text source supports it",
    "unresolved_exception": "Possible exception or qualifier",
    "possible_rule_object_mismatch": "Possible wrong rule type",
    "upstream_review_requested": "Extractor asked for review",
    "plausible": "Plausible",
    "likely_correct": "Likely correct",
    "weak": "Weak support",
    "likely_wrong_or_noise": "Likely wrong or noise",
    "guardrail_blocked_low_similarity": "Not close enough to verified rules",
    "high_confidence_near_duplicate": "Likely duplicate",
    "close_semantic_match": "Close meaning match",
    "no_close_semantic_match": "No close meaning match",
    "operator_not_supported": "Direction word not proven",
    "scope_not_supported": "Scope not proven",
    "applies_to_not_supported": "Applies-to text not proven",
    "condition_not_supported": "Condition not proven",
    "unit_not_supported": "Unit not proven",
    "value_not_supported": "Number not proven",
    "rule_object_not_supported": "Rule type not proven",
    "rag_context_mismatch": "Extractor text did not match the source page",
    "pass": "Pass",
    "fail-closed": "Fail-closed",
    "scope mismatch": "Scope mismatch",
    "unsafe / needs fix": "Unsafe / needs fix",
    "needs review": "Needs review",
    "missing": "Missing",
    "mvp_safety_ready": "Safety ready",
    "native_m7": "Native M7",
    "native_v3": "Native V3",
    "native_v2": "Native V2",
    "legacy_p5": "Pipeline 5 reference",
    "legacy_p9": "Pipeline 9 reference",
    "legacy_internal_registry": "Internal registry reference",
    "burnaby_r1": "Burnaby R1",
    "vancouver_rs": "Vancouver RS",
    "calgary_rcg": "Calgary RCG",
}


HELP_TEXT = {
    "human_legal_review": "The evidence may be real, but the rule depends on legal interpretation, an exception, or a condition that the verifier should not guess.",
    "operator_review": "The number is present, but the source text does not safely prove whether it is a minimum, maximum, or exact requirement.",
    "rerun_with_evidence_bundle": "There may be enough source text if several nearby evidence snippets are combined, but it still must pass the deterministic verifier.",
    "retry_with_better_evidence": "The candidate may be correct, but the current evidence packet is too weak. Find a stronger source passage first.",
    "condition_evidence_needed": "The candidate depends on a condition, qualifier, exception, or branch that needs explicit source support.",
    "scope_review": "The candidate may use the right number but for the wrong legal scope, object, or building type.",
    "semantic_guardrail_review": "The meaning resembles a verified rule, but similarity is advisory only and cannot approve it.",
    "semantic_duplicate_review": "This may already be covered by a verified rule. Check before adding another rule.",
    "fix_candidate_or_rule_family_mapping": "The extractor likely assigned the wrong rule family, such as treating a definition as a numeric zoning rule.",
    "defer_low_priority": "This item is probably outside the current numeric verification contract or has weak support.",
    "fail-closed": "The verifier avoided unsafe approvals, but too many true rules may still be stuck in review.",
    "scope mismatch": "The extractor produced many candidates outside the verifier's current numeric zoning contract.",
    "unsafe / needs fix": "At least one false verified rule or false approval was found. Treat this output as unsafe until fixed.",
    "pass": "The benchmark gates passed for the current contract.",
    "native_m7": "Current native exhaustive extraction path. RAG finds evidence; deterministic verification still decides.",
    "native_v3": "Previous native extraction reference. Kept for comparison.",
    "native_v2": "Older native extraction reference. Kept for comparison.",
    "legacy_p5": "Legacy structured-registry reference. Kept for comparison, not the current product path.",
    "legacy_p9": "Legacy graph-RAG reference. Kept for comparison, not the current product path.",
}


RAW_VALUE_COLUMNS = {
    "rule_id",
    "source_rule_id",
    "matched_verified",
    "semantic_match",
    "evidence_id",
    "current_evidence",
    "best_evidence",
    "original_evidence",
    "retry_evidence",
    "bundle_ids",
    "file",
    "path",
    "url",
    "quote",
    "evidence",
    "source_window",
    "value",
    "unit",
    "score",
    "confidence",
    "count",
    "rows",
}

# Retrieval depth for the bylaw chatbot. The grounded LLM only sees what is
# retrieved, so too-shallow retrieval makes it answer "the sections do not say"
# even when the bylaw does. Modern chat models (the OpenRouter default has a 1M
# context window) easily absorb a generous, section-grounded context, so we
# retrieve broadly and let the model find the relevant clause.
RAG_CHAT_TOP_K = 8
# Two-stage retrieval: BM25/RRF is recall-oriented but its ordering buries the
# decisive clause among many same-topic sections (e.g. the canonical R-CG height
# question puts the 11.0 m clause §541(1) at ~rank 24 behind a dozen other
# "building height" hits). So we retrieve a BROAD candidate set and, when an
# OpenRouter key is available, rerank the shortlist with a cross-encoder
# (cohere/rerank-4-fast) down to RAG_CHAT_TOP_K. No key / any rerank error falls
# back to the BM25/RRF order — never raises, never starves the LLM context.
RAG_RERANK_CANDIDATES = 30
RAG_CONTEXT_CHAR_LIMIT = 18000
RAG_CONTEXT_PER_HIT_LIMIT = 2400

RAG_QUERY_SYNONYMS = {
    "tall": ("height",),
    "high": ("height",),
    "taller": ("height",),
    "big": ("floor", "area", "size"),
    "large": ("floor", "area", "size"),
    "size": ("floor", "area"),
    "far": ("setback", "distance"),
    "close": ("setback", "separation", "distance"),
    "distance": ("setback", "separation"),
    "wide": ("width",),
    "floors": ("storeys",),
    "levels": ("storeys",),
    "garage": ("parking",),
}


def native_run_root(output_dir: Path) -> str | None:
    """Return m7_runs/v3_runs/v2_runs for a native model output dir."""
    try:
        root = output_dir.parent.parent.name
    except IndexError:
        return None
    return root if root in NATIVE_RUN_ROOTS else None


def m55_run_id(output_dir: Path) -> str:
    try:
        if output_dir.parent.parent.name == "m7_measure":
            return output_dir.parent.name
    except IndexError:
        return ""
    return ""


def native_lane_for_dir(output_dir: Path) -> str | None:
    root = native_run_root(output_dir)
    if root is None:
        return None
    return f"native_{NATIVE_RUN_LABELS[root].lower()}"


def native_label_for_dir(output_dir: Path) -> str:
    root = native_run_root(output_dir)
    return NATIVE_RUN_LABELS.get(str(root), "Native")


def preferred_reference_dir(stem: str, suffix: str, outputs_root: Path | None = None) -> Path:
    """Prefer refreshed v21 reference artifacts, then fall back to old names."""
    outputs_root = outputs_root or OUTPUTS_ROOT
    versioned = outputs_root / f"{stem}{suffix}_v21"
    if versioned.exists():
        return versioned
    return outputs_root / f"{stem}{suffix}"


def discover_city_output_dirs(outputs_root: Path = OUTPUTS_ROOT) -> list[Path]:
    """Return city output dirs that contain verified_rules.json, sorted by name.

    Any new city (e.g. calgary) appears automatically once its
    `<city>_..._slim_pipeline5_registry/verified_rules.json` exists on disk.
    """
    if not outputs_root.is_dir():
        return []
    standard = [
        path
        for path in outputs_root.iterdir()
        if path.is_dir()
        and path.name.endswith(REFERENCE_DIR_SUFFIXES)
        and (path / "verified_rules.json").exists()
    ]
    native_runs = []
    for root_name in NATIVE_RUN_ROOTS:
        native_root = outputs_root / root_name
        if not native_root.is_dir():
            continue
        for city_dir in native_root.iterdir():
            if not city_dir.is_dir():
                continue
            for model_dir in city_dir.iterdir():
                if model_dir.is_dir() and (model_dir / "verified_rules.json").exists():
                    native_runs.append(model_dir)
    m55_runs = []
    m55_root = outputs_root / "m7_measure"
    if m55_root.is_dir():
        for run_dir in m55_root.iterdir():
            if not run_dir.is_dir():
                continue
            for city_dir in run_dir.iterdir():
                if city_dir.is_dir() and (city_dir / "verified_rules.json").exists():
                    m55_runs.append(city_dir)
    return sorted([*standard, *native_runs, *m55_runs], key=lambda path: str(path))


def discover_product_output_dirs(outputs_root: Path = OUTPUTS_ROOT) -> list[Path]:
    """Return only the demo product path and its direct predecessor.

    The workspace keeps V2/P5/P9 artifacts for audit and regression work, but
    the final dashboard selector should stay focused: current M7 plus the V3
    run it was built from.
    """
    if not outputs_root.is_dir():
        return []
    product_runs = []
    for root_name in PRODUCT_RUN_ROOTS:
        native_root = outputs_root / root_name
        if not native_root.is_dir():
            continue
        for city_dir in native_root.iterdir():
            if not city_dir.is_dir():
                continue
            # Model-agnostic: pick the newest model dir present per city (the M7
            # default is google_gemini_3_1_flash_lite; '3_1' sorts after '2_5').
            # Hardcoding the 2.5 slug here was a rename miss that hid the M7 product.
            model_dirs = sorted(
                (md for md in city_dir.iterdir() if md.is_dir() and (md / "verified_rules.json").exists()),
                key=lambda md: md.name,
                reverse=True,
            )
            if model_dirs:
                product_runs.append(model_dirs[0])
    order = {root: index for index, root in enumerate(PRODUCT_RUN_ROOTS)}
    return sorted(product_runs, key=lambda path: (order.get(path.parent.parent.name, 99), city_stem_from_dir(path)))


def city_key_from_dir(output_dir: Path) -> str:
    """Return the city prefix for an output dir, e.g. burnaby_r1_... -> burnaby."""
    if m55_run_id(output_dir):
        return output_dir.name.split("_")[0].lower()
    if native_run_root(output_dir):
        return output_dir.parent.name.split("_")[0].lower()
    return output_dir.name.split("_")[0].lower()


def city_stem_from_dir(output_dir: Path) -> str:
    """Return the full city stem, e.g. burnaby_r1_slim_pipeline5_registry ->
    burnaby_r1 and vancouver_rs_p9 -> vancouver_rs.

    The short ``city_key`` ('burnaby') is right for centroids and labels but
    WRONG for artifact paths — every on-disk artifact uses the full stem
    ('burnaby_r1'), which is why path lookups must come through here.
    """
    name = output_dir.name
    if m55_run_id(output_dir):
        return name
    if native_run_root(output_dir):
        return output_dir.parent.name
    for suffix in (f"{OUTPUT_DIR_SUFFIX}_v21", OUTPUT_DIR_SUFFIX, f"{P9_DIR_SUFFIX}_v21", P9_DIR_SUFFIX):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def bylaw_index_path(output_dir: Path) -> Path | None:
    """Resolve the bylaw-RAG index for an output dir.

    A P5 registry carries its own index; a P9 run borrows the sibling P5
    registry's index for the SAME city stem (same bylaw corpus). Previously
    this path was built from the short city_key, which never matched a real
    directory — the legal-context expander silently rendered nothing.
    """
    own = output_dir / "bylaw_rag_index.json"
    if own.exists():
        return own
    sibling = OUTPUTS_ROOT / f"{city_stem_from_dir(output_dir)}{OUTPUT_DIR_SUFFIX}" / "bylaw_rag_index.json"
    if sibling.exists():
        return sibling
    source_corpus = ROOT / "benchmark" / "source_corpus" / city_stem_from_dir(output_dir) / "rag_index.json"
    if source_corpus.exists():
        return source_corpus
    return None


def city_label_from_dir(output_dir: Path) -> str:
    """Human-readable label for the sidebar selector, e.g. 'Burnaby R1'."""
    run_id = m55_run_id(output_dir)
    if run_id:
        stem = city_stem_from_dir(output_dir)
        parts = [part for part in stem.split("_") if part]
        base = parts[0].capitalize() + (" " + " ".join(part.upper() for part in parts[1:]) if parts[1:] else "")
        if run_id.startswith("m7"):
            label = "M7"
        elif run_id.startswith(("m56", "m6")):
            label = "M6"
        else:
            label = "M5.5"
        return f"{label} {run_id} — {base}"
    native_root = native_run_root(output_dir)
    if native_root:
        stem = city_stem_from_dir(output_dir)
        parts = [part for part in stem.split("_") if part]
        base = parts[0].capitalize() + (" " + " ".join(part.upper() for part in parts[1:]) if parts[1:] else "")
        if native_root == "m7_runs":
            return f"Current M7 \u2014 {base}"
        if native_root == "v3_runs":
            return f"Previous V3 \u2014 {base}"
        return f"{NATIVE_RUN_LABELS[native_root]} reference \u2014 {base}"
    is_p9 = output_dir.name.endswith(P9_DIR_SUFFIX) or output_dir.name.endswith(f"{P9_DIR_SUFFIX}_v21")
    stem = city_stem_from_dir(output_dir)
    parts = [part for part in stem.split("_") if part]
    if not parts:
        return output_dir.name
    label = parts[0].capitalize() + (" " + " ".join(part.upper() for part in parts[1:]) if parts[1:] else "")
    return f"{label} — Pipeline 9" if is_p9 else label


def source_document_url_for_output(output_dir: Path, data: dict[str, Any]) -> str:
    """Return the best source-PDF URL for the selected city output."""
    _ = data
    return SOURCE_DOCUMENT_URLS.get(city_stem_from_dir(output_dir), SOURCE_DOCUMENT_URL)


def load_output_data(output_dir: Path) -> dict[str, Any]:
    """Load all dashboard source files from one verifier output directory."""
    # The dashboard is intentionally read-only. It consumes generated JSON
    # reports and never calls Gemini, reruns verification, or mutates outputs.
    return {
        "output_dir": output_dir,
        "validation": _read_json(output_dir / "validation_report.json", {}),
        "benchmark": _read_json(output_dir / "benchmark_report.json", {}),
        "intelligence": _read_json(output_dir / "evidence_intelligence.json", {"items": [], "summary": {}}),
        "repair": _read_json(output_dir / "evidence_repair_suggestions.json", {"suggestions": []}),
        "rerun": _read_json(output_dir / "evidence_rerun_report.json", {"attempts": [], "verified_after_rerun": []}),
        "bundle_rerun": _read_json(output_dir / "evidence_bundle_rerun_report.json", {"attempts": [], "promotion_ready": []}),
        "safe_tuning": _read_json(output_dir / "safe_verifier_tuning_candidates.json", {"items": [], "candidate_count": 0}),
        "router": _read_json(output_dir / "review_router.json", {"items": [], "summary": {}}),
        "resolution": _read_json(output_dir / "review_resolution.json", {"items": [], "summary": {}}),
        "rule_graph": _read_json(output_dir / "rule_graph.json", {"nodes": [], "edges": [], "summary": {}}),
        "semantic": _read_json(output_dir / "semantic_review_report.json", {"items": [], "summary": {}}),
        "bundle_promotion": _read_json(output_dir / "bundle_promotion_report.json", {"promoted_rules": []}),
        "source_repair": _read_json(output_dir / "source_repair_report.json", {"items": [], "status_counts": {}}),
        "review_assistant_packets": _read_json(output_dir / "review_assistant_packets.json", {"items": []}),
        "coverage_report": _read_json(output_dir / "coverage_report.json", {}),
        "rule_slot_ledger": _read_json(output_dir / "rule_slot_ledger.json", {}),
        "slot_audit": _read_json(output_dir / "slot_audit.json", {}),
        "m55_reconciliation": _read_json(output_dir / "m4_m55_reconciliation.json", {}),
        "evidence_units": _read_json(output_dir / "evidence_units.json", []),
        "verified": _read_json(output_dir / "verified_rules.json", []),
        "review": _read_json(output_dir / "review_needed.json", []),
        "rejected": _read_json(output_dir / "rejected_rules.json", []),
        "not_used": _read_json(output_dir / "not_used.json", []),
        "rule_candidates": _read_json(output_dir / "rule_candidates.json", []),
        "preflight": _read_json(output_dir / "pipeline5_extraction_preflight.json", {}),
        "model_cost": _read_json(output_dir / "model_cost_report.json", {}),
        "source_summary": _read_json(output_dir / "source_summary.json", {}),
        "examiner": _read_json(output_dir / "llm_examiner_report.json", {}),
        "examiner_suggestions": _read_json(output_dir / "llm_examiner_suggestions.json", {"items": []}),
        "examiner_rerun": _read_json(output_dir / "llm_examiner_rerun_plan.json", {"actions": []}),
    }


def output_bucket_counts(data: dict[str, Any]) -> dict[str, int]:
    """KPI bucket counts that match the lists the dashboard actually renders.

    The triage tables, matrix and funnel are built from the loaded bucket lists
    (verified_rules.json, review_needed.json, ...), so the KPI must count THOSE
    lists. A validation_report.json ``bucket_counts`` can drift out of sync with
    the on-disk artifacts; using it as the headline let the "Needs review" KPI
    disagree with the review table beneath it. The validation counts are now only
    a fallback for a bucket whose list was not loaded at all.
    """
    validation_counts = ((data.get("validation") or {}).get("bucket_counts") or {})
    live = {
        "verified": data.get("verified"),
        "review_needed": data.get("review"),
        "rejected": data.get("rejected"),
        "not_used": data.get("not_used"),
    }
    return {
        bucket: len(items) if isinstance(items, list) else int(validation_counts.get(bucket) or 0)
        for bucket, items in live.items()
    }


# Funnel stage semantics. FIELD_GAPS are per-field proof failures (the words,
# number, unit, or direction could not be grounded in the cited evidence);
# POLICY_GAPS hold a fully-proven rule for a human by policy. A review rule
# with any FIELD_GAP dies at the "fields proven" stage; one held only by
# POLICY_GAPS is a parking lot, not a loss — the funnel renders it as "held".
FIELD_GAPS = frozenset(
    {
        "value_not_found_in_evidence",
        "unit_not_found_in_evidence",
        "operator_not_supported",
        "applies_to_not_supported",
        "constraint_scope_not_supported",
        "rule_object_not_supported",
        "rule_object_not_canonical",
        "rule_object_unit_not_compatible",
        "non_numeric_value_for_numeric_rule",
        "text_condition_not_supported",
        "table_applies_to_not_supported",
        "table_condition_not_supported",
        "table_rule_object_not_supported",
        "table_operator_refuted",
        "rule_family_direction_mismatch",
        "cross_family_value_collision",
        "source_evidence_id_not_found",
    }
)
POLICY_GAPS = frozenset(
    {
        "pipeline5_text_candidate_requires_review",
        "table_cell_candidate_requires_review",
        "table_evidence_candidate_requires_review",
        "table_fallback_candidate_requires_review",
        "table_column_not_target_scope",
        "unresolved_exception_cue",
        "allowance_trigger_threshold",
        "upstream_extraction_requested_review",
    }
)


def _gap_codes(rule: dict[str, Any]) -> list[str]:
    gaps = rule.get("support_gaps")
    if not gaps:
        gaps = rule.get("review_reasons") or []
    return [str(gap) for gap in gaps]


def _top_reasons(
    rules: list[dict[str, Any]],
    limit: int = 3,
    only: frozenset[str] | None = None,
) -> list[tuple[str, int]]:
    # ``only`` scopes the story to the gate being explained: a review rule
    # carries BOTH field and policy gaps, and each stage should show its own.
    counts = Counter(
        code
        for rule in rules
        for code in _gap_codes(rule)
        if only is None or code in only
    )
    return [(_plain_label(code), count) for code, count in counts.most_common(limit)]


def funnel_stages(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Candidate -> verified funnel rows. Pure data; rendering happens later.

    Stages: extracted -> inside verification scope (- not_used) -> evidence-backed
    (- rejected) -> fields proven (- review rules with FIELD_GAPS) ->
    verified (- review rules held by policy only). Counts reconcile with the
    bucket files by construction; if the candidate file is missing the first
    stage falls back to the bucket sum so the funnel never lies.
    """
    verified = data.get("verified") or []
    review = data.get("review") or []
    rejected = data.get("rejected") or []
    not_used = data.get("not_used") or []
    bucket_total = len(verified) + len(review) + len(rejected) + len(not_used)
    candidates = data.get("rule_candidates") or []
    total = len(candidates) or bucket_total

    field_held = [rule for rule in review if set(_gap_codes(rule)) & FIELD_GAPS]
    policy_held = [rule for rule in review if not (set(_gap_codes(rule)) & FIELD_GAPS)]

    stages = [
        {
            "stage": "extracted",
            "label": "Candidates extracted",
            "count": total,
            "dropped": 0,
            "outflow_status": "",
            "top_reasons": [],
        },
        {
            "stage": "in_contract",
            "label": "Inside verification scope",
            "count": total - len(not_used),
            "dropped": len(not_used),
            "outflow_status": "not_used",
            "top_reasons": _top_reasons(not_used),
        },
        {
            "stage": "evidence_backed",
            "label": "Evidence-backed (not contradicted)",
            "count": total - len(not_used) - len(rejected),
            "dropped": len(rejected),
            "outflow_status": "rejected",
            "top_reasons": _top_reasons(rejected, only=FIELD_GAPS),
        },
        {
            "stage": "fields_proven",
            "label": "Every field proven",
            "count": len(verified) + len(policy_held),
            "dropped": len(field_held),
            "outflow_status": "review",
            "top_reasons": _top_reasons(field_held, only=FIELD_GAPS),
        },
        {
            "stage": "verified",
            "label": "Verified",
            "count": len(verified),
            "dropped": len(policy_held),
            "outflow_status": "held",
            "top_reasons": _top_reasons(policy_held, only=POLICY_GAPS),
        },
    ]
    if total != bucket_total and candidates:
        stages[0]["note"] = (
            f"{total} extracted candidates vs {bucket_total} decided rules — "
            "some candidates merge before decision."
        )
    return stages


MATRIX_COLUMNS: list[tuple[str, str]] = [
    ("rowhouse", "Rowhouse (1\u20133 units)"),
    ("ssmu_1_2", "SSMU 1\u20132 units"),
    ("ssmu_3_4", "SSMU 3\u20134 units"),
    ("ssmu_5_6_ftn", "SSMU 5\u20136 units (FTN only)"),
]

_FOOTNOTE_SUFFIX_RE = re.compile(r"\s*\.\d+\s*$")


def gold_path_for(output_dir: Path, root: Path = ROOT) -> Path | None:
    """Gold rules file for an output dir's city stem, or None."""
    path = root / "benchmark" / "gold" / f"{city_stem_from_dir(output_dir)}_gold_rules.json"
    return path if path.exists() else None


def applicability_buckets(rule: dict[str, Any]) -> set[str]:
    """Map a rule onto the Burnaby 101.4 matrix columns.

    Prefers the verifier's structured ``applicability`` block (selectors with
    dwelling_type + unit_range); degrades to text-parsing applies_to/condition
    for rules that predate it. A rule with no dwelling-type signal spans ALL
    columns — that is how 101.4 actually reads (building-scoped rows like the
    setbacks apply to every dwelling-type column).
    """
    buckets: set[str] = set()
    block = rule.get("applicability") or {}
    for selector in block.get("selectors") or []:
        dwelling = selector.get("dwelling_type")
        unit_range = selector.get("unit_range") or {}
        low, high = unit_range.get("min"), unit_range.get("max")
        exact = unit_range.get("exact")
        if dwelling == "rowhouse":
            buckets.add("rowhouse")
        elif dwelling == "small_scale_multi_unit" or low is not None or exact is not None:
            if (low, high) == (1, 2):
                buckets.add("ssmu_1_2")
            elif (low, high) == (3, 4) or exact in (3, 4):
                buckets.add("ssmu_3_4")
            elif (low, high) == (5, 6) or exact in (5, 6):
                buckets.add("ssmu_5_6_ftn")
            elif exact in (1, 2):
                buckets.add("ssmu_1_2")
            elif dwelling:
                buckets.update({"ssmu_1_2", "ssmu_3_4", "ssmu_5_6_ftn"})
    if buckets:
        return buckets

    text = _FOOTNOTE_SUFFIX_RE.sub("", f"{rule.get('applies_to') or ''}; {rule.get('condition') or ''}").lower()
    if "rowhouse" in text:
        buckets.add("rowhouse")
    if "1 to 2" in text:
        buckets.add("ssmu_1_2")
    if "3 to 4" in text:
        buckets.add("ssmu_3_4")
    if "5 to 6" in text or "frequent transit" in text or "ftn" in text:
        buckets.add("ssmu_5_6_ftn")
    if buckets:
        return buckets
    return {key for key, _ in MATRIX_COLUMNS}


def _matrix_row_key(rule: dict[str, Any]) -> tuple[str, str]:
    family = str(rule.get("rule_object") or "")
    scope = str(rule.get("constraint_scope") or "")
    text = f"{rule.get('applies_to') or ''} {rule.get('condition') or ''}".lower()
    qualifier = ""
    if family in {"height", "storeys"}:
        for role in ("front", "rear", "accessory"):
            if role in text or role in scope:
                qualifier = role
                break
        if family == "height":
            if "sloping" in text:
                qualifier += " sloping"
            elif "flat" in text:
                qualifier += " flat"
    elif family == "setback":
        qualifier = scope.replace("_", " ")
    elif family == "building_separation":
        qualifier = scope.replace("_", " ")
    return (family, qualifier.strip())


_MATRIX_ROW_ORDER = [
    "dwelling_units", "lot_area", "lot_coverage", "impervious_surface",
    "height", "storeys", "setback", "building_separation",
]


def matrix_cells(
    verified: list[dict[str, Any]],
    review: list[dict[str, Any]],
    gold_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the 101.4 matrix grid: rows = regulations, cols = dwelling buckets.

    Cell precedence: verified > review > gold-only "missing" > "n/a". A cell
    is only ever called MISSING when a gold row claims it should exist —
    absence of gold means no claim, rendered honestly as n/a.
    """
    cells: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def add(rule: dict[str, Any], status: str) -> None:
        family = str(rule.get("rule_object") or "")
        if family not in _MATRIX_ROW_ORDER:
            return
        row_key = _matrix_row_key(rule)
        for bucket in applicability_buckets(rule):
            slot = cells.setdefault(row_key, {}).get(bucket)
            rank = {"verified": 0, "review": 1, "missing": 2}
            if slot is None or rank[status] < rank[slot["status"]]:
                value = f"{rule.get('value') or ''} {rule.get('unit') or ''}".strip()
                reason = ""
                if status == "review":
                    reason = _plain_join((rule.get("support_gaps") or [])[:2])
                if status == "missing":
                    reason = "in gold, not yet proven"
                cells.setdefault(row_key, {})[bucket] = {
                    "status": status,
                    "text": value or status,
                    "rule_id": str(rule.get("rule_id") or rule.get("gold_id") or ""),
                    "reason": reason,
                }

    for rule in verified:
        add(rule, "verified")
    for rule in review:
        add(rule, "review")
    for gold in gold_rules:
        add(gold, "missing")

    rows = []
    for row_key in sorted(cells, key=lambda key: (_MATRIX_ROW_ORDER.index(key[0]), key[1])):
        family, qualifier = row_key
        label = _plain_label(family) + (f" \u2014 {qualifier}" if qualifier else "")
        rows.append(
            {
                "label": label,
                "cells": [
                    cells[row_key].get(bucket, {"status": "na", "text": "n/a", "rule_id": "", "reason": ""})
                    for bucket, _ in MATRIX_COLUMNS
                ],
            }
        )
    return {"columns": [label for _, label in MATRIX_COLUMNS], "rows": rows}


def matrix_table_html(grid: dict[str, Any]) -> str:
    """Render the matrix grid as themed HTML (pure string, testable)."""
    head = "".join(f"<th>{html.escape(column)}</th>" for column in grid["columns"])
    body_rows = []
    for row in grid["rows"]:
        cells = []
        for cell in row["cells"]:
            title = html.escape(f"{cell.get('rule_id') or ''} {cell.get('reason') or ''}".strip())
            cells.append(
                f"<td><span class='matrix-cell status-{cell['status']}' title='{title}'>"
                f"{html.escape(str(cell['text']))}</span></td>"
            )
        body_rows.append(f"<tr><td class='row-label'>{html.escape(row['label'])}</td>{''.join(cells)}</tr>")
    return (
        "<table class='matrix-table'><thead><tr><th>Regulation</th>"
        + head
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table>"
    )


def coverage_rows(
    data: dict[str, Any],
    gold_rules: list[dict[str, Any]],
    benchmark: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per-family coverage: candidates -> buckets -> gold coverage."""
    metrics = (benchmark or {}).get("rule_metrics", {})
    matched_verified = {m.get("gold_id") for m in metrics.get("matched_verified", []) if isinstance(m, dict)}
    matched_review = {m.get("gold_id") for m in metrics.get("matched_review", []) if isinstance(m, dict)}

    families: dict[str, dict[str, Any]] = {}

    def slot(family: str) -> dict[str, Any]:
        return families.setdefault(
            family,
            {"family": family, "candidates": 0, "verified": 0, "review": 0,
             "rejected": 0, "not_used": 0, "gold": 0, "gold_verified": 0,
             "gold_review": 0, "hold_reasons": Counter()},
        )

    for candidate in data.get("rule_candidates") or []:
        slot(str(candidate.get("rule_object") or "?"))["candidates"] += 1
    for bucket in ("verified", "review", "rejected", "not_used"):
        for rule in data.get(bucket) or []:
            entry = slot(str(rule.get("rule_object") or "?"))
            entry[bucket] += 1
            if bucket == "review":
                for gap in _gap_codes(rule)[:1]:
                    entry["hold_reasons"][gap] += 1
    for gold in gold_rules:
        entry = slot(str(gold.get("rule_object") or "?"))
        entry["gold"] += 1
        if gold.get("gold_id") in matched_verified:
            entry["gold_verified"] += 1
        elif gold.get("gold_id") in matched_review:
            entry["gold_review"] += 1

    rows = []
    for family, entry in sorted(families.items(), key=lambda item: -item[1]["candidates"]):
        top = entry["hold_reasons"].most_common(1)
        rows.append(
            {
                "family": _plain_label(family),
                "candidates": entry["candidates"],
                "verified": entry["verified"],
                "review": entry["review"],
                "rejected": entry["rejected"],
                "not_used": entry["not_used"],
                "top_hold_reason": _plain_label(top[0][0]) if top else "",
                "gold": entry["gold"],
                "gold_verified": entry["gold_verified"],
                "gold_review": entry["gold_review"],
                "coverage": (entry["gold_verified"] / entry["gold"]) if entry["gold"] else None,
            }
        )
    return rows


def gold_gap_rows(benchmark: dict[str, Any], gold_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each gold rule the verifier has NOT proven, with where it sits."""
    metrics = (benchmark or {}).get("rule_metrics", {})
    matched_verified = {m.get("gold_id"): m for m in metrics.get("matched_verified", []) if isinstance(m, dict)}
    matched_review = {m.get("gold_id"): m for m in metrics.get("matched_review", []) if isinstance(m, dict)}
    missing_entirely = set(metrics.get("missed_verified_or_review_gold_rule_ids") or [])
    rows = []
    for gold in gold_rules:
        gold_id = str(gold.get("gold_id") or "")
        if gold_id in matched_verified:
            continue
        if gold_id in missing_entirely:
            status, detail = "absent", "no candidate covers this rule \u2014 upstream extraction gap"
        elif gold_id in matched_review:
            status, detail = "review", f"covered in review as {matched_review[gold_id].get('rule_id')}"
        else:
            status, detail = "unproven", "not matched by any verified rule"
        rows.append(
            {
                "gold_id": gold_id,
                "family": _plain_label(str(gold.get("rule_object") or "")),
                "claim": f"{_operator_short(gold.get('operator'))} {gold.get('value') or ''} {gold.get('unit') or ''}".strip(),
                "applies_to": str(gold.get("applies_to") or ""),
                "status": status,
                "detail": detail,
            }
        )
    return rows


def city_comparison_rows(outputs_root: Path = OUTPUTS_ROOT) -> list[dict[str, Any]]:
    """One row per city x lane for the portfolio grid."""
    rows = []
    for output_dir in discover_city_output_dirs(outputs_root):
        native_lane = native_label_for_dir(output_dir) if native_run_root(output_dir) else None
        is_p9 = output_dir.name.endswith(P9_DIR_SUFFIX) or output_dir.name.endswith(f"{P9_DIR_SUFFIX}_v21")
        lane = native_lane or ("P9" if is_p9 else "P5")
        benchmark = _read_json(output_dir / "benchmark_report.json", {})
        summary = _read_json(output_dir / "slim_summary.json", {})
        metrics = benchmark.get("rule_metrics", {})
        rows.append(
            {
                "city": city_label_from_dir(output_dir).replace(" \u2014 Pipeline 9", ""),
                "lane": lane,
                "output_dir": str(output_dir),
                "candidates": summary.get("candidate_rule_count"),
                "verified": metrics.get("verified_rule_count"),
                "review": metrics.get("review_rule_count"),
                "precision": metrics.get("verified_precision"),
                "gold_recall": metrics.get("verified_gold_recall"),
                "false_verified": metrics.get("false_verified_count"),
                "gate_status": pipeline_gate_status(summary, benchmark),
            }
        )
    rows.sort(key=lambda row: (row["city"], row["lane"]))
    return rows


# Plotly defaults shared by every chart; a plain dict so tests can pin it
# without importing plotly. Charts degrade to the HTML bar rows when plotly
# is not installed — the dashboard keeps its runs-with-base-deps guarantee.
PLOTLY_LAYOUT = {
    "font": {"family": "Inter, -apple-system, sans-serif", "size": 13, "color": "#1f2328"},
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "colorway": ["#0969da", "#1a7f37", "#9a6700", "#cf222e", "#57606a", "#8250df"],
    "margin": {"l": 8, "r": 8, "t": 28, "b": 36},
    "xaxis": {"gridcolor": "#eef1f4", "zerolinecolor": "#d0d7de"},
    "yaxis": {"gridcolor": "#eef1f4", "zerolinecolor": "#d0d7de"},
    "hoverlabel": {"bgcolor": "#1f2328"},
    "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02},
}


def _themed_plotly(st: Any, figure_builder: Any) -> bool:
    """Render a plotly figure with the shared layout; False -> caller falls back."""
    try:
        import plotly.graph_objects as go  # noqa: F401
    except Exception:
        return False
    try:
        figure = figure_builder()
        figure.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
        return True
    except Exception as error:  # pragma: no cover - plotting failure is cosmetic
        st.caption(f"Chart unavailable: {error}")
        return False


def _funnel_view(st: Any, data: dict[str, Any]) -> None:
    """Where do candidates die? One funnel + the reasons at each gate."""
    stages = funnel_stages(data)
    st.markdown("#### Where candidates die")
    st.caption(
        "Each stage is a verification gate. Rules held for review are a parking "
        "lot, not a loss — they wait for evidence or a human, never auto-promote."
    )

    def _build():
        import plotly.graph_objects as go

        return go.Figure(
            go.Funnel(
                y=[row["label"] for row in stages],
                x=[row["count"] for row in stages],
                textinfo="value+percent initial",
                marker={"color": ["#0969da", "#218bff", "#54aeff", "#2da44e", "#1a7f37"]},
                connector={"line": {"color": "#d0d7de", "width": 1}},
            )
        )

    if not _themed_plotly(st, _build):
        for row in stages:
            share = row["count"] / max(stages[0]["count"], 1)
            st.markdown(
                f"<div class='bar-row'><span>{html.escape(row['label'])}</span>"
                f"<div class='bar-track'><div class='bar-fill' style='width:{share * 100:.1f}%'></div></div>"
                f"<b>{row['count']}</b></div>",
                unsafe_allow_html=True,
            )
    outflows = [row for row in stages if row["dropped"]]
    if outflows:
        columns = st.columns(len(outflows))
        for column, row in zip(columns, outflows):
            with column:
                status = "review" if row["outflow_status"] == "held" else row["outflow_status"]
                color = STATUS_COLORS.get(status, "#57606a")
                verb = "held for review" if row["outflow_status"] == "held" else row["outflow_status"].replace("_", " ")
                st.markdown(
                    f"<div class='guide-card'><b style='color:{color}'>{row['dropped']} {verb}</b>"
                    + "".join(
                        f"<span style='display:block'>{html.escape(reason)} ({count})</span>"
                        for reason, count in row["top_reasons"]
                    )
                    + "</div>",
                    unsafe_allow_html=True,
                )
    note = stages[0].get("note")
    if note:
        st.caption(note)


def filter_triage_items(
    items: list[dict[str, Any]],
    *,
    categories: list[str],
    priorities: list[str],
    likelihoods: list[str],
    rule_objects: list[str],
) -> list[dict[str, Any]]:
    """Apply dashboard filters to triage rows."""
    filtered = items
    if categories:
        filtered = [item for item in filtered if item.get("review_category") in categories]
    if priorities:
        filtered = [item for item in filtered if item.get("triage_priority") in priorities]
    if likelihoods:
        filtered = [item for item in filtered if item.get("likely_status") in likelihoods]
    if rule_objects:
        filtered = [item for item in filtered if item.get("rule_object") in rule_objects]
    return filtered


def compact_rule_row(rule: dict[str, Any]) -> dict[str, Any]:
    """Return one table row with the fields reviewers need first."""
    return {
        "Rule ID": rule.get("rule_id"),
        "Rule family": _plain_label(rule.get("rule_object")),
        "Scope": _plain_label(rule.get("constraint_scope")),
        "Applies to": _plain_label(rule.get("applies_to")),
        "Direction": _operator_short(rule.get("operator"), rule.get("constraint_type")),
        "Value": rule.get("value"),
        "Unit": rule.get("unit"),
        "Why review": _plain_label(rule.get("review_category")),
        "Urgency": _plain_label(rule.get("triage_priority") or rule.get("review_priority")),
        "Likely outcome": _plain_label(rule.get("likely_status")),
        "Score": rule.get("likely_correct_score"),
        "Missing proof": _plain_join(rule.get("support_gaps", [])[:4]),
    }


def _safety_chip_html(false_verified: int, gate_pass: bool) -> str:
    """Green chip when there are zero false verifies (the safety win); red ONLY
    when a false verify exists, so red stays meaningful (a failed recall gate is
    not a safety failure)."""
    if false_verified > 0:
        return f"<div class='safety-chip safety-alert'>Attention — {false_verified} false verifies</div>"
    suffix = " · quality gate passed" if gate_pass else ""
    return f"<div class='safety-chip safety-ok'>✓ Safe — 0 false verifies{suffix}</div>"


def _coverage_hero(st: Any, data: dict[str, Any], counts: dict[str, int]) -> None:
    slot_metrics = (data.get("slot_audit") or {}).get("slot_metrics") or {}
    coverage = slot_metrics.get("scored_verified_coverage")
    if coverage is None:
        st.markdown(
            "<div class='coverage-hero'><div><span class='pct'>"
            f"{counts.get('verified', 0)}</span> <span class='cap'>verified rules</span></div>"
            "<div class='cap'>Scored coverage is computed in an M5 measurement run; this view shows the "
            "verified rule count.</div></div>",
            unsafe_allow_html=True,
        )
        return
    denom = slot_metrics.get("distinct_scored_legal_slot_count") or 0
    verified = int(slot_metrics.get("scored_verified_slot_count") or 0)
    review = int(slot_metrics.get("scored_review_slot_count") or 0)
    missed = int(slot_metrics.get("scored_missed_slot_count") or 0)
    total = max(verified + review + missed, 1)
    segments = (
        f"<div class='seg seg-verified' style='width:{verified / total * 100:.1f}%'></div>"
        f"<div class='seg seg-review' style='width:{review / total * 100:.1f}%'></div>"
        f"<div class='seg seg-missed' style='width:{missed / total * 100:.1f}%'></div>"
    )
    st.markdown(
        "<div class='coverage-hero'>"
        f"<div><span class='pct'>{html.escape(str(_format_coverage(coverage)))}</span> "
        f"<span class='cap'>of {denom} distinct legal rules proven from source</span></div>"
        f"<div class='coverage-bar'>{segments}</div>"
        "<div class='coverage-key'>"
        f"<span><i style='background:var(--status-verified)'></i>Verified <b>{verified}</b></span>"
        f"<span><i style='background:var(--status-review)'></i>Review <b>{review}</b></span>"
        f"<span><i style='background:var(--status-not-used)'></i>Missed <b>{missed}</b></span>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _status_mix_bar(st: Any, counts: dict[str, int]) -> None:
    order = [("verified", "Verified"), ("review", "Review"), ("rejected", "Rejected"), ("not_used", "Not used")]
    total = max(sum(int(counts.get(key, 0)) for key, _ in order), 1)
    segments = ""
    for key, label in order:
        n = int(counts.get(key, 0))
        if n <= 0:
            continue
        pct = n / total * 100
        segments += (
            f"<div class='seg {key}' style='width:{pct:.2f}%' title='{label}: {n}'>"
            f"{n if pct > 7 else ''}</div>"
        )
    st.markdown(f"<div class='status-bar'>{segments}</div>", unsafe_allow_html=True)


def _rules_drilldown(st, data: dict[str, Any]) -> None:
    """Make every decision count explorable: one expander per bucket that opens
    the exact rules behind the number (rule id, family, direction, value, unit,
    section/page). Answers 'click Verified -> show me those rules.'"""
    buckets = [
        ("Verified", data.get("verified", [])),
        ("Needs review", data.get("review", [])),
        ("Rejected", data.get("rejected", [])),
        ("Not used", data.get("not_used", [])),
    ]
    if not any(rules for _, rules in buckets):
        return
    st.markdown("##### Browse the rules behind these numbers")
    st.caption("Open a bucket to see the exact rules it counts.")
    for label, rules in buckets:
        if not rules:
            continue
        with st.expander(f"{label} — {len(rules)} rule{'s' if len(rules) != 1 else ''}", expanded=False):
            st.dataframe(
                _display_rows([compact_rule_row(rule) for rule in rules]),
                width="stretch",
                hide_index=True,
            )


def _summary_tab(st: Any, data: dict[str, Any]) -> None:
    benchmark = data.get("benchmark", {})
    metrics = benchmark.get("rule_metrics", {})
    gates = benchmark.get("quality_gates", {})
    counts = output_bucket_counts(data)
    false_verified = int(metrics.get("false_verified_count", 0) or 0)
    st.markdown(_safety_chip_html(false_verified, bool(gates.get("passed"))), unsafe_allow_html=True)
    _coverage_hero(st, data, counts)

    slot_metrics = (data.get("slot_audit") or {}).get("slot_metrics") or {}
    coverage = slot_metrics.get("scored_verified_coverage")
    coverage_display = _format_coverage(coverage) if coverage is not None else "—"
    kpis = [
        ("Verified", counts.get("verified", 0), "verified", "proven against source text"),
        ("Needs review", counts.get("review", 0), "review", "never auto-approved"),
        ("Verified coverage", coverage_display, "verified", "of in-scope legal rules"),
        ("False verifies", false_verified, "verified" if false_verified == 0 else "rejected", "must stay at 0"),
    ]
    cards = "".join(
        f"<div class='metric metric-{tone}'><div class='metric-label'>{html.escape(label)}</div>"
        f"<div class='metric-value'>{html.escape(str(value))}</div>"
        f"<div style='font-size:11px;color:var(--ink-soft);margin-top:4px;'>{html.escape(sub)}</div></div>"
        for label, value, tone, sub in kpis
    )
    st.caption("Each tile below is also explorable — open a bucket under the bar to see its exact rules.")
    st.markdown(f"<div class='metric-grid'>{cards}</div>", unsafe_allow_html=True)
    _status_mix_bar(st, counts)
    _rules_drilldown(st, data)
    _action_summary(st, data)
    with st.expander("How rules flow through the verifier", expanded=False):
        _funnel_view(st, data)
    with st.expander("How we got these numbers", expanded=False):
        _count_audit_panel(st, data)
        _not_used_explanation(st, data)


def _review_queue_tab(st: Any, data: dict[str, Any], output_dir: Path, triage_items: list[dict[str, Any]]) -> None:
    st.caption("Rules the verifier could not prove — your worklist. Filtering here never changes a decision.")
    columns = st.columns(4)
    with columns[0]:
        categories = st.multiselect("Why it needs review", _unique(triage_items, "review_category"), format_func=_plain_label)
    with columns[1]:
        priorities = st.multiselect("Urgency", _unique(triage_items, "triage_priority"), format_func=_plain_label)
    with columns[2]:
        likelihoods = st.multiselect("Likely outcome", _unique(triage_items, "likely_status"), format_func=_plain_label)
    with columns[3]:
        rule_objects = st.multiselect("Rule family", _unique(triage_items, "rule_object"), format_func=_plain_label)
    filtered_items = filter_triage_items(
        triage_items,
        categories=categories,
        priorities=priorities,
        likelihoods=likelihoods,
        rule_objects=rule_objects,
    )
    evidence_by_id = {str(unit.get("evidence_id")): unit for unit in data["evidence_units"]}
    queue_tabs = st.tabs(["Queue summary", "Review one rule", "Compare with verified"])
    with queue_tabs[0]:
        _review_router_tab(st, data["router"])
    with queue_tabs[1]:
        _review_assistant_tab(st, data["review_assistant_packets"], data["review"], output_dir, evidence_by_id)
    with queue_tabs[2]:
        _candidate_compare_tab(st, filtered_items, data["review"], data["verified"], output_dir, evidence_by_id)


def _gis_handoff_tab(st: Any, data: dict[str, Any], output_dir: Path) -> None:
    felt = _read_json(output_dir / "gis_felt_export.json", {})
    contract_path = output_dir / "gis_rule_contract.json"
    felt_path = output_dir / "gis_felt_export.json"
    constraints = felt.get("constraints", []) if isinstance(felt, dict) else []
    if not constraints and not contract_path.exists():
        st.info(
            "No GIS export for this run yet. The verified-only GIS contract and felt export are written "
            "next to the verified rules when the pipeline runs."
        )
        return
    export_counts = felt.get("export_counts", {}) if isinstance(felt, dict) else {}
    ready = sum(1 for constraint in constraints if constraint.get("gis_ready"))
    st.caption(
        "Verified-only, deduplicated, geometry-tagged rules ready for the map. "
        "These are the only rules that should drive GIS."
    )
    cards = [
        ("Verified rules", export_counts.get("verified_rule_count", len(constraints)), "verified", "source-supported"),
        ("GIS constraints", export_counts.get("gis_constraint_count", len(constraints)), "verified", "deduplicated for the map"),
        ("Map-ready", ready, "verified", "drawable: number + geometry"),
    ]
    html_cards = "".join(
        f"<div class='metric metric-{tone}'><div class='metric-label'>{html.escape(label)}</div>"
        f"<div class='metric-value'>{html.escape(str(value))}</div>"
        f"<div style='font-size:11px;color:var(--ink-soft);margin-top:4px;'>{html.escape(sub)}</div></div>"
        for label, value, tone, sub in cards
    )
    st.markdown(f"<div class='metric-grid'>{html_cards}</div>", unsafe_allow_html=True)
    rows = [
        {
            "rule": constraint.get("rule_object"),
            "constraint": " ".join(
                str(part) for part in (constraint.get("operator"), constraint.get("value"), constraint.get("unit")) if part
            ),
            "geometry": constraint.get("geometry_target") or "—",
            "map-ready": "yes" if constraint.get("gis_ready") else "no",
            "page": constraint.get("source_page"),
            "plain English": _short_display_quote(constraint.get("felt_popup_sentence") or "", 140),
        }
        for constraint in constraints
    ]
    if rows:
        st.markdown("#### Verified GIS constraints")
        st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    download_columns = st.columns(2)
    if contract_path.exists():
        download_columns[0].download_button(
            "Download gis_rule_contract.json",
            contract_path.read_text(encoding="utf-8"),
            file_name="gis_rule_contract.json",
            mime="application/json",
        )
    if felt_path.exists():
        download_columns[1].download_button(
            "Download gis_felt_export.json",
            felt_path.read_text(encoding="utf-8"),
            file_name="gis_felt_export.json",
            mime="application/json",
        )


def _sidebar_status_legend(st: Any) -> None:
    st.sidebar.markdown(
        "<div style='display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 2px;'>"
        "<span class='status-pill status-verified'>Verified</span>"
        "<span class='status-pill status-review'>Review</span>"
        "<span class='status-pill status-rejected'>Rejected</span>"
        "<span class='status-pill status-not_used'>Not used</span>"
        "</div>",
        unsafe_allow_html=True,
    )


_ADVANCED_VIEWS = (
    "(none)",
    "Coverage vs gold",
    "Pipeline comparison",
    "Evidence repair",
    "Shadow reruns",
    "Engineering details",
)


def _sidebar_advanced(st: Any) -> str:
    with st.sidebar.expander("Advanced & diagnostics", expanded=False):
        return st.radio(
            "Engineering view",
            _ADVANCED_VIEWS,
            key="adv_view",
            help="Diagnostic artifacts for engineers; not part of the reviewer workflow. Renders below the tabs.",
        )


def _render_advanced_view(st: Any, view: str, data: dict[str, Any], output_dir: Path) -> None:
    if view == "Coverage vs gold":
        _coverage_tab(st, data, output_dir)
    elif view == "Pipeline comparison":
        _pipeline_comparison_tab(st, output_dir)
    elif view == "Evidence repair":
        _repair_tab(st, data["repair"])
    elif view == "Shadow reruns":
        _rerun_tab(st, data["rerun"], data["evidence_units"])
    elif view == "Engineering details":
        _advanced_tab(st, data, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args, _ = parser.parse_known_args()
    cli_output_dir = Path(args.output_dir).expanduser().resolve()

    try:
        import streamlit as st
    except ModuleNotFoundError as exc:
        raise SystemExit("Streamlit is not installed. Run `pip install -r requirements.txt`.") from exc

    st.set_page_config(
        page_title="BC Zoning Verification Dashboard",
        page_icon="BV",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _style(st)

    # City selector: scan outputs/ for any *_slim_pipeline5_registry dir with
    # verified_rules.json. New cities appear automatically; nothing is hardcoded.
    city_dirs = discover_product_output_dirs()
    if (
        cli_output_dir.is_dir()
        and cli_output_dir not in city_dirs
        and native_run_root(cli_output_dir) in PRODUCT_RUN_ROOTS
    ):
        city_dirs = [*city_dirs, cli_output_dir]
    if not city_dirs:
        st.error(f"No verifier output directories found under `{OUTPUTS_ROOT}`.")
        return
    st.sidebar.header("Dataset")
    PORTFOLIO = "__portfolio__"
    selection = st.sidebar.selectbox(
        "View",
        [PORTFOLIO, *city_dirs],
        index=0,
        format_func=lambda item: "Start here \u2014 current M7 overview" if item == PORTFOLIO else city_label_from_dir(item),
        help=(
            "Start with the current M7 overview. Pick a city for drilldown. "
            "Only current M7 and its V3 predecessor are shown here."
        ),
    )
    if selection == PORTFOLIO:
        _render_header(st, "Current M7 Verification Status", portfolio=True)
        _portfolio_page(st)
        return
    output_dir = selection
    city_key = city_key_from_dir(output_dir)
    city_label = city_label_from_dir(output_dir)

    data = load_output_data(output_dir)
    source_url = source_document_url_for_output(output_dir, data)
    _ACTIVE_SOURCE["url"] = source_url
    _ACTIVE_SOURCE["label"] = f"{city_label} bylaw PDF"

    # Reviewer queue source (filters now live inline on the Review Queue tab).
    triage_items = data["review"]

    # Lean sidebar: the dataset selector lives above; everything heavier than a
    # glance is one collapsed door away.
    st.sidebar.caption(f"Loaded: {output_dir.name}")
    _sidebar_status_legend(st)
    advanced_view = _sidebar_advanced(st)
    _sidebar_guidance(st)
    st.sidebar.markdown(
        "<div class='trust-note' style='margin-top:10px;font-size:12px;'>Read-only · advisory. "
        f"<a href='{html.escape(source_url)}' target='_blank'>Source bylaw PDF</a></div>",
        unsafe_allow_html=True,
    )

    _render_header(st, city_label)

    # Civic Console: the three questions a user asks, plus the conversation.
    sections = st.tabs(["Summary", "Review Queue", "GIS Handoff", "Ask the Bylaw"])
    with sections[0]:
        _summary_tab(st, data)
    with sections[1]:
        _review_queue_tab(st, data, output_dir, triage_items)
    with sections[2]:
        _gis_handoff_tab(st, data, output_dir)
    with sections[3]:
        _bylaw_tab(st, data)

    if advanced_view and advanced_view != "(none)":
        st.divider()
        st.caption("Advanced & diagnostics (selected from the sidebar) — engineering detail, not part of the reviewer workflow.")
        _render_advanced_view(st, advanced_view, data, output_dir)


def count_audit_status(slot_audit: dict[str, Any]) -> str:
    metrics = (slot_audit or {}).get("slot_metrics") or {}
    if not metrics:
        return "not available"
    unsupported = int(metrics.get("unsupported_verified_rule_count") or 0)
    unresolved_duplicates = int(metrics.get("duplicate_verified_slot_count") or 0)
    mapping_rate = float(metrics.get("verified_slot_mapping_rate") or 0)
    if unsupported or unresolved_duplicates or mapping_rate < 1.0:
        return "too much risk"
    review = int(metrics.get("scored_review_slot_count", metrics.get("review_slot_count")) or 0)
    missed = int(metrics.get("scored_missed_slot_count", metrics.get("missed_slot_count")) or 0)
    if review or missed:
        return "safe but conservative"
    return "balanced"


def _format_coverage(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return f"{round(float(value) * 100)}%"
    return value


def count_audit_summary_rows(slot_audit: dict[str, Any], reconciliation: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    metrics = (slot_audit or {}).get("slot_metrics") or {}
    reconciliation = reconciliation or {}
    if not metrics:
        return []
    safety_and_delta = [
        {"metric": "Duplicate merged", "value": metrics.get("duplicate_merged_count"), "meaning": "not counted twice"},
        {"metric": "Unsupported verified", "value": metrics.get("unsupported_verified_rule_count"), "meaning": "must be zero"},
        {
            "metric": "Verified slot delta from M4",
            "value": reconciliation.get("effective_verified_slot_count_delta"),
            "meaning": "unique verified-slot change",
        },
    ]
    # M5.6: lead with the scored denominator (in-contract, recognized-family,
    # corpus-derived, deduped to distinct legal rules). The raw ledger stays
    # visible but is labelled an advisory over-count ceiling, not a legal total.
    if metrics.get("distinct_scored_legal_slot_count") is not None:
        return [
            {"metric": "Scored legal slots", "value": metrics.get("distinct_scored_legal_slot_count"), "meaning": "in-contract distinct legal rules (honest denominator)"},
            {"metric": "Verified coverage", "value": _format_coverage(metrics.get("scored_verified_coverage")), "meaning": "scored slots that are verified"},
            {"metric": "Scored verified", "value": metrics.get("scored_verified_slot_count"), "meaning": "distinct legal rules proven"},
            {"metric": "Scored review-only", "value": metrics.get("scored_review_slot_count"), "meaning": "safe, awaiting proof"},
            {"metric": "Scored missed", "value": metrics.get("scored_missed_slot_count"), "meaning": "actionable backlog"},
            {"metric": "Raw rule slots (advisory)", "value": metrics.get("total_rule_slots"), "meaning": "loose over-count ceiling, not a legal total"},
            {"metric": "Unique verified slots", "value": metrics.get("effective_verified_slot_count"), "meaning": "deduplicated verifier output"},
            *safety_and_delta,
        ]
    return [
        {"metric": "Rule slots", "value": metrics.get("total_rule_slots"), "meaning": "source-derived denominator"},
        {"metric": "Raw verified rules", "value": metrics.get("verified_rule_count"), "meaning": "verifier output rows"},
        {"metric": "Unique verified slots", "value": metrics.get("effective_verified_slot_count"), "meaning": "deduplicated count"},
        {"metric": "Review slots", "value": metrics.get("review_slot_count"), "meaning": "safe but not fully proven"},
        {"metric": "Candidate-only slots", "value": metrics.get("candidate_only_slot_count"), "meaning": "extracted but not proven"},
        {"metric": "Missed slots", "value": metrics.get("missed_slot_count"), "meaning": "no mapped candidate yet"},
        *safety_and_delta,
    ]


def _count_audit_panel(st: Any, data: dict[str, Any]) -> None:
    slot_audit = data.get("slot_audit") or {}
    rows = count_audit_summary_rows(slot_audit, data.get("m55_reconciliation") or {})
    if not rows:
        st.info("M6 slot audit not found for this output. Run the measurement layer to answer too much vs too little precisely.")
        return
    status = count_audit_status(slot_audit)
    st.markdown("#### Too Much / Too Little")
    st.caption(
        "This panel leads with the M6 scored legal denominator and keeps raw slots as an advisory over-count. "
        "Unsupported verified rules mean too much; scored review or missed slots mean conservative coverage."
    )
    st.markdown(f"<div class='trust-note'><b>Count status:</b> {html.escape(_plain_label(status))}</div>", unsafe_allow_html=True)
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)


def _not_used_explanation(st: Any, data: dict[str, Any]) -> None:
    not_used = data.get("not_used") or []
    if not not_used:
        return
    reason_counts = Counter(
        str(gap)
        for rule in not_used
        for gap in (rule.get("support_gaps") or [])
    )
    family_counts = Counter(str(rule.get("rule_object") or "unknown") for rule in not_used)
    if reason_counts.get("outside_target_section"):
        explanation = (
            "These candidates came from the full bylaw but outside the configured target sections. "
            "They are kept for audit and review, not trusted as verified rules."
        )
    else:
        explanation = "These candidates are retained for traceability but are outside the current verified-rule output contract."
    st.markdown("#### Out-of-scope candidates")
    st.caption(explanation)
    rows = [
        {"type": "Reason", "name": _plain_label(name), "count": count}
        for name, count in reason_counts.most_common(6)
    ] + [
        {"type": "Rule family", "name": _plain_label(name), "count": count}
        for name, count in family_counts.most_common(6)
    ]
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)


def _advanced_tab(st: Any, data: dict[str, Any], output_dir: Path) -> None:
    st.subheader("Advanced Diagnostics")
    st.caption("Engineering and audit views. These explain why the system behaved a certain way; they do not approve rules.")
    diagnostic = st.selectbox(
        "Diagnostic view",
        [
            "Rule Graph",
            "Review Resolution",
            "Semantic Review",
            "Evidence Intelligence",
            "Evidence Bundle Rerun",
            "Safe Verifier Tuning",
            "Run Cost & Source",
            "Shadow Examiner",
            "Verification Structure",
            "Extraction Preflight",
        ],
        help="Keep this section for debugging, tuning, and audit. The main review workflow is in Review Workbench.",
    )
    if diagnostic == "Rule Graph":
        _rule_graph_tab(st, data["rule_graph"])
    elif diagnostic == "Review Resolution":
        _review_resolution_tab(st, data["resolution"])
    elif diagnostic == "Semantic Review":
        _semantic_review_tab(st, data["semantic"])
    elif diagnostic == "Evidence Intelligence":
        _evidence_intelligence_tab(st, data["intelligence"])
    elif diagnostic == "Evidence Bundle Rerun":
        _bundle_rerun_tab(st, data["bundle_rerun"])
    elif diagnostic == "Safe Verifier Tuning":
        _safe_tuning_tab(st, data["safe_tuning"], data["evidence_units"])
    elif diagnostic == "Run Cost & Source":
        _run_cost_source_tab(st, data)
    elif diagnostic == "Shadow Examiner":
        _shadow_examiner_tab(st, data)
    elif diagnostic == "Verification Structure":
        _structure_tab(st)
    elif diagnostic == "Extraction Preflight":
        _preflight_tab(st, data["preflight"])


def pipeline_comparison_rows(output_dir: Path) -> list[dict[str, Any]]:
    """Return native and legacy comparison rows for the selected city stem."""
    stem = city_stem_from_dir(output_dir)
    candidates = [
        ("Native M7", OUTPUTS_ROOT / "m7_runs" / stem / "google_gemini_2_5_flash_lite"),
        ("Native V3", OUTPUTS_ROOT / "v3_runs" / stem / "google_gemini_2_5_flash_lite"),
    ]
    rows: list[dict[str, Any]] = []
    for label, path in candidates:
        if not path.exists():
            continue
        summary = _read_json(path / "slim_summary.json", {})
        benchmark = _read_json(path / "benchmark_report.json", {})
        metrics = benchmark.get("rule_metrics", {})
        cost = _read_json(path / "model_cost_report.json", {})
        gates = benchmark.get("quality_gates", {})
        status = pipeline_gate_status(summary, benchmark)
        rows.append(
            {
                "pipeline": label,
                "path": path.name,
                "candidates": summary.get("candidate_rule_count"),
                "evidence_blocks": summary.get("evidence_unit_count"),
                "verified": summary.get("verified_rule_count"),
                "review": summary.get("review_rule_count"),
                "rejected": summary.get("rejected_rule_count"),
                "not_used": summary.get("not_used_rule_count"),
                "precision": metrics.get("verified_precision"),
                "false_verified": metrics.get("false_verified_count"),
                "verified_or_review_recall": metrics.get("verified_or_review_recall"),
                "estimated_cost": cost.get("estimated_cost_usd"),
                "gate_status": status,
                "status_meaning": HELP_TEXT.get("native_m7" if label == "Native M7" else status, HELP_TEXT.get(status, "")),
            }
        )
    return rows


def pipeline_gate_status(summary: dict[str, Any], benchmark: dict[str, Any]) -> str:
    """Human label for benchmark state; keeps P9 failures honest."""
    if not summary:
        return "missing"
    quality = benchmark.get("quality_gates", {})
    if quality.get("passed") is True:
        return "pass"
    metrics = benchmark.get("rule_metrics", {})
    proposal = benchmark.get("proposal_metrics", {})
    false_verified = int(metrics.get("false_verified_count") or 0)
    false_approval = int(proposal.get("false_approval_count") or metrics.get("false_approval_count") or 0)
    candidates = int(summary.get("candidate_rule_count") or 0)
    verified = int(summary.get("verified_rule_count") or 0)
    review = int(summary.get("review_rule_count") or 0)
    rejected = int(summary.get("rejected_rule_count") or 0)
    not_used = int(summary.get("not_used_rule_count") or 0)
    if false_verified or false_approval:
        return "unsafe / needs fix"
    if verified == 0 and review:
        return "fail-closed"
    if candidates and not_used >= max(1, verified + review + rejected):
        return "scope mismatch"
    return "needs review"


def _pipeline_comparison_tab(st: Any, output_dir: Path) -> None:
    st.subheader("Pipeline Comparison")
    st.caption(
        "M4 is current. V3 is the direct predecessor M4 was built from. "
        "Recall is benchmark recall, not full-bylaw completeness."
    )
    rows = pipeline_comparison_rows(output_dir)
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)


def _run_cost_source_tab(st: Any, data: dict[str, Any]) -> None:
    st.subheader("Run Cost & Source")
    st.caption("Source, retrieval, and cost artifacts are advisory/debug records. The verifier JSON files remain authoritative.")
    source = data.get("source_summary") or {}
    cost = data.get("model_cost") or {}
    if not source and not cost:
        st.info("No source or model-cost artifact found for this output.")
        return
    left, right = st.columns(2)
    with left:
        st.markdown("#### Full-bylaw source cache")
        m4_source = source.get("m4_source_corpus") or {}
        m4_manifest = _read_json(Path(m4_source.get("path") or "") / "manifest.json", {})
        rows = [
            {"metric": "Full PDF pages", "value": m4_manifest.get("page_count")},
            {"metric": "Source chunks", "value": source.get("source_chunk_count")},
            {"metric": "Evidence packs", "value": source.get("evidence_pack_count")},
            {"metric": "Pages with chunks", "value": source.get("page_count")},
            {"metric": "Last page", "value": source.get("last_page")},
            {"metric": "Rule-like numeric clauses", "value": m4_source.get("rule_like_numeric_clause_count")},
            {"metric": "Selected rule-like coverage", "value": m4_source.get("selected_rule_like_numeric_coverage")},
            {"metric": "Discovery version", "value": source.get("discovery_version")},
        ]
        st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
        if source.get("lane_counts"):
            st.markdown("#### Pack lanes")
            _bar_rows(st, source.get("lane_counts", []), "name", "count")
    with right:
        st.markdown("#### Model run cost")
        rows = [
            {"metric": "Model", "value": cost.get("model")},
            {"metric": "Estimated cost", "value": cost.get("estimated_cost_usd")},
            {"metric": "Latency ms", "value": cost.get("latency_ms")},
            {"metric": "Input tokens", "value": cost.get("estimated_input_tokens")},
            {"metric": "Output tokens", "value": cost.get("estimated_output_tokens")},
            {"metric": "Cache hits", "value": cost.get("cache_hit_count")},
            {"metric": "Extraction errors", "value": cost.get("extraction_error_count")},
        ]
        st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
        st.caption(cost.get("pricing_note") or "Cost estimates are advisory.")


def _shadow_examiner_tab(st: Any, data: dict[str, Any]) -> None:
    st.subheader("Shadow Examiner")
    st.caption("Private developer diagnostics. These findings cannot verify, reject, or approve rules.")
    examiner = data.get("examiner") or {}
    if not examiner:
        st.info("No shadow examiner report found for this output.")
        return
    summary = examiner.get("summary", {})
    st.table(
        _display_rows(
            [
                {"metric": "Mode", "value": examiner.get("mode")},
                {"metric": "Model", "value": examiner.get("model")},
                {"metric": "Findings", "value": summary.get("finding_count")},
                {"metric": "False verified", "value": summary.get("false_verified_count")},
                {"metric": "Verified or review recall", "value": summary.get("verified_or_review_recall")},
            ]
        )
    )
    findings = examiner.get("findings", [])
    if findings:
        st.markdown("#### Findings")
        st.dataframe(
            _display_rows(
                [
                    {
                        "severity": item.get("severity"),
                        "category": item.get("category"),
                        "claim": item.get("claim"),
                        "suggested_test": item.get("suggested_test"),
                    }
                    for item in findings
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        selected = st.selectbox("Finding detail", [item.get("finding_id") for item in findings])
        item = next((row for row in findings if row.get("finding_id") == selected), findings[0])
        st.markdown("#### Evidence")
        st.code(str(item.get("evidence") or ""), language="text")
        st.markdown("#### Suggestion")
        st.write(item.get("suggestion") or "")
    rerun = data.get("examiner_rerun") or {}
    if rerun.get("actions"):
        st.markdown("#### Suggested reruns")
        st.dataframe(_display_rows(rerun.get("actions", [])), width="stretch", hide_index=True)


def _packet_by_rule_id(packet_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("rule_id") or ""): item for item in packet_report.get("items", [])}


def _review_assistant_tab(
    st: Any,
    packet_report: dict[str, Any],
    review_rules: list[dict[str, Any]],
    output_dir: Path,
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    st.subheader("Review One Rule")
    st.caption(
        "Pick a held rule, inspect the source evidence, and ask an optional LLM for an explanation. The LLM cannot approve anything."
    )
    packet_by_rule = _packet_by_rule_id(packet_report)
    if not review_rules:
        st.info("No review-needed rules in this output.")
        return
    options = [str(rule.get("rule_id")) for rule in review_rules if rule.get("rule_id")]
    rule_lookup = {str(rule.get("rule_id")): rule for rule in review_rules if rule.get("rule_id")}
    selected_id = st.selectbox(
        "Rule to inspect",
        options,
        key=f"assistant_rule_{output_dir.name}",
        format_func=lambda rule_id: _rule_option_label(rule_lookup.get(str(rule_id), {})),
        help="These are candidates the verifier refused to prove. Pick one to inspect its evidence and missing support.",
    )
    rule = _by_rule_id(review_rules, selected_id)
    packet = packet_by_rule.get(selected_id, {})
    if not packet:
        st.warning("No prebuilt review assistant packet found. Rerun the slim verifier to generate review_assistant_packets.json.")
        packet = _fallback_packet(rule)

    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### Candidate")
        st.table([compact_rule_row(rule)])
        st.markdown("#### Why this needs review")
        st.write(_list_text(rule.get("support_gaps", [])))
        st.info(packet.get("suggested_next_action") or "Inspect the source evidence before any verifier rerun.")
    with right:
        source = packet.get("source", {})
        st.markdown("#### Source evidence")
        st.caption(
            f"Page {source.get('page') or 'unknown'} · evidence `{source.get('evidence_id') or ''}` · "
            f"context status: {_plain_label(source.get('repair_status') or 'unknown')}"
        )
        st.markdown("*Extractor evidence*")
        st.code(source.get("original_evidence") or _source_text(rule), language="text")
        st.markdown("*Source context added before verification*")
        repaired = source.get("repaired_context")
        if repaired:
            st.code(repaired, language="text")
        else:
            st.caption("No repaired context available.")

    _legal_context_expander(st, output_dir, rule, evidence_by_id)

    st.markdown("#### Ask for an explanation")
    question = st.text_input(
        "Reviewer question",
        key=f"assistant_q_{output_dir.name}_{selected_id}",
        placeholder="e.g. why is the operator missing, or what evidence would repair this?",
    )
    prompt = _assistant_prompt(packet, question)
    with st.expander("Prompt sent to optional LLM"):
        st.code(prompt, language="text")
    if question:
        answer = _optional_llm_review_answer(prompt)
        if answer:
            st.markdown("#### LLM Draft")
            st.write(answer)
            st.caption("Draft only. Any proposed repair must be rerun through the deterministic verifier.")
        else:
            st.info("No LLM key/client available. Use the bounded context above with a reviewer or keep using retrieval-only review.")


def _fallback_packet(rule: dict[str, Any]) -> dict[str, Any]:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    return {
        "rule_id": rule.get("rule_id"),
        "candidate_rule": compact_rule_row(rule),
        "support_gaps": list(rule.get("support_gaps", [])),
        "suggested_next_action": "Inspect the source evidence and rerun deterministic verification only after evidence is repaired.",
        "source": {
            "page": source.get("page"),
            "evidence_id": source.get("evidence_id"),
            "original_evidence": source.get("evidence_text"),
            "repaired_context": source.get("source_context"),
            "repair_status": "fallback",
        },
    }


def proof_trace_lines(rule: dict[str, Any], limit_per_field: int = 140) -> list[str]:
    """Per-field proof labels as short lines for the assistant prompt.

    The assistant previously saw only the rule JSON + gap codes; the proof
    trace is the verifier's actual reasoning ("operator: not_enough_info —
    'the proposed operator is not supported…'") and is what a reviewer needs
    to answer "why is this in review?".
    """
    trace = rule.get("proof_trace") or rule.get("merged_proof_trace") or {}
    lines: list[str] = []
    for claim, item in trace.items():
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        reason = str(item.get("reason") or "")[:limit_per_field]
        if label and label != "supported":
            lines.append(f"{claim}: {label} \u2014 {reason}")
    return lines[:8]


def suggested_review_questions(packet: dict[str, Any]) -> list[str]:
    """Gap-aware question chips for the review assistant."""
    questions = ["Why is this rule in review?"]
    by_gap = {
        "operator_not_supported": "What wording would prove the direction (minimum/maximum)?",
        "applies_to_not_supported": "What nearby text would prove what this applies to?",
        "table_condition_not_supported": "Which condition is the table column carrying?",
        "conditional_cell_condition_missing": "What lot-size branch does this value belong to?",
        "column_qualifier_not_claimed": "What column qualifier is this claim missing?",
        "unresolved_exception_cue": "What exception wording is unresolved here?",
        "pipeline5_text_candidate_requires_review": "What second source would corroborate this rule?",
        "rule_family_direction_mismatch": "Is this bound in the wrong direction for its family?",
    }
    for gap in packet.get("support_gaps") or []:
        question = by_gap.get(str(gap))
        if question and question not in questions:
            questions.append(question)
    return questions[:4]


def _assistant_prompt(packet: dict[str, Any], question: str) -> str:
    context = packet.get("llm_context") or {
        "instruction": "Advisory only. Do not approve or verify.",
        "rule": packet.get("candidate_rule", {}),
        "support_gaps": packet.get("support_gaps", []),
        "original_evidence": (packet.get("source") or {}).get("original_evidence"),
        "repaired_context": (packet.get("source") or {}).get("repaired_context"),
        "suggested_next_action": packet.get("suggested_next_action"),
    }
    trace_lines = proof_trace_lines(packet.get("candidate_rule") or packet)
    proof_block = ("Proof trace (unproven fields):\n" + "\n".join(trace_lines) + "\n") if trace_lines else ""
    return (
        f"{context.get('instruction')}\n\n"
        f"Rule: {json.dumps(context.get('rule', {}), ensure_ascii=False)}\n"
        f"Support gaps: {', '.join(str(gap) for gap in context.get('support_gaps', [])) or 'none'}\n"
        f"{proof_block}"
        f"Original evidence: {context.get('original_evidence') or ''}\n"
        f"Repaired context: {context.get('repaired_context') or ''}\n"
        f"Suggested next action: {context.get('suggested_next_action') or ''}\n\n"
        f"Reviewer question: {question or 'Explain why this item is still in review.'}\n\n"
        "Answer briefly. Cite only the evidence above. Do not say this rule is approved or verified."
    )


def _optional_llm_review_answer(prompt: str) -> str | None:
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        return None
    try:  # pragma: no cover - optional interactive network path
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-opus-4-8"),
            max_tokens=700,
            system="You are an advisory zoning review assistant. Never approve or verify rules.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
    except Exception as error:
        return f"LLM unavailable: {type(error).__name__}: {error}"


def _evidence_intelligence_tab(st: Any, report: dict[str, Any]) -> None:
    items = report.get("items", [])
    st.subheader("Evidence Intelligence")
    st.caption("Rule-centric evidence ranking and bundle suggestions. This page does not verify rules.")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Review Rules", report.get("review_rule_count", len(items)))
    metric_cols[1].metric("Evidence Indexed", report.get("evidence_index_count", 0))
    metric_cols[2].metric("Safe Bundle Retry", report.get("safe_retry_count", 0))
    metric_cols[3].metric("Blocked", report.get("blocked_count", 0))

    summary = report.get("summary", {})
    left, right = st.columns(2)
    with left:
        st.markdown("### Next Actions")
        _bar_rows(st, summary.get("next_action_counts", []), "name", "count")
    with right:
        st.markdown("### Missing Fields")
        _bar_rows(st, summary.get("missing_field_counts", []), "name", "count")

    if not items:
        st.info("No evidence intelligence output found. Rerun the slim verifier.")
        return
    only_safe = st.checkbox("Show safe bundle retry only")
    visible = [item for item in items if item.get("safe_retry")] if only_safe else items
    rows = [
        {
            "rule_id": item.get("rule_id"),
            "safe_retry": item.get("safe_retry"),
            "score": item.get("bundle_score"),
            "next_action": item.get("next_action"),
            "rule_object": item.get("rule_object"),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "missing_fields": ", ".join(item.get("bundle_missing_fields", [])),
            "blocked_by": ", ".join(item.get("blocked_by", [])),
        }
        for item in visible[:250]
    ]
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    if visible:
        selected = st.selectbox("Evidence intelligence detail", [item["rule_id"] for item in visible])
        item = next(candidate for candidate in visible if candidate["rule_id"] == selected)
        _detail_sentence_panel(
            st,
            "Evidence intelligence in plain English",
            _intelligence_detail_sentences(item),
            _bundle_display_evidence(item),
            item,
        )
        st.markdown("#### Best Evidence Bundle")
        st.dataframe(_display_rows(_bundle_rows(item)), width="stretch", hide_index=True)
        with st.expander("Raw evidence intelligence JSON"):
            st.json(item)


def _review_router_tab(st: Any, report: dict[str, Any]) -> None:
    items = report.get("items", [])
    st.subheader("Queue Summary")
    st.caption("A plain-language worklist for the rules still in review. These labels guide reviewers; they do not approve rules.")
    summary = report.get("summary", {})
    left, middle, right = st.columns(3)
    with left:
        st.markdown("#### Suggested work")
        _bar_rows(st, summary.get("action_counts", []), "name", "count")
    with middle:
        st.markdown("#### Why held")
        _bar_rows(st, summary.get("category_counts", []), "name", "count")
    with right:
        st.markdown("#### Meaning check")
        _bar_rows(st, summary.get("semantic_review_counts", []), "name", "count")

    if not items:
        st.info("No review router output found. Rerun the slim verifier.")
        return
    actions = st.multiselect("Suggested work", _unique(items, "action_bucket"), format_func=_plain_label)
    categories = st.multiselect("Why held", _unique(items, "review_category"), format_func=_plain_label)
    semantic_classes = st.multiselect("Meaning check", _unique(items, "semantic_review_class"), format_func=_plain_label)
    visible = items
    if actions:
        visible = [item for item in visible if item.get("action_bucket") in actions]
    if categories:
        visible = [item for item in visible if item.get("review_category") in categories]
    if semantic_classes:
        visible = [item for item in visible if item.get("semantic_review_class") in semantic_classes]
    rows = [
        {
            "Rule ID": item.get("rule_id"),
            "Why held": item.get("review_category"),
            "Suggested work": item.get("action_bucket"),
            "Explanation": HELP_TEXT.get(str(item.get("action_bucket") or ""), ""),
            "Urgency": item.get("priority"),
            "Rule family": item.get("rule_object"),
            "Meaning check": item.get("semantic_review_class"),
            "Meaning score": item.get("semantic_score"),
            "Closest verified rule": item.get("semantic_verified_rule_id"),
            "Still missing": ", ".join(item.get("semantic_guardrail_blockers", [])),
            "Evidence bundle safe": item.get("bundle_safe_retry"),
            "Bundle ready": item.get("bundle_rerun_promotion_ready"),
            "Next step": item.get("next_step"),
        }
        for item in visible[:250]
    ]
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    if visible:
        selected = st.selectbox(
            "Queue item detail",
            [item["rule_id"] for item in visible],
            format_func=lambda rule_id: _rule_option_label(next((item for item in visible if item.get("rule_id") == rule_id), {})),
        )
        item = next(candidate for candidate in visible if candidate["rule_id"] == selected)
        _detail_sentence_panel(
            st,
            "Review route in plain English",
            _router_detail_sentences(item),
            {"evidence_quote": item.get("evidence_sentence")},
            item,
        )
        with st.expander("Raw route JSON"):
            st.json(item)


def _review_resolution_tab(st: Any, report: dict[str, Any]) -> None:
    """Show final reviewer-facing resolution labels for remaining review items."""
    items = report.get("items", [])
    st.subheader("Review Resolution")
    st.caption(
        "Final operating labels for the remaining review queue. This page tells a reviewer what kind of work is left; it does not promote rules."
    )
    summary = report.get("summary", {})
    metric_cols = st.columns(4)
    metric_cols[0].metric("Review Rules", report.get("review_rule_count", len(items)))
    metric_cols[1].metric("Evidence-Fix Candidates", summary.get("can_promote_after_evidence_fix_count", 0))
    metric_cols[2].metric("Semantic Duplicates", summary.get("duplicate_or_degraded_count", 0))
    metric_cols[3].metric("Promotable Now", summary.get("promotable_now_count", 0))

    left, right = st.columns(2)
    with left:
        st.markdown("### Resolution Buckets")
        _bar_rows(st, summary.get("resolution_counts", []), "name", "count")
    with right:
        st.markdown("### Next Step Types")
        _bar_rows(st, summary.get("next_step_type_counts", []), "name", "count")

    recommendations = summary.get("recommendations", [])
    if recommendations:
        st.markdown("### Recommended Workflow")
        for item in recommendations:
            st.markdown(f"- {item}")

    if not items:
        st.info("No review resolution output found. Rerun the slim verifier.")
        return
    buckets = st.multiselect("Resolution", _unique(items, "resolution"), format_func=_plain_label)
    next_steps = st.multiselect("Next step type", _unique(items, "next_step_type"), format_func=_plain_label)
    visible = items
    if buckets:
        visible = [item for item in visible if item.get("resolution") in buckets]
    if next_steps:
        visible = [item for item in visible if item.get("next_step_type") in next_steps]

    rows = [
        {
            "rule_id": item.get("rule_id"),
            "resolution": item.get("resolution"),
            "next_step": item.get("next_step_type"),
            "can_promote_after_fix": item.get("can_promote_after_evidence_fix"),
            "rule_object": item.get("rule_object"),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "semantic_match": item.get("semantic_verified_rule_id"),
            "semantic_score": item.get("semantic_score"),
            "gaps": ", ".join(item.get("support_gaps", [])[:4]),
            "page": item.get("source_page"),
            "evidence_id": item.get("source_evidence_id"),
            "where": item.get("where_to_find_it"),
        }
        for item in visible[:250]
    ]
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    if visible:
        selected = st.selectbox("Resolution detail", [item["rule_id"] for item in visible])
        item = next(candidate for candidate in visible if candidate["rule_id"] == selected)
        _detail_sentence_panel(
            st,
            "Resolution in plain English",
            _resolution_detail_sentences(item),
            {"evidence_quote": item.get("evidence_sentence"), "page": item.get("source_page")},
            item,
        )
        with st.expander("Raw resolution JSON"):
            st.json(item)


def _bundle_rerun_tab(st: Any, report: dict[str, Any]) -> None:
    attempts = report.get("attempts", [])
    st.subheader("Evidence Bundle Rerun")
    st.caption("Shadow-mode rerun using the best evidence bundle. Bundle score cannot verify a rule by itself.")
    metric_cols = st.columns(6)
    metric_cols[0].metric("Attempts", report.get("attempt_count", len(attempts)))
    metric_cols[1].metric("Verified After Rerun", report.get("verified_after_rerun_count", 0))
    metric_cols[2].metric("Promotion Ready", report.get("promotion_ready_count", 0))
    metric_cols[3].metric("Still Review", report.get("review_after_rerun_count", 0))
    metric_cols[4].metric("Rejected", report.get("rejected_after_rerun_count", 0))
    metric_cols[5].metric("Skipped", report.get("skipped_count", 0))
    if not attempts:
        st.info("No bundle rerun attempts found.")
        return
    only_ready = st.checkbox("Promotion-ready bundle reruns only")
    visible = [item for item in attempts if item.get("promotion_ready")] if only_ready else attempts
    rows = [
        {
            "rule_id": item.get("original_rule_id"),
            "decision": item.get("retry_decision"),
            "ready": item.get("promotion_ready"),
            "score": item.get("bundle_score"),
            "rule_object": item.get("rule_object"),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "bundle_ids": ", ".join(str(value) for value in item.get("bundle_evidence_ids", [])),
            "missing": ", ".join(item.get("bundle_missing_fields", [])),
            "risk_flags": ", ".join(item.get("promotion_risk_flags", [])),
            "gaps": ", ".join(item.get("retry_support_gaps", [])[:4]),
        }
        for item in visible[:250]
    ]
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    if visible:
        selected = st.selectbox("Bundle rerun detail", [item["original_rule_id"] for item in visible])
        item = next(candidate for candidate in visible if candidate["original_rule_id"] == selected)
        _detail_sentence_panel(
            st,
            "Bundle rerun in plain English",
            _bundle_rerun_detail_sentences(item),
            {"page": "", "evidence_quote": item.get("bundle_evidence_quote")},
            item,
        )
        with st.expander("Raw bundle rerun JSON"):
            st.json(item)


def _semantic_review_tab(st: Any, report: dict[str, Any]) -> None:
    items = report.get("items", [])
    st.subheader("Semantic Review")
    st.caption("Structured meaning comparison plus optional MiniLM embedding similarity. Advisory only; it cannot clear support gaps.")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Review Rules", report.get("review_rule_count", len(items)))
    metric_cols[1].metric("Verified Rules Compared", report.get("verified_rule_count", 0))
    metric_cols[2].metric("High Similarity", report.get("high_similarity_count", 0))
    embedding = report.get("embedding", {})
    metric_cols[3].metric("Embedding Mode", embedding.get("mode", "unknown"))
    if embedding:
        st.caption(
            f"Embedding backend: {embedding.get('model') or 'none'} "
            f"({ 'available' if embedding.get('available') else embedding.get('reason', 'unavailable') })."
        )
    actions = report.get("summary", {}).get("semantic_action_counts", [])
    if actions:
        st.markdown("### Semantic Next Actions")
        _bar_rows(st, actions, "name", "count")
    if not items:
        st.info("No semantic review report found. Rerun the slim verifier.")
        return
    threshold = st.slider("Minimum meaning score", 0.0, 1.0, 0.70, 0.05)
    visible = [item for item in items if float(item.get("best_semantic_score") or 0.0) >= threshold]
    rows = []
    for item in visible[:250]:
        top = item.get("best_verified_matches", [{}])[0] if item.get("best_verified_matches") else {}
        rows.append(
            {
                "rule_id": item.get("rule_id"),
                "combined_score": item.get("best_combined_semantic_score", item.get("best_semantic_score")),
                "structured_score": item.get("best_structured_score"),
                "embedding_score": item.get("best_embedding_score"),
                "match_type": item.get("semantic_match_type"),
                "action": item.get("semantic_next_action"),
                "matched_verified": top.get("verified_rule_id"),
                "guardrail_blockers": ", ".join(item.get("semantic_guardrail_blockers", [])),
                "reasons": ", ".join(top.get("match_reasons", [])),
                "support_gaps": ", ".join(item.get("support_gaps", [])[:4]),
            }
        )
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    if visible:
        selected = st.selectbox("Semantic detail", [item["rule_id"] for item in visible])
        item = next(candidate for candidate in visible if candidate["rule_id"] == selected)
        top = item.get("best_verified_matches", [{}])[0] if item.get("best_verified_matches") else {}
        _detail_sentence_panel(
            st,
            "Semantic review in plain English",
            [
                f"Review rule `{item.get('rule_id')}` has combined semantic score {_display_value(item.get('best_combined_semantic_score', item.get('best_semantic_score')))} against verified rule `{top.get('verified_rule_id')}`.",
                f"Structured score: {_display_value(top.get('structured_score'))}; embedding score: {_display_value(top.get('embedding_score'))}.",
                f"The match reasons are: {_list_text(top.get('match_reasons', []))}.",
                f"Guardrails passed: {_list_text(top.get('semantic_guardrails', []))}. Blockers: {_list_text(top.get('semantic_guardrail_blockers', []))}.",
                f"The verifier still blocks this candidate because of: {_list_text(item.get('support_gaps', []))}.",
                f"Suggested meaning-review action: {_plain_label(item.get('semantic_next_action'))}.",
                "This comparison prioritizes review only. It cannot verify a rule.",
            ],
            {"evidence_quote": json.dumps(item.get("signature", {}), indent=2)},
            item,
        )
        with st.expander("Raw semantic JSON"):
            st.json(item)


def _rule_graph_tab(st: Any, graph: dict[str, Any]) -> None:
    st.subheader("Rule Graph")
    st.caption("Diagnostic graph showing candidates, evidence, canonical keys, verified rules, and review rules. It does not change verification.")
    metric_cols = st.columns(2)
    metric_cols[0].metric("Nodes", graph.get("node_count", len(graph.get("nodes", []))))
    metric_cols[1].metric("Edges", graph.get("edge_count", len(graph.get("edges", []))))
    summary = graph.get("summary", {})
    left, right = st.columns(2)
    with left:
        st.markdown("### Node Types")
        _bar_rows(st, summary.get("node_type_counts", []), "name", "count")
    with right:
        st.markdown("### Edge Types")
        _bar_rows(st, summary.get("edge_type_counts", []), "name", "count")
    edges = graph.get("edges", [])
    if edges:
        edge_types = st.multiselect("Edge type", _unique(edges, "type"), format_func=_plain_label)
        visible = [edge for edge in edges if not edge_types or edge.get("type") in edge_types]
        st.dataframe(_display_rows(visible[:500]), width="stretch", hide_index=True)
    else:
        st.info("No graph output found. Rerun the slim verifier.")


def p9_provenance_summary(rule: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Collect the Pipeline 9 lane for one review rule, or None for P5 rules.

    Pure data (no streamlit) so tests can pin it: provenance identifies where
    the RAG candidate came from (pack, lane, pseudo->original page, upstream
    filter action), and the evidence comparison shows the RAG block text next
    to the re-anchored authentic source window — or flags the mismatch that
    forced the rule to review.
    """
    candidate = rule.get("candidate") or {}
    provenance = candidate.get("p9_provenance") or rule.get("p9_provenance") or {}
    if not provenance:
        return None
    evidence = evidence_by_id.get(str(candidate.get("evidence_id") or rule.get("source_evidence_id") or "")) or {}
    return {
        "pack": provenance.get("rag_pack_id"),
        "lane": provenance.get("rag_lane"),
        "applicability": provenance.get("rag_applicability"),
        "pseudo_page": provenance.get("pseudo_page"),
        "original_page": provenance.get("original_page_number"),
        "filter_action": provenance.get("target_filter_action"),
        "block_id": provenance.get("block_id") or provenance.get("source_id"),
        "rag_text": str(evidence.get("evidence_text") or ""),
        "reanchored": bool(evidence.get("reanchored_to_source")),
        "mismatched": bool(evidence.get("rag_context_mismatch")),
        "source_window": str(evidence.get("source_context") or "") if evidence.get("reanchored_to_source") else "",
    }


def _legal_context_expander(
    st: Any,
    output_dir: Path,
    rule: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Retrieved FULL bylaw sections for a review rule (advisory context).

    The reviewer's recurring question is 'is there a qualifier NEARBY that the
    extractor missed?' — this answers it in place: the rule's own sentence is
    the retrieval query against the city's bylaw-RAG index, and hits come back
    section-expanded (the whole numbered provision, not a fragment).
    """
    lane = p9_provenance_summary(rule, evidence_by_id or {})
    index_path = bylaw_index_path(output_dir)
    if index_path is None and lane is None:
        return
    with st.expander("Nearby bylaw text"):
        if lane:
            st.markdown("**Pipeline 9 source trace**")
            st.caption(
                f"pack `{lane['pack']}` | lane {lane['lane']} ({lane['applicability']}) | "
                f"pseudo page {lane['pseudo_page']} → bylaw page {lane['original_page']} | "
                f"upstream filter: {lane['filter_action']} | block `{lane['block_id']}`"
            )
            if lane["mismatched"]:
                st.warning(
                    "Source mismatch: this extractor block was not found on its claimed source page, so the candidate stays in review."
                )
            if lane["reanchored"] and lane["source_window"]:
                rag_col, source_col = st.columns(2)
                with rag_col:
                    st.markdown("*Extractor text*")
                    st.markdown(
                        f"<div class='bylaw-section'>{html.escape(_short_display_quote(lane['rag_text']))}</div>",
                        unsafe_allow_html=True,
                    )
                with source_col:
                    st.markdown("*Matched source page text*")
                    st.markdown(
                        f"<div class='bylaw-section'>{html.escape(_short_display_quote(lane['source_window']))}</div>",
                        unsafe_allow_html=True,
                    )
            st.caption("Source trace is display-only. Upstream labels never approve a rule.")
        if index_path is None:
            return
        try:
            from burnaby_prototype.bylaw_rag import load_index

            query = " ".join(
                str(rule.get(field) or "")
                for field in ("rule_object", "applies_to", "constraint_scope", "condition", "value", "unit")
            )
            hits = load_index(index_path).ask(query, top_k=3)
        except Exception as error:  # pragma: no cover - optional dep path
            st.caption(f"Retrieval unavailable: {error}")
            return
        if not hits:
            st.caption("No related sections retrieved.")
            return
        for hit in hits:
            label = hit.get("section") or hit.get("chunk_id")
            st.markdown(
                f"<div class='bylaw-section'><b>[{html.escape(str(label))}]</b><br>"
                f"{html.escape(_short_display_quote(hit.get('section_text') or hit.get('text') or ''))}</div>",
                unsafe_allow_html=True,
            )
        st.caption("Retrieved context only. It cannot change the rule's decision.")


def _candidate_compare_tab(
    st: Any,
    triage_items: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    evidence_by_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    st.subheader("Compare With Verified Rules")
    st.caption("Use this when a review item looks like a rule that was already proven. Similarity is only a review aid.")
    if not triage_items:
        st.info("No review items match the current filters.")
        return
    options = [item["rule_id"] for item in triage_items]
    triage_lookup = {str(item.get("rule_id")): item for item in triage_items}
    selected_id = st.selectbox(
        "Rule to compare",
        options,
        format_func=lambda rule_id: _rule_option_label(triage_lookup.get(str(rule_id), {})),
    )
    review_rule = _by_rule_id(review_rules, selected_id)
    _legal_context_expander(st, output_dir, review_rule, evidence_by_id)
    triage_item = next((item for item in triage_items if item["rule_id"] == selected_id), {})
    semantic_match_id = triage_item.get("semantic_verified_rule_id") or review_rule.get("semantic_verified_rule_id")
    lexical_match_id = triage_item.get("similar_verified_rule_id") or review_rule.get("similar_verified_rule_id")
    verified_rule = _by_rule_id(verified_rules, semantic_match_id or lexical_match_id)

    st.markdown("### Claim comparison")
    sentence_left, sentence_right = st.columns(2)
    with sentence_left:
        _sentence_card(
            st,
            "Candidate in review",
            _rule_sentence(review_rule),
            "review",
            "Generated from the candidate's normalized fields.",
        )
    with sentence_right:
        if verified_rule:
            _sentence_card(
                st,
                "Closest verified rule",
                _rule_sentence(verified_rule),
                "verified",
                f"Semantic score: {triage_item.get('semantic_score') or review_rule.get('semantic_score') or 'n/a'}; lexical score: {triage_item.get('similar_verified_score')}",
            )
        else:
            _sentence_card(
                st,
                "Closest verified rule",
                "No verified comparison rule was found for this review item.",
                "neutral",
                "Use evidence repair or manual review instead.",
            )

    if verified_rule:
        st.markdown("#### Field differences")
        st.dataframe(_display_rows(_field_comparison_rows(review_rule, verified_rule)), width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.markdown("### Candidate in review")
        st.table([compact_rule_row(review_rule)])
        st.markdown("#### Evidence")
        st.code(_source_text(review_rule), language="text")
        st.markdown("#### Suggested next step")
        st.write(triage_item.get("suggested_fix"))
    with right:
        st.markdown("### Closest verified rule")
        if verified_rule:
            st.table([compact_rule_row(verified_rule)])
            st.markdown(f"Semantic score: `{triage_item.get('semantic_score') or review_rule.get('semantic_score') or 'n/a'}`")
            st.markdown(f"Lexical score: `{triage_item.get('similar_verified_score')}`")
            st.code(_source_text(verified_rule), language="text")
        else:
            st.info("No verified comparison rule found.")


def _repair_tab(st: Any, repair: dict[str, Any]) -> None:
    suggestions = repair.get("suggestions", [])
    st.subheader(f"Evidence Repair ({len(suggestions)})")
    st.caption("Find stronger source passages for candidates held in review. A repair suggestion still has to pass the verifier.")
    rows = []
    for item in suggestions[:200]:
        top = item.get("top_evidence", [{}])[0] if item.get("top_evidence") else {}
        rows.append(
            {
                "Rule ID": item.get("rule_id"),
                "Can retry verifier": item.get("can_retry_verification"),
                "Confidence": item.get("best_repair_confidence"),
                "Rule family": item.get("rule_object"),
                "Value": item.get("value"),
                "Unit": item.get("unit"),
                "Current evidence": item.get("current_evidence_id"),
                "Best evidence": top.get("evidence_id"),
                "Fields repair may help": ", ".join(item.get("repairable_fields", [])),
                "Why this evidence matched": ", ".join(top.get("match_reasons", [])),
            }
        )
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    if suggestions:
        selected = st.selectbox(
            "Repair detail",
            [item["rule_id"] for item in suggestions],
            format_func=lambda rule_id: _rule_option_label(next((item for item in suggestions if item.get("rule_id") == rule_id), {})),
        )
        item = next(item for item in suggestions if item["rule_id"] == selected)
        top_evidence = item.get("top_evidence", [{}])[0] if item.get("top_evidence") else {}
        _detail_sentence_panel(
            st,
            "Evidence repair in plain English",
            _repair_detail_sentences(item, top_evidence),
            top_evidence,
            item,
        )
        with st.expander("Raw repair JSON"):
            st.json(item)


def _rerun_tab(st: Any, rerun: dict[str, Any], evidence_units: list[dict[str, Any]]) -> None:
    attempts = rerun.get("attempts", [])
    verified = rerun.get("verified_after_rerun", [])
    st.subheader("Shadow Reruns")
    st.caption("Test stronger evidence without changing verified_rules.json. Promotion still requires deterministic proof and benchmark safety.")
    metric_cols = st.columns(6)
    metric_cols[0].metric("Attempts", rerun.get("attempt_count", len(attempts)))
    metric_cols[1].metric("Verified After Rerun", rerun.get("verified_after_rerun_count", len(verified)))
    metric_cols[2].metric("Promotion Ready", rerun.get("promotion_ready_count", 0))
    metric_cols[3].metric("Still Review", rerun.get("review_after_rerun_count", 0))
    metric_cols[4].metric("Rejected", rerun.get("rejected_after_rerun_count", 0))
    metric_cols[5].metric("Skipped", rerun.get("skipped_count", 0))

    if not attempts:
        st.info("No evidence rerun attempts found.")
        return

    left, middle, right = st.columns([1, 1, 1])
    decisions = left.multiselect("Rerun result", _unique(attempts, "retry_decision"), format_func=_plain_label)
    rule_objects = middle.multiselect("Rule family", _unique(attempts, "rule_object"), format_func=_plain_label)
    only_ready = right.checkbox("Passed shadow checks only")
    visible = attempts
    if decisions:
        visible = [item for item in visible if item.get("retry_decision") in decisions]
    if rule_objects:
        visible = [item for item in visible if item.get("rule_object") in rule_objects]
    if only_ready:
        visible = [item for item in visible if item.get("promotion_ready")]

    ready_rows = [
        {
            "Rule ID": item.get("original_rule_id"),
            "Rule family": item.get("rule_object"),
            "Scope": item.get("constraint_scope"),
            "Direction": _operator_short(item.get("operator"), item.get("constraint_type")),
            "Value": item.get("value"),
            "Unit": item.get("unit"),
            "Retry evidence": item.get("retry_evidence_id"),
            "Confidence": item.get("repair_confidence"),
        }
        for item in attempts
        if item.get("promotion_ready")
    ]
    if ready_rows:
        st.markdown("### Passed shadow checks")
        st.dataframe(_display_rows(ready_rows), width="stretch", hide_index=True)

    rows = [
        {
            "Rule ID": item.get("original_rule_id"),
            "Rerun result": item.get("retry_decision"),
            "Rule family": item.get("rule_object"),
            "Value": item.get("value"),
            "Unit": item.get("unit"),
            "Original evidence": item.get("original_evidence_id"),
            "Retry evidence": item.get("retry_evidence_id"),
            "Confidence": item.get("repair_confidence"),
            "Ready for promotion": item.get("promotion_ready"),
            "Risk flags": ", ".join(item.get("promotion_risk_flags", [])),
            "Still missing": ", ".join(item.get("retry_support_gaps", [])[:4]),
        }
        for item in visible[:250]
    ]
    st.markdown(f"### Shadow rerun attempts ({len(visible)})")
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    if visible:
        selected = st.selectbox(
            "Shadow rerun detail",
            [item["original_rule_id"] for item in visible],
            format_func=lambda rule_id: _rule_option_label(next((item for item in visible if item.get("original_rule_id") == rule_id), {})),
        )
        item = next(item for item in visible if item["original_rule_id"] == selected)
        evidence = _evidence_by_id(evidence_units, item.get("retry_evidence_id"))
        _detail_sentence_panel(
            st,
            "Evidence rerun in plain English",
            _rerun_detail_sentences(item),
            evidence,
            item,
        )
        with st.expander("Raw rerun JSON"):
            st.json(item)


def _safe_tuning_tab(st: Any, report: dict[str, Any], evidence_units: list[dict[str, Any]]) -> None:
    items = report.get("items", [])
    st.subheader(f"Safe Verifier Tuning ({len(items)})")
    st.caption("Engineering backlog for general verifier improvements. These candidates are not automatically promoted.")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Candidates", report.get("candidate_count", len(items)))
    metric_cols[1].metric("Promotion-Ready Reruns", sum(1 for item in items if item.get("rerun_promotion_ready")))
    metric_cols[2].metric("Tuning Types", len(report.get("tuning_type_counts", [])))

    type_rows = report.get("tuning_type_counts", [])
    if type_rows:
        st.markdown("### Tuning Type Mix")
        _bar_rows(st, type_rows, "name", "count")
    if not items:
        st.info("No safe verifier tuning candidates found.")
        return

    tuning_types = st.multiselect("Tuning type", _unique(items, "tuning_type"), format_func=_plain_label)
    visible = [item for item in items if not tuning_types or item.get("tuning_type") in tuning_types]
    rows = [
        {
            "rule_id": item.get("rule_id"),
            "tuning_type": item.get("tuning_type"),
            "rule_object": item.get("rule_object"),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "likely": item.get("likely_status"),
            "score": item.get("likely_correct_score"),
            "rerun_ready": item.get("rerun_promotion_ready"),
            "gaps": ", ".join(item.get("support_gaps", [])[:4]),
        }
        for item in visible[:250]
    ]
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    selected = st.selectbox("Tuning detail", [item["rule_id"] for item in visible])
    item = next(candidate for candidate in visible if candidate["rule_id"] == selected)
    evidence = _evidence_by_id(evidence_units, item.get("evidence_id") or item.get("rerun_evidence_id"))
    _detail_sentence_panel(
        st,
        "Safe tuning candidate in plain English",
        _safe_tuning_detail_sentences(item),
        evidence,
        item,
    )
    with st.expander("Required tests"):
        for test in item.get("required_tests", []):
            st.write(f"- {test}")
    with st.expander("Guardrails"):
        for guardrail in item.get("guardrails", []):
            st.write(f"- {guardrail}")
    with st.expander("Raw safe-tuning JSON"):
        st.json(item)


def _structure_tab(st: Any) -> None:
    st.subheader("Verification Layer Structure")
    st.code(
        """Pipeline 5 final_rule_registry.json
  -> zihao_adapter.py
  -> slim_pipeline.py
  -> verification.py
       normalization.py
       support_checks.py
       proof_trace.py
       text_span_proof.py
       table_natural_logic.py
       decision_policy.py
  -> verified / review / rejected / not_used
  -> evidence_intelligence.py
  -> rule_graph.py
  -> evidence_bundle_rerun
  -> guarded bundle promotion
  -> semantic_review.py
  -> evidence_repair.py
  -> evidence_rerun.py
  -> safe_tuning.py
  -> review_router.py
  -> dashboard""",
        language="text",
    )
    rows = [
        {"layer": "Adapter", "file": "zihao_adapter.py", "purpose": "Normalize Pipeline 5 registry into candidates and evidence packets."},
        {"layer": "Verifier", "file": "verification.py", "purpose": "Main support-gap loop and final rule objects."},
        {"layer": "Normalization", "file": "normalization.py", "purpose": "Candidate cleanup before support checks; no rule promotion."},
        {"layer": "Support checks", "file": "support_checks.py", "purpose": "Reusable deterministic checks for value, unit, operator, scope, applies_to, and rule family."},
        {"layer": "Proof trace", "file": "proof_trace.py", "purpose": "Human-readable proof traces, review reasons, and proof/decision diagnostics."},
        {"layer": "Text span proof", "file": "text_span_proof.py", "purpose": "Prose evidence proof for value, unit, operator, scope, condition."},
        {"layer": "Table proof", "file": "table_natural_logic.py", "purpose": "Table title/row/column/cell proof."},
        {"layer": "Decision policy", "file": "decision_policy.py", "purpose": "Map support gaps to verified/review/rejected/not_used."},
        {"layer": "Evidence intelligence", "file": "evidence_intelligence.py", "purpose": "Build a rule-centric evidence index, score evidence bundles, and recommend safe shadow reruns."},
        {"layer": "Evidence repair", "file": "evidence_repair.py", "purpose": "Find stronger existing evidence for review rules."},
        {"layer": "Evidence rerun", "file": "evidence_rerun.py", "purpose": "Rerun repairable candidates or bundles against stronger evidence in shadow mode."},
        {"layer": "Bundle promotion", "file": "evidence_rerun.py", "purpose": "Move only deterministic, no-gap, no-risk bundle reruns into verified output."},
        {"layer": "Rule graph", "file": "rule_graph.py", "purpose": "Diagnostic graph linking candidates, evidence packets, canonical keys, verified rules, and review rules."},
        {"layer": "Verification cache", "file": "verification_cache.py", "purpose": "Stable cache keys and hit/miss diagnostics for future incremental multi-bylaw runs."},
        {"layer": "Semantic review", "file": "semantic_review.py", "purpose": "Structured meaning comparison between review and verified rules; advisory only."},
        {"layer": "Safe tuning", "file": "safe_tuning.py", "purpose": "List verifier-tuning candidates with experiments, tests, and guardrails."},
        {"layer": "Review router", "file": "review_router.py", "purpose": "Single review module: triage (rank + likely mistakes), action audit (next-action buckets), and the consolidated reviewer route. Advisory only."},
    ]
    st.table(rows)


def _preflight_tab(st: Any, preflight: dict[str, Any]) -> None:
    st.subheader("Pipeline 5 Extraction Preflight")
    if not preflight:
        st.info("No preflight report found.")
        st.code(
            "python3 scripts/run_pipeline5_extraction.py "
            "--report-json outputs/burnaby_r1_slim_pipeline5_registry/pipeline5_extraction_preflight.json",
            language="bash",
        )
        return
    checks = preflight.get("checks", {})
    st.table([{"check": key, "status": "OK" if value else "MISSING"} for key, value in checks.items()])
    # The preflight script (scripts/run_pipeline5_extraction.py) only emits
    # checks/blockers/can_execute, so the saved-registry status is derived from
    # its saved_final_registry_exists check rather than from keys it never writes.
    if checks.get("saved_final_registry_exists"):
        st.success("Saved Pipeline 5 registry found. The verifier can run from this saved extraction output.")
    else:
        failed_checks = [name for name, passed in checks.items() if not passed]
        st.error("Saved registry missing: " + (", ".join(failed_checks) or "saved_final_registry_exists"))

    execution_blockers = preflight.get("blockers") or []
    if execution_blockers:
        st.warning("Full notebook execution still needs: " + ", ".join(execution_blockers))
    else:
        st.success("Pipeline 5 notebook execution is ready.")
    st.json({
        key: preflight.get(key)
        for key in ("pipeline5_dir", "notebook", "final_registry", "can_execute")
    })


def extract_bylaw_sections(payload: Any) -> list[dict[str, str]]:
    """Normalize an unknown extraction payload into [{title, text}, ...]."""
    title_keys = ("section", "section_id", "id", "anchor", "number", "title", "heading", "name")
    text_keys = ("text", "content", "body", "raw_text", "section_text")

    def _from_dict_item(item: dict[str, Any], fallback_title: str) -> dict[str, str] | None:
        text = next((str(item[key]) for key in text_keys if isinstance(item.get(key), str) and item[key].strip()), "")
        if not text:
            return None
        title = next((str(item[key]) for key in title_keys if item.get(key) not in (None, "")), fallback_title)
        heading = next((str(item[key]) for key in ("title", "heading") if item.get(key) not in (None, "")), "")
        if heading and heading != title:
            title = f"{title} — {heading}"
        return {"title": title, "text": text}

    sections: list[dict[str, str]] = []
    if isinstance(payload, str):
        if payload.strip():
            sections.append({"title": "Extracted text", "text": payload})
    elif isinstance(payload, list):
        for index, item in enumerate(payload, start=1):
            if isinstance(item, dict):
                section = _from_dict_item(item, f"Section {index}")
                if section:
                    sections.append(section)
            elif isinstance(item, str) and item.strip():
                sections.append({"title": f"Section {index}", "text": item})
    elif isinstance(payload, dict):
        nested = payload.get("sections")
        if isinstance(nested, (list, dict)):
            return extract_bylaw_sections(nested if isinstance(nested, list) else [
                {"title": key, **(value if isinstance(value, dict) else {"text": str(value)})}
                for key, value in nested.items()
            ])
        direct = _from_dict_item(payload, "Extracted text")
        if direct:
            sections.append(direct)
        else:
            # Loose {key: text} shape: only accept prose-like values so
            # metadata payloads (urls, hashes, timestamps) are not mistaken
            # for bylaw sections.
            for key, value in payload.items():
                if isinstance(value, str) and len(value.split()) >= 8:
                    sections.append({"title": str(key), "text": value})
                elif isinstance(value, dict):
                    section = _from_dict_item(value, str(key))
                    if section:
                        sections.append(section)
    return sections


def highlight_evidence(section_text: str, quote: str) -> tuple[str, bool]:
    """Mark the cited evidence inside section text via simple substring markup.

    Both sides are whitespace-normalized; progressively shorter quote prefixes
    are tried so truncated evidence quotes still anchor. Returns escaped HTML
    plus whether a match was found.
    """
    normalized = " ".join(str(section_text or "").split())
    words = " ".join(str(quote or "").split()).rstrip(". ").removesuffix("...").split()
    for length in (len(words), 24, 16, 10, 6):
        needle = " ".join(words[:length])
        if len(needle) < 12:
            break
        index = normalized.lower().find(needle.lower())
        if index >= 0:
            end = index + len(needle)
            return (
                html.escape(normalized[:index])
                + "<mark class='evidence-hit'>"
                + html.escape(normalized[index:end])
                + "</mark>"
                + html.escape(normalized[end:]),
                True,
            )
    return html.escape(normalized), False


def _rag_chat_key(city_stem: str) -> str:
    return f"bylaw_rag_chat::{city_stem}"


def _rag_tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", str(text or "").lower())


def _rag_query_terms(question: str) -> list[str]:
    tokens = _rag_tokenize(question)
    expanded = list(tokens)
    seen = set(tokens)
    for token in tokens:
        for extra in RAG_QUERY_SYNONYMS.get(token, ()):
            if extra not in seen:
                seen.add(extra)
                expanded.append(extra)
    return expanded


def _dashboard_reranker(st: Any | None) -> Any | None:
    """Return a session-cached ``OpenRouterReranker`` or ``None``.

    Reuses the SAME ``OPENROUTER_API_KEY`` the dashboard's ``_load_dotenv``
    already loaded (the key the extraction layer uses). Returns ``None`` when
    there is no key or the reranker client cannot be constructed — callers must
    treat ``None`` as "skip reranking, keep BM25/RRF order". Never raises.
    """
    api_key = _secret_value(st, "OPENROUTER_API_KEY")
    if not api_key:
        return None
    cache_key = "_bylaw_rag_reranker"
    if st is not None:
        try:
            cached = st.session_state.get(cache_key)
            if cached is not None:
                return cached
        except Exception:
            cached = None
    try:
        from burnaby_prototype.native_extraction import OpenRouterReranker

        reranker = OpenRouterReranker(api_key)
    except Exception:
        return None
    if st is not None:
        try:
            st.session_state[cache_key] = reranker
        except Exception:
            pass
    return reranker


def _rerank_rag_hits(question: str, hits: list[dict[str, Any]], top_k: int, st: Any | None) -> list[dict[str, Any]]:
    """Cross-encoder rerank a broad candidate shortlist down to ``top_k``.

    The reranker scores ``_pack_rerank_text`` which reads ``source_text``; the
    RAG hits carry the full-context clause under ``section_text``/``text``, so we
    expose that as ``source_text`` for scoring only. On no key, empty results, or
    any error we return the original BM25/RRF top-``top_k`` unchanged.
    """
    if len(hits) <= top_k:
        return hits
    reranker = _dashboard_reranker(st)
    if reranker is None:
        return hits[:top_k]
    packs = [
        {**hit, "source_text": str(hit.get("section_text") or hit.get("text") or "")}
        for hit in hits
    ]
    try:
        ranked = reranker.rerank(question, packs, top_n=top_k)
    except Exception:
        return hits[:top_k]
    if not ranked:
        return hits[:top_k]
    # Strip the scoring-only ``source_text`` shim; keep the reranker's score as a
    # signal so the sources table can show why a clause surfaced.
    cleaned: list[dict[str, Any]] = []
    for pack in ranked[:top_k]:
        pack = dict(pack)
        pack.pop("source_text", None)
        score = pack.pop("rerank_score", None)
        if score is not None:
            signals = dict(pack.get("signals") or {})
            signals["rerank_score"] = round(float(score), 6)
            pack["signals"] = signals
        cleaned.append(pack)
    return cleaned


def _dashboard_rag_hits(
    index_path: Path,
    question: str,
    top_k: int = RAG_CHAT_TOP_K,
    st: Any | None = None,
) -> list[dict[str, Any]]:
    """Return bylaw RAG hits with two-stage retrieval and a cloud fallback.

    Stage 1 retrieves a BROAD candidate set (``RAG_RERANK_CANDIDATES``) from the
    existing BM25/RRF index (``bylaw_rag.BylawIndex``) so the decisive clause is
    in the pool even when it ranks well below the ``top_k`` cutoff. Stage 2, when
    an OpenRouter key is available, reranks that shortlist with a cross-encoder
    and keeps the top ``top_k``; otherwise it falls back to the BM25/RRF order.

    The deployment repo intentionally contains only the dashboard and JSON
    outputs, not the full Python package. Locally we use ``bylaw_rag.py`` when it
    is importable; on cloud we read the index JSON directly via the standalone
    lexical retriever. Either path goes through the same rerank stage.
    """
    candidate_k = max(top_k, RAG_RERANK_CANDIDATES)
    try:
        from burnaby_prototype.bylaw_rag import load_index

        candidates = load_index(index_path).ask(question, top_k=candidate_k)
    except Exception:
        candidates = _standalone_rag_hits(index_path, question, top_k=candidate_k)
    return _rerank_rag_hits(question, candidates, top_k, st)


def _standalone_rag_hits(index_path: Path, question: str, top_k: int = RAG_CHAT_TOP_K) -> list[dict[str, Any]]:
    payload = _read_json(index_path, {})
    chunks = [chunk for chunk in payload.get("chunks", []) if str(chunk.get("text") or "").strip()]
    query_terms = _rag_query_terms(question)
    query_set = set(query_terms)
    if not chunks or not query_set:
        return []

    scored: list[tuple[float, dict[str, Any], set[str]]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        tokens = set(_rag_tokenize(text))
        overlap = tokens & query_set
        if not overlap:
            continue
        exact_value_bonus = sum(1 for term in query_set if re.fullmatch(r"\d+(?:\.\d+)?", term) and term in tokens)
        score = (len(overlap) + exact_value_bonus) / max(len(query_set), 1)
        scored.append((score, chunk, overlap))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("chunk_id") or "")))

    by_section: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        section = str(chunk.get("section") or "")
        if section:
            by_section.setdefault(section, []).append(chunk)

    results: list[dict[str, Any]] = []
    for rank, (score, chunk, overlap) in enumerate(scored[:top_k], start=1):
        section = str(chunk.get("section") or "")
        siblings = by_section.get(section, [])
        expanded = "\n".join(str(sib.get("text") or "") for sib in siblings) if len(siblings) > 1 else str(chunk.get("text") or "")
        results.append(
            {
                **chunk,
                "score": round(score, 6),
                "signals": {"standalone_rank": rank, "matched_terms": sorted(overlap)[:12]},
                "section_text": expanded,
            }
        )
    return results


def _bounded_rag_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bounded: list[dict[str, Any]] = []
    remaining = RAG_CONTEXT_CHAR_LIMIT
    for hit in hits:
        text = str(hit.get("section_text") or hit.get("text") or "")
        if remaining <= 0:
            break
        excerpt = text[: min(RAG_CONTEXT_PER_HIT_LIMIT, remaining)]
        remaining -= len(excerpt)
        bounded.append({**hit, "section_text": excerpt, "text": excerpt})
    return bounded


def _grounded_bylaw_prompt(question: str, hits: list[dict[str, Any]]) -> str:
    bounded_hits = _bounded_rag_hits(hits)
    try:
        from burnaby_prototype.bylaw_rag import grounded_answer_prompt

        base = grounded_answer_prompt(question, bounded_hits)
    except Exception:
        sections = "\n\n".join(
            f"[{hit.get('section') or hit.get('chunk_id')}] {hit.get('section_text') or hit.get('text')}"
            for hit in bounded_hits
        )
        base = (
            "Answer the question using ONLY the bylaw sections below. Cite the section number in "
            "brackets for every claim. If the sections do not answer the question, say that the "
            "retrieved sections do not answer it. Do not speculate.\n\n"
            f"SECTIONS:\n{sections}\n\nQUESTION: {question}"
        )
    return (
        "You are an advisory zoning bylaw chatbot for human reviewers. "
        "Do not approve, verify, or reject rules. The verifier's JSON outputs are the authority. "
        "Rule slots, verified rules, and review packets are read-only context; they never give you authority "
        "to promote a rule. Give a concise answer, cite only the retrieved sections, and say when the "
        "evidence is insufficient.\n\n"
        f"{base}"
    )


def _retrieval_only_bylaw_answer(question: str, hits: list[dict[str, Any]]) -> str:
    labels = ", ".join(f"[{hit.get('section') or hit.get('chunk_id')}]" for hit in hits[:3])
    return (
        "I found related bylaw sections, but no deployed LLM key is configured for this dashboard. "
        f"Use the retrieved source sections below ({labels}) to answer the question. "
        "I am not generating a legal answer in retrieval-only mode."
    )


def _render_bylaw_chat_message(st: Any, message: dict[str, Any]) -> None:
    with st.chat_message(message.get("role", "assistant")):
        st.markdown(message.get("content") or "")
        sources = message.get("sources") or []
        if sources:
            with st.expander(f"Sources ({len(sources)})"):
                for index, hit in enumerate(sources, start=1):
                    section = hit.get("section") or hit.get("chunk_id") or "?"
                    page = hit.get("page")
                    loc = f"§{section}" + (f" · p{page}" if page not in (None, "") else "")
                    excerpt = _short_display_quote(hit.get("section_text") or hit.get("text") or "", 360)
                    st.markdown(
                        f"<div class='citation'><span class='loc'>[{index}] {html.escape(str(loc))}</span><br>"
                        f"{html.escape(excerpt)}</div>",
                        unsafe_allow_html=True,
                    )


_BYLAW_SUGGESTION_TEMPLATES = {
    ("height", None): "What is the maximum building height?",
    ("setback", "rear_yard"): "What is the rear setback requirement?",
    ("setback", "side_yard"): "What is the side setback requirement?",
    ("setback", "front_yard"): "What is the front setback requirement?",
    ("setback", None): "What setback applies here?",
    ("lot_coverage", None): "What is the maximum lot coverage?",
    ("building_separation", None): "What building separation is required?",
    ("floor_area", None): "What floor area is allowed?",
    ("floor_space_ratio", None): "What is the floor space ratio?",
    ("storeys", None): "How many storeys are permitted?",
    ("lot_area", None): "What is the minimum lot area?",
    ("dwelling_units", None): "How many dwelling units are allowed?",
}

_BYLAW_SUGGESTION_FALLBACK = [
    "What is the maximum building height?",
    "What setbacks apply to the rear and side yards?",
    "What is the maximum lot coverage?",
    "What rules apply to a secondary suite?",
]


def _bylaw_suggestions(data: dict[str, Any], limit: int = 6) -> list[str]:
    """Data-generated chat prompt suggestions (hidden behind the popover).

    Derived from the rule families/scopes actually present in this city's
    verified + review rules, so the hints are never stale hardcoded strings.
    """
    questions: list[str] = []
    seen: set[str] = set()
    rules = list(data.get("verified") or []) + list(data.get("review") or [])
    for rule in rules:
        family = str(rule.get("rule_object") or "")
        scope = str(rule.get("constraint_scope") or "")
        question = _BYLAW_SUGGESTION_TEMPLATES.get((family, scope)) or _BYLAW_SUGGESTION_TEMPLATES.get((family, None))
        if question and question not in seen:
            seen.add(question)
            questions.append(question)
        if len(questions) >= limit:
            break
    for question in _BYLAW_SUGGESTION_FALLBACK:
        if len(questions) >= limit:
            break
        if question not in seen:
            seen.add(question)
            questions.append(question)
    return questions


def _bylaw_chat_respond(st: Any, question: str, index_path: Path, chat_key: str) -> None:
    """Run one retrieval -> grounded-prompt -> answer turn, rendering inline."""
    user_message = {"role": "user", "content": question}
    st.session_state[chat_key].append(user_message)
    _render_bylaw_chat_message(st, user_message)
    hits = _dashboard_rag_hits(index_path, question, top_k=RAG_CHAT_TOP_K, st=st)
    if not hits:
        answer = (
            "I could not find a related bylaw section for that question. Try the bylaw's own terms, "
            "such as setback, height, storey, parcel, coverage, or suite."
        )
        assistant_message = {"role": "assistant", "content": answer, "sources": [], "question": question}
    else:
        bounded_hits = _bounded_rag_hits(hits)
        prompt = _grounded_bylaw_prompt(question, bounded_hits)
        # Prior turns (exclude the just-appended current question) give the LLM
        # conversational context for follow-ups; the grounded prompt stays the
        # final, source-anchored user message inside _optional_bylaw_llm_answer.
        prior_turns = st.session_state[chat_key][-5:-1]
        answer = _optional_bylaw_llm_answer(prompt, st, history=prior_turns) or _retrieval_only_bylaw_answer(question, bounded_hits)
        assistant_message = {"role": "assistant", "content": answer, "sources": bounded_hits, "question": question}
    st.session_state[chat_key].append(assistant_message)
    _render_bylaw_chat_message(st, assistant_message)


def _secret_value(st: Any | None, name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    if st is None:
        return ""
    try:
        secret = st.secrets.get(name, "")
    except Exception:
        return ""
    return str(secret or "")


def _bylaw_llm_status(st: Any | None = None) -> dict[str, Any]:
    preferred = (_secret_value(st, "BYLAW_RAG_PROVIDER") or "").strip().lower()
    openrouter_key = _secret_value(st, "OPENROUTER_API_KEY")
    gemini_key = (
        _secret_value(st, "GEMINI_API_KEY")
        or _secret_value(st, "GOOGLE_API_KEY")
        or _secret_value(st, "GOOGLE_GENAI_API_KEY")
    )
    openai_key = _secret_value(st, "OPENAI_API_KEY")
    anthropic_key = _secret_value(st, "ANTHROPIC_API_KEY") or _secret_value(st, "CLAUDE_API_KEY")

    def _status(provider: str, key: str, model: str) -> dict[str, Any]:
        return {
            "provider": provider,
            "model": _secret_value(st, "BYLAW_RAG_MODEL") or model,
            "available": bool(key),
            "configured": bool(key),
        }

    if preferred in {"openrouter", "open-router"}:
        return _status("openrouter", openrouter_key, DEFAULT_BYLAW_CHAT_MODEL)
    if preferred in {"gemini", "google"}:
        return _status("gemini", gemini_key, _secret_value(st, "GEMINI_MODEL") or "gemini-2.0-flash-lite")
    if preferred in {"openai", "openai-compatible"}:
        return _status("openai", openai_key, _secret_value(st, "OPENAI_MODEL") or "gpt-4o-mini")
    if preferred in {"anthropic", "claude"}:
        return _status("anthropic", anthropic_key, _secret_value(st, "CLAUDE_MODEL") or "claude-3-5-haiku-latest")
    # Auto-detect: OpenRouter first — the project's .env already ships an
    # OPENROUTER_API_KEY (the same key the extraction layer uses), so the chat
    # works out of the box with no extra configuration.
    if openrouter_key:
        return _status("openrouter", openrouter_key, DEFAULT_BYLAW_CHAT_MODEL)
    if gemini_key:
        return _status("gemini", gemini_key, _secret_value(st, "GEMINI_MODEL") or "gemini-2.0-flash-lite")
    if openai_key:
        return _status("openai", openai_key, _secret_value(st, "OPENAI_MODEL") or "gpt-4o-mini")
    if anthropic_key:
        return _status("anthropic", anthropic_key, _secret_value(st, "CLAUDE_MODEL") or "claude-3-5-haiku-latest")
    return {"provider": "none", "model": "", "available": False, "configured": False}


def _optional_bylaw_llm_answer(
    prompt: str,
    st: Any | None = None,
    history: list[dict[str, Any]] | None = None,
) -> str | None:
    status = _bylaw_llm_status(st)
    if not status.get("available"):
        return None
    provider = status["provider"]
    if provider == "openrouter":
        return _openrouter_answer(prompt, _secret_value(st, "OPENROUTER_API_KEY"), status["model"], history)
    if provider == "gemini":
        key = _secret_value(st, "GEMINI_API_KEY") or _secret_value(st, "GOOGLE_API_KEY") or _secret_value(st, "GOOGLE_GENAI_API_KEY")
        return _gemini_answer(prompt, key, status["model"])
    if provider == "openai":
        return _openai_answer(prompt, _secret_value(st, "OPENAI_API_KEY"), status["model"], st)
    if provider == "anthropic":
        key = _secret_value(st, "ANTHROPIC_API_KEY") or _secret_value(st, "CLAUDE_API_KEY")
        return _anthropic_answer(prompt, key, status["model"])
    return None


_BYLAW_CHAT_SYSTEM = (
    "You answer only from retrieved zoning bylaw excerpts. You are an advisory "
    "assistant for human reviewers and never approve, verify, reject, or promote a rule. "
    "Cite the section number in brackets for every claim, and say plainly when the "
    "retrieved sections do not answer the question."
)


def _openrouter_answer(
    prompt: str,
    api_key: str,
    model: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer via OpenRouter's OpenAI-compatible chat-completions endpoint.

    Prior conversation turns (trimmed) are included so follow-up questions read
    naturally, while the final user message carries the freshly retrieved,
    section-grounded prompt — keeping every answer anchored to source text.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": _BYLAW_CHAT_SYSTEM}]
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": str(content)[:1500]})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model or DEFAULT_BYLAW_CHAT_MODEL,
        "temperature": 0.0,
        "max_tokens": 800,
        "messages": messages,
    }
    data = _post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        payload,
        {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/ubco-mds-2025-labs",
            "X-Title": "Bylaw Verification Dashboard",
        },
    )
    if data.get("_error"):
        return f"LLM unavailable: {data['_error']}"
    return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip() or "The LLM returned no text."


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 35) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:500]
        return {"_error": f"HTTP {error.code}: {body}"}
    except Exception as error:
        return {"_error": f"{type(error).__name__}: {error}"}


def _gemini_answer(prompt: str, api_key: str, model: str) -> str:
    model_name = str(model or "gemini-2.0-flash-lite").removeprefix("models/")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model_name, safe='-._~')}:generateContent?key={urllib.parse.quote(api_key)}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 700},
    }
    data = _post_json(url, payload, {})
    if data.get("_error"):
        return f"LLM unavailable: {data['_error']}"
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    text = "\n".join(str(part.get("text") or "") for part in parts).strip()
    return text or "The LLM returned no text."


def _openai_answer(prompt: str, api_key: str, model: str, st: Any | None = None) -> str:
    base_url = (_secret_value(st, "OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": model or "gpt-4o-mini",
        "temperature": 0.0,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": "You answer only from retrieved zoning bylaw excerpts. Never approve or verify rules."},
            {"role": "user", "content": prompt},
        ],
    }
    data = _post_json(f"{base_url}/chat/completions", payload, {"Authorization": f"Bearer {api_key}"})
    if data.get("_error"):
        return f"LLM unavailable: {data['_error']}"
    return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip() or "The LLM returned no text."


def _anthropic_answer(prompt: str, api_key: str, model: str) -> str:
    payload = {
        "model": model or "claude-3-5-haiku-latest",
        "max_tokens": 700,
        "temperature": 0.0,
        "system": "You answer only from retrieved zoning bylaw excerpts. Never approve or verify rules.",
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        payload,
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    if data.get("_error"):
        return f"LLM unavailable: {data['_error']}"
    blocks = data.get("content") or []
    return "\n".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text").strip() or "The LLM returned no text."


def _ask_the_bylaw_panel(st: Any, output_dir: Path, data: dict[str, Any] | None = None) -> None:
    """Conversational, source-grounded bylaw assistant — a real LLM chat that
    answers ONLY from retrieved bylaw sections. ADVISORY: it never verifies,
    approves, rejects, edits JSON, or changes GIS outputs."""
    data = data or {}
    index_path = bylaw_index_path(output_dir)
    city_stem = city_stem_from_dir(output_dir)
    city_label = city_label_from_dir(output_dir)
    llm_status = _bylaw_llm_status(st)

    st.markdown("<div class='chat-shell'>", unsafe_allow_html=True)
    mode_pill = (
        f"<span class='mode-pill live'>LLM + RAG · {html.escape(str(llm_status['provider']))}</span>"
        if llm_status.get("available")
        else "<span class='mode-pill'>Retrieval only</span>"
    )
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px;'>"
        "<span class='chat-ribbon'>Advisory · answers come from retrieved bylaw sections · cannot verify, approve, reject, or edit outputs</span>"
        f"{mode_pill}</div>",
        unsafe_allow_html=True,
    )

    if index_path is None:
        st.info(
            "No retrieval index yet — build it with "
            f"`.venv/bin/python scripts/build_rag_index.py --city {city_stem}`."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    chat_key = _rag_chat_key(city_stem)
    st.session_state.setdefault(chat_key, [])
    history = st.session_state[chat_key]

    head_left, head_right = st.columns([5, 1])
    if head_right.button("↺ New chat", key=f"clear_{chat_key}"):
        st.session_state[chat_key] = []
        history = st.session_state[chat_key]

    if not history:
        st.markdown(
            f"<div class='chat-empty'><h2>Ask about the {html.escape(city_label)} bylaw</h2>"
            "<p>Plain-English questions about setbacks, height, coverage, suites, and parcels. "
            "Every answer cites the section it came from. I can't approve, reject, or change anything.</p></div>",
            unsafe_allow_html=True,
        )

    # Hidden prompt hints: revealed only on demand, never shown up front.
    pending_question = None
    suggestions = _bylaw_suggestions(data)
    try:
        ideas = st.popover("Need ideas?")
    except Exception:  # pragma: no cover - popover always present in Streamlit 1.58
        ideas = st.expander("Need ideas?")
    with ideas:
        for index, suggestion in enumerate(suggestions):
            if st.button(suggestion, key=f"sugg_{city_stem}_{index}", width="stretch"):
                pending_question = suggestion

    for message in history:
        _render_bylaw_chat_message(st, message)

    typed = st.chat_input("Ask about the bylaw…", key=f"rag_chat_input_{city_stem}")
    question = typed or pending_question
    if question:
        _bylaw_chat_respond(st, question, index_path, chat_key)
    st.markdown("</div>", unsafe_allow_html=True)


def _bylaw_tab(st: Any, data: dict[str, Any]) -> None:
    """Conversational bylaw assistant — the whole tab is the chat now.

    The former nested sub-tabs (Ask Source / Explain Verified Rule / Why In
    Review / Prompt Library) collapsed into one chat: their example questions
    became the data-generated, hidden ``Need ideas?`` suggestions, and the
    section text now rides along in each answer's collapsed citation cards.
    """
    output_dir = Path(data.get("output_dir") or DEFAULT_OUTPUT_DIR)
    _ask_the_bylaw_panel(st, output_dir, data)


def _render_header(st: Any, city_label: str = "Burnaby R1", *, portfolio: bool = False) -> None:
    """Render a compact product-style header for the review console."""
    eyebrow = "M4 Verification Dashboard" if portfolio else "Verification Review Console"
    title = city_label if portfolio else f"{city_label} Rule Review"
    body = (
        "Review M4 first. V3 is retained only as the predecessor comparison. The deterministic verifier is the authority."
        if portfolio
        else "Use verified rules as trusted outputs, send uncertain rules to review, and inspect the source text before changing the verifier."
    )
    main_pill = "Current path: M4" if portfolio else "Verified-only output"
    st.markdown(
        f"""
<div class="app-header">
  <div>
    <div class="eyebrow">{html.escape(eyebrow)}</div>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(body)}</p>
  </div>
  <div class="status-legend">
    <span class="status-pill status-verified">{html.escape(main_pill)}</span>
    <span class="status-pill status-verified">Verified</span>
    <span class="status-pill status-review">Needs review</span>
    <span class="status-pill status-rejected">Rejected</span>
    <span class="status-pill status-not_used">Not used</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _sidebar_guidance(st: Any) -> None:
    """Keep short usage instructions visible near the filters."""
    with st.sidebar.expander("Decision language", expanded=False):
        st.markdown(
            """
- **Verified**: exact source support exists for the rule fields.
- **Review**: plausible, needs a human check.
- **Rejected**: the candidate conflicts with the verifier contract or source support.
- **Not used**: outside the current product scope.
- **Recall**: benchmark recall, not full-bylaw completeness.
"""
        )


def _router_item_row(item: dict[str, Any]) -> dict[str, Any]:
    """One reviewer-queue row: which rule, what it claims, why held, next step."""
    return {
        "Rule ID": item.get("rule_id") or item.get("candidate_id"),
        "Rule family": _humanize(item.get("rule_object")),
        "What it says": _short_display_quote(item.get("candidate_sentence") or "", 150),
        "Why it's held": _plain_label(item.get("review_category") or item.get("blocking_reason") or ""),
        "Next step": _short_display_quote(item.get("human_instruction") or item.get("next_step") or item.get("next_action") or "", 130),
    }


def _action_summary(st: Any, data: dict[str, Any]) -> None:
    """Surface the highest-value review-volume reduction paths.

    Each card's number is the exact set of queued rules in its action buckets,
    and an expander under the cards lists those precise rules (rule id, plain
    claim, why it is held, and the next step) so a reviewer can jump from a
    count straight to the rules behind it.
    """
    items_by_bucket: dict[str, list[dict[str, Any]]] = {}
    for item in data.get("router", {}).get("items", []):
        items_by_bucket.setdefault(str(item.get("action_bucket") or ""), []).append(item)

    categories = [
        (
            "Can improve with better source evidence",
            ("rerun_with_evidence_bundle", "retry_with_better_evidence", "condition_evidence_needed"),
            "Start here. These candidates may be held because the evidence packet is incomplete.",
        ),
        (
            "Need direction-word check",
            ("operator_review",),
            "The number is visible, but the source must prove minimum, maximum, or exact wording.",
        ),
        (
            "Need legal scope review",
            ("human_legal_review", "scope_review"),
            "These involve exceptions, scope, or interpretation. Keep them untrusted unless proven.",
        ),
    ]
    resolved = [
        (title, [rule for bucket in buckets for rule in items_by_bucket.get(bucket, [])], body)
        for title, buckets, body in categories
    ]

    html_cards = []
    for title, rules, body in resolved:
        html_cards.append(
            "<div class='action-card'>"
            f"<div class='action-value'>{len(rules)}</div>"
            f"<div class='action-title'>{html.escape(title)}</div>"
            f"<p>{html.escape(body)}</p>"
            "</div>"
        )
    st.markdown("<div class='action-grid'>" + "".join(html_cards) + "</div>", unsafe_allow_html=True)

    any_rules = any(rules for _, rules, _ in resolved)
    if any_rules:
        st.caption("Open a path to see exactly which rules it covers.")
    for title, rules, _ in resolved:
        if not rules:
            continue
        with st.expander(f"View these {len(rules)} rule{'s' if len(rules) != 1 else ''} · {title}", expanded=False):
            st.dataframe(_display_rows([_router_item_row(rule) for rule in rules]), width="stretch", hide_index=True)


def _sentence_card(st: Any, title: str, sentence: str, tone: str, caption: str = "") -> None:
    """Render one plain-language rule claim."""
    st.markdown(
        "<div class='sentence-card sentence-{}'>"
        "<div class='sentence-title'>{}</div>"
        "<p>{}</p>"
        "<span>{}</span>"
        "</div>".format(
            html.escape(tone),
            html.escape(title),
            html.escape(sentence),
            html.escape(str(caption or "")),
        ),
        unsafe_allow_html=True,
    )


def _rule_sentence(rule: dict[str, Any]) -> str:
    """Convert a structured rule into a reviewer-readable sentence.

    This is intentionally deterministic. It explains the current normalized
    fields and does not infer legal meaning beyond operator wording.
    """
    if not rule:
        return "No rule is available."

    rule_object = _humanize(rule.get("rule_object")) or "rule"
    scope = _humanize(rule.get("constraint_scope"))
    applies_to = str(rule.get("applies_to") or "").strip()
    subject = applies_to or "The relevant proposal item"
    condition = str(rule.get("condition") or "").strip()
    exception = str(rule.get("exception") or "").strip()

    value = rule.get("value")
    unit = str(rule.get("unit") or "").strip()
    value_text = _format_value_unit(value, unit)
    operator_phrase = _operator_phrase(rule.get("operator"), rule.get("constraint_type"), value_text)

    scope_phrase = f" for {scope.strip()}" if scope else ""
    sentence = f"{subject}: {rule_object}{scope_phrase} {operator_phrase}"
    if condition:
        sentence += f" when {condition}"
    if exception:
        sentence += f", except {exception}"
    return sentence.rstrip(" .") + "."


def _rule_option_label(rule: dict[str, Any]) -> str:
    if not rule:
        return ""
    rule_id = str(rule.get("rule_id") or rule.get("original_rule_id") or "").strip()
    family = _plain_label(rule.get("rule_object"))
    value = _format_value_unit(rule.get("value"), str(rule.get("unit") or ""))
    reason = _plain_label(rule.get("review_category") or rule.get("action_bucket") or rule.get("retry_decision"))
    parts = [part for part in (rule_id, family, value, reason) if part]
    return " | ".join(parts)


def _operator_phrase(operator: Any, constraint_type: Any, value_text: str) -> str:
    """Map machine operators to concise natural-language wording."""
    text = f"{operator or ''} {constraint_type or ''}".lower()
    if any(token in text for token in ("<=", "maximum", "max", "not_exceed")):
        return f"must be no more than {value_text}"
    if any(token in text for token in (">=", "minimum", "min", "at_least")):
        return f"must be at least {value_text}"
    if ">" in text:
        return f"must be more than {value_text}"
    if "<" in text:
        return f"must be less than {value_text}"
    if any(token in text for token in ("allowed", "permitted")):
        return "is permitted" if not value_text else f"is permitted with value {value_text}"
    if "required" in text:
        return "is required" if not value_text else f"is required above {value_text}"
    if value_text:
        return f"has value {value_text}"
    return "is claimed"


def _field_comparison_rows(candidate: dict[str, Any], verified: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a compact candidate-vs-verified field comparison table."""
    rows = []
    for field, label in [
        ("rule_object", "Rule object"),
        ("constraint_scope", "Scope"),
        ("applies_to", "Applies to"),
        ("operator", "Operator"),
        ("value", "Value"),
        ("unit", "Unit"),
        ("condition", "Condition"),
        ("exception", "Exception"),
    ]:
        candidate_value = _clean_value(candidate.get(field))
        verified_value = _clean_value(verified.get(field))
        rows.append(
            {
                "field": label,
                "review_candidate": candidate_value,
                "verified_rule": verified_value,
                "matches": "yes" if candidate_value == verified_value else "no",
            }
        )
    return rows


def _detail_sentence_panel(
    st: Any,
    title: str,
    sentences: list[str],
    evidence: dict[str, Any],
    rule_like: dict[str, Any],
) -> None:
    """Render human-readable detail plus bylaw lookup instructions."""
    st.markdown(f"### {title}")
    html_sentences = []
    for index, sentence in enumerate(sentences, start=1):
        html_sentences.append(
            "<div class='detail-sentence'>"
            f"<b>{index}.</b><span>{html.escape(sentence)}</span>"
            "</div>"
        )
    st.markdown("".join(html_sentences), unsafe_allow_html=True)
    _bylaw_lookup_panel(st, evidence, rule_like)


def _repair_detail_sentences(item: dict[str, Any], top_evidence: dict[str, Any]) -> list[str]:
    """Explain one evidence repair suggestion in plain English."""
    gaps = _list_text(item.get("support_gaps", []))
    repair_fields = _list_text(item.get("repairable_fields", []))
    match_reasons = _list_text(top_evidence.get("match_reasons", []))
    evidence_id = top_evidence.get("evidence_id") or "no suggested evidence"
    confidence = _display_value(item.get("best_repair_confidence"))
    return [
        f"Candidate claim: {_rule_sentence(item)}",
        f"The original evidence `{item.get('current_evidence_id')}` kept this rule in review because of: {gaps}.",
        f"The best suggested evidence is `{evidence_id}` with repair confidence {confidence}.",
        f"The repair mainly targets: {repair_fields}. Match reasons: {match_reasons}.",
        "This page suggests better evidence only; it does not itself promote the rule into verified output.",
    ]


def _intelligence_detail_sentences(item: dict[str, Any]) -> list[str]:
    """Explain one evidence intelligence item in plain English."""
    missing = _list_text(item.get("bundle_missing_fields", []))
    blocked = _list_text(item.get("blocked_by", []))
    safe = "safe to rerun through the deterministic verifier" if item.get("safe_retry") else "not safe to rerun automatically"
    return [
        f"Candidate claim: {_rule_sentence(item)}",
        f"The best evidence bundle has score {_display_value(item.get('bundle_score'))} and is {safe}.",
        f"The bundle currently supports: {_list_text(item.get('bundle_supported_fields', []))}. Missing fields: {missing}.",
        f"Blocked by: {blocked}.",
        f"Next action: `{item.get('next_action')}`. Bundle sentence: {item.get('bundle_sentence')}",
    ]


def _router_detail_sentences(item: dict[str, Any]) -> list[str]:
    """Explain one decision-tree route in plain English."""
    path = " -> ".join(_plain_label(part) for part in item.get("decision_path", [])) or "no path recorded"
    semantic_match = item.get("semantic_verified_rule_id") or "none"
    semantic_score = _display_value(item.get("semantic_score"))
    semantic_blockers = _list_text(item.get("semantic_guardrail_blockers", [])) or "none"
    return [
        f"Candidate claim: {item.get('candidate_sentence') or _rule_sentence(item)}",
        f"Original evidence says: {item.get('evidence_sentence') or 'no evidence sentence available'}",
        f"The review queue classifies this as {_plain_label(item.get('review_category'))} and suggests: {_plain_label(item.get('action_bucket'))}.",
        f"Meaning check: {_plain_label(item.get('semantic_review_class'))}. Closest verified match: `{semantic_match}` with score {semantic_score}; blockers: {semantic_blockers}.",
        f"Decision path: {path}.",
        f"Human instruction: {item.get('human_instruction')}",
        f"Evidence bundle summary: {item.get('bundle_sentence')}",
    ]


def _resolution_detail_sentences(item: dict[str, Any]) -> list[str]:
    """Explain one review-resolution label in plain English."""
    can_fix = (
        "has a plausible deterministic evidence-fix path"
        if item.get("can_promote_after_evidence_fix")
        else "does not currently have a safe deterministic promotion path"
    )
    semantic = item.get("semantic_verified_rule_id") or "none"
    score = _display_value(item.get("semantic_score"))
    return [
        f"Candidate claim: {item.get('candidate_sentence') or _rule_sentence(item)}",
        f"Original evidence says: {item.get('evidence_sentence') or 'no evidence sentence available'}",
        f"The final resolution is {_plain_label(item.get('resolution'))}, so the next step is {_plain_label(item.get('next_step_type'))}.",
        f"This item {can_fix}. Support gaps: {_list_text(item.get('support_gaps', []))}.",
        f"Closest meaning match: `{semantic}` with score {score}. Still missing: {_list_text(item.get('semantic_guardrail_blockers', []))}.",
        f"Bundle rerun decision: {_plain_label(item.get('bundle_rerun_decision'))} with gaps {_list_text(item.get('bundle_rerun_gaps', []))}.",
        f"Human next step: {item.get('human_next_step')}",
        f"Where to check in the bylaw: {item.get('where_to_find_it')}",
    ]


def _bundle_rerun_detail_sentences(item: dict[str, Any]) -> list[str]:
    """Explain one evidence-bundle rerun result in plain English."""
    decision = _plain_label(item.get("retry_decision") or "unknown")
    ready = "promotion-ready" if item.get("promotion_ready") else "not promotion-ready"
    return [
        f"Candidate claim: {_rule_sentence(item)}",
        f"The rerun used bundle `{item.get('bundle_evidence_id')}` built from: {_list_text(item.get('bundle_evidence_ids', []))}.",
        f"The deterministic verifier returned {decision} with gaps: {_list_text(item.get('retry_support_gaps', []))}.",
        f"The result is {ready}. Risk flags: {_list_text(item.get('promotion_risk_flags', []))}.",
        f"Recommendation: {item.get('promotion_recommendation') or 'keep in review until the verifier and benchmark support promotion'}.",
    ]


def _bundle_display_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """Return one evidence-like object for the bylaw lookup panel."""
    bundle = item.get("best_evidence_bundle", [])
    first = bundle[0] if bundle else {}
    return {
        "page": first.get("page"),
        "evidence_quote": first.get("evidence_quote") or item.get("original_evidence_sentence"),
    }


def _bundle_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Return display rows for a best evidence bundle."""
    return [
        {
            "evidence_id": evidence.get("evidence_id"),
            "page": evidence.get("page"),
            "type": evidence.get("evidence_type"),
            "score": evidence.get("raw_score"),
            "confidence": evidence.get("bundle_confidence"),
            "supported_fields": ", ".join(evidence.get("supported_fields", [])),
            "reasons": ", ".join(evidence.get("match_reasons", [])),
            "quote": evidence.get("evidence_quote"),
        }
        for evidence in item.get("best_evidence_bundle", [])
    ]


def _rerun_detail_sentences(item: dict[str, Any]) -> list[str]:
    """Explain one shadow rerun result in plain English."""
    decision = _plain_label(item.get("retry_decision") or "unknown")
    gaps = _list_text(item.get("retry_support_gaps", [])) or "none"
    risk_flags = _list_text(item.get("promotion_risk_flags", [])) or "none"
    promotion = "promotion-ready" if item.get("promotion_ready") else "not promotion-ready"
    return [
        f"Candidate claim: {_rule_sentence(item)}",
        f"The rerun replaced original evidence `{item.get('original_evidence_id')}` with retry evidence `{item.get('retry_evidence_id')}`.",
        f"The deterministic verifier returned {decision} with support gaps: {gaps}.",
        f"The shadow result is {promotion}. Promotion risk flags: {risk_flags}.",
        f"Recommendation: {item.get('promotion_recommendation') or 'inspect before promotion'}.",
    ]


def _safe_tuning_detail_sentences(item: dict[str, Any]) -> list[str]:
    """Explain one verifier-tuning backlog item in plain English."""
    gaps = _list_text(item.get("support_gaps", []))
    tests = _list_text(item.get("required_tests", []))
    guardrails = _list_text(item.get("guardrails", []))
    rerun = _plain_label(item.get("rerun_decision") or "not rerun")
    rerun_ready = "promotion-ready" if item.get("rerun_promotion_ready") else "not promotion-ready"
    return [
        f"Candidate claim: {_rule_sentence(item)}",
        f"This is a {_plain_label(item.get('tuning_type'))} tuning candidate because the blocking gaps are: {gaps}.",
        f"Proposed experiment: {item.get('proposed_experiment')}",
        f"Evidence rerun status: {rerun}, {rerun_ready}.",
        f"Required validation: {tests}.",
        f"Guardrails that must remain true: {guardrails}.",
    ]


def _bylaw_lookup_panel(st: Any, evidence: dict[str, Any], rule_like: dict[str, Any]) -> None:
    """Tell a reviewer how to find and verify the rule in the source bylaw."""
    page = evidence.get("page") or rule_like.get("page")
    quote = _quote_from_evidence(evidence)
    search_phrase = _search_phrase(rule_like, quote)

    st.markdown("#### How to find this in the bylaw")
    page_text = f"page `{page}`" if page not in (None, "") else "the cited section/page from the evidence packet"
    st.markdown(
        f"""
1. Open the [{_ACTIVE_SOURCE['label']}]({_ACTIVE_SOURCE['url']}).
2. Go to {page_text}. If the PDF page number is offset, use text search instead.
3. Search for the phrase below, then compare the candidate's value, unit, operator, scope, and condition against the bylaw wording.
4. If the passage contains words like `except`, `subject to`, `notwithstanding`, `unless`, or a covenant condition, keep the rule in human review unless the condition is explicitly modeled.
"""
    )
    st.code(search_phrase or "Search by rule object, value, unit, and applies_to fields.", language="text")
    if quote:
        st.markdown("#### Evidence quote")
        st.code(_short_display_quote(quote), language="text")


def _quote_from_evidence(evidence: dict[str, Any]) -> str:
    """Return the most useful evidence text available for reviewers."""
    return str(
        evidence.get("evidence_quote")
        or evidence.get("evidence_text")
        or evidence.get("source_context")
        or ""
    ).strip()


def _search_phrase(rule_like: dict[str, Any], quote: str) -> str:
    """Choose a short search phrase for the PDF find box."""
    if quote:
        cleaned = " ".join(quote.split())
        words = cleaned.split()
        return " ".join(words[:16])
    parts = [
        rule_like.get("rule_object"),
        rule_like.get("applies_to"),
        rule_like.get("value"),
        rule_like.get("unit"),
    ]
    return " ".join(str(part) for part in parts if part not in (None, ""))


def _short_display_quote(value: str, limit: int = 420) -> str:
    """Keep bylaw evidence quotes readable inside Streamlit."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _evidence_by_id(evidence_units: list[dict[str, Any]], evidence_id: Any) -> dict[str, Any]:
    """Find an evidence packet by id for bylaw lookup instructions."""
    return next((item for item in evidence_units if item.get("evidence_id") == evidence_id), {})


def _list_text(values: Any) -> str:
    """Format lists without exposing raw JSON syntax in summary sentences."""
    if not values:
        return "none"
    if isinstance(values, str):
        return _plain_label(values)
    return ", ".join(_plain_label(value) for value in values)


def _bar_table(st: Any, counts: dict[str, Any]) -> None:
    rows = [{"name": key, "count": value} for key, value in counts.items()]
    _bar_rows(st, rows, "name", "count")


def _bar_rows(st: Any, rows: list[dict[str, Any]], label_key: str, value_key: str) -> None:
    if not rows:
        st.caption("No data.")
        return
    max_value = max(float(row.get(value_key) or 0) for row in rows) or 1.0
    html_rows = []
    for row in rows:
        raw_label = str(row.get(label_key) or "")
        label = html.escape(_plain_label(raw_label))
        help_text = HELP_TEXT.get(raw_label, "")
        value = float(row.get(value_key) or 0)
        width = int((value / max_value) * 100)
        html_rows.append(
            "<div class='bar-row'>"
            f"<span title='{html.escape(help_text)}'>{label}</span>"
            f"<div class='bar-track'><div class='bar-fill' style='width:{width}%'></div></div>"
            f"<b>{int(value)}</b></div>"
        )
    st.markdown("\n".join(html_rows), unsafe_allow_html=True)


def _style(st: Any) -> None:
    # Design system — "Civic Primer". Three blocks: tokens, chrome, components.
    # STRICT status color semantics (verified green, review amber, rejected
    # red, not_used grey) are reused by every status-coded element below and
    # pinned by tests. De-boxing rule: at most ONE border level visible at a
    # time — cards inside expanders render flat, hairlines instead of frames.
    # Presentation only.
    st.markdown(
        """
<style>
/* ---- tokens ---- */
:root {
  --status-verified: #1a7f37;
  --status-review: #9a6700;
  --status-rejected: #cf222e;
  --status-not-used: #57606a;
  --ink: #1f2328;
  --ink-soft: #57606a;
  --accent: #0969da;
  --accent-strong: #0550ae;
  --lane-p9: #8250df;
  --canvas: #ffffff;
  --subtle: #f6f8fa;
  --line: #d0d7de;
  --hairline: #eaeef2;
}
/* ---- chrome ---- */
#MainMenu, footer, div[data-testid="stDecoration"] {display:none;}
header[data-testid="stHeader"] {background:transparent;}
html, body, [class*="css"] {font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;}
.block-container {padding-top: 1.1rem; max-width: 1180px;}
h1 {font-size:28px;} h2 {font-size:22px;} h3 {font-size:18px;}
h4 {font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--ink-soft); font-weight:700;}
/* ---- components ---- */
.app-header {display:flex; justify-content:space-between; align-items:flex-start; gap:16px; border:0; border-bottom:1px solid var(--hairline); border-radius:0; padding:6px 0 14px; background:transparent; margin-bottom:18px;}
.app-header h1 {font-size:28px; line-height:1.15; margin:2px 0 6px; color:var(--ink); letter-spacing:-.01em;}
.app-header p {margin:0; color:var(--ink-soft); font-size:14px;}
.eyebrow {font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--accent); font-weight:700;}
.status-legend {display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end;}
.status-pill {font-size:11px; font-weight:700; padding:3px 9px; border-radius:999px; color:#fff; letter-spacing:.02em;}
.status-pill.status-verified, .status-verified-bg {background:var(--status-verified);}
.status-pill.status-review, .status-review-bg {background:var(--status-review);}
.status-pill.status-rejected, .status-rejected-bg {background:var(--status-rejected);}
.status-pill.status-not_used, .status-not_used-bg {background:var(--status-not-used);}
.lane-pill {font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px; color:#fff;}
.lane-pill-p5 {background:var(--accent);}
.lane-pill-p9 {background:var(--lane-p9);}
.gate-pill {font-size:11px; font-weight:700; padding:2px 9px; border-radius:999px; color:#fff;}
.gate-pill-pass {background:var(--status-verified);}
.gate-pill-fail-closed {background:#475569;}
.gate-pill-scope {background:var(--status-review);}
.gate-pill-unsafe {background:var(--status-rejected);}
.gate-pill-review {background:var(--status-not-used);}
.metric-grid {display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr)); gap:10px; margin:12px 0 20px;}
.metric {border:1px solid var(--line); border-radius:8px; padding:13px 14px; background:var(--canvas); min-height:86px;}
.metric-verified {border-top:4px solid var(--status-verified);}
.metric-review {border-top:4px solid var(--status-review);}
.metric-rejected {border-top:4px solid var(--status-rejected);}
.metric-not_used {border-top:4px solid var(--status-not-used);}
.metric-label {font-size:10px; line-height:1.25; color:var(--ink-soft); text-transform:uppercase; font-weight:700; overflow-wrap:normal;}
.metric-value {font-size:28px; font-weight:700; color:var(--ink); font-variant-numeric: tabular-nums;}
.hero-grid {display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin:8px 0 12px;}
.hero-card {border:1px solid var(--line); border-radius:8px; padding:13px 14px; background:var(--canvas); min-height:108px;}
.hero-card-verified {border-top:4px solid var(--status-verified);}
.hero-card-review {border-top:4px solid var(--status-review);}
.hero-card-rejected {border-top:4px solid var(--status-rejected);}
.hero-card-not_used {border-top:4px solid var(--status-not-used);}
.hero-label {font-size:10px; line-height:1.25; color:var(--ink-soft); text-transform:uppercase; font-weight:700;}
.hero-value {font-size:25px; line-height:1.15; margin-top:8px; color:var(--ink); font-weight:750; font-variant-numeric:tabular-nums;}
.hero-note {font-size:12px; line-height:1.35; margin-top:7px; color:var(--ink-soft);}
.instruction-banner {border-left:4px solid var(--accent); background:var(--subtle); border-radius:0 8px 8px 0; color:var(--ink); padding:11px 14px; margin:10px 0 14px; font-size:14px;}
.timeline {display:grid; grid-template-columns:1fr 28px 1fr 28px 1fr 28px 1fr; align-items:stretch; gap:6px; margin:12px 0 16px;}
.timeline-compact {grid-template-columns:1fr 28px 1fr; max-width:760px;}
.timeline-step {border:1px solid var(--hairline); border-radius:8px; background:var(--canvas); padding:11px 12px; min-height:72px;}
.timeline-step b {display:block; color:var(--ink); font-size:13px;}
.timeline-step span {display:block; color:var(--ink-soft); margin-top:4px; font-size:12px;}
.timeline-active {border-color:var(--status-verified); border-top:4px solid var(--status-verified);}
.timeline-arrow {display:flex; align-items:center; justify-content:center; color:var(--ink-soft); font-weight:700;}
.legend-grid {display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; margin:12px 0 18px;}
.legend-grid div {border:1px solid var(--hairline); border-radius:8px; padding:10px 11px; background:var(--canvas);}
.legend-grid b {display:block; font-size:13px; color:var(--ink);}
.legend-grid span {display:block; margin-top:3px; color:var(--ink-soft); font-size:12px; line-height:1.35;}
.roadmap-grid {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:10px 0 12px;}
.roadmap-card {border:1px solid var(--hairline); border-radius:8px; background:var(--canvas); padding:13px 14px; min-height:104px;}
.roadmap-card b {display:block; color:var(--ink); margin-bottom:5px;}
.roadmap-card span {display:block; color:var(--ink-soft); font-size:14px; line-height:1.4;}
.trust-note {border:1px solid var(--hairline); border-radius:8px; background:var(--subtle); padding:11px 13px; color:var(--ink-soft); font-size:14px; margin:8px 0 12px;}
.guidance-grid, .action-grid {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:12px 0 20px;}
.guide-card, .action-card {border:0; border-radius:8px; background:var(--subtle); padding:14px 15px;}
.guide-card b {display:block; color:var(--ink); margin-bottom:5px;}
.guide-card span, .action-card p {color:var(--ink-soft); font-size:14px; margin:0;}
.action-value {font-size:28px; font-weight:700; color:var(--status-verified); font-variant-numeric: tabular-nums;}
.action-title {font-weight:700; color:var(--ink); margin:1px 0 4px;}
.sentence-card {border:1px solid var(--hairline); border-radius:8px; padding:15px 16px; min-height:142px; background:var(--canvas);}
.sentence-card p {font-size:17px; line-height:1.45; color:var(--ink); margin:8px 0 10px;}
.sentence-card span {font-size:12px; color:var(--ink-soft);}
.sentence-title {font-size:12px; text-transform:uppercase; letter-spacing:.06em; font-weight:700;}
.sentence-review {border-top:4px solid var(--status-review);}
.sentence-verified {border-top:4px solid var(--status-verified);}
.sentence-neutral {border-top:4px solid var(--status-not-used);}
.bylaw-section {border:0; border-left:3px solid var(--line); border-radius:0 8px 8px 0; background:var(--subtle); padding:12px 14px; margin:8px 0; line-height:1.6; color:var(--ink); white-space:pre-wrap; font-family: ui-monospace, "SF Mono", "Roboto Mono", monospace; font-size:13px;}
.bylaw-section h4 {margin:0 0 8px; color:var(--ink); letter-spacing:0; text-transform:none; font-size:14px;}
mark.evidence-hit {background:#fff3bf; border-bottom:2px solid var(--status-review); padding:1px 2px; border-radius:2px;}
.detail-sentence {display:grid; grid-template-columns:28px 1fr; gap:8px; border:0; border-radius:8px; background:var(--subtle); padding:11px 13px; margin:7px 0;}
.detail-sentence b {color:var(--accent);}
.detail-sentence span {color:var(--ink); line-height:1.45;}
.bar-row {display:grid; grid-template-columns:minmax(160px,240px) 1fr 52px; gap:12px; align-items:center; margin:7px 0;}
.bar-row span {color:var(--ink); font-size:14px;}
.bar-row b {color:var(--ink); text-align:right; font-variant-numeric: tabular-nums;}
.bar-track {height:12px; background:var(--subtle); border-radius:999px; overflow:hidden; border:1px solid var(--hairline);}
.bar-fill {height:100%; background:linear-gradient(90deg,var(--accent),var(--accent-strong));}
.matrix-table {width:100%; border-collapse:separate; border-spacing:0; font-size:13px;}
.matrix-table th {text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--ink-soft); padding:8px 10px; border-bottom:2px solid var(--line); background:var(--subtle); position:sticky; top:0;}
.matrix-table td {padding:8px 10px; border-bottom:1px solid var(--hairline); vertical-align:top; line-height:1.4;}
.matrix-table td.row-label {font-weight:600; color:var(--ink); white-space:nowrap;}
.matrix-cell {border-radius:6px; padding:6px 8px; display:block;}
.matrix-cell.status-verified {background:color-mix(in srgb, var(--status-verified) 12%, white); border-left:3px solid var(--status-verified);}
.matrix-cell.status-review {background:color-mix(in srgb, var(--status-review) 12%, white); border-left:3px solid var(--status-review);}
.matrix-cell.status-missing {background:color-mix(in srgb, var(--status-rejected) 8%, white); border-left:3px dashed var(--status-rejected); color:var(--ink-soft);}
.matrix-cell.status-na {color:#b6bec7;}
div[data-testid="stDataFrame"] {border:1px solid var(--hairline); border-radius:8px; overflow:hidden;}
div[data-testid="stExpander"] {border:1px solid var(--hairline); border-radius:8px;}
div[data-testid="stExpander"] .guide-card, div[data-testid="stExpander"] .action-card {background:transparent; padding:8px 0;}
/* ---- redesign: civic console (Summary hero, status bar, safety chip, chat) ---- */
.safety-chip {display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:700; padding:4px 11px; border-radius:999px; white-space:nowrap;}
.safety-ok {background:color-mix(in srgb, var(--status-verified) 12%, white); color:var(--status-verified);}
.safety-alert {background:color-mix(in srgb, var(--status-rejected) 12%, white); color:var(--status-rejected);}
.coverage-hero {display:grid; gap:12px; padding:22px 24px; border:1px solid var(--hairline); border-radius:12px; background:var(--canvas); box-shadow:0 1px 2px rgba(31,35,40,.05); margin:6px 0 18px;}
.coverage-hero .pct {font-size:46px; font-weight:750; color:var(--status-verified); line-height:1; font-variant-numeric:tabular-nums;}
.coverage-hero .cap {font-size:13px; color:var(--ink-soft);}
.coverage-bar {height:14px; border-radius:999px; overflow:hidden; display:flex; border:1px solid var(--hairline);}
.coverage-bar .seg {height:100%;}
.coverage-bar .seg-verified {background:var(--status-verified);}
.coverage-bar .seg-review {background:var(--status-review);}
.coverage-bar .seg-missed {background:var(--status-not-used);}
.coverage-key {display:flex; gap:16px; flex-wrap:wrap; font-size:12px; color:var(--ink-soft);}
.coverage-key b {color:var(--ink); font-variant-numeric:tabular-nums;}
.coverage-key i {font-style:normal; display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:middle;}
.status-bar {display:flex; height:34px; border-radius:8px; overflow:hidden; border:1px solid var(--hairline); margin:6px 0 18px;}
.status-bar .seg {display:flex; align-items:center; justify-content:center; color:#fff; font-size:12px; font-weight:700; min-width:0; white-space:nowrap; overflow:hidden;}
.status-bar .seg.verified {background:var(--status-verified);}
.status-bar .seg.review {background:var(--status-review);}
.status-bar .seg.rejected {background:var(--status-rejected);}
.status-bar .seg.not_used {background:var(--status-not-used);}
/* chat — scoped so it never bleeds into other tabs */
.chat-shell {max-width:780px; margin:0 auto;}
.chat-ribbon {font-size:12px; color:var(--ink-soft); background:var(--subtle); border:1px solid var(--hairline); border-radius:999px; padding:7px 14px; display:inline-flex; gap:8px; align-items:center; margin-bottom:6px;}
.chat-ribbon::before {content:'●'; color:var(--accent); font-size:9px;}
.mode-pill {font-size:11px; font-weight:700; padding:3px 9px; border-radius:999px; background:var(--subtle); color:var(--ink-soft);}
.mode-pill.live {background:color-mix(in srgb, var(--status-verified) 12%, white); color:var(--status-verified);}
.chat-empty {text-align:center; color:var(--ink-soft); padding:40px 0 14px;}
.chat-empty h2 {color:var(--ink); font-size:24px; margin:8px 0 6px; letter-spacing:-.01em;}
.chat-empty p {max-width:520px; margin:0 auto; font-size:14px; line-height:1.5;}
.citation {border:0; border-left:3px solid var(--accent); background:var(--subtle); border-radius:0 8px 8px 0; padding:10px 12px; margin:6px 0; font-size:13px; line-height:1.5; color:var(--ink);}
.citation .loc {font-family:ui-monospace,"SF Mono","Roboto Mono",monospace; font-size:11px; color:var(--ink-soft); white-space:nowrap; font-weight:700;}
[data-testid="stChatMessage"] {border:0; box-shadow:none; background:transparent; padding:6px 0;}
[data-testid="stChatInput"] textarea {border-radius:18px;}
@media (max-width: 900px) {
  .metric-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
  .hero-grid, .legend-grid {grid-template-columns:1fr 1fr;}
  .timeline {grid-template-columns:1fr;}
  .timeline-arrow {display:none;}
  .roadmap-grid {grid-template-columns:1fr;}
  .guidance-grid, .action-grid {grid-template-columns:1fr;}
  .bar-row {grid-template-columns:1fr;}
}
</style>
""",
        unsafe_allow_html=True,
    )


def _coverage_tab(st: Any, data: dict[str, Any], output_dir: Path) -> None:
    """What's missing vs gold, per rule family + the 101.4 matrix."""
    gold_path = gold_path_for(output_dir)
    gold = _read_json(gold_path, []) if gold_path else []
    benchmark = data.get("benchmark") or {}
    report = data.get("coverage_report") or {}

    st.markdown("#### Coverage by rule family")
    st.caption("Gold coverage = hand-checked bylaw rules the verifier has proven. Held rules wait in review; they never auto-promote.")
    rows = coverage_rows(data, gold, benchmark) if gold else report.get("family_rows", [])
    if rows:
        try:
            import pandas as pd

            frame = pd.DataFrame(rows)
            st.dataframe(
                frame,
                hide_index=True,
                width="stretch",
                column_config={
                    "coverage": st.column_config.ProgressColumn(
                        "Gold coverage", min_value=0.0, max_value=1.0, format="percent"
                    )
                },
            )
        except Exception:
            st.table(rows)

    gaps = gold_gap_rows(benchmark, gold)
    if gaps:
        with st.expander(f"Gold rules not yet proven ({len(gaps)})"):
            for gap in gaps:
                color = STATUS_COLORS.get("review" if gap["status"] == "review" else "rejected", "#57606a")
                st.markdown(
                    f"<div class='detail-sentence'><b style='color:{color}'>\u25cf</b>"
                    f"<span><b>{html.escape(gap['gold_id'])}</b> \u2014 {html.escape(gap['family'])} "
                    f"{html.escape(gap['claim'])} ({html.escape(gap['applies_to'])})<br>"
                    f"<small>{html.escape(gap['detail'])}</small></span></div>",
                    unsafe_allow_html=True,
                )
    elif gold:
        st.success("Every gold rule is verified.")

    if city_stem_from_dir(output_dir).startswith("burnaby"):
        st.markdown("#### Bylaw matrix \u2014 101.4 Development Regulations")
        st.caption(
            "Rows are regulations, columns are the bylaw's dwelling-type \u00d7 unit-count "
            "buckets. Green = verified (geometry-bound to its column), amber = held for "
            "review, red dashes = a gold rule not yet proven, grey = no claim."
        )
        grid = matrix_cells(data.get("verified") or [], data.get("review") or [], gold) if gold else report.get("matrix", {})
        if not grid:
            st.info("No matrix coverage report found. Rerun the slim verifier to generate coverage_report.json.")
            return
        st.markdown(matrix_table_html(grid), unsafe_allow_html=True)


def load_mvp_report() -> dict[str, Any]:
    """Load the final-demo product report used by the portfolio landing page."""
    return _read_json(MVP_REPORT_PATH, {})


def load_m4_source_audit() -> dict[str, Any]:
    """Load the source-PDF audit proving M4 used the expected city PDFs."""
    return _read_json(M4_SOURCE_AUDIT_PATH, {})


def _portfolio_metric_card(label: str, value: Any, note: str = "", tone: str = "") -> str:
    tone_class = f" hero-card-{tone}" if tone else ""
    return (
        f"<div class='hero-card{tone_class}'>"
        f"<div class='hero-label'>{html.escape(label)}</div>"
        f"<div class='hero-value'>{html.escape(str(value))}</div>"
        f"<div class='hero-note'>{html.escape(note)}</div>"
        "</div>"
    )


def _city_name(city: Any) -> str:
    return _plain_label(str(city or ""))


def _current_product_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in report.get("current_runs") or []:
        rows.append(
            {
                "city": _city_name(item.get("city")),
                "candidates": item.get("candidate_rule_count"),
                "verified": item.get("verified_rule_count"),
                "review": item.get("review_rule_count"),
                "rejected": item.get("rejected_rule_count"),
                "not_used": item.get("not_used_rule_count"),
                "precision": item.get("verified_precision"),
                "false_verified": item.get("false_verified_count"),
                "recall": item.get("verified_or_review_recall"),
                "status": item.get("status_label"),
            }
        )
    return rows


def _history_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    groups = [
        ("M4 current", report.get("current_runs") or []),
        ("V3 predecessor", report.get("v3_experimental_runs") or []),
    ]
    rows = []
    for group, items in groups:
        for item in items:
            rows.append(
                {
                    "version": group,
                    "city": _city_name(item.get("city")),
                    "lane": _plain_label(item.get("lane")),
                    "candidates": item.get("candidate_rule_count"),
                    "verified": item.get("verified_rule_count"),
                    "review": item.get("review_rule_count"),
                    "rejected": item.get("rejected_rule_count"),
                    "not_used": item.get("not_used_rule_count"),
                    "precision": item.get("verified_precision"),
                    "false_verified": item.get("false_verified_count"),
                    "recall": item.get("verified_or_review_recall"),
                    "status": item.get("status_label"),
                }
            )
    return rows


def _pdf_page_count(report: dict[str, Any], city: str) -> Any:
    for row in report.get("pdf_inventory") or []:
        if row.get("city") == city:
            return row.get("page_count")
    return ""


def _progress_timeline(st: Any) -> None:
    steps = [
        ("V3 predecessor", "foundation run"),
        ("M4 current", "final-demo path"),
    ]
    html_steps = []
    for index, (title, note) in enumerate(steps):
        active = " timeline-active" if index == len(steps) - 1 else ""
        html_steps.append(
            f"<div class='timeline-step{active}'><b>{html.escape(title)}</b><span>{html.escape(note)}</span></div>"
        )
        if index < len(steps) - 1:
            html_steps.append("<div class='timeline-arrow'>\u2192</div>")
    st.markdown(f"<div class='timeline timeline-compact'>{''.join(html_steps)}</div>", unsafe_allow_html=True)


def _plain_bucket_legend(st: Any) -> None:
    st.markdown(
        """
<div class="legend-grid">
  <div><b>Verified</b><span>safe to use</span></div>
  <div><b>Review</b><span>plausible, needs human check</span></div>
  <div><b>Rejected</b><span>unsafe or unsupported</span></div>
  <div><b>Not used</b><span>outside current product scope</span></div>
  <div><b>Recall</b><span>benchmark recall, not full-bylaw completeness</span></div>
</div>
""",
        unsafe_allow_html=True,
    )


def _source_audit_panel(st: Any, report: dict[str, Any]) -> None:
    audit = load_m4_source_audit()
    summary = audit.get("summary") or {}
    if not summary and not report.get("pdf_inventory"):
        st.info("No M4 source-PDF audit artifact found yet.")
        return
    st.markdown("#### Source audit")
    st.caption("This confirms M4 is reading the real bylaw PDFs. Calgary is treated as the full 1,053-page bylaw.")
    rows = []
    if summary:
        for city, row in summary.items():
            rows.append(
                {
                    "city": _city_name(city),
                    "pdf_pages": row.get("pdf_pages"),
                    "verified_rules": row.get("verified_rules"),
                    "cited_pages": ", ".join(str(page) for page in row.get("unique_cited_pages", [])),
                }
            )
    else:
        for row in report.get("pdf_inventory") or []:
            rows.append(
                {
                    "city": _city_name(row.get("city")),
                    "pdf_pages": row.get("page_count"),
                    "verified_rules": "",
                    "cited_pages": "",
                }
            )
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)
    failure_count = int(audit.get("failure_count") or 0)
    if failure_count:
        st.error(f"Source audit has {failure_count} failure(s). Treat M4 as unsafe until resolved.")
    else:
        st.success("Source audit passed: no source-PDF failures found.")


def _cloud_roadmap_panel(st: Any) -> None:
    st.markdown("#### Cloud roadmap")
    st.caption("Final-demo cloud work should stay secrets-managed and keep the verifier read-only from the dashboard.")
    st.markdown(
        """
<div class="roadmap-grid">
  <div class="roadmap-card"><b>Phase 1</b><span>Streamlit Cloud demo with curated M4 outputs and optional Gemini Flash Lite secrets for reviewer chat.</span></div>
  <div class="roadmap-card"><b>Phase 2</b><span>Containerized app with persistent artifact storage and environment-managed secrets.</span></div>
  <div class="roadmap-card"><b>Phase 3</b><span>Scheduled extraction and verification jobs, artifact versioning, and reviewer login if needed.</span></div>
</div>
""",
        unsafe_allow_html=True,
    )
    with st.expander("Streamlit Cloud secrets for Ask the Bylaw"):
        st.markdown("Use one hosted provider key. The dashboard still works in retrieval-only mode when no key is configured.")
        st.code(
            """BYLAW_RAG_PROVIDER = "gemini"
BYLAW_RAG_MODEL = "gemini-2.0-flash-lite"
GEMINI_API_KEY = "..."  # Streamlit Cloud secret only""",
            language="toml",
        )


def _portfolio_page(st: Any) -> None:
    """M4-first final-demo landing page."""
    report = load_mvp_report()
    if not report:
        st.info(f"No MVP report found at `{MVP_REPORT_PATH}`. Run `scripts/run_consolidated_prototype.py status`.")
        return

    current_rows = _current_product_rows(report)
    city_count = len([row for row in current_rows if row])
    verified_total = sum(int(row.get("verified") or 0) for row in current_rows)
    review_total = sum(int(row.get("review") or 0) for row in current_rows)
    calgary_pages = _pdf_page_count(report, "calgary_rcg") or "unknown"
    calgary_page_label = f"{int(calgary_pages):,} pages" if isinstance(calgary_pages, int) else f"{calgary_pages} pages"
    promoted = "yes" if (report.get("m4_promotion") or {}).get("promoted") else "no"
    cards = [
        _portfolio_metric_card("Current product path", "M4", "Native extraction + deterministic verifier", "verified"),
        _portfolio_metric_card("Safety status", _plain_label(report.get("overall_status")), f"M4 promoted: {promoted}", "verified"),
        _portfolio_metric_card("False verified", report.get("current_false_verified_total", 0), "must stay zero", "rejected"),
        _portfolio_metric_card("Cities tested", city_count, f"{verified_total} verified, {review_total} in review", "review"),
        _portfolio_metric_card("Calgary source", calgary_page_label, "full bylaw, not a seven-page slice", "not_used"),
    ]
    st.markdown("<div class='hero-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='instruction-banner'><b>Review M4 first.</b> V3 is retained only as the predecessor comparison. "
        "Downstream work must consume verified-only artifacts.</div>",
        unsafe_allow_html=True,
    )
    _progress_timeline(st)
    _plain_bucket_legend(st)

    st.markdown("#### Current M7 result")
    st.caption("These are the current product rows. Recall means benchmark recall, not full-bylaw completeness.")
    st.dataframe(_display_rows(current_rows), width="stretch", hide_index=True)

    def _build():
        import plotly.graph_objects as go

        cities = [row["city"] for row in current_rows]
        figure = go.Figure()
        figure.add_bar(name="Verified", x=cities, y=[row.get("verified") or 0 for row in current_rows], marker_color="#1a7f37")
        figure.add_bar(name="Review", x=cities, y=[row.get("review") or 0 for row in current_rows], marker_color="#9a6700")
        figure.update_layout(barmode="group", title="Current M7 verified and review counts")
        return figure

    if current_rows:
        _themed_plotly(st, _build)

    _source_audit_panel(st, report)
    _cloud_roadmap_panel(st)

    with st.expander("Predecessor comparison: M4 and V3", expanded=False):
        st.caption("Use this section to explain what changed from V3 to M4. It is not the default product path.")
        history = _history_rows(report)
        if history:
            st.dataframe(_display_rows(history), width="stretch", hide_index=True)
        else:
            st.info("No comparison rows found in the MVP report.")
        st.caption("Recall is benchmark recall from curated evaluation cases, not a promise that every bylaw clause was extracted.")

    st.caption("Pick a city in the sidebar to drill into its funnel, coverage gaps, review workbench, and Ask the Bylaw chat.")


def _unique(items: list[dict[str, Any]], key: str) -> list[str]:
    return sorted({str(item.get(key)) for item in items if item.get(key) not in (None, "")})


def _named_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {str(row.get("name")): int(row.get("count") or 0) for row in rows}


def _by_rule_id(rules: list[dict[str, Any]], rule_id: Any) -> dict[str, Any]:
    return next((rule for rule in rules if rule.get("rule_id") == rule_id), {})


def _source_text(rule: dict[str, Any]) -> str:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    return str(source.get("evidence_text") or source.get("source_context") or "")


def _humanize(value: Any) -> str:
    return _plain_label(value)


def _plain_label(value: Any) -> str:
    """Convert internal ids into reviewer-facing labels."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if text in PLAIN_LABELS:
        return PLAIN_LABELS[text]
    if "," in text:
        return ", ".join(_plain_label(part.strip()) for part in text.split(","))
    if " > " in text:
        return " > ".join(_plain_label(part.strip()) for part in text.split(" > "))
    cleaned = text.replace("_", " ").strip()
    if cleaned.isupper():
        return cleaned
    return cleaned[:1].upper() + cleaned[1:]


def _plain_join(values: Any) -> str:
    if not values:
        return "none"
    if isinstance(values, str):
        return _plain_label(values)
    return ", ".join(_plain_label(value) for value in values)


def _operator_short(operator: Any, constraint_type: Any = None) -> str:
    text = f"{operator or ''} {constraint_type or ''}".lower()
    if any(token in text for token in ("<=", "maximum", "max", "not_exceed")):
        return "No more than"
    if any(token in text for token in (">=", "minimum", "min", "at_least")):
        return "At least"
    if ">" in text:
        return "More than"
    if "<" in text:
        return "Less than"
    if "=" in text or "equal" in text:
        return "Exactly"
    return _plain_label(operator or constraint_type or "")


def _format_value_unit(value: Any, unit: str) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return f"{text} {unit}".strip()


def _clean_value(value: Any) -> str:
    return str(value or "").strip()


def _display_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert mixed JSON values into stable Streamlit table strings."""
    return [
        {
            _display_key(key): _display_table_value(key, value)
            for key, value in row.items()
        }
        for row in rows
    ]


def _display_key(key: Any) -> str:
    return _plain_label(key)


def _display_table_value(key: Any, value: Any) -> str:
    rendered = _display_value(value)
    key_text = str(key).lower()
    if any(raw in key_text for raw in RAW_VALUE_COLUMNS):
        return rendered
    return _plain_label(rendered)


def _display_value(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
