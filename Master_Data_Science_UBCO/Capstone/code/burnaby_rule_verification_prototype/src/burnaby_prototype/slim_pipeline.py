"""Current deterministic candidate/evidence verification pipeline.

Role: this IS the deterministic verifier (the product M7 verification path);
"Pipeline 5" in the filename is historical, not a separate or legacy lane.

The filename is historical: this is not a Pipeline 5-only path. M4, Pipeline 5,
Pipeline 9, and native candidate sets all enter as normalized candidates plus
evidence. This module does not parse PDFs, retrieve blocks, or call an LLM; it
verifies, reports, and writes verified-only GIS exports.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .config import load_config, write_json
from .consensus import detect_consensus_and_conflicts
from .coverage_report import build_coverage_report
from .decision_policy import NOT_USED, REJECTED, verification_decision_from_gaps
from .evidence_intelligence import build_evidence_intelligence, evidence_intelligence_markdown
from .evidence_repair import evidence_repair_markdown, suggest_evidence_repairs
from .evidence_rerun import (
    apply_bundle_promotions,
    bundle_promotion_markdown,
    evidence_bundle_rerun_markdown,
    evidence_rerun_markdown,
    run_evidence_bundle_reruns,
    run_evidence_reruns,
)
from .evidence_contract import annotate_evidence_quality, evidence_quality_summary
from .geometry_operator import derive_geometry_operator
from .gis_felt_export import _value_numeric, build_gis_felt_export, validate_gis_felt_export
from .review_assistant_packets import build_review_assistant_packets
from .review_resolution import build_review_resolution, review_resolution_markdown
from .review_router import build_review_layer, review_router_markdown
from .rule_graph import build_rule_graph
# Re-exported for scripts/build_proof_graph.py and other consumers that import
# the sentence helper from slim_pipeline; it now lives in the leaf rule_text.
from .rule_text import _rule_sentence
from .safe_tuning import build_safe_tuning_report, safe_tuning_markdown
from .semantic_review import build_semantic_review_report
from .source_repair import repair_evidence_from_source, source_pdf_for_config
from .table_matrix import anchor_evidence, build_page_matrices
from .verification import verify_candidates
from .verification_cache import build_verification_cache_report


GIS_CONTRACT_SCHEMA_VERSION = "1.1"
_GIS_CONTRACT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "gis_rule_contract.schema.json"
PROOF_DAG_REPORT_SCHEMA_VERSION = "proof_dag_report_v1"


def project_gis_contract_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Project a rich verified rule into the slim, GIS-facing contract shape.

    GIS needs the rule fields plus one citation, not the verifier's internal
    proof traces, support checks, normalization trace, or the raw candidate. Those
    stay in verified_rules.json. Keeping the contract slim means downstream code
    is not coupled to verifier internals and the file stays small.
    """
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    return {
        "rule_id": rule.get("rule_id"),
        "rule_object": rule.get("rule_object"),
        "constraint_type": rule.get("constraint_type"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "value_numeric": _value_numeric(rule.get("value")),
        "unit": rule.get("unit"),
        "condition": rule.get("condition"),
        "exception": rule.get("exception"),
        # Structured applicability for matrix-column rules (selectors +
        # qualifiers); None for selector-less rules. This is how a GIS
        # consumer disambiguates the four lot-coverage limits per parcel.
        "applicability": rule.get("applicability"),
        "geometry": derive_geometry_operator(rule),
        "verification_status": rule.get("verification_status"),
        "citation": {
            "document": source.get("document"),
            "url": source.get("url"),
            "page": source.get("page"),
            "evidence_id": source.get("evidence_id") or "",
            "quote": source.get("evidence_text"),
        },
    }


def deduplicate_verified_rules_for_export(
    verified_rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge exact source-aware duplicates for downstream GIS exports only.

    ``verified_rules.json`` remains the audit trail. GIS-facing files should not
    repeat the same legal rule and citation just because two extraction streams
    produced equivalent verified rows. The keeper is deterministic: lowest
    ``rule_id`` wins, and merged ids are reported for traceability.
    """
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for rule in verified_rules:
        groups.setdefault(_gis_export_dedupe_key(rule), []).append(rule)

    deduped: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    for members in groups.values():
        ordered = sorted(members, key=lambda item: str(item.get("rule_id") or ""))
        keeper = ordered[0]
        deduped.append(keeper)
        merged = ordered[1:]
        if merged:
            duplicate_groups.append(
                {
                    "keeper_rule_id": keeper.get("rule_id"),
                    "merged_rule_ids": [item.get("rule_id") for item in merged],
                    "count": len(ordered),
                }
            )

    deduped.sort(key=lambda item: str(item.get("rule_id") or ""))
    duplicate_groups.sort(key=lambda item: str(item.get("keeper_rule_id") or ""))
    return deduped, {
        "input_verified_rule_count": len(verified_rules),
        "export_rule_count": len(deduped),
        "duplicate_merged_count": sum(len(group["merged_rule_ids"]) for group in duplicate_groups),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_groups": duplicate_groups,
        "policy": "source_aware_exact_duplicate_merge_for_gis_exports_only",
    }


def _gis_export_dedupe_key(rule: dict[str, Any]) -> tuple[str, ...]:
    """Dedup the GIS export on a rule's LEGAL identity, not its citation.

    The key is the verified legal content (family, scope, applies_to, operator,
    value, unit, condition, exception, structured applicability). Source/citation
    fields (page, evidence_text, table headers, cell_value, document, url) are
    pure provenance and are deliberately EXCLUDED, so the same legal rule cited by
    two lanes or two evidence spans merges into one GIS row instead of being
    exported twice. ``condition`` and ``applicability`` stay in the key so
    genuinely distinct rules (laned vs laneless setback; SSMU 1-2 vs 3-4 unit
    matrix columns) remain separate. verified_rules.json keeps the full audit
    trail; only the GIS export is deduped.
    """
    applicability = rule.get("applicability")
    return tuple(
        _dedupe_text(value)
        for value in (
            rule.get("rule_object"),
            rule.get("constraint_type"),
            rule.get("constraint_scope"),
            rule.get("applies_to"),
            rule.get("operator"),
            rule.get("value"),
            rule.get("unit"),
            rule.get("condition"),
            rule.get("exception"),
            json.dumps(applicability, sort_keys=True) if isinstance(applicability, dict) else applicability,
        )
    )


def _dedupe_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def validate_gis_contract(contract: dict[str, Any]) -> None:
    """Validate the GIS contract against its JSON schema before writing.

    A contract that violates its own schema must never reach GIS, so this raises
    rather than warns. ``additionalProperties: false`` in the schema means a
    leaked internal field is caught here, not by a downstream consumer.
    """
    try:
        import jsonschema
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise SystemExit(
            "jsonschema is required to validate the GIS contract. Run `pip install -r requirements.txt`."
        ) from exc
    import json

    schema = json.loads(_GIS_CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(contract, schema)


def write_felt_exports(
    *,
    output_dir: Path,
    contract: dict[str, Any],
    review_rules: list[dict[str, Any]],
    evidence_rerun_report: dict[str, Any],
) -> dict[str, Any]:
    """Write Felt-ready CSV exports from verifier outputs.

    Felt can display CSV layers directly, but GIS geometry should still be
    generated from the verified-only contract. These CSVs are table/pop-up layers:
    verified rules are safe to consume, while review/rerun rows are explicitly
    marked as non-authoritative.
    """
    verified_path = output_dir / "felt_verified_rules.csv"
    review_path = output_dir / "felt_review_rules.csv"
    rerun_path = output_dir / "felt_evidence_rerun.csv"

    verified_rows = [_felt_verified_row(rule, contract) for rule in contract.get("rules", [])]
    review_rows = [_felt_review_row(rule) for rule in review_rules]
    rerun_rows = [_felt_rerun_row(item) for item in evidence_rerun_report.get("attempts", [])]

    _write_csv(verified_path, verified_rows, FELT_VERIFIED_FIELDS)
    _write_csv(review_path, review_rows, FELT_REVIEW_FIELDS)
    _write_csv(rerun_path, rerun_rows, FELT_RERUN_FIELDS)

    manifest = {
        "purpose": "Felt dashboard table layers; only felt_verified_rules.csv is authoritative for GIS.",
        "verified_rules_csv": verified_path.name,
        "review_rules_csv": review_path.name,
        "evidence_rerun_csv": rerun_path.name,
        "verified_rule_count": len(verified_rows),
        "review_rule_count": len(review_rows),
        "rerun_attempt_count": len(rerun_rows),
        "authoritative_file": "gis_rule_contract.json",
        "notes": [
            "Review and rerun exports are for inspection only.",
            "Do not use review_needed or rerun rows to calculate geometry until they become verified.",
        ],
    }
    write_json(output_dir / "felt_export_manifest.json", manifest)
    return manifest


FELT_VERIFIED_FIELDS = [
    "rule_id",
    "city",
    "zone",
    "status",
    "rule_object",
    "constraint_type",
    "constraint_scope",
    "applies_to",
    "operator",
    "value",
    "unit",
    "condition",
    "exception",
    "source_page",
    "evidence_id",
    "evidence_quote",
    "rule_sentence",
]

FELT_REVIEW_FIELDS = [
    "rule_id",
    "status",
    "review_action_bucket",
    "review_category",
    "triage_priority",
    "likely_status",
    "likely_correct_score",
    "rule_object",
    "constraint_scope",
    "applies_to",
    "operator",
    "value",
    "unit",
    "condition",
    "support_gaps",
    "source_page",
    "evidence_id",
    "evidence_quote",
    "rule_sentence",
]

FELT_RERUN_FIELDS = [
    "original_rule_id",
    "retry_decision",
    "promotion_ready",
    "rule_object",
    "constraint_scope",
    "applies_to",
    "operator",
    "value",
    "unit",
    "condition",
    "original_evidence_id",
    "retry_evidence_id",
    "retry_evidence_page",
    "retry_support_gaps",
    "promotion_risk_flags",
    "promotion_recommendation",
    "retry_evidence_quote",
    "rule_sentence",
]


def _felt_verified_row(rule: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    citation = rule.get("citation", {}) if isinstance(rule.get("citation"), dict) else {}
    return {
        "rule_id": rule.get("rule_id"),
        "city": contract.get("city"),
        "zone": contract.get("zone"),
        "status": "verified",
        "rule_object": rule.get("rule_object"),
        "constraint_type": rule.get("constraint_type"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "condition": rule.get("condition"),
        "exception": rule.get("exception"),
        "source_page": citation.get("page"),
        "evidence_id": citation.get("evidence_id"),
        "evidence_quote": citation.get("quote"),
        "rule_sentence": _rule_sentence(rule),
    }


def _felt_review_row(rule: dict[str, Any]) -> dict[str, Any]:
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    return {
        "rule_id": rule.get("rule_id"),
        "status": rule.get("verification_decision"),
        "review_action_bucket": rule.get("review_action_bucket"),
        "review_category": rule.get("review_category"),
        "triage_priority": rule.get("triage_priority") or rule.get("review_priority"),
        "likely_status": rule.get("likely_status"),
        "likely_correct_score": rule.get("likely_correct_score"),
        "rule_object": rule.get("rule_object"),
        "constraint_scope": rule.get("constraint_scope"),
        "applies_to": rule.get("applies_to"),
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "unit": rule.get("unit"),
        "condition": rule.get("condition"),
        "support_gaps": "; ".join(str(gap) for gap in rule.get("support_gaps", [])),
        "source_page": source.get("page"),
        "evidence_id": source.get("evidence_id"),
        "evidence_quote": source.get("evidence_text"),
        "rule_sentence": _rule_sentence(rule),
    }


def _felt_rerun_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "original_rule_id": item.get("original_rule_id"),
        "retry_decision": item.get("retry_decision"),
        "promotion_ready": item.get("promotion_ready"),
        "rule_object": item.get("rule_object"),
        "constraint_scope": item.get("constraint_scope"),
        "applies_to": item.get("applies_to"),
        "operator": item.get("operator"),
        "value": item.get("value"),
        "unit": item.get("unit"),
        "condition": item.get("condition"),
        "original_evidence_id": item.get("original_evidence_id"),
        "retry_evidence_id": item.get("retry_evidence_id"),
        "retry_evidence_page": item.get("retry_evidence_page"),
        "retry_support_gaps": "; ".join(str(gap) for gap in item.get("retry_support_gaps", [])),
        "promotion_risk_flags": "; ".join(str(flag) for flag in item.get("promotion_risk_flags", [])),
        "promotion_recommendation": item.get("promotion_recommendation"),
        "retry_evidence_quote": item.get("retry_evidence_quote"),
        "rule_sentence": _rule_sentence(item),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def run_slim_verification(
    config_path: Path | dict[str, Any],
    output_dir: Path,
    *,
    evidence_units: list[dict[str, Any]],
    rule_candidates: list[dict[str, Any]],
    input_mode: str,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Run the active product path from external extraction to validation output.

    This function intentionally does not parse PDFs or call an LLM. It assumes an
    extraction system already produced candidate/evidence JSON and focuses only
    on evidence quality, deterministic verification, and export files.

    ``config_path`` accepts either a config file path or an already-loaded
    config dict (as returned by ``load_config``, which stamps ``_config_path``
    for provenance). CLIs that load the config for the adapter pass the dict so
    the file is not parsed twice per run.
    """
    config = config_path if isinstance(config_path, dict) else load_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Source repair is evidence repair, not verification. It can add authentic
    # source context from cached bylaw PDFs and can force mismatched RAG evidence
    # to review, but the trust decision still belongs to verification.py.
    evidence_units, rule_candidates, source_repair_report = repair_evidence_from_source(
        evidence_units,
        rule_candidates,
        config,
        use_config_source_pdf=input_mode != "unit_test",
    )

    # Matrix anchoring is geometry-backed evidence enrichment: table evidence
    # gains a matrix_anchor (column bands + per-band cell text recovered from
    # the cached source PDF) so the verifier can BIND a value claim to its
    # table column. Without a PDF (or for prose evidence) nothing is attached
    # and verification behaves exactly as before — the layer is inert, never
    # a guess. Tests can pre-attach matrix_anchor blocks directly.
    matrix_pdf = source_pdf_for_config(config) if input_mode != "unit_test" else None
    matrix_anchor_report: dict[str, Any] = {"anchored": 0, "ambiguous_skipped": 0, "rows": []}
    if matrix_pdf is not None:
        matrix_anchor_report = anchor_evidence(evidence_units, build_page_matrices(matrix_pdf))

    # Evidence quality is separate from verification. It helps us diagnose
    # whether bad results come from weak evidence packets or strict verifier
    # logic.
    evidence_units = annotate_evidence_quality(evidence_units)
    evidence_summary = evidence_quality_summary(evidence_units, rule_candidates)

    # verification.py is the trust gate. It returns verified rules plus one
    # combined list of non-verified rules, which we split below into review,
    # rejected, and not_used for cleaner outputs.
    verification = verify_candidates(config, evidence_units, rule_candidates)
    verified_rules = verification["verified_rules"]
    review_rules, rejected_rules, not_used_rules = _split_non_verified(verification["review_needed"])

    # Cross-source consensus / conflict report (improvement #3). Reporting only:
    # consensus never verifies a rule and a conflict never silently picks a winner.
    consensus_report = detect_consensus_and_conflicts(rule_candidates)

    # Review intelligence layer. Order matters:
    # 1. triage ranks and labels review rules;
    # 2. evidence repair searches for alternate source packets;
    # 3. review audit combines both into next-action buckets.
    # None of these steps can promote a rule into verified. Review annotation
    # (triage/audit/router) runs once AFTER promotion via build_review_layer;
    # only evidence_intelligence is needed here, to feed the bundle rerun. The
    # repair/rerun reports are likewise built once, AFTER promotion, from the
    # remaining review rules — nothing reads a pre-promotion version of them.
    evidence_intelligence_report = build_evidence_intelligence(
        review_rules=review_rules,
        verified_rules=verified_rules,
        rule_candidates=rule_candidates,
        evidence_units=evidence_units,
    )
    evidence_bundle_rerun_report = run_evidence_bundle_reruns(
        config,
        evidence_units,
        rule_candidates,
        review_rules,
        evidence_intelligence_report,
    )
    verified_rules, review_rules, bundle_promotion_report = apply_bundle_promotions(
        verified_rules,
        review_rules,
        evidence_bundle_rerun_report,
    )

    # Bundle promotion changes the review queue. Rebuild reviewer-facing reports
    # from the remaining review rules so dashboard counts do not describe stale
    # pre-promotion items.
    evidence_repair_report = suggest_evidence_repairs(review_rules, evidence_units)
    evidence_intelligence_report = build_evidence_intelligence(
        review_rules=review_rules,
        verified_rules=verified_rules,
        rule_candidates=rule_candidates,
        evidence_units=evidence_units,
    )
    evidence_rerun_report = run_evidence_reruns(
        config,
        evidence_units,
        rule_candidates,
        review_rules,
        evidence_repair_report,
    )
    # Keep verifier runs deterministic and fast by default. Embedding semantic
    # ranking remains available to tests/tools via build_semantic_review_report,
    # but the product path uses structured signatures only.
    semantic_review_report = build_semantic_review_report(
        review_rules,
        verified_rules,
        enable_embeddings=False,
    )
    # One review-annotation entry point: triage -> audit -> router, applied once.
    review_rules, triage_report, review_audit_report, review_router_report = build_review_layer(
        review_rules,
        verified_rules,
        evidence_repair_report=evidence_repair_report,
        evidence_rerun_report=evidence_rerun_report,
        evidence_intelligence_report=evidence_intelligence_report,
        evidence_bundle_rerun_report=evidence_bundle_rerun_report,
        semantic_review_report=semantic_review_report,
    )
    review_resolution_report = build_review_resolution(
        review_rules,
        review_router_report=review_router_report,
        evidence_bundle_rerun_report=evidence_bundle_rerun_report,
    )
    review_assistant_packet_report = build_review_assistant_packets(
        review_rules,
        evidence_units,
        source_repair_report,
    )
    safe_tuning_report = build_safe_tuning_report(review_rules, review_audit_report, evidence_rerun_report)
    rule_graph_report = build_rule_graph(
        rule_candidates=rule_candidates,
        evidence_units=evidence_units,
        verified_rules=verified_rules,
        review_rules=review_rules,
    )
    include_matrix_report = any(
        rule.get("applicability") or rule.get("matrix_bands")
        for rule in [*verified_rules, *review_rules, *rejected_rules, *not_used_rules]
    )
    coverage_report = build_coverage_report(
        rule_candidates=rule_candidates,
        verified_rules=verified_rules,
        review_rules=review_rules,
        rejected_rules=rejected_rules,
        not_used_rules=not_used_rules,
        include_matrix=include_matrix_report,
    )
    proof_dag_report = extract_proof_dag_report([
        ("verified", verified_rules),
        ("review_needed", review_rules),
        ("rejected", rejected_rules),
        ("not_used", not_used_rules),
    ])
    previous_cache = _read_existing_json(output_dir / "verification_cache.json")
    verification_cache_report = build_verification_cache_report(
        config=config,
        evidence_units=evidence_units,
        rule_candidates=rule_candidates,
        verified_rules=verified_rules,
        review_rules=[*review_rules, *rejected_rules, *not_used_rules],
        previous_cache=previous_cache,
        cache_enabled=use_cache,
    )

    write_json(output_dir / "evidence_units.json", evidence_units)
    write_json(output_dir / "source_repair_report.json", source_repair_report)
    write_json(output_dir / "matrix_anchor_report.json", matrix_anchor_report)
    write_json(output_dir / "evidence_quality_report.json", evidence_summary)
    write_json(output_dir / "rule_candidates.json", rule_candidates)
    write_json(output_dir / "verified_rules.json", verified_rules)
    write_json(output_dir / "review_needed.json", review_rules)
    write_json(output_dir / "rejected_rules.json", rejected_rules)
    write_json(output_dir / "not_used.json", not_used_rules)
    write_json(output_dir / "rule_consensus.json", consensus_report["consensus"])
    write_json(output_dir / "rule_conflicts.json", consensus_report["conflicts"])
    write_json(output_dir / "evidence_intelligence.json", evidence_intelligence_report)
    write_json(output_dir / "evidence_repair_suggestions.json", evidence_repair_report)
    write_json(output_dir / "evidence_rerun_report.json", evidence_rerun_report)
    write_json(output_dir / "evidence_rerun_verified.json", evidence_rerun_report.get("verified_after_rerun", []))
    write_json(output_dir / "evidence_rerun_promotion_ready.json", evidence_rerun_report.get("promotion_ready", []))
    write_json(output_dir / "evidence_bundle_rerun_report.json", evidence_bundle_rerun_report)
    write_json(output_dir / "evidence_bundle_promotion_ready.json", evidence_bundle_rerun_report.get("promotion_ready", []))
    write_json(output_dir / "bundle_promotion_report.json", bundle_promotion_report)
    write_json(output_dir / "bundle_promoted_rules.json", bundle_promotion_report.get("promoted_rules", []))
    write_json(output_dir / "rule_graph.json", rule_graph_report)
    write_json(output_dir / "review_router.json", review_router_report)
    write_json(output_dir / "review_resolution.json", review_resolution_report)
    write_json(output_dir / "review_assistant_packets.json", review_assistant_packet_report)
    write_json(output_dir / "proof_dag_report.json", proof_dag_report)
    write_json(output_dir / "coverage_report.json", coverage_report)
    write_json(output_dir / "verification_cache.json", verification_cache_report)
    write_json(output_dir / "semantic_review_report.json", semantic_review_report)
    write_json(output_dir / "safe_verifier_tuning_candidates.json", safe_tuning_report)
    # Markdown reports are duplicated from JSON on purpose: JSON powers the
    # dashboard, while markdown gives a quick presentation/debugging artifact.
    (output_dir / "evidence_intelligence_report.md").write_text(evidence_intelligence_markdown(evidence_intelligence_report), encoding="utf-8")
    (output_dir / "evidence_repair_report.md").write_text(evidence_repair_markdown(evidence_repair_report), encoding="utf-8")
    (output_dir / "evidence_rerun_report.md").write_text(evidence_rerun_markdown(evidence_rerun_report), encoding="utf-8")
    (output_dir / "evidence_bundle_rerun_report.md").write_text(evidence_bundle_rerun_markdown(evidence_bundle_rerun_report), encoding="utf-8")
    (output_dir / "bundle_promotion_report.md").write_text(bundle_promotion_markdown(bundle_promotion_report), encoding="utf-8")
    (output_dir / "review_router_report.md").write_text(review_router_markdown(review_router_report), encoding="utf-8")
    (output_dir / "review_resolution_report.md").write_text(review_resolution_markdown(review_resolution_report), encoding="utf-8")
    (output_dir / "safe_verifier_tuning_candidates.md").write_text(safe_tuning_markdown(safe_tuning_report), encoding="utf-8")
    # Keep this compatibility file so the benchmark can run without special
    # casing the old retrieval pipeline. Retrieval is not active here.
    write_json(
        output_dir / "retrieved_blocks.json",
        {
            "retrieval_backend": "not_applicable",
            "embedding_model": None,
            "device": None,
            "deduped_blocks_for_llm": [],
            "notes": "Slim verifier used external candidate/evidence JSON; no retrieval was run.",
        },
    )

    # Compatibility export for downstream tools that still expect a GIS contract.
    # The core Stage 1 product is the validation split above; this file remains
    # verified-only so downstream consumers cannot accidentally use review items.
    # It is SLIM by design: only the rule fields plus one compact citation. The
    # full proof/debug detail stays in verified_rules.json so the contract does
    # not couple GIS to internal verifier scaffolding, and it is schema-validated
    # at write time so any drift (e.g. a leaked debug field) fails loudly.
    export_verified_rules, export_deduplication_report = deduplicate_verified_rules_for_export(verified_rules)
    contract = {
        "city": config["city"],
        "zone": config["zone"],
        "source_document": config.get("source_document"),
        "source_url": config.get("source_url"),
        "input_mode": input_mode,
        "schema_version": GIS_CONTRACT_SCHEMA_VERSION,
        "deduplication": export_deduplication_report,
        "rules": [project_gis_contract_rule(rule) for rule in export_verified_rules],
    }
    validate_gis_contract(contract)
    write_json(output_dir / "gis_rule_contract.json", contract)

    # Rich GIS/Felt handoff: typed value_numeric + coarse geometry_target,
    # projected from verified rules only. Pure post-verification projection, so
    # it cannot move any trust metric.
    gis_felt = build_gis_felt_export(export_verified_rules, review_rules, not_used_rules, config)
    gis_felt["input_mode"] = input_mode
    validate_gis_felt_export(gis_felt)
    write_json(output_dir / "gis_felt_export.json", gis_felt)

    felt_export_manifest = write_felt_exports(
        output_dir=output_dir,
        contract=contract,
        review_rules=review_rules,
        evidence_rerun_report=evidence_rerun_report,
    )

    summary = _summary(
        output_dir=output_dir,
        input_mode=input_mode,
        evidence_units=evidence_units,
        rule_candidates=rule_candidates,
        verified_rules=verified_rules,
        review_rules=review_rules,
        rejected_rules=rejected_rules,
        not_used_rules=not_used_rules,
        evidence_summary=evidence_summary,
        triage_report=triage_report,
        evidence_intelligence_report=evidence_intelligence_report,
        evidence_repair_report=evidence_repair_report,
        evidence_rerun_report=evidence_rerun_report,
        evidence_bundle_rerun_report=evidence_bundle_rerun_report,
        bundle_promotion_report=bundle_promotion_report,
        review_audit_report=review_audit_report,
        rule_graph_report=rule_graph_report,
        proof_dag_report=proof_dag_report,
        coverage_report=coverage_report,
        review_resolution_report=review_resolution_report,
        review_assistant_packet_report=review_assistant_packet_report,
        verification_cache_report=verification_cache_report,
        semantic_review_report=semantic_review_report,
        safe_tuning_report=safe_tuning_report,
        felt_export_manifest=felt_export_manifest,
    )
    write_json(output_dir / "slim_summary.json", summary)
    write_json(output_dir / "validation_report.json", _validation_report(summary))
    _write_slim_report(output_dir / "slim_report.md", summary)
    _write_slim_diagram(output_dir / "pipeline_diagram.mmd")
    return summary


def _split_non_verified(
    rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate non-verified rules into human review, hard rejection, and not-used."""
    review_rules: list[dict[str, Any]] = []
    rejected_rules: list[dict[str, Any]] = []
    not_used_rules: list[dict[str, Any]] = []
    for rule in rules:
        decision = rule.get("verification_decision") or verification_decision_from_gaps(rule.get("support_gaps", []))
        normalized = dict(rule)
        normalized["verification_decision"] = decision
        if decision == REJECTED:
            rejected_rules.append(normalized)
        elif decision == NOT_USED:
            not_used_rules.append(normalized)
        else:
            review_rules.append(normalized)
    return review_rules, rejected_rules, not_used_rules


def _read_existing_json(path: Path) -> dict[str, Any] | None:
    """Read an existing output JSON file if present.

    Used only for cache hit/miss diagnostics. A malformed cache is ignored
    rather than blocking verification because cache is non-authoritative.
    """
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def extract_proof_dag_report(bucketed_rules: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """Move full proof DAGs into one sidecar and leave compact refs on rules."""
    dags: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    for bucket, rules in bucketed_rules:
        for rule in rules:
            dag = rule.pop("proof_dag", None)
            if not isinstance(dag, dict):
                continue
            dag_id = f"{rule.get('rule_id') or dag.get('candidate_id') or len(dags) + 1}::proof_dag"
            dag = {**dag, "dag_id": dag_id, "rule_id": rule.get("rule_id"), "bucket": bucket}
            dags.append(dag)
            bucket_counts[bucket] += 1
            for status, count in (dag.get("status_counts") or {}).items():
                status_counts[str(status)] += int(count or 0)
            rule["proof_dag_ref"] = dag_id
            rule["proof_dag_summary"] = {
                "support_gap_count": dag.get("support_gap_count", 0),
                "status_counts": dag.get("status_counts", {}),
            }
    return {
        "schema_version": PROOF_DAG_REPORT_SCHEMA_VERSION,
        "dag_count": len(dags),
        "bucket_counts": [{"name": name, "count": count} for name, count in sorted(bucket_counts.items())],
        "status_counts": [{"name": name, "count": count} for name, count in sorted(status_counts.items())],
        "dags": dags,
    }


def _summary(
    *,
    output_dir: Path,
    input_mode: str,
    evidence_units: list[dict[str, Any]],
    rule_candidates: list[dict[str, Any]],
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    rejected_rules: list[dict[str, Any]],
    not_used_rules: list[dict[str, Any]],
    evidence_summary: dict[str, Any],
    triage_report: dict[str, Any],
    evidence_intelligence_report: dict[str, Any],
    evidence_repair_report: dict[str, Any],
    evidence_rerun_report: dict[str, Any],
    evidence_bundle_rerun_report: dict[str, Any],
    bundle_promotion_report: dict[str, Any],
    review_audit_report: dict[str, Any],
    rule_graph_report: dict[str, Any],
    proof_dag_report: dict[str, Any],
    coverage_report: dict[str, Any],
    review_resolution_report: dict[str, Any],
    review_assistant_packet_report: dict[str, Any],
    verification_cache_report: dict[str, Any],
    semantic_review_report: dict[str, Any],
    safe_tuning_report: dict[str, Any],
    felt_export_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact run summary for humans and benchmark/debugging."""
    gaps = Counter(
        gap
        for rule in [*review_rules, *rejected_rules, *not_used_rules]
        for gap in rule.get("support_gaps", [])
    )
    return {
        "pipeline": "slim_verification_first",
        "input_mode": input_mode,
        "output_dir": _display_path(output_dir),
        "evidence_unit_count": len(evidence_units),
        "candidate_rule_count": len(rule_candidates),
        "verified_rule_count": len(verified_rules),
        "review_rule_count": len(review_rules),
        "rejected_rule_count": len(rejected_rules),
        "not_used_rule_count": len(not_used_rules),
        "evidence_quality": evidence_summary,
        "review_triage": triage_report.get("summary", {}),
        "evidence_intelligence": {
            "review_rule_count": evidence_intelligence_report.get("review_rule_count", 0),
            "evidence_index_count": evidence_intelligence_report.get("evidence_index_count", 0),
            "safe_retry_count": evidence_intelligence_report.get("safe_retry_count", 0),
            "blocked_count": evidence_intelligence_report.get("blocked_count", 0),
            "summary": evidence_intelligence_report.get("summary", {}),
        },
        "evidence_repair": {
            "suggestion_count": evidence_repair_report.get("suggestion_count", 0),
            "alternative_evidence_count": evidence_repair_report.get("alternative_evidence_count", 0),
            "retry_candidate_count": evidence_repair_report.get("retry_candidate_count", 0),
        },
        "evidence_rerun": {
            "attempt_count": evidence_rerun_report.get("attempt_count", 0),
            "verified_after_rerun_count": evidence_rerun_report.get("verified_after_rerun_count", 0),
            "promotion_ready_count": evidence_rerun_report.get("promotion_ready_count", 0),
            "review_after_rerun_count": evidence_rerun_report.get("review_after_rerun_count", 0),
            "rejected_after_rerun_count": evidence_rerun_report.get("rejected_after_rerun_count", 0),
            "skipped_count": evidence_rerun_report.get("skipped_count", 0),
        },
        "evidence_bundle_rerun": {
            "attempt_count": evidence_bundle_rerun_report.get("attempt_count", 0),
            "verified_after_rerun_count": evidence_bundle_rerun_report.get("verified_after_rerun_count", 0),
            "promotion_ready_count": evidence_bundle_rerun_report.get("promotion_ready_count", 0),
            "review_after_rerun_count": evidence_bundle_rerun_report.get("review_after_rerun_count", 0),
            "rejected_after_rerun_count": evidence_bundle_rerun_report.get("rejected_after_rerun_count", 0),
            "skipped_count": evidence_bundle_rerun_report.get("skipped_count", 0),
        },
        "bundle_promotion": {
            "promotion_count": bundle_promotion_report.get("promotion_count", 0),
            "review_removed_count": bundle_promotion_report.get("review_removed_count", 0),
            "rejected_promotion_count": bundle_promotion_report.get("rejected_promotion_count", 0),
            "promoted_rule_ids": bundle_promotion_report.get("promoted_rule_ids", []),
        },
        "review_audit": review_audit_report.get("summary", {}),
        "review_resolution": {
            "review_rule_count": review_resolution_report.get("review_rule_count", 0),
            "summary": review_resolution_report.get("summary", {}),
        },
        "review_assistant_packets": {
            "packet_count": review_assistant_packet_report.get("packet_count", 0),
            "advisory_only": review_assistant_packet_report.get("advisory_only", True),
        },
        "rule_graph": {
            "node_count": rule_graph_report.get("node_count", 0),
            "edge_count": rule_graph_report.get("edge_count", 0),
            "summary": rule_graph_report.get("summary", {}),
        },
        "proof_dag": {
            "dag_count": proof_dag_report.get("dag_count", 0),
            "bucket_counts": proof_dag_report.get("bucket_counts", []),
            "status_counts": proof_dag_report.get("status_counts", []),
        },
        "coverage_report": {
            "family_count": len(coverage_report.get("family_rows", [])),
            "matrix_row_count": len((coverage_report.get("matrix") or {}).get("rows", [])),
        },
        "verification_cache": {
            "cache_enabled": verification_cache_report.get("cache_enabled"),
            "entry_count": verification_cache_report.get("entry_count", 0),
            "cache_hit_count": verification_cache_report.get("cache_hit_count", 0),
            "safe_reuse_count": verification_cache_report.get("safe_reuse_count", 0),
            "cache_miss_count": verification_cache_report.get("cache_miss_count", 0),
            "cache_mode": verification_cache_report.get("cache_mode"),
        },
        "semantic_review": {
            "review_rule_count": semantic_review_report.get("review_rule_count", 0),
            "verified_rule_count": semantic_review_report.get("verified_rule_count", 0),
            "high_similarity_count": semantic_review_report.get("high_similarity_count", 0),
            "summary": semantic_review_report.get("summary", {}),
        },
        "safe_tuning": {
            "candidate_count": safe_tuning_report.get("candidate_count", 0),
            "tuning_type_counts": safe_tuning_report.get("tuning_type_counts", []),
        },
        "felt_export": felt_export_manifest,
        "top_review_reasons": [
            {"reason": reason, "count": count}
            for reason, count in gaps.most_common(10)
        ],
    }


def _write_slim_report(path: Path, summary: dict[str, Any]) -> None:
    """Write a short markdown report that explains the run at a glance."""
    lines = [
        "# Slim Verification Report",
        "",
        "```text",
        "Pipeline 5 candidates/evidence -> deterministic validation -> verified/review/rejected/not_used",
        "```",
        "",
        f"- Input mode: `{summary['input_mode']}`",
        f"- Evidence units: {summary['evidence_unit_count']}",
        f"- Candidate rules: {summary['candidate_rule_count']}",
        f"- Verified rules: {summary['verified_rule_count']}",
        f"- Review needed: {summary['review_rule_count']}",
        f"- Rejected rules: {summary['rejected_rule_count']}",
        f"- Not used / traceability only: {summary['not_used_rule_count']}",
        f"- Evidence match rate: {summary['evidence_quality']['candidate_evidence_match_rate']:.2f}",
        f"- Value grounding rate: {summary['evidence_quality']['candidate_value_grounding_rate']:.2f}",
        f"- Table context completion: {summary['evidence_quality']['table_context_completion_rate']:.2f}",
        f"- Evidence repair suggestions: {summary['evidence_repair']['suggestion_count']}",
        f"- Suggestions with alternative evidence: {summary['evidence_repair']['alternative_evidence_count']}",
        f"- Retry candidates from evidence repair: {summary['evidence_repair']['retry_candidate_count']}",
        f"- Evidence intelligence safe bundle retries: {summary['evidence_intelligence']['safe_retry_count']}",
        f"- Evidence rerun attempts: {summary['evidence_rerun']['attempt_count']}",
        f"- Promotion-ready shadow reruns: {summary['evidence_rerun']['promotion_ready_count']}",
        f"- Evidence bundle rerun attempts: {summary['evidence_bundle_rerun']['attempt_count']}",
        f"- Promotion-ready bundle reruns: {summary['evidence_bundle_rerun']['promotion_ready_count']}",
        f"- Guarded bundle promotions: {summary['bundle_promotion']['promotion_count']}",
        f"- Rule graph nodes / edges: {summary['rule_graph']['node_count']} / {summary['rule_graph']['edge_count']}",
        f"- Proof DAG sidecar entries: {summary['proof_dag']['dag_count']}",
        f"- Cache hits / misses: {summary['verification_cache']['cache_hit_count']} / {summary['verification_cache']['cache_miss_count']}",
        f"- Semantic high-similarity review items: {summary['semantic_review']['high_similarity_count']}",
        f"- Review items potentially promotable after evidence fix: {summary['review_resolution']['summary'].get('can_promote_after_evidence_fix_count', 0)}",
        f"- Safe verifier tuning candidates: {summary['safe_tuning']['candidate_count']}",
        f"- Felt verified-rule CSV rows: {summary['felt_export']['verified_rule_count']}",
        "",
        "## Review Actions",
        "",
    ]
    for item in summary.get("review_audit", {}).get("action_counts", []):
        lines.append(f"- `{item['name']}`: {item['count']}")
    lines.extend(
        [
            "",
            "## Top Review / Rejection Reasons",
            "",
        ]
    )
    for item in summary["top_review_reasons"]:
        lines.append(f"- `{item['reason']}`: {item['count']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validation_report(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a compact dashboard-ready validation summary.

    Unlike the benchmark report, this does not need gold labels. It simply
    describes how this extraction run was routed by the verifier.
    """
    candidate_count = summary["candidate_rule_count"]
    bucket_counts = {
        "verified": summary["verified_rule_count"],
        "review_needed": summary["review_rule_count"],
        "rejected": summary["rejected_rule_count"],
        "not_used": summary["not_used_rule_count"],
    }
    return {
        "pipeline": summary["pipeline"],
        "input_mode": summary["input_mode"],
        "output_dir": summary["output_dir"],
        "candidate_rule_count": candidate_count,
        "bucket_counts": bucket_counts,
        "bucket_rates": {
            bucket: round(count / candidate_count, 3) if candidate_count else 0.0
            for bucket, count in bucket_counts.items()
        },
        "evidence_quality": summary["evidence_quality"],
        "review_triage": summary["review_triage"],
        "evidence_intelligence": summary["evidence_intelligence"],
        "evidence_repair": summary["evidence_repair"],
        "evidence_rerun": summary["evidence_rerun"],
        "evidence_bundle_rerun": summary["evidence_bundle_rerun"],
        "bundle_promotion": summary["bundle_promotion"],
        "review_audit": summary["review_audit"],
        "review_resolution": summary["review_resolution"],
        "rule_graph": summary["rule_graph"],
        "proof_dag": summary["proof_dag"],
        "coverage_report": summary["coverage_report"],
        "verification_cache": summary["verification_cache"],
        "semantic_review": summary["semantic_review"],
        "safe_tuning": summary["safe_tuning"],
        "felt_export": summary["felt_export"],
        "top_review_reasons": summary["top_review_reasons"],
        "notes": [
            "verified is the only bucket eligible for downstream rule consumption",
            "review_needed means plausible but not fully proven",
            "rejected means contradiction or unsafe malformed candidate",
            "not_used means traceability-only or outside the current validation contract",
        ],
    }


def _display_path(path: Path) -> str:
    """Return a stable report path without leaking local machine temp paths."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _write_slim_diagram(path: Path) -> None:
    """Write a Mermaid diagram of the active verification-first path."""
    path.write_text(
        """flowchart LR
  A[Pipeline 5 Candidate Rules] --> C[Normalize + Evidence Lookup]
  B[Pipeline 5 Evidence Packets] --> C
  C --> D[Deterministic Verification]
  D --> E[verified_rules.json]
  D --> F[review_needed.json]
  D --> G[rejected_rules.json]
  D --> H[not_used.json]
  F --> K[Evidence Intelligence]
  K --> L[Evidence Bundle Rerun]
  K --> M[Review Decision Tree]
  C --> N[Rule Graph]
  E --> I[GIS/Felt verified-only export]
  E --> J[Benchmark]
  F --> J
  G --> J
  H --> J
  K --> O[Dashboard]
  L --> O
  M --> O
  N --> O
""",
        encoding="utf-8",
    )
