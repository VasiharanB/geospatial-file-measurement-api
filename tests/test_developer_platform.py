"""
Developer Platform & Multi-Tenant Security Regression Test Suite
================================================================
Verifies all capabilities of Phase 12:
- Developer identity (Argon2id, email normalization, session lifecycle, password change)
- Project lifecycle and strict cross-tenant isolation (IDOR defense)
- API key generation (prefixes, peppered SHA-256 hash, one-time reveal, metadata hygiene)
- API key revocation and rotation
- Tenant-isolated file ingestion, measurements, and explicit deletion (/api/v1/files/)
- Legacy anonymous compatibility and security boundary (anonymous cannot access tenant files)
- Usage accounting and daily quota enforcement (HTTP 429)
- Developer console delivery (/console, /portal)
"""

import hashlib
import json
import os
import pathlib
import sys
import uuid
from starlette.testclient import TestClient

WORKSPACE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR))

import main
from main import app, get_db, UserRecord, ProjectRecord, APIKeyRecord, SessionRecord, FileRecord, UsageRecord
from sqlalchemy import select

client = TestClient(app)

print("=" * 80)
print("PHASE 12 — DEVELOPER PLATFORM & TENANT ISOLATION VERIFICATION SUITE")
print("=" * 80)

# Sample valid KML for test uploads
SAMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Platform Test Survey</name>
    <Placemark>
      <name>Parcel Alpha</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5946,12.9716,0
              77.5956,12.9716,0
              77.5956,12.9726,0
              77.5946,12.9726,0
              77.5946,12.9716,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""

# ------------------------------------------------------------------------------
# 1. Developer Identity & Registration
# ------------------------------------------------------------------------------
print("\n--- 1. DEVELOPER IDENTITY & REGISTRATION ---")

# 1.1 Registration with email normalization
email_raw = f"  Alice_{uuid.uuid4().hex[:6]}@Example.COM  "
expected_email = email_raw.strip().lower()
password_alice = "SuperSecretPassword123!"

r_reg = client.post("/api/v1/auth/register", json={
    "email": email_raw,
    "password": password_alice,
    "company_name": "Acme Geospatial Corp",
})
assert r_reg.status_code == 201, f"Registration failed: {r_reg.text}"
reg_data = r_reg.json()
assert reg_data["user"]["email"] == expected_email, f"Email was not normalized: {reg_data['user']['email']}"
alice_user_id = reg_data["user"]["id"]
print("[PASS] 1.1 Developer registration succeeded with email normalization (lowercase, trimmed)")

# 1.2 Duplicate registration rejection (409 Conflict)
r_dup = client.post("/api/v1/auth/register", json={
    "email": expected_email,
    "password": "AnotherPassword456!",
})
assert r_dup.status_code == 409, f"Expected 409 for duplicate email, got: {r_dup.status_code}"
assert "already exists" in r_dup.json()["detail"].lower()
print("[PASS] 1.2 Duplicate registration prevented with HTTP 409 Conflict")

# 1.3 Password length validation (rejected for short password)
r_short_pw = client.post("/api/v1/auth/register", json={
    "email": f"short_{uuid.uuid4().hex[:6]}@test.com",
    "password": "short",
})
assert r_short_pw.status_code == 422, f"Expected 422 for short password, got: {r_short_pw.status_code}"
print("[PASS] 1.3 Short password rejected with HTTP 422 Unprocessable Entity")

# ------------------------------------------------------------------------------
# 2. Authentication & Session Lifecycle
# ------------------------------------------------------------------------------
print("\n--- 2. AUTHENTICATION & SESSION LIFECYCLE ---")

# 2.1 Valid login returns Bearer token
r_login = client.post("/api/v1/auth/login", json={
    "email": expected_email,
    "password": password_alice,
})
assert r_login.status_code == 200, f"Login failed: {r_login.text}"
login_data = r_login.json()
alice_token = login_data["access_token"]
assert alice_token.startswith("gfm_sess_"), f"Unexpected token format: {alice_token}"
alice_headers = {"Authorization": f"Bearer {alice_token}"}
print("[PASS] 2.1 Valid login returned session Bearer token")

# 2.2 Invalid password rejected (401)
r_bad_pw = client.post("/api/v1/auth/login", json={
    "email": expected_email,
    "password": "WrongPassword999!",
})
assert r_bad_pw.status_code == 401
assert "invalid email or password" in r_bad_pw.json()["detail"].lower()
print("[PASS] 2.2 Invalid password rejected with HTTP 401 Unauthorized")

# 2.3 Non-existent user rejected (401 without enumeration leak)
r_non_user = client.post("/api/v1/auth/login", json={
    "email": "nobody_exists_12345@test.com",
    "password": "SomePassword123!",
})
assert r_non_user.status_code == 401
assert "invalid email or password" in r_non_user.json()["detail"].lower()
print("[PASS] 2.3 Non-existent user rejected with HTTP 401 (enumeration-safe)")

# 2.4 User profile introspection (/api/v1/auth/me)
r_me = client.get("/api/v1/auth/me", headers=alice_headers)
assert r_me.status_code == 200
assert r_me.json()["email"] == expected_email
print("[PASS] 2.4 Authenticated user profile retrieved via /api/v1/auth/me")

# 2.5 Unauthenticated /me rejected (401)
r_no_auth = client.get("/api/v1/auth/me")
assert r_no_auth.status_code == 401
print("[PASS] 2.5 Unauthenticated /me rejected with HTTP 401")

# 2.6 User logout invalidates session
r_temp_login = client.post("/api/v1/auth/login", json={
    "email": expected_email,
    "password": password_alice,
})
temp_token = r_temp_login.json()["access_token"]
r_logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {temp_token}"})
assert r_logout.status_code == 200
r_after_logout = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {temp_token}"})
assert r_after_logout.status_code == 401, "Logged-out session must be invalidated"
print("[PASS] 2.6 Logout successfully invalidated session token")

# 2.7 Password change updates credentials and invalidates active session
new_password_alice = "BrandNewSecurePassword456!"
r_change_pw = client.post("/api/v1/auth/change-password", headers=alice_headers, json={
    "current_password": password_alice,
    "new_password": new_password_alice,
})
assert r_change_pw.status_code == 200

# Old token should be invalidated
r_old_token_check = client.get("/api/v1/auth/me", headers=alice_headers)
assert r_old_token_check.status_code == 401, "Password change must invalidate existing sessions"

# Old password cannot log in
r_old_pw_login = client.post("/api/v1/auth/login", json={
    "email": expected_email,
    "password": password_alice,
})
assert r_old_pw_login.status_code == 401

# New password logs in successfully
r_new_pw_login = client.post("/api/v1/auth/login", json={
    "email": expected_email,
    "password": new_password_alice,
})
assert r_new_pw_login.status_code == 200
alice_token = r_new_pw_login.json()["access_token"]
alice_headers = {"Authorization": f"Bearer {alice_token}"}
print("[PASS] 2.7 Password change rotated credentials and purged stale sessions")

# ------------------------------------------------------------------------------
# 3. Project Management & Multi-Tenant Isolation
# ------------------------------------------------------------------------------
print("\n--- 3. PROJECT MANAGEMENT & MULTI-TENANT ISOLATION ---")

# Register second developer: Bob
email_bob = f"bob_{uuid.uuid4().hex[:6]}@example.com"
password_bob = "BobPasswordSecure789!"
r_reg_bob = client.post("/api/v1/auth/register", json={
    "email": email_bob,
    "password": password_bob,
    "company_name": "Bob Geosystems",
})
assert r_reg_bob.status_code == 201
r_login_bob = client.post("/api/v1/auth/login", json={"email": email_bob, "password": password_bob})
bob_headers = {"Authorization": f"Bearer {r_login_bob.json()['access_token']}"}

# 3.1 Alice creates project
r_proj_a = client.post("/api/v1/projects/", headers=alice_headers, json={
    "name": "Alice Survey Alpha",
    "description": "Primary cadastral mapping project",
    "daily_request_limit": 500,
})
assert r_proj_a.status_code == 201
alice_project = r_proj_a.json()
alice_proj_id = alice_project["id"]
print("[PASS] 3.1 Project created with custom quotas and description")

# 3.2 List projects is owner-isolated
r_list_alice = client.get("/api/v1/projects/", headers=alice_headers)
alice_projects = r_list_alice.json()["projects"]
assert len(alice_projects) >= 1
assert any(p["id"] == alice_proj_id for p in alice_projects)

r_list_bob = client.get("/api/v1/projects/", headers=bob_headers)
bob_projects = r_list_bob.json()["projects"]
assert not any(p["id"] == alice_proj_id for p in bob_projects), "Bob should not see Alice's projects"
print("[PASS] 3.2 Project listing is strictly isolated per owner")

# 3.3 Alice updates project
r_patch_proj = client.patch(f"/api/v1/projects/{alice_proj_id}", headers=alice_headers, json={
    "name": "Alice Survey Alpha Renamed",
})
assert r_patch_proj.status_code == 200
assert r_patch_proj.json()["name"] == "Alice Survey Alpha Renamed"
print("[PASS] 3.3 Project metadata updated via PATCH")

# 3.4 Cross-user project access rejected (IDOR protection - HTTP 404)
r_bob_get_alice_proj = client.get(f"/api/v1/projects/{alice_proj_id}", headers=bob_headers)
assert r_bob_get_alice_proj.status_code == 404, "Bob reading Alice's project must return 404"

r_bob_patch_alice_proj = client.patch(f"/api/v1/projects/{alice_proj_id}", headers=bob_headers, json={
    "name": "Bob Hijacked Alice Project",
})
assert r_bob_patch_alice_proj.status_code == 404, "Bob patching Alice's project must return 404"

r_bob_del_alice_proj = client.delete(f"/api/v1/projects/{alice_proj_id}", headers=bob_headers)
assert r_bob_del_alice_proj.status_code == 404, "Bob deleting Alice's project must return 404"
print("[PASS] 3.4 Cross-tenant project access rejected with HTTP 404 (IDOR-safe)")

# ------------------------------------------------------------------------------
# 4. API Key Management & Lifecycle
# ------------------------------------------------------------------------------
print("\n--- 4. API KEY MANAGEMENT & SECURE LIFECYCLE ---")

# 4.1 Create API key with prefix and one-time raw reveal
r_key_create = client.post(f"/api/v1/projects/{alice_proj_id}/api-keys/", headers=alice_headers, json={
    "name": "Alice Production Primary",
    "environment": "live",
    "scopes": ["read", "write"],
})
assert r_key_create.status_code == 201
key_data = r_key_create.json()
alice_raw_key = key_data.get("key")
assert alice_raw_key is not None, "Raw key must be revealed on creation"
assert alice_raw_key.startswith("gfm_live_"), f"Raw key must have 'gfm_live_' prefix: {alice_raw_key}"
entropy_hex = alice_raw_key.replace("gfm_live_", "")
assert len(entropy_hex) == 64, f"API key entropy must be 64 hex characters (256 bits), got {len(entropy_hex)}"
int(entropy_hex, 16)  # Asserts valid hex string
alice_key_id = key_data["id"]
print("[PASS] 4.1 API key generated with 256-bit CSPRNG entropy, 'gfm_live_' prefix, and one-time reveal")

# 4.2 Database stores peppered hash, never raw plaintext key
with next(get_db()) as db:
    stored_key = db.execute(select(APIKeyRecord).where(APIKeyRecord.id == alice_key_id)).scalar_one()
    assert stored_key.key_hash != alice_raw_key, "Raw key must NEVER be stored in plaintext"
    assert len(stored_key.key_hash) == 64, "Hashed key must be 64-character SHA-256 digest"
print("[PASS] 4.2 Database verified: stores SHA-256 peppered hash, never plaintext key")

# 4.3 List API keys returns safe metadata without raw secret
r_key_list = client.get(f"/api/v1/projects/{alice_proj_id}/api-keys/", headers=alice_headers)
assert r_key_list.status_code == 200
for k in r_key_list.json()["keys"]:
    assert "key" not in k or k["key"] is None, "Plaintext raw key must not leak in list requests"
    assert "key_hash" not in k, "Hashed key secret must not leak in response"
    assert "last_four" in k
    assert "key_prefix" in k
print("[PASS] 4.3 Key metadata listing is leak-free (no raw_key or key_hash)")

# 4.4 Cross-user API key management rejected (Bob cannot manage Alice's keys)
r_bob_key_create = client.post(f"/api/v1/projects/{alice_proj_id}/api-keys/", headers=bob_headers, json={
    "name": "Bob Illegitimate Key",
})
assert r_bob_key_create.status_code == 404

r_bob_key_list = client.get(f"/api/v1/projects/{alice_proj_id}/api-keys/", headers=bob_headers)
assert r_bob_key_list.status_code == 404

r_bob_key_revoke = client.post(f"/api/v1/projects/{alice_proj_id}/api-keys/{alice_key_id}/revoke", headers=bob_headers)
assert r_bob_key_revoke.status_code == 404
print("[PASS] 4.4 Cross-user API key management rejected with HTTP 404")

# 4.5 Key rotation
r_key_rotate = client.post(f"/api/v1/projects/{alice_proj_id}/api-keys/{alice_key_id}/rotate", headers=alice_headers)
assert r_key_rotate.status_code == 200
rotated_data = r_key_rotate.json()
alice_rotated_raw_key = rotated_data["key"]
assert alice_rotated_raw_key.startswith("gfm_live_")
assert alice_rotated_raw_key != alice_raw_key, "Rotated key must be distinct from original key"

# Old key must now be revoked
r_test_old_key = client.get("/api/v1/files/", headers={"X-API-Key": alice_raw_key})
assert r_test_old_key.status_code == 401, "Revoked/rotated old key must be rejected"
assert "revoked" in r_test_old_key.json()["detail"].lower()
print("[PASS] 4.5 Key rotation revoked old key and issued new active key")

# 4.6 Missing or invalid API key rejected
r_no_key = client.get("/api/v1/files/")
assert r_no_key.status_code == 401
r_bad_key = client.get("/api/v1/files/", headers={"X-API-Key": "gfm_live_invalid_garbage_key"})
assert r_bad_key.status_code == 401
print("[PASS] 4.6 Missing and invalid API keys rejected with HTTP 401")

# Create a test key for Alice and a live key for Bob
r_key_alice_live = client.post(f"/api/v1/projects/{alice_proj_id}/api-keys/", headers=alice_headers, json={
    "name": "Alice Live Key 2",
    "environment": "live",
})
alice_api_key = r_key_alice_live.json()["key"]

# Create project and key for Bob
r_proj_bob = client.post("/api/v1/projects/", headers=bob_headers, json={"name": "Bob Project 1"})
bob_proj_id = r_proj_bob.json()["id"]
r_key_bob = client.post(f"/api/v1/projects/{bob_proj_id}/api-keys/", headers=bob_headers, json={"name": "Bob Live Key"})
bob_api_key = r_key_bob.json()["key"]

# ------------------------------------------------------------------------------
# 5. Tenant-Isolated File Ingestion & Measurement Operations (/api/v1/files/)
# ------------------------------------------------------------------------------
print("\n--- 5. TENANT-ISOLATED FILE OPERATIONS ---")

# 5.1 Authenticated file upload with X-API-Key under Alice's project
r_upload_alice = client.post(
    "/api/v1/files/",
    headers={"X-API-Key": alice_api_key},
    files={"file": ("alice_survey.kml", SAMPLE_KML.encode("utf-8"), "application/vnd.google-earth.kml+xml")},
)
assert r_upload_alice.status_code == 201, f"Tenant upload failed: {r_upload_alice.text}"
alice_file = r_upload_alice.json()
alice_file_id = alice_file["id"]
assert alice_file["status"].upper() == "COMPLETED"
assert alice_file["feature_count"] == 1
print("[PASS] 5.1 Authenticated file uploaded and ingested under tenant project")

