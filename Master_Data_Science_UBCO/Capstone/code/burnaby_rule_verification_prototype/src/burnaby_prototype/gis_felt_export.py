"""Rich GIS/Felt handoff export, projected from verified rules only.

This is a PURE POST-VERIFICATION PROJECTION. It reads the verifier's already
decided ``verified_rules`` and reshapes them into the map-oriented export the
Felt dashboard consumes. It adds two machine-usable fields the slim
``gis_rule_contract.json`` lacks:

* ``value_numeric`` -- the typed float of ``value`` (``"281"`` -> ``281.0``), or
  ``None`` when the value is non-numeric (``"Permitted"``) or ambiguous
  (a multi-number string such as ``"3 to 4"``).
* ``geometry_target`` -- a coarse, Felt-friendly STRING naming the geometry a
  rule constrains (``front_lot_line``, ``building_footprint`` ...), derived from
  rule_object and, for setbacks, constraint_scope. Never guessed: an unmapped
  family/scope yields ``None``.

Because nothing here feeds back into the verifier (the benchmark, holdout, and
adversarial suites never read this file), building this export cannot move any
trust metric. The schema is validated at write time, exactly like the slim
contract, so a malformed export fails loudly rather than reaching GIS.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .applicability import applicability_slug
from .geometry_operator import AXIS_BY_SCOPE, derive_geometry_operator
from .normalization_rules import CANONICAL_SETBACK_SCOPES, universal_setback_scope
from .rule_text import _rule_sentence


GIS_FELT_EXPORT_SCHEMA_VERSION = "gis_felt_export_v1"
_GIS_FELT_EXPORT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "gis_felt_export.schema.json"
)

# Coarse Felt geometry targets. Closed set; mirrored by the schema enum.
_GEOMETRY_BY_OBJECT = {
    "permitted_use": "zoning_polygon",
    "lot_area": "parcel_polygon",
    "floor_area": "building_footprint",
    "floor_space_ratio": "parcel_polygon",
    "height": "building_footprint",
    "storeys": "building_footprint",
    "building_separation": "building_footprint",
    "dwelling_units": "parcel_polygon",
    "automatic_sprinkler": "dwelling_unit",
    "fire_access_corridor": "access_path",
    "lot_coverage": "building_footprint",
    "impervious_surface": "parcel_polygon",
}
# Setbacks refine the target by which lot line the yard scope names.
# Single-sourced from the geometry operator's scope->axis map so the two can
# never drift again. The only naming difference is the lane edge: the geometry
# axis is called ``lane_lot_line`` (it is an offset axis like the other lot
# lines), while the Felt map layer has always been named simply ``lane``.
_FELT_LAYER_BY_AXIS = {"lane_lot_line": "lane"}
_SETBACK_GEOMETRY_BY_SCOPE = {
    scope: _FELT_LAYER_BY_AXIS.get(axis, axis) for scope, axis in AXIS_BY_SCOPE.items()
}
GEOMETRY_TARGETS = sorted(
    set(_GEOMETRY_BY_OBJECT.values()) | set(_SETBACK_GEOMETRY_BY_SCOPE.values())
)

# rule_object -> export grouping used by the dashboard and the buildable-area map.
_EXPORT_GROUP_BY_OBJECT = {
    "permitted_use": "use_context",
    "lot_area": "capacity",
    "floor_area": "capacity",
    "floor_space_ratio": "capacity",
    "dwelling_units": "capacity",
    "automatic_sprinkler": "fire_access",
    "fire_access_corridor": "fire_access",
}
# Groups whose numeric rules roll up into buildable_area_parameters.
_PARAMETER_GROUPS = {"buildable_area", "capacity", "fire_access"}

# Map-layer metadata, emitted only for the geometry targets actually present.
_LAYER_INFO = {
    "parcel_polygon": "Parcel boundary polygons for lot-level filters and capacity context.",
    "zoning_polygon": "Zoning district polygons for use-permission context.",
    "building_footprint": "Building footprint polygons for height, storey, separation, and coverage limits.",
    "front_lot_line": "Front lot-line segments for verified front street-yard setbacks.",
    "side_lot_line": "Side lot-line segments for interior and flanking side-yard setbacks.",
    "rear_lot_line": "Rear lot-line segments for rear-yard setbacks.",
    "lane": "Lane edges for verified lane-yard setbacks.",
    "dwelling_unit": "Dwelling-unit points/areas for unit-level trigger predicates (e.g. sprinklers).",
    "access_path": "Fire-access corridor paths for width and vertical-clearance checks.",
}

_CONSUMER_NOTES = [
    "This export is derived only from verified_rules.json.",
    "Review, rejected, and not_used rules are not executable constraints.",
    "Map consumers should display review_blockers as warnings, not apply them as zoning logic.",
]


def _value_numeric(value: Any) -> float | None:
    """Return the typed float of a rule value, or None when not safely numeric.

    Guards (matching the verifier's numeric-token discipline): bools and None
    are not numbers; any alphabetic character (``"R1"``, ``"Permitted"``) means
    the value is not numeric; thousands separators are stripped; and a string
    carrying more than one number (``"3 to 4"``, ``"0.45 or 45%"``) is ambiguous
    and returns None rather than silently picking the first number. ``"0"`` maps
    to ``0.0`` (a real value, not None).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or re.search(r"[A-Za-z]", text):
        return None
    numbers = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if len(numbers) != 1:
        return None
    try:
        return float(numbers[0])
    except ValueError:
        return None


def _geometry_target(rule_object: Any, constraint_scope: Any) -> str | None:
    """Return a coarse Felt geometry target string, or None when underivable."""
    rule_object = str(rule_object or "")
    if rule_object == "setback":
        # Never guess: an unrecognized yard scope yields None.
        return _SETBACK_GEOMETRY_BY_SCOPE.get(str(constraint_scope or ""))
    return _GEOMETRY_BY_OBJECT.get(rule_object)


def _export_group(rule_object: Any) -> str:
    return _EXPORT_GROUP_BY_OBJECT.get(str(rule_object or ""), "buildable_area")


def _role(text: str) -> str:
    """Coarse building role from applies_to/condition text for parameter keys."""
    text = text.lower()
    if "accessory" in text:
        return "accessory_building"
    has_principal = "principal" in text
    if "front" in text and "rear" in text:
        return "front_rear_principal" if has_principal else "building"
    if "front" in text:
        return "front_principal" if has_principal else "building"
    if "rear" in text:
        return "rear_principal" if has_principal else "building"
    return "building"


def _num_slug(value_numeric: float) -> str:
    """Stable slug for a numeric value, used only to disambiguate key clashes."""
    text = ("%g" % value_numeric)
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def _parameter_key(rule: dict[str, Any]) -> str:
    """Deterministic, human-readable grouping key. Display/dedupe only.

    This is NOT a verification key and never feeds the verifier. Equivalent
    rules from different sources (e.g. a table cell and prose both stating the
    6.0 m front/rear principal separation) collapse to the same key so the
    buildable-area map lists one parameter with both source rule ids.

    Rules carrying structured applicability (matrix-column rules: lot
    coverage by dwelling-type column, per-column dwelling maxima) get an
    ``__<slug>`` suffix so the four coverage limits are four parameters
    (max_lot_coverage_pct__rowhouse, ...__ssmu_1_2u, ...) instead of one
    colliding key. Selector-less rules keep byte-identical keys.
    """
    base = _base_parameter_key(rule)
    slug = applicability_slug(rule.get("applicability"))
    return f"{base}__{slug}" if slug else base


def _base_parameter_key(rule: dict[str, Any]) -> str:
    rule_object = str(rule.get("rule_object") or "")
    scope = str(rule.get("constraint_scope") or "")
    text = f"{rule.get('applies_to') or ''} {rule.get('condition') or ''}".lower()

    if rule_object == "setback":
        return {
            "street_yard_front": "front_street_yard_setback_m",
            "street_yard_flanking": "flanking_street_yard_setback_m",
            "lane_yard": "lane_yard_setback_m",
            "interior_rear_yard": (
                "accessory_rear_yard_setback_m" if "accessory" in text else "rear_yard_setback_m"
            ),
            "interior_side_yard": (
                "end_unit_interior_side_yard_setback_m" if "end" in text else "interior_side_yard_setback_m"
            ),
        }.get(scope, _fallback_key(rule))
    if rule_object == "height":
        roof = "sloping_roof" if "sloping" in text else ("flat_roof" if "flat" in text else "")
        return "_".join(part for part in (_role(text), "height", roof, "m") if part)
    if rule_object == "storeys":
        return f"{_role(text)}_max_storeys"
    if rule_object == "building_separation":
        tokens = set(re.findall(r"[a-z]+", text))
        if {"front", "rear"} <= tokens:
            return "front_rear_principal_separation_m"
        if "rear" in tokens and "principal" in tokens:
            return "rear_principal_separation_m"
        if "front" in tokens and "principal" in tokens:
            return "front_principal_separation_m"
        if "other" in tokens:
            return "other_building_separation_m"
        return "building_separation_m"
    if rule_object == "lot_coverage":
        return "max_lot_coverage_pct"
    if rule_object == "impervious_surface":
        return "max_impervious_surface_pct"
    if rule_object == "dwelling_units":
        return "max_dwelling_units"
    if rule_object == "lot_area":
        return "min_lot_area_m2"
    if rule_object == "floor_area":
        return "max_floor_area_m2"
    if rule_object == "floor_space_ratio":
        return "max_floor_space_ratio"
    if rule_object == "automatic_sprinkler":
        return "sprinkler_distance_threshold_m"
    if rule_object == "fire_access_corridor":
        return (
            "fire_access_vertical_clearance_m"
            if scope == "vertical_clearance"
            else "fire_access_corridor_width_m"
        )
    if rule_object == "permitted_use":
        return "permitted_use"
    return _fallback_key(rule)


def _fallback_key(rule: dict[str, Any]) -> str:
    parts = [rule.get("rule_object"), rule.get("constraint_scope")]
    return _slug("_".join(str(part) for part in parts if part)) or "rule"


def _constraint(rule: dict[str, Any]) -> dict[str, Any]:
    """Build one constraints[] row for a verified rule."""
    source = rule.get("source", {}) if isinstance(rule.get("source"), dict) else {}
    # Coerce to string to match the GIS contract schema (rule_object: string,
    # non-null), consistent with _geometry_target/_export_group/_base_parameter_key.
    rule_object = str(rule.get("rule_object") or "")
    value_numeric = _value_numeric(rule.get("value"))
    gis_relevance = rule.get("gis_relevance") or "context"
    # Resolve the setback lot-line axis for GIS geometry. When the extractor left
    # constraint_scope generic ("setback"), derive the canonical axis scope from
    # the standard front/side/rear/lane property-line vocabulary in the rule's own
    # scope/condition/applies_to/source text. This is evidence-grounded (never a
    # guess) and bylaw-agnostic, so setbacks are drawable for any municipality. It
    # is used ONLY for GIS geometry here; the verified rule's gate-checked
    # constraint_scope is never mutated.
    scope_for_geometry = rule.get("constraint_scope")
    if rule_object == "setback" and str(scope_for_geometry or "") not in CANONICAL_SETBACK_SCOPES:
        derived_scope = universal_setback_scope(
            " ".join(
                str(rule.get(field) or "")
                for field in ("constraint_scope", "condition", "applies_to")
            )
            + " "
            + str(source.get("evidence_text") or "")
        )
        if derived_scope is not None:
            scope_for_geometry = derived_scope
    geometry_target = _geometry_target(rule_object, scope_for_geometry)
    scope_derived = scope_for_geometry != rule.get("constraint_scope")
    geometry = derive_geometry_operator(
        {**rule, "constraint_scope": scope_for_geometry} if scope_derived else rule
    )
    if geometry and scope_derived:
        # Honest provenance: the lot-line axis was derived from the rule's
        # evidence/condition text, not its (generic) constraint_scope field.
        geometry = {
            **geometry,
            "source_fields": [
                ("evidence_lot_line" if field == "constraint_scope" else field)
                for field in geometry.get("source_fields", [])
            ],
        }
    return {
        "constraint_id": rule.get("rule_id"),
        "source_rule_id": rule.get("rule_id"),
        "rule_object": rule_object,
        "parameter_key": _parameter_key(rule),
        "export_group": _export_group(rule_object),
        "geometry_target": geometry_target,
        "geometry": geometry,
        "operator": rule.get("operator"),
        "value": rule.get("value"),
        "value_numeric": value_numeric,
        "unit": rule.get("unit") or "",
        "applies_to": rule.get("applies_to") or "",
        "condition": rule.get("condition") or "",
        "exception": rule.get("exception") or "",
        # Structured applicability (dwelling type x unit range + qualifiers),
        # present only for matrix-column rules. GIS consumers use it to pick
        # the right parameter for a parcel: 600 m2 lot, 2 units planned ->
        # selector unit_range covers 2 -> ssmu_1_2u -> lot_area_threshold
        # qualifier "> 567" branch -> 30%.
        "applicability": rule.get("applicability"),
        "gis_relevance": gis_relevance,
        # gis_ready: directly drawable, mapped, and carrying a usable number.
        # Context-only, non-numeric, or unmapped verified rules remain visible
        # but must not become executable GIS parameters.
        "gis_ready": (
            gis_relevance == "direct"
            and value_numeric is not None
            and geometry_target is not None
            and geometry is not None
        ),
        "source_page": source.get("page"),
        "source_evidence_id": source.get("evidence_id") or "",
        "source_quote": source.get("evidence_text"),
        "felt_popup_sentence": _rule_sentence(rule),
    }


def _buildable_area_parameters(constraints: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll numeric constraints up into a parameter map keyed by parameter_key.

    Rules that share a parameter_key AND value/unit/operator merge into one
    parameter (carrying every source rule id). Rules that share a key but differ
    in value (e.g. two front-principal storey caps) are kept distinct by
    suffixing the key with the value, so no parameter is ever lost.
    """
    eligible = [
        c
        for c in constraints
        if c["export_group"] in _PARAMETER_GROUPS and c["value_numeric"] is not None
        and c["geometry_target"] is not None
        and c["geometry"] is not None
    ]
    # Group by (key, value, unit, operator). Each group becomes one parameter.
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for c in eligible:
        gk = (c["parameter_key"], c["value_numeric"], c["unit"], c["operator"])
        groups.setdefault(gk, []).append(c)

    # Which parameter_keys carry more than one distinct value -> need disambiguation.
    distinct_values: dict[str, set] = {}
    for parameter_key, value_numeric, unit, operator in groups:
        distinct_values.setdefault(parameter_key, set()).add((value_numeric, unit, operator))

    parameters: dict[str, Any] = {}
    for gk in sorted(groups, key=lambda k: (k[0], k[1])):
        parameter_key, value_numeric, unit, operator = gk
        members = groups[gk]
        out_key = parameter_key
        if len(distinct_values[parameter_key]) > 1:
            out_key = f"{parameter_key}__{_num_slug(value_numeric)}"
        conditions: list[str] = []
        for member in members:
            condition = member.get("condition")
            if condition and condition not in conditions:
                conditions.append(condition)
        parameters[out_key] = {
            "parameter_key": out_key,
            "value": members[0]["value"],
            "value_numeric": value_numeric,
            "unit": unit,
            "operator": operator,
            "geometry_target": members[0]["geometry_target"],
            "source_rule_ids": sorted({m["source_rule_id"] for m in members if m["source_rule_id"] is not None}),
            "source_pages": sorted(
                # Pages can arrive as int (table stream) and str (prose stream)
                # for the same parameter; a plain sort would TypeError on the
                # mixed types. Sorting by (type name, value) keeps the export
                # deterministic without coercing anyone's page representation.
                {m["source_page"] for m in members if m["source_page"] is not None},
                key=lambda p: (str(type(p)), p),
            ),
            "conditions": conditions,
        }
    return parameters


def _map_layer_requirements(constraints: list[dict[str, Any]], city: Any) -> list[dict[str, Any]]:
    present = sorted({c["geometry_target"] for c in constraints if c["geometry_target"]})
    # The example path is per-city (slugged from the config's display name,
    # e.g. "Vancouver" -> vancouver) so a non-Burnaby export never points the
    # GIS team at Burnaby's layer files.
    city_segment = _slug(str(city or "")) or "city"
    return [
        {
            "layer_key": target,
            "description": _LAYER_INFO.get(target, "Map layer used by verified constraints."),
            "example_team_file": f"code/gis_files/{city_segment}/{target}.gpkg",
        }
        for target in present
    ]


def _counts(values: Any) -> list[dict[str, Any]]:
    counter = Counter(v for v in values if v not in (None, ""))
    return [
        {"name": name, "count": count}
        for name, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _review_blockers(review_rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(review_rules),
        "category_counts": _counts(r.get("review_category") for r in review_rules),
        "action_counts": _counts(r.get("review_action_bucket") for r in review_rules),
        "rule_family_counts": _counts(r.get("rule_object") for r in review_rules),
        "example_blockers": [
            {
                "rule_id": r.get("rule_id"),
                "rule_object": r.get("rule_object"),
                "review_category": r.get("review_category"),
                "review_reason": r.get("review_reason"),
            }
            for r in review_rules[:8]
        ],
    }


def _not_used_summary(not_used_rules: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter = Counter()
    for rule in not_used_rules:
        for gap in rule.get("support_gaps", []) or []:
            reasons[gap] += 1
    return {
        "count": len(not_used_rules),
        "top_reasons": [
            {"name": name, "count": count}
            for name, count in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "example_rule_ids": [r.get("rule_id") for r in not_used_rules[:8]],
    }


def build_gis_felt_export(
    verified_rules: list[dict[str, Any]],
    review_rules: list[dict[str, Any]],
    not_used_rules: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Project verified rules into the rich Felt/GIS handoff export.

    Read-only with respect to its inputs: it never mutates the rule dicts.
    """
    constraints = [_constraint(rule) for rule in verified_rules]
    parameters = _buildable_area_parameters(constraints)
    return {
        "schema_version": GIS_FELT_EXPORT_SCHEMA_VERSION,
        "city": config.get("city"),
        "zone": config.get("zone"),
        "source_document": config.get("source_document"),
        "source_url": config.get("source_url"),
        "input_mode": None,
        "consumer_notes": list(_CONSUMER_NOTES),
        "map_layer_requirements": _map_layer_requirements(constraints, config.get("city")),
        "buildable_area_parameters": parameters,
        "constraints": constraints,
        "review_blockers": _review_blockers(review_rules),
        "not_used_summary": _not_used_summary(not_used_rules),
        "export_counts": {
            "verified_rule_count": len(verified_rules),
            "gis_constraint_count": len(constraints),
            "buildable_area_parameter_count": len(parameters),
            "review_blocker_rule_count": len(review_rules),
            "not_used_rule_count": len(not_used_rules),
        },
    }


def validate_gis_felt_export(export: dict[str, Any]) -> None:
    """Validate the Felt export against its JSON schema before writing.

    Raises (does not warn): a malformed export must never reach GIS, exactly
    like the slim contract validator.
    """
    try:
        import jsonschema
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise SystemExit(
            "jsonschema is required to validate the GIS Felt export. Run `pip install -r requirements.txt`."
        ) from exc
    import json

    schema = json.loads(_GIS_FELT_EXPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(export, schema)
