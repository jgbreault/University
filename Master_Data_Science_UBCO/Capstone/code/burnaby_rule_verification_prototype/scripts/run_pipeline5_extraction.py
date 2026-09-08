#!/usr/bin/env python3
"""Preflight or execute Zihao's Pipeline 5 extraction notebook.

Pipeline 5 is notebook/API driven.  This helper makes the external prerequisites
explicit before we ask the user or CI to run a long Gemini extraction job.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import upstream_city_segment

DEFAULT_PIPELINE5_DIR = (
    ROOT.parent
    / "w2025-data599-capstone-projects-green-metrics-technology"
    / "code"
    / "prototype_pipeline_5"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pipeline5-dir",
        default=str(DEFAULT_PIPELINE5_DIR),
        help="Directory containing pipeline5_rule_extraction.ipynb.",
    )
    parser.add_argument(
        "--city",
        default="burnaby_r1",
        help="City/zone key; the registry path uses its bare city segment "
        "(burnaby_r1 -> outputs/burnaby/...).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the notebook after prerequisite checks pass.",
    )
    parser.add_argument(
        "--executed-output",
        default="pipeline5_rule_extraction_executed.ipynb",
        help="Notebook filename to write when --execute is used.",
    )
    parser.add_argument(
        "--report-json",
        default=None,
        help="Optional path to write a machine-readable preflight report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pipeline_dir = Path(args.pipeline5_dir).expanduser()
    report = preflight(pipeline_dir, upstream_city_segment(args.city))
    _print_report(report)
    if args.report_json:
        _write_report_json(Path(args.report_json), report)

    if report["blockers"]:
        print("\nPipeline 5 extraction is blocked. Resolve blockers before executing.")
        return 2

    if not args.execute:
        print("\nPreflight passed. Re-run with --execute to run the notebook.")
        return 0

    notebook = pipeline_dir / "pipeline5_rule_extraction.ipynb"
    print("\nExecuting Pipeline 5 notebook...")
    command = [
        sys.executable,
        "-m",
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--execute",
        str(notebook),
        "--output",
        args.executed_output,
        "--ExecutePreprocessor.timeout=3600",
    ]
    completed = subprocess.run(command, cwd=pipeline_dir, check=False)
    if completed.returncode != 0:
        print(f"Pipeline 5 notebook execution failed with exit code {completed.returncode}.")
        return completed.returncode

    final_registry = report["final_registry"]
    if not final_registry.exists():
        print(f"Notebook ran, but final registry was not found at {final_registry}.")
        return 3

    print(f"Pipeline 5 extraction complete: {final_registry}")
    return 0


def preflight(pipeline_dir: Path, segment: str = "burnaby") -> dict:
    """Return prerequisite status without executing external API calls."""
    notebook = pipeline_dir / "pipeline5_rule_extraction.ipynb"
    final_registry = pipeline_dir / "outputs" / segment / "rule_extraction" / "final_rule_registry.json"
    checks = {
        "pipeline5_dir_exists": pipeline_dir.exists(),
        "notebook_exists": notebook.exists(),
        "saved_final_registry_exists": final_registry.exists(),
        "gemini_api_key_set": bool(os.environ.get("GEMINI_API_KEY")),
        "jupyter_module_available": _module_available("jupyter"),
        "nbconvert_available": _module_available("nbconvert"),
        "google_gemini_sdk_available": _module_available("google.generativeai"),
    }
    blockers = [
        name
        for name, passed in checks.items()
        if name
        in {
            "pipeline5_dir_exists",
            "notebook_exists",
            "gemini_api_key_set",
            "jupyter_module_available",
            "nbconvert_available",
            "google_gemini_sdk_available",
        }
        and not passed
    ]
    return {
        "pipeline5_dir": pipeline_dir,
        "notebook": notebook,
        "final_registry": final_registry,
        "checks": checks,
        "blockers": blockers,
    }


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _print_report(report: dict) -> None:
    print("Pipeline 5 extraction preflight")
    print(f"  pipeline5_dir: {report['pipeline5_dir']}")
    print(f"  notebook:      {report['notebook']}")
    print(f"  final_registry:{report['final_registry']}")
    for name, passed in report["checks"].items():
        status = "OK" if passed else "MISSING"
        print(f"  {status:7} {name}")


def _write_report_json(path: Path, report: dict) -> None:
    import json

    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_serializable_report(report), indent=2) + "\n", encoding="utf-8")


def _serializable_report(report: dict) -> dict:
    return {
        "pipeline5_dir": str(report["pipeline5_dir"]),
        "notebook": str(report["notebook"]),
        "final_registry": str(report["final_registry"]),
        "checks": report["checks"],
        "blockers": report["blockers"],
        "can_execute": not bool(report["blockers"]),
    }


if __name__ == "__main__":
    sys.exit(main())
