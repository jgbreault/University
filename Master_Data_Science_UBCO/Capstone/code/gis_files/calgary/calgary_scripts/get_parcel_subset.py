from qgis.core import QgsProject, QgsVectorLayer, QgsFeatureRequest, QgsExpression

# ------- CONFIG -------
PARCELS_NAME = "parcels"          
LAT_A, LAT_B = 51.060, 51.075
LNG_A, LNG_B = -114.126, -114.141
# ----------------------

src = QgsProject.instance().mapLayersByName(PARCELS_NAME)[0]
crs = src.crs().authid()
min_lat, max_lat = min(LAT_A, LAT_B), max(LAT_A, LAT_B)
min_lng, max_lng = min(LNG_A, LNG_B), max(LNG_A, LNG_B)

expr = QgsExpression(
  "y(centroid(transform($geometry, '{c}', 'EPSG:4326'))) BETWEEN {ymin} AND {ymax} "
  "AND x(centroid(transform($geometry, '{c}', 'EPSG:4326'))) BETWEEN {xmin} AND {xmax}".format(
      c=crs, ymin=min_lat, ymax=max_lat, xmin=min_lng, xmax=max_lng))

out = src.materialize(QgsFeatureRequest(expr))
out.setName("parcels_subset")
QgsProject.instance().addMapLayer(out)
print("parcels in range:", out.featureCount(), "of", src.featureCount())
