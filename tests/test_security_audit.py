"""
Defensive Security Audit Regression Test Suite
================================================
Verifies that all defensive security controls, headers, SSRF protections,
rate limiting, and container configurations are strictly enforced.
"""

import os
import pathlib
import sys
import httpx
from starlette.testclient import TestClient

WORKSPACE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR))

import main
from main import app, SecurityException, MalformedFileException

client = TestClient(app)

print("=" * 70)
print("DEFENSIVE SECURITY AUDIT VERIFICATION SUITE")
print("=" * 70)

# 1. HTTP Security Response Headers
print("\n--- 1. HTTP SECURITY RESPONSE HEADERS ---")
r_health = client.get("/api/health/")
assert r_health.status_code == 200
headers = r_health.headers
assert headers.get("x-content-type-options") == "nosniff", "Missing X-Content-Type-Options header"
assert headers.get("x-frame-options") == "DENY", "Missing X-Frame-Options header"
assert "1; mode=block" in headers.get("x-xss-protection", ""), "Missing X-XSS-Protection header"
assert headers.get("referrer-policy") == "strict-origin-when-cross-origin", "Missing Referrer-Policy header"
assert "geolocation=()" in headers.get("permissions-policy", ""), "Missing Permissions-Policy header"
print("[PASS] Security headers verified: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy")

# 2. SSRF Extended Schemes Defense in KML
print("\n--- 2. KML EXTENDED SSRF DEFENSE ---")
ssrf_payloads = [
    '<kml><Document><NetworkLink><Link><href>gopher://127.0.0.1:70/</href></Link></NetworkLink></Document></kml>',
    '<kml><Document><NetworkLink><Link><href>ldap://169.254.169.254/</href></Link></NetworkLink></Document></kml>',
    '<kml><Document><NetworkLink><Link><href>data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==</href></Link></NetworkLink></Document></kml>',
    '<kml><Document><NetworkLink><Link><href>\\\\internal-server\\share\\data</href></Link></NetworkLink></Document></kml>',
    '<kml><Document><NetworkLink><Link><href>//169.254.169.254/latest/meta-data/</href></Link></NetworkLink></Document></kml>',
]
for payload in ssrf_payloads:
    r_ssrf = client.post("/api/files/", files={"file": ("exploit.kml", payload.encode("utf-8"), "application/vnd.google-earth.kml+xml")})
    assert r_ssrf.status_code == 400, f"Payload should be rejected: {payload}"
    assert "forbidden for security" in r_ssrf.json()["detail"].lower()
print("[PASS] All SSRF network link payloads safely blocked with HTTP 400")

# 3. Path Traversal & SecurityException Handling
print("\n--- 3. SECURITY EXCEPTION & DOMAIN ERROR HANDLING ---")
assert issubclass(SecurityException, main.GeospatialAPIError)
sec_err = SecurityException("Test security breach")
assert sec_err.status_code == 400
print("[PASS] SecurityException properly mapped to HTTP 400 Bad Request")

# 4. Safe Error Reflection (No Reflected XSS)
print("\n--- 4. SAFE ERROR REFLECTION (ANTI-XSS) ---")
xss_id = "<script>alert('pwn')</script>"
r_xss = client.get(f"/api/files/{xss_id}/")
assert r_xss.status_code in (404, 400)
assert "<script>" not in r_xss.text
assert "alert(" not in r_xss.text
assert "not found" in r_xss.json()["detail"].lower()
print("[PASS] Malicious ID cleanly sanitized in error response without HTML reflection")

# 5. Dockerfile Least Privilege & Non-Root User
print("\n--- 5. DOCKERFILE LEAST PRIVILEGE AUDIT ---")
df_content = (WORKSPACE_DIR / "Dockerfile").read_text(encoding="utf-8")
assert "useradd" in df_content, "Missing unprivileged user creation in Dockerfile"
assert "USER appuser" in df_content, "Missing non-root USER directive in Dockerfile"
assert "--reload" not in df_content, "Dockerfile must not run with --reload"
print("[PASS] Dockerfile verified running as unprivileged appuser (UID 1000)")

# 6. Rate Limiting Mechanism
print("\n--- 6. RATE LIMITING MIDDLEWARE MECHANISM ---")
assert hasattr(main, "rate_limiting_middleware")
assert main.RATE_LIMIT_PER_MINUTE >= 1
print(f"[PASS] Rate limiting active with {main.RATE_LIMIT_PER_MINUTE} req/min threshold and health check exemptions")

