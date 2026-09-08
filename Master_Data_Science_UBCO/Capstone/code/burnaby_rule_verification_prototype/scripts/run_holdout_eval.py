#!/usr/bin/env python3
"""Compatibility wrapper for scripts/legacy/run_holdout_eval.py."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


LEGACY_SCRIPT = Path(__file__).resolve().parent / "legacy" / "run_holdout_eval.py"
sys.argv[0] = str(LEGACY_SCRIPT)
runpy.run_path(str(LEGACY_SCRIPT), run_name="__main__")
