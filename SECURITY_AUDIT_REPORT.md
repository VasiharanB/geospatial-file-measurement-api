# SECURITY AUDIT & HARDENING REPORT (PHASE 11 & 11.1 CLOSURE GATE)

**Application**: Geospatial File Measurement API  
**Assessment Date**: 2026-10-13  
**Auditor**: Senior Application Security Engineer, DevSecOps Specialist & Security Architect  
**Target Repository**: [https://github.com/VasiharanB/geospatial-file-measurement-api](https://github.com/VasiharanB/geospatial-file-measurement-api)  
**Baseline Hardening Commit**: `c32ad32` (Branch: `main`)  
**Test Environment**: Python 3.14 / 3.11, FastAPI 0.142.2, SQLAlchemy 2.1.3, SQLite 3 (WAL Mode), Starlette TestClient, HTTPX  
**Automated Master Regression**: **9/9 Test Suites Passed (147/147 Scenarios Verified 100%)**  

---

## 1. Executive Summary & Audit Reconciliation

This authoritative report reconciles all security audit evidence, automated testing outcomes, live production checks, and defensive hardening configurations for the **Geospatial File Measurement API**, completing the **Phase 11.1 Security Closure Gate** prior to building Phase 12 (Developer Accounts, Projects, and API Key Management).

### Test Count Reconciliation (142 vs. 144 vs. 147):
A discrepancy in prior working notes between 142, 144, and 147 scenarios has been conclusively resolved through exhaustive inspection of the master test runner and individual test modules:
- **142 Scenarios**: Early draft summary that inadvertently omitted 2 sub-scenarios in Part 8 (production deployment readiness) prior to full test orchestration.
- **144 Scenarios**: Phase 11 initial audit runner reflecting Parts 2–9A (136 scenarios) + Part 10 (8 initial security audit scenarios).
- **147 Scenarios (Current Authoritative Total)**: Parts 2–9A (136 scenarios) + Part 10 (11 security audit scenarios, expanded with Scenarios 9, 10, and 11 to formally verify bounded HTTP 429 & Retry-After response headers, multi-client IP rate isolation, and API Content-Security-Policy enforcement).

### Master Suite Breakdown:
1. **Part 2** (`verify_part2.py`): **23 scenarios** (Stream limits, Zip-Slip, XML/XXE defusing, bomb thresholds)
2. **Part 3** (`test_part3.py`): **16 scenarios** (CRS detection, auto-UTM resolution, EPSG transforms)
3. **Part 4** (`test_part4.py`): **20 scenarios** (Planar metric engine, Shoelace, geodesic benchmarks)
4. **Part 5** (`test_part5.py`): **15 scenarios** (Relational persistence, SQLAlchemy models, SQLite WAL)
5. **Part 6** (`test_part6.py`): **11 scenarios** (API serialization, REST contracts, schema validation)
6. **Part 7** (`test_part7.py`): **15 scenarios** (Database layer, connection pooling, rollback safety)
7. **Part 8** (`test_part8.py`): **16 scenarios** (Production quality, health checks, error formatting)
8. **Part 9A** (`test_part9a.py`): **20 scenarios** (UI validation, Leaflet/Three.js integration, zero innerHTML)
9. **Part 10** (`test_security_audit.py`): **11 scenarios** (Defensive security audit, SSRF, headers, CSP, rate limits, IP derivation)
**Total: 9 suites, 147 scenarios (100% Passing)**

---

## 2. Authorized Scope & Rules of Engagement Adherence

### Evaluated Assets:
1. **Application Source Code**:
   - Backend: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py) (FastAPI monolithic service)
   - Frontend: [script.js](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/script.js), [index.html](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/index.html), [style.css](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/style.css)
   - Configuration: [.env.example](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/.env.example), [Dockerfile](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/Dockerfile), [render.yaml](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/render.yaml), [.github/workflows/ci.yml](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/.github/workflows/ci.yml)
2. **Live Production Frontend**: `https://vasiharanb.github.io/geospatial-file-measurement-api/` (GitHub Pages)
3. **Live Production Backend**: `https://geospatial-measurement-api-9tqz.onrender.com/` (Render Web Service)
4. **Interactive Documentation**: `https://geospatial-measurement-api-9tqz.onrender.com/docs` (Swagger UI)

