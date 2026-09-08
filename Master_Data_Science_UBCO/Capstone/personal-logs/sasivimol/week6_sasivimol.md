# Week 6

## Summary

Continued GIS visualization work by building a pipeline to integrate rule extraction outputs with parcel GIS data for display in Felt. Automated the spatial join between parcel, zoning, and rule files to produce a single upload-ready GeoJSON. Completed the full layer stack in Felt with hover tooltip showing zoning rules per parcel, and identified the remaining gap of expanding rule coverage beyond R1 zone.

---

## Tasks

- Investigated which GIS files and rule extraction outputs are needed for the Felt dashboard and mapped the full data flow

- Built `build_felt_parcels.py` script that:
  - Spatially joins `Legal_Parcels.shp` with `Zoning.shp` to add `zone_code` to each of 36,913 parcels
  - Joins extracted rules by `zone_code` and embeds them as columns on each parcel feature
  - Exports a single Felt-ready GeoJSON (`felt_parcels.geojson`) in WGS84

- Uploaded and configured all layers in Felt: Felt Parcels, Lot Lines Labelled, Building Outlines, Fitted Setback Areas 10×15, Fitted Buildings 10×15, Empty Buildable Areas, Lane, Street

- Confirmed hover tooltip is working — clicking a parcel shows `zone_code`, `rule_setback`, `rule_height`, `rule_building_separation`, `rule_dwelling_units`, and `rule_storeys`

- Traced the rule source chain: `gis_rule_contract.json` (Pipeline 5 slim registry) → `convert_rules_to_felt.py` → `burnaby_r1_rules.csv` → `build_felt_parcels.py` → `felt_parcels.geojson`

---

## Time

| Activity | Hours |
|---|---|
| Syncing with main and reviewing new outputs | 3 |
| Investigating GIS and rule file structure | 5 |
| Building spatial join and export script | 6 |
| Uploading and configuring layers in Felt | 10 |
| Testing hover tooltip and debugging | 6 |
| Meeting with team and partner | 2 |
| **Total** | **32** |

---

## Challenges

- Rule extraction outputs cannot be uploaded to Felt directly — they must first be joined to parcel geometries so each feature carries its own rules as attributes
- The parcel shapefile has no zone information, requiring a spatial join with the zoning shapefile

---

## Next Steps

- Integrate the new upgraded verified rules for Burnaby to replace the current R1-only rule set

- Extend the dashboard to support Calgary by processing Calgary GIS and rule extraction files through the same pipeline

---
