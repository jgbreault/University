"""Property-based invariants over the deterministic verify path (Hypothesis).

Example-based tests pin known cases; these pin whole CLASSES of behavior:
whatever inputs Hypothesis generates, the boundary discipline behind
value_not_found_in_evidence must hold, decisions must not depend on evidence
ordering or comma formatting, and the decision-policy precedence must be total.
The verify path itself is untouched — this is pure test code.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config
from burnaby_prototype.decision_policy import (
    CRITICAL_REJECTION_GAPS,
    MISSING_SCOPE_GAPS,
    NOT_USED_GAPS,
    verification_decision_from_gaps,
)
from burnaby_prototype.domain_schema import token_visible
from burnaby_prototype.support_checks import contains_value
from burnaby_prototype.verification import verify_candidates

CONFIG_PATH = ROOT / "configs" / "burnaby_r1.json"
CONFIG = load_config(CONFIG_PATH)

# Conservative example budget: the whole module must stay fast enough for the
# standing unittest gate (it runs on every change).
FAST = settings(max_examples=60, deadline=None)


class TokenVisibilityProperties(unittest.TestCase):
    @FAST
    @given(value=st.integers(min_value=1, max_value=999), text=st.text(alphabet="abcdefghij ,.;", max_size=80))
    def test_value_never_visible_in_digitless_text(self, value: int, text: str) -> None:
        # Whatever the prose, a numeric value cannot be "found" in evidence
        # that contains no digits at all.
        self.assertFalse(token_visible(text, str(value)))
        self.assertFalse(contains_value(text, value))

    @FAST
    @given(value=st.integers(min_value=1, max_value=999))
    def test_digit_boundaries_reject_substring_neighbors(self, value: int) -> None:
        token = str(value)
        # The value's digits as a PREFIX of a longer number must not match
        # (e.g. 5 inside 50, 12 inside 120) ...
        self.assertFalse(token_visible(f"the limit is {token}0 m", token))
        # ... nor as a decimal's fractional neighbor (5 inside 7.5-style).
        self.assertFalse(token_visible(f"the limit is 7.{token} m", token))
        # ... but the exact number, even at sentence end, must match.
        self.assertTrue(token_visible(f"the limit is {token} m", token))
        self.assertTrue(token_visible(f"must be at least {token}.", token))

    @FAST
    @given(whole=st.integers(min_value=1, max_value=999), frac=st.integers(min_value=1, max_value=99))
    def test_decimal_values_match_exactly_not_partially(self, whole: int, frac: int) -> None:
        token = f"{whole}.{frac:02d}"
        self.assertTrue(token_visible(f"shall not exceed {token} m", token))
        # The whole part alone must NOT be satisfied by the decimal.
        self.assertFalse(token_visible(f"shall not exceed {token} m", str(whole)))

    @FAST
    @given(value=st.integers(min_value=1000, max_value=999999))
    def test_comma_grouping_never_hides_a_value(self, value: int) -> None:
        grouped = f"{value:,}"
        # contains_value strips comma grouping on both sides.
        self.assertTrue(contains_value(f"minimum lot area of {grouped} m2", str(value)))
        self.assertTrue(contains_value(f"minimum lot area of {value} m2", grouped))


class DecisionPolicyProperties(unittest.TestCase):
    ALL_GAPS = sorted(CRITICAL_REJECTION_GAPS | NOT_USED_GAPS | MISSING_SCOPE_GAPS)

    @FAST
    @given(gaps=st.lists(st.sampled_from(ALL_GAPS), max_size=6))
    def test_precedence_is_total_and_stable(self, gaps: list[str]) -> None:
        decision = verification_decision_from_gaps(gaps)
        self.assertIn(decision, {"verified", "rejected", "not_used", "review_needed"})
        # Precedence: any critical gap forces rejection regardless of company.
        if set(gaps) & CRITICAL_REJECTION_GAPS:
            self.assertEqual(decision, "rejected")
        elif set(gaps) & NOT_USED_GAPS:
            self.assertEqual(decision, "not_used")
        elif gaps:
            self.assertEqual(decision, "review_needed")
        else:
            self.assertEqual(decision, "verified")
        # Order independence: the gap LIST order can never change the decision.
        self.assertEqual(decision, verification_decision_from_gaps(list(reversed(gaps))))


def _fixture(seed: int) -> tuple[list[dict], list[dict]]:
    """Small deterministic multi-rule fixture parameterized by seed."""
    evidence = [
        {
            "evidence_id": "pv_ev_a", "page": 2, "evidence_type": "clause",
            "evidence_text": "Rear principal buildings maximum height shall not exceed 7.5 m.",
            "source_context": "Rear principal buildings maximum height shall not exceed 7.5 m.",
        },
        {
            "evidence_id": "pv_ev_b", "page": 2, "evidence_type": "table_cell",
            "table_title": "Minimum Lot Area", "row_header": "Standard",
            "column_header": "", "cell_value": f"{280 + seed} m²",
            "evidence_text": f"Minimum Lot Area | Standard | {280 + seed} m²",
        },
        {
            "evidence_id": "pv_ev_c", "page": 3, "evidence_type": "clause",
            "evidence_text": "Lot coverage shall not exceed 45 %.",
            "source_context": "Lot coverage shall not exceed 45 %.",
        },
    ]
    candidates = [
        {
            "candidate_id": "pv_cand_height", "evidence_id": "pv_ev_a",
            "rule_object": "height", "constraint_type": "maximum",
            "constraint_scope": "building", "applies_to": "Rear Principal Buildings",
            "operator": "<=", "value": "7.5", "unit": "m",
            "extraction_method": "pipeline5_final_registry", "source_stream": "gemini_text_block",
        },
        {
            "candidate_id": "pv_cand_lot", "evidence_id": "pv_ev_b",
            "rule_object": "lot_area", "constraint_type": "minimum",
            "constraint_scope": "lot", "applies_to": "Standard",
            "operator": ">=", "value": str(280 + seed), "unit": "m²",
            "extraction_method": "pipeline5_final_registry", "source_stream": "gemini_table_image",
        },
        {
            "candidate_id": "pv_cand_cov", "evidence_id": "pv_ev_c",
            "rule_object": "lot_coverage", "constraint_type": "maximum",
            "constraint_scope": "lot", "applies_to": "all buildings",
            "operator": "<=", "value": "45", "unit": "%",
            "extraction_method": "pipeline5_final_registry", "source_stream": "gemini_text_block",
        },
    ]
    return evidence, candidates


def _decisions(result: dict) -> dict[str, str]:
    return {
        rule["candidate"]["candidate_id"]: rule["verification_decision"]
        for rule in [*result["verified_rules"], *result["review_needed"]]
    }


class MetamorphicVerifierProperties(unittest.TestCase):
    @settings(max_examples=20, deadline=None)
    @given(seed=st.integers(min_value=0, max_value=9), order=st.permutations(range(3)))
    def test_decisions_invariant_under_evidence_and_candidate_order(self, seed: int, order) -> None:
        evidence, candidates = _fixture(seed)
        baseline = _decisions(verify_candidates(CONFIG, evidence, candidates))
        shuffled_e = [evidence[i] for i in order]
        shuffled_c = [candidates[i] for i in order]
        permuted = _decisions(verify_candidates(CONFIG, shuffled_e, shuffled_c))
        self.assertEqual(baseline, permuted)

    @settings(max_examples=20, deadline=None)
    @given(seed=st.integers(min_value=0, max_value=9), pad=st.sampled_from(["  ", "\t", " \n "]))
    def test_decisions_invariant_under_whitespace_padding(self, seed: int, pad: str) -> None:
        evidence, candidates = _fixture(seed)
        baseline = _decisions(verify_candidates(CONFIG, evidence, candidates))
        padded = [dict(unit, evidence_text=pad + str(unit.get("evidence_text") or "") + pad) for unit in evidence]
        result = _decisions(verify_candidates(CONFIG, padded, candidates))
        self.assertEqual(baseline, result)


if __name__ == "__main__":
    unittest.main()
