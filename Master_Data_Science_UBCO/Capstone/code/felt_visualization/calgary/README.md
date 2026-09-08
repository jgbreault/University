# Calgary Felt Dashboard

**Live Dashboard:** https://felt.com/map/Calgary-rMIhLTEVSkiaOV2rH36IpB?loc=51.07295,-114.133876,18.12z

## Files

- `convert_rules_to_felt_calgary.py` — converts m7 verified rules from `gis_rule_contract.json` to `calgary_rcg_rules.csv`
- `build_felt_parcels_calgary.py` — joins rules to parcel geometries, detects laned/corner parcels, builds per-parcel tooltip, exports `felt_parcels_calgary.geojson`
- `calgary_rcg_rules.csv` — verified RCG rules ready for joining

## Layers uploaded to Felt

1. `felt_parcels_calgary.geojson` — main parcel layer with rules tooltip
2. `buildable_areas.gpkg` — buildable area per lot after setbacks
3. `fitted_footprints.gpkg` — sample fitted laneway home footprint
4. `buildings_labelled.gpkg` — existing buildings
5. `lot_lines_labelled.gpkg` — lot boundary lines
