"""ddmin evidence minimization: decision-preserving, genuinely minimal-ish."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for path in (str(SRC), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

from burnaby_prototype.config import load_config
from minimize_evidence import _decision_for, minimize_evidence

CONFIG = load_config(ROOT / "configs" / "burnaby_r1.json")

EVIDENCE = {
    "evidence_id": "ddmin_ev",
    "page": 2,
    "evidence_type": "clause",
    "evidence_text": (
        "This section discusses landscaping requirements for corner lots. "
        "Rear principal buildings maximum height shall not exceed 7.5 m. "
        "Refer to the design guidelines for additional context."
    ),
    "source_context": "",
}
CANDIDATE = {
    "candidate_id": "ddmin_cand",
    "evidence_id": "ddmin_ev",
    "rule_object": "height",
    "constraint_type": "maximum",
    "constraint_scope": "building",
    "applies_to": "Rear Principal Buildings",
    "operator": "<=",
    "value": "7.5",
    "unit": "m",
    "extraction_method": "pipeline5_final_registry",
    "source_stream": "gemini_table_image",
}


class EvidenceMinimizerTests(unittest.TestCase):
    def test_minimization_preserves_decision_and_shrinks(self) -> None:
        original_decision = _decision_for(CONFIG, EVIDENCE, CANDIDATE, EVIDENCE["evidence_text"])
        result = minimize_evidence(CONFIG, EVIDENCE, CANDIDATE)
        self.assertEqual(result["decision"], original_decision)
        self.assertLess(result["minimal_length"], result["original_length"])
        # The minimal fragment still yields the same decision on its own.
        self.assertEqual(
            _decision_for(CONFIG, EVIDENCE, CANDIDATE, result["decisive_span"]),
            original_decision,
        )
        # The decisive span keeps the load-bearing sentence.
        self.assertIn("7.5", result["decisive_span"])

    def test_unrelated_padding_is_removed(self) -> None:
        result = minimize_evidence(CONFIG, EVIDENCE, CANDIDATE)
        self.assertNotIn("landscaping", result["decisive_span"].lower())
        self.assertNotIn("design guidelines", result["decisive_span"].lower())


if __name__ == "__main__":
    unittest.main()