### Rules of Engagement Compliance:
- **Non-Destructive Testing**: All active fuzzing, path-traversal payload testing, and rate-limiting stress checks were performed against local sandbox instances.
- **Production Safety**: Live production probes were strictly limited to low-volume, read-only HTTP status and TLS header verifications. High-volume flooding or automated DAST scanners were never pointed at Render or GitHub infrastructure.
- **Zero Privacy Leakage**: Only synthetic bounding boxes and artificial polygon coordinates were used across all test suites. No real personal coordinates or home property boundaries were ever processed or stored.

---

## 3. Tooling & Verification Matrix

| Tool | Purpose | Result / Status | Notes |
| :--- | :--- | :--- | :--- |
| **pip-audit (v2.10.1)** | Dependency Vulnerability Scan | **PASS (0 Vulnerabilities)** | Scanned `requirements.txt` against PyPI advisory DB; 0 CVEs. |
| **bandit (v1.9.4)** | AST Static Security Analysis | **PASS (0 Issues)** | Scanned [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py); resolved B110 exception handling. |
| **git log / ls-files** | Secret & Credential Scanning | **PASS (0 Leaks)** | Verified 0 private keys, passwords, or `.env` files in Git history. |
| **HTTPX (v0.28.1)** | Live Production Probes | **PASS (Verified)** | Verified TLS, HTTPS status 200, and operational endpoints on live URLs. |
| **Starlette TestClient** | Automated Regression Suites | **PASS (147/147 Scenarios)** | Verified Parts 2 through 10 with 100% pass rate. |

---

## 4. Confirmed Findings, Evidence & Remediations

### SEC-01: Arbitrary API Base URL Parameter Override & Silent Exfiltration
- **Severity**: **HIGH** (CVSS 7.5 / CWE-601 / CWE-200)
- **Affected Component**: [script.js](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/script.js) (`getAuthoritativeApiBaseUrl`)
- **Root Cause**: `script.js` previously set `API_BASE_URL` directly from `new URLSearchParams(window.location.search).get('api_url')` without validating the host or execution context.
- **Attack Scenario**: An attacker could craft a link:  
  `https://vasiharanb.github.io/geospatial-file-measurement-api/?api_url=https://attacker-c2.com`  
  A victim opening this link would see the legitimate application interface, but any uploaded Shapefile or KML survey containing proprietary boundary coordinates would be silently POSTed directly to the attacker's server.
- **Phase 11.1 Hardening & Localhost Restriction**:
  - Implemented strict context-aware origin validation in `getAuthoritativeApiBaseUrl()`.
  - External untrusted URLs are unconditionally rejected.
  - On the deployed GitHub Pages frontend, `localhost` / `127.0.0.1` API overrides are strictly **prohibited**.
  - `localhost` / `127.0.0.1` overrides are permitted **only** when the frontend is running in its intended local development context (`window.location.hostname === 'localhost' || '127.0.0.1'`).
  - `window.ENV_API_BASE_URL` is validated using the exact same trust policy.
  - Rejected overrides fall back safely to the authoritative backend default (`https://geospatial-measurement-api-9tqz.onrender.com`) and log a clear warning to `console.warn`.
  - **Zero innerHTML invariant**: Strict DOM property assignment (`textContent`, `createElement`, `setAttribute`) preserved across [script.js](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/script.js).
- **Regression Verification**: [tests/test_security_audit.py Scenario 7](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-02: Missing Defense-in-Depth HTTP Security Headers & Content Security Policy
- **Severity**: **MEDIUM** (CWE-693: Protection Mechanism Failure)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py) (`security_headers_middleware`)
- **Root Cause**: FastAPI lacked standard defense-in-depth response headers and did not enforce a Content Security Policy on API routes.
- **Remediation**: Implemented `security_headers_middleware` in [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py) injecting:
  - `X-Content-Type-Options: nosniff` (prevents MIME sniffing)
  - `X-Frame-Options: DENY` (prevents clickjacking)
  - `X-XSS-Protection: 1; mode=block` (legacy XSS filter defense)
  - `Referrer-Policy: strict-origin-when-cross-origin` (prevents path leakage in referrers)
  - `Permissions-Policy: geolocation=(), camera=(), microphone=()` (blocks unauthorized browser APIs)
  - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (applied to `/api/*` endpoints to block script/object execution in API responses)
