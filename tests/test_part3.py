import sys
from pathlib import Path
import math
import io
import tempfile
import zipfile

# Set workspace path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyproj
import shapely.geometry
from shapely.geometry import Point, LineString, Polygon
from starlette.testclient import TestClient

from main import (
    app,
    Base,
    engine,
    determine_projected_crs,
    reproject_geometry,
    resolve_crs_and_project_geometry,
    detect_and_resolve_source_crs,
    get_crs_linear_unit,
    is_metric_crs,
    CRSResolutionResult,
    calculate_feature_measurement,
)

print("=" * 60)
print("PART 3 CRS STRATEGY & REPROJECTION TEST SUITE")
print("=" * 60)

# ==============================================================================
# SECTION A: GEOSPATIAL CORRECTNESS TESTS (A - I)
# ==============================================================================
print("\n--- 1. SPECIFIC CRS CORRECTNESS TESTS (A - I) ---")

# Test A: Paris (lon ~2.35, lat ~48.85) -> UTM Zone 31N (EPSG:32631)
poly_paris = Polygon([(2.34, 48.84), (2.36, 48.84), (2.36, 48.86), (2.34, 48.86), (2.34, 48.84)])
target_crs_a, name_a, note_a = determine_projected_crs(poly_paris, pyproj.CRS.from_epsg(4326))
assert target_crs_a.to_epsg() == 32631, f"Test A Failed: expected 32631, got {target_crs_a.to_epsg()}"
print(f"[PASS] Test A (Paris): {name_a}")

# Test B: Bangalore (77.59 E, 12.97 N) -> UTM Zone 43N (EPSG:32643)
poly_blr = Polygon([(77.58, 12.96), (77.60, 12.96), (77.60, 12.98), (77.58, 12.98), (77.58, 12.96)])
target_crs_b, name_b, note_b = determine_projected_crs(poly_blr, pyproj.CRS.from_epsg(4326))
assert target_crs_b.to_epsg() == 32643, f"Test B Failed: expected 32643, got {target_crs_b.to_epsg()}"
print(f"[PASS] Test B (Bangalore): {name_b}")

# Test C: New York (-74.0 W, 40.7 N) -> UTM Zone 18N (EPSG:32618)
poly_nyc = Polygon([(-74.01, 40.70), (-73.99, 40.70), (-73.99, 40.72), (-74.01, 40.72), (-74.01, 40.70)])
target_crs_c, name_c, note_c = determine_projected_crs(poly_nyc, pyproj.CRS.from_epsg(4326))
assert target_crs_c.to_epsg() == 32618, f"Test C Failed: expected 32618, got {target_crs_c.to_epsg()}"
print(f"[PASS] Test C (New York): {name_c}")

# Test D: Southern Hemisphere (Sydney, 151.2 E, -33.86 S) -> UTM Zone 56S (EPSG:32756)
poly_syd = Polygon([(151.19, -33.87), (151.21, -33.87), (151.21, -33.85), (151.19, -33.85), (151.19, -33.87)])
target_crs_d, name_d, note_d = determine_projected_crs(poly_syd, pyproj.CRS.from_epsg(4326))
assert target_crs_d.to_epsg() == 32756, f"Test D Failed: expected 32756, got {target_crs_d.to_epsg()}"
print(f"[PASS] Test D (Southern Hemisphere Sydney): {name_d}")

# Test E: Already Projected CRS (EPSG:32631) -> not round-tripped through EPSG:4326
poly_utm = Polygon([(452000, 5410000), (453000, 5410000), (453000, 5411000), (452000, 5411000), (452000, 5410000)])
res_e = resolve_crs_and_project_geometry(poly_utm, pyproj.CRS.from_epsg(32631), "EPSG:32631")
assert res_e.status == "RETAINED_PROJECTED", f"Test E Failed: status is {res_e.status}"
assert res_e.target_crs.to_epsg() == 32631
assert res_e.reprojected_geom == poly_utm  # identical geometry object, no conversion
print(f"[PASS] Test E (Already Projected Metric CRS Retained): {res_e.note}")