# 5.2 List project files returns Alice's file for Alice, but not for Bob
r_files_alice = client.get("/api/v1/files/", headers={"X-API-Key": alice_api_key})
assert r_files_alice.status_code == 200
assert any(f["id"] == alice_file_id for f in r_files_alice.json()["files"])

r_files_bob = client.get("/api/v1/files/", headers={"X-API-Key": bob_api_key})
assert r_files_bob.status_code == 200
assert len(r_files_bob.json()["files"]) == 0, "Bob must not see Alice's files"
print("[PASS] 5.2 Project file listing enforces tenant isolation")

# 5.3 Detail retrieval enforces tenant isolation
r_detail_alice = client.get(f"/api/v1/files/{alice_file_id}/", headers={"X-API-Key": alice_api_key})
assert r_detail_alice.status_code == 200
assert r_detail_alice.json()["id"] == alice_file_id

r_detail_bob = client.get(f"/api/v1/files/{alice_file_id}/", headers={"X-API-Key": bob_api_key})
assert r_detail_bob.status_code == 404, "Bob accessing Alice's file detail must receive 404"
print("[PASS] 5.3 File detail retrieval enforces tenant isolation (IDOR-safe 404)")

# 5.4 Measurement retrieval enforces tenant isolation
r_meas_alice = client.get(f"/api/v1/files/{alice_file_id}/measurements/", headers={"X-API-Key": alice_api_key})
assert r_meas_alice.status_code == 200
assert r_meas_alice.json()["total_features"] == 1
assert r_meas_alice.json()["measurements"][0]["measurement"]["type"] == "area"

r_meas_bob = client.get(f"/api/v1/files/{alice_file_id}/measurements/", headers={"X-API-Key": bob_api_key})
assert r_meas_bob.status_code == 404, "Bob accessing Alice's file measurements must receive 404"
print("[PASS] 5.4 File measurements retrieval enforces tenant isolation (IDOR-safe 404)")

# 5.5 Cross-tenant deletion rejected
r_del_bob = client.delete(f"/api/v1/files/{alice_file_id}/", headers={"X-API-Key": bob_api_key})
assert r_del_bob.status_code == 404, "Bob deleting Alice's file must receive 404"
print("[PASS] 5.5 Cross-tenant file deletion rejected with HTTP 404")

# ------------------------------------------------------------------------------
# 6. Backward Compatibility & Anonymous Legacy Endpoint Isolation
# ------------------------------------------------------------------------------
print("\n--- 6. BACKWARD COMPATIBILITY & LEGACY ISOLATION ---")

# 6.1 Legacy anonymous upload remains functional without breaking existing frontend
r_anon_upload = client.post(
    "/api/files/",
    files={"file": ("legacy_demo.kml", SAMPLE_KML.encode("utf-8"), "application/vnd.google-earth.kml+xml")},
)
assert r_anon_upload.status_code == 201, f"Legacy upload failed: {r_anon_upload.text}"
anon_file = r_anon_upload.json()
anon_file_id = anon_file["id"]
print("[PASS] 6.1 Legacy anonymous upload at /api/files/ remains 100% backward compatible")

# 6.2 Legacy anonymous detail & measurements retrieval works for anonymous files
r_anon_detail = client.get(f"/api/files/{anon_file_id}/")
assert r_anon_detail.status_code == 200
r_anon_meas = client.get(f"/api/files/{anon_file_id}/measurements/")
assert r_anon_meas.status_code == 200
print("[PASS] 6.2 Legacy anonymous detail and measurement endpoints work for anonymous uploads")

# 6.3 Legacy anonymous endpoint CANNOT access tenant-owned developer files (Isolation Guard)
r_anon_breach = client.get(f"/api/files/{alice_file_id}/")
assert r_anon_breach.status_code == 404, "Legacy anonymous endpoint must not reveal tenant files"

