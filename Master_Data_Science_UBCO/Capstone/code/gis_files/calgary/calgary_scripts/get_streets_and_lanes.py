from qgis.core import QgsProject, QgsFeatureRequest, QgsExpression

SRC_NAME    = "streets_and_lanes"
CLASS_FIELD = "ctp_class"
LANE_VALUE  = "Lanes (Alleys)"

src = QgsProject.instance().mapLayersByName(SRC_NAME)[0]

# lanes: ctp_class == "Lanes (Alleys)"
lane_expr = QgsExpression('"%s" = \'%s\'' % (CLASS_FIELD, LANE_VALUE))
lanes = src.materialize(QgsFeatureRequest(lane_expr))
lanes.setName("lanes") 

# streets: everything else (including NULLs, so nothing is dropped)
street_expr = QgsExpression('"%s" IS NULL OR "%s" <> \'%s\''
                          % (CLASS_FIELD, CLASS_FIELD, LANE_VALUE))
streets = src.materialize(QgsFeatureRequest(street_expr))
streets.setName("streets")

QgsProject.instance().addMapLayer(lanes)
QgsProject.instance().addMapLayer(streets)
print("source:", src.featureCount(), "| lanes:", lanes.featureCount(), "| streets:", streets.featureCount())