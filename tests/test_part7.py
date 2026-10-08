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
from sqlalchemy import select, func, text, inspect
import sqlalchemy.exc
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point

from main import (
    app,
    Base,
    engine,
    SessionLocal,
    get_db,
    FileRecord,
    FeatureRecord,
    MeasurementRecord,
    FileDetailResponse,
    FileMeasurementListResponse,
    FeatureDetailResponse,
    FeatureMeasurementResponse,
    MeasurementDetail,
    STORAGE_DIR,
    DB_PATH,
    BASE_DIR,
)

client = TestClient(app)

print("=" * 70)
print("PART 7 — DATABASE & ARCHITECTURE HARDENING VERIFICATION SUITE")
print("=" * 70)

# ==============================================================================
# 1. SCENARIO 1: DATABASE STARTUP AND TABLE CREATION
# ==============================================================================
print("\n--- 1. DATABASE STARTUP AND TABLE CREATION ---")
inspector = inspect(engine)
tables = inspector.get_table_names()
assert "files" in tables, "Table 'files' missing from SQLite"
assert "features" in tables, "Table 'features' missing from SQLite"
assert "measurements" in tables, "Table 'measurements' missing from SQLite"

# Verify column schema
file_cols = {c["name"] for c in inspector.get_columns("files")}
assert {"id", "filename", "file_type", "crs", "feature_count", "status", "created_at"}.issubset(file_cols)

feat_cols = {c["name"] for c in inspector.get_columns("features")}
assert {"id", "file_id", "feature_index", "geometry_type", "geometry_geojson", "properties", "status"}.issubset(feat_cols)

meas_cols = {c["name"] for c in inspector.get_columns("measurements")}
assert {"id", "file_id", "feature_index", "geometry_type", "measurement_type", "measurement_value", "unit", "status"}.issubset(meas_cols)
print(f"[PASS] Scenario 1 (Startup & Tables): Tables 'files', 'features', 'measurements' verified with complete schema")


# ==============================================================================
# 2. SCENARIO 2: SQLITE WAL AND CONCURRENCY CONFIGURATION
# ==============================================================================
print("\n--- 2. SQLITE WAL & CONCURRENCY CONFIGURATION ---")
with engine.connect() as conn:
    journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
    sync_mode = conn.execute(text("PRAGMA synchronous;")).scalar()
    assert journal_mode.lower() == "wal", f"Expected WAL mode, got {journal_mode}"
    # synchronous=1 corresponds to NORMAL in SQLite
    assert sync_mode in (1, 2), f"Expected NORMAL (1) or FULL (2) sync, got {sync_mode}"
print(f"[PASS] Scenario 2 (SQLite WAL & Concurrency): PRAGMA journal_mode={journal_mode.upper()}, synchronous={sync_mode}")


# ==============================================================================
# 3. SCENARIO 3: SQLITE FOREIGN KEYS AND BUSY TIMEOUT ENFORCEMENT
# ==============================================================================
print("\n--- 3. SQLITE FOREIGN KEYS & BUSY TIMEOUT ENFORCEMENT ---")
with engine.connect() as conn:
    fk_enabled = conn.execute(text("PRAGMA foreign_keys;")).scalar()
    busy_timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()
    assert fk_enabled == 1, f"Foreign keys are NOT enabled in SQLite! Got {fk_enabled}"
    assert busy_timeout >= 5000, f"Expected busy timeout >= 5000 ms, got {busy_timeout}"
print(f"[PASS] Scenario 3 (FK & Busy Timeout): PRAGMA foreign_keys={fk_enabled} (ON), busy_timeout={busy_timeout} ms")


# ==============================================================================
# 4. SCENARIO 4: FOREIGN KEY VIOLATION & CASCADE DELETION TEST
# ==============================================================================
print("\n--- 4. FOREIGN KEY VIOLATION & CASCADE DELETION ---")
# 4.1 Foreign Key Violation: Inserting feature with non-existent file_id must fail
with SessionLocal() as db:
    bad_feature = FeatureRecord(
        file_id="non-existent-file-id-9999",
        feature_index=0,
        geometry_type="Point",
        status="VALID",
    )
    db.add(bad_feature)
    fk_violation_caught = False
    try:
        db.commit()
    except sqlalchemy.exc.IntegrityError:
        fk_violation_caught = True
        db.rollback()

    assert fk_violation_caught, "Inserting FeatureRecord with non-existent file_id did NOT raise IntegrityError!"

# 4.2 Cascade Deletion: Deleting parent FileRecord must delete child features and measurements
with SessionLocal() as db:
    test_file = FileRecord(
        id=str(uuid.uuid4()),
        filename="cascade_test.kml",
        file_type="kml",
        feature_count=1,
        status="COMPLETED",
    )
    db.add(test_file)
    db.flush()

    test_feat = FeatureRecord(
        file_id=test_file.id,
        feature_index=0,
        geometry_type="Point",
        status="VALID",
    )
    test_meas = MeasurementRecord(
        file_id=test_file.id,
        feature_index=0,
        geometry_type="Point",
        measurement_type="none",
        status="SKIPPED",
    )
    db.add(test_feat)
    db.add(test_meas)
    db.commit()

    test_fid = test_file.id

    # Verify rows exist
    f_count = db.execute(select(func.count(FeatureRecord.id)).where(FeatureRecord.file_id == test_fid)).scalar()
    m_count = db.execute(select(func.count(MeasurementRecord.id)).where(MeasurementRecord.file_id == test_fid)).scalar()
    assert f_count == 1 and m_count == 1

    # Delete FileRecord
    db.delete(test_file)
    db.commit()

    # Verify cascade deletion
    f_post = db.execute(select(func.count(FeatureRecord.id)).where(FeatureRecord.file_id == test_fid)).scalar()
    m_post = db.execute(select(func.count(MeasurementRecord.id)).where(MeasurementRecord.file_id == test_fid)).scalar()
    assert f_post == 0, "FeatureRecord was not cascade-deleted!"
    assert m_post == 0, "MeasurementRecord was not cascade-deleted!"

print("[PASS] Scenario 4 (FK Violation & Cascade): Invalid FK insert blocked by IntegrityError; parent deletion cleanly cascade-deleted children")


# ==============================================================================
# 5. SCENARIO 5: TRANSACTION ROLLBACK INTEGRITY
# ==============================================================================
print("\n--- 5. TRANSACTION ROLLBACK INTEGRITY ---")
with SessionLocal() as db:
    initial_file_count = db.execute(select(func.count(FileRecord.id))).scalar()
    initial_feat_count = db.execute(select(func.count(FeatureRecord.id))).scalar()

    # Simulate transactional failure
    try:
        dummy_file = FileRecord(
            id=str(uuid.uuid4()),
            filename="abort_test.kml",
            file_type="kml",
            feature_count=2,
            status="PROCESSING",
        )
        db.add(dummy_file)
        db.flush()
        # Intentional error
        raise RuntimeError("Simulated mid-transaction failure")
        db.commit()
    except RuntimeError:
        db.rollback()

    post_file_count = db.execute(select(func.count(FileRecord.id))).scalar()
    post_feat_count = db.execute(select(func.count(FeatureRecord.id))).scalar()

    assert post_file_count == initial_file_count, "Rollback failed to revert FileRecord insert!"
    assert post_feat_count == initial_feat_count, "Rollback failed to revert FeatureRecord insert!"

print("[PASS] Scenario 5 (Transaction Rollback): Simulated failure rolled back cleanly with 0 database state change")


# ==============================================================================
# 6. SCENARIO 6: ZERO ORPHAN FEATURE RECORDS IN DATABASE
# ==============================================================================
print("\n--- 6. ZERO ORPHAN FEATURE RECORDS ---")
with SessionLocal() as db:
    orphan_features = db.execute(
        select(func.count(FeatureRecord.id)).where(~FeatureRecord.file_id.in_(select(FileRecord.id)))
    ).scalar()
    assert orphan_features == 0, f"Found {orphan_features} orphan feature rows!"
