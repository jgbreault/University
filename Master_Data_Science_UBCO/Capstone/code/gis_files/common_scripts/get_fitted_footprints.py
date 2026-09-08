import math
from collections import defaultdict
from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature, QgsField, QgsFields,
                     QgsGeometry, QgsPointXY, QgsCoordinateTransform)
from qgis.PyQt.QtCore import QVariant

# ------------------------------ CONFIG ------------------------------
BASE = ("/Users/jamie/Documents/UBCO_MDS/w2025-data599-capstone-projects-green-metrics-technology/code/gis_files")

BUILDABLE_NAME = "buildable_areas"              # parcels to test (in project)
LINES_NAME     = "lot_lines_labelled"          # source of front/rear positions (in project)
FOOTPRINT_DIR  = "footprint"
FOOTPRINT_NAME = "footprint"  
FOOTPRINT_PATH = BASE + "/" + FOOTPRINT_DIR + "/footprint.gpkg"

PID_FIELD   = "parcel_id"
LABEL_FIELD = "segment_label" 
FRONT_VALUE = "front"
REAR_VALUE  = "rear"

ROT_STEP   = 10.0     # rotation step, degrees (0..360 swept)
SEED_STEP  = 4.0      # spacing of starting positions across the parcel (m)
MOVE_STEP  = 0.5      # translation step for the slide-in search (m); halves as it homes in
AREA_TOL   = 1e-6     # overflow area treated as "fully inside" (m2)
# --------------------------------------------------------------------

def get_layer(name, path=None):
  found = QgsProject.instance().mapLayersByName(name)
  if found:
      return found[0]
  if path:
      lyr = QgsVectorLayer(path, name, "ogr")
      if lyr.isValid():
          return lyr 
  raise Exception("layer not found: " + name)

def midpoint_of(geom):
  poly = geom.asPolyline()  
  if len(poly) >= 2:
      a, b = poly[0], poly[-1]
      return (a.x() + b.x()) / 2, (a.y() + b.y()) / 2
  c = geom.centroid().asPoint()
  return c.x(), c.y()

def mean_xy(pts):
  if not pts:
      return None
  return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

def dist(ax, ay, bx, by):
  return math.hypot(ax - bx, ay - by)

def overflow(g, parcel):
  out = g.difference(parcel)
  return 0.0 if out.isEmpty() else out.area()

def settle(g, parcel, step):  
  a = overflow(g, parcel)
  s = step
  dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
  while s >= 0.05:
      if a < AREA_TOL:
          return g, 0.0
      improved = False
      for ux, uy in dirs:
          nrm = math.hypot(ux, uy)
          gt = QgsGeometry(g); gt.translate(ux / nrm * s, uy / nrm * s)
          at = overflow(gt, parcel)
          if at < a - 1e-12:
              g, a, improved = gt, at, True
              break
      if not improved:
          s *= 0.5
  return g, a

def best_fit(footprint, parcel, fpos, rpos):
  """All rotations + seed/slide search. A placement is accepted only if fully
  contained AND its centroid is closer to the parcel rear than the front.
  Returns (placed_geom, angle, d_front, d_rear) or None."""
  if rpos is None or footprint.area() > parcel.area():
      return None
  pivot = footprint.centroid().asPoint()
  pbb = parcel.boundingBox()
  pc = parcel.centroid().asPoint()
  seeds = [(pc.x(), pc.y())]
  x = pbb.xMinimum()
  while x <= pbb.xMaximum():
      y = pbb.yMinimum()
      while y <= pbb.yMaximum():
          if parcel.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
              seeds.append((x, y))
          y += SEED_STEP
      x += SEED_STEP
  n = int(round(360.0 / ROT_STEP))
  for k in range(n):
      ang = k * ROT_STEP
      fr = QgsGeometry(footprint); fr.rotate(ang, pivot)
      frc = fr.centroid().asPoint()
      for sx, sy in seeds:
          g = QgsGeometry(fr); g.translate(sx - frc.x(), sy - frc.y())
          g, a = settle(g, parcel, MOVE_STEP)
          if a < AREA_TOL:
              bc = g.centroid().asPoint()
              d_rear = dist(bc.x(), bc.y(), rpos[0], rpos[1])
              d_front = dist(bc.x(), bc.y(), fpos[0], fpos[1]) if fpos else None
              if d_front is None or d_rear < d_front:     # closer to rear than front
                  return g, round(ang, 2), d_front, d_rear
  return None

# --- load layers ---
buildable = get_layer(BUILDABLE_NAME)
lines     = get_layer(LINES_NAME)
footprint_lyr = get_layer(FOOTPRINT_NAME, FOOTPRINT_PATH)

ffeat = next(footprint_lyr.getFeatures())
footprint_geom = QgsGeometry(ffeat.geometry())
if not footprint_geom.isGeosValid():
  footprint_geom = footprint_geom.makeValid()
if footprint_lyr.crs() != buildable.crs():
  footprint_geom.transform(QgsCoordinateTransform(footprint_lyr.crs(), buildable.crs(), QgsProject.instance()))

# --- per-parcel average front/rear positions from labelled lot lines ---
front_pts, rear_pts = defaultdict(list), defaultdict(list)
for f in lines.getFeatures():
  pid = f[PID_FIELD]
  lab = f[LABEL_FIELD]
  if lab == FRONT_VALUE:
      front_pts[pid].append(midpoint_of(f.geometry()))
  elif lab == REAR_VALUE:
      rear_pts[pid].append(midpoint_of(f.geometry()))
front_pos = {pid: mean_xy(v) for pid, v in front_pts.items()}
rear_pos  = {pid: mean_xy(v) for pid, v in rear_pts.items()}

has_pid = PID_FIELD in [fld.name() for fld in buildable.fields()]

# --- output layer ---
out = QgsVectorLayer("Polygon?crs=" + buildable.crs().authid(), "fitted_footprints", "memory")
flds = QgsFields()
for n, t in [(PID_FIELD, QVariant.String), ("rot_angle", QVariant.Double),
           ("d_front", QVariant.Double), ("d_rear", QVariant.Double)]:
  flds.append(QgsField(n, t))
out.dataProvider().addAttributes(flds.toList())
out.updateFields()  

# --- per-parcel fit + rear-position validation ---
feats, n_fit = [], 0
for p in buildable.getFeatures():
  parcel_geom = p.geometry()
  if not parcel_geom.isGeosValid():
      parcel_geom = parcel_geom.makeValid()
  pid = p[PID_FIELD] if has_pid else None
  res = best_fit(footprint_geom, parcel_geom, front_pos.get(pid), rear_pos.get(pid))
  if res is None:
      continue
  placed, ang, d_front, d_rear = res
  n_fit += 1
  f = QgsFeature(out.fields()) 
  f.setGeometry(placed)
  f.setAttributes([pid, ang,
                   None if d_front is None else round(d_front, 2),
                   round(d_rear, 2)])
  feats.append(f) 

out.dataProvider().addFeatures(feats)
QgsProject.instance().addMapLayer(out)
print("parcels tested:", buildable.featureCount(), "| footprint fits (closer to rear):", n_fit)
