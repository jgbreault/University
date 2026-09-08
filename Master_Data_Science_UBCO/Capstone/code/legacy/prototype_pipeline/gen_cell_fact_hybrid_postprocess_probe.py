import textwrap
from pathlib import Path

import nbformat as nbf


OUT = Path(__file__).with_name("cell_fact_hybrid_postprocess_probe.ipynb")


def md(text: str):
    return nbf.v4.new_markdown_cell(textwrap.dedent(text).strip())


def code(text: str):
    return nbf.v4.new_code_cell(textwrap.dedent(text).strip())


nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "pygments_lexer": "ipython3"},
}

nb.cells = [
    md(
        """
        # Cell-Fact Hybrid Postprocess Probe - Burnaby R1

        Offline-only notebook. This tests the next table route:

        PyMuPDF table structure -> `cell_facts.csv` -> deterministic table rules
        + existing Gemini non-table rules -> one merged registry.

        No Gemini/API calls are made here.
        """
    ),
    code(
        r'''
        import json
        import os
        import re
        from pathlib import Path

        import pandas as pd

        def locate_prototype_dir():
            cwd = Path.cwd()
            for d in [cwd, *cwd.parents]:
                candidate = d / "code" / "prototype_pipeline"
                if (candidate / "prototype_rule_extraction_pipeline.ipynb").exists():
                    return candidate.resolve()
                if (d / "prototype_rule_extraction_pipeline.ipynb").exists():
                    return d.resolve()
            return cwd.resolve()

        PROTOTYPE_DIR = locate_prototype_dir()
        os.chdir(PROTOTYPE_DIR)

        TARGET_CITY = "burnaby"
        RUN_ID = f"prototype_{TARGET_CITY}_rule_pipeline"
        BASE_DIR = PROTOTYPE_DIR / "outputs" / TARGET_CITY / RUN_ID
        CELL_FACT_DIR = BASE_DIR / "08_table_structure_probe"
        NON_TABLE_DIR = BASE_DIR / "06_gemini_non_table_probe"
        OUT_DIR = BASE_DIR / "09_cell_fact_hybrid_postprocess_probe"
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        STRUCTURED_CELL_FACTS_CSV = CELL_FACT_DIR / "structured_cell_facts.csv"
        LEGACY_CELL_FACTS_CSV = CELL_FACT_DIR / "cell_facts.csv"
        CELL_FACTS_CSV = STRUCTURED_CELL_FACTS_CSV if STRUCTURED_CELL_FACTS_CSV.exists() else LEGACY_CELL_FACTS_CSV
        NON_TABLE_RULES_CSV = NON_TABLE_DIR / "gemini_non_table_rules_raw.csv"

        print("PROTOTYPE_DIR:", PROTOTYPE_DIR)
        print("CELL_FACTS_CSV:", CELL_FACTS_CSV, CELL_FACTS_CSV.exists())
        print("NON_TABLE_RULES_CSV:", NON_TABLE_RULES_CSV, NON_TABLE_RULES_CSV.exists())
        print("OUT_DIR:", OUT_DIR)
        '''
    ),
    md("## Load Inputs"),
    code(
        r'''
        cell_facts_df = pd.read_csv(CELL_FACTS_CSV)
        non_table_raw_df = pd.read_csv(NON_TABLE_RULES_CSV)

        print("cell facts:", len(cell_facts_df))
        print("non-table raw rules:", len(non_table_raw_df))
        display(cell_facts_df.head(80))
        '''
    ),
    md("## Shared Helpers"),
    code(
        r'''
        def is_blank(value):
            if value is None:
                return True
            try:
                if pd.isna(value):
                    return True
            except Exception:
                pass
            return str(value).strip() == ""

        def clean(value):
            return "" if is_blank(value) else str(value).strip()

        def norm(value):
            return re.sub(r"\s+", " ", clean(value).lower()).strip()

        def compact_key(value):
            return re.sub(r"[^a-z0-9]+", "_", norm(value)).strip("_")

        def normalize_unit(unit):
            u = norm(unit)
            if u in {"%", "percent", "percentage"}:
                return "percent"
            if u in {"m", "meter", "meters", "metre", "metres"}:
                return "m"
            if u in {"m2", "sq m", "sq. m", "square metre", "square metres", "square meter", "square meters"}:
                return "sq. m"
            if "storey" in u or "story" in u:
                return "storeys"
            if "unit" in u:
                return "units"
            if "person" in u:
                return "persons"
            return u

        def parse_number_unit(text):
            s = clean(text).replace(",", "")
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*(%|m2|sq\.?\s*m|square metres?|square meters?|metres?|meters?|m\b|storeys?|stories?|units?|persons?)?", s, flags=re.I)
            if not m:
                return "", ""
            return m.group(1), normalize_unit(m.group(2) or "")

        def split_range_units(text):
            s = clean(text)
            m = re.search(r"(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)(?:\s*/?\s*(units?))?", s, flags=re.I)
            if not m:
                return []
            return [
                {"value": m.group(1), "unit": "units", "operator": ">="},
                {"value": m.group(2), "unit": "units", "operator": "<="},
            ]

        def parse_range_units(text):
            s = clean(text)
            m = re.search(r"(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)(?:\s*/?\s*(units?))?", s, flags=re.I)
            if not m:
                return None
            return {"min": m.group(1), "max": m.group(2), "unit": "units", "text": f"{m.group(1)} to {m.group(2)} units"}

        def clean_condition_path(text):
            parts = [clean(p) for p in re.split(r"\s*/\s*", clean(text)) if clean(p)]
            out = []
            skip = {"dwelling type", "units", "unit"}
            for part in parts:
                low = part.lower()
                if low in skip:
                    continue
                if re.fullmatch(r"\d+(?:\.\d+)?\s*to\s*\d+(?:\.\d+)?", part, flags=re.I):
                    part = f"{part} Units"
                if out and out[-1].lower() == part.lower():
                    continue
                out.append(part)
            return " / ".join(out)

        def source_condition_for_column(col_idx, column_header=""):
            header = clean(column_header)
            # PyMuPDF table columns are sparse because of merged cells. This map
            # preserves the main page-2 Burnaby table columns better than the
            # flattened-row evidence did.
            if col_idx in {3, 4, 5}:
                base = "Rowhouse / 1 to 3 Units"
            elif col_idx in {6, 7, 8}:
                base = "Small-Scale Multi-Unit / 1 to 2 Units"
            elif col_idx in {9, 10, 11}:
                base = "Small-Scale Multi-Unit / 3 to 4 Units"
            elif col_idx in {12, 13, 14}:
                base = "Small-Scale Multi-Unit / 5 to 6 Units / Frequent Transit Network Area Only"
            else:
                base = ""
            if header and header.lower() not in base.lower():
                return clean_condition_path(f"{base} / {header}" if base else header)
            return clean_condition_path(base)

        def visible(value, evidence_text):
            val = clean(value)
            if not val:
                return True
            text = norm(evidence_text)
            variants = {norm(val), norm(str(val).rstrip(".0"))}
            try:
                num = float(val)
                variants.add(norm(str(int(num))) if num.is_integer() else norm(str(num)))
            except Exception:
                pass
            return any(v and v in text for v in variants)
        '''
    ),
    md("## Convert Table Cell Facts to Rules"),
    code(
        r'''
        def table_key(group, row_label, value, unit, condition, cell_text):
            g = norm(group)
            r = norm(row_label)
            c = norm(condition)
            if "permitted dwelling units" in r:
                return "permitted_dwelling_units"
            if "minimum lot area" in r:
                return "min_lot_area"
            if "maximum lot area" in r:
                return "max_lot_area"
            if "lot coverage" in g and "impervious" in r:
                return "max_impervious_surface"
            if "lot coverage" in g:
                return "max_lot_coverage_all_buildings"
            if g == "height":
                if "accessory" in r:
                    subject = "accessory_building"
                elif "rear principal" in r:
                    subject = "rear_principal_building"
                else:
                    subject = "front_principal_building"
                if normalize_unit(unit) == "storeys":
                    return f"max_{subject}_storeys"
                if "flat roof" in c:
                    return f"max_{subject}_height_flat_roof"
                if "sloping roof" in c or "sloped roof" in c:
                    return f"max_{subject}_height_sloped_roof"
                return f"max_{subject}_height"
            if "setback" in g or "yard" in r:
                if "street yard" in r:
                    return "min_street_yard_setback"
                if "lane yard" in r:
                    return "min_lane_yard_setback"
                if "interior rear" in r:
                    return "min_interior_rear_yard_setback"
                if "interior side" in r:
                    return "min_interior_side_yard_setback"
            if "separation" in g or "between" in r:
                if "front & rear" in r or "front and rear" in r:
                    return "min_separation_between_front_and_rear_principals"
                if "rear principals" in r:
                    return "min_separation_between_rear_principals"
                if "front principals" in r:
                    return "min_separation_between_front_principals"
                if "all other buildings" in r:
                    return "min_separation_between_all_other_buildings"
            return compact_key(f"{group}_{row_label}") or "unknown_table_rule"

        def table_operator(group, key):
            g = norm(group)
            if "maximum" in g or key.startswith("max_"):
                return "<="
            if "minimum" in g or key.startswith("min_"):
                return ">="
            if key == "permitted_dwelling_units":
                return "="
            return "="

        def add_table_rule(fact, value, unit, operator, condition="", exception="", value_source="cell_fact"):
            group = clean(fact.get("group_title"))
            row_label = clean(fact.get("row_label_path") or fact.get("row_label"))
            cell_text = clean(fact.get("cell_text"))
            value_text = clean(fact.get("value_text") or cell_text)
            col_cond = clean_condition_path(clean(fact.get("column_header_path"))) or source_condition_for_column(int(fact.get("column_index", -1)), fact.get("column_header", ""))
            local_condition = clean_condition_path(clean(fact.get("local_condition")))
            parts = [p for p in [col_cond, local_condition, clean(condition)] if p]
            full_condition = clean_condition_path(" / ".join(dict.fromkeys(parts)))
            key = table_key(group, row_label, value, unit, full_condition, value_text)
            op = operator or table_operator(group, key)
            return {
                "rule_id": f"cellfact_{clean(fact.get('fact_id'))}_{compact_key(str(value)+'_'+unit+'_'+full_condition)}",
                "evidence_id": clean(fact.get("fact_id")),
                "source_stream": "table_cell_fact",
                "group_title": group,
                "row_label": row_label,
                "column_index": int(fact.get("column_index", -1)),
                "column_header": clean(fact.get("column_header_path") or fact.get("column_header")),
                "source_column_condition": col_cond,
                "normalized_rule_key": key,
                "operator": op,
                "value": clean(value),
                "unit": normalize_unit(unit),
                "condition": full_condition,
                "exception": clean(exception),
                "evidence_text": clean(fact.get("row_text")),
                "cell_text": cell_text,
                "value_text": value_text,
                "mapping_confidence": fact.get("mapping_confidence", ""),
                "mapping_warnings": clean(fact.get("mapping_warnings")),
                "value_source": value_source,
                "value_visible": visible(value, fact.get("row_text", "")),
            }

        def rules_from_cell_fact(fact):
            text = clean(fact.get("value_text") or fact.get("cell_text"))
            row = norm(fact.get("row_label_path") or fact.get("row_label"))
            group = norm(fact.get("group_title"))
            out = []

            warnings = norm(fact.get("mapping_warnings"))
            if "missing_row_label" in warnings:
                return out

            if not text or text in {"-", ":"}:
                return out
            if not re.search(r"\d|%|m\b|m2|storey|unit", text, flags=re.I):
                return out
            # Skip pure label cells such as "4 Units Only"; let the numeric cell
            # carry this as condition when possible.
            if re.fullmatch(r"\d+\s*units?\s*only:?", text, flags=re.I):
                return out

            if "permitted dwelling units" in row:
                range_info = parse_range_units(text)
                for item in split_range_units(text):
                    rule = add_table_rule(fact, item["value"], item["unit"], item["operator"], value_source="range_endpoint")
                    if range_info:
                        rule["range_min"] = range_info["min"]
                        rule["range_max"] = range_info["max"]
                        rule["range_unit"] = range_info["unit"]
                        rule["range_text"] = range_info["text"]
                        rule["range_pair_id"] = f"{rule['normalized_rule_key']}|{rule['condition']}|{range_info['min']}|{range_info['max']}|{range_info['unit']}"
                    out.append(rule)
                return out

            # Generic legal-table exception pattern:
            # "3.0 m, except 1.5 m for accessory buildings"
            # "0 m, except 1.2 m / for end unit lots"
            exc = re.search(
                r"(?P<base>\d+(?:\.\d+)?)\s*(?P<unit>m|m2|sq\.?\s*m|%|storeys?)\s*,?\s*except\s*"
                r"(?P<exc>\d+(?:\.\d+)?)\s*(?P<exc_unit>m|m2|sq\.?\s*m|%|storeys?)?\s*(?:/)?\s*(?:for\s*)?(?P<scope>.*)",
                text,
                flags=re.I,
            )
            if exc:
                scope = clean(exc.group("scope"))
                unit = exc.group("unit")
                exc_unit = exc.group("exc_unit") or unit
                out.append(add_table_rule(fact, exc.group("base"), unit, table_operator(group, table_key(group, row, exc.group("base"), unit, "", text)), exception=f"{exc.group('exc')} {normalize_unit(exc_unit)} for {scope}".strip()))
                out.append(add_table_rule(fact, exc.group("exc"), exc_unit, table_operator(group, table_key(group, row, exc.group("exc"), exc_unit, scope, text)), condition=scope, value_source="derived_from_exception"))
                return out

            # Conditional percentage cells, e.g. "Lots < 567 m2: 40%".
            pct_condition = re.search(r"(.+?):\s*(\d+(?:\.\d+)?)\s*%", text, flags=re.I)
            if pct_condition:
                out.append(add_table_rule(fact, pct_condition.group(2), "percent", "<=", condition=pct_condition.group(1)))
                return out

            # Height rows with two roof values in one cell.
            for roof_label, value in re.findall(r"(sloping roof|flat roof)\s*:\s*(\d+(?:\.\d+)?)\s*m", text, flags=re.I):
                out.append(add_table_rule(fact, value, "m", "<=", condition=roof_label.lower()))
            if out:
                return out

            # Accessory building combines metre height and storeys in one cell.
            if "accessory" in row:
                for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(m|storeys?|stories?)", text, flags=re.I):
                    out.append(add_table_rule(fact, value, unit, "<="))
                return out

            # Street yard: one column may include front/flanking sub-values.
            for label, value in re.findall(r"(front|flanking)\s*:\s*(\d+(?:\.\d+)?)\s*m", text, flags=re.I):
                out.append(add_table_rule(fact, value, "m", ">=", condition=label.lower()))
            bare = re.sub(r"(front|flanking)\s*:\s*\d+(?:\.\d+)?\s*m", "", text, flags=re.I)
            if not out or re.search(r"\d", bare):
                value, unit = parse_number_unit(bare)
                if value:
                    out.insert(0, add_table_rule(fact, value, unit or "m", table_operator(group, table_key(group, row, value, unit, "", text))))
            return out

            return out

        table_rules = []
        for _, fact_row in cell_facts_df.iterrows():
            table_rules.extend(rules_from_cell_fact(fact_row.to_dict()))

        table_rules_df = pd.DataFrame(table_rules)
        print("table rules from cell facts:", len(table_rules_df))
        display(table_rules_df[["normalized_rule_key", "operator", "value", "unit", "condition", "exception", "cell_text", "source_column_condition"]].head(120))
        '''
    ),
    md("## Normalize Existing Non-Table Rules"),
    code(
        r'''
        def normalize_non_table_key(rule):
            text = norm(" ".join(clean(rule.get(k)) for k in ["rule_key", "rule_object", "subject", "condition", "value"]))
            raw_key = norm(rule.get("rule_key"))
            exact = {
                "boarding_lodging_rooming_house_occupancy": "boarding_lodging_rooming_house_occupancy",
                "boarding_lodging_rooming_house_lot_area": "boarding_lodging_rooming_house_lot_area",
                "category_a_supportive_housing_principal_use": "category_a_supportive_housing_principal_use",
                "living_unit_minimum_floor_area": "min_floor_area",
                "garage_carport_below_grade_height_limit": "garage_carport_below_grade_height_limit",
                "garage_carport_below_grade_setback": "garage_carport_below_grade_setback",
                "automatic_sprinkler_system_requirement": "required_automatic_sprinkler_system",
                "fire_access_corridor_minimum_width": "min_fire_access_corridor_width",
                "fire_access_corridor_purpose": "fire_access_corridor_purpose",
                "fire_access_corridor_clearance_height": "min_clear_height",
                "panhandle_width_lane_access": "min_panhandle_width",
                "panhandle_width_no_lane_access": "min_panhandle_width",
                "panhandle_clearance_height_lane_access": "min_clear_height",
                "panhandle_clearance_height_no_lane_access": "min_clear_height",
                "lot_coverage_increase_permitted": "max_lot_coverage_exception",
                "impervious_surface_area_increase_permitted": "max_impervious_surface_exception",
                "principal_building_height_exclusion": "principal_building_height_exclusion",
                "street_yard_setback_minimum": "min_street_yard_setback_exception",
                "separation_between_buildings_reduction_permitted": "separation_between_buildings_reduction_permitted",
                "off_street_vehicular_parking_requirement": "not_required_off_street_parking",
                "parking_location_standard": "parking_location_permission",
                "parking_location_exception": "parking_location_permission",
                "parking_in_yards_permitted": "parking_location_permission",
                "existing_non_conforming_parking_use": "parking_location_permission",
                "principal_building_separation": "principal_building_separation",
                "principal_building_separation_through_lots": "min_separation_between_front_and_rear_principals",
                "principal_building_separation_side_lot_line": "min_separation_between_other_principals",
            }
            if raw_key in exact:
                return exact[raw_key]
            if "off_street_vehicular_parking_requirement" in text or ("off street vehicular parking" in text and "not_permitted" in text):
                return "not_required_off_street_parking"
            if "not required" in text and "parking" in text:
                return "not_required_off_street_parking"
            if "sprinkler" in text:
                return "required_automatic_sprinkler_system"
            if "walkway_clear_height" in text or "clear_height" in text:
                return "min_clear_height"
            if "walkway" in text and ("wide" in text or "width" in text):
                return "min_pedestrian_walkway_width"
            if "walkway" in text and ("spaced" in text or "spacing" in text):
                return "max_pedestrian_walkway_spacing"
            if "panhandle_width" in text or ("panhandle" in text and "width" in text):
                return "min_panhandle_width"
            if "panhandle_clearance_height" in text or ("panhandle" in text and "height" in text):
                return "min_clear_height"
            if "fire access corridor" in text and ("width" in text or "1.0" in text):
                return "min_fire_access_corridor_width"
            if "fire access corridor" in text:
                return "fire_access_corridor_purpose"
            if "main entrance" in text:
                return "required_main_entrance_orientation"
            if "floor area" in text:
                return "min_floor_area"
            if "impervious" in text:
                return "max_impervious_surface_exception"
            if "lot coverage" in text:
                return "max_lot_coverage_exception"
            if "street yard" in text and ("setback" in text or "2.0" in text):
                return "min_street_yard_setback_exception"
            if "parking" in text:
                return "parking_location_permission"
            if "boarding" in text and "persons" in text:
                return "boarding_lodging_rooming_house_occupancy"
            if "boarding" in text and "lot" in text:
                return "boarding_lodging_rooming_house_lot_area"
            if "supportive housing" in text and "principal use" in text:
                return "category_a_supportive_housing_principal_use"
            if "garage" in text and "above" in text:
                return "garage_carport_below_grade_height_limit"
            if "garage" in text and "lot line" in text:
                return "garage_carport_below_grade_setback"
            if "height exclusion" in text or "excluded from the maximum permitted height" in text:
                return "principal_building_height_exclusion"
            if "separation" in text and "reduced" in text:
                return "separation_between_buildings_reduction_permitted"
            if "any other principals" in text or "side lot line" in text:
                return "min_separation_between_other_principals"
            if "through lots" in text or "opposing front principals" in text:
                return "min_separation_between_front_and_rear_principals"
            return compact_key(rule.get("rule_key")) or "unknown_non_table_rule"

        # Load evidence text from raw non-table file only; it does not currently
        # include full evidence text, so keep fields as-is for this probe.
        def normalize_non_table_rule(row):
            rule = row.to_dict()
            hay = norm(" ".join(clean(rule.get(k)) for k in ["rule_key", "rule_object", "subject", "condition", "value"]))
            if "not required" in hay or "off_street_vehicular_parking_requirement" in hay or ("parking" in hay and "not_permitted" in hay):
                rule["value"] = "not required"
                rule["operator"] = "="
                rule["unit"] = ""
            if "automatic_sprinkler_system_requirement" in hay and is_blank(rule.get("value")):
                m = re.search(r">\s*(\d+(?:\.\d+)?)\s*m", hay)
                if m:
                    rule["value"] = m.group(1)
                    rule["unit"] = "m"
                    rule["operator"] = ">"
            value = clean(rule.get("value"))
            if re.fullmatch(r"\d+(?:\.\d+)?", value):
                value = value.rstrip("0").rstrip(".") if "." in value else value
            unit = normalize_unit(rule.get("unit"))
            key = normalize_non_table_key(rule)
            op = clean(rule.get("operator"))
            if key.startswith("required_") and not op:
                op = "required"
            elif key.endswith("_permission") and not op:
                op = "permitted"
            elif key.startswith("min_") and not op:
                op = ">="
            elif key.startswith("max_") and not op:
                op = "<="
            return {
                "rule_id": f"non_table_{clean(rule.get('evidence_id'))}_{compact_key(key+'_'+value)}",
                "evidence_id": clean(rule.get("evidence_id")),
                "source_stream": "non_table",
                "group_title": "",
                "row_label": clean(rule.get("rule_object")),
                "column_index": "",
                "column_header": "",
                "source_column_condition": "",
                "normalized_rule_key": key,
                "operator": op,
                "value": value,
                "unit": unit,
                "condition": clean(rule.get("condition")),
                "exception": clean(rule.get("exception")),
                "evidence_text": "",
                "cell_text": "",
                "value_source": "gemini_non_table",
                "value_visible": True,
            }

        non_table_rules_df = pd.DataFrame([normalize_non_table_rule(row) for _, row in non_table_raw_df.iterrows()])
        print("non-table rules:", len(non_table_rules_df))
        display(non_table_rules_df[["normalized_rule_key", "operator", "value", "unit", "condition"]].head(80))
        '''
    ),
    md("## Combine, Deduplicate, and Route"),
    code(
        r'''
        combined_df = pd.concat([table_rules_df, non_table_rules_df], ignore_index=True, sort=False)

        def specificity_score(row):
            score = 0
            for col in ["condition", "source_column_condition", "column_header", "exception"]:
                if clean(row.get(col)):
                    score += 1
            if row.get("value_visible", True):
                score += 1
            return score

        combined_df["dedup_key"] = combined_df.apply(
            lambda r: "|".join(norm(r.get(c)) for c in ["source_stream", "normalized_rule_key", "operator", "value", "unit", "condition", "exception", "source_column_condition"]),
            axis=1,
        )
        combined_df["specificity_score"] = combined_df.apply(specificity_score, axis=1)
        deduped_df = (
            combined_df.sort_values(["dedup_key", "specificity_score"], ascending=[True, False])
            .drop_duplicates("dedup_key", keep="first")
            .reset_index(drop=True)
        )

        def final_action(row):
            text = norm(" ".join(clean(row.get(c)) for c in ["condition", "exception", "cell_text", "row_label"]))
            if any(w in text for w in ["except", "may", "subject to", "provided that", "director"]):
                return "REVIEW"
            if not row.get("value_visible", True):
                return "REVIEW"
            return "ACCEPT"

        deduped_df["final_action"] = deduped_df.apply(final_action, axis=1)
        accepted_df = deduped_df[deduped_df["final_action"] == "ACCEPT"].copy()
        review_df = deduped_df[deduped_df["final_action"] == "REVIEW"].copy()

        def collapse_equivalent_rules(df):
            """Collapse same rule/value/operator rows that only differ by condition.

            This keeps every atomic row in `deduped_df`, but also creates a compact
            registry view for values repeated across multiple table columns.
            """
            group_cols = ["source_stream", "normalized_rule_key", "operator", "value", "unit", "exception", "final_action"]
            if "range_pair_id" in df.columns:
                group_cols.append("range_pair_id")
            records = []
            for _, group_df in df.groupby(group_cols, dropna=False, sort=False):
                first = group_df.iloc[0].to_dict()
                conditions = []
                source_conditions = []
                evidence_ids = []
                for _, r in group_df.iterrows():
                    cond = clean(r.get("condition"))
                    src_cond = clean(r.get("source_column_condition"))
                    eid = clean(r.get("evidence_id"))
                    if cond and cond not in conditions:
                        conditions.append(cond)
                    if src_cond and src_cond not in source_conditions:
                        source_conditions.append(src_cond)
                    if eid and eid not in evidence_ids:
                        evidence_ids.append(eid)
                first["condition_count"] = len(conditions)
                first["conditions_json"] = json.dumps(conditions, ensure_ascii=False)
                first["source_column_conditions_json"] = json.dumps(source_conditions, ensure_ascii=False)
                first["evidence_ids_json"] = json.dumps(evidence_ids, ensure_ascii=False)
                first["collapsed_from_count"] = len(group_df)
                records.append(first)
            return pd.DataFrame(records)

        collapsed_df = collapse_equivalent_rules(deduped_df)

        def build_range_paired_registry(df):
            records = []
            used = set()
            if "range_pair_id" in df.columns:
                range_df = df[df["range_pair_id"].apply(lambda x: bool(clean(x)))]
                for pair_id, pair_df in range_df.groupby("range_pair_id", dropna=True):
                    if len(pair_df) < 2:
                        continue
                    first = pair_df.iloc[0].to_dict()
                    min_v = clean(first.get("range_min"))
                    max_v = clean(first.get("range_max"))
                    unit = clean(first.get("range_unit")) or "units"
                    first["operator"] = "range"
                    first["value"] = f"{min_v}-{max_v}"
                    first["unit"] = unit
                    first["range_min"] = min_v
                    first["range_max"] = max_v
                    first["range_unit"] = unit
                    first["range_text"] = clean(first.get("range_text")) or f"{min_v} to {max_v} {unit}"
                    first["paired_from_operators"] = ",".join(sorted(set(clean(x) for x in pair_df["operator"] if clean(x))))
                    first["paired_from_count"] = len(pair_df)
                    records.append(first)
                    used.update(pair_df.index.tolist())
            remainder = df.drop(index=list(used)) if used else df
            records.extend(remainder.to_dict("records"))
            return pd.DataFrame(records).reset_index(drop=True)

        final_registry_df = build_range_paired_registry(collapsed_df)

        print("combined:", len(combined_df))
        print("deduped:", len(deduped_df))
        print("collapsed:", len(collapsed_df))
        print("final registry:", len(final_registry_df))
        print("accepted:", len(accepted_df))
        print("review:", len(review_df))
        print("\\nby stream/action")
        print(deduped_df.groupby(["source_stream", "final_action"]).size())
        display(deduped_df[["source_stream", "normalized_rule_key", "operator", "value", "unit", "condition", "source_column_condition", "final_action", "cell_text"]].head(140))
        display(collapsed_df[["source_stream", "normalized_rule_key", "operator", "value", "unit", "condition_count", "conditions_json", "final_action", "collapsed_from_count"]].head(140))
        display(final_registry_df[["source_stream", "normalized_rule_key", "operator", "value", "unit", "condition", "range_min", "range_max", "final_action"]].head(140))
        '''
    ),
    md("## Expected Coverage"),
    code(
        r'''
        expected_keys = [
            "permitted_dwelling_units", "min_lot_area", "max_lot_area",
            "max_lot_coverage_all_buildings", "max_impervious_surface",
            "max_front_principal_building_height_sloped_roof", "max_front_principal_building_height_flat_roof", "max_front_principal_building_storeys",
            "max_rear_principal_building_height_sloped_roof", "max_rear_principal_building_height_flat_roof", "max_rear_principal_building_storeys",
            "max_accessory_building_height", "max_accessory_building_storeys",
            "min_street_yard_setback", "min_lane_yard_setback", "min_interior_rear_yard_setback", "min_interior_side_yard_setback",
            "min_separation_between_front_principals", "min_separation_between_rear_principals", "min_separation_between_front_and_rear_principals", "min_separation_between_all_other_buildings",
            "required_main_entrance_orientation", "max_pedestrian_walkway_spacing", "min_pedestrian_walkway_width", "min_clear_height",
            "min_floor_area", "required_automatic_sprinkler_system", "min_fire_access_corridor_width", "min_panhandle_width",
            "max_lot_coverage_exception", "max_impervious_surface_exception", "min_street_yard_setback_exception", "not_required_off_street_parking",
        ]
        found = set(deduped_df["normalized_rule_key"])
        coverage_df = pd.DataFrame([{"expected_key": key, "found": key in found} for key in expected_keys])
        print("Expected keys found:", int(coverage_df["found"].sum()), "/", len(coverage_df))
        display(coverage_df)
        print("\\nCounts by key:")
        print(deduped_df["normalized_rule_key"].value_counts().sort_index().to_string())
        '''
    ),
    md("## Save Outputs"),
    code(
        r'''
        table_rules_df.to_csv(OUT_DIR / "cell_fact_table_rules.csv", index=False, encoding="utf-8-sig")
        combined_df.to_csv(OUT_DIR / "cell_fact_hybrid_rules_postprocessed.csv", index=False, encoding="utf-8-sig")
        deduped_df.to_csv(OUT_DIR / "cell_fact_hybrid_rules_postprocessed_deduped.csv", index=False, encoding="utf-8-sig")
        deduped_df.to_json(OUT_DIR / "cell_fact_hybrid_rules_postprocessed_deduped.json", orient="records", force_ascii=False, indent=2)
        collapsed_df.to_csv(OUT_DIR / "cell_fact_hybrid_rules_collapsed.csv", index=False, encoding="utf-8-sig")
        collapsed_df.to_json(OUT_DIR / "cell_fact_hybrid_rules_collapsed.json", orient="records", force_ascii=False, indent=2)
        final_registry_df.to_csv(OUT_DIR / "cell_fact_hybrid_final_registry.csv", index=False, encoding="utf-8-sig")
        final_registry_df.to_json(OUT_DIR / "cell_fact_hybrid_final_registry.json", orient="records", force_ascii=False, indent=2)
        accepted_df.to_csv(OUT_DIR / "cell_fact_hybrid_accepted_rules.csv", index=False, encoding="utf-8-sig")
        review_df.to_csv(OUT_DIR / "cell_fact_hybrid_review_rules.csv", index=False, encoding="utf-8-sig")
        coverage_df.to_csv(OUT_DIR / "cell_fact_hybrid_expected_key_coverage.csv", index=False, encoding="utf-8-sig")

        summary = [
            "# Cell-Fact Hybrid Postprocess Summary",
            "",
            f"cell_facts: {len(cell_facts_df)}",
            f"table_rules_from_cell_facts: {len(table_rules_df)}",
            f"non_table_raw_rules: {len(non_table_raw_df)}",
            f"combined_rules: {len(combined_df)}",
            f"deduped_rules: {len(deduped_df)}",
            f"collapsed_rules: {len(collapsed_df)}",
            f"final_registry_rules: {len(final_registry_df)}",
            f"accepted_rules: {len(accepted_df)}",
            f"review_rules: {len(review_df)}",
            f"expected_keys_found: {int(coverage_df['found'].sum())}/{len(coverage_df)}",
            "",
            "## Counts By Stream/Action",
            deduped_df.groupby(["source_stream", "final_action"]).size().to_string(),
            "",
            "## Counts By Key",
            deduped_df["normalized_rule_key"].value_counts().sort_index().to_string(),
        ]
        (OUT_DIR / "cell_fact_hybrid_postprocess_summary.md").write_text("\\n".join(summary), encoding="utf-8")
        print((OUT_DIR / "cell_fact_hybrid_postprocess_summary.md").read_text(encoding="utf-8"))
        print("Saved:", OUT_DIR)
        '''
    ),
]

nbf.write(nb, OUT)
print(f"Wrote {OUT}")