# Test F: Large Longitudinal Extent (>= 6 degrees) -> equal-area fallback (EPSG:6933)
poly_large = Polygon([(10.0, 45.0), (20.0, 45.0), (20.0, 48.0), (10.0, 48.0), (10.0, 45.0)]) # 10 deg span
target_crs_f, name_f, note_f = determine_projected_crs(poly_large, pyproj.CRS.from_epsg(4326))
assert target_crs_f.to_epsg() == 6933, f"Test F Failed: expected 6933, got {target_crs_f.to_epsg()}"
print(f"[PASS] Test F (Large Longitudinal Extent Fallback): {name_f}")

# Test G1: Valid extreme latitude within EPSG:6933 coverage (lat 85.0) -> fallback remains valid
poly_polar_85 = Polygon([(10.0, 84.5), (12.0, 84.5), (12.0, 85.5), (10.0, 85.5), (10.0, 84.5)])
target_crs_g1, name_g1, note_g1 = determine_projected_crs(poly_polar_85, pyproj.CRS.from_epsg(4326))
assert target_crs_g1 is not None, "Test G1 Failed: target_crs should not be None for lat 85°"
assert target_crs_g1.to_epsg() == 6933, f"Test G1 Failed: expected 6933, got {target_crs_g1.to_epsg()}"
print(f"[PASS] Test G1 (Extreme Latitude within ±86° Coverage -> EPSG:6933): {name_g1}")

# Test G2: Latitude beyond 86° (lat 89.0) -> must NOT select EPSG:6933, returns clear error
poly_polar_89 = Polygon([(10.0, 88.5), (12.0, 88.5), (12.0, 89.5), (10.0, 89.5), (10.0, 88.5)])
target_crs_g2, name_g2, note_g2 = determine_projected_crs(poly_polar_89, pyproj.CRS.from_epsg(4326))
assert target_crs_g2 is None, f"Test G2 Failed: target_crs must NOT be selected for lat 89°, got {target_crs_g2}"
assert "exceeds ±86.0°" in note_g2, f"Test G2 Failed: unexpected note: {note_g2}"
res_g2 = resolve_crs_and_project_geometry(poly_polar_89, pyproj.CRS.from_epsg(4326), "EPSG:4326")
assert res_g2.status == "ERROR"
assert res_g2.target_crs is None
assert "exceeds ±86.0°" in res_g2.note
print(f"[PASS] Test G2 (Latitude beyond 86° safely rejected without selecting EPSG:6933): {note_g2}")

# Test H: Missing CRS (None) -> Preserves unknown, returns clear error, never invents EPSG:4326
res_h = resolve_crs_and_project_geometry(poly_blr, None, None)
assert res_h.status == "UNKNOWN_CRS"
assert res_h.target_crs is None
assert res_h.reprojected_geom is None
stat_meas, meas_det, note_meas = calculate_feature_measurement(poly_blr, None, None)
assert stat_meas == "ERROR"
assert meas_det is None
assert "missing coordinate reference system" in note_meas.lower()
print(f"[PASS] Test H (Missing CRS Handled Gracefully without Guessing): {note_meas}")

# Test I: Axis order (always_xy=True ensures lon=X, lat=Y)
pt = Point(2.35, 48.85)  # lon=2.35, lat=48.85
proj_pt, err_pt = reproject_geometry(pt, pyproj.CRS.from_epsg(4326), pyproj.CRS.from_epsg(32631))
assert err_pt is None
# In UTM 31N, Paris coordinates are approx easting ~452314 m, northing ~5410984 m
assert 450000 < proj_pt.x < 460000, f"X axis out of range for UTM easting: {proj_pt.x}"
assert 5400000 < proj_pt.y < 5420000, f"Y axis out of range for UTM northing: {proj_pt.y}"
print(f"[PASS] Test I (Axis Order Validation): (lon={pt.x}, lat={pt.y}) -> (Easting={proj_pt.x:.1f}, Northing={proj_pt.y:.1f})")

