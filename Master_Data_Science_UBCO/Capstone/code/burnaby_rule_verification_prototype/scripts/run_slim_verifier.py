#!/usr/bin/env python3
"""Run the final Pipeline 5 verification-first path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import resolve_city_paths, upstream_city_segment
from burnaby_prototype.config import load_config
from burnaby_prototype.slim_pipeline import run_slim_verification
from burnaby_prototype.zihao_adapter import adapt_pipeline5_registry, adapt_zihao_outputs


def _default_zihao_dir(segment: str) -> Path:
    """Resolve the Pipeline 3 handoff dir for a city ``segment`` (e.g. burnaby)."""
    candidates = [
        ROOT.parent
        / "w2025-data599-capstone-projects-green-metrics-technology"
        / "code"
        / "prototype_pipeline_3",
        ROOT.parent / "prototype_pipeline_3",
        ROOT.parent / "code" / "prototype_pipeline_3",
    ]
    for base in candidates:
        handoff = (
            base
            / "outputs"
            / segment
            / f"pipeline3_{segment}_rule_pipeline"
            / "06_teammate_verification_handoff"
        )
        if (handoff / "evidence_units.json").exists() and (handoff / "rule_candidates.json").exists():
            return handoff
    return (
        candidates[0]
        / "outputs"
        / segment
        / f"pipeline3_{segment}_rule_pipeline"
        / "06_teammate_verification_handoff"
    )


def _default_pipeline5_registry(city_key: str, segment: str) -> Path:
    """Resolve the Pipeline 5 registry for a city ``segment`` (e.g. burnaby)."""
    candidates = [
        ROOT / "outputs" / f"{city_key}_extraction" / "final_rule_registry.json",
        ROOT / "outputs" / f"{segment}_extraction" / "final_rule_registry.json",
        ROOT.parent
        / "w2025-data599-capstone-projects-green-metrics-technology"
        / "code"
        / "prototype_pipeline_5"
        / "outputs"
        / segment
        / "rule_extraction"
        / "final_rule_registry.json",
        ROOT.parent
        / "prototype_pipeline_5"
        / "outputs"
        / segment
        / "rule_extraction"
        / "final_rule_registry.json",
        ROOT.parent
        / "code"
        / "prototype_pipeline_5"
        / "outputs"
        / segment
        / "rule_extraction"
        / "final_rule_registry.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DEFAULT_INPUT_MODE = "pipeline5_registry"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--city",
        default="burnaby_r1",
        help="City/zone key. Resolves configs/<city>.json and outputs/<city>_slim_pipeline5_registry/ "
        "by convention. Use --config/--output-dir to override.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="City/zone config used by deterministic verification (defaults to configs/<city>.json).",
    )
    parser.add_argument(
        "--input-mode",
        choices=["pipeline5_registry", "zihao_input_only"],
        default=DEFAULT_INPUT_MODE,
        help="Input source for verification. Pipeline 5 is preferred when final_rule_registry.json is available.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for slim verifier artifacts (defaults to outputs/<city>_slim_pipeline5_registry/).",
    )
    parser.add_argument(
        "--pipeline5-registry",
        default=None,
        help="Zihao Pipeline 5 final_rule_registry.json path "
        "(defaults to .../prototype_pipeline_5/outputs/<city-segment>/rule_extraction/final_rule_registry.json).",
    )
    parser.add_argument(
        "--zihao-evidence",
        default=None,
        help="Zihao evidence_units.json path (defaults to the <city-segment> Pipeline 3 handoff).",
    )
    parser.add_argument(
        "--zihao-rules",
        default=None,
        help="Zihao Pipeline 3 handoff rule_candidates.json path (defaults to the <city-segment> handoff).",
    )
    parser.add_argument(
        "--pipeline9-run",
        default=None,
        help=(
            "Pipeline 9 city run directory (e.g. /tmp/pipeline9_run_outputs/calgary). "
            "Adapts merged_rules_deduplicated.json + RAG text blocks into the verifier "
            "contract, re-anchoring evidence to data/bylaws/<city>/source.pdf when "
            "present. RAG proposes; the verifier proves; GIS consumes only verified."
        ),
    )
    parser.add_argument(
        "--native-extraction",
        default=None,
        help=(
            "Native RAG+LLM extraction output directory containing evidence_units.json "
            "and rule_candidates.json. Native extraction proposes; the verifier proves."
        ),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable verification cache hit/miss diagnostics for this run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    city = resolve_city_paths(ROOT, args.city)
    config_path = Path(args.config) if args.config else city.config
    output_dir = Path(args.output_dir) if args.output_dir else city.output_dir
    args.resolved_city_key = city.city_key
    # Default upstream-extraction paths follow the bare city segment (burnaby_r1
    # -> burnaby) so a new city resolves its own inputs without a code edit.
    segment = upstream_city_segment(args.city)
    # The adapter uses the city config's normalization hints so it never stamps a
    # Burnaby label onto another city's rule (verification re-derives the rest).
    # The same loaded dict is handed to run_slim_verification (load_config
    # stamps _config_path for provenance) so the file is parsed once per run.
    config = load_config(config_path)
    candidate_set = _load_candidate_set(args, segment, config)
    input_mode = (
        "native_rag_llm"
        if getattr(args, "native_extraction", None)
        else "pipeline9_rag"
        if getattr(args, "pipeline9_run", None)
        else args.input_mode
    )
    summary = run_slim_verification(
        config_path=config,
        output_dir=output_dir,
        evidence_units=candidate_set["evidence_units"],
        rule_candidates=candidate_set["rule_candidates"],
        input_mode=input_mode,
        use_cache=not args.no_cache,
    )

    print("\nSlim verification complete")
    print(f"Input mode: {summary['input_mode']}")
    print(f"Output directory: {summary['output_dir']}")
    print(f"Evidence units: {summary['evidence_unit_count']}")
    print(f"Rule candidates: {summary['candidate_rule_count']}")
    print(f"Verified rules: {summary['verified_rule_count']}")
    print(f"Review needed: {summary['review_rule_count']}")
    print(f"Rejected rules: {summary['rejected_rule_count']}")
    print(f"Not used / traceability only: {summary['not_used_rule_count']}")


def _load_candidate_set(
    args: argparse.Namespace, segment: str, config: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    if getattr(args, "native_extraction", None):
        run_dir = Path(args.native_extraction)
        evidence_path = run_dir / "evidence_units.json"
        candidates_path = run_dir / "rule_candidates.json"
        if not evidence_path.exists() or not candidates_path.exists():
            raise FileNotFoundError(
                f"Native extraction output must contain evidence_units.json and "
                f"rule_candidates.json: {run_dir}"
            )
        evidence_units = _read_json(evidence_path, [])
        rule_candidates = _read_json(candidates_path, [])
        print(f"[native] {len(rule_candidates)} candidates / {len(evidence_units)} evidence")
        return {"evidence_units": evidence_units, "rule_candidates": rule_candidates}
    if getattr(args, "pipeline9_run", None):
        # Pipeline 9 (RAG candidate generator) path: adapt + re-anchor to the
        # city's cached source PDF when present. The adapter is proposer-tier;
        # the verifier still proves everything itself.
        from burnaby_prototype.pipeline9_adapter import adapt_pipeline9_run

        source_pdf = ROOT / "data" / "bylaws" / args.city.lower() / "source.pdf"
        adapted = adapt_pipeline9_run(
            Path(args.pipeline9_run),
            args.city,
            config,
            source_pdf=source_pdf if source_pdf.exists() else None,
        )
        summary = adapted["summary"]
        reanchor = summary.get("reanchor", {})
        print(
            f"[pipeline9] {summary['rule_count']} candidates / {summary['evidence_count']} evidence "
            f"(unjoined: {summary['unjoined_blocks']}; reanchored: {reanchor.get('reanchored', 'skipped')}"
            f", mismatched: {reanchor.get('mismatched', 0)})"
        )
        return {
            "evidence_units": adapted["evidence_units"],
            "rule_candidates": adapted["rule_candidates"],
        }
    if args.input_mode == "pipeline5_registry":
        city_key = getattr(args, "resolved_city_key", segment)
        registry = Path(args.pipeline5_registry) if args.pipeline5_registry else _default_pipeline5_registry(city_key, segment)
        return _load_pipeline5(registry, config)
    zihao_dir = _default_zihao_dir(segment)
    evidence = Path(args.zihao_evidence) if args.zihao_evidence else zihao_dir / "evidence_units.json"
    rules = Path(args.zihao_rules) if args.zihao_rules else zihao_dir / "rule_candidates.json"
    return _load_zihao(evidence, rules, config)


def _load_pipeline5(registry_path: Path, config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not registry_path.exists():
        raise FileNotFoundError(
            "Pipeline 5 registry was not found. Expected final_rule_registry.json at "
            f"{registry_path}. Pass --pipeline5-registry if Zihao's Pipeline 5 output is elsewhere."
        )
    return adapt_pipeline5_registry(_read_json(registry_path, {"rules": []}), config)


def _load_zihao(evidence_path: Path, rules_path: Path, config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return adapt_zihao_outputs(
        _read_json(evidence_path, []),
        _read_json(rules_path, []),
        config,
    )


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


if __name__ == "__main__":
    main()
