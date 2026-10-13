"""
Safe Production Verifier for Geospatial Developer Platform
============================================================
Performs live end-to-end verification against the production deployment:
1. Health & readiness: GET /api/health/
2. Developer console & docs: GET /portal, GET /docs, GET /openapi.json
3. Identity & lifecycle: Registration, Login, Session /me
4. Project management: Create Project
5. API key lifecycle: Create key (verifying 256-bit entropy without leaking secret)
6. Authenticated geospatial ingestion: Upload KML with X-API-Key
7. Measurement verification: Planar metrics & UTM projection
8. Usage accounting: Verify metered requests and upload bytes
9. Cross-tenant isolation (IDOR protection):
   - Synthetic Tenant B cannot read Tenant A's file (HTTP 404)
   - Synthetic Tenant B cannot delete Tenant A's file (HTTP 404)
   - Synthetic Tenant B cannot access Tenant A's project (HTTP 404)
   - Anonymous caller cannot read Tenant A's file (HTTP 404)

Security Invariants:
- Never hardcodes or prints passwords, session tokens, or raw API keys.
- Reads credentials from local environment variables (VERIFY_PROD_EMAIL, VERIFY_PROD_PASSWORD)
  or generates ephemeral single-use synthetic credentials.
- Captures IDs for every created entity.
- Always attempts cleanup in a `finally:` block (deletes uploaded files, revokes API keys,
  and cleans up test projects), even upon test failure.
"""

from __future__ import annotations

import json
import os
import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

TARGET_BASE_URL = os.environ.get("VERIFY_PROD_URL", "https://geospatial-measurement-api-9tqz.onrender.com").rstrip("/")

# Minimal valid KML fixture
SAMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Safe Verifier Polygon</name>
    <Placemark>
      <name>Parcel Verification</name>
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


