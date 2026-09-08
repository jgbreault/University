GIS       = ("/Users/jamie/Documents/UBCO_MDS/w2025-data599-capstone-projects-green-metrics-technology/code/gis_files")
CITY_PATH = GIS + "/burnaby"  
PARCELS_PATH = CITY_PATH + "/parcels/Legal_Parcels.shp"
ZONING_PATH  = CITY_PATH + "/zoning/Zoning.shp"
STREETS_PATH = CITY_PATH + "/streets/Street.shp"
LANES_PATH   = CITY_PATH + "/lane/Lane.shp"

TARGET_CRS = "EPSG:26910"

PARCEL_REF_FIELD   = "LTO_PID"
PARCEL_LOTID_FIELD = "LOT_ID"
LOT_ID_MIN, LOT_ID_MAX = 8000, 9000

PARCEL_ZONE_FIELD = None            # Burnaby: zone comes from the zoning layer, not the parcel
ZONE_FIELD        = "ZONECODE"
TARGET_ZONE       = "R1"

STREET_MATCH_MODE = "name_type"     # Burnaby parcels have street name + type
PARCEL_STREETNAME_FIELD = "ST_NAME"
PARCEL_STREETTYPE_FIELD = "ST_TYPE"
STREET_NAME_FIELD       = "STREETNAME"
STREET_TYPE_FIELD       = "STREETTYPE"
PARCEL_ADDRESS_FIELD    = "address"   # unused in name_type mode, kept for parity
STREET_FULLNAME_FIELD   = "full_name" # unused in name_type mode, kept for parity

FRONT_SETBACK         = 4.0   
SIDE_INTERIOR_SETBACK = 1.2
SIDE_STREET_SETBACK   = 3.0
REAR_INTERIOR_SETBACK = 3.0
REAR_LANE_SETBACK     = 1.5   
SHARE_TOL       = 0.001
BUFFER_SEGMENTS = 6

BUILDINGS_NAME = "Building_Outlines"
BUILDINGS_PATH = CITY_PATH + "/building_outlines/Building_Outlines.shp"
MIN_FRONT_REAR = 6.0
MIN_ACCESSORY  = 2.4
IGNORE_N_SMALLEST_ACCESSORIES = 999