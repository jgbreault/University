"""Tests for the consolidated advisory layer (router, repair, intelligence,
rerun anchoring, resolution, heuristic assistant, shared review text).

These tests pin the audit fixes:
  1. the guardrail-blocked semantic route (9a) is reachable;
  2. the decision tree is authoritative (no audit fallback can contradict it);
  3. top_blocking_reasons counts the blocking_reason field;
  4. evidence repair can report "no alternative evidence";
  5. zero-supported-field packets never join an evidence bundle;
  6. numeric value anchoring is boundary-aware in all three copies;
  7. one canonical LEGAL_EXCEPTION_CUES guards the promotion path;
  8. guard-rejected bundle promotions are labelled as such;
  9. heuristic briefs never put a guidance sentence in proposed_value;
 10. reviewer text helpers are shared and consistent.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.domain_schema import LEGAL_EXCEPTION_CUES, unresolved_exception_cues
from burnaby_prototype.evidence_intelligence import (
    _best_bundle,
    _contains_value as intelligence_contains_value,
)
from burnaby_prototype.evidence_repair import (
    _contains_value as repair_contains_value,
    suggest_evidence_repairs,
)
from burnaby_prototype.evidence_rerun import (
    _bundle_promotion_blockers,
    _single_source_bundle,
)
from burnaby_prototype.llm_review_assistant import heuristic_brief
from burnaby_prototype.review_resolution import build_review_resolution
from burnaby_prototype.review_router import (
    ACTION_SEMANTIC_GUARDRAIL_REVIEW,
    _router_item,
    _semantic_route,
)
from burnaby_prototype.review_router import build_review_router
from burnaby_prototype.review_text import (
    candidate_sentence,
    count_lines,
    counter_rows,
    evidence_sentence,
)
from burnaby_prototype.review_assistant_packets import build_review_assistant_packets
from burnaby_prototype.source_repair import repair_evidence_from_source
from burnaby_prototype.verification import verify_candidates


def _review_rule(**overrides: Any) -> dict[str, Any]:
    rule = {
        "rule_id": "adv_rule_001",
        "rule_object": "setback",
        "constraint_scope": "front yard",
        "applies_to": "principal building",
        "condition": "",
        "operator": ">=",
        "value": "4.5",
        "unit": "m",
        "support_gaps": ["text_candidate_requires_review"],
        "candidate": {"candidate_id": "adv_cand_001"},
        "source": {"evidence_id": "ev_current", "page": 3, "evidence_text": "Front yard setback shall be a minimum of 4.5 m."},
    }
    rule.update(overrides)
    return rule


class SemanticGuardrailRouteTests(unittest.TestCase):
    """Finding 1: the blocked tier must be reachable despite the 0.71 cap."""

    def _blocked_semantic(self) -> dict[str, Any]:
        # _combined_score caps blocked matches at 0.71 — the raw structured
        # score is what must open the 9a branch.
        return {
            "rule_id": "adv_rule_001",
            "best_combined_semantic_score": 0.71,
            "best_structured_score": 0.75,
            "best_embedding_score": None,
            "semantic_guardrail_blockers": ["different_numeric_value"],
            "best_verified_matches": [{"verified_rule_id": "verified_001"}],
        }

    def test_blocked_route_reachable_from_raw_structured_score(self) -> None:
        route = _semantic_route(_review_rule(), self._blocked_semantic())
        self.assertIsNotNone(route)
        self.assertEqual(route["path_step"], "9a:semantic_guardrail_blocked")
        self.assertEqual(route["action_bucket"], ACTION_SEMANTIC_GUARDRAIL_REVIEW)

    def test_blocked_route_reachable_from_raw_embedding_score(self) -> None:
        semantic = self._blocked_semantic()
        semantic["best_structured_score"] = 0.5
        semantic["best_embedding_score"] = 0.85
        semantic["best_combined_semantic_score"] = 0.62
        route = _semantic_route(_review_rule(), semantic)
        self.assertIsNotNone(route)
        self.assertEqual(route["path_step"], "9a:semantic_guardrail_blocked")

    def test_blocked_but_weak_match_does_not_route(self) -> None:
        semantic = self._blocked_semantic()
        semantic["best_structured_score"] = 0.4
        semantic["best_embedding_score"] = 0.5
        semantic["best_combined_semantic_score"] = 0.4
        self.assertIsNone(_semantic_route(_review_rule(), semantic))

    def test_full_router_reports_guardrail_blocked_item(self) -> None:
        report = build_review_router(
            [_review_rule()],
            triage_report={"items": []},
            audit_report={"items": []},
            evidence_repair_report={"suggestions": []},
            evidence_rerun_report={"attempts": []},
            semantic_review_report={"items": [self._blocked_semantic()]},
        )
        item = report["items"][0]
        self.assertEqual(item["action_bucket"], ACTION_SEMANTIC_GUARDRAIL_REVIEW)
        self.assertIn("9a:semantic_guardrail_blocked", item["decision_path"])


class AuthoritativeDecisionTreeTests(unittest.TestCase):
    """Finding 2: route fields cannot be overridden or contradicted by audit."""

    def test_audit_bucket_cannot_override_tree_route(self) -> None:
        rule = _review_rule(support_gaps=["operator_not_supported"])
        audit = {
            "action_bucket": "defer_low_priority",
            "action_reason": "stale audit reason",
            "next_step": "stale audit step",
        }
        item = _router_item(rule, {}, audit, {}, {}, {}, {}, {})
        self.assertEqual(item["action_bucket"], "operator_review")
        self.assertIn("operator_review", item["action_reason"])
        self.assertIn("3:operator_missing_or_refuted", item["action_reason"])
        self.assertNotIn("stale audit", item["action_reason"])
        self.assertNotIn("stale audit", item["next_step"])

    def test_action_reason_always_names_the_chosen_bucket(self) -> None:
        for gaps in (
            ["cross_reference_only"],
            ["value_not_found_in_evidence"],
            ["rule_object_not_supported"],
            ["unresolved_exception_cue"],
            ["cross_family_value_collision"],
            ["text_candidate_requires_review"],
        ):
            item = _router_item(_review_rule(support_gaps=gaps), {}, {}, {}, {}, {}, {}, {})
            self.assertIn(item["action_bucket"], item["action_reason"], gaps)

    def test_top_blocking_reasons_counts_blocking_reason_field(self) -> None:
        rules = [
            _review_rule(rule_id="a", blocking_reason="operator wording missing"),
            _review_rule(rule_id="b", blocking_reason="operator wording missing"),
            _review_rule(rule_id="c", blocking_reason="value not in evidence"),
        ]
        report = build_review_router(
            rules,
            triage_report={"items": []},
            audit_report={"items": []},
            evidence_repair_report={"suggestions": []},
            evidence_rerun_report={"attempts": []},
        )
        reasons = {row["name"]: row["count"] for row in report["summary"]["top_blocking_reasons"]}
        self.assertEqual(reasons["operator wording missing"], 2)
        self.assertEqual(reasons["value not in evidence"], 1)
        # And it is no longer a clone of the support-gap histogram.
        gaps = {row["name"] for row in report["summary"]["top_support_gaps"]}
        self.assertIn("text_candidate_requires_review", gaps)
        self.assertNotIn("text_candidate_requires_review", reasons)


class EvidenceRepairBaselineTests(unittest.TestCase):
    """Finding 4: 'no alternative evidence found' must be representable."""

    def test_unrelated_evidence_yields_no_alternative_suggestion(self) -> None:
        rule = _review_rule(
            support_gaps=["constraint_scope_not_supported"],
            value="4.5",
            unit="m",
        )
        unrelated = {
            "evidence_id": "ev_noise",
            "page": 9,
            "evidence_type": "clause",
            "evidence_text": "Schedule of fees payable upon application submission.",
            "evidence_quality_score": 0.9,
        }
        report = suggest_evidence_repairs([rule], [unrelated])
        suggestion = report["suggestions"][0]
        self.assertEqual(suggestion["top_evidence"], [])
        self.assertEqual(suggestion["best_repair_confidence"], 0.0)
        self.assertFalse(suggestion["can_retry_verification"])
        self.assertEqual(report["alternative_evidence_count"], 0)

    def test_substantive_match_still_scores(self) -> None:
        rule = _review_rule(support_gaps=["constraint_scope_not_supported"])
        relevant = {
            "evidence_id": "ev_better",
            "page": 4,
            "evidence_type": "clause",
            "evidence_text": "The front yard setback shall be a minimum of 4.5 m.",
            "evidence_quality_score": 0.9,
        }
        report = suggest_evidence_repairs([rule], [relevant])
        suggestion = report["suggestions"][0]
        self.assertTrue(suggestion["top_evidence"])
        self.assertGreater(suggestion["best_repair_confidence"], 0.0)


class SourceBackedRepairTests(unittest.TestCase):
    def test_parent_lead_in_is_attached_only_from_source_text(self) -> None:
        evidence = [{"evidence_id": "ev_child", "page": 1, "evidence_text": "(a) 3.0 metres from the rear property line"}]
        candidates = [{"candidate_id": "cand", "evidence_id": "ev_child"}]
        repaired, _, report = repair_evidence_from_source(
            evidence,
            candidates,
            {"city": "Test", "zone": "T"},
            source_pages={1: "The minimum setback is: (a) 3.0 metres from the rear property line;"},
        )
        self.assertEqual(report["status_counts"]["reanchored"], 1)
        self.assertIn("parent_lead_in_attached", repaired[0]["source_repair"]["actions"])
        self.assertIn("minimum setback", repaired[0]["source_context"])

    def test_p9_source_mismatch_forces_review(self) -> None:
        evidence = [{
            "evidence_id": "ev_p9",
            "page": 1,
            "evidence_text": "minimum height is 9.0 metres",
            "p9_provenance": {"original_page_number": 1},
        }]
        candidates = [{"candidate_id": "cand", "evidence_id": "ev_p9", "extraction_review_reasons": []}]
        _, repaired_candidates, report = repair_evidence_from_source(
            evidence,
            candidates,
            {"city": "Test", "zone": "T"},
            source_pages={1: "This page says nothing about that rule."},
        )
        self.assertEqual(report["forced_review_count"], 1)
        self.assertEqual(repaired_candidates[0]["extraction_final_action"], "REVIEW")
        self.assertIn("rag_context_mismatch", repaired_candidates[0]["extraction_review_reasons"])

    def test_repaired_context_is_proved_by_existing_verifier(self) -> None:
        evidence = [{"evidence_id": "ev_child", "page": 1, "evidence_text": "(a) 3.0 metres from the rear property line"}]
        candidates = [{
            "candidate_id": "cand",
            "evidence_id": "ev_child",
            "rule_object": "setback",
            "constraint_type": "minimum",
            "constraint_scope": "rear property line",
            "applies_to": "rear property line",
            "operator": ">=",
            "value": "3.0",
            "unit": "m",
        }]
        config = {
            "city": "Test",
            "zone": "T",
            "verification": {
                "verify_text_candidates": True,
                "require_text_consensus": False,
                "gis_text_rule_contract": ["setback"],
                "single_source_text_rule_contract": ["setback"],
                "rule_family_direction": {"setback": "min"},
            },
        }
        repaired_evidence, repaired_candidates, _ = repair_evidence_from_source(
            evidence,
            candidates,
            config,
            source_pages={1: "The minimum setback from the rear property line is: (a) 3.0 metres from the rear property line;"},
        )
        result = verify_candidates(config, repaired_evidence, repaired_candidates)
        self.assertEqual(len(result["verified_rules"]), 1)
        self.assertEqual(result["verified_rules"][0]["rule_object"], "setback")

    def test_long_projection_block_does_not_borrow_neighboring_separation_rule(self) -> None:
        trap_text = (
            "(3.2) (a) Where portions of a Backyard Suite meet the requirements of subsection (b) "
            "these portions may project: (i) into a setback area from a property line shared with a "
            "street or a lane to a minimum building setback of 0.6 metres from the shared property line; "
            "and (ii) 0.6 metres into the minimum separation area required in subsection (3) or the "
            "amenity space required in subsection (3.1); (b) Projections described in subsection (a) "
            "must: (i) not exceed 40.0 per cent of the length of the facade on each storey for the "
            "total combined length of all projections; (ii) each contain a window; and (iii) each have "
            "a maximum length of 3.1 metres"
        )
        page = (
            "A minimum separation of 5.0 metres is required between buildings. "
            + trap_text
            + " The maximum building height is 7.5 metres."
        )
        evidence = [{"evidence_id": "ev_projection", "page": 1, "evidence_text": trap_text}]
        candidates = [{
            "candidate_id": "cand_projection",
            "evidence_id": "ev_projection",
            "rule_object": "building_separation",
            "constraint_type": "minimum",
            "constraint_scope": "building_separation",
            "applies_to": "building_separation",
            "operator": ">=",
            "value": "3.1",
            "unit": "m",
        }]
        config = {
            "city": "Test",
            "zone": "T",
            "verification": {
                "verify_text_candidates": True,
                "require_text_consensus": False,
                "gis_text_rule_contract": ["building_separation"],
                "single_source_text_rule_contract": ["building_separation"],
                "rule_family_direction": {"building_separation": "min"},
            },
        }
        repaired_evidence, repaired_candidates, _ = repair_evidence_from_source(
            evidence,
            candidates,
            config,
            source_pages={1: page},
        )
        self.assertIn("long_evidence_context_limited", repaired_evidence[0]["source_repair"]["actions"])
        self.assertNotIn("minimum separation of 5.0", repaired_evidence[0]["source_context"])
        result = verify_candidates(config, repaired_evidence, repaired_candidates)
        self.assertEqual(result["verified_rules"], [])


class ReviewAssistantPacketTests(unittest.TestCase):
    def test_packets_are_bounded_and_advisory(self) -> None:
        rule = _review_rule(support_gaps=["operator_not_supported"])
        evidence = [{
            "evidence_id": "ev_current",
            "page": 3,
            "evidence_text": "4.5 m",
            "source_context": "minimum " + ("x" * 1200),
        }]
        report = build_review_assistant_packets([rule], evidence, {"items": [{"evidence_id": "ev_current", "status": "reanchored"}]})
        packet = report["items"][0]
        self.assertTrue(report["advisory_only"])
        self.assertTrue(packet["advisory_only"])
        self.assertLessEqual(len(packet["source"]["repaired_context"]), 900)
        self.assertIn("operator", packet["suggested_next_action"])


class BundleSelectionTests(unittest.TestCase):
    """Finding 5: zero-supported-field packets never join a bundle."""

    def test_best_bundle_skips_packets_without_supported_fields(self) -> None:
        scored = [
            {"evidence_id": "ev_current", "raw_score": 5.0, "supported_fields": ["value", "unit"]},
            {"evidence_id": "ev_quality_only", "raw_score": 0.9, "supported_fields": []},
            {"evidence_id": "ev_useful", "raw_score": 4.0, "supported_fields": ["operator"]},
        ]
        bundle = _best_bundle(scored, current_evidence_id="ev_current", bundle_size=4)
        ids = [item["evidence_id"] for item in bundle]
        self.assertIn("ev_current", ids)
        self.assertIn("ev_useful", ids)
        self.assertNotIn("ev_quality_only", ids)


class ValueAnchoringTests(unittest.TestCase):
    """Finding 6: '4.5' must never anchor inside '14.5' in any copy."""

    def test_intelligence_contains_value_is_boundary_aware(self) -> None:
        self.assertFalse(intelligence_contains_value("the height is 14.5 m", "4.5"))
        self.assertTrue(intelligence_contains_value("the setback is 4.5 m", "4.5"))
        self.assertTrue(intelligence_contains_value("lot area of 1,115 m2", "1115"))

    def test_repair_contains_value_is_boundary_aware(self) -> None:
        self.assertFalse(repair_contains_value("the height is 14.5 m", "4.5"))
        self.assertTrue(repair_contains_value("the setback is 4.5 m", "4.5"))
        self.assertFalse(repair_contains_value("a value of 50 m", "5"))

    def test_single_source_bundle_rejects_substring_value_anchor(self) -> None:
        candidate = {"value": "4.5", "operator": ">=", "constraint_type": "minimum"}
        evidence_by_id = {
            "ev_sub": {
                "evidence_id": "ev_sub",
                "evidence_text": "The building height shall be a minimum of 14.5 m.",
                "section": "6.1",
                "page": 2,
            }
        }
        bundle = [{"evidence_id": "ev_sub", "raw_score": 5.0}]
        members, key, value_member = _single_source_bundle(bundle, candidate, evidence_by_id)
        self.assertIsNone(value_member)
        self.assertEqual(members, [])

    def test_single_source_bundle_accepts_exact_value_anchor(self) -> None:
        candidate = {"value": "4.5", "operator": ">=", "constraint_type": "minimum"}
        evidence_by_id = {
            "ev_exact": {
                "evidence_id": "ev_exact",
                "evidence_text": "The setback shall be a minimum of 4.5 m.",
                "section": "6.1",
                "page": 2,
            }
        }
        bundle = [{"evidence_id": "ev_exact", "raw_score": 5.0}]
        members, key, value_member = _single_source_bundle(bundle, candidate, evidence_by_id)
        self.assertIsNotNone(value_member)
        self.assertEqual(key, "section:6.1")


class LegalExceptionCueTests(unittest.TestCase):
    """Finding 7: one canonical cue set guards the promotion path."""

    def test_canonical_cue_set_contents(self) -> None:
        # The exclud* family joined after a live P9-fed false verify: an
        # exclusion criterion ("...the total area being excluded does not
        # exceed 3.1 m") verified as a height cap.
        self.assertEqual(
            LEGAL_EXCEPTION_CUES,
            frozenset(
                {
                    "except",
                    "exception",
                    "notwithstanding",
                    "unless",
                    "covenant",
                    "excluding",
                    "excluded",
                    "exclusion",
                }
            ),
        )

    def test_exclusion_criterion_keeps_its_cues(self) -> None:
        # The live Vancouver leak: an eligibility test for a floor-area
        # exclusion that reads like a height cap. Its cues must survive.
        text = (
            "the ceiling height, excluding roof structure, of the total area "
            "being excluded does not exceed 3.1 m, measured from the floor"
        )
        self.assertEqual(unresolved_exception_cues(text), {"excluding", "excluded"})

    def test_resolved_default_rule_preamble_is_discounted(self) -> None:
        # Calgary 1P2007 default-rule preambles: the clause itself resolves
        # the exception by naming where overrides live, so the stated value
        # is the operative default and must stay verifiable.
        for text in (
            "Unless otherwise referenced in subsections (3.1) and (3.2), a minimum "
            "separation of 5.0 metres is required between the closest facade",
            "Unless otherwise referenced in subsection (4.1), the maximum building "
            "height for a Backyard Suite is 7.5 metres.",
            "unless otherwise provided in this Bylaw, the minimum setback is 6.0 m",
        ):
            self.assertEqual(unresolved_exception_cues(text), set(), text)

    def test_discretionary_unless_keeps_its_cue(self) -> None:
        # "unless approved by the Director" is a discretionary escape, not a
        # resolved cross-reference — the cue must hold the rule for review.
        text = "the minimum site width is 9.8 m, unless approved by the Director of Planning"
        self.assertEqual(unresolved_exception_cues(text), {"unless"})

    def test_bare_preamble_without_target_keeps_its_cue(self) -> None:
        # "unless otherwise specified" with no named target (Burnaby lane-yard
        # row) leaves the override universe open — it must stay held, unlike
        # the Calgary form that points at its overriding subsections.
        text = "Lane Yard unless otherwise specified | 1.5 m"
        self.assertEqual(unresolved_exception_cues(text), {"unless"})

    def test_promotion_blocker_fires_for_every_cue(self) -> None:
        for cue in LEGAL_EXCEPTION_CUES:
            attempt = {
                "promotion_ready": True,
                "retry_decision": "verified",
                "retry_support_gaps": [],
                "promotion_risk_flags": [],
                "bundle_missing_fields": [],
                "bundle_provenance_key": "section:6.1",
                "value": "4.5",
                "bundle_evidence_quote": f"Setback of 4.5 m applies, {cue} as provided in Section 6.20.",
            }
            promoted_rule = {"rule_id": "x", "support_gaps": []}
            blockers = _bundle_promotion_blockers(attempt, promoted_rule)
            self.assertIn("bundle_contains_exception_or_covenant_language", blockers, cue)

    def test_clean_attempt_has_no_exception_blocker(self) -> None:
        attempt = {
            "promotion_ready": True,
            "retry_decision": "verified",
            "retry_support_gaps": [],
            "promotion_risk_flags": [],
            "bundle_missing_fields": [],
            "bundle_provenance_key": "section:6.1",
            "value": "4.5",
            "bundle_evidence_quote": "Setback of 4.5 m applies to all principal buildings.",
        }
        blockers = _bundle_promotion_blockers(attempt, {"rule_id": "x", "support_gaps": []})
        self.assertNotIn("bundle_contains_exception_or_covenant_language", blockers)


class GuardRejectedResolutionTests(unittest.TestCase):
    """Finding 8: guard-rejected promotions must not be labelled promotion-ready."""

    def _bundle_attempt(self) -> dict[str, Any]:
        return {
            "original_rule_id": "adv_rule_001",
            "promotion_ready": True,
            "retry_decision": "verified",
            "retry_support_gaps": [],
            "promotion_risk_flags": [],
        }

    def test_remaining_promotion_ready_rule_is_marked_guard_rejected(self) -> None:
        # The rule is still in the review queue, so apply_bundle_promotions
        # must have rejected it; the resolution has to say so.
        report = build_review_resolution(
            [_review_rule(support_gaps=[])],
            review_router_report={"items": []},
            evidence_bundle_rerun_report={"attempts": [self._bundle_attempt()]},
        )
        item = report["items"][0]
        self.assertEqual(item["resolution"], "promotion_rejected_by_guard")
        self.assertFalse(item["can_promote_after_evidence_fix"])
        self.assertFalse(item["promotable_now"])

    def test_promotable_now_count_is_always_zero(self) -> None:
        report = build_review_resolution(
            [_review_rule(), _review_rule(rule_id="adv_rule_002", support_gaps=[])],
            review_router_report={"items": []},
            evidence_bundle_rerun_report={"attempts": [self._bundle_attempt()]},
        )
        self.assertEqual(report["summary"]["promotable_now_count"], 0)

    def test_context_gap_rule_still_has_evidence_fix_path(self) -> None:
        report = build_review_resolution(
            [_review_rule(support_gaps=["text_condition_not_supported"])],
            review_router_report={"items": []},
            evidence_bundle_rerun_report={"attempts": []},
        )
        self.assertTrue(report["items"][0]["can_promote_after_evidence_fix"])

    def test_operator_gap_rule_has_no_evidence_fix_path(self) -> None:
        report = build_review_resolution(
            [_review_rule(support_gaps=["operator_not_supported"])],
            review_router_report={"items": []},
            evidence_bundle_rerun_report={"attempts": []},
        )
        self.assertFalse(report["items"][0]["can_promote_after_evidence_fix"])


class HeuristicBriefTests(unittest.TestCase):
    """Finding 9: proposed_value must be a field value or None, never guidance."""

    def test_proposed_value_is_none_and_guidance_moves_to_rationale(self) -> None:
        rule = _review_rule(
            support_gaps=["applies_to_not_supported"],
            blocking_reason="applies_to not grounded",
            suggested_fix="Ground applies_to in the cited row/column header.",
        )
        brief = heuristic_brief(rule)
        self.assertEqual(brief["likely_fix"]["field"], "applies_to")
        self.assertIsNone(brief["likely_fix"]["proposed_value"])
        self.assertIn("Ground applies_to", brief["likely_fix"]["rationale"])

    def test_no_dominant_field_keeps_null_value(self) -> None:
        brief = heuristic_brief(_review_rule(support_gaps=["cross_family_value_collision"]))
        self.assertEqual(brief["likely_fix"]["field"], "none")
        self.assertIsNone(brief["likely_fix"]["proposed_value"])


class ReviewTextHelperTests(unittest.TestCase):
    """Finding 10: one shared wording for reviewer-facing helpers."""

    def test_candidate_sentence_defaults(self) -> None:
        self.assertEqual(candidate_sentence({}), "The rule has a constraint rule.")
        sentence = candidate_sentence(_review_rule())
        self.assertIn("principal building", sentence)
        self.assertIn("4.5 m", sentence)

    def test_evidence_sentence_truncates_and_handles_missing(self) -> None:
        self.assertEqual(evidence_sentence({}), "No cited evidence text is available.")
        long_text = "a" * 400
        rendered = evidence_sentence({"evidence_text": long_text})
        self.assertEqual(len(rendered), 260)
        self.assertTrue(rendered.endswith("..."))

    def test_counter_rows_and_count_lines(self) -> None:
        from collections import Counter

        rows = counter_rows(Counter({"x": 2, "y": 1}))
        self.assertEqual(rows[0], {"name": "x", "count": 2})
        self.assertEqual(count_lines(rows), ["- `x`: 2", "- `y`: 1"])
        self.assertEqual(count_lines([]), ["- none"])

    def test_router_and_intelligence_share_candidate_wording(self) -> None:
        # The two modules used to carry drifted copies; both now defer to the
        # shared helper, so a bare rule renders identically everywhere.
        from burnaby_prototype import evidence_intelligence, review_resolution, review_router

        for module in (review_router, review_resolution, evidence_intelligence):
            self.assertIs(getattr(module, "candidate_sentence"), candidate_sentence)


if __name__ == "__main__":
    unittest.main()