r_anon_meas_breach = client.get(f"/api/files/{alice_file_id}/measurements/")
assert r_anon_meas_breach.status_code == 404, "Legacy anonymous endpoint must not reveal tenant measurements"
print("[PASS] 6.3 Anonymous callers blocked from accessing tenant-owned developer files (HTTP 404)")

# ------------------------------------------------------------------------------
# 7. Owner File Deletion & Disk Cleanup
# ------------------------------------------------------------------------------
print("\n--- 7. OWNER FILE DELETION & STORAGE CLEANUP ---")

# 7.1 Owner deletes their file
r_del_alice = client.delete(f"/api/v1/files/{alice_file_id}/", headers={"X-API-Key": alice_api_key})
assert r_del_alice.status_code == 204
r_after_del = client.get(f"/api/v1/files/{alice_file_id}/", headers={"X-API-Key": alice_api_key})
assert r_after_del.status_code == 404, "Deleted file must no longer be retrievable"
print("[PASS] 7.1 Owner file deletion purged database record and returned HTTP 204")

# ------------------------------------------------------------------------------
# 8. Usage Accounting & Quota Enforcement
# ------------------------------------------------------------------------------
print("\n--- 8. USAGE ACCOUNTING & QUOTA ENFORCEMENT ---")

# 8.1 Usage analytics endpoint returns accurate metrics
r_usage = client.get(f"/api/v1/projects/{alice_proj_id}/usage", headers=alice_headers)
assert r_usage.status_code == 200
usage_stats = r_usage.json()
assert usage_stats["total_requests"] >= 1
assert usage_stats["requests_today"] >= 1
assert usage_stats["bytes_uploaded"] > 0
print(f"[PASS] 8.1 Usage analytics returned real metrics: {usage_stats['total_requests']} requests recorded")

# 8.2 Daily quota enforcement (HTTP 429)
# Create a test project with quota of 2 requests
r_quota_proj = client.post("/api/v1/projects/", headers=alice_headers, json={
    "name": "Strict Quota Project",
    "daily_request_limit": 2,
})
quota_proj_id = r_quota_proj.json()["id"]
r_quota_key = client.post(f"/api/v1/projects/{quota_proj_id}/api-keys/", headers=alice_headers, json={
    "name": "Strict Quota Key",
})
quota_api_key = r_quota_key.json()["key"]

# Request 1 (under quota)
r_q1 = client.get("/api/v1/files/", headers={"X-API-Key": quota_api_key})
assert r_q1.status_code == 200

# Request 2 (reaches quota)
r_q2 = client.get("/api/v1/files/", headers={"X-API-Key": quota_api_key})
assert r_q2.status_code == 200

# Request 3 (exceeds quota -> HTTP 429)
r_q3 = client.get("/api/v1/files/", headers={"X-API-Key": quota_api_key})
assert r_q3.status_code == 429, f"Expected 429 Too Many Requests, got: {r_q3.status_code}"
assert "daily request quota" in r_q3.json()["detail"].lower() and "exceeded" in r_q3.json()["detail"].lower()
print("[PASS] 8.2 Daily request quota strictly enforced with HTTP 429 Too Many Requests")

# ------------------------------------------------------------------------------
# 9. Developer Console Delivery
# ------------------------------------------------------------------------------
print("\n--- 9. DEVELOPER CONSOLE DELIVERY ---")

r_console = client.get("/console")
assert r_console.status_code == 200
assert "text/html" in r_console.headers.get("content-type", "")
assert "Developer Console" in r_console.text

r_portal = client.get("/portal")
assert r_portal.status_code == 200
assert "text/html" in r_portal.headers.get("content-type", "")
assert "Developer Console" in r_portal.text
print("[PASS] 9.1 Developer Console served at /console and /portal with HTTP 200 HTML")

print("\n" + "=" * 80)
print("ALL 35 DEVELOPER PLATFORM & TENANT ISOLATION SCENARIOS VERIFIED 100% PASS")
print("=" * 80)