# Test J: Non-metric projected data (EPSG:2263 in US survey feet) -> reprojected to metric
res_j = resolve_crs_and_project_geometry(
    Polygon([(980000, 190000), (990000, 190000), (990000, 200000), (980000, 200000), (980000, 190000)]),
    pyproj.CRS.from_epsg(2263),
    "EPSG:2263"
)
assert res_j.status == "NON_METRIC_REPROJECTED"
assert res_j.source_linear_unit == "US survey foot"
assert res_j.target_linear_unit == "metre"
assert res_j.target_crs.to_epsg() == 32618
print(f"[PASS] Test J (Non-metric State Plane in feet reprojected to metric UTM): {res_j.note}")


# ==============================================================================
# SECTION B: FASTAPI REGRESSION TESTS (Part 1 & Part 2)
# ==============================================================================
print("\n--- 2. REGRESSION TESTS WITH TESTCLIENT ---")
client = TestClient(app)

# 1. Health check
r_health = client.get("/api/health/")
assert r_health.status_code == 200
print("[PASS] GET /api/health/ -> 200 OK")

# 2. Valid KML upload
kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Paris Polygon</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>2.34,48.84,0 2.36,48.84,0 2.36,48.86,0 2.34,48.86,0 2.34,48.84,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
r_kml = client.post("/api/files/", files={"file": ("paris.kml", kml_content.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r_kml.status_code == 201
kml_id = r_kml.json()["id"]
r_meas = client.get(f"/api/files/{kml_id}/measurements/")
assert r_meas.status_code == 200
meas_item = r_meas.json()["measurements"][0]
assert meas_item["measurement"]["projected_crs"] == "EPSG:32631 (WGS 84 / UTM zone 31N)"
assert meas_item["measurement"]["type"] == "area"
assert meas_item["measurement"]["value"] > 0
print(f"[PASS] Valid KML correctly projected to: {meas_item['measurement']['projected_crs']} with area={meas_item['measurement']['value']} m²")

# 3. Fake non-KML XML upload rejected
fake_xml = b"""<?xml version="1.0" encoding="UTF-8"?><note><to>Alice</to><body>Test</body></note>"""
r_fake = client.post("/api/files/", files={"file": ("fake.kml", fake_xml, "application/vnd.google-earth.kml+xml")})
assert r_fake.status_code == 400
assert "root element must be <kml>" in r_fake.json()["detail"].lower()
print("[PASS] Fake KML rejected with HTTP 400")

# 4. Shapefile without .prj upload (verifies CRS preserved as None, does NOT invent EPSG:4326)
def build_test_shapefile_zip(include_prj=True):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        import geopandas as gpd
        gdf = gpd.GeoDataFrame(
            {"id": [1], "name": ["Plot A"]},
            geometry=[Polygon([(77.58, 12.96), (77.60, 12.96), (77.60, 12.98), (77.58, 12.98), (77.58, 12.96)])],
            crs="EPSG:4326" if include_prj else None
        )
        shp_path = base / "test.shp"
        gdf.to_file(shp_path)
        if not include_prj:
            prj_file = base / "test.prj"
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
r_det = client.get(f"/api/files/{no_prj_id}/")
feat_no_prj = r_det.json()["features"][0]
assert feat_no_prj["status"] == "ERROR"
assert "missing coordinate reference system" in feat_no_prj["error_message"].lower()
print("[PASS] Shapefile without .prj accurately preserved as unknown CRS (None) with clear error note")

# 5. Shapefile WITH .prj upload
zip_with_prj = build_test_shapefile_zip(include_prj=True)
r_with_prj = client.post("/api/files/", files={"file": ("with_prj.zip", zip_with_prj, "application/zip")})
assert r_with_prj.status_code == 201
assert r_with_prj.json()["crs"] == "EPSG:4326"
with_prj_id = r_with_prj.json()["id"]
r_meas_prj = client.get(f"/api/files/{with_prj_id}/measurements/")
assert r_meas_prj.json()["measurements"][0]["measurement"]["projected_crs"] == "EPSG:32643 (WGS 84 / UTM zone 43N)"
print("[PASS] Shapefile with .prj correctly resolved to EPSG:32643")

print("\n" + "=" * 60)
print(">>> ALL PART 3 CRS TESTS AND REGRESSIONS PASSED! <<<")
print("=" * 60)
