"""Learned review ranker: JSON-model mechanics + the advisory boundary.

Performance is NOT asserted here (the honest leave-one-city-out numbers live
in the trained model artifact); these tests pin the mechanics: deterministic
pure-Python scoring, feature extraction from verifier fields only, annotation
behavior, and the gold-free runtime boundary.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.review_ranker import (
    extract_features,
    feature_names,
    rank_review_rules,
    score_rule,
)

RULE = {
    "rule_id": "lr_001",
    "condition": "sloping roof",
    "evidence_strength": 0.71,
    "proof_type": "table_cell",
    "support_gaps": ["applies_to_not_supported"],
    "support_checks": {
        "value_supported": True,
        "unit_supported": True,
        "operator_supported": True,
        "applies_to_supported": False,
        "scope_supported": True,
        "rule_object_supported": True,
    },
    "proof_trace": {
        "value": {"label": "supported"},
        "unit": {"label": "supported"},
        "applies_to": {"label": "not_enough_info"},
    },
}

MODEL = {
    "intercept": -1.0,
    "coefficients": {
        "check::value_supported": 1.2,
        "gap::applies_to_not_supported": -0.4,
        "evidence_strength": 2.0,
    },
    "conformal": {"score_threshold": 0.75},
}


class RankerMechanicsTests(unittest.TestCase):
    def test_features_are_deterministic_and_closed_vocabulary(self) -> None:
        features = extract_features(RULE)
        self.assertEqual(features, extract_features(dict(RULE)))
        self.assertTrue(set(features) <= set(feature_names()))
        self.assertEqual(features["check::value_supported"], 1.0)
        self.assertEqual(features["gap::applies_to_not_supported"], 1.0)
        self.assertEqual(features["proof::not_enough_info"], 1.0)
        self.assertEqual(features["is_table_evidence"], 1.0)

    def test_score_is_pure_python_logistic_of_the_json_model(self) -> None:
        import math

        z = -1.0 + 1.2 * 1.0 + (-0.4) * 1.0 + 2.0 * 0.71
        self.assertAlmostEqual(score_rule(RULE, MODEL), 1.0 / (1.0 + math.exp(-z)), places=9)
        # Unknown features in the model are ignored gracefully.
        self.assertGreater(score_rule(RULE, {"intercept": 0.0, "coefficients": {"nope": 5.0}}), 0.49)

    def test_ranking_annotates_and_orders_desc(self) -> None:
        weak = {**RULE, "rule_id": "lr_002", "evidence_strength": 0.1}
        ranked = rank_review_rules([weak, RULE], MODEL)
        self.assertEqual([r["rule_id"] for r in ranked], ["lr_001", "lr_002"])
        self.assertIn("ranker_score", ranked[0])
        self.assertIn("ranker_calibrated_confident", ranked[0])
        # Threshold from the model decides the calibrated flag.
        self.assertEqual(
            ranked[0]["ranker_calibrated_confident"], ranked[0]["ranker_score"] >= 0.75
        )

    def test_runtime_module_is_gold_free_and_sklearn_free(self) -> None:
        source = (SRC / "burnaby_prototype" / "review_ranker.py").read_text(encoding="utf-8")
        for forbidden in ("import sklearn", "from sklearn", "benchmark/gold", "_gold_rules", "import pickle"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()


class NliSecondOpinionTests(unittest.TestCase):
    class FakeNli:
        """predict() returns (contradiction, entailment, neutral) logits."""

        def __init__(self, entail: bool) -> None:
            self.entail = entail

        def predict(self, pairs):
            return [(0.0, 6.0, 0.0) if self.entail else (6.0, 0.0, 0.0) for _ in pairs]

    RULE = {
        "rule_id": "nli_001",
        "rule_object": "height",
        "constraint_type": "maximum",
        "applies_to": "laneway house",
        "operator": "<=",
        "value": "8.5",
        "unit": "m",
        "source": {"evidence_text": "The building height for a laneway house must not exceed 8.5 m."},
    }

    def test_unavailable_without_backend_or_local_model(self) -> None:
        from burnaby_prototype.nli_semantics import entailment_lookup

        report = entailment_lookup([self.RULE], model_name="definitely/not-a-local-model")
        self.assertFalse(report["available"])
        self.assertEqual(report["items"], [])

    def test_entailment_scores_and_audit_flags(self) -> None:
        from burnaby_prototype.nli_semantics import audit_flags, entailment_lookup

        high = entailment_lookup([self.RULE], backend=self.FakeNli(entail=True))
        self.assertTrue(high["available"])
        self.assertGreater(high["items"][0]["entailment_probability"], 0.9)
        self.assertEqual(audit_flags(high, [self.RULE]), [])

        low = entailment_lookup([self.RULE], backend=self.FakeNli(entail=False))
        flags = audit_flags(low, [self.RULE])
        self.assertEqual(len(flags), 1)
        self.assertIn("deterministic proof stands", flags[0]["note"])

    def test_nli_module_respects_verify_boundary(self) -> None:
        source = (SRC / "burnaby_prototype" / "nli_semantics.py").read_text(encoding="utf-8")
        for forbidden in ("from .verification", "from .decision_policy", "import verification", "import decision_policy"):
            self.assertNotIn(forbidden, source)
