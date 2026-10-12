# SECURITY AUDIT & HARDENING REPORT (PHASE 11)

**Application**: Geospatial File Measurement API  
**Assessment Date**: 2026-10-13  
**Auditor**: Senior Application Security Engineer & DevSecOps Specialist  
**Target Repository**: [https://github.com/VasiharanB/geospatial-file-measurement-api](https://github.com/VasiharanB/geospatial-file-measurement-api)  
**Baseline Git Commit**: `2713b50` (Branch: `main`)  
**Test Environment**: Python 3.14 / 3.11, FastAPI 0.142.2, SQLAlchemy 2.1.3, SQLite 3 (WAL Mode), Starlette TestClient, HTTPX  
**Automated Verification**: **9/9 Test Suites Passed (144/144 Scenarios Verified 100%)**

---

## 1. Executive Summary

This defensive security assessment was conducted under authorized engagement rules for the **Geospatial File Measurement API** to audit, identify, prioritize, safely validate, remediate, and re-audit the entire application before constructing the public developer portal and API-key management tier.

### Core Audit Outcomes:
- **Zero Ingestion Breaches**: The backend's core geospatial parsing layers correctly enforce `defusedxml` (blocking XXE and entity expansion), strict Zip-Slip extraction boundaries (`os.path.commonpath`), decompression bomb thresholds (100 MB max, 100:1 ratio limit), and strict 25 MB stream limits (HTTP 413).
- **Critical Frontend Risk Resolved**: A high-severity vulnerability was identified in [script.js](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/script.js) where an unvalidated `?api_url=` query parameter allowed an external attacker to hijack API endpoints and exfiltrate uploaded geospatial survey files. This has been remediated using strict trusted origin allowlisting.
- **Backend Defense-in-Depth Hardened**: Missing HTTP security headers, missing rate-limiting on compute endpoints, missing exception classes, overly broad SSRF regexes, and container superuser privileges were systematically remediated.
- **Zero Known Dependency Vulnerabilities**: Authoritative `pip-audit` scan verified 0 CVEs across all direct and transitive dependencies.
- **Clean Static Analysis**: `bandit` static analysis confirmed 0 issues across all severity tiers.

---

## 2. Authorized Scope & Testing Boundaries

### Evaluated Assets:
1. **Source Code**: Single-file FastAPI backend ([main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py)), Frontend controller ([script.js](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/script.js)), HTML structure ([index.html](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/index.html)), Configuration ([.env.example](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/.env.example), [Dockerfile](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/Dockerfile), [render.yaml](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/render.yaml), [.github/workflows/ci.yml](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/.github/workflows/ci.yml)).
2. **Live Production Frontend**: `https://vasiharanb.github.io/geospatial-file-measurement-api/` (GitHub Pages)
3. **Live Production Backend**: `https://geospatial-measurement-api-9tqz.onrender.com/` (Render Web Service)
4. **Authoritative API Documentation**: `https://geospatial-measurement-api-9tqz.onrender.com/docs` (Swagger UI / OpenAPI)

### Rules of Engagement Adherence:
- **Non-Destructive Testing**: All active testing, fuzzing simulations, and vulnerability reproductions were performed against isolated local instances using synthetic GIS coordinates.
- **Production Safety**: Only low-volume, read-only HTTP probes were sent to the live Render and GitHub Pages endpoints. Zero denial-of-service, automated scanners, or destructive calls were directed at third-party infrastructure.
- **Zero Privacy Leakage**: No real personal coordinates or home property boundaries were used in any test fixture.

---

## 3. Tooling & Verification Matrix

| Tool | Purpose | Result / Status | Notes |
| :--- | :--- | :--- | :--- |
| **pip-audit (v2.10.1)** | Dependency Vulnerability Scan | **PASS (0 Vulnerabilities)** | Evaluated `requirements.txt` against PyPI advisory DB. |
| **bandit (v1.9.4)** | AST Static Security Analysis | **PASS (0 Issues)** | Scanned [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py); resolved B110 warning. |
| **git log / ls-files** | Secret & Credential Scanning | **PASS (0 Leaks)** | Verified zero API keys, private keys, or `.env` files in Git history. |
| **HTTPX (v0.28.1)** | Live Production Probes | **PASS (Verified)** | Tested HTTPS, TLS, certificate validity, and status 200 on live URLs. |
| **Starlette TestClient** | Automated Regression Suites | **PASS (144/144 Scenarios)** | Verified Parts 2 through 10 with 100% pass rate. |

---

## 4. Confirmed Findings, Evidence & Remediations

### SEC-01: Arbitrary API Base URL Parameter Override & Silent Exfiltration
- **Severity**: **HIGH** (CVSS 7.5 / CWE-601 / CWE-200)
- **Affected Component**: [script.js](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/script.js#L11-L60) (`getAuthoritativeApiBaseUrl`)
- **Root Cause**: `script.js` previously set `API_BASE_URL` directly from `new URLSearchParams(window.location.search).get('api_url')` without validating the host or scheme.
- **Practical Impact**: An attacker could craft a link such as `https://vasiharanb.github.io/geospatial-file-measurement-api/?api_url=https://attacker-c2.com`. A victim opening this link would see the legitimate application interface, but any uploaded Shapefile or KML survey containing proprietary boundary coordinates would be silently POSTed directly to `https://attacker-c2.com/api/files/`.
- **Safe Validation**: Confirmed locally with mock query string tests.
- **Remediation**: Implemented `getAuthoritativeApiBaseUrl()` in [script.js](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/script.js) with a strict `TRUSTED_API_ORIGINS` Set (`https://geospatial-measurement-api-9tqz.onrender.com`, `http://127.0.0.1:8000`, `http://localhost:8000`). Untrusted URLs are rejected with a console warning and safely fall back to the authoritative default.
- **Regression Test**: Added [tests/test_security_audit.py Scenario 7](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-02: Missing Defense-in-Depth HTTP Security Response Headers
- **Severity**: **MEDIUM** (CWE-693: Protection Mechanism Failure)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py#L1225-L1240) (`security_headers_middleware`)
- **Root Cause**: The FastAPI app registered `CORSMiddleware` but did not provide standard HTTP response security headers.
- **Practical Impact**: Allowed possible framing/clickjacking attacks, MIME sniffing confusion on API payloads, and cross-origin referrer leakage.
- **Safe Validation**: Probing `/api/health/` confirmed absent headers.
- **Remediation**: Implemented `security_headers_middleware` injecting:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), camera=(), microphone=()`
- **Regression Test**: Added [tests/test_security_audit.py Scenario 1](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-03: Missing API Request Rate Limiting / Flooding Protection
- **Severity**: **MEDIUM** (CWE-770: Allocation of Resources Without Limits)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py#L1242-L1280) (`rate_limiting_middleware`), [.env.example](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/.env.example)
- **Root Cause**: No request throttling existed, allowing rapid automated loops to exhaust worker threadpools or disk space.
- **Practical Impact**: Potential service degradation under high-volume automated abuse.
- **Safe Validation**: Measured unthrottled request frequency capability.
- **Remediation**: Implemented thread-safe in-memory sliding-window IP rate limiter (`RATE_LIMIT_PER_MINUTE=600`, configurable via environment), returning HTTP 429 with `Retry-After: 60`, while safely exempting OPTIONS preflights, `/api/health/`, and documentation endpoints.
- **Regression Test**: Added [tests/test_security_audit.py Scenario 6](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-04: Container Execution as Root Superuser in Production Dockerfile
- **Severity**: **MEDIUM** (CWE-250: Execution with Unnecessary Privileges)
- **Affected Component**: [Dockerfile](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/Dockerfile#L21-L32)
- **Root Cause**: The Docker container ran application processes as the default `root` user.
- **Practical Impact**: If an unpatched native C library vulnerability (e.g. in GDAL/PROJ) were triggered, an attacker would gain root privileges inside the container.
- **Safe Validation**: Inspected Dockerfile build layers.
- **Remediation**: Added system group and unprivileged user `appuser` (UID 1000), set ownership of `/app` and `/app/storage/uploads`, and added `USER appuser`.
- **Regression Test**: Added [tests/test_security_audit.py Scenario 5](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-05: Undefined SecurityException Triggering Unhandled 500 NameError
- **Severity**: **LOW / CODE QUALITY** (CWE-390)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py#L328)
- **Root Cause**: Lines 1342 and 1346 raised `SecurityException` upon detecting path traversal during upload staging, but the class was never imported or defined.
- **Practical Impact**: If triggered, Python raised a `NameError` routing to the generic 500 handler rather than a controlled 400 Bad Request.
- **Safe Validation**: Direct class inspection confirmed missing definition.
- **Remediation**: Defined `SecurityException(GeospatialAPIError)` mapped to `HTTP_400_BAD_REQUEST`.
- **Regression Test**: Added [tests/test_security_audit.py Scenario 3](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-06: Incomplete URI Scheme Protocol Filtering in KML SSRF Defense
- **Severity**: **LOW** (CWE-918: Server-Side Request Forgery)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py#L390-L405) (`validate_and_sanitize_kml`)
- **Root Cause**: Static prefix check matched only `http://`, `https://`, `ftp://`, `file://`, and `\\\\`.
- **Practical Impact**: Non-standard URI schemes (`gopher://`, `ldap://`, `data:`, `//`) were not explicitly matched.
- **Safe Validation**: Tested with synthetic KML containing `<href>gopher://127.0.0.1:70/</href>`.
- **Remediation**: Upgraded check with regular expression `^[a-zA-Z][a-zA-Z0-9+.-]*://` and prefix matching for `//`, `\\\\`, `data:`, `javascript:`, `vbscript:`, and `netdoc:`.
- **Regression Test**: Added [tests/test_security_audit.py Scenario 2](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-07: Unsanitized Resource ID Reflection in 404 Error Detail
- **Severity**: **LOW** (CWE-79 / CWE-116)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py#L1460, #L1510) (`get_file_detail`, `get_file_measurements`)
- **Root Cause**: Raw `id` parameter string was interpolated directly into `ResourceNotFoundException(f"File with ID '{id}' was not found.")`.
- **Practical Impact**: While JSON serialization prevents direct HTML execution in browsers, automated DAST scanners flag raw character reflection.
- **Safe Validation**: Probed `/api/files/<script>alert(1)</script>/`.
- **Remediation**: Sanitized reflected ID using `re.sub(r"[^a-zA-Z0-9_\-]", "", clean_id)[:64]`.
- **Regression Test**: Added [tests/test_security_audit.py Scenario 4](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-08: Blind Try-Except-Pass in Property Serialization (Bandit B110)
- **Severity**: **LOW / CODE QUALITY** (CWE-703)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py#L1092-L1098)
- **Root Cause**: Broad `except Exception: pass` when attempting `.item()` conversion on numpy scalars.
- **Practical Impact**: Masked potential unexpected exceptions during attribute parsing.
- **Remediation**: Constrained exception handling to `except (ValueError, TypeError, AttributeError):` with debug logging.
- **Regression Test**: Verified with `python -m bandit -r main.py` (0 issues). Result: **PASS**.

---

## 5. Production Checks Actually Performed

Low-volume, non-destructive checks against authorized production endpoints:

1. **Frontend Asset Integrity**:
   - `GET https://vasiharanb.github.io/geospatial-file-measurement-api/`
   - Response: `HTTP 200 OK`, `server: GitHub.com`, `strict-transport-security: max-age=31556952`.
2. **Backend Operational Readiness**:
   - `GET https://geospatial-measurement-api-9tqz.onrender.com/api/health/`
   - Response: `HTTP 200 OK`, `{"status": "ok", "service": "Geospatial File Measurement API"}`.
   - HTTPS / TLS Certificate: Valid, Cloudflare CDN proxy.
3. **Interactive Documentation**:
   - `GET https://geospatial-measurement-api-9tqz.onrender.com/docs` -> `HTTP 200 OK`
   - `GET https://geospatial-measurement-api-9tqz.onrender.com/openapi.json` -> `HTTP 200 OK`

---

## 6. Access Control & Privacy Analysis: Current vs. Developer Portal Phase

### Current Service Posture:
- **Application Authentication**: **None**. The API currently operates as a public, open geospatial processing utility.
- **Object Access Model**: Files and measurements are looked up via UUIDv4 identifiers.
  - *Entropy*: UUIDv4 provides 122 bits of cryptographically strong randomness (~$5.3 \times 10^{36}$ values), making brute-force discovery of file IDs computationally impossible.
  - *Privacy Risk*: Any entity in possession of a UUIDv4 (e.g. through shared URLs, browser history, or network logging) can view the geometries and properties of that file.

### Required Architecture for Upcoming Developer Portal:
When implementing user accounts and API-key management in the next phase, the following controls MUST be introduced:
1. **API Key Authentication**: Require `X-API-Key` or `Authorization: Bearer <token>` on all `/api/files/` routes.
2. **Tenant Isolation / Row-Level Ownership**: Associate each `FileRecord` with an `account_id` / `user_id`. Enforce that callers can only access records owned by their authenticated account.
3. **Data Retention & TTL**: Implement automatic purging of uploaded files and measurement records after a configurable TTL (e.g., 24 hours for temporary calculations, or user-managed lifecycle).
4. **Explicit Delete Endpoint**: Provide `DELETE /api/files/{id}/` allowing developers to delete their proprietary survey data immediately after calculation.
5. **Distributed Rate Limiting**: Transition in-memory rate limiting to Redis-backed token buckets for multi-worker / multi-container deployments.

---

## 7. Checks Explicitly Not Executed

In strict compliance with the Rules of Engagement:
- **No Volumetric DoS / DDoS**: Flooding and network saturation tests were excluded.
- **No Active Scanners Against Production**: OWASP ZAP, Nikto, or SQLMap were not pointed at Render or GitHub infrastructure.
- **No Real Personal Data Testing**: Personal property coordinates were never transmitted.
- **No Third-Party Infrastructure Attacks**: Render internal networks and GitHub Pages servers were not probed.

---

## 8. Verification & Test Suite Summary

All 9 test suites were executed sequentially via the master runner [tests/run_all_tests.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/run_all_tests.py):

```text
================================================================================
GEOSPATIAL FILE MEASUREMENT API — FULL VERIFICATION SUITE
================================================================================

>>> Running Part 2 — File Ingestion & Security Validation (verify_part2.py) [23 scenarios]...
[PASS] Part 2 — File Ingestion & Security Validation passed (23/23)

>>> Running Part 3 — CRS Detection & UTM Resolution Engine (test_part3.py) [16 scenarios]...
[PASS] Part 3 — CRS Detection & UTM Resolution Engine passed (16/16)

>>> Running Part 4 — Planar Metric Engine & Geodesic Benchmarks (test_part4.py) [20 scenarios]...
[PASS] Part 4 — Planar Metric Engine & Geodesic Benchmarks passed (20/20)

>>> Running Part 5 — Relational Persistence & SQLAlchemy 2.0 Models (test_part5.py) [15 scenarios]...
[PASS] Part 5 — Relational Persistence & SQLAlchemy 2.0 Models passed (15/15)

>>> Running Part 6 — API Serialization & REST Contract Enforcement (test_part6.py) [11 scenarios]...
[PASS] Part 6 — API Serialization & REST Contract Enforcement passed (11/11)

>>> Running Part 7 — Database Layer & Architecture Hardening (test_part7.py) [15 scenarios]...
[PASS] Part 7 — Database Layer & Architecture Hardening passed (15/15)

>>> Running Part 8 — Production Quality & Deployment Readiness (test_part8.py) [16 scenarios]...
[PASS] Part 8 — Production Quality & Deployment Readiness passed (16/16)

>>> Running Part 9A — Functional UI Validation & End-to-End Integration (test_part9a.py) [20 scenarios]...
[PASS] Part 9A — Functional UI Validation & End-to-End Integration passed (20/20)

>>> Running Part 10 — Defensive Security Audit & Hardening (test_security_audit.py) [8 scenarios]...
[PASS] Part 10 — Defensive Security Audit & Hardening passed (8/8)

================================================================================
SUMMARY: 9/9 SUITES PASSED (144 SCENARIOS VERIFIED 100%)
================================================================================
```
