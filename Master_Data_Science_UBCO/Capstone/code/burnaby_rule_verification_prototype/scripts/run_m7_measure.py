#!/usr/bin/env python3
"""Run the M7 benchmark-driven measurement layer (formerly M5/M6).

The runner copies existing verifier artifacts into a fresh measurement folder
before benchmarking, so canonical outputs are not overwritten. Runs land under
outputs/m7_measure/<run_id>/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.m7_measure import DEFAULT_M5_CITIES, run_m7_measurement  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--city",
        action="append",
        help="City key to include. Repeatable. Defaults to Burnaby, Vancouver, and Calgary.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run id. Defaults to a UTC timestamp.",
    )
    parser.add_argument(
        "--out-root",
        default=str(ROOT / "outputs" / "m7_measure"),
        help="Root folder for measurement runs. Default: outputs/m7_measure.",
    )
    parser.add_argument(
        "--changed-component",
        default="measurement_baseline",
        help="Label for the component being tested in this run.",
    )
    parser.add_argument(
        "--model",
        default="existing_outputs",
        help="Model label for the scoreboard row.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=6,
        help="RAG retrieval evaluation cutoff.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow reusing an existing run folder with the same run id.",
    )
    parser.add_argument(
        "--refresh-verifier",
        action="store_true",
        help="Re-run the deterministic verifier into each fresh M5 city folder before benchmarking.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cities = args.city or list(DEFAULT_M5_CITIES)
    summary = run_m7_measurement(
        root=ROOT,
        cities=cities,
        run_id=args.run_id,
        out_root=Path(args.out_root),
        changed_component=args.changed_component,
        model=args.model,
        overwrite=args.overwrite,
        top_k=args.top_k,
        refresh_verifier=args.refresh_verifier,
    )
    print(f"M7 measurement run written: {summary['run_root']}")
    print(f"Hard gates passed: {summary['hard_gates_passed']}")
    for city in summary["city_reports"]:
        top = city.get("top_bottleneck") or {}
        bottleneck = (
            f"{top.get('stage')}::{top.get('metric')}" if top else "none"
        )
        print(f"  {city['city']}: accepted={city['accepted']} top_bottleneck={bottleneck}")
    return 0 if summary["hard_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
