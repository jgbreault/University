#!/usr/bin/env python3
"""City-config validator — structure + the config TRUST MODEL, made explicit.

Threat model (also documented in ADDING_A_FAMILY_OR_CITY.md): a city config is
a TRUSTED, code-reviewed artifact — the same tier as the verifier source. A
malicious committed config can mis-declare a city's legal regime (e.g. flip a
family's direction) exactly as malicious committed code could; no validator
can know legal truth. What this validator DOES guarantee mechanically:

* structural sanity — families, units, directions all come from the closed
  shared vocabulary (typos cannot silently disable a gate);
* unit_rewrites may only map phrasing onto KNOWN canonical unit keys, and a
  rewrite whose match terms themselves canonicalize to a DIFFERENT known unit
  is rejected (a 'feet'->'m' style physical-unit conversion is never a
  legitimate phrasing rewrite — found by external review);
* a human-review listing of every direction and rewrite, so the dangerous
  knobs are one `git diff` glance, never buried.

Exit 1 on any violation. Run by tests over every committed config.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.domain_schema import KNOWN_RULE_OBJECTS, UNIT_ALIASES, unit_key


def validate_config(config: dict, name: str) -> list[str]:
    problems: list[str] = []
    verification = config.get("verification", {}) or {}
    normalization = config.get("normalization", {}) or {}

    for field in ("gis_text_rule_contract", "single_source_text_rule_contract"):
        for family in verification.get(field, []) or []:
            if family not in KNOWN_RULE_OBJECTS:
                problems.append(f"{name}: {field} names unknown family '{family}'")

    for family, direction in (verification.get("rule_family_direction", {}) or {}).items():
        if family not in KNOWN_RULE_OBJECTS:
            problems.append(f"{name}: rule_family_direction names unknown family '{family}'")
        if direction not in ("min", "max"):
            problems.append(f"{name}: rule_family_direction[{family}] must be min|max, got '{direction}'")

    for family in (normalization.get("rule_object_text_cue_extras", {}) or {}):
        if family not in KNOWN_RULE_OBJECTS:
            problems.append(f"{name}: rule_object_text_cue_extras names unknown family '{family}'")

    for index, spec in enumerate(normalization.get("unit_rewrites", []) or []):
        target = spec.get("unit")
        if target not in UNIT_ALIASES:
            problems.append(
                f"{name}: unit_rewrites[{index}] target '{target}' is not a known canonical unit key"
            )
        if spec.get("set_rule_object") and spec["set_rule_object"] not in KNOWN_RULE_OBJECTS:
            problems.append(
                f"{name}: unit_rewrites[{index}] set_rule_object '{spec['set_rule_object']}' unknown"
            )
        for term_field in ("all_terms", "any_terms"):
            for term in spec.get(term_field, []) or []:
                term_unit = unit_key(term)
                if term_unit in UNIT_ALIASES and term_unit != target:
                    problems.append(
                        f"{name}: unit_rewrites[{index}] matches the unit phrase '{term}' "
                        f"({term_unit}) but maps it to '{target}' — physical-unit conversion "
                        "is never a phrasing rewrite"
                    )
    return problems


def review_listing(config: dict, name: str) -> list[str]:
    lines = []
    verification = config.get("verification", {}) or {}
    normalization = config.get("normalization", {}) or {}
    for family, direction in sorted((verification.get("rule_family_direction", {}) or {}).items()):
        lines.append(f"  {name}: direction {family} = {direction}")
    for spec in normalization.get("unit_rewrites", []) or []:
        lines.append(f"  {name}: unit_rewrite {spec}")
    for family, phrases in sorted((normalization.get("rule_object_text_cue_extras", {}) or {}).items()):
        lines.append(f"  {name}: cue_extras {family} += {list(phrases)}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", nargs="*", default=sorted(str(p) for p in (ROOT / "configs").glob("*.json")))
    args = parser.parse_args()
    all_problems: list[str] = []
    for path in args.configs:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
        name = Path(path).stem
        all_problems += validate_config(config, name)
        for line in review_listing(config, name):
            print(line)
    if all_problems:
        print("\nCONFIG VALIDATION FAILED:")
        for problem in all_problems:
            print(f"  ✗ {problem}")
        return 1
    print("\nall configs structurally valid (trust model: configs are reviewed artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
