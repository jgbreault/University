#!/usr/bin/env python3
"""Pipeline 9 runner: graph/RAG-selected rule extraction packs.

Pipeline 9 turns the current rule-extraction experiment into a repeatable path:

1. deterministic local candidate selection;
2. automatic discovery/audit of candidate rule sections;
3. semantic/lexical compression;
4. graph/RAG pack construction with rule lanes;
5. conversion into legacy visual-block input;
6. optional legacy text rule extraction.

The default run is offline and stops before any LLM/API call.
"""

from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PIPELINE6_DIR = ROOT.parent / "prototype_pipeline_6"
PIPELINE5_DIR = ROOT.parent / "prototype_pipeline_5"
for dep_dir in (PIPELINE6_DIR, PIPELINE5_DIR):
    if str(dep_dir) not in sys.path:
        sys.path.insert(0, str(dep_dir))

from auto_discovery import run as run_auto_discovery  # noqa: E402
from generic_discovery_pack_builder import run as build_generic_discovery_packs  # noqa: E402
from local_candidate_block_selector import CITY_CONFIGS, process_local_selection  # noqa: E402
from rag_packs_to_visual_blocks import run as adapt_rag_packs  # noqa: E402
from semantic_compression import compress as run_semantic_compression  # noqa: E402
from visual_blocks_rule_extractor import process_extraction  # noqa: E402


DEFAULT_MODEL = "gemini-3.5-flash"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city", choices=["burnaby", "calgary", "vancouver"])
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs")
    parser.add_argument("--api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--text-model", default=None)
    parser.add_argument("--table-model", default=None)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=int, default=20)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--max-windows", type=int, default=100)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-local-selection", action="store_true")
    parser.add_argument("--skip-auto-discovery", action="store_true")
    parser.add_argument("--skip-semantic-compression", action="store_true")
    parser.add_argument("--compression-provider", choices=["lexical", "ollama"], default="lexical")
    parser.add_argument("--compression-threshold", type=float, default=0.32)
    parser.add_argument("--compression-query", default="")
    parser.add_argument("--ollama-model", default="nomic-embed-text")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument(
        "--pack-threshold",
        type=float,
        default=0.28,
        help="Minimum compression score for weak same-page/same-section blocks entering extraction packs.",
    )
    parser.add_argument("--skip-pack-build", action="store_true")
    parser.add_argument("--skip-adapter", action="store_true")
    parser.add_argument("--run-extraction", action="store_true", help="Call the legacy LLM rule extractor.")
    return parser.parse_args()


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    city_dir = args.output_root.resolve() / args.city
    local_dir = city_dir / "01_local_selection"
    discovery_dir = city_dir / "02_auto_discovery"
    compression_dir = city_dir / "03_semantic_compression"
    rag_dir = city_dir / "04_graph_rag_packs"
    visual_dir = city_dir / "05_rag_visual_blocks"
    rules_dir = city_dir / "06_rule_extraction"

    summary: dict[str, Any] = {
        "pipeline": "prototype_pipeline_9_graph_rag_rule_extraction",
        "city": args.city,
        "output_dir": str(city_dir),
        "default_mode": "offline_until_--run-extraction",
        "stages": {},
    }

    if not args.skip_local_selection:
        summary["stages"]["local_selection"] = process_local_selection(
            Namespace(
                city=args.city,
                output_dir=local_dir,
                pdf=None,
                context_lines=4,
                neighbor_blocks=2,
                visual_page_radius=1,
                max_windows=args.max_windows,
                prune_windows=True,
                include_other_zones=False,
            )
        )
    elif not local_dir.exists():
        raise FileNotFoundError(f"{local_dir} does not exist; cannot skip local selection.")

    if not args.skip_auto_discovery:
        config = CITY_CONFIGS[args.city]
        summary["stages"]["auto_discovery"] = run_auto_discovery(
            Namespace(
                local_dir=local_dir,
                output_dir=discovery_dir,
                target_terms=config.get("target_terms", []),
                parent_terms=config.get("parent_terms", []),
            )
        )
    elif not discovery_dir.exists():
        raise FileNotFoundError(f"{discovery_dir} does not exist; cannot skip auto discovery.")

    config = CITY_CONFIGS[args.city]
    if not args.skip_semantic_compression:
        summary["stages"]["semantic_compression"] = run_semantic_compression(
            Namespace(
                discovery_dir=discovery_dir,
                output_dir=compression_dir,
                provider=args.compression_provider,
                threshold=args.compression_threshold,
                query=args.compression_query,
                target_terms=config.get("target_terms", []),
                parent_terms=config.get("parent_terms", []),
                ollama_model=args.ollama_model,
                ollama_url=args.ollama_url,
            )
        )
        blocks_file = compression_dir / "compressed_blocks.jsonl"
    elif compression_dir.exists():
        blocks_file = compression_dir / "compressed_blocks.jsonl"
    else:
        blocks_file = discovery_dir / "discovered_blocks.jsonl"

    if not args.skip_pack_build:
        summary["stages"]["graph_rag_pack_build"] = build_generic_discovery_packs(
            Namespace(
                city=args.city,
                discovery_dir=discovery_dir,
                blocks_file=blocks_file,
                output_dir=rag_dir,
                pack_threshold=args.pack_threshold,
            )
        )
    elif not rag_dir.exists():
        raise FileNotFoundError(f"{rag_dir} does not exist; cannot skip pack build.")

    if not args.skip_adapter:
        manifest_path = visual_dir / "rag_adapter_manifest.json"
        if manifest_path.exists() and not args.overwrite:
            summary["stages"]["rag_visual_block_adapter"] = {
                **read_json(manifest_path),
                "status": "cached",
            }
        else:
            summary["stages"]["rag_visual_block_adapter"] = adapt_rag_packs(
                Namespace(
                    rag_dir=rag_dir,
                    output_dir=visual_dir,
                    lanes=[
                        "extract_now_core_packs.jsonl",
                        "extract_separately_use_permission_packs.jsonl",
                        "district_dimensional_overrides_packs.jsonl",
                        "universal_applicable_rules_packs.jsonl",
                    ],
                    overwrite=args.overwrite,
                    target_terms=config.get("target_terms", []),
                    parent_terms=config.get("parent_terms", []),
                    disable_target_filter=False,
                    include_broad_context=False,
                )
            )
    elif not visual_dir.exists():
        raise FileNotFoundError(f"{visual_dir} does not exist; cannot skip adapter.")

    if args.run_extraction:
        summary["stages"]["rule_extraction"] = process_extraction(
            Namespace(
                visual_blocks_dir=visual_dir,
                output_dir=rules_dir,
                model=args.model,
                text_model=args.text_model,
                table_model=args.table_model,
                api_key_env=args.api_key_env,
                timeout=args.timeout,
                max_retries=args.max_retries,
                retry_base_seconds=args.retry_base_seconds,
                max_workers=args.max_workers,
                overwrite=args.overwrite,
                target_terms=config.get("target_terms", []),
            )
        )
    else:
        summary["stages"]["rule_extraction"] = {
            "status": "skipped",
            "reason": "pass --run-extraction to call the LLM extractor",
            "input_visual_blocks_dir": str(visual_dir),
            "planned_output_dir": str(rules_dir),
        }

    write_json(city_dir / "pipeline9_summary.json", summary)
    return summary


def compact_run_summary(summary: dict[str, Any]) -> dict[str, Any]:
    stages = summary.get("stages", {})
    local = stages.get("local_selection", {})
    discovery = stages.get("auto_discovery", {})
    compression = stages.get("semantic_compression", {})
    pack_stage = stages.get("graph_rag_pack_build", {})
    packs = pack_stage.get("graph_rag_pack_policy") or pack_stage
    adapter = stages.get("rag_visual_block_adapter", {})
    extraction = stages.get("rule_extraction", {})
    return {
        "pipeline": summary.get("pipeline"),
        "city": summary.get("city"),
        "output_dir": summary.get("output_dir"),
        "local_selection": {
            "local_block_count": local.get("local_block_count"),
            "candidate_window_count": local.get("candidate_window_count"),
            "recommended_visual_page_count": local.get("recommended_visual_page_count"),
        },
        "auto_discovery": {
            "selected_block_count": discovery.get("selected_block_count"),
            "target_hit_block_count": discovery.get("target_hit_block_count"),
            "target_hit_discarded_count": discovery.get("target_hit_discarded_count"),
            "rule_signal_discarded_count": discovery.get("rule_signal_discarded_count"),
            "low_confidence_selected_count": discovery.get("low_confidence_selected_count"),
            "lane_counts": discovery.get("lane_counts"),
            "selected_tier_counts": discovery.get("selected_tier_counts"),
            "selected_drop_risk_counts": discovery.get("selected_drop_risk_counts"),
            "output_dir": discovery.get("output_dir"),
        },
        "semantic_compression": {
            "provider": compression.get("provider"),
            "threshold": compression.get("threshold"),
            "input_selected_block_count": compression.get("input_selected_block_count"),
            "compressed_block_count": compression.get("compressed_block_count"),
            "dropped_block_count": compression.get("dropped_block_count"),
            "compression_ratio": compression.get("compression_ratio"),
            "compressed_lane_counts": compression.get("compressed_lane_counts"),
            "compressed_tier_counts": compression.get("compressed_tier_counts"),
            "compressed_drop_risk_counts": compression.get("compressed_drop_risk_counts"),
            "output_dir": compression.get("output_dir"),
        },
        "graph_rag_pack_build": {
            "selected_block_count": packs.get("selected_block_count"),
            "evidence_block_count": packs.get("evidence_block_count"),
            "context_pack_count": packs.get("context_pack_count"),
            "duplicate_cluster_count": packs.get("duplicate_cluster_count"),
            "duplicate_source_block_count": packs.get("duplicate_source_block_count"),
            "pack_threshold": packs.get("pack_threshold"),
            "pack_applicability": packs.get("pack_applicability"),
            "recommended_extraction_plan": packs.get("recommended_extraction_plan"),
        },
        "rag_visual_block_adapter": {
            "pack_count": adapter.get("pack_count"),
            "text_block_count": adapter.get("text_block_count"),
            "unique_source_block_count_including_duplicates": adapter.get("unique_source_block_count_including_duplicates"),
            "duplicate_cluster_count": adapter.get("duplicate_cluster_count"),
            "target_filter_enabled": adapter.get("target_filter_enabled"),
            "include_broad_context": adapter.get("include_broad_context"),
            "target_filter_actions": adapter.get("target_filter_actions"),
            "output_dir": adapter.get("output_dir"),
            "status": adapter.get("status", "generated"),
        },
        "rule_extraction": extraction,
        "full_summary_path": str((Path(summary["output_dir"]) / "pipeline9_summary.json").resolve()),
    }


def main() -> None:
    summary = run_pipeline(parse_args())
    print(json.dumps(compact_run_summary(summary), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
