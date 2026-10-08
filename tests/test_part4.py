import sys
import io
import math
import tempfile
import zipfile
from pathlib import Path

# Workspace path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyproj
import shapely.geometry
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, Point, MultiPoint, GeometryCollection, LinearRing
from starlette.testclient import TestClient

from main import (
    app,
    Base,
    engine,
    calculate_feature_measurement,
    determine_projected_crs,
    resolve_crs_and_project_geometry,
    reproject_geometry,
    CRSResolutionResult,
)

print("=" * 65)
print("PART 4 MEASUREMENT ENGINE BENCHMARK & REGRESSION TEST SUITE")
print("=" * 65)

# ==============================================================================
# SECTION 1: BENCHMARK GEOMETRIC TESTS (A - M)
# ==============================================================================
print("\n--- 1. GEOMETRIC BENCHMARK TESTS (A - M) ---")

# Test A — 100 m x 100 m square in metric projected CRS (EPSG:32631)
poly_100m = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
st_a, meas_a, note_a = calculate_feature_measurement(poly_100m, pyproj.CRS.from_epsg(32631), "EPSG:32631")
assert st_a == "COMPLETED"
assert meas_a is not None
assert meas_a.type == "area"
assert meas_a.unit == "square_meters"
assert abs(meas_a.value - 10000.0) < 0.01, f"Expected 10000.0 m², got {meas_a.value}"
print(f"[PASS] Test A (100m x 100m square): Area = {meas_a.value} m² (Expected ~10000.0 m²)")

# Test B — 500 m straight line in metric projected CRS (EPSG:32631)
line_500m = LineString([(0, 0), (500, 0)])
st_b, meas_b, note_b = calculate_feature_measurement(line_500m, pyproj.CRS.from_epsg(32631), "EPSG:32631")
assert st_b == "COMPLETED"
assert meas_b is not None
assert meas_b.type == "length"
assert meas_b.unit == "meters"
assert abs(meas_b.value - 500.0) < 0.01, f"Expected 500.0 m, got {meas_b.value}"
print(f"[PASS] Test B (500m straight line): Length = {meas_b.value} m (Expected ~500.0 m)")

