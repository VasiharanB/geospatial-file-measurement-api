import io
import math
import os
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

# Workspace path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient
from sqlalchemy import select, func
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point, GeometryCollection

from main import (
    app,
    Base,
    engine,
    SessionLocal,
    FileRecord,
    FeatureRecord,
    MeasurementRecord,
    STORAGE_DIR,
    MAX_UPLOAD_SIZE_BYTES,
)

client = TestClient(app)

print("=" * 70)
print("PART 6 — END-TO-END PROCESSING PIPELINE VERIFICATION SUITE")
print("=" * 70)

# ==============================================================================
# 1. SCENARIO 1: COMPLETE END-TO-END KML PIPELINE (A)
# ==============================================================================
print("\n--- 1. END-TO-END KML PIPELINE ---")
kml_survey = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Survey Parcel</name>
      <description>Lot 42 boundary</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              2.34,48.84,0 2.36,48.84,0 2.36,48.86,0 2.34,48.86,0 2.34,48.84,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Survey Traverse Line</name>
      <description>Transit baseline</description>
      <LineString>
        <coordinates>2.34,48.84,0 2.36,48.86,0</coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Benchmark Station</name>
      <description>Station BM-1</description>
      <Point>
        <coordinates>2.35,48.85,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""

r_kml = client.post(
    "/api/files/",
    files={"file": ("survey_cad.kml", kml_survey.encode("utf-8"), "application/vnd.google-earth.kml+xml")}
)
assert r_kml.status_code == 201, f"KML upload failed: {r_kml.status_code} {r_kml.text}"
kml_res = r_kml.json()
kml_id = kml_res["id"]
assert kml_res["filename"] == "survey_cad.kml"
assert kml_res["file_type"] == "kml"
assert kml_res["feature_count"] == 3
assert kml_res["crs"] == "EPSG:4326"
assert kml_res["status"] == "COMPLETED"

# Verify GET /api/files/{id}/
r_kml_detail = client.get(f"/api/files/{kml_id}/")
assert r_kml_detail.status_code == 200
kml_detail = r_kml_detail.json()
assert kml_detail["id"] == kml_id
assert kml_detail["status"] == "COMPLETED"
assert len(kml_detail["features"]) == 3
assert kml_detail["features"][0]["feature_id"] == 0
assert kml_detail["features"][0]["geometry_type"] == "Polygon"
assert kml_detail["features"][0]["properties"]["Name"] == "Survey Parcel"
assert kml_detail["features"][1]["feature_id"] == 1
assert kml_detail["features"][1]["geometry_type"] == "LineString"
assert kml_detail["features"][2]["feature_id"] == 2
assert kml_detail["features"][2]["geometry_type"] == "Point"

# Verify GET /api/files/{id}/measurements/
r_kml_meas = client.get(f"/api/files/{kml_id}/measurements/")
assert r_kml_meas.status_code == 200
kml_meas = r_kml_meas.json()
assert kml_meas["total_features"] == 3

# Polygon -> Area
p_meas = kml_meas["measurements"][0]
assert p_meas["feature_id"] == 0
assert p_meas["geometry_type"] == "Polygon"
assert p_meas["status"] == "COMPLETED"
assert p_meas["measurement"]["type"] == "area"
assert p_meas["measurement"]["unit"] == "square_meters"
assert p_meas["measurement"]["value"] > 1000000.0
assert "32631" in p_meas["measurement"]["projected_crs"]

# LineString -> Length
l_meas = kml_meas["measurements"][1]
assert l_meas["feature_id"] == 1
assert l_meas["geometry_type"] == "LineString"
assert l_meas["status"] == "COMPLETED"
assert l_meas["measurement"]["type"] == "length"
assert l_meas["measurement"]["unit"] == "meters"
assert l_meas["measurement"]["value"] > 1000.0
assert "32631" in l_meas["measurement"]["projected_crs"]

# Point -> SKIPPED
pt_meas = kml_meas["measurements"][2]
assert pt_meas["feature_id"] == 2
assert pt_meas["geometry_type"] == "Point"
assert pt_meas["status"] == "SKIPPED"
assert pt_meas["measurement"] is None
assert "point geometry does not require" in pt_meas["note"].lower()
print("[PASS] Scenario 1 (Complete KML Pipeline): Polygon area, Line length, Point SKIPPED, API retrieval matching")


# ==============================================================================
# 2. SCENARIO 2: COMPLETE END-TO-END SHAPEFILE PIPELINE (B)
# ==============================================================================
print("\n--- 2. END-TO-END SHAPEFILE PIPELINE ---")
def create_shapefile_zip(include_prj=True, extra_files=None):
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        gdf = gpd.GeoDataFrame(
            {
                "lot_no": [201, 202],
                "zoning": ["Commercial", "Residential"],
                "tax_value": [450000.50, 275000.00]
            },
            geometry=[
                Polygon([(77.58, 12.96), (77.60, 12.96), (77.60, 12.98), (77.58, 12.98), (77.58, 12.96)]),
                Polygon([(77.62, 12.96), (77.64, 12.96), (77.64, 12.98), (77.62, 12.98), (77.62, 12.96)]),
            ],
            crs="EPSG:4326" if include_prj else None
        )
        shp_path = base / "cadastre.shp"
        gdf.to_file(shp_path)
        if not include_prj:
            prj = base / "cadastre.prj"
            if prj.exists():
                prj.unlink()
        if extra_files:
            for fn, content in extra_files.items():
                (base / fn).write_text(content)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in base.iterdir():
                zf.write(p, arcname=p.name)
        return buf.getvalue()

shp_zip_data = create_shapefile_zip(include_prj=True, extra_files={"metadata.xml": "<meta>Cadastre</meta>"})
r_shp = client.post("/api/files/", files={"file": ("cadastre.zip", shp_zip_data, "application/zip")})
assert r_shp.status_code == 201
shp_res = r_shp.json()
shp_id = shp_res["id"]
assert shp_res["filename"] == "cadastre.zip"
assert shp_res["file_type"] == "shapefile_zip"
assert shp_res["feature_count"] == 2
assert shp_res["crs"] == "EPSG:4326"
assert shp_res["status"] == "COMPLETED"

# Verify GET /api/files/{id}/
r_shp_detail = client.get(f"/api/files/{shp_id}/")
assert r_shp_detail.status_code == 200
shp_det = r_shp_detail.json()
assert shp_det["feature_count"] == 2
assert shp_det["features"][0]["properties"]["lot_no"] == 201
assert shp_det["features"][0]["properties"]["zoning"] == "Commercial"
assert shp_det["features"][0]["properties"]["tax_value"] == 450000.50

# Verify GET /api/files/{id}/measurements/
r_shp_meas = client.get(f"/api/files/{shp_id}/measurements/")
assert r_shp_meas.status_code == 200
shp_m = r_shp_meas.json()
assert len(shp_m["measurements"]) == 2
for m in shp_m["measurements"]:
    assert m["status"] == "COMPLETED"
    assert m["measurement"]["type"] == "area"
    assert m["measurement"]["unit"] == "square_meters"
    assert "32643" in m["measurement"]["projected_crs"]
    assert m["measurement"]["value"] > 1000000.0
print("[PASS] Scenario 2 (Complete Shapefile Pipeline): Attributes parsed, CRS from .prj, metrics computed in EPSG:32643")


# ==============================================================================
# 3. SCENARIO 3: MISSING CRS FLOW (C)
# ==============================================================================
print("\n--- 3. MISSING CRS FLOW ---")
no_prj_zip = create_shapefile_zip(include_prj=False)
r_no_prj = client.post("/api/files/", files={"file": ("no_prj.zip", no_prj_zip, "application/zip")})
assert r_no_prj.status_code == 201
no_prj_res = r_no_prj.json()
assert no_prj_res["crs"] is None  # Never guesses EPSG:4326
no_prj_id = no_prj_res["id"]

# Detail returns geometry safely
r_no_prj_det = client.get(f"/api/files/{no_prj_id}/")
assert r_no_prj_det.status_code == 200
assert r_no_prj_det.json()["crs"] is None
assert len(r_no_prj_det.json()["features"]) == 2

# Measurements return controlled ERROR with explanation
r_no_prj_meas = client.get(f"/api/files/{no_prj_id}/measurements/")
assert r_no_prj_meas.status_code == 200
for m in r_no_prj_meas.json()["measurements"]:
    assert m["status"] == "ERROR"
    assert m["measurement"] is None
    assert "missing coordinate reference system (.prj)" in m["note"].lower()
print("[PASS] Scenario 3 (Missing CRS Flow): Ingestion 201, CRS preserved as null, measurements=ERROR without guessing 4326")


# ==============================================================================
# 4. SCENARIO 4: FEATURE-LEVEL FAILURE ISOLATION (D)
# ==============================================================================
print("\n--- 4. FEATURE-LEVEL FAILURE ISOLATION ---")
mixed_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <!-- Feature 0: Valid Polygon -->
    <Placemark>
      <name>Valid Field</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>2.34,48.84,0 2.36,48.84,0 2.36,48.86,0 2.34,48.86,0 2.34,48.84,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <!-- Feature 1: Point -->
    <Placemark>
      <name>Survey Peg</name>
      <Point>
        <coordinates>2.35,48.85,0</coordinates>
      </Point>
    </Placemark>
    <!-- Feature 2: Valid LineString -->
    <Placemark>
      <name>Boundary Wall</name>
      <LineString>
        <coordinates>2.34,48.84,0 2.36,48.84,0</coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""