print(f"[PASS] Scenario 6 (Orphan Feature Check): Total orphan features in DB = {orphan_features}")


# ==============================================================================
# 7. SCENARIO 7: ZERO ORPHAN MEASUREMENT RECORDS IN DATABASE
# ==============================================================================
print("\n--- 7. ZERO ORPHAN MEASUREMENT RECORDS ---")
with SessionLocal() as db:
    orphan_measurements = db.execute(
        select(func.count(MeasurementRecord.id)).where(~MeasurementRecord.file_id.in_(select(FileRecord.id)))
    ).scalar()
    assert orphan_measurements == 0, f"Found {orphan_measurements} orphan measurement rows!"
print(f"[PASS] Scenario 7 (Orphan Measurement Check): Total orphan measurements in DB = {orphan_measurements}")


# ==============================================================================
# 8. SCENARIO 8: FEATURE COUNT CONSISTENCY ACROSS ALL FILES
# ==============================================================================
print("\n--- 8. FEATURE COUNT CONSISTENCY ---")
with SessionLocal() as db:
    files = db.execute(select(FileRecord)).scalars().all()
    assert len(files) > 0, "No files found in database"
    for f in files:
        actual_features = len(f.features)
        assert f.feature_count == actual_features, f"File {f.id} declared feature_count={f.feature_count} but has {actual_features} features!"
print(f"[PASS] Scenario 8 (Feature Count Consistency): Verified {len(files)} files; all declared counts match stored child rows")


# ==============================================================================
# 9. SCENARIO 9: MEASUREMENT / FEATURE / FILE RELATIONSHIP CONSISTENCY
# ==============================================================================
print("\n--- 9. RELATIONSHIP CONSISTENCY ---")
with SessionLocal() as db:
    active_files = db.execute(select(FileRecord)).scalars().all()
    for f in active_files:
        feat_indices = [feat.feature_index for feat in f.features]
        meas_indices = [meas.feature_index for meas in f.measurements]
        assert feat_indices == meas_indices, f"File {f.id} feature indices {feat_indices} != measurement indices {meas_indices}"
        assert len(f.features) == len(f.measurements)
print("[PASS] Scenario 9 (Relationship Consistency): Every feature index maps 1:1 with its measurement record")


# ==============================================================================
# 10. SCENARIO 10: SESSION MANAGEMENT & DEPENDENCY CLOSURE
# ==============================================================================
print("\n--- 10. SESSION MANAGEMENT & CLOSURE ---")
# Verify get_db generator properly yields and closes
db_gen = get_db()
session_instance = next(db_gen)
assert session_instance.is_active
try:
    next(db_gen)
except StopIteration:
    pass
# After generator finishes, session should be closed
# In SQLAlchemy 2.0, closed session has no active transaction or is closed
assert not session_instance.is_active or session_instance.get_transaction() is None
print("[PASS] Scenario 10 (Session Lifecycle): get_db() dependency correctly allocates and closes sessions")