# Test C — Polygon in EPSG:4326 (Paris area)
poly_paris = Polygon([(2.34, 48.84), (2.36, 48.84), (2.36, 48.86), (2.34, 48.86), (2.34, 48.84)])
st_c, meas_c, note_c = calculate_feature_measurement(poly_paris, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_c == "COMPLETED"
assert meas_c.type == "area"
assert meas_c.unit == "square_meters"
assert meas_c.value > 1000000.0  # Approx 3.26 km² = 3,260,000 m²
assert "32631" in meas_c.projected_crs
print(f"[PASS] Test C (Polygon in EPSG:4326): Area = {meas_c.value} m², projected to {meas_c.projected_crs}")

# Test D — LineString in EPSG:4326
line_blr = LineString([(77.59, 12.97), (77.60, 12.98)])
st_d, meas_d, note_d = calculate_feature_measurement(line_blr, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_d == "COMPLETED"
assert meas_d.type == "length"
assert meas_d.unit == "meters"
assert meas_d.value > 1000.0  # Approx 1.5 km
assert "32643" in meas_d.projected_crs
print(f"[PASS] Test D (LineString in EPSG:4326): Length = {meas_d.value} m, projected to {meas_d.projected_crs}")

# Test E — MultiPolygon (two 100m x 100m squares in EPSG:32631)
poly_1 = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
poly_2 = Polygon([(200, 0), (300, 0), (300, 100), (200, 100), (200, 0)])
mp = MultiPolygon([poly_1, poly_2])
st_e, meas_e, note_e = calculate_feature_measurement(mp, pyproj.CRS.from_epsg(32631), "EPSG:32631")
assert st_e == "COMPLETED"
assert meas_e.type == "area"
assert abs(meas_e.value - 20000.0) < 0.01, f"Expected 20000.0 m², got {meas_e.value}"
print(f"[PASS] Test E (MultiPolygon): Combined Area = {meas_e.value} m² (Expected ~20000.0 m²)")

# Test F — MultiLineString (two 500m lines in EPSG:32631)
line_1 = LineString([(0, 0), (500, 0)])
line_2 = LineString([(0, 100), (500, 100)])
mls = MultiLineString([line_1, line_2])
st_f, meas_f, note_f = calculate_feature_measurement(mls, pyproj.CRS.from_epsg(32631), "EPSG:32631")
assert st_f == "COMPLETED"
assert meas_f.type == "length"
assert abs(meas_f.value - 1000.0) < 0.01, f"Expected 1000.0 m, got {meas_f.value}"
print(f"[PASS] Test F (MultiLineString): Combined Length = {meas_f.value} m (Expected ~1000.0 m)")

# Test G — Point / MultiPoint -> SKIPPED
pt = Point(77.59, 12.97)
st_g, meas_g, note_g = calculate_feature_measurement(pt, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_g == "SKIPPED"
assert meas_g is None
assert "Point geometry does not require" in note_g
mpt = MultiPoint([(77.59, 12.97), (77.60, 12.98)])
st_g2, meas_g2, note_g2 = calculate_feature_measurement(mpt, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_g2 == "SKIPPED"
assert meas_g2 is None
print(f"[PASS] Test G (Point & MultiPoint): Status = SKIPPED, Note = {note_g}")

# Test H — Invalid Polygon (self-intersecting bow-tie)
# In EPSG:32631: two 10m triangles with total area = 50 m²
bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
assert not bowtie.is_valid
st_h, meas_h, note_h = calculate_feature_measurement(bowtie, pyproj.CRS.from_epsg(32631), "EPSG:32631")
assert st_h == "COMPLETED"
assert meas_h.type == "area"
assert abs(meas_h.value - 50.0) < 0.01, f"Expected 50.0 m², got {meas_h.value}"
assert "repaired" in note_h.lower()
print(f"[PASS] Test H (Invalid Bow-Tie Polygon): Repaired and measured Area = {meas_h.value} m², Note = {note_h}")

# Test I — Empty Geometry
empty_poly = Polygon()
st_i, meas_i, note_i = calculate_feature_measurement(empty_poly, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_i == "INVALID"
assert meas_i is None
assert "null or empty" in note_i.lower()
print(f"[PASS] Test I (Empty Geometry): Status = {st_i}, Note = {note_i}")

# Test J — Unsupported Geometry (GeometryCollection, LinearRing)
gc = GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])])
st_j, meas_j, note_j = calculate_feature_measurement(gc, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_j == "UNSUPPORTED"
assert meas_j is None
assert "not supported" in note_j.lower()
print(f"[PASS] Test J (Unsupported Geometry): Status = {st_j}, Note = {note_j}")

# Test K — Missing CRS
st_k, meas_k, note_k = calculate_feature_measurement(poly_100m, None, None)
assert st_k == "ERROR"
assert meas_k is None
assert "missing coordinate reference system" in note_k.lower()
print(f"[PASS] Test K (Missing CRS): Status = {st_k}, Note = {note_k}")

# Test L — Non-metric projected CRS (EPSG:2263 NY State Plane US survey feet)
# A 1000 ft x 1000 ft square: 1,000,000 sq ft ≈ 92,903.04 m²
poly_feet = Polygon([(980000, 190000), (981000, 190000), (981000, 191000), (980000, 191000), (980000, 190000)])
st_l, meas_l, note_l = calculate_feature_measurement(poly_feet, pyproj.CRS.from_epsg(2263), "EPSG:2263")
assert st_l == "COMPLETED"
assert meas_l.type == "area"
assert meas_l.unit == "square_meters"
assert "32618" in meas_l.projected_crs
assert 92000.0 < meas_l.value < 94000.0, f"Expected ~92903 m², got {meas_l.value}"
print(f"[PASS] Test L (Non-metric State Plane in feet): Reprojected to {meas_l.projected_crs}, Area = {meas_l.value} m²")

# Test M — Large Geographic Extent: Area vs Length CRS differentiation
# Area on large extent (10 deg span) -> EPSG:6933 (Equal Area)
poly_large = Polygon([(10.0, 45.0), (20.0, 45.0), (20.0, 48.0), (10.0, 48.0), (10.0, 45.0)])
st_m_area, meas_m_area, note_m_area = calculate_feature_measurement(poly_large, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_m_area == "COMPLETED"
assert "6933" in meas_m_area.projected_crs
print(f"[PASS] Test M1 (Large Extent Polygon): Selected {meas_m_area.projected_crs} (Equal Area)")

# Length on large extent (10 deg span at 45°N) -> Centered Azimuthal Equidistant (AEQD)
line_large = LineString([(10.0, 45.0), (20.0, 45.0)])
st_m_len, meas_m_len, note_m_len = calculate_feature_measurement(line_large, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert st_m_len == "COMPLETED"
assert "AEQD" in meas_m_len.projected_crs

# Reference geodesic distance on WGS 84 ellipsoid
geod = pyproj.Geod(ellps="WGS84")
ref_geodesic_len = geod.geometry_length(line_large)  # Approx 787,967.30 m

diff_m = abs(meas_m_len.value - ref_geodesic_len)
pct_err = (diff_m / ref_geodesic_len) * 100.0

# Verify against reference geodesic length within 0.05% tolerance (sub-meter accuracy)
# (EPSG:4087 would produce 1,113,194 m / 41.3% error, failing this test)
assert pct_err < 0.05, f"Length calculation error too high: {pct_err:.2f}% (Measured: {meas_m_len.value} m, Geodesic: {ref_geodesic_len:.2f} m)"
print(f"[PASS] Test M2 (Large Extent LineString): Measured = {meas_m_len.value} m, Reference Geodesic = {ref_geodesic_len:.2f} m, Diff = {diff_m:.2f} m, Error = {pct_err:.5f}% (Projected CRS: {meas_m_len.projected_crs})")


# ==============================================================================
# SECTION 2: FASTAPI INTEGRATION & REGRESSION SUITE
# ==============================================================================
print("\n--- 2. FASTAPI INTEGRATION VERIFICATION ---")
client = TestClient(app)

# 1. Health check
r_health = client.get("/api/health/")
assert r_health.status_code == 200
print("[PASS] GET /api/health/ -> 200 OK")

# 2. Multi-feature KML (Polygon, LineString, Point)
multi_geom_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Survey Polygon</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>2.34,48.84,0 2.36,48.84,0 2.36,48.86,0 2.34,48.86,0 2.34,48.84,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Survey Line</name>
      <LineString>
        <coordinates>2.34,48.84,0 2.36,48.86,0</coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Survey Station Point</name>
      <Point>
        <coordinates>2.35,48.85,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""

r_kml = client.post("/api/files/", files={"file": ("survey.kml", multi_geom_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r_kml.status_code == 201, f"KML upload failed: {r_kml.status_code} {r_kml.text}"
file_id = r_kml.json()["id"]

r_meas = client.get(f"/api/files/{file_id}/measurements/")
assert r_meas.status_code == 200
meas_list = r_meas.json()["measurements"]
assert len(meas_list) == 3

# Polygon
p_meas = meas_list[0]
assert p_meas["geometry_type"] == "Polygon"
assert p_meas["status"] == "COMPLETED"
assert p_meas["measurement"]["type"] == "area"
assert p_meas["measurement"]["unit"] == "square_meters"
assert p_meas["measurement"]["value"] > 1000000.0
assert "32631" in p_meas["measurement"]["projected_crs"]
print(f"[PASS] API KML Polygon: status={p_meas['status']}, area={p_meas['measurement']['value']} m²")

# LineString
l_meas = meas_list[1]
assert l_meas["geometry_type"] == "LineString"
assert l_meas["status"] == "COMPLETED"
assert l_meas["measurement"]["type"] == "length"
assert l_meas["measurement"]["unit"] == "meters"
assert l_meas["measurement"]["value"] > 1000.0
assert "32631" in l_meas["measurement"]["projected_crs"]
print(f"[PASS] API KML LineString: status={l_meas['status']}, length={l_meas['measurement']['value']} m")

# Point
pt_meas = meas_list[2]
assert pt_meas["geometry_type"] == "Point"
assert pt_meas["status"] == "SKIPPED"
assert pt_meas["measurement"] is None
assert "Point geometry does not require" in pt_meas["note"]
print(f"[PASS] API KML Point: status={pt_meas['status']}, measurement=null, note={pt_meas['note']}")

# 3. Shapefile without .prj -> 201 Created, crs=null, measurement status=ERROR
def build_test_shapefile_zip(include_prj=True):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        import geopandas as gpd
        gdf = gpd.GeoDataFrame(
            {"id": [1, 2], "name": ["Lot 1", "Lot 2"]},
            geometry=[
                Polygon([(77.58, 12.96), (77.60, 12.96), (77.60, 12.98), (77.58, 12.98), (77.58, 12.96)]),
                Polygon([(77.62, 12.96), (77.64, 12.96), (77.64, 12.98), (77.62, 12.98), (77.62, 12.96)])
            ],
            crs="EPSG:4326" if include_prj else None
        )
        shp_path = base / "parcels.shp"
        gdf.to_file(shp_path)
        if not include_prj:
            prj_file = base / "parcels.prj"
            if prj_file.exists():
                prj_file.unlink()
        
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in base.iterdir():
                zf.write(f, arcname=f.name)
        return buf.getvalue()

zip_no_prj = build_test_shapefile_zip(include_prj=False)
r_no_prj = client.post("/api/files/", files={"file": ("no_prj.zip", zip_no_prj, "application/zip")})
assert r_no_prj.status_code == 201
assert r_no_prj.json()["crs"] is None
no_prj_id = r_no_prj.json()["id"]

r_meas_no_prj = client.get(f"/api/files/{no_prj_id}/measurements/")
assert r_meas_no_prj.status_code == 200
for item in r_meas_no_prj.json()["measurements"]:
    assert item["status"] == "ERROR"
    assert item["measurement"] is None
    assert "missing coordinate reference system" in item["note"].lower()
print("[PASS] Shapefile without .prj: Ingestion 201 OK, CRS=null, measurements=ERROR with explanatory note")

# 4. Shapefile WITH .prj -> Measurements computed with EPSG:32643
zip_with_prj = build_test_shapefile_zip(include_prj=True)
r_with_prj = client.post("/api/files/", files={"file": ("with_prj.zip", zip_with_prj, "application/zip")})
assert r_with_prj.status_code == 201
assert r_with_prj.json()["crs"] == "EPSG:4326"
with_prj_id = r_with_prj.json()["id"]

r_meas_with_prj = client.get(f"/api/files/{with_prj_id}/measurements/")
assert r_meas_with_prj.status_code == 200
shp_meas = r_meas_with_prj.json()["measurements"]
assert shp_meas[0]["status"] == "COMPLETED"
assert shp_meas[0]["measurement"]["type"] == "area"
assert "32643" in shp_meas[0]["measurement"]["projected_crs"]
assert shp_meas[1]["status"] == "COMPLETED"
assert shp_meas[1]["measurement"]["type"] == "area"
assert "32643" in shp_meas[1]["measurement"]["projected_crs"]
print(f"[PASS] Shapefile with .prj: Polygon 1 area={shp_meas[0]['measurement']['value']} m², Polygon 2 area={shp_meas[1]['measurement']['value']} m², projected={shp_meas[0]['measurement']['projected_crs']}")

print("\n" + "=" * 65)
print(">>> ALL PART 4 BENCHMARKS AND INTEGRATION TESTS PASSED! <<<")
print("=" * 65)
