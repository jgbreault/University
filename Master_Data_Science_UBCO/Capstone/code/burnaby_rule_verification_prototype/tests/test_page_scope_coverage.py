"""Page-scoping coverage guard.

Corpus page-scoping (``provenance.pages``) focuses extraction on a district's
pages on a large multi-district bylaw. The risk (audit recall-5) is silent: a
gold rule whose source page falls OUTSIDE the scoped spans becomes unreachable
and recall drops with no signal. This test fails CI if any city's authored gold
sits outside its own scoped page range, so a future mis-scoping is caught before
it silently zeroes recall. Cities without ``provenance.pages`` (whole-PDF) are
unconstrained.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from burnaby_prototype.extraction.pdf_ingest import page_ranges_from_provenance  # noqa: E402

CITIES = ("calgary_rcg", "burnaby_r1", "vancouver_rs")


class PageScopeCoverageTests(unittest.TestCase):
    def test_gold_pages_inside_scoped_spans(self) -> None:
        checked = 0
        for city in CITIES:
            prov_path = ROOT / "data" / "bylaws" / city / "provenance.json"
            gold_path = ROOT / "benchmark" / "gold" / f"{city}_gold_rules.json"
            if not (prov_path.exists() and gold_path.exists()):
                continue
            ranges = page_ranges_from_provenance(json.loads(prov_path.read_text(encoding="utf-8")))
            if not ranges:
                continue  # whole-PDF corpus -- nothing to constrain
            checked += 1
            gold = json.loads(gold_path.read_text(encoding="utf-8"))
            for rule in gold:
                page = rule.get("source_page")
                if not isinstance(page, int):
                    continue
                in_scope = any(start <= page <= end for start, end in ranges)
                self.assertTrue(
                    in_scope,
                    f"{city}: gold {rule.get('gold_id')} source_page {page} is OUTSIDE the "
                    f"scoped page spans {ranges} -- page-scoping would silently drop it.",
                )
        self.assertGreater(checked, 0, "expected at least one page-scoped city (calgary_rcg)")


if __name__ == "__main__":
    unittest.main()