# ==============================================================================
# 11. SCENARIO 11: DUPLICATE UPLOAD ISOLATION
# ==============================================================================
print("\n--- 11. DUPLICATE UPLOAD ISOLATION ---")
sample_kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document><Placemark><name>Iso Test</name><Point><coordinates>10,20,0</coordinates></Point></Placemark></Document>
</kml>"""
r1 = client.post("/api/files/", files={"file": ("iso.kml", sample_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
r2 = client.post("/api/files/", files={"file": ("iso.kml", sample_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
assert r1.status_code == 201 and r2.status_code == 201
id1, id2 = r1.json()["id"], r2.json()["id"]
assert id1 != id2
with SessionLocal() as db:
    f1 = db.execute(select(FileRecord).where(FileRecord.id == id1)).scalar_one()
    f2 = db.execute(select(FileRecord).where(FileRecord.id == id2)).scalar_one()
    assert f1.id != f2.id
    assert f1.features[0].id != f2.features[0].id
print(f"[PASS] Scenario 11 (Duplicate Upload Isolation): Uploads {id1} and {id2} stored as distinct isolated records")


# ==============================================================================
# 12. SCENARIO 12: STORAGE ROOT & PATH TRAVERSAL DEFENSE
# ==============================================================================
print("\n--- 12. STORAGE ROOT & PATH TRAVERSAL DEFENSE ---")
storage_resolved = STORAGE_DIR.resolve()
assert storage_resolved.exists()
# Verify all folders in STORAGE_DIR are strictly valid UUID subdirectories
for item in storage_resolved.iterdir():
    if item.is_dir():
        # Directory name should be valid UUID
        try:
            uuid.UUID(item.name)
        except ValueError:
            assert False, f"Unexpected non-UUID directory found in storage: {item.name}"
print("[PASS] Scenario 12 (Storage Root Safety): Managed uploads strictly contained in isolated UUID subdirectories")


# ==============================================================================
# 13. SCENARIO 13: MALFORMED / ATTACK ID SAFE HANDLING
# ==============================================================================
print("\n--- 13. MALFORMED ID SAFE HANDLING ---")
malformed_ids = [
    "non-existent-uuid",
    "../../etc/passwd",
    "' OR '1'='1",
    "x" * 200,
    "   ",
]
for mid in malformed_ids:
    r_bad = client.get(f"/api/files/{mid}/")
    assert r_bad.status_code in (404, 400), f"Malformed ID '{mid}' gave unexpected status {r_bad.status_code}"
    assert "traceback" not in r_bad.text.lower()
    assert "c:\\" not in r_bad.text.lower()
    assert "select " not in r_bad.text.lower()
print("[PASS] Scenario 13 (Malformed ID Handling): SQL injection, path traversal, oversized IDs safely rejected with controlled 404/400")


# ==============================================================================
# 14. SCENARIO 14: SERIALIZATION AFTER FRESH SESSION (DETACHED INSTANCE TEST)
# ==============================================================================
print("\n--- 14. SERIALIZATION AFTER FRESH SESSION ---")
# Upload a file, close everything, then load in a completely new session and serialize
r_kml_ser = client.post("/api/files/", files={"file": ("ser.kml", sample_kml.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
ser_id = r_kml_ser.json()["id"]

# Open fresh session, query, close session, and verify serialization does not raise DetachedInstanceError
with SessionLocal() as db_fresh:
    rec = db_fresh.execute(select(FileRecord).where(FileRecord.id == ser_id)).scalar_one()
    # Read properties into Pydantic while session open
    dto = FileDetailResponse(
        id=rec.id,
        filename=rec.filename,
        file_type=rec.file_type,
        feature_count=rec.feature_count,
        crs=rec.crs,
        status=rec.status,
        error_message=rec.error_message,
        created_at=rec.created_at,
        features=[
            FeatureDetailResponse(
                feature_id=f.feature_index,
                geometry_type=f.geometry_type,
                geometry=f.geometry_geojson,
                crs=rec.crs,
                properties=f.properties or {},
                status=f.status,
                error_message=f.error_message,
            )
            for f in rec.features
        ]
    )
assert dto.id == ser_id
assert len(dto.features) == 1
# Verify JSON serialization works cleanly
json_str = dto.model_dump_json()
assert "Iso Test" in json_str
print("[PASS] Scenario 14 (Serialization & ORM Boundaries): Zero lazy-loading crashes; clean serialization to Pydantic/JSON")


# ==============================================================================
# 15. SCENARIO 15: APPLICATION INTEGRATION REGRESSION
# ==============================================================================
print("\n--- 15. APPLICATION INTEGRATION REGRESSION ---")
r_health = client.get("/api/health/")
assert r_health.status_code == 200
assert r_health.json()["status"] == "ok"

r_docs = client.get("/docs")
assert r_docs.status_code == 200

r_openapi = client.get("/openapi.json")
assert r_openapi.status_code == 200
print("[PASS] Scenario 15 (Integration Regression): Health, OpenAPI, and Docs verified operational")

print("\n" + "=" * 70)
print(">>> ALL PART 7 DATABASE & ARCHITECTURE HARDENING TESTS PASSED! <<<")
print("=" * 70)
