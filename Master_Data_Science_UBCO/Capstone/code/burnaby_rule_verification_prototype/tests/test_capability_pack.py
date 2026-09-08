"""Future-city capability pack: floor_space_ratio family + config-extensible cues.

These tests pin two properties:
1. The FSR family exists in the shared vocabulary with safe boundaries (no
   'far' prose alias, ratio patterns ordered before floor_area) while staying
   DORMANT for both current cities (nothing activated — the adversarial suite
   pins that end to end).
2. The per-city cue knobs (rule_object_text_cue_extras,
   material_condition_cue_extras, unit_rewrites) are byte-neutral when absent
   and take effect only for the configured city.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.config import load_config
from burnaby_prototype.domain_schema import (
    RULE_OBJECT_ALIASES,
    RULE_OBJECT_ALLOWED_UNITS,
    TEXT_RULE_OBJECT_PATTERNS,
    unit_key,
    unit_visible,
)
from burnaby_prototype.geometry_operator import derive_geometry_operator
from burnaby_prototype.gis_felt_export import _parameter_key, _value_numeric
from burnaby_prototype.normalization import normalize_candidate
from burnaby_prototype.normalization_rules import (
    material_condition_cue_extras,
    rule_object_text_cue_extras,
    unit_rewrite,
)
from burnaby_prototype.support_checks import rule_object_supported, rule_object_unit_compatible
from burnaby_prototype.table_natural_logic import RULE_OBJECT_CUES, _matching_rule_object
from burnaby_prototype.text_span_proof import _material_condition
from burnaby_prototype.verification import verify_candidates

CONFIG = ROOT / "configs" / "burnaby_r1.json"


class FloorSpaceRatioFamilyTests(unittest.TestCase):
    def test_fsr_spellings_canonicalize_and_far_stays_out_of_prose(self) -> None:
        for spelling in ("fsr", "floor space ratio", "floor area ratio"):
            self.assertEqual(unit_key(spelling), "fsr", spelling)
        # 'far' is NOT a unit alias: as one it would enter the table-proof
        # refutation vocabulary and match prose like "as far as".
        self.assertEqual(unit_key("far"), "far")
        self.assertFalse(unit_visible("setbacks extend as far as the lane", "fsr"))
        # The FAR spelling lives in the rule-object FIELD alias map instead.
        self.assertEqual(RULE_OBJECT_ALIASES["far"], "floor_space_ratio")

    def test_fsr_is_dimensionless_only(self) -> None:
        self.assertEqual(RULE_OBJECT_ALLOWED_UNITS["floor_space_ratio"], {"fsr"})
        self.assertTrue(rule_object_unit_compatible({"rule_object": "floor_space_ratio", "unit": "fsr"}))
        self.assertTrue(rule_object_unit_compatible({"rule_object": "floor_space_ratio", "unit": "floor space ratio"}))
        self.assertTrue(rule_object_unit_compatible({"rule_object": "floor_space_ratio", "unit": None}))
        self.assertFalse(rule_object_unit_compatible({"rule_object": "floor_space_ratio", "unit": "%"}))
        self.assertFalse(rule_object_unit_compatible({"rule_object": "floor_space_ratio", "unit": "m2"}))
        # City-verbatim phrasing is NOT silently accepted by shared vocabulary.
        self.assertFalse(
            rule_object_unit_compatible({"rule_object": "floor_space_ratio", "unit": "multiplied by the site area"})
        )

    def test_pattern_ordering_ratio_before_floor_area(self) -> None:
        text_order = [family for family, _ in TEXT_RULE_OBJECT_PATTERNS]
        self.assertLess(text_order.index("floor_space_ratio"), text_order.index("floor_area"))
        cue_order = list(RULE_OBJECT_CUES)
        self.assertLess(cue_order.index("floor_space_ratio"), cue_order.index("floor_area"))
        # First-match-wins consequence: ratio text claims the ratio family.
        self.assertEqual(_matching_rule_object("maximum floor area ratio 0.6"), "floor_space_ratio")

    def test_floor_area_ratio_text_canonicalizes_to_fsr_family(self) -> None:
        ratio = normalize_candidate(
            {"rule_object": "floor area ratio", "value": "0.6"},
            {"evidence_text": "maximum floor area ratio 0.6"},
            None,
        )
        self.assertEqual(ratio.get("rule_object"), "floor_space_ratio")
        # Regression: plain floor-area and lot-area text keep their families.
        floor = normalize_candidate(
            {"rule_object": "floor_area", "value": "186", "unit": "sq. m"},
            {"evidence_text": "The floor area for a laneway house must not exceed 186 sq. m."},
            None,
        )
        self.assertEqual(floor.get("rule_object"), "floor_area")

    def test_geometry_and_export_projection(self) -> None:
        op = derive_geometry_operator({"rule_object": "floor_space_ratio"})
        self.assertEqual(op["operation"], "density_ratio_cap")
        self.assertEqual(_parameter_key({"rule_object": "floor_space_ratio"}), "max_floor_space_ratio")
        self.assertEqual(_value_numeric("0.25"), 0.25)

    def test_sentence_final_period_does_not_hide_value(self) -> None:
        # Found by adv_fsr_direction_flip: 'at least 0.25.' states 0.25.
        from burnaby_prototype.domain_schema import token_visible

        self.assertTrue(token_visible("the floor space ratio must be at least 0.25.", "0.25"))
        # Decimal tails still disqualify (section references stay safe).
        self.assertFalse(token_visible("see section 101.5.2 for details", "101.5"))
        self.assertFalse(token_visible("a value of 0.253 applies", "0.25"))


class CueExtrasConfigTests(unittest.TestCase):
    PROSE = "buildings must be located at least 0.9 m from the ultimate rear property line."

    def _config_with_extras(self) -> dict:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config.setdefault("normalization", {})["rule_object_text_cue_extras"] = {
            "setback": ["property line"]
        }
        return config

    def test_accessors_default_to_empty(self) -> None:
        self.assertEqual(rule_object_text_cue_extras({}), {})
        self.assertEqual(material_condition_cue_extras({}), frozenset())
        self.assertIsNone(unit_rewrite("floor_area", "anything", "anything", []))

    def test_rule_object_cue_extras_flip_support_only_for_configured_family(self) -> None:
        plain_config = json.loads(CONFIG.read_text(encoding="utf-8"))
        candidate = {"rule_object": "setback"}
        # Without extras: prose setbacks phrased via 'property line' miss.
        self.assertFalse(rule_object_supported(plain_config, candidate, self.PROSE))
        # With extras: supported — for the configured family only.
        extras_config = self._config_with_extras()
        self.assertTrue(rule_object_supported(extras_config, candidate, self.PROSE))
        self.assertFalse(
            rule_object_supported(extras_config, {"rule_object": "height"}, self.PROSE)
        )

    def test_cue_extras_end_to_end_removes_only_the_rule_object_gap(self) -> None:
        evidence = [{
            "evidence_id": "cue_ev_001", "page": 1, "evidence_type": "clause",
            "evidence_text": self.PROSE, "source_context": self.PROSE,
        }]
        candidates = [{
            "candidate_id": "cue_cand_001", "evidence_id": "cue_ev_001",
            "rule_object": "setback", "constraint_type": "minimum",
            "constraint_scope": "rear_yard", "applies_to": "rear",
            "operator": ">=", "value": "0.9", "unit": "m",
            "extraction_method": "pipeline5_final_registry",
            "source_stream": "gemini_text_block",
        }]
        plain = verify_candidates(json.loads(CONFIG.read_text(encoding="utf-8")), evidence, candidates)
        plain_gaps = plain["review_needed"][0]["support_gaps"]
        self.assertIn("rule_object_not_supported", plain_gaps)

        extras = verify_candidates(self._config_with_extras(), evidence, candidates)
        extras_gaps = extras["review_needed"][0]["support_gaps"]
        self.assertNotIn("rule_object_not_supported", extras_gaps)
        # The knob is additive support, not a verifier bypass: the candidate
        # still faces every other gate (here: single-source text consensus).
        self.assertIn("text_candidate_requires_review", extras_gaps)

    def test_material_condition_extras_are_fail_closed(self) -> None:
        # 'within the flood plain' has no shared material cue -> non-material.
        self.assertFalse(_material_condition("within the flood plain"))
        # With per-city extras it becomes material -> more review pressure.
        self.assertTrue(_material_condition("within the flood plain", None, frozenset({"flood"})))

    def test_unit_rewrite_maps_city_phrasing_only_when_configured(self) -> None:
        specs = [{
            "rule_objects": ["floor_area"],
            "all_terms": ["multiplied by the site area"],
            "unit": "fsr",
            "set_rule_object": "floor_space_ratio",
        }]
        hit = unit_rewrite("floor_area", "multiplied by the site area", "", specs)
        self.assertEqual(hit, {"unit": "fsr", "rule_object": "floor_space_ratio"})
        self.assertIsNone(unit_rewrite("height", "multiplied by the site area", "", specs))
        self.assertIsNone(unit_rewrite("floor_area", "sq. m", "", specs))


class StrictnessAuditTests(unittest.TestCase):
    """The audit's classifiers must only flag TRUE lexicon misses."""

    def test_numeric_equivalence_classifier(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from audit_strictness import _numeric_equivalence_would_fix

        # '6.00' in evidence for value '6.0' is a float-equal spelling miss.
        rule = {"value": "6.0", "source": {"evidence_text": "separation of 6.00 m"}}
        self.assertIsNotNone(_numeric_equivalence_would_fix(rule, "separation of 6.00 m"))
        # Same spelling -> boundary matching already finds it -> not a miss.
        rule = {"value": "6.0", "source": {"evidence_text": "separation of 6.0 m"}}
        self.assertIsNone(_numeric_equivalence_would_fix(rule, "separation of 6.0 m"))
        # A different number is a genuine gap, never an equivalence.
        rule = {"value": "6.0", "source": {"evidence_text": "separation of 7.5 m"}}
        self.assertIsNone(_numeric_equivalence_would_fix(rule, "separation of 7.5 m"))

    def test_operator_synonym_classifier(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from audit_strictness import _operator_synonym_would_fix

        rule = {"operator": "<="}
        # Unlisted synonym present -> actionable miss. ('may not exceed' would
        # NOT count: it substring-contains the listed 'not exceed' — the very
        # reason the real audit found zero misses.)
        self.assertIsNotNone(_operator_synonym_would_fix(rule, "the height shall be no more than 9 m"))
        # Current lexicon already covers it -> not a miss.
        self.assertIsNone(_operator_synonym_would_fix(rule, "the maximum height is 9 m"))
        # No bound wording at all -> genuine gap.
        self.assertIsNone(_operator_synonym_would_fix(rule, "the height is discussed in 4.2"))


if __name__ == "__main__":
    unittest.main()


class SubsectionReferenceTests(unittest.TestCase):
    """Paren-wrapped bare numbers are cross-references, never measurements.

    Pinned from the live Calgary leak: 'required in subsection (3.1)' let the
    reference '(3.1)' masquerade as the 3.1 m value, anchoring every support
    window on the wrong clause — building_separation >= 3.1 nearly verified.
    """

    def test_parenthesized_reference_is_not_a_value(self) -> None:
        from burnaby_prototype.domain_schema import token_visible
        from burnaby_prototype.support_checks import value_local_window

        ref_text = "0.6 metres into the minimum separation area required in subsection (3.1);"
        self.assertFalse(token_visible(ref_text, "3.1"))
        # A real occurrence elsewhere still wins, and the window anchors THERE.
        full = ref_text + " (b) projections must each have a maximum length of 3.1 metres"
        self.assertTrue(token_visible(full, "3.1"))
        window = value_local_window(full, "3.1")
        self.assertIn("maximum length", window)
        self.assertNotIn("separation", window)


class NumericReferenceShapeTests(unittest.TestCase):
    """Citation-shaped numbers are never measurements (external-review finds)."""

    def test_codex_counterexamples_are_closed(self) -> None:
        from burnaby_prototype.domain_schema import token_visible

        # Amendment codes: '10P2019' must never satisfy value 10.
        self.assertFalse(token_visible("as amended by 10P2019", "10"))
        # Prose section references: 'section 3.1' states a location.
        self.assertFalse(token_visible("see section 3.1 for details", "3.1"))
        self.assertFalse(token_visible("under subsection 2.1 thereof", "2.1"))
        # Paren-wrapped number FOLLOWED BY A UNIT is a real measurement.
        self.assertTrue(token_visible("a clearance of (3.0) metres", "3.0"))
        # Paren-wrapped bare number remains a reference.
        self.assertFalse(token_visible("required in subsection (3.1);", "3.1"))
        # Plain measurements are unaffected.
        self.assertTrue(token_visible("a setback of 3.1 metres", "3.1"))
        self.assertTrue(token_visible("must be at least 0.25.", "0.25"))


class ConfigValidatorTests(unittest.TestCase):
    """Configs are trusted artifacts; the validator pins their STRUCTURE."""

    def _validate(self, config: dict) -> list[str]:
        sys.path.insert(0, str(ROOT / "scripts"))
        from validate_config import validate_config

        return validate_config(config, "test")

    def test_all_committed_configs_are_valid(self) -> None:
        for path in sorted((ROOT / "configs").glob("*.json")):
            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(self._validate(config), [], path.name)

    def test_physical_unit_conversion_rewrites_are_rejected(self) -> None:
        # The external-review exploit: a 'feet'->'m' rewrite laundering a unit
        # mismatch. Phrasing rewrites may only target known canonical units,
        # and a spec whose match terms ARE a different known unit is invalid.
        bad = {
            "normalization": {
                "unit_rewrites": [
                    {"rule_objects": ["height"], "all_terms": ["storeys"], "unit": "m"}
                ]
            }
        }
        problems = self._validate(bad)
        self.assertTrue(any("physical-unit conversion" in p for p in problems))
        unknown_target = {
            "normalization": {"unit_rewrites": [{"all_terms": ["cubits"], "unit": "cubit"}]}
        }
        self.assertTrue(any("not a known canonical unit" in p for p in self._validate(unknown_target)))

    def test_unknown_families_and_directions_are_rejected(self) -> None:
        bad = {
            "verification": {
                "gis_text_rule_contract": ["unicorn_density"],
                "rule_family_direction": {"height": "sideways"},
            }
        }
        problems = self._validate(bad)
        self.assertEqual(len(problems), 2)


class MalformedEvidenceTypeTests(unittest.TestCase):
    def test_unknown_evidence_type_faces_the_text_gate(self) -> None:
        # An unrecognized evidence_type must be treated as NON-table evidence:
        # it faces the text gate (fail-closed), never the table bypass.
        evidence = [{
            "evidence_id": "weird_ev", "page": 1, "evidence_type": "banana",
            "evidence_text": "Rear principal buildings maximum height shall not exceed 7.5 m.",
            "source_context": "Rear principal buildings maximum height shall not exceed 7.5 m.",
        }]
        candidates = [{
            "candidate_id": "weird_cand", "evidence_id": "weird_ev",
            "rule_object": "height", "constraint_type": "maximum",
            "constraint_scope": "building", "applies_to": "Rear Principal Buildings",
            "operator": "<=", "value": "7.5", "unit": "m",
            "extraction_method": "pipeline5_final_registry",
            "source_stream": "gemini_text_block",
        }]
        result = verify_candidates(json.loads(CONFIG.read_text(encoding="utf-8")), evidence, candidates)
        pool = [*result["verified_rules"], *result["review_needed"]]
        gaps = pool[0]["support_gaps"]
        self.assertIn("text_candidate_requires_review", gaps)
