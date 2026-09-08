import math, uuid, processing
from collections import defaultdict
from qgis.core import (QgsVectorLayer, QgsFeature, QgsField, QgsFields,
                     QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsProject)
from qgis.PyQt.QtCore import QVariant
import importlib.util

# ============================== CONFIG ==============================
#CONFIG_PATH = ("/Users/jamie/Documents/UBCO_MDS/w2025-data599-capstone-projects-green-metrics-technology/code/gis_files/burnaby/burnaby_scripts/burnaby_params.py")
CONFIG_PATH = ("/Users/jamie/Documents/UBCO_MDS/w2025-data599-capstone-projects-green-metrics-technology/code/gis_files/calgary/calgary_scripts/calgary_params.py")

_spec = importlib.util.spec_from_file_location("buildable_config", CONFIG_PATH)
_cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cfg)
globals().update({k: getattr(_cfg, k) for k in dir(_cfg) if k.isupper()})

THRESHOLD = 50.0
OVERLAP_TOL = 10
TRIM = 0.01
# ====================================================================

def normstr(v):
  return " ".join(str(v).strip().upper().split()) if v is not None else ""

def fval(feat, field):
  if not field:   
      return None
  try:
      return feat[field]
  except KeyError:
      return None

def parcel_street_key(feat):
  if STREET_MATCH_MODE == "address":
      toks = str(fval(feat, PARCEL_ADDRESS_FIELD) or "").split()
      if toks and toks[0][0:1].isdigit():
          toks = toks[1:]   
      return normstr(" ".join(toks))
  return normstr(" ".join([str(fval(feat, PARCEL_STREETNAME_FIELD) or ""),
                           str(fval(feat, PARCEL_STREETTYPE_FIELD) or "")]))

def street_key(feat):
  if STREET_MATCH_MODE == "address":
      return normstr(fval(feat, STREET_FULLNAME_FIELD))
  return normstr(" ".join([str(fval(feat, STREET_NAME_FIELD) or ""),
                           str(fval(feat, STREET_TYPE_FIELD) or "")]))

def setback_distance(label, shared, closer_to_street):
  if label == "front":
      return FRONT_SETBACK
  if label == "side":
      if shared:
          return SIDE_INTERIOR_SETBACK
      return SIDE_STREET_SETBACK if closer_to_street else SIDE_INTERIOR_SETBACK
  if label == "rear":
      if shared:
          return REAR_INTERIOR_SETBACK
      return SIDE_STREET_SETBACK if closer_to_street else REAR_LANE_SETBACK
  return 0.0

def azimuth(p1, p2):
  return math.degrees(math.atan2(p2.x() - p1.x(), p2.y() - p1.y())) % 360

def trim_start(line, d):
  pts = line.asPolyline()
  a, b = pts[0], pts[-1]
  Ln = math.hypot(b.x() - a.x(), b.y() - a.y())
  if Ln <= d:
      return line 
  t = d / Ln
  na = QgsPointXY(a.x() + t * (b.x() - a.x()), a.y() + t * (b.y() - a.y()))
  return QgsGeometry.fromPolylineXY([na, b])

def rings_of(geom): 
  if geom.isMultipart():
      return [r for poly in geom.asMultiPolygon() for r in poly]
  return list(geom.asPolygon())

def boundary_geom(geom):
  return QgsGeometry.collectGeometry([QgsGeometry.fromPolylineXY(r) for r in rings_of(geom)])

def get_layer(name, path=None):
  found = QgsProject.instance().mapLayersByName(name)
  if found:
      return found[0]
  if path:
      lyr = QgsVectorLayer(path, name, "ogr")
      if lyr.isValid():
          return lyr
  raise Exception("layer not found: " + name)

def reproject(layer):
  if layer.crs().authid() == TARGET_CRS:
      return layer
  return processing.run("native:reprojectlayer",
                        {"INPUT": layer, "TARGET_CRS": TARGET_CRS, "OUTPUT": "memory:"})["OUTPUT"]

def load_reproj(path, name):
  lyr = QgsVectorLayer(path, name, "ogr")
  assert lyr.isValid(), "invalid layer: " + path
  return reproject(lyr)