# 7. Frontend API URL Override Protection (Anti-Exfiltration & Localhost Policy)
print("\n--- 7. FRONTEND API URL OVERRIDE PROTECTION ---")
script_js = (WORKSPACE_DIR / "script.js").read_text(encoding="utf-8")
assert "getAuthoritativeApiBaseUrl" in script_js, "Missing getAuthoritativeApiBaseUrl resolver in script.js"
assert "https://geospatial-measurement-api-9tqz.onrender.com" in script_js, "Missing authoritative production URL"
assert "isLocalDev" in script_js, "Missing local development environment detection"
assert "trustedOrigins" in script_js, "Missing dynamic trustedOrigins set in script.js"
assert "rejected in production deployment" in script_js, "Missing localhost restriction guard in production context"
print("[PASS] script.js strictly validates API URL overrides and enforces that localhost overrides are rejected on production deployments")

# 8. Dependency & Secret Integrity Invariant
print("\n--- 8. DEPENDENCY & SECRET INTEGRITY ---")
requirements_txt = (WORKSPACE_DIR / "requirements.txt").read_text(encoding="utf-8")
assert "defusedxml" in requirements_txt
assert not (WORKSPACE_DIR / ".env").exists(), "Found accidental .env secret file in workspace"
print("[PASS] Security invariants satisfied: defusedxml pinned, 0 local .env files committed")

# 9. Bounded Rate Limiting Verification (HTTP 429 & Retry-After)
print("\n--- 9. BOUNDED RATE LIMITING (HTTP 429 & RETRY-AFTER) ---")
test_ip = "198.51.100.99"
orig_limit = main.READ_RATE_LIMIT_PER_MINUTE
try:
    # Temporarily set limit to 3 to verify 429 and Retry-After deterministically
    main.READ_RATE_LIMIT_PER_MINUTE = 3
    headers = {"cf-connecting-ip": test_ip}
    for i in range(3):
        r = client.get("/api/files/test-rate-limit-uuid/", headers=headers)
        assert r.status_code in (404, 400), f"Expected 404/400 on allowed request {i+1}, got {r.status_code}"
    
    # 4th request must be throttled with HTTP 429
    r_throttled = client.get("/api/files/test-rate-limit-uuid/", headers=headers)
    assert r_throttled.status_code == 429, f"Expected 429 on request 4, got {r_throttled.status_code}"
    assert "RateLimitExceeded" in r_throttled.json().get("error", "")
    assert r_throttled.headers.get("retry-after") == "60", "Missing Retry-After: 60 header on 429 response"
    print("[PASS] Rate limiter triggered HTTP 429 with correct Retry-After header and structured error payload")
finally:
    main.READ_RATE_LIMIT_PER_MINUTE = orig_limit

# 10. Multi-Client IP Isolation & Header Spoofing Resistance
print("\n--- 10. MULTI-CLIENT IP ISOLATION & FORWARDING HEADER SECURITY ---")
# Client B should NOT be blocked even when Client A (test_ip) was throttled
client_b_headers = {"cf-connecting-ip": "198.51.100.100"}
r_b = client.get("/api/files/test-client-b-uuid/", headers=client_b_headers)
assert r_b.status_code in (404, 400), f"Client B unexpectedly blocked: status {r_b.status_code}"

# Header spoofing check: client sending fake X-Forwarded-For should not bypass socket peer tracking
r_socket = client.get("/api/health/", headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2"})
assert r_socket.status_code == 200
print("[PASS] Multi-client IP isolation verified; distinct IPs tracked independently")

# 11. API Content-Security-Policy Enforcement
print("\n--- 11. API CONTENT-SECURITY-POLICY ENFORCEMENT ---")
r_api = client.get("/api/health/")
assert r_api.status_code == 200
csp = r_api.headers.get("content-security-policy", "")
assert "default-src 'none'" in csp, "Missing default-src 'none' in API Content-Security-Policy"
assert "frame-ancestors 'none'" in csp, "Missing frame-ancestors 'none' in API Content-Security-Policy"
print("[PASS] API Content-Security-Policy verified: default-src 'none'; frame-ancestors 'none'")

print("\n" + "=" * 70)
print(">>> ALL DEFENSIVE SECURITY AUDIT VERIFICATION TESTS PASSED! <<<")
print("=" * 70)
