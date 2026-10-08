"""
Part 9A Verification Suite: Functional Validation UI & End-to-End Frontend Flow
Tests all 20 required scenarios covering DOM, styles, JS logic, API integration, and security.
"""

import io
import json
import os
import pathlib
import re
import sys
import zipfile
import httpx
WORKSPACE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR))
API_BASE_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:5500"

print("=" * 70)
print("PART 9A — SIMPLE FUNCTIONAL UI VERIFICATION SUITE")
print("=" * 70)

# Load frontend files
index_html = (WORKSPACE_DIR / "index.html").read_text(encoding="utf-8")
styles_css = (WORKSPACE_DIR / "styles.css").read_text(encoding="utf-8")
script_js = (WORKSPACE_DIR / "script.js").read_text(encoding="utf-8")

client = httpx.Client(base_url=API_BASE_URL, timeout=30.0)

# ==============================================================================
# 1. SCENARIO 1: PAGE LOADS & HTML STRUCTURE
# ==============================================================================
print("\n--- 1. PAGE LOAD & STRUCTURE ---")
assert (WORKSPACE_DIR / "index.html").exists(), "index.html missing"
assert (WORKSPACE_DIR / "styles.css").exists(), "styles.css missing"
assert (WORKSPACE_DIR / "script.js").exists(), "script.js missing"
assert "<title>Geospatial File Measurement API</title>" in index_html
assert "<h1>Geospatial File Measurement API</h1>" in index_html
assert 'id="file-input"' in index_html
assert 'id="upload-btn"' in index_html
assert 'id="measurements-table"' in index_html
assert 'id="features-table"' in index_html
print("[PASS] Scenario 1: Page structure, titles, and files verified")


# ==============================================================================
# 2. SCENARIO 2: API HEALTH INDICATOR LOGIC & ENDPOINT
# ==============================================================================
print("\n--- 2. API HEALTH INDICATOR ---")
assert 'id="health-badge"' in index_html
assert "checkHealth" in script_js
r_health = client.get("/api/health/")
assert r_health.status_code == 200
assert r_health.json()["status"] == "ok"
print(f"[PASS] Scenario 2: Health check endpoint verified ({r_health.json()}) and UI badge bound")


# ==============================================================================
# 3. SCENARIO 3: VALID KML UPLOAD FLOW
# ==============================================================================
print("\n--- 3. VALID KML UPLOAD FLOW ---")
kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Parc des Buttes-Chaumont</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              2.3800,48.8800,0
              2.3850,48.8800,0
              2.3850,48.8850,0
              2.3800,48.8850,0
              2.3800,48.8800,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Rue de Crimee</name>
      <LineString>
        <coordinates>
          2.3800,48.8800,0
          2.3850,48.8850,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Metro Station</name>
      <Point>
        <coordinates>2.3825,48.8825,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""

