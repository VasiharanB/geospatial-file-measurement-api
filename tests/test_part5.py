import io
import sys
import tempfile
import zipfile
from pathlib import Path

# Workspace path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point

from main import app, Base, engine

client = TestClient(app)

print("=" * 65)
print("PART 5 API COMPLETION VERIFICATION SUITE")
print("=" * 65)

# ------------------------------------------------------------------------------
# 1. Health check: GET /api/health/ -> 200
# ------------------------------------------------------------------------------
r_health = client.get("/api/health/")
assert r_health.status_code == 200
assert r_health.json() == {"status": "ok", "service": "Geospatial File Measurement API"}
print("[PASS] 1. GET /api/health/ -> 200 OK")

# ------------------------------------------------------------------------------
# 2. POST valid KML -> 201
# ------------------------------------------------------------------------------
valid_kml = """<?xml version="1.0" encoding="UTF-8"?>
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
      <name>Survey Marker</name>
      <Point>
        <coordinates>2.35,48.85,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""

r_kml = client.post("/api/files/", files={"file": ("test_survey.kml", valid_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r_kml.status_code == 201, f"Expected 201, got {r_kml.status_code}: {r_kml.text}"
kml_resp = r_kml.json()
assert "id" in kml_resp
assert kml_resp["filename"] == "test_survey.kml"
assert kml_resp["file_type"] == "kml"
assert kml_resp["feature_count"] == 3
assert kml_resp["crs"] == "EPSG:4326"
assert kml_resp["status"] == "COMPLETED"
kml_file_id = kml_resp["id"]
print(f"[PASS] 2. POST valid KML -> 201 Created (id={kml_file_id})")

# ------------------------------------------------------------------------------
# 3. POST valid Shapefile ZIP -> 201
# ------------------------------------------------------------------------------
def build_test_shp_zip(include_prj=True):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        gdf = gpd.GeoDataFrame(
            {"id": [1, 2], "name": ["Plot A", "Plot B"]},
            geometry=[
                Polygon([(77.58, 12.96), (77.60, 12.96), (77.60, 12.98), (77.58, 12.98), (77.58, 12.96)]),
                Polygon([(77.62, 12.96), (77.64, 12.96), (77.64, 12.98), (77.62, 12.98), (77.62, 12.96)])
            ],
            crs="EPSG:4326" if include_prj else None
        )
        shp_file = base / "plots.shp"
        gdf.to_file(shp_file)
        if not include_prj:
            prj = base / "plots.prj"
            if prj.exists():
                prj.unlink()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in base.iterdir():
                zf.write(p, arcname=p.name)
        return buf.getvalue()

shp_zip_bytes = build_test_shp_zip(include_prj=True)
r_shp = client.post("/api/files/", files={"file": ("plots.zip", shp_zip_bytes, "application/zip")})
assert r_shp.status_code == 201, f"Expected 201, got {r_shp.status_code}: {r_shp.text}"
shp_resp = r_shp.json()
assert shp_resp["filename"] == "plots.zip"
assert shp_resp["file_type"] == "shapefile_zip"
assert shp_resp["feature_count"] == 2
assert shp_resp["crs"] == "EPSG:4326"
shp_file_id = shp_resp["id"]
print(f"[PASS] 3. POST valid Shapefile ZIP -> 201 Created (id={shp_file_id})")

# ------------------------------------------------------------------------------
# 4. POST unsupported extension -> 400
# ------------------------------------------------------------------------------
r_unsupported_ext = client.post(
    "/api/files/",
    files={"file": ("data.geojson", b'{"type": "FeatureCollection", "features": []}', "application/geo+json")}
)
assert r_unsupported_ext.status_code == 400, f"Expected 400, got {r_unsupported_ext.status_code}"
assert r_unsupported_ext.json()["error"] == "UnsupportedFileTypeException"
assert "invalid file extension '.geojson'" in r_unsupported_ext.json()["detail"].lower()

r_txt = client.post(
    "/api/files/",
    files={"file": ("notes.txt", b"plain text", "text/plain")}
)
assert r_txt.status_code == 400
print("[PASS] 4. POST unsupported extension (.geojson, .txt) -> 400 Bad Request")

# ------------------------------------------------------------------------------
# 5. GET existing file -> 200
# ------------------------------------------------------------------------------
r_get_file = client.get(f"/api/files/{kml_file_id}/")
assert r_get_file.status_code == 200
file_data = r_get_file.json()
assert file_data["id"] == kml_file_id
assert file_data["filename"] == "test_survey.kml"
assert file_data["file_type"] == "kml"
assert file_data["feature_count"] == 3
assert file_data["crs"] == "EPSG:4326"
assert file_data["status"] == "COMPLETED"
assert "created_at" in file_data
assert len(file_data["features"]) == 3
for feat in file_data["features"]:
    assert "feature_id" in feat
    assert "geometry_type" in feat
    assert "geometry" in feat
    assert "crs" in feat
    assert "properties" in feat
print(f"[PASS] 5. GET existing file -> 200 OK (returned {len(file_data['features'])} features)")

# ------------------------------------------------------------------------------
# 6. GET missing file -> 404
# ------------------------------------------------------------------------------
r_missing = client.get("/api/files/non-existent-uuid-12345/")
assert r_missing.status_code == 404
assert r_missing.json()["error"] == "ResourceNotFoundException"
assert "not found" in r_missing.json()["detail"].lower()

r_missing_meas = client.get("/api/files/non-existent-uuid-12345/measurements/")
assert r_missing_meas.status_code == 404
assert r_missing_meas.json()["error"] == "ResourceNotFoundException"
print("[PASS] 6. GET missing file (details & measurements) -> 404 Not Found")

# ------------------------------------------------------------------------------
# 7. GET measurements for valid polygon -> 200
# ------------------------------------------------------------------------------
r_kml_meas = client.get(f"/api/files/{kml_file_id}/measurements/")
assert r_kml_meas.status_code == 200
meas_data = r_kml_meas.json()
assert meas_data["file_id"] == kml_file_id
assert meas_data["status"] == "COMPLETED"
assert meas_data["total_features"] == 3

# Feature 0: Polygon
poly_meas = meas_data["measurements"][0]
assert poly_meas["geometry_type"] == "Polygon"
assert poly_meas["status"] == "COMPLETED"
assert poly_meas["measurement"]["type"] == "area"
assert poly_meas["measurement"]["unit"] == "square_meters"
assert isinstance(poly_meas["measurement"]["value"], float)
assert poly_meas["measurement"]["value"] > 1000000.0
assert "32631" in poly_meas["measurement"]["projected_crs"]
print(f"[PASS] 7. GET measurements for valid polygon -> 200 OK (area = {poly_meas['measurement']['value']} m²)")

# ------------------------------------------------------------------------------
# 8. GET measurements for valid line -> 200
# ------------------------------------------------------------------------------
line_meas = meas_data["measurements"][1]
assert line_meas["geometry_type"] == "LineString"
assert line_meas["status"] == "COMPLETED"
assert line_meas["measurement"]["type"] == "length"
assert line_meas["measurement"]["unit"] == "meters"
assert isinstance(line_meas["measurement"]["value"], float)
assert line_meas["measurement"]["value"] > 1000.0
assert "32631" in line_meas["measurement"]["projected_crs"]
print(f"[PASS] 8. GET measurements for valid line -> 200 OK (length = {line_meas['measurement']['value']} m)")

# ------------------------------------------------------------------------------
# 9. Point measurement -> SKIPPED
# ------------------------------------------------------------------------------
pt_meas = meas_data["measurements"][2]
assert pt_meas["geometry_type"] == "Point"
assert pt_meas["status"] == "SKIPPED"
assert pt_meas["measurement"] is None
assert "point geometry does not require" in pt_meas["note"].lower()
print(f"[PASS] 9. Point measurement -> SKIPPED with null measurement and explanatory note")

# ------------------------------------------------------------------------------
# 10. Missing CRS Shapefile -> controlled ERROR
# ------------------------------------------------------------------------------
no_prj_zip = build_test_shp_zip(include_prj=False)
r_no_prj = client.post("/api/files/", files={"file": ("unprojected.zip", no_prj_zip, "application/zip")})
assert r_no_prj.status_code == 201
assert r_no_prj.json()["crs"] is None
no_prj_id = r_no_prj.json()["id"]

r_no_prj_meas = client.get(f"/api/files/{no_prj_id}/measurements/")
assert r_no_prj_meas.status_code == 200
for item in r_no_prj_meas.json()["measurements"]:
    assert item["status"] == "ERROR"
    assert item["measurement"] is None
    assert "missing coordinate reference system (.prj)" in item["note"].lower()
print("[PASS] 10. Missing CRS Shapefile -> Ingestion 201, measurements=ERROR without guessing EPSG:4326")

# ------------------------------------------------------------------------------
# 11. Malformed KML -> 400
# ------------------------------------------------------------------------------
r_bad_kml = client.post(
    "/api/files/",
    files={"file": ("broken.kml", b"<kml><unclosed>", "application/vnd.google-earth.kml+xml")}
)
assert r_bad_kml.status_code == 400
assert r_bad_kml.json()["error"] == "MalformedFileException"
assert "syntax error" in r_bad_kml.json()["detail"].lower()
print("[PASS] 11. Malformed KML -> 400 Bad Request")

# ------------------------------------------------------------------------------
# 12. Malicious KML (XXE & SSRF) -> 400
# ------------------------------------------------------------------------------
xxe_payload = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><kml>&xxe;</kml>'
r_xxe = client.post("/api/files/", files={"file": ("xxe.kml", xxe_payload, "application/vnd.google-earth.kml+xml")})
assert r_xxe.status_code == 400
assert r_xxe.json()["error"] == "MalformedFileException"

ssrf_payload = b'<?xml version="1.0"?><kml><NetworkLink><Link><href>http://169.254.169.254/secret</href></Link></NetworkLink></kml>'
r_ssrf = client.post("/api/files/", files={"file": ("ssrf.kml", ssrf_payload, "application/vnd.google-earth.kml+xml")})
assert r_ssrf.status_code == 400
assert r_ssrf.json()["error"] == "MalformedFileException"
print("[PASS] 12. Malicious KML (XXE & NetworkLink SSRF) -> 400 Bad Request")

# ------------------------------------------------------------------------------
# 13. Malicious ZIP (Zip-Slip & Bomb) -> 400
# ------------------------------------------------------------------------------
# Zip-Slip
buf_slip = io.BytesIO()
with zipfile.ZipFile(buf_slip, "w") as zf:
    zf.writestr("../../etc/passwd", "root:x:0:0")
    zf.writestr("test.shp", "shp")
r_slip = client.post("/api/files/", files={"file": ("slip.zip", buf_slip.getvalue(), "application/zip")})
assert r_slip.status_code == 400
assert "zip-slip" in r_slip.json()["detail"].lower()

# Zip bomb (excessive compression ratio)
buf_bomb = io.BytesIO()
with zipfile.ZipFile(buf_bomb, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("bomb.bin", b"0" * (2 * 1024 * 1024))
r_bomb = client.post("/api/files/", files={"file": ("bomb.zip", buf_bomb.getvalue(), "application/zip")})
assert r_bomb.status_code == 400
assert "excessively compressed" in r_bomb.json()["detail"].lower()
print("[PASS] 13. Malicious ZIP (Zip-Slip & Compression Bomb) -> 400 Bad Request")

# ------------------------------------------------------------------------------
# 14. Documentation: /docs & /openapi.json -> 200
# ------------------------------------------------------------------------------
r_docs = client.get("/docs")
assert r_docs.status_code == 200

r_openapi = client.get("/openapi.json")
assert r_openapi.status_code == 200
schema = r_openapi.json()
paths = schema.get("paths", {})
assert "/api/health/" in paths
assert "/api/files/" in paths
assert "/api/files/{id}/" in paths
assert "/api/files/{id}/measurements/" in paths

# Verify tags and parameter descriptions
assert "Files" in [tag["name"] for tag in schema.get("tags", [])] or any("Files" in op.get("tags", []) for op in paths["/api/files/"].values())
print("[PASS] 14. Documentation (/docs, /openapi.json) -> 200 OK with all required endpoints documented")

# ------------------------------------------------------------------------------
# 15. Security & Path-Leakage Check
# ------------------------------------------------------------------------------
# Verify that error responses do not leak server filesystem paths or stack traces
assert "c:\\" not in r_bad_kml.text.lower()
assert "/tmp" not in r_bad_kml.text.lower()
assert "traceback" not in r_bad_kml.text.lower()
assert "select " not in r_bad_kml.text.lower()

assert "c:\\" not in r_missing.text.lower()
assert "traceback" not in r_missing.text.lower()
assert "select " not in r_missing.text.lower()
print("[PASS] 15. Security Audit: Zero filesystem path, SQL query, or Python traceback leakage in responses")

print("\n" + "=" * 65)
print(">>> ALL PART 5 API TESTS PASSED WITH ZERO FAILURES! <<<")
print("=" * 65)