- **Frontend CSP Compatibility Analysis**:
  - A blanket `default-src 'self'` policy in `index.html` would break core frontend components:
    * **Leaflet Tile Layers**: OpenStreetMap (`*.tile.openstreetmap.org`), Esri Satellite/Topo (`server.arcgisonline.com`), OpenTopoMap (`*.tile.opentopomap.org`).
    * **Google Fonts**: Stylesheet (`fonts.googleapis.com`), webfonts (`fonts.gstatic.com`).
    * **Three.js**: Import map scripts and worker threads.
  - Distinguishing Edge vs Application Headers: Render's reverse proxy terminates TLS, applies Cloudflare DDoS protections, and manages edge HTTP/2 framing. Application security headers set in [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py) pass cleanly through Render's proxy to the client.
- **Regression Verification**: [tests/test_security_audit.py Scenarios 1 & 11](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-03: Missing Request Rate Limiting & Proxy IP Derivation
- **Severity**: **MEDIUM** (CWE-770: Allocation of Resources Without Limits)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py) (`rate_limiting_middleware`), [.env.example](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/.env.example)
- **Root Cause**: The API lacked request rate limiting, and standard reverse proxy setups can allow clients to spoof their IP via untrusted `X-Forwarded-For` headers.
- **Phase 11.1 Hardening & IP Derivation**:
  - Implemented `get_client_ip(request)`:
    * **Priority 1**: `CF-Connecting-IP` header (injected immutably by Cloudflare at Render's edge; client cannot spoof this through the Cloudflare proxy).
    * **Priority 2**: Direct peer socket `request.client.host`.
    * **Anti-Spoofing**: Does **not** blindly trust client-supplied `X-Forwarded-For` headers, preventing rate-limit evasion via arbitrary header spoofing.
  - **Differentiated Rate Limits**:
    * **Expensive File Uploads / Processing**: `UPLOAD_RATE_LIMIT_PER_MINUTE=60` (`POST /api/files/`). Uploading and parsing 25 MB Shapefiles/KML geometries is CPU/memory-intensive. 60 requests/min provides generous headroom for valid users while preventing resource starvation.
    * **Lightweight Read Endpoints**: `READ_RATE_LIMIT_PER_MINUTE=300` (e.g. `GET /api/files/`, `GET /api/files/{id}/`, `GET /api/files/{id}/measurements/`).
    * **Exemptions**: OPTIONS preflights, `/api/health/`, `/docs`, `/openapi.json`.
  - **429 & Retry-After Verification**: Tested locally that requests exceeding the sliding window receive HTTP 429 with `Retry-After: 60`.
  - **Multi-Client Isolation**: Verified that rate-limiting Client A does not impact requests from Client B.
  - **In-Memory Concurrency Architecture**: Documented that the current thread-safe sliding window is process-bound. In multi-worker or horizontally scaled container clusters, a shared Redis token-bucket store is required (scheduled for Phase 12).
- **Regression Verification**: [tests/test_security_audit.py Scenarios 6, 9, & 10](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-04: Container Execution as Root Superuser in Production Dockerfile
- **Severity**: **MEDIUM** (CWE-250: Execution with Unnecessary Privileges)
- **Affected Component**: [Dockerfile](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/Dockerfile)
- **Root Cause**: The container executed as default UID 0 (`root`).
- **Remediation**: Added dedicated non-root system user `appuser` (UID 1000), set directory ownership on `/app` and `/app/storage/uploads`, and dropped privileges via `USER appuser`.
- **Regression Verification**: [tests/test_security_audit.py Scenario 5](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-05: Undefined SecurityException Triggering 500 NameError
- **Severity**: **LOW / CODE QUALITY** (CWE-390)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py)
- **Root Cause**: Staging path traversal detection raised `SecurityException`, but the class was never defined, resulting in an unhandled `NameError` (HTTP 500).
- **Remediation**: Defined `SecurityException(GeospatialAPIError)` mapped cleanly to `HTTP_400_BAD_REQUEST`.
- **Regression Verification**: [tests/test_security_audit.py Scenario 3](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-06: Incomplete URI Scheme Filtering in KML SSRF Defense
- **Severity**: **LOW** (CWE-918: Server-Side Request Forgery)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py) (`validate_and_sanitize_kml`)
- **Root Cause**: Static prefix filter checked only `http://`, `https://`, `ftp://`, `file://`.
- **Remediation**: Upgraded check using regex `^[a-zA-Z][a-zA-Z0-9+.-]*://` and explicit blocking for `//`, `\\\\`, `data:`, `javascript:`, `vbscript:`, and `netdoc:`.
- **Regression Verification**: [tests/test_security_audit.py Scenario 2](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-07: Unsanitized Resource ID Reflection in 404 Error Detail
- **Severity**: **LOW** (CWE-79 / CWE-116)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py) (`get_file_detail`, `get_file_measurements`)
- **Root Cause**: Raw `id` parameter was reflected directly in 404 error messages.
- **Remediation**: Sanitized reflected ID using `re.sub(r"[^a-zA-Z0-9_\-]", "", clean_id)[:64]`.
- **Regression Verification**: [tests/test_security_audit.py Scenario 4](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/test_security_audit.py). Result: **PASS**.

---

### SEC-08: Blind Try-Except-Pass in Property Serialization
- **Severity**: **LOW / CODE QUALITY** (CWE-703)
- **Affected Component**: [main.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/main.py)
- **Root Cause**: Broad `except Exception: pass` during numpy scalar conversion.
- **Remediation**: Constrained to `except (ValueError, TypeError, AttributeError):` with debug logging.
- **Regression Verification**: Bandit AST analysis verified 0 issues. Result: **PASS**.

---

## 5. Live Production Checks Actually Performed

Low-volume, read-only operational checks were conducted against production infrastructure:

1. **Frontend Integrity (GitHub Pages)**:
   - `GET https://vasiharanb.github.io/geospatial-file-measurement-api/`
   - Response: `HTTP 200 OK`
   - Headers: `server: GitHub.com`, `strict-transport-security: max-age=31556952`
2. **Backend Operational Status (Render)**:
   - `GET https://geospatial-measurement-api-9tqz.onrender.com/api/health/`
   - Response: `HTTP 200 OK`, `{"status": "ok", "service": "Geospatial File Measurement API"}`
   - TLS/HTTPS: Valid certificate issued via Cloudflare edge reverse proxy.
3. **Interactive Documentation**:
   - `GET https://geospatial-measurement-api-9tqz.onrender.com/docs` -> `HTTP 200 OK`
   - `GET https://geospatial-measurement-api-9tqz.onrender.com/openapi.json` -> `HTTP 200 OK`

---

## 6. Access Control & Privacy Analysis: Current vs. Phase 12 Developer Portal

### Current Public Utility Posture:
- **Authentication**: **None**. The API currently operates as an open, anonymous geospatial measurement service.
- **Object Access Model**: Files and measurements are referenced via UUIDv4 identifiers.
  - *Cryptographic Randomness*: UUIDv4 provides 122 bits of entropy (~$5.3 \times 10^{36}$ possible values). Brute-force guessing or ID enumeration is computationally infeasible.
  - *Crucial Security Distinction*: **UUID unpredictability is NOT authorization.**
  - *Privacy Implication*: Any entity possessing a file's UUID (via shared links, HTTP referrers, proxy logs, or browser history) can retrieve its feature geometries and calculated measurements.
  - *Accepted Design Decision*: For the initial public demonstration phase, this open access model is accepted.

### Mandatory Security Controls for Phase 12 (Developer Portal):
To transition this service to a secure multi-tenant developer platform, the following controls are mandatory:
1. **User and Project Ownership**:
   - Extend `FileRecord` to include `project_id` and `user_id` foreign keys.
   - Every file upload must be linked directly to an authenticated project.
2. **Row-Level Ownership Verification**:
   - Every `GET`, `POST`, or `DELETE` on `/api/files/{id}/` must verify that the requesting API key belongs to the project owning the file record. Unauthorized requests must return HTTP 403 Forbidden (or HTTP 404 to prevent existence discovery).
3. **Isolated Per-Project API Keys**:
   - Keys formatted as `gfm_live_<32-byte-hex>` or `gfm_test_<32-byte-hex>`.
   - Keys must be hashed using SHA-256 before database storage; raw keys are displayed only once upon generation.
4. **Key Revocation & Usage Quotas**:
   - Instant revocation capability for compromised keys.
   - Enforce per-project request and byte-volume rate limits.
5. **Data Retention & Secure Deletion Policies**:
   - Provide `DELETE /api/files/{id}/` for explicit file purge by developers.
   - Configurable automatic TTL (e.g. 24-hour cleanup for transient survey calculations).
   - Secure disk unlink removing temporary files from the filesystem.

---

## 7. Checks Explicitly Not Executed

In strict adherence to ethical penetration testing and provider Terms of Service:
- **No Volumetric Flooding / DoS**: No denial-of-service tests were sent to production infrastructure.
- **No High-Volume 429 Probes on Render**: Rate limiter saturation was validated exclusively against local test instances.
- **No DAST Scanners Against Cloud Providers**: Automated fuzzers (ZAP, Burp) were not directed at GitHub Pages or Render.
- **No Real PII / Coordinate Harvesting**: Real-world property boundaries were never collected or queried.

---

## 8. Verification & Test Suite Summary

Execution output of the master test runner [tests/run_all_tests.py](file:///c:/Users/vasiharan/Downloads/Geospatial%20File%20Measurement%20API/tests/run_all_tests.py):

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

>>> Running Part 10 — Defensive Security Audit & Hardening (test_security_audit.py) [11 scenarios]...
[PASS] Part 10 — Defensive Security Audit & Hardening passed (11/11)

================================================================================
SUMMARY: 9/9 SUITES PASSED (147 SCENARIOS VERIFIED 100%)
================================================================================
```

---

## 9. Residual Risks & Technical Debt

1. **In-Memory Rate Limiting**: The current sliding-window rate limiter stores state in memory within the single FastAPI process. While effective for single-instance deployments, horizontal scaling across multiple instances requires a distributed cache (Redis) to share quotas.
2. **Anonymous Data Exposure via UUID Leak**: While UUIDs cannot be brute-forced, any leaked UUID allows read access until Phase 12 developer authentication and ownership verification are deployed.
3. **Ephemeral Disk on Free-Tier Hosting**: Render free instances run on ephemeral filesystems. Uploads and local SQLite data reset on container restart (to be addressed with PostgreSQL + S3 object storage in production infrastructure planning).

---

## 10. Phase 11.1 Security Closure Gate Verdict

| Gate Criteria | Status | Evidence / Notes |
| :--- | :--- | :--- |
| **Audit Evidence Reconciled** | **PASSED** | 147 scenarios across 9 suites verified 100%. Discrepancies resolved. |
| **Frontend API Trust Policy** | **PASSED** | External overrides blocked; localhost blocked on production; zero innerHTML. |
| **Security Headers & API CSP** | **PASSED** | Nosniff, DENY, Referrer-Policy, Permissions-Policy, API CSP enforced. |
| **Rate Limiter & IP Derivation** | **PASSED** | `CF-Connecting-IP` used safely; 60 uploads/min vs 300 reads/min; 429 verified. |
| **Access Control Model Corrected** | **PASSED** | UUID unpredictability explicitly documented; Phase 12 architecture specified. |
| **Static & Dependency Security** | **PASSED** | 0 Bandit issues, 0 CVEs on pip-audit, 0 credential leaks in Git. |
| **Production Health Verified** | **PASSED** | GitHub Pages and Render endpoints operational on TLS/HTTPS. |

**GATE STATUS: CLOSED & PASSED.**  
The Geospatial File Measurement API is fully hardened and verified. The codebase is ready to proceed to **Phase 12 — Developer Accounts, Projects, and API Key Management**.