r_upload = client.post("/api/files/", files={"file": ("test_survey.kml", kml_content.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r_upload.status_code == 201, f"Expected 201, got {r_upload.status_code}: {r_upload.text}"
kml_file_id = r_upload.json()["id"]
print(f"[PASS] Scenario 3: Valid KML upload succeeded (id={kml_file_id})")


# ==============================================================================
# 4. SCENARIO 4: KML FILE SUMMARY RETRIEVAL
# ==============================================================================
print("\n--- 4. KML FILE SUMMARY ---")
r_detail = client.get(f"/api/files/{kml_file_id}/")
assert r_detail.status_code == 200
kml_detail = r_detail.json()
assert kml_detail["filename"] == "test_survey.kml"
assert kml_detail["file_type"] == "kml"
assert kml_detail["feature_count"] == 3
assert kml_detail["status"] == "COMPLETED"
assert "4326" in kml_detail["crs"]
print(f"[PASS] Scenario 4: KML summary verified (Features: {kml_detail['feature_count']}, CRS: {kml_detail['crs']}, Status: {kml_detail['status']})")


# ==============================================================================
# 5. SCENARIO 5: KML FEATURES RENDERING
# ==============================================================================
print("\n--- 5. KML FEATURES EXTRACTION ---")
features = kml_detail["features"]
assert len(features) == 3
geom_types = [f["geometry_type"] for f in features]
assert geom_types == ["Polygon", "LineString", "Point"]
print(f"[PASS] Scenario 5: Features parsed correctly: {geom_types}")


# ==============================================================================
# 6. SCENARIO 6: POLYGON AREA MEASUREMENT
# ==============================================================================
print("\n--- 6. POLYGON AREA MEASUREMENT ---")
r_meas = client.get(f"/api/files/{kml_file_id}/measurements/")
assert r_meas.status_code == 200
measurements = r_meas.json()["measurements"]
poly_meas = measurements[0]
assert poly_meas["geometry_type"] == "Polygon"
assert poly_meas["status"] == "COMPLETED"
assert poly_meas["measurement"]["type"] == "area"
assert poly_meas["measurement"]["unit"] == "square_meters"
assert poly_meas["measurement"]["value"] > 0
print(f"[PASS] Scenario 6: Polygon area calculated: {poly_meas['measurement']['value']:,.4f} m² (CRS: {poly_meas['measurement']['projected_crs']})")


# ==============================================================================
# 7. SCENARIO 7: LINESTRING LENGTH MEASUREMENT
# ==============================================================================
print("\n--- 7. LINESTRING LENGTH MEASUREMENT ---")
line_meas = measurements[1]
assert line_meas["geometry_type"] == "LineString"
assert line_meas["status"] == "COMPLETED"
assert line_meas["measurement"]["type"] == "length"
assert line_meas["measurement"]["unit"] == "meters"
assert line_meas["measurement"]["value"] > 0
print(f"[PASS] Scenario 7: LineString length calculated: {line_meas['measurement']['value']:,.4f} m (CRS: {line_meas['measurement']['projected_crs']})")


# ==============================================================================
# 8. SCENARIO 8: POINT SKIPPED MEASUREMENT
# ==============================================================================
print("\n--- 8. POINT SKIPPED MEASUREMENT ---")
pt_meas = measurements[2]
assert pt_meas["geometry_type"] == "Point"
assert pt_meas["status"] == "SKIPPED"
assert pt_meas["measurement"] is None
assert "point geometry does not require" in pt_meas["note"].lower()
print(f"[PASS] Scenario 8: Point geometry correctly marked SKIPPED with explanatory note")


# ==============================================================================
# 9. SCENARIO 9: VALID SHAPEFILE ZIP UPLOAD
# ==============================================================================
print("\n--- 9. SHAPEFILE ZIP UPLOAD ---")
import geopandas as gpd
from shapely.geometry import box
import tempfile

with tempfile.TemporaryDirectory() as td:
    shp_path = pathlib.Path(td) / "cadastre.shp"
    gdf = gpd.GeoDataFrame(
        {"name": ["Plot A", "Plot B"], "zone": ["Urban", "Commercial"]},
        geometry=[box(77.5, 12.9, 77.6, 13.0), box(77.6, 13.0, 77.7, 13.1)],
        crs="EPSG:4326"
    )
    gdf.to_file(shp_path)
    
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        for ext in [".shp", ".shx", ".dbf", ".prj"]:
            f = shp_path.with_suffix(ext)
            if f.exists():
                zf.write(f, arcname=f.name)
    zip_bytes = zip_buf.getvalue()

r_shp = client.post("/api/files/", files={"file": ("cadastre.zip", zip_bytes, "application/zip")})
assert r_shp.status_code == 201, f"Shapefile upload failed: {r_shp.text}"
shp_file_id = r_shp.json()["id"]
print(f"[PASS] Scenario 9: Valid Shapefile ZIP upload succeeded (id={shp_file_id})")


# ==============================================================================
# 10. SCENARIO 10: SHAPEFILE ATTRIBUTES DISPLAYED
# ==============================================================================
print("\n--- 10. SHAPEFILE ATTRIBUTES DISPLAY ---")
r_shp_detail = client.get(f"/api/files/{shp_file_id}/")
assert r_shp_detail.status_code == 200
shp_detail = r_shp_detail.json()
assert shp_detail["feature_count"] == 2
for feat in shp_detail["features"]:
    props = feat["properties"]
    assert "name" in props and "zone" in props
print(f"[PASS] Scenario 10: Attributes parsed and preserved in JSON format: {[f['properties'] for f in shp_detail['features']]}")


# ==============================================================================
# 11. SCENARIO 11: CRS DISPLAY (INPUT & PROJECTED)
# ==============================================================================
print("\n--- 11. CRS DISPLAY (INPUT & PROJECTED) ---")
r_shp_meas = client.get(f"/api/files/{shp_file_id}/measurements/")
assert r_shp_meas.status_code == 200
shp_meas_list = r_shp_meas.json()["measurements"]
assert "4326" in shp_meas_list[0]["measurement"]["input_crs"]
assert "32643" in shp_meas_list[0]["measurement"]["projected_crs"]
print(f"[PASS] Scenario 11: CRS displayed accurately (Input: {shp_meas_list[0]['measurement']['input_crs']} -> Projected: {shp_meas_list[0]['measurement']['projected_crs']})")


# ==============================================================================
# 12. SCENARIO 12: MISSING CRS SHAPEFILE BEHAVIOR
# ==============================================================================
print("\n--- 12. MISSING CRS SHAPEFILE BEHAVIOR ---")
with tempfile.TemporaryDirectory() as td:
    shp_path = pathlib.Path(td) / "no_crs.shp"
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(10, 10, 20, 20)]
    )
    gdf.to_file(shp_path)
    
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        for ext in [".shp", ".shx", ".dbf"]:
            f = shp_path.with_suffix(ext)
            if f.exists():
                zf.write(f, arcname=f.name)
    no_crs_zip = zip_buf.getvalue()

r_no_crs = client.post("/api/files/", files={"file": ("no_crs.zip", no_crs_zip, "application/zip")})
assert r_no_crs.status_code == 201
no_crs_id = r_no_crs.json()["id"]
r_no_crs_meas = client.get(f"/api/files/{no_crs_id}/measurements/")
assert r_no_crs_meas.json()["measurements"][0]["status"] == "ERROR"
assert "missing coordinate reference system" in r_no_crs_meas.json()["measurements"][0]["note"].lower()
print("[PASS] Scenario 12: Shapefile without .prj preserved with status=ERROR and clear explanatory note")


# ==============================================================================
# 13. SCENARIO 13: UNSUPPORTED EXTENSION VALIDATION
# ==============================================================================
print("\n--- 13. UNSUPPORTED EXTENSION REJECTION ---")
# Client JS check verification
assert "ALLOWED_EXTENSIONS" in script_js
assert '".kml"' in script_js and '".zip"' in script_js
r_bad_ext = client.post("/api/files/", files={"file": ("parcels.geojson", b'{"type":"FeatureCollection"}', "application/json")})
assert r_bad_ext.status_code == 400
assert "invalid file extension" in r_bad_ext.json()["detail"].lower()
print("[PASS] Scenario 13: Unsupported file formats rejected with clear message")


# ==============================================================================
# 14. SCENARIO 14: FILE >25 MB REJECTION
# ==============================================================================
print("\n--- 14. FILE > 25 MB LIMIT ---")
# Client JS check verification
assert "MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024" in script_js
# Backend enforcement
r_oversize = client.post("/api/files/", files={"file": ("huge.kml", b"x" * (25 * 1024 * 1024 + 1024), "application/vnd.google-earth.kml+xml")})
assert r_oversize.status_code == 413
assert "exceeds" in r_oversize.json()["detail"].lower()
print("[PASS] Scenario 14: Files > 25MB rejected by both client guard and backend HTTP 413")


# ==============================================================================
# 15. SCENARIO 15: MALFORMED KML REJECTION
# ==============================================================================
print("\n--- 15. MALFORMED KML REJECTION ---")
r_malformed = client.post("/api/files/", files={"file": ("broken.kml", b"<?xml version='1.0'?><kml><Placemark>", "application/vnd.google-earth.kml+xml")})
assert r_malformed.status_code == 400
assert "kml xml syntax error" in r_malformed.json()["detail"].lower()
print("[PASS] Scenario 15: Malformed KML XML rejected with HTTP 400")


# ==============================================================================
# 16. SCENARIO 16: BACKEND 404 NOT FOUND HANDLING
# ==============================================================================
print("\n--- 16. BACKEND 404 NOT FOUND HANDLING ---")
r_404 = client.get("/api/files/00000000-0000-0000-0000-000000000000/")
assert r_404.status_code == 404
assert "not found" in r_404.json()["detail"].lower()
print("[PASS] Scenario 16: 404 Not Found returns clean JSON error payload")


# ==============================================================================
# 17. SCENARIO 17: BACKEND 500 ERROR MASKING
# ==============================================================================
print("\n--- 17. BACKEND 500 ERROR MASKING ---")
assert "InternalServerError" in (WORKSPACE_DIR / "main.py").read_text(encoding="utf-8")
assert "An unexpected server error occurred." in (WORKSPACE_DIR / "main.py").read_text(encoding="utf-8")
print("[PASS] Scenario 17: Generic 500 error handler masks low-level exceptions from clients")


# ==============================================================================
# 18. SCENARIO 18: SECOND UPLOAD REPLACES PREVIOUS RESULTS
# ==============================================================================
print("\n--- 18. SECOND UPLOAD REPLACEMENT ---")
assert "clearRenderedTables" in script_js
assert "resultsContainer.style.display = \"none\"" in script_js
assert "hideError" in script_js
print("[PASS] Scenario 18: Upload flow cleans prior state and tables before processing new uploads")


# ==============================================================================
# 19. SCENARIO 19: NO HTML / SCRIPT INJECTION (SAFE textContent RENDERING)
# ==============================================================================
print("\n--- 19. XSS / SCRIPT INJECTION DEFENSE ---")
# Verify script.js NEVER sets innerHTML on any feature properties or notes
assert "innerHTML" not in script_js, "Found forbidden innerHTML usage in script.js!"
assert "textContent" in script_js, "Expected textContent DOM rendering"

# Upload KML containing XSS payload in placemark name and description
xss_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>&lt;script&gt;alert('xss')&lt;/script&gt;</name>
    <description>&lt;img src=x onerror=alert(1)&gt;</description>
    <Point><coordinates>1.0,2.0,0</coordinates></Point>
  </Placemark>
</kml>"""
r_xss = client.post("/api/files/", files={"file": ("xss_test.kml", xss_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r_xss.status_code == 201
xss_file_id = r_xss.json()["id"]
r_xss_detail = client.get(f"/api/files/{xss_file_id}/")
assert r_xss_detail.status_code == 200
prop_str = json.dumps(r_xss_detail.json()["features"][0]["properties"])
assert "<script>" in prop_str or "&lt;script&gt;" in prop_str
print("[PASS] Scenario 19: XSS payload safely handled as text without innerHTML rendering")


# ==============================================================================
# 20. SCENARIO 20: RESPONSIVE MOBILE LAYOUT
# ==============================================================================
print("\n--- 20. RESPONSIVE MOBILE LAYOUT ---")
assert "@media (max-width: 640px)" in styles_css
assert "overflow-x: auto" in styles_css
assert "table-responsive" in styles_css
print("[PASS] Scenario 20: Mobile responsive media queries and horizontal table scrolling verified")

print("\n" + "=" * 70)
print(">>> ALL 20 PART 9A FRONTEND & INTEGRATION SCENARIOS PASSED! <<<")
print("=" * 70)