def build_index(layer):
  idx, geoms = QgsSpatialIndex(), {}
  for i, f in enumerate(layer.getFeatures()):
      g = f.geometry()
      if g is None or g.isEmpty():
          continue
      geoms[i] = g
      ft = QgsFeature(i); ft.setGeometry(g); idx.addFeature(ft)
  return idx, geoms

def nearest_dist(pt_geom, idx, geoms, k=5):
  ids = idx.nearestNeighbor(pt_geom.asPoint(), k)
  if not ids:
      return float("inf")   
  return min(pt_geom.distance(geoms[i]) for i in ids if i in geoms)

# ===================== PART 1: pipeline -> empty buildable area per parcel =====================
parcels = load_reproj(PARCELS_PATH, "parcels")
streets = load_reproj(STREETS_PATH, "streets")
lanes   = load_reproj(LANES_PATH,   "lanes")
CRS = TARGET_CRS

street_index, street_geoms = build_index(streets)
lane_index,   lane_geoms   = build_index(lanes)

# zone resolver: from parcel field, or from a zoning layer
if PARCEL_ZONE_FIELD is None: 
  zoning = load_reproj(ZONING_PATH, "zoning")
  zgeoms, zindex = {}, QgsSpatialIndex()
  for i, zf in enumerate(zoning.getFeatures()):
      g = zf.geometry()
      if not g.isGeosValid():
          g = g.makeValid() 
      zgeoms[i] = (g, fval(zf, ZONE_FIELD))
      feat = QgsFeature(i); feat.setGeometry(g); zindex.addFeature(feat)
  def parcel_zone(pf):
      pt = pf.geometry().centroid()
      for cid in zindex.intersects(pt.boundingBox()):
          g, code = zgeoms[cid]
          if g.contains(pt):
              return code
      return None 
else:
  def parcel_zone(pf):
      return fval(pf, PARCEL_ZONE_FIELD)

parts = defaultdict(list)
for s in streets.getFeatures():
  parts[street_key(s)].append(s.geometry())
street_geom = {k: QgsGeometry.collectGeometry(v) for k, v in parts.items()}
all_streets = QgsGeometry.collectGeometry([g for v in parts.values() for g in v])

boundaries, parcel_index = {}, QgsSpatialIndex()
targets = [] 
counter = 0
for pf in parcels.getFeatures():
  g = pf.geometry()
  if g is None or g.isEmpty():
      continue
  if not g.isGeosValid():   
      g = g.makeValid()
  bgeom = boundary_geom(g)
  feat = QgsFeature(counter); feat.setGeometry(bgeom); parcel_index.addFeature(feat)
  boundaries[counter] = bgeom
  cid = counter   
  counter += 1

  lotid = None
  if PARCEL_LOTID_FIELD:
      try:
          lotid = int(fval(pf, PARCEL_LOTID_FIELD))
      except (TypeError, ValueError):
          lotid = None
      if lotid is None or not (LOT_ID_MIN <= lotid <= LOT_ID_MAX):
          continue

  zcode = parcel_zone(pf)
  if TARGET_ZONE is not None and normstr(zcode) != normstr(TARGET_ZONE):
      continue
  targets.append({"pid": str(uuid.uuid4()), "cid": cid, "lotid": lotid,
                  "ref": fval(pf, PARCEL_REF_FIELD), "skey": parcel_street_key(pf),
                  "zone": zcode, "poly": g, "bnd": bgeom})
print("indexed", counter, "parcels;", len(targets), "targets")

def is_shared(seg, own_cid):  
  for cid in parcel_index.intersects(seg.boundingBox()):
      if cid == own_cid:
          continue
      inter = seg.intersection(boundaries[cid])
      if not inter.isEmpty() and inter.length() > SHARE_TOL:
          return True
  return False

seg_fields = QgsFields()
for n, t in [("parcel_id", QVariant.String), ("parcel_ref", QVariant.String),
           ("lot_id", QVariant.Int), ("zone", QVariant.String),
           ("segment_id", QVariant.String), ("perp_bearing", QVariant.Double),
           ("street_facing_deviance", QVariant.Double),
           ("shared_line", QVariant.Bool), ("closer_to_street", QVariant.Bool),
           ("segment_label", QVariant.String), ("setback", QVariant.Double)]:
  seg_fields.append(QgsField(n, t))