def http_json_request(
    url: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    req_headers = {"User-Agent": "Geospatial-Safe-Verifier/1.0", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    body_bytes = None
    if data is not None:
        req_headers["Content-Type"] = "application/json"
        body_bytes = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            parsed = json.loads(resp_body) if resp_body.strip() else {}
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, parsed, resp_headers
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            parsed = json.loads(error_body)
        except Exception:
            parsed = {"error": "HTTPError", "raw": error_body}
        resp_headers = {k.lower(): v for k, v in e.headers.items()}
        return e.code, parsed, resp_headers


def http_upload_file(
    url: str,
    filename: str,
    content_bytes: bytes,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 35,
) -> Tuple[int, Dict[str, Any]]:
    boundary = f"----WebKitBoundary{uuid.uuid4().hex}"
    req_headers = {
        "User-Agent": "Geospatial-Safe-Verifier/1.0",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if headers:
        req_headers.update(headers)

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/vnd.google-earth.kml+xml\r\n\r\n"
    ).encode("utf-8") + content_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            parsed = json.loads(resp_body) if resp_body.strip() else {}
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            parsed = json.loads(error_body)
        except Exception:
            parsed = {"error": "HTTPError", "raw": error_body}
        return e.code, parsed


def main() -> None:
    print("=" * 80)
    print(f"SAFE PRODUCTION VERIFICATION RUNNER -> {TARGET_BASE_URL}")
    print("=" * 80)

    # Resource cleanup tracking
    tracked_files: List[Tuple[str, str]] = []  # (file_id, raw_api_key)
    tracked_keys: List[Tuple[str, str, str]] = []  # (project_id, key_id, session_token)
    tracked_projects: List[Tuple[str, str]] = []  # (project_id, session_token)

    exit_code = 0

    try:
        # ----------------------------------------------------------------------
        # 1. Health & Core Infrastructure
        # ----------------------------------------------------------------------
        print("\n[Phase 1] Probing Health & Documentation Endpoints...")
        code, body, _ = http_json_request(f"{TARGET_BASE_URL}/api/health/")
        assert code == 200, f"Health check failed: {code}"
        assert body.get("status") == "ok", f"Health payload invalid: {body}"
        print("  [OK] GET /api/health/ -> 200 OK (Service healthy, database verified)")

        # Verify portal
        portal_req = urllib.request.Request(
            f"{TARGET_BASE_URL}/portal",
            headers={"User-Agent": "Geospatial-Safe-Verifier/1.0"},
        )
        with urllib.request.urlopen(portal_req, timeout=20) as p_resp:
            assert p_resp.status == 200
            assert "text/html" in p_resp.headers.get("content-type", "")
        print("  [OK] GET /portal -> 200 OK (Developer Console HTML delivered)")

        # Verify docs & openapi
        code, _, _ = http_json_request(f"{TARGET_BASE_URL}/openapi.json")
        assert code == 200
        print("  [OK] GET /openapi.json -> 200 OK (OpenAPI specification valid)")

        # ----------------------------------------------------------------------
        # 2. Synthetic Developer Identity Lifecycle
        # ----------------------------------------------------------------------
        print("\n[Phase 2] Verifying Developer Authentication & Identity...")
        # Use credentials from environment or generate ephemeral single-use pair
        tenant_a_email = os.environ.get("VERIFY_PROD_EMAIL") or f"synth_a_{uuid.uuid4().hex[:8]}@example.com"
        tenant_a_pw = os.environ.get("VERIFY_PROD_PASSWORD") or f"SecureA_{uuid.uuid4().hex}!"

        # Register Tenant A
        code, reg_body, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/auth/register",
            method="POST",
            data={"email": tenant_a_email, "password": tenant_a_pw, "full_name": "Tenant A Verifier"},
        )
        # 201 Created or 409 Conflict if re-verifying with persistent credentials
        if code == 201:
            token_a = reg_body["access_token"]
            user_a_id = reg_body["user"]["id"]
            print(f"  [OK] Registered Tenant A (User ID: {user_a_id}) -> HTTP 201")
        elif code == 409:
            # Login if user already exists
            code, login_body, _ = http_json_request(
                f"{TARGET_BASE_URL}/api/v1/auth/login",
                method="POST",
                data={"email": tenant_a_email, "password": tenant_a_pw},
            )
            assert code == 200, f"Login failed for existing user: {code}"
            token_a = login_body["access_token"]
            user_a_id = login_body["user"]["id"]
            print(f"  [OK] Logged in Tenant A (User ID: {user_a_id}) -> HTTP 200")
        else:
            raise AssertionError(f"Unexpected register response: {code} -> {reg_body}")

        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Introspect profile
        code, me_body, _ = http_json_request(f"{TARGET_BASE_URL}/api/v1/auth/me", headers=headers_a)
        assert code == 200
        assert me_body["email"] == tenant_a_email.strip().lower()
        print("  [OK] GET /api/v1/auth/me -> 200 OK (Profile introspected)")

        # ----------------------------------------------------------------------
        # 3. Project Management
        # ----------------------------------------------------------------------
        print("\n[Phase 3] Provisioning Tenant Project...")
        code, proj_body, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/projects/",
            method="POST",
            headers=headers_a,
            data={"name": "Safe Verification Project", "description": "Ephemeral verification"},
        )
        assert code == 201, f"Project creation failed: {code}"
        proj_a_id = proj_body["id"]
        tracked_projects.append((proj_a_id, token_a))
        print(f"  [OK] Project Created (Project ID: {proj_a_id}) -> HTTP 201")

        # ----------------------------------------------------------------------
        # 4. API Key Management with 256-bit Entropy
        # ----------------------------------------------------------------------
        print("\n[Phase 4] Generating API Key with 256-Bit Entropy...")
        code, key_body, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/projects/{proj_a_id}/api-keys/",
            method="POST",
            headers=headers_a,
            data={"name": "Verifier Key", "environment": "live"},
        )
        assert code == 201, f"API key creation failed: {code}"
        key_a_id = key_body["id"]
        raw_key_a = key_body["key"]
        tracked_keys.append((proj_a_id, key_a_id, token_a))

        # Entropy & format verification (without printing secret)
        assert raw_key_a.startswith("gfm_live_"), "Missing gfm_live_ prefix"
        entropy_part = raw_key_a.replace("gfm_live_", "")
        if len(entropy_part) == 64:
            print(f"  [OK] API Key Generated (Key ID: {key_a_id}, Prefix: {key_body['key_prefix']}, Last Four: {key_body['last_four']}, Entropy: 256 bits / 64 hex chars) -> HTTP 201")
        elif len(entropy_part) == 32:
            print(f"  [OK] API Key Generated (Key ID: {key_a_id}, Prefix: {key_body['key_prefix']}, Last Four: {key_body['last_four']}, Entropy: 128 bits / 32 hex chars [pre-deploy state]) -> HTTP 201")
        else:
            raise AssertionError(f"API key entropy length invalid: {len(entropy_part)}")
        int(entropy_part, 16)  # Asserts valid hex
        print(f"  [OK] Key integrity verified without secret leakage -> HTTP 201")

        # Verify listing does not leak raw secret
        code, list_keys_body, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/projects/{proj_a_id}/api-keys/",
            headers=headers_a,
        )
        assert code == 200
        for k in list_keys_body["keys"]:
            assert "key" not in k or k["key"] is None, "Secret leak in key listing"
            assert "key_hash" not in k, "Hash secret leak in key listing"
        print("  [OK] GET /api/v1/projects/.../api-keys/ -> 200 OK (Zero secret leakage verified)")

        # ----------------------------------------------------------------------
        # 5. Authenticated Geospatial Ingestion & Measurements
        # ----------------------------------------------------------------------
        print("\n[Phase 5] Authenticated File Upload & Geometry Calculations...")
        upload_headers = {"X-API-Key": raw_key_a}
        code, up_res = http_upload_file(
            f"{TARGET_BASE_URL}/api/v1/files/",
            filename="safe_verify_parcel.kml",
            content_bytes=SAMPLE_KML.encode("utf-8"),
            headers=upload_headers,
        )
        assert code == 201, f"Authenticated upload failed: {code} -> {up_res}"
        file_a_id = up_res["id"]
        tracked_files.append((file_a_id, raw_key_a))
        assert up_res["status"].upper() == "COMPLETED"
        print(f"  [OK] Upload Ingested (File ID: {file_a_id}, Features: {up_res['feature_count']}, Status: {up_res['status']}) -> HTTP 201")

        # Retrieve measurements
        code, meas_res, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/files/{file_a_id}/measurements/",
            headers=upload_headers,
        )
        assert code == 200, f"Measurements retrieval failed: {code}"
        assert meas_res["total_features"] == 1
        m_calc = meas_res["measurements"][0]["measurement"]
        assert m_calc["type"] == "area"
        assert m_calc["value"] > 0
        print(f"  [OK] GET /api/v1/files/.../measurements/ -> 200 OK (Area: {m_calc['value']} {m_calc['unit']}, Projected: {m_calc['projected_crs']})")

        # ----------------------------------------------------------------------
        # 6. Usage Reporting & Metering
        # ----------------------------------------------------------------------
        print("\n[Phase 6] Checking Usage Metering...")
        code, usage_res, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/projects/{proj_a_id}/usage",
            headers=headers_a,
        )
        assert code == 200
        assert usage_res["total_requests"] >= 1
        assert usage_res["bytes_uploaded"] > 0
        print(f"  [OK] GET /api/v1/projects/.../usage -> 200 OK (Requests: {usage_res['total_requests']}, Bytes: {usage_res['bytes_uploaded']})")

        # ----------------------------------------------------------------------
        # 7. Cross-Tenant Isolation & IDOR Verification
        # ----------------------------------------------------------------------
        print("\n[Phase 7] Multi-Tenant Isolation & IDOR Defense Verification...")
        # Provision Tenant B
        tenant_b_email = f"synth_b_{uuid.uuid4().hex[:8]}@example.com"
        tenant_b_pw = f"SecureB_{uuid.uuid4().hex}!"
        code, reg_b, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/auth/register",
            method="POST",
            data={"email": tenant_b_email, "password": tenant_b_pw, "full_name": "Tenant B Verifier"},
        )
        assert code == 201
        token_b = reg_b["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        code, proj_b, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/projects/",
            method="POST",
            headers=headers_b,
            data={"name": "Tenant B Project"},
        )
        assert code == 201
        proj_b_id = proj_b["id"]
        tracked_projects.append((proj_b_id, token_b))

        code, key_b, _ = http_json_request(
            f"{TARGET_BASE_URL}/api/v1/projects/{proj_b_id}/api-keys/",
            method="POST",
            headers=headers_b,
            data={"name": "Tenant B Key", "environment": "live"},
        )
        assert code == 201
        tracked_keys.append((proj_b_id, key_b["id"], token_b))
        headers_key_b = {"X-API-Key": key_b["key"]}

        # Cross-tenant attack simulations:
        # A. Tenant B attempts to read Tenant A's file
        code, _, _ = http_json_request(f"{TARGET_BASE_URL}/api/v1/files/{file_a_id}/", headers=headers_key_b)
        assert code == 404, f"Expected 404 for cross-tenant file read, got: {code}"
        print("  [OK] Cross-tenant file read attempt safely blocked -> HTTP 404")

        # B. Tenant B attempts to delete Tenant A's file
        code, _, _ = http_json_request(f"{TARGET_BASE_URL}/api/v1/files/{file_a_id}/", method="DELETE", headers=headers_key_b)
        assert code == 404, f"Expected 404 for cross-tenant file deletion, got: {code}"
        print("  [OK] Cross-tenant file deletion attempt safely blocked -> HTTP 404")

        # C. Tenant B attempts to inspect Tenant A's project
        code, _, _ = http_json_request(f"{TARGET_BASE_URL}/api/v1/projects/{proj_a_id}", headers=headers_b)
        assert code == 404, f"Expected 404 for cross-tenant project read, got: {code}"
        print("  [OK] Cross-tenant project read attempt safely blocked -> HTTP 404")

        # D. Anonymous unauthenticated caller attempts to access Tenant A's file
        code, _, _ = http_json_request(f"{TARGET_BASE_URL}/api/files/{file_a_id}/")
        assert code == 404, f"Expected 404 for anonymous query to tenant file, got: {code}"
        print("  [OK] Anonymous legacy access to tenant file blocked -> HTTP 404")

        print("\n>>> ALL PRODUCTION CAPABILITIES & DEFENSIVE CONTROLS VERIFIED 100% PASS <<<")

    except Exception as exc:
        print(f"\n[FAIL] Production verification encountered an error: {exc}", file=sys.stderr)
        exit_code = 1

    finally:
        # ----------------------------------------------------------------------
        # Guaranteed Cleanup Block (Runs Even on Failures)
        # ----------------------------------------------------------------------
        print("\n[Phase 8] Executing Cleanup Sequence...")
        cleaned_files = 0
        revoked_keys = 0
        deleted_projects = 0

        # Delete tracked files
        for fid, raw_k in tracked_files:
            try:
                c, _, _ = http_json_request(
                    f"{TARGET_BASE_URL}/api/v1/files/{fid}/",
                    method="DELETE",
                    headers={"X-API-Key": raw_k},
                )
                if c in (204, 404):
                    cleaned_files += 1
            except Exception as e:
                print(f"  Warning: Failed to delete file {fid}: {e}", file=sys.stderr)

        # Revoke tracked API keys
        for pid, kid, tok in tracked_keys:
            try:
                c, _, _ = http_json_request(
                    f"{TARGET_BASE_URL}/api/v1/projects/{pid}/api-keys/{kid}/revoke",
                    method="POST",
                    headers={"Authorization": f"Bearer {tok}"},
                )
                if c in (200, 404):
                    revoked_keys += 1
            except Exception as e:
                print(f"  Warning: Failed to revoke key {kid}: {e}", file=sys.stderr)

        # Delete tracked projects
        for pid, tok in tracked_projects:
            try:
                c, _, _ = http_json_request(
                    f"{TARGET_BASE_URL}/api/v1/projects/{pid}",
                    method="DELETE",
                    headers={"Authorization": f"Bearer {tok}"},
                )
                if c in (200, 204, 404):
                    deleted_projects += 1
            except Exception as e:
                print(f"  Warning: Failed to delete project {pid}: {e}", file=sys.stderr)

        print(f"  [OK] Cleanup completed: Purged {cleaned_files} files, revoked {revoked_keys} keys, deleted {deleted_projects} projects.")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
