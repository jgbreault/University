# Burnaby Felt Dashboard

**Live Dashboard:** https://felt.com/map/Burnaby-9A1ZFVWRiSAWSvSlxPZvSwB?loc=49.23802,-122.95828,12.16z

## Files

- `convert_rules_to_felt_burnaby.py` — converts m7 verified rules from `gis_rule_contract.json` to `burnaby_r1_rules.csv`
- `build_felt_parcels_burnaby.py` — joins rules to parcel geometries, detects laned/corner parcels, builds per-parcel tooltip, exports `felt_parcels_burnaby.geojson`
- `burnaby_r1_rules.csv` — verified R1 rules ready for joining

## Layers uploaded to Felt

1. `felt_parcels_burnaby.geojson` — main parcel layer with rules tooltip
2. `buildable_areas.gpkg` — buildable area per lot after setbacks
3. `fitted_footprints.gpkg` — sample fitted laneway home footprint
4. `buildings_labelled.gpkg` — existing buildings
5. `lot_lines_labelled.gpkg` — lot boundary lines
