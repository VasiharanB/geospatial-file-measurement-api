import io
import sys
import tempfile
import zipfile
from pathlib import Path

# Add current workspace directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point

from main import app, Base, engine

# Ensure DB initialized
Base.metadata.create_all(bind=engine)
client = TestClient(app)

print("=" * 60)
print("PART 2 VERIFICATION SUITE")
print("=" * 60)

# ==============================================================================
# 1. KML TESTS
# ==============================================================================
print("\n--- 1. KML VALIDATION & INGESTION ---")

# 1.1 Valid Point KML
point_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Survey Marker 1</name>
      <description>Geodetic point</description>
      <Point><coordinates>77.5946,12.9716,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""
r = client.post("/api/files/", files={"file": ("point.kml", point_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r.status_code == 201, f"Point KML failed: {r.status_code} {r.text}"
point_id = r.json()["id"]
r_det = client.get(f"/api/files/{point_id}/")
feat = r_det.json()["features"][0]
assert feat["geometry_type"] == "Point"
assert feat["properties"]["Name"] == "Survey Marker 1"
assert feat["properties"]["description"] == "Geodetic point"
print("[PASS] Valid Point KML: OK")

# 1.2 Valid LineString KML
line_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Pipeline A</name>
      <LineString><coordinates>77.5900,12.9700,0 77.5950,12.9750,0</coordinates></LineString>
    </Placemark>
  </Document>
</kml>"""
r = client.post("/api/files/", files={"file": ("line.kml", line_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r.status_code == 201
line_id = r.json()["id"]
r_det = client.get(f"/api/files/{line_id}/")
assert r_det.json()["features"][0]["geometry_type"] == "LineString"
print("[PASS] Valid LineString KML: OK")

# 1.3 Valid Polygon KML
poly_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Parcel 101</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5946,12.9716,0 77.5970,12.9716,0 77.5970,12.9735,0 77.5946,12.9735,0 77.5946,12.9716,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
r = client.post("/api/files/", files={"file": ("poly.kml", poly_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r.status_code == 201
poly_id = r.json()["id"]
r_det = client.get(f"/api/files/{poly_id}/")
assert r_det.json()["features"][0]["geometry_type"] == "Polygon"
print("[PASS] Valid Polygon KML: OK")

# 1.4 Multiple Placemarks in one file
multi_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>P1</name><Point><coordinates>1,1,0</coordinates></Point></Placemark>
    <Placemark><name>L1</name><LineString><coordinates>1,1,0 2,2,0</coordinates></LineString></Placemark>
  </Document>
</kml>"""
r = client.post("/api/files/", files={"file": ("multi.kml", multi_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r.status_code == 201
assert r.json()["feature_count"] == 2
print("[PASS] Multiple Placemarks preserved: OK")

# 1.5 Malformed XML
malformed_xml = b"<kml><Document><Placemark><name>Unclosed</name></Document>"
r = client.post("/api/files/", files={"file": ("bad.kml", malformed_xml, "application/vnd.google-earth.kml+xml")})
assert r.status_code == 400
assert "syntax error" in r.json()["detail"].lower()
print("[PASS] Malformed XML rejected with 400: OK")

# 1.6 Fake KML (valid XML but NOT KML: <note><to>Alice</to><body>Test</body></note>)
fake_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<note>
    <to>Alice</to>
    <body>Test</body>
</note>"""
r_fake = client.post("/api/files/", files={"file": ("fake_note.kml", fake_xml, "application/vnd.google-earth.kml+xml")})
print(f"  Fake KML Upload HTTP Status: {r_fake.status_code}")
print(f"  Fake KML Upload Response: {r_fake.json()}")
assert r_fake.status_code == 400
assert "root element must be <kml>" in r_fake.json()["detail"].lower()
print("[PASS] Fake .kml (unrelated XML) rejected with 400: OK")

# 1.7 Malicious XXE Injection Attempt
xxe_xml = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><kml>&xxe;</kml>'
r = client.post("/api/files/", files={"file": ("xxe.kml", xxe_xml, "application/vnd.google-earth.kml+xml")})
assert r.status_code == 400
assert "security validation" in r.json()["detail"].lower() or "disallowed" in r.json()["detail"].lower()
print("[PASS] XXE attack rejected with 400: OK")

# 1.8 Remote NetworkLink SSRF Attempt
ssrf_kml = b'<?xml version="1.0"?><kml><NetworkLink><Link><href>http://169.254.169.254/metadata</href></Link></NetworkLink></kml>'
r = client.post("/api/files/", files={"file": ("ssrf.kml", ssrf_kml, "application/vnd.google-earth.kml+xml")})
assert r.status_code == 400
assert "external network link" in r.json()["detail"].lower()
print("[PASS] NetworkLink SSRF attempt rejected with 400: OK")


# ==============================================================================
# 2. SHAPEFILE ZIP TESTS
# ==============================================================================
print("\n--- 2. SHAPEFILE ZIP VALIDATION & INGESTION ---")

def build_shapefile_zip(include_shx=True, include_dbf=True, include_prj=True, nested_folder=None, extra_files=None):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        shp_dir = base_dir / nested_folder if nested_folder else base_dir
        shp_dir.mkdir(parents=True, exist_ok=True)
        shp_file = shp_dir / "parcels.shp"

        # Write shapefile
        gdf = gpd.GeoDataFrame(
            {
                "parcel_id": [101, 102],
                "owner": ["Alice", "Bob"],
                "geometry": [
                    Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                    Polygon([(2, 2), (3, 2), (3, 3), (2, 3)]),
                ],
            },
            crs="EPSG:4326" if include_prj else None,
        )
        gdf.to_file(shp_file)

        # Remove files if requested
        if not include_shx:
            (shp_dir / "parcels.shx").unlink(missing_ok=True)
        if not include_dbf:
            (shp_dir / "parcels.dbf").unlink(missing_ok=True)
        if not include_prj:
            (shp_dir / "parcels.prj").unlink(missing_ok=True)

        # Add extra files if requested
        if extra_files:
            for fname, fcontent in extra_files.items():
                (shp_dir / fname).write_text(fcontent)

        # Package into ZIP
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in base_dir.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=str(p.relative_to(base_dir)))
        return buf.getvalue()

# 2.1 Valid Shapefile (.shp + .shx + .dbf + .prj)
zip_valid = build_shapefile_zip(include_prj=True, extra_files={"README.txt": "Dataset notes"})
r = client.post("/api/files/", files={"file": ("valid_parcels.zip", zip_valid, "application/zip")})
assert r.status_code == 201, f"Failed: {r.status_code} {r.text}"
assert r.json()["crs"] == "EPSG:4326"
assert r.json()["feature_count"] == 2
print("[PASS] Valid Shapefile ZIP (.shp+.shx+.dbf+.prj + extra README.txt): OK")

# 2.2 Valid Shapefile without .prj (preserves unknown/None CRS)
zip_no_prj = build_shapefile_zip(include_prj=False)
r = client.post("/api/files/", files={"file": ("no_prj.zip", zip_no_prj, "application/zip")})
assert r.status_code == 201
assert r.json()["crs"] is None  # Accurately preserved as unknown
print("[PASS] Valid Shapefile without .prj (accurately reports CRS as null): OK")

# 2.3 Nested ZIP directory
zip_nested = build_shapefile_zip(nested_folder="gis/subfolder")
r = client.post("/api/files/", files={"file": ("nested.zip", zip_nested, "application/zip")})
assert r.status_code == 201
assert r.json()["feature_count"] == 2
print("[PASS] Nested directory Shapefile ZIP accepted: OK")

# 2.4 Missing .shx rejected
zip_no_shx = build_shapefile_zip(include_shx=False)
r = client.post("/api/files/", files={"file": ("no_shx.zip", zip_no_shx, "application/zip")})
assert r.status_code == 400
assert "missing mandatory companion file(s): .shx" in r.json()["detail"].lower()
print("[PASS] Missing .shx rejected with 400: OK")

# 2.5 Missing .dbf rejected
zip_no_dbf = build_shapefile_zip(include_dbf=False)
r = client.post("/api/files/", files={"file": ("no_dbf.zip", zip_no_dbf, "application/zip")})
assert r.status_code == 400
assert "missing mandatory companion file(s): .dbf" in r.json()["detail"].lower()
print("[PASS] Missing .dbf rejected with 400: OK")

# 2.6 No .shp file in ZIP
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("notes.txt", "hello world")
r = client.post("/api/files/", files={"file": ("no_shp.zip", buf.getvalue(), "application/zip")})
assert r.status_code == 400
assert "must contain at least one valid '.shp' file" in r.json()["detail"].lower()
print("[PASS] ZIP with no .shp rejected with 400: OK")

# 2.7 Corrupt/Invalid ZIP bytes
r = client.post("/api/files/", files={"file": ("corrupt.zip", b"PK\x03\x04corruptedbytesjunk", "application/zip")})
assert r.status_code == 400
assert "corrupted or invalid" in r.json()["detail"].lower()
print("[PASS] Corrupted ZIP archive rejected with 400: OK")


# ==============================================================================
# 3. ZIP SECURITY TESTS
# ==============================================================================
print("\n--- 3. ZIP SECURITY DEFENSES ---")

# 3.1 Zip-Slip path traversal (relative)
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("../../etc/passwd", "root:x:0:0")
    zf.writestr("test.shp", "shp")
r = client.post("/api/files/", files={"file": ("slip.zip", buf.getvalue(), "application/zip")})
assert r.status_code == 400
assert "zip-slip" in r.json()["detail"].lower()
print("[PASS] Relative Zip-Slip traversal (../../) rejected with 400: OK")

# 3.2 Absolute path inside ZIP (/etc/shadow)
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("/etc/shadow", "evil")
r = client.post("/api/files/", files={"file": ("abs.zip", buf.getvalue(), "application/zip")})
assert r.status_code == 400
assert "absolute path" in r.json()["detail"].lower()
print("[PASS] Absolute path in ZIP (/etc/shadow) rejected with 400: OK")

# 3.3 Windows-style traversal (..\..\windows\system32)
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("..\\..\\windows\\system32\\calc.exe", "evil")
r = client.post("/api/files/", files={"file": ("win_slip.zip", buf.getvalue(), "application/zip")})
assert r.status_code == 400
assert "zip-slip" in r.json()["detail"].lower()
print("[PASS] Windows backslash traversal (..\\..\\) rejected with 400: OK")

# 3.4 Oversized decompression (uncompressed > 100 MB with normal ratio < 100)
import random
rng = random.Random(42)
chunk_1mb = bytes([rng.randint(0, 1) for _ in range(1024 * 1024)])  # 1 MB, ratio ~ 6.4:1
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    for i in range(105):  # 105 MB total uncompressed, ~16.3 MB upload payload
        zf.writestr(f"file_{i}.bin", chunk_1mb)

r = client.post("/api/files/", files={"file": ("bomb_size.zip", buf.getvalue(), "application/zip")})
assert r.status_code == 400
assert "uncompressed size exceeds maximum" in r.json()["detail"].lower()
print("[PASS] Oversized decompression (>100MB) rejected with 400: OK")

# 3.5 Excessive compression ratio (> 100:1)
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    # 2 MB of zeros compressed into ~2 KB -> ratio ~ 1000:1
    data = b"0" * (2 * 1024 * 1024)
    zf.writestr("ratio_bomb.bin", data)
r = client.post("/api/files/", files={"file": ("ratio_bomb.zip", buf.getvalue(), "application/zip")})
assert r.status_code == 400
assert "excessively compressed" in r.json()["detail"].lower()
print("[PASS] Excessive compression ratio (>100:1) rejected with 400: OK")


# ==============================================================================
# 4. REGRESSION VERIFICATION (PART 1)
# ==============================================================================
print("\n--- 4. PART 1 REGRESSION VERIFICATION ---")

r_health = client.get("/api/health/")
assert r_health.status_code == 200
assert r_health.json() == {"status": "ok", "service": "Geospatial File Measurement API"}
print("[PASS] GET /api/health/ -> 200 OK")

r_docs = client.get("/docs")
assert r_docs.status_code == 200
print("[PASS] GET /docs -> 200 OK")

r_openapi = client.get("/openapi.json")
assert r_openapi.status_code == 200
print("[PASS] GET /openapi.json -> 200 OK")

print("\n" + "=" * 60)
print(">>> ALL PART 2 VERIFICATION TESTS PASSED PERFECTLY! <<<")
print("=" * 60)
