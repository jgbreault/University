from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject

LENGTH_FT = 25
WIDTH_FT  = 20

CRS = "EPSG:26910"  
FT = 0.3048         # foot to metre
x0, y0 = 40, 5      # bottom-left corner (in CRS units / metres)

L, W = LENGTH_FT * FT, WIDTH_FT * FT
rect = QgsVectorLayer("Polygon?crs=" + CRS, "footprint", "memory")
f = QgsFeature()
f.setGeometry(QgsGeometry.fromWkt(
  "POLYGON((%f %f,%f %f,%f %f,%f %f,%f %f))"
  % (x0, y0, x0 + L, y0, x0 + L, y0 + W, x0, y0 + W, x0, y0)))
rect.dataProvider().addFeature(f)
QgsProject.instance().addMapLayer(rect)
QgsProject.instance().setCrs(rect.crs())