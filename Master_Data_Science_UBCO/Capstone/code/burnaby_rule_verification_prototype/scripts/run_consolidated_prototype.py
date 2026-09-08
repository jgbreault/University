#!/usr/bin/env python3
"""Single front door for the consolidated verification prototype.

This script does not replace the existing specialist scripts. It gives the
project one stable command surface for handoff:

- status: read the current MVP report and print the honest state;
- mvp: refresh benchmark/status artifacts;
- native: run our own M4 full-bylaw discovery/extraction path.

The trust boundary stays unchanged: extraction proposes; the deterministic
verifier decides; GIS consumes only verified rules.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "outputs" / "mvp_verification" / "mvp_report.json"
DEFAULT_NATIVE_MODEL = "google/gemini-3.1-flash-lite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Print the current consolidated MVP status.")
    status.add_argument("--report", default=str(DEFAULT_REPORT))

    mvp = sub.add_parser("mvp", help="Refresh the MVP report.")
    mvp.add_argument("--refresh-discovery", action="store_true", help="Also rebuild dry discovery packs.")
    mvp.add_argument("--print-only", action="store_true", help="Print the command instead of running it.")

    native = sub.add_parser("native", help="Run our own M4 discovery/extraction path for one city.")
    native.add_argument("--city", default="burnaby_r1", help="City key: burnaby_r1, vancouver_rs, calgary_rcg.")
    native.add_argument("--models", default=DEFAULT_NATIVE_MODEL, help="Comma-separated OpenRouter model ids.")
    native.add_argument("--max-packs", type=int, default=None, help="Evidence-pack budget; default is city-aware.")
    native.add_argument("--dry-run", action="store_true", help="Build source/evidence packs only; no LLM call.")
    native.add_argument(
        "--no-examiner",
        action="store_true",
        help="Backward-compatible no-op; M4 native runs do not invoke the advisory examiner.",
    )
    native.add_argument("--refresh-packs", action="store_true", help="Rebuild evidence packs from cached/source chunks.")
    native.add_argument("--print-only", action="store_true", help="Print the command instead of running it.")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        return status(Path(args.report))
    if args.command == "mvp":
        return run_or_print(mvp_command(args), args.print_only)
    if args.command == "native":
        return run_or_print(native_command(args), args.print_only)
    raise AssertionError(f"unhandled command: {args.command}")


def status(report_path: Path) -> int:
    if not report_path.exists():
        print(f"MVP report not found: {report_path}")
        print("Create it with: .venv/bin/python scripts/run_consolidated_prototype.py mvp")
        return 1
    report = read_json(report_path)
    print(f"Overall status: {report.get('overall_status')}")
    print(f"Current false verified total: {report.get('current_false_verified_total')}")
    unsafe = report.get("unsafe_current_rows") or []
    print(f"Unsafe current rows: {', '.join(unsafe) if unsafe else 'none'}")
    print()
    print("Current lanes:")
    current_rows = report.get("current_runs")
    if current_rows is None:
        # Backward compatibility for reports generated before native V2 became
        # the current product path.
        current_rows = [(comparison.get("current") or {}) for comparison in report.get("comparisons", [])]
    for row in current_rows:
        label = row.get("label")
        if row.get("missing"):
            print(f"  {label}: missing")
            continue
        print(
            "  "
            f"{label}: status={row.get('status_label')} "
            f"candidates={row.get('candidate_rule_count')} "
            f"verified={row.get('verified_rule_count')} "
            f"review={row.get('review_rule_count')} "
            f"rejected={row.get('rejected_rule_count')} "
            f"not_used={row.get('not_used_rule_count')} "
            f"false_verified={row.get('false_verified_count')}"
        )
    return 0 if not unsafe else 1


def mvp_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, "scripts/run_mvp_verification.py", "--refresh-benchmarks"]
    if args.refresh_discovery:
        command.append("--refresh-discovery")
    return command


def native_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "scripts/run_m4_bakeoff.py",
        "--city",
        args.city,
        "--models",
        args.models,
        "--max-packs",
        str(args.max_packs or default_max_packs(args.city)),
    ]
    if args.dry_run:
        command.append("--dry-run")
        command.append("--no-verify")
    if args.refresh_packs:
        command.append("--refresh-packs")
    return command


def default_max_packs(city: str) -> int:
    # M4 is exhaustive by default. Calgary is the stress case: full
    # 1,053-page bylaw, so it needs a broad pack set.
    key = str(city or "").lower()
    if key == "calgary_rcg":
        return 1400
    if key == "vancouver_rs":
        return 260
    return 180


def run_or_print(command: list[str], print_only: bool) -> int:
    display = display_command(command)
    if print_only:
        print(display)
        return 0
    print(f"Running: {display}")
    result = subprocess.run(command, cwd=ROOT, text=True, check=False)
    return result.returncode


def display_command(command: list[str]) -> str:
    parts = list(command)
    if parts and Path(parts[0]).name == "python":
        try:
            if Path(parts[0]).resolve() == Path(sys.executable).resolve():
                parts[0] = ".venv/bin/python"
        except OSError:
            pass
    return " ".join(parts)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
