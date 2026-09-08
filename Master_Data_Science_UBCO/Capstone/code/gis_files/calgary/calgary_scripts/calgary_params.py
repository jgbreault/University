GIS       = ("/Users/jamie/Documents/UBCO_MDS/"
           "w2025-data599-capstone-projects-green-metrics-technology/code/gis_files")
CITY_PATH = GIS + "/calgary"
PARCELS_PATH = CITY_PATH + "/parcels_subset.gpkg"
ZONING_PATH  = CITY_PATH + "/zoning/geo_export_b7b3578e-8b90-4b40-b8e4-54f33c58e646.shp"
STREETS_PATH = CITY_PATH + "/streets.gpkg"
LANES_PATH   = CITY_PATH + "/lanes.gpkg"

TARGET_CRS = "EPSG:3776"

PARCEL_REF_FIELD   = "cpid"
PARCEL_LOTID_FIELD = None
LOT_ID_MIN, LOT_ID_MAX = 8000, 9000

PARCEL_ZONE_FIELD = "land_use_designation"
ZONE_FIELD        = "lu_code"
TARGET_ZONE       = "R-CG"

STREET_MATCH_MODE = "address" 
PARCEL_STREETNAME_FIELD = "ST_NAME"
PARCEL_STREETTYPE_FIELD = "ST_TYPE"
STREET_NAME_FIELD       = "STREETNAME"
STREET_TYPE_FIELD       = "STREETTYPE"
PARCEL_ADDRESS_FIELD    = "address"
STREET_FULLNAME_FIELD   = "full_name"

FRONT_SETBACK         = 3
SIDE_INTERIOR_SETBACK = 1.2   
SIDE_STREET_SETBACK   = 0.6
REAR_INTERIOR_SETBACK = 7.5
REAR_LANE_SETBACK     = 1.2
SHARE_TOL       = 0.001
BUFFER_SEGMENTS = 6

BUILDINGS_NAME = "buildings"
BUILDINGS_PATH = CITY_PATH + "/buildings/geo_export_5ef4a853-a61d-434f-8581-ff0fab00c67a.shp"
MIN_FRONT_REAR = 6.5
MIN_ACCESSORY  = 0
IGNORE_N_SMALLEST_ACCESSORIES = 999