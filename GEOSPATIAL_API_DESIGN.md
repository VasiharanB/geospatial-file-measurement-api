# Architectural & Technical Analysis: Geospatial File Measurement API

**Project:** Geospatial File Measurement API  
**Framework:** FastAPI (Python 3.10+)  
**Target Repository:** Production-grade Backend API (Evaluation & Public GitHub Ready)  

---

## 1. Specification Breakdown: Mandatory vs. Optional Scope

| Domain | Mandatory Requirements (Strict Scope) | Optional Enhancements (Future / Production Scale) |
| :--- | :--- | :--- |
| **Backend Framework** | FastAPI with ASGI runner (Uvicorn). | Celery + Redis worker queue for asynchronous job execution. |
| **File Formats** | `.kml` and `.zip` containing a Shapefile (`.shp`, `.shx`, `.dbf`, `.prj`). | GeoJSON, GeoPackage (`.gpkg`), FlatGeobuf, GeoTIFF. |
| **Feature Extraction** | Feature ID/index, geometry type, geometry representation, CRS, properties/attributes. Unsupported geometries handled gracefully. | Spatial indexing (R-Tree), topology simplification (Douglas-Peucker). |
| **Measurements** | Polygon / MultiPolygon $\rightarrow$ Area ($m^2$); LineString / MultiLineString $\rightarrow$ Length ($m$); Point / MultiPoint $\rightarrow$ No measurement required. | Centroid coordinates, bounding box (bbox), polygon perimeter, multi-part geometry breakdown. |
| **CRS Handling** | Reject direct degree calculations; detect input CRS; reproject to appropriate projected CRS before measurement; explainable strategy in documentation. | User-specified override CRS query parameter, custom local projection grid files (.gsb). |
| **API Endpoints** | `POST /api/files/`, `GET /api/files/{id}/`, `GET /api/files/{id}/measurements/`. | Pagination on feature lists, filtering by geometry type, file deletion (`DELETE`). |
| **Database & Persistence** | Persist file metadata, features, and measurements for retrieval by ID. | PostGIS spatial database, AWS S3 / MinIO object storage. |
| **Documentation** | Detailed README: Setup, API docs, Architecture, Data flow, CRS rationale, Learnings, Future scope. | Interactive Swagger/Redoc theming, Postman collection export. |

---

## 2. Recommended Architecture

The system follows a **Layered Service Architecture** designed to cleanly isolate fast I/O ingestion from CPU-bound geospatial computation and relational persistence.

```
                              ┌────────────────────────────────────────┐
                              │           Client Application           │
                              └──────────────────┬─────────────────────┘
                                                 │ HTTP / REST
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                          FastAPI Layer                                           │
│  ┌─────────────────────────┐  ┌───────────────────────────┐  ┌────────────────────────────────┐  │
│  │   Request Validation    │  │     API Routers & DTOs    │  │    Global Exception Handler    │  │
│  │  (File size / mime / PK)│  │   (/api/files endpoints)  │  │   (HTTP 400, 415, 422, 500)    │  │
│  └─────────────────────────┘  └─────────────┬─────────────┘  └────────────────────────────────┘  │
└─────────────────────────────────────────────┼────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       Service / Core Layer                                       │
│                                                                                                  │
│   ┌────────────────────────┐      ┌─────────────────────────┐      ┌─────────────────────────┐   │
│   │   Safe Unpack & I/O    │ ───► │    Geospatial Parser    │ ───► │   CRS & Measurement     │   │
│   │   - Zip-slip guard     │      │   - GeoPandas / Pyogrio │      │   - Detect CRS          │   │
│   │   - Defused XML parser │      │   - Extract features    │      │   - Auto-UTM / Eq-Area  │   │
│   │   - Temp workspace mgmt│      │   - Attribute dicts     │      │   - Shapely Area/Length │   │
│   └────────────────────────┘      └─────────────────────────┘      └─────────────────────────┘   │
└─────────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       Persistence Layer                                          │
│   ┌────────────────────────────────────────────────┐   ┌─────────────────────────────────────┐   │
│   │        SQLAlchemy 2.0 (SQLite / WAL Mode)      │   │           Local File Store          │   │
│   │  Tables: files, features, measurements         │   │   uploads/{file_id}/original_file   │   │
│   └────────────────────────────────────────────────┘   └─────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Concurrency & Threading Model
- FastAPI endpoints run on an asynchronous event loop (`async def`).
- Geospatial operations (via GDAL, GEOS, and PROJ C-libraries) are CPU-bound and block the thread.
- **Pattern:** CPU-intensive file parsing and measurement routines are dispatched to worker threads via `fastapi.concurrency.run_in_threadpool` or `asyncio.to_thread`. This keeps the API event loop non-blocking and responsive during file uploads.

---

## 3. Project Folder Structure

A production-ready layout adhering to standard FastAPI patterns and clean separation of concerns:

```text
geospatial-file-measurement-api/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application factory, middleware, CORS
│   ├── config.py                   # Pydantic BaseSettings (env configs, storage paths, limits)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                 # Dependency injection (DB session, storage paths)
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py           # V1 endpoint aggregation
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           └── files.py        # POST /, GET /{id}/, GET /{id}/measurements/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exceptions.py           # Custom Domain Exceptions (CRSNotFoundError, InvalidZipError)
│   │   ├── error_handlers.py       # FastAPI exception handlers returning clean JSON errors
│   │   ├── security.py             # File sanitization, ZipSlip check, size limits
│   │   └── logging.py              # Structured logging configuration
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                 # Declarative Base
│   │   └── session.py              # SQLAlchemy engine and session factory
│   ├── models/                     # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── file_record.py          # Uploaded file metadata
│   │   └── feature_record.py       # Extracted features and measurement details
│   ├── schemas/                    # Pydantic validation schemas (DTOs)
│   │   ├── __init__.py
│   │   ├── file.py                 # FileUploadResponse, FileDetailResponse
│   │   ├── feature.py              # FeatureSchema, GeometrySchema
│   │   └── measurement.py          # MeasurementResponse, MeasurementSummary
│   └── services/                   # Business logic
│       ├── __init__.py
│       ├── storage_service.py      # Safe temp directory management and file writing
│       ├── zip_extractor.py        # Safe extraction and Shapefile component validation
│       ├── geospatial_parser.py    # KML and Shapefile feature parsing
│       ├── crs_service.py          # CRS identification & projected transformation engine
│       └── measurement_service.py  # Area and length computation engine
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Test fixtures (test DB, TestClient, sample files)
│   ├── data/                       # Test datasets
│   │   ├── sample_polygons.kml
│   │   ├── sample_shapefile.zip
│   │   ├── missing_prj.zip
│   │   ├── invalid_extension.txt
│   │   └── malicious_traversal.zip
│   ├── test_api.py                 # Integration tests for API endpoints
│   ├── test_crs_service.py         # Unit tests for CRS selection and transformation
│   ├── test_measurements.py        # Unit tests for mathematical calculations
│   └── test_security.py            # Unit tests for Zip-Slip, size limits, format checks
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml / requirements.txt
└── README.md
```

---

## 4. Recommended Python & Geospatial Libraries

| Library | Version / Role | Justification |
| :--- | :--- | :--- |
| **FastAPI** | `^0.110.0` | High performance, automatic OpenAPI/Swagger documentation, native type hints, dependency injection. |
| **Pydantic** | `^2.6.0` | High-performance data validation and serialization for GeoJSON-like payloads. |
| **GeoPandas** | `^0.14.0` | The standard high-level Python geospatial abstraction. Combines Shapely geometries, Fiona/Pyogrio I/O, and attribute tables into a unified dataframe. |
| **Pyogrio / Fiona** | `^0.7.0` / `^1.9.0` | High-speed C-engine bindings for GDAL/OGR vector drivers. Reads Shapefiles from ZIP files and parses KML files. |
| **Shapely** | `^2.0.0` | Direct GEOS wrapper for geometry inspection, validation (`is_valid`), area, and length measurements. |
| **PyProj** | `^3.6.0` | PROJ library binding. Used for CRS detection, looking up EPSG codes, and calculating UTM zones from coordinates. |
| **SQLAlchemy** | `^2.0.0` | Modern Python ORM with native JSON/JSONB column support for attributes and geometry structures. |
| **defusedxml** | `^0.7.1` | Hardens XML/KML processing against XML External Entity (XXE) and entity expansion attacks. |
| **pytest & httpx** | `^8.0.0` | Full asynchronous and synchronous integration testing of FastAPI endpoints. |

---

## 5. End-to-End Data Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as FastAPI Router
    participant Sec as Security & Storage
    participant Geo as Geospatial Parser
    participant CRS as CRS & Measurement Engine
    participant DB as SQLite DB

    Client->>API: POST /api/files/ (file upload)
    API->>Sec: Validate extension (.kml / .zip) and size
    alt Validation Failed
        Sec-->>API: Reject with HTTP 400 / 413 / 415
        API-->>Client: Error response
    end

    Sec->>Sec: Save to isolated UUID directory
    alt Is .zip (Shapefile)
        Sec->>Sec: Check for Zip-Slip & bomb; Extract
        Sec->>Sec: Verify mandatory components (.shp, .shx, .dbf)
    else Is .kml
        Sec->>Sec: Sanitize XML with defusedxml
    end

    API->>Geo: Parse file (via GeoPandas / Pyogrio)
    Geo->>Geo: Extract feature list, geometries, properties & input CRS
    
    API->>CRS: Process measurements
    loop For each feature
        CRS->>CRS: Inspect geometry type
        alt Point / MultiPoint
            CRS->>CRS: Record measurement: null (Skipped)
        alt Polygon / MultiPolygon OR LineString / MultiLineString
            CRS->>CRS: Detect input CRS (fallback if missing)
            CRS->>CRS: Compute centroid; Select projected target CRS (e.g. UTM)
            CRS->>CRS: Reproject geometry to Target CRS
            CRS->>CRS: Calculate Area (m²) or Length (m)
        alt Unsupported / GeometryCollection
            CRS->>CRS: Flag as unsupported; Record reason
        end
    end

    API->>DB: Store FileRecord, FeatureRecords, and Measurements
    DB-->>API: Persisted (file_id)
    API-->>Client: HTTP 201 Created (file_id, status, feature_count)

    Note over Client,API: Retrieval Flow
    Client->>API: GET /api/files/{id}/
    API->>DB: Fetch file metadata and features
    DB-->>API: File and features
    API-->>Client: HTTP 200 OK (File info, features, geometry types, attributes)

    Client->>API: GET /api/files/{id}/measurements/
    API->>DB: Fetch measurements for file_id
    DB-->>API: Measurement records
    API-->>Client: HTTP 200 OK (Calculated area/length, projected CRS used, units)
```

---

## 6. Database & Storage Strategy

### Primary Recommendation: SQLite (WAL Mode) + SQLAlchemy 2.0
- **Zero-Barrier Evaluation:** Evaluators and reviewers can run tests or boot the service with zero external dependencies (no running PostgreSQL instance or Docker container strictly required).
- **Native JSON Support:** Modern SQLite supports JSON functions and native JSON columns, allowing dynamic GeoJSON geometries and varying attribute schemas to be stored cleanly.
- **High Concurrency:** Setting `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;` allows concurrent readers alongside active writers without database locking issues.

### Production Alternative: PostgreSQL + PostGIS
- Ideal for production systems performing server-side spatial indexing and spatial SQL queries (`ST_Intersects`, `ST_Area`).
- The application uses standard SQLAlchemy 2.0 ORM mappings and a configurable `DATABASE_URL`, allowing seamless switching from SQLite to PostgreSQL with a single configuration flag.

### File Asset Retention
- Uploaded archives are assigned a UUID and stored at `storage/uploads/{file_id}/`.
- Temporary working directories created during ZIP decompression are automatically removed inside a `finally` block or context manager after processing completes.

---

## 7. Coordinate Reference System (CRS) Strategy

### Why Planar Calculations on Geographic CRS Are Prohibited
Geographic Coordinate Systems (such as **WGS 84 / EPSG:4326**, the standard for KML and GPS) represent locations on an ellipsoidal Earth using **angular degrees** (latitude and longitude):
- $1^\circ$ of latitude is approximately $111\text{ km}$ everywhere.
- $1^\circ$ of longitude is approximately $111\text{ km}$ at the equator, but shrinks to $78\text{ km}$ at $45^\circ$, and approaches $0\text{ km}$ near the poles.
- Applying Euclidean formulas ($\Delta x \times \Delta y$ or $\sqrt{\Delta x^2 + \Delta y^2}$) directly on degrees yields **"square degrees"**, which have no constant metric area and distort severely depending on latitude.

### Why Web Mercator (EPSG:3857) Must NOT Be Used for Area Measurement
Web Mercator measures in nominal meters, but its conformal cylindrical projection distorts scale drastically as latitude moves away from the equator (the Greenland problem: Greenland appears comparable in size to Africa on Web Mercator, despite Africa being 14 times larger). Measuring areas in EPSG:3857 produces major calculation errors.

### The Recommended Reprojection Engine

A **Centroid-Based Local UTM Selection with Equal-Area Fallback**:

```
Input Geometry
      │
      ▼
Detect Input CRS
(KML -> EPSG:4326; Shapefile -> .prj file)
      │
      ▼
Transform coordinates to standard WGS 84 (EPSG:4326)
      │
      ▼
Compute Feature Bounding Box & Centroid (lon, lat)
      │
      ├─────────────────────────────────────────┐
      │ Width < 6° Longitude                    │ Width ≥ 6° Longitude (Spans multiple zones)
      ▼                                         ▼
Auto-Determine Local UTM Zone             Select Global Equal-Area Projection
zone = floor((lon + 180) / 6) + 1         (EPSG:6933 - World Cylindrical Equal Area
hemisphere: EPSG:326XX (N) / 327XX (S)     or Albers Equal Area for continents)
      │                                         │
      └────────────────────┬────────────────────┘
                           │
                           ▼
Reproject Geometry to Selected Projected CRS (in meters)
                           │
                           ▼
Perform Planar Measurement
- Polygon: area in m²
- LineString: length in meters
```

### Response Transparency
Every measurement response explicitly includes the projection metadata:
```json
{
  "feature_id": 1,
  "geometry_type": "Polygon",
  "measurement": {
    "type": "area",
    "value": 15420.55,
    "unit": "square_meters",
    "projected_crs": "EPSG:32632 (WGS 84 / UTM zone 32N)",
    "input_crs": "EPSG:4326"
  }
}
```

---

## 8. Error Handling & Edge Cases

The system enforces a **two-tier error model**:
- **File-Level Errors:** Reject the upload or query with an explicit HTTP status code.
- **Feature-Level Degradation:** Corrupt or unsupported geometries within a valid file do not cause the entire file processing to fail.

### 1. HTTP Status Code Mapping

| Condition | HTTP Status | Response Payload |
| :--- | :--- | :--- |
| File is not `.kml` or `.zip` | `415 Unsupported Media Type` | `{"error": "UnsupportedFileType", "detail": "Allowed: .kml, .zip"}` |
| Corrupt archive or missing `.shp` | `400 Bad Request` | `{"error": "InvalidShapefileStructure", "detail": "Missing mandatory .shp file"}` |
| File size exceeds limit (e.g., 25MB) | `413 Payload Too Large` | `{"error": "FileTooLarge", "detail": "Max allowed size is 25MB"}` |
| File contains zero valid features | `422 Unprocessable Entity` | `{"error": "NoFeaturesFound", "detail": "No parseable features detected"}` |
| Non-existent file ID on GET | `404 Not Found` | `{"error": "FileNotFound", "detail": "File ID not found"}` |
| Internal parsing crash | `500 Internal Server Error` | Sanitized error message with an internal correlation ID |

### 2. Feature-Level Degradation Strategy
For a file containing 100 features where feature #12 is malformed or unsupported:
- **Valid Polygon:** `{"feature_id": 1, "type": "Polygon", "measurement": {"value": 4520.12, "unit": "square_meters"}}`
- **Point:** `{"feature_id": 2, "type": "Point", "measurement": null, "note": "Point geometry requires no measurement"}`
- **Unsupported (GeometryCollection, TIN):** `{"feature_id": 3, "type": "GeometryCollection", "measurement": null, "status": "unsupported", "error": "GeometryCollection measurements are not supported"}`
- **Self-Intersecting Polygon:** Attempts automatic repair via `shapely.validation.make_valid()`. If repair fails, flags `{"status": "invalid_geometry", "error": "Self-intersection could not be repaired"}` without terminating the job.

---

## 9. Security Considerations

File uploads and ZIP archives introduce distinct security risks that must be defended against:

| Threat Vector | Mechanism | Defensive Implementation |
| :--- | :--- | :--- |
| **1. Zip Slip (Path Traversal)** | Malicious relative paths in zip entries (e.g. `../../etc/passwd`). | Verify every extracted path resides strictly inside the temporary sandbox directory: `os.path.commonpath([target, base]) == base`. |
| **2. Decompression Bomb (Zip Bomb)** | Small archive decompressing to hundreds of gigabytes. | Inspect `ZipInfo.file_size` totals before extraction; reject archives exceeding 100MB uncompressed or compression ratios above 100:1. |
| **3. XXE Injection** | Malicious XML DOCTYPE declarations in KML resolving system files or SSRF endpoints. | Parse XML exclusively via `defusedxml` with external entity resolution disabled. |
| **4. Memory Exhaustion** | Oversized file uploads overwhelming server RAM. | Stream uploaded files in chunks; enforce a hard payload cutoff before buffering in memory. |
| **5. File Extension Spoofing** | Executables renamed to `.zip` or `.kml`. | Validate file magic bytes (PK header `0x04034b50` for ZIP, XML declaration for KML). |

---

## 10. Testing Strategy

The test suite uses `pytest` and `httpx` across three test categories:

### 1. Unit Tests
- **Measurement Calculations:** Test known geometric shapes (e.g., $100\text{ m} \times 100\text{ m}$ square verifies area $= 10,000\text{ m}^2 \pm 0.1\%$; $500\text{ m}$ straight line verifies length).
- **Point Exemption:** Confirm that Point geometries return `None` for measurement without errors.
- **CRS Selection:** Verify that Paris coordinates ($2.35^\circ\text{ E}, 48.85^\circ\text{ N}$) resolve to UTM Zone 31N (`EPSG:32631`) and New York coordinates resolve to UTM Zone 18N (`EPSG:32618`).
- **Security Defenses:** Assert that synthetic Zip-Slip archives trigger a `ZipTraversalError`, and malicious XML entities trigger `DefusedXmlException`.

### 2. Integration Tests
- `POST /api/files/` with valid `.kml` $\rightarrow$ `201 Created`.
- `POST /api/files/` with valid Shapefile `.zip` $\rightarrow$ `201 Created`.
- `POST /api/files/` with unsupported file types (`.txt`) $\rightarrow$ `415 Unsupported Media Type`.
- `POST /api/files/` with incomplete Shapefile (missing `.shp` or `.dbf`) $\rightarrow$ `400 Bad Request`.
- `GET /api/files/{id}/` $\rightarrow$ `200 OK` with metadata and feature list.
- `GET /api/files/{id}/measurements/` $\rightarrow$ `200 OK` with area and length calculations.
- `GET /api/files/{non_existent}/` $\rightarrow$ `404 Not Found`.

---

## 11. Recommended Development Phases

```text
Phase 1: Project Skeleton & Environment Setup
├── Project configuration (pyproject.toml / requirements.txt)
├── FastAPI app factory, Pydantic BaseSettings, and CORS setup
└── SQLAlchemy 2.0 SQLite database models and session setup

Phase 2: Security & File Ingestion Service
├── Upload validation (magic byte checking, MIME type, size limit)
├── Safe ZIP extraction engine with Zip-Slip and Zip-Bomb defenses
└── KML input sanitization via defusedxml

Phase 3: Geospatial Parser & Feature Extraction
├── KML parser extracting Placemarks, attributes, and geometries
├── Shapefile parser extracting features via GeoPandas/Pyogrio
└── Graceful handler for unsupported and invalid geometries

Phase 4: CRS Engine & Measurement Module
├── Input CRS detection and normalization
├── Centroid-based projected UTM / Equal-Area CRS selection
└── Planar calculation engine (Area for Polygons, Length for LineStrings)

Phase 5: API Endpoints & Persistence Layer
├── POST /api/files/
├── GET /api/files/{id}/
├── GET /api/files/{id}/measurements/
└── Global exception handlers and response DTO schemas

Phase 6: Testing, Docker & Documentation
├── Automated unit, integration, and security test suite in pytest
├── Dockerfile and docker-compose.yml configuration
└── Production README.md covering setup, API docs, architecture, CRS rationale, and learnings
```