r_mixed = client.post("/api/files/", files={"file": ("mixed_features.kml", mixed_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r_mixed.status_code == 201
mixed_id = r_mixed.json()["id"]

r_mix_meas = client.get(f"/api/files/{mixed_id}/measurements/")
assert r_mix_meas.status_code == 200
m_list = r_mix_meas.json()["measurements"]
assert len(m_list) == 3
assert m_list[0]["status"] == "COMPLETED"
assert m_list[0]["measurement"]["type"] == "area"
assert m_list[1]["status"] == "SKIPPED"
assert m_list[1]["measurement"] is None
assert m_list[2]["status"] == "COMPLETED"
assert m_list[2]["measurement"]["type"] == "length"
print("[PASS] Scenario 4 (Feature-Level Isolation): Valid Polygon measured, Point SKIPPED, Valid Line measured independently")


# ==============================================================================
# 5. SCENARIO 5: DATABASE TRANSACTION INTEGRITY & RESTART PERSISTENCE (E, J)
# ==============================================================================
print("\n--- 5. DATABASE TRANSACTION INTEGRITY & RESTART PERSISTENCE ---")
# Query SQLite database using fresh SessionLocal session to verify physical persistence
with SessionLocal() as db:
    db_file = db.execute(select(FileRecord).where(FileRecord.id == kml_id)).scalar_one_or_none()
    assert db_file is not None, "FileRecord not persisted in SQLite"
    assert db_file.filename == "survey_cad.kml"
    assert db_file.feature_count == 3
    assert db_file.status == "COMPLETED"

    db_features = db.execute(select(FeatureRecord).where(FeatureRecord.file_id == kml_id)).scalars().all()
    assert len(db_features) == 3, f"Expected 3 FeatureRecords in DB, found {len(db_features)}"

    db_measurements = db.execute(select(MeasurementRecord).where(MeasurementRecord.file_id == kml_id)).scalars().all()
    assert len(db_measurements) == 3, f"Expected 3 MeasurementRecords in DB, found {len(db_measurements)}"

    # Check relationships
    assert len(db_file.features) == 3
    assert len(db_file.measurements) == 3

    # Check for zero orphan records across the database
    orphan_features = db.execute(
        select(func.count(FeatureRecord.id)).where(~FeatureRecord.file_id.in_(select(FileRecord.id)))
    ).scalar()
    assert orphan_features == 0, f"Found {orphan_features} orphan feature rows"

    orphan_measurements = db.execute(
        select(func.count(MeasurementRecord.id)).where(~MeasurementRecord.file_id.in_(select(FileRecord.id)))
    ).scalar()
    assert orphan_measurements == 0, f"Found {orphan_measurements} orphan measurement rows"
print("[PASS] Scenario 5 (Persistence & Integrity): Verified physical SQLite persistence, relationships, and 0 orphan rows")


# ==============================================================================
# 6. SCENARIO 6: MULTIPLE UPLOADS & DUPLICATE SAFETY (F)
# ==============================================================================
print("\n--- 6. MULTIPLE UPLOADS & DUPLICATE SAFETY ---")
# Upload identical KML file second time
r_dup = client.post("/api/files/", files={"file": ("survey_cad.kml", kml_survey.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r_dup.status_code == 201
dup_id = r_dup.json()["id"]
assert dup_id != kml_id, "Duplicate upload must receive unique UUID"

# Verify both exist independently
r_first = client.get(f"/api/files/{kml_id}/")
r_second = client.get(f"/api/files/{dup_id}/")
assert r_first.status_code == 200
assert r_second.status_code == 200
assert r_first.json()["id"] == kml_id
assert r_second.json()["id"] == dup_id
print(f"[PASS] Scenario 6 (Duplicate Safety): Re-uploaded file received distinct UUIDs ({kml_id} != {dup_id}) without cross-contamination")


# ==============================================================================
# 7. SCENARIO 7: TEMPORARY FILE CLEANUP (G)
# ==============================================================================
print("\n--- 7. TEMPORARY FILE CLEANUP ---")
# Verify that no leftover extraction directories exist in system temp
import glob
temp_extract_dirs = glob.glob(os.path.join(tempfile.gettempdir(), "shp_extract_*"))
assert len(temp_extract_dirs) == 0, f"Found leftover extraction directories: {temp_extract_dirs}"

# Verify that successful files exist in STORAGE_DIR / file_id
assert (STORAGE_DIR / kml_id).exists()
assert (STORAGE_DIR / kml_id / "survey_cad.kml").exists()
assert (STORAGE_DIR / shp_id).exists()
print("[PASS] Scenario 7 (Temporary File Cleanup): All shp_extract_* directories cleaned up; managed uploads securely stored")


# ==============================================================================
# 8. SCENARIO 8: TRANSACTION ROLLBACK & CLEANUP ON PARSER FAILURE (E, G, H)
# ==============================================================================
print("\n--- 8. TRANSACTION ROLLBACK & CLEANUP ON PARSER FAILURE ---")
# Malformed file (bad ZIP header / content)
pre_count = 0
with SessionLocal() as db:
    pre_count = db.execute(select(func.count(FileRecord.id))).scalar()

r_corrupt = client.post(
    "/api/files/",
    files={"file": ("corrupt.zip", b"PK\x03\x04randomjunknotazip", "application/zip")}
)
assert r_corrupt.status_code == 400
assert r_corrupt.json()["error"] == "MalformedFileException"

# Check database has NO partial records added
with SessionLocal() as db:
    post_count = db.execute(select(func.count(FileRecord.id))).scalar()
    assert post_count == pre_count, "Failed upload must not leave rows in database"

print("[PASS] Scenario 8 (Rollback & Failure Isolation): Failed upload resulted in 0 database changes and clean error note")


# ==============================================================================
# 9. SCENARIO 9: OVERSIZED UPLOAD PROTECTION (HTTP 413) (O)
# ==============================================================================
print("\n--- 9. OVERSIZED UPLOAD PROTECTION (HTTP 413) ---")
# Create an oversized payload exceeding 25 MB (e.g. 26 MB)
oversized_len = 26 * 1024 * 1024
oversized_stream = io.BytesIO(b"PK\x03\x04" + b"X" * (oversized_len - 4))

storage_dirs_before = set(os.listdir(STORAGE_DIR))

r_oversized = client.post(
    "/api/files/",
    files={"file": ("too_large.zip", oversized_stream, "application/zip")}
)
assert r_oversized.status_code == 413, f"Expected 413, got {r_oversized.status_code}: {r_oversized.text}"
assert r_oversized.json()["error"] == "FileTooLargeException"
assert "exceeds maximum limit of 25 mb" in r_oversized.json()["detail"].lower()

# Verify zero leftover files in storage
storage_dirs_after = set(os.listdir(STORAGE_DIR))
assert storage_dirs_after == storage_dirs_before, "Oversized upload left behind directory in storage!"

# Verify zero rows added to DB
with SessionLocal() as db:
    post_oversized_count = db.execute(select(func.count(FileRecord.id))).scalar()
    assert post_oversized_count == pre_count
print("[PASS] Scenario 9 (Oversized Upload): File > 25MB rejected with HTTP 413, 0 storage leakage, 0 database rows")


# ==============================================================================
# 10. SCENARIO 10: NUMERIC & SERIALIZATION INTEGRITY (L)
# ==============================================================================
print("\n--- 10. NUMERIC & SERIALIZATION INTEGRITY ---")
for meas_item in kml_meas["measurements"]:
    if meas_item["measurement"] is not None:
        val = meas_item["measurement"]["value"]
        assert isinstance(val, (int, float))
        assert math.isfinite(val)
        assert not math.isnan(val)
        assert not math.isinf(val)
        assert val >= 0.0
        # Precision check: float with rounded value
        assert round(val, 4) == val
print("[PASS] Scenario 10 (Numeric Integrity): Values are strictly finite, non-NaN, non-inf, non-negative, and properly rounded")


# ==============================================================================
# 11. SCENARIO 11: END-TO-END SECURITY AUDIT & LEAK DEFENSE (M)
# ==============================================================================
print("\n--- 11. END-TO-END SECURITY AUDIT ---")
# 1. XXE Attack
r_xxe = client.post("/api/files/", files={"file": ("xxe.kml", b"<?xml version=\"1.0\"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><kml>&xxe;</kml>", "application/vnd.google-earth.kml+xml")})
assert r_xxe.status_code == 400
assert "xxe" not in r_xxe.text.lower() or "disallowed" in r_xxe.text.lower() or "security" in r_xxe.text.lower()

# 2. SSRF Attack
r_ssrf = client.post("/api/files/", files={"file": ("ssrf.kml", b"<?xml version=\"1.0\"?><kml><NetworkLink><Link><href>http://169.254.169.254/meta</href></Link></NetworkLink></kml>", "application/vnd.google-earth.kml+xml")})
assert r_ssrf.status_code == 400
assert "external network link" in r_ssrf.json()["detail"].lower()

# 3. Zip-Slip Attack
buf_slip = io.BytesIO()
with zipfile.ZipFile(buf_slip, "w") as zf:
    zf.writestr("../../etc/shadow", "evil")
r_slip = client.post("/api/files/", files={"file": ("slip.zip", buf_slip.getvalue(), "application/zip")})
assert r_slip.status_code == 400
assert "zip-slip" in r_slip.json()["detail"].lower()

# 4. Zero Path / SQL Leakage
for resp in [r_corrupt, r_oversized, r_xxe, r_ssrf, r_slip]:
    assert "c:\\" not in resp.text.lower(), f"Leaked Windows path: {resp.text}"
    assert "/tmp" not in resp.text.lower(), f"Leaked tmp path: {resp.text}"
    assert "traceback" not in resp.text.lower(), f"Leaked traceback: {resp.text}"
    assert "select " not in resp.text.lower(), f"Leaked SQL: {resp.text}"

print("[PASS] Scenario 11 (Security Audit): Zero XXE/SSRF/Zip-Slip compromises; zero filesystem path, SQL query, or traceback leakage")

print("\n" + "=" * 70)
print(">>> ALL PART 6 END-TO-END PIPELINE SCENARIOS PASSED WITH ZERO FAILURES! <<<")
print("=" * 70)
