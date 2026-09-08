"""Structured geometry operators for verified zoning rules.

A pure post-verification projection that turns a verified rule into an
*executable* geometry spec a GIS engine can act on, e.g. a front setback becomes
``{"operation": "offset_inward", "axis": "front_lot_line", "direction": "inward"}``
and a height limit becomes ``{"operation": "extrude_z", "axis": "vertical",
"direction": "up"}``. The numeric magnitude/unit/operator stay on the constraint
itself (``value_numeric``/``unit``/``operator``); this block says *what kind of
geometric operation* the rule constrains.

This carries no verification weight and is never read by the verifier, the
benchmark, the holdout eval, or the adversarial suite. It only enriches the GIS
handoff. The rule is **never guess**: an unmapped family, or a setback whose
scope has no known lot-line axis, yields ``None``.
"""

from __future__ import annotations

from typing import Any


# rule_object -> the geometric operation a GIS engine performs for this family.
OPERATION_BY_RULE_OBJECT = {
    "setback": "offset_inward",          # offset the named lot line inward by `value`
    "building_separation": "min_separation",  # minimum distance between buildings
    "height": "extrude_z",               # vertical envelope cap
    "storeys": "storey_count_cap",       # max number of storeys
    "lot_coverage": "footprint_ratio_cap",    # max building footprint / lot area
    "impervious_surface": "surface_ratio_cap",  # max impervious area / lot area
    "lot_area": "area_floor",            # minimum parcel area
    "floor_area": "floor_area_cap",      # max gross floor area on the lot (laneway homes etc.)
    "floor_space_ratio": "density_ratio_cap",  # max floor area / site area (FSR/FAR)
    "dwelling_units": "unit_count_cap",  # max dwelling units on the lot
    "automatic_sprinkler": "trigger_predicate",  # conditional requirement, not a shape
    "fire_access_corridor": "clearance",       # required corridor width / vertical clearance
    "permitted_use": "use_permission",   # allowed-use flag for the zoning polygon
}

# setback constraint_scope -> which lot line the offset applies to.
AXIS_BY_SCOPE = {
    "street_yard_front": "front_lot_line",
    "street_yard_flanking": "side_lot_line",
    "lane_yard": "lane_lot_line",
    "interior_rear_yard": "rear_lot_line",
    "interior_side_yard": "side_lot_line",
}

# Closed vocabularies (mirrored by the JSON schema enums).
OPERATIONS = sorted(set(OPERATION_BY_RULE_OBJECT.values()))
AXES = sorted(set(AXIS_BY_SCOPE.values()) | {"vertical"})
DIRECTIONS = ["inward", "up"]


def derive_geometry_operator(rule: dict[str, Any]) -> dict[str, Any] | None:
    """Return a structured geometry operator for a verified rule, or None.

    Shape: ``{"operation": str, "axis": str|None, "direction": str|None,
    "source_fields": list[str]}``. Returns ``None`` only when the operation is
    genuinely underivable (unknown family, or a setback with an unmapped scope),
    never a guess.
    """
    rule_object = str(rule.get("rule_object") or "")
    operation = OPERATION_BY_RULE_OBJECT.get(rule_object)
    if operation is None:
        return None

    axis: str | None = None
    direction: str | None = None
    source_fields = ["rule_object"]

    if rule_object == "setback":
        scope = str(rule.get("constraint_scope") or "")
        axis = AXIS_BY_SCOPE.get(scope)
        if axis is None:
            # A setback whose scope we cannot anchor to a lot line is not
            # safely drawable — never guess the edge.
            return None
        direction = "inward"
        source_fields.append("constraint_scope")
    elif rule_object == "height":
        axis = "vertical"
        direction = "up"

    return {
        "operation": operation,
        "axis": axis,
        "direction": direction,
        "source_fields": source_fields,
    }
