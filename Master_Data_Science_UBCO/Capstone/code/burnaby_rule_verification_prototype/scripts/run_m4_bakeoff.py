#!/usr/bin/env python3
"""Run M4 exhaustive discovery on top of the native extraction/verifier path."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_v3_bakeoff.py"),
        "--discovery-mode",
        "m4",
        "--out-root",
        str(ROOT / "outputs" / "m7_runs"),
        *sys.argv[1:],
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