lines = QgsVectorLayer("LineString?crs=" + CRS, "lot_lines_labelled", "memory")
lines.dataProvider().addAttributes(seg_fields.toList()); lines.updateFields()

bee_fields = QgsFields()
for n, t in [("parcel_id", QVariant.String), ("segment_id", QVariant.String),
           ("bee_bearing", QVariant.Double), ("segment_label", QVariant.String)]:
  bee_fields.append(QgsField(n, t))
bees = QgsVectorLayer("LineString?crs=" + CRS, "bee_lines", "memory")
bees.dataProvider().addAttributes(bee_fields.toList()); bees.updateFields()

lfeats, beefeats, counts = [], [], defaultdict(int)
empty_by_pid = {}   
pid_meta = {p["pid"]: p for p in targets}
for p in targets:
  sgeom = street_geom.get(p["skey"], all_streets)
  seg_setbacks = []
  for ring in rings_of(p["poly"]):
      for i in range(len(ring) - 1):
          a, b = ring[i], ring[i + 1]
          edge = QgsGeometry.fromPolylineXY([a, b])
          perp = (azimuth(a, b) + 90) % 360
          mid = QgsPointXY((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
          beel = QgsGeometry.fromPointXY(mid).shortestLine(sgeom)
          bp = beel.asPolyline()
          if len(bp) < 2:
              continue
          bee_b = azimuth(bp[0], bp[-1])
          dev = math.degrees(math.acos(max(-1.0, min(1.0,
                  abs(math.cos(math.radians(bee_b - perp)))))))
          tb = trim_start(beel, TRIM)
          any_p = False
          for cid in parcel_index.intersects(tb.boundingBox()):
              if tb.intersects(boundaries[cid]):
                  any_p = True
                  break
          own_p = tb.intersects(p["bnd"])
          if dev < THRESHOLD and not any_p:
              label = "front"
          elif dev < THRESHOLD and own_p:
              label = "rear"
          else:   
              label = "side"
          counts[label] += 1

          shared = is_shared(edge, p["cid"])
          closer_to_street = False
          if label in ("side", "rear") and not shared:
              mg = QgsGeometry.fromPointXY(mid)
              ds = nearest_dist(mg, street_index, street_geoms)
              dl = nearest_dist(mg, lane_index, lane_geoms)
              closer_to_street = ds < dl
          d = setback_distance(label, shared, closer_to_street)
          seg_setbacks.append(edge.buffer(d, BUFFER_SEGMENTS))

          seg_id = str(uuid.uuid4())
          lf = QgsFeature(lines.fields()); lf.setGeometry(edge)
          lf.setAttributes([p["pid"], p["ref"], p["lotid"], p["zone"],
                            seg_id, perp, dev, bool(shared), bool(closer_to_street), label, d])
          lfeats.append(lf)
          bf = QgsFeature(bees.fields()); bf.setGeometry(beel)
          bf.setAttributes([p["pid"], seg_id, bee_b, label])
          beefeats.append(bf)

  poly = p["poly"]
  if seg_setbacks:
      merged = QgsGeometry.unaryUnion(seg_setbacks)
      if not merged.isGeosValid():
          merged = merged.makeValid()
      build = poly.difference(merged)
  else:
      build = poly
  if build is not None and not build.isEmpty():
      empty_by_pid[p["pid"]] = build

lines.dataProvider().addFeatures(lfeats)
bees.dataProvider().addFeatures(beefeats)
QgsProject.instance().addMapLayer(lines)
QgsProject.instance().addMapLayer(bees)
print("segments:", len(lfeats), "| labels:", dict(counts),
    "| empty buildable parcels:", len(empty_by_pid))

# ===================== PART 2: assign buildings -> label -> buffer (ignore N smallest accessories) =====================
tgt_index = QgsSpatialIndex() 
tgt = {}
for k, p in enumerate(targets):
  tgt[k] = p
  feat = QgsFeature(k); feat.setGeometry(p["poly"]); tgt_index.addFeature(feat)
      
buildings = reproject(get_layer(BUILDINGS_NAME, BUILDINGS_PATH))
bld_by_pid = defaultdict(list)
for bld in buildings.getFeatures():
  bgeom = bld.geometry()
  if bgeom is None or bgeom.isEmpty():
      continue
  if not bgeom.isGeosValid():
      bgeom = bgeom.makeValid()
  # A building that spans multiple parcels belongs to EVERY parcel it overlaps,
  # so it gets ranked (primary/accessory/ignored) and subtracted per lot.
  for k in tgt_index.intersects(bgeom.boundingBox()):
      poly = tgt[k]["poly"]
      if not poly.intersects(bgeom):
          continue
      inter = poly.intersection(bgeom)
      if inter is None or inter.isEmpty() or inter.area() <= OVERLAP_TOL:
          continue  # pure edge-touching on a shared lot line, not a real span
      bld_by_pid[tgt[k]["pid"]].append(QgsGeometry(bgeom))

bld_fields = QgsFields()
for n, t in [("parcel_id", QVariant.String), ("building_label", QVariant.String),
           ("ignored", QVariant.Bool), ("buffer_m", QVariant.Double)]:
  bld_fields.append(QgsField(n, t))
bld_lyr = QgsVectorLayer("Polygon?crs=" + CRS, "buildings_labelled", "memory")
bld_lyr.dataProvider().addAttributes(bld_fields.toList()); bld_lyr.updateFields()

excl_by_pid, bld_out, n_ignored = {}, [], 0
for pid, blds in bld_by_pid.items():
  largest = max(blds, key=lambda gg: gg.area())
  accessories = sorted([g for g in blds if g is not largest], key=lambda gg: gg.area())
  n_skip = min(IGNORE_N_SMALLEST_ACCESSORIES, len(accessories))
  ignored_ids = set(id(g) for g in accessories[:n_skip])
  n_ignored += len(ignored_ids)
  excl = []
  for gg in blds:
      is_primary = gg is largest
      is_ignored = id(gg) in ignored_ids
      label = "primary_front" if is_primary else "accessory"
      d = MIN_FRONT_REAR if is_primary else MIN_ACCESSORY
      bo = QgsFeature(bld_lyr.fields()); bo.setGeometry(gg)
      bo.setAttributes([pid, label, bool(is_ignored), d]); bld_out.append(bo)
      if is_ignored:
          continue
      excl.append(gg)
      excl.append(gg.buffer(d, BUFFER_SEGMENTS))
  e = QgsGeometry.unaryUnion(excl)
  if not e.isGeosValid():   
      e = e.makeValid()
  excl_by_pid[pid] = e
bld_lyr.dataProvider().addFeatures(bld_out)
QgsProject.instance().addMapLayer(bld_lyr)
print("buildings assigned:", sum(len(v) for v in bld_by_pid.values()),
    "| accessories ignored:", n_ignored)

# ===================== PART 3: final = empty buildable - (kept buildings + buffers) =====================
final_fields = QgsFields()
for n, t in [("parcel_id", QVariant.String), ("parcel_ref", QVariant.String),
           ("lot_id", QVariant.Int), ("zone", QVariant.String),
           ("area_m2", QVariant.Double)]:
  final_fields.append(QgsField(n, t))
final = QgsVectorLayer("Polygon?crs=" + CRS, "buildable_areas", "memory")
final.dataProvider().addAttributes(final_fields.toList()); final.updateFields()

ffeats = []
for pid, build in empty_by_pid.items():
  g = build
  if pid in excl_by_pid:
      g = g.difference(excl_by_pid[pid])
  if g is None or g.isEmpty(): 
      continue
  m = pid_meta[pid]
  f = QgsFeature(final.fields()); f.setGeometry(g)
  f.setAttributes([pid, m["ref"], m["lotid"], m["zone"], round(g.area(), 2)])
  ffeats.append(f)
final.dataProvider().addFeatures(ffeats)
QgsProject.instance().addMapLayer(final)
print("buildable_areas:", len(ffeats), "features")
