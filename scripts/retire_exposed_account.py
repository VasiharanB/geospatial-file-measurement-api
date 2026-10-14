"""
Audit and Retire Exposed Test Account on Production
===================================================
Target Account: prod_verify_cc25f7@example.com
Actions:
1. Authenticate with previously exposed password
2. Enumerate all associated projects, API keys, and files
3. Delete all files owned by the tenant
4. Revoke all active API keys
5. Delete all projects
6. Rotate password to a secure 64-char unguessable random string (invalidating all sessions)
7. Log out and verify that the exposed password no longer works (HTTP 401)
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

TARGET_BASE_URL = os.environ.get("VERIFY_PROD_URL", "https://geospatial-measurement-api-9tqz.onrender.com").rstrip("/")
EXPOSED_EMAIL = "prod_verify_cc25f7@example.com"
EXPOSED_PASSWORD = os.environ.get("RETIRE_ACCOUNT_OLD_PASSWORD", "ProdVerifyPassword456!")


def http_request(
    url: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 40,
) -> Tuple[int, Dict[str, Any]]:
    req_headers = {"User-Agent": "Account-Retirement/1.0", "Accept": "application/json"}
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
    print(f"AUDITING & RETIRING EXPOSED ACCOUNT: {EXPOSED_EMAIL}")
    print(f"TARGET: {TARGET_BASE_URL}")
    print("=" * 80)

    # 1. Attempt login with exposed password
    print("\n[Step 1] Authenticating with exposed credentials...")
    code, login_res = http_request(
        f"{TARGET_BASE_URL}/api/v1/auth/login",
        method="POST",
        data={"email": EXPOSED_EMAIL, "password": EXPOSED_PASSWORD},
    )

    if code == 401:
        print(f"  [INFO] Account {EXPOSED_EMAIL} already rejected with HTTP 401 (already retired or password rotated).")
        print("\n>>> ACCOUNT IS ALREADY RETIRED AND INACCESSIBLE <<<")
        return

    if code != 200:
        print(f"  [FAIL] Unexpected login response: {code} -> {login_res}", file=sys.stderr)
        sys.exit(1)

    token = login_res["access_token"]
    user_id = login_res["user"]["id"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"  [OK] Authenticated successfully. User ID: {user_id}")

    # 2. Enumerate Projects
    print("\n[Step 2] Enumerating projects...")
    code, proj_data = http_request(f"{TARGET_BASE_URL}/api/v1/projects/", headers=headers)
    projects = proj_data.get("projects", []) if code == 200 else []
    print(f"  [INFO] Found {len(projects)} associated project(s):")
    for p in projects:
        print(f"    - Project ID: {p['id']}, Name: {p['name']}")

    # 3. Enumerate and Revoke API Keys
    print("\n[Step 3] Enumerating and revoking API keys...")
    revoked_count = 0
    for p in projects:
        code, key_data = http_request(f"{TARGET_BASE_URL}/api/v1/projects/{p['id']}/api-keys/", headers=headers)
        keys = key_data.get("keys", []) if code == 200 else []
        print(f"  [INFO] Project {p['id']} has {len(keys)} key(s):")
        for k in keys:
            is_active = k.get("is_active", True)
            key_id = k["id"]
            prefix = k.get("key_prefix", "gfm_")
            last_four = k.get("last_four", "????")
            if is_active:
                rcode, rres = http_request(
                    f"{TARGET_BASE_URL}/api/v1/projects/{p['id']}/api-keys/{key_id}/revoke",
                    method="POST",
                    headers=headers,
                )
                print(f"    - Revoked Key {key_id} (prefix: {prefix}, last4: {last_four}) -> HTTP {rcode}")
                revoked_count += 1
            else:
                print(f"    - Key {key_id} already revoked.")

    # 4. Enumerate and Delete Files
    print("\n[Step 4] Enumerating and deleting uploaded files...")
    deleted_files_count = 0
    code, file_data = http_request(f"{TARGET_BASE_URL}/api/v1/files/", headers=headers)
    files = file_data.get("files", []) if code == 200 else []
    print(f"  [INFO] Found {len(files)} file(s) owned by user:")
    for f in files:
        fid = f["id"]
        fname = f.get("filename", "unknown")
        dcode, dres = http_request(f"{TARGET_BASE_URL}/api/v1/files/{fid}/", method="DELETE", headers=headers)
        print(f"    - Deleted File {fid} ({fname}) -> HTTP {dcode}")
        deleted_files_count += 1

    # 5. Delete Projects
    print("\n[Step 5] Deleting projects...")
    deleted_projects_count = 0
    for p in projects:
        pid = p["id"]
        pname = p.get("name", "unnamed")
        dpcode, dpres = http_request(f"{TARGET_BASE_URL}/api/v1/projects/{pid}", method="DELETE", headers=headers)
        print(f"    - Deleted Project {pid} ({pname}) -> HTTP {dpcode}")
        deleted_projects_count += 1

    # 6. Rotate Password to an Unguessable High-Entropy Random String
    print("\n[Step 6] Rotating password to unguessable random string and purging all sessions...")
    retired_password = f"RetiredAccount_{secrets.token_urlsafe(48)}!A9z"
    code, change_res = http_request(
        f"{TARGET_BASE_URL}/api/v1/auth/change-password",
        method="POST",
        headers=headers,
        data={"current_password": EXPOSED_PASSWORD, "new_password": retired_password},
    )
    assert code == 200, f"Password change failed: {code} -> {change_res}"
    print("  [OK] Password rotated. All active sessions purged.")

    # 7. Verify Old Password Is Blocked
    print("\n[Step 7] Verifying exposed password is rejected...")
    code, test_login = http_request(
        f"{TARGET_BASE_URL}/api/v1/auth/login",
        method="POST",
        data={"email": EXPOSED_EMAIL, "password": EXPOSED_PASSWORD},
    )
    assert code == 401, f"Expected 401 Unauthorized for old password, got: {code}"
    print("  [OK] Confirmed: Old exposed password returns HTTP 401 Unauthorized.")

    # 8. Verify Old Session Token Is Invalidated
    print("\n[Step 8] Verifying old session token is invalidated...")
    code, test_me = http_request(f"{TARGET_BASE_URL}/api/v1/auth/me", headers=headers)
    assert code == 401, f"Expected 401 for old session token, got: {code}"
    print("  [OK] Confirmed: Old session token returns HTTP 401 Unauthorized.")

    print("\n" + "=" * 80)
    print("SUMMARY OF RETIREMENT ACTION:")
    print(f"  - Account: {EXPOSED_EMAIL} (User ID: {user_id})")
    print(f"  - Files Deleted: {deleted_files_count}")
    print(f"  - Keys Revoked: {revoked_count}")
    print(f"  - Projects Deleted: {deleted_projects_count}")
    print("  - Password Rotated: YES (Unguessable 64-char CSPRNG string, never recorded)")
    print("  - Sessions Purged: YES (0 active sessions)")
    print("  - Re-authentication with old credentials: BLOCKED (HTTP 401)")
    print(">>> EXPOSED ACCOUNT IS FULLY NEUTRALIZED AND RETIRED <<<")
    print("=" * 80)


if __name__ == "__main__":
    main()
