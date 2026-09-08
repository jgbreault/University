"""Consolidated prototype entrypoint tests."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_consolidated_prototype import (  # noqa: E402
    default_max_packs,
    display_command,
    mvp_command,
    native_command,
)


class ConsolidatedPrototypeCommandTests(unittest.TestCase):
    def test_default_pack_budget_is_city_aware(self) -> None:
        self.assertEqual(default_max_packs("calgary_rcg"), 1400)
        self.assertEqual(default_max_packs("Calgary_RCG"), 1400)
        self.assertEqual(default_max_packs("burnaby_r1"), 180)
        self.assertEqual(default_max_packs("vancouver_rs"), 260)

    def test_mvp_command_refreshes_benchmarks_by_default(self) -> None:
        args = argparse.Namespace(refresh_discovery=False)
        command = mvp_command(args)
        self.assertEqual(command[1:], ["scripts/run_mvp_verification.py", "--refresh-benchmarks"])

    def test_mvp_command_can_refresh_discovery(self) -> None:
        args = argparse.Namespace(refresh_discovery=True)
        command = mvp_command(args)
        self.assertIn("--refresh-discovery", command)

    def test_native_command_wraps_m4_bakeoff_without_hiding_flags(self) -> None:
        args = argparse.Namespace(
            city="calgary_rcg",
            models="google/gemini-2.5-flash-lite",
            max_packs=None,
            dry_run=True,
            no_examiner=True,
            refresh_packs=True,
        )
        command = native_command(args)
        self.assertIn("scripts/run_m4_bakeoff.py", command)
        self.assertIn("--city", command)
        self.assertIn("calgary_rcg", command)
        self.assertIn("--max-packs", command)
        self.assertIn("1400", command)
        self.assertIn("--dry-run", command)
        self.assertIn("--no-verify", command)
        self.assertIn("--refresh-packs", command)

    def test_native_command_respects_explicit_pack_budget(self) -> None:
        args = argparse.Namespace(
            city="calgary_rcg",
            models="m",
            max_packs=25,
            dry_run=False,
            no_examiner=False,
            refresh_packs=False,
        )
        command = native_command(args)
        self.assertEqual(command[command.index("--max-packs") + 1], "25")
        self.assertNotIn("--dry-run", command)
        self.assertNotIn("--no-verify", command)

    def test_display_command_prefers_repo_local_python(self) -> None:
        command = display_command([sys.executable, "scripts/run_consolidated_prototype.py", "status"])
        self.assertTrue(command.startswith(".venv/bin/python "), command)


if __name__ == "__main__":
    unittest.main()
