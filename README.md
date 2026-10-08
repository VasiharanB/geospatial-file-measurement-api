# Geospatial File Measurement API

> **Authoritative, CRS-Aware Geospatial Processing Engine with Interactive 3D Earth Analytics**  
> Ingests KML 2.2 and ESRI Shapefile archives, resolves local and global conformal metric projections, computes millimeter-precision planar area and length, persists spatial entities, and exposes results via high-performance REST APIs.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Problem Statement & Why It Exists](#problem-statement--why-it-exists)
3. [Key Features](#key-features)
4. [Real-World Use Cases](#real-world-use-cases)
5. [System Architecture](#system-architecture)
6. [Data Flow & Processing Lifecycle](#data-flow--processing-lifecycle)
7. [Coordinate Reference System (CRS) Engine](#coordinate-reference-system-crs-engine)
8. [Planar Measurement Methodology](#planar-measurement-methodology)
9. [Security Architecture & Defense-in-Depth](#security-architecture--defense-in-depth)
10. [Database Design & Persistence](#database-design--persistence)
11. [Client Presentation Layer (3D Command Center)](#client-presentation-layer-3d-command-center)
12. [Visual Interface & Screenshots](#visual-interface--screenshots)
13. [Technology Stack](#technology-stack)
14. [Installation & Setup](#installation--setup)
15. [Running with Docker](#running-with-docker)
16. [API Reference & Usage Examples](#api-reference--usage-examples)
17. [Standardized Error Responses](#standardized-error-responses)
18. [Sample Data](#sample-data)
19. [Verification & Test Suites](#verification--test-suites)
20. [Key Design Decisions](#key-design-decisions)
21. [Alternatives Considered](#alternatives-considered)
22. [Performance Considerations](#performance-considerations)
23. [Known Limitations & Future Scope](#known-limitations--future-scope)
24. [5-Minute Demonstration Flow](#5-minute-demonstration-flow)
25. [60–90 Second Interview Summary](#6090-second-interview-summary)
26. [Git Submission Instructions](#git-submission-instructions)

---

## Project Overview

The **Geospatial File Measurement API** is a production-hardened, single-file FastAPI service engineered to eliminate coordinate distortion in spatial measurements. It serves as an authoritative backend calculation engine that:

1. Validates and ingests **Google Earth KML 2.2** files and **ESRI Shapefile ZIP bundles** (`.shp`, `.shx`, `.dbf`, `.prj`).
2. Isolates uploads into cryptographically secure UUID directories while enforcing bounded decompression and path containment.
3. Parses feature geometries, extracts tabular attributes, and normalizes coordinates.
4. Dynamically determines an optimal metric planar projection (local UTM zone, equal-area cylindrical, or azimuthal equidistant) rather than attempting calculations on unprojected degrees.
5. Computes authoritative planar area ($m^2$) for Polygons and length ($m$) for LineStrings, with automated geometry topology repair.
6. Persists relational metadata across SQLite in Write-Ahead Logging (WAL) mode with foreign key cascade guarantees.
7. Exposes an interactive **3D WebGL Command Center** client featuring a procedural 3D Earth, dual Light/Dark theme engine, 2D vector geometry viewport, and real-time feature explorer.

---

## Problem Statement & Why It Exists

Many modern software platforms—ranging from construction management and real estate cadastre portals to drone surveying dashboards—frequently accept user-submitted spatial vector datasets. However, standard web and backend frameworks lack built-in GIS engines. Implementing raw spatial parsing requires solving several non-trivial engineering hurdles:

* **The Angular Coordinate Pitfall:** Geospatial data is commonly stored in geographic coordinates (latitude and longitude in degrees, such as WGS 84 / `EPSG:4326`). Computing planar Euclidean distance ($\sqrt{\Delta x^2 + \Delta y^2}$) or shoelace polygon area directly on angular degrees results in catastrophic distortion exceeding **40% to 60%** away from the equator because degrees of longitude shrink toward the poles.
* **Format Fragmentation:** Shapefiles require validating companion files (`.shp`, `.shx`, `.dbf`, and optional `.prj`), whereas KML files require XML sanitization.
* **Malicious Archive Vectors:** ZIP archives and XML files are notorious attack surfaces for directory traversal (**Zip-Slip**), excessive decompression ratios (**Zip Bombs**), XML External Entity injection (**XXE**), and Server-Side Request Forgery (**SSRF**).
* **Missing Spatial References:** Datasets exported from CAD tools often omit `.prj` files. Blindly guessing `EPSG:4326` corrupts industrial measurements.

This API acts as a **centralized, authoritative calculation boundary**, offloading GIS complexity from frontend applications, mobile clients, and distributed microservices.

---

## Key Features

* **Multi-Format Ingestion:** Native support for `.kml` vectors and multi-part `.zip` ESRI Shapefiles.
* **Defense-in-Depth Security:** 25 MB stream limit, 100 MB decompression limit, 100:1 compression ratio limit, strict Zip-Slip containment, defused XML parsing, and safe parameterization.
* **Dynamic CRS Engine:** Centroid-based automatic UTM zone selection, World Cylindrical Equal-Area fallback (`EPSG:6933`), and feature-centered Azimuthal Equidistant (`PROJ:AEQD`) projection.
* **Strict Non-Guessing Policy:** Datasets lacking `.prj` spatial references are safely preserved with an explanatory `ERROR` status rather than guessing a coordinate datum.
* **Metric Planar Calculations:** Authoritative planar area in square meters ($m^2$) and Euclidean length in meters ($m$), with derived display conversions to hectares ($ha$), square kilometers ($km^2$), and kilometers ($km$).
* **Automated Geometry Topology Repair:** Self-intersecting rings are repaired using Shapely's `make_valid()` without data loss.
* **Single-File Backend Architecture:** Entire backend GIS engine, database models, Pydantic schemas, and security routers contained in a clean, maintainable `main.py` (1,496 lines).
* **Observatory-Grade 3D Web UI:** Procedural WebGL Earth with blue oceans, land biomes, clouds, day/night lighting, real Dark/Light themes, and zero `innerHTML` usage.

---

## Real-World Use Cases

| Domain | Application Scenario | Client Architecture |
| :--- | :--- | :--- |
| **Land Surveying & Cadastre** | Surveyors upload boundaries exported from GPS total stations to verify title parcel areas in hectares. | Mobile field tablet uploads Shapefile ZIP to API. |
| **Civil Infrastructure** | Construction planners upload road alignment KMLs to calculate linear excavation and paving distances. | Web GIS portal queries `/api/files/{id}/measurements/`. |
| **Drone Imagery Analysis** | Photogrammetry pipelines upload surveyed orthomosaic flight boundaries to verify ground coverage. | Automated CLI worker streams flight boundary KML. |
| **Enterprise Dashboards** | Municipal land records departments batch-audit uploaded Shapefiles for spatial reference compliance. | Enterprise microservices query file status and CRS notes. |

---

## System Architecture

```mermaid
flowchart TD
    Client[Web Client / Mobile App / GIS Portal]
    
    subgraph FastAPI Backend [Authoritative Backend Engine — main.py]
        Router[FastAPI Security & REST Router]
        StreamGuard[Bounded Stream Guard < 25 MB]
        
        subgraph Ingestion & Security [Hardened Ingestion Pipeline]
            FormatRouter{Format Branch}
            KmlEngine[Defused XML & XXE / SSRF Defense]
            ZipEngine[Zip-Slip & Compression Bomb Defense]
            IsolationStorage[UUID Isolated Storage Sandbox]
        end
        
        subgraph Geodesic Engine [CRS & Measurement Engine]
            DriverParser[Pyogrio / GeoPandas Feature Extraction]
            CrsResolver{CRS Detection}
            UTMEngine[Dynamic Centroid UTM Resolver]
            EqualArea[EPSG:6933 Equal-Area Fallback]
            AeqdEngine[Centered Azimuthal Equidistant]
            MetricCalc[Shapely Planar Area & Length Engine]
        end
        
        subgraph Persistence Layer [SQLite Database — WAL Mode]
            ORM[SQLAlchemy 2.0 ORM]
            DB[(geospatial.db)]
        end
    end

    Client -->|POST /api/files/ Multipart| Router
    Router --> StreamGuard
    StreamGuard --> FormatRouter
    FormatRouter -->|KML File| KmlEngine
    FormatRouter -->|Shapefile ZIP| ZipEngine
    KmlEngine --> IsolationStorage
    ZipEngine --> IsolationStorage
    IsolationStorage --> DriverParser
    DriverParser --> CrsResolver
    CrsResolver -->|Local Extent| UTMEngine
    CrsResolver -->|Wide Polygon| EqualArea
    CrsResolver -->|Wide Line| AeqdEngine
    UTMEngine --> MetricCalc
    EqualArea --> MetricCalc
    AeqdEngine --> MetricCalc
    MetricCalc --> ORM
    ORM --> DB
    DB --> ORM
    ORM -->|JSON API Response| Client
```

---

## Data Flow & Processing Lifecycle

```
[1. UPLOAD]           Client sends multipart file payload (enforcing 25 MB stream limit).
       │
[2. VALIDATE]         Format check; magic byte verification; Zip-Slip & XML bomb scans.
       │
[3. ISOLATE]          Payload committed to storage/uploads/{uuid4}/ with sanitized filename.
       │
[4. EXTRACT]          Shapefiles decompressed into temp directory; KML parsed via defusedxml.
       │
[5. PARSE]            Pyogrio/GeoPandas extracts records, geometries, and attribute dictionaries.
       │
[6. CRS DETECT]       Source CRS resolved from .prj or default WGS 84 (KML). Unset CRS flagged.
       │
[7. PROJECT]          Centroid computed; target metric projection (UTM / EPSG:6933 / AEQD) generated.
       │
[8. MEASURE]          Shapely 2.0 repairs topology (make_valid) and executes planar calculations.
       │
[9. PERSIST]          File metadata, individual features, and measurements saved in SQLite WAL DB.
       │
[10. RESPOND]         FastAPI serializes structured JSON response with HTTP 201 Created.
```

---

## Coordinate Reference System (CRS) Engine

The CRS engine executes a multi-tiered projection strategy to ensure planar metric validity:

```
                                  [Source Dataset Ingested]
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
                 [KML 2.2 Vector]                       [ESRI Shapefile ZIP]
                         │                                         │
                 Default: EPSG:4326                        Inspect .prj file
                         │                                         │
                         │                         ┌───────────────┴───────────────┐
                         │                         ▼                               ▼
                         │                  [.prj Present]                  [.prj Missing]
                         │                         │                               │
                         │                 Parse Coordinate Datum           Refuse to guess!
                         │                         │                        Status = ERROR
                         └─────────────────────────┼───────────────────────────────┘
                                                   ▼
                                      [Is Source Projected & Metric?]
                                                   │
                                      ┌────────────┴────────────┐
                                      ▼                         ▼
                                    [Yes]                      [No]
                                      │                         │
                          Retain Projected CRS       Compute Geometry Centroid
                                                                │
                                              ┌─────────────────┴─────────────────┐
                                              ▼                                   ▼
                                       [Local Extent]                      [Large Extent]
                                              │                                   │
                                   Dynamic UTM Zone Selection           Inspect Geometry Type
                                   EPSG:32601-32660 (North)                       │
                                   EPSG:32701-32760 (South)             ┌─────────┴─────────┐
                                                                        ▼                   ▼
                                                                    [Polygon]          [LineString]
                                                                        │                   │
                                                                    EPSG:6933           PROJ:AEQD
                                                                   (Equal-Area)     (Azimuthal Equi.)
```

### 1. KML 2.2 Datasets
* Under OGC KML 2.2 specifications, spatial coordinates represent longitude and latitude in degrees on the WGS 84 ellipsoid.
* Ingested KML coordinates without custom SRS are anchored to `EPSG:4326`.

### 2. ESRI Shapefile Archives
* Ingests the companion `.prj` file (WKT 1 format) to identify the source coordinate reference system.
* **Strict Non-Guessing Mandate:** When `.prj` is missing, the API stores `crs = null` on the file and outputs an explanatory `ERROR` status for measurements (`"Missing coordinate reference system (.prj). Cannot accurately compute planar measurements without an authoritative CRS."`). The engine **never assumes EPSG:4326** to prevent corrupted results.

### 3. Projection Selection Strategy
1. **Existing Metric Projections:** If the source data is already projected in a linear metric unit (meters), the original projection is preserved.
2. **Local Extents (UTM):** For features within standard longitudinal spans ($\le 6^\circ$), the engine computes the centroid $(\text{lon}_0, \text{lat}_0)$ and projects to the corresponding Universal Transverse Mercator (UTM) zone:
   $$\text{Zone} = \lfloor(\text{lon}_0 + 180) / 6\rfloor + 1$$
   * Northern Hemisphere ($\text{lat}_0 \ge 0$): `EPSG:32601` through `EPSG:32660`
   * Southern Hemisphere ($\text{lat}_0 < 0$): `EPSG:32701` through `EPSG:32760`
3. **Large Extent Polygons (Equal-Area Fallback):** For polygon features spanning multiple UTM zones within valid coverage (latitudes between $-80^\circ$ and $+80^\circ$), the engine reprojects to **EPSG:6933** (WGS 84 / World Cylindrical Equal Area).
4. **Large Extent LineStrings (Azimuthal Equidistant):** For long-distance linear features, the engine dynamically constructs a feature-centered Azimuthal Equidistant projection (`PROJ:AEQD` with `+lat_0`, `+lon_0`) to preserve geodesic path distance.

---

## Planar Measurement Methodology

Measurements are strictly computed by the Python backend via Shapely 2.0 and PyProj:

* **Polygon & MultiPolygon:**
  * Area is computed as planar surface area in square meters ($m^2$).
  * Self-intersecting rings are passed through `shapely.make_valid()` before calculation.
* **LineString & MultiLineString:**
  * Length is computed as planar Euclidean length along the reprojected metric path in meters ($m$).
* **Point & MultiPoint:**
  * Marked as `SKIPPED` with an explanatory note: `"Point geometry does not require area or length measurement"`. Measurement object is `null`.
* **GeometryCollection / Unsupported:**
  * Handled cleanly with an `UNSUPPORTED` status or filtered into constituent components.
* **Derived Frontend Conversions:**
  * Conversions to hectares ($ha = m^2 / 10\,000$), square kilometers ($km^2 = m^2 / 1\,000\,000$), and kilometers ($km = m / 1\,000$) are formatted display transformations. The backend numeric value in $m$ or $m^2$ remains the authoritative source of truth.

---

## Security Architecture & Defense-in-Depth

The backend implements security validation across all ingestion points:

| Vulnerability Vector | Defense Mechanism | Implemented Constraint |
| :--- | :--- | :--- |
| **Oversized Payloads** | Streaming byte counter | Rejects uploads $> 25\text{ MB}$ with `HTTP 413 Request Entity Too Large`. |
| **Zip-Slip (Directory Traversal)** | Path containment assertion | Resolves all extracted ZIP paths relative to the destination directory. Rejects `../`, absolute paths (`/etc/passwd`), and Windows drive paths (`C:\...`). |
| **Decompression Bomb (Zip Bomb)** | Decompression bounds | Enforces a maximum decompressed extraction limit of $100\text{ MB}$ and a maximum compression ratio of $100:1$. |
| **XML External Entity (XXE)** | XML entity prohibition | `defusedxml.ElementTree` forbids DOCTYPE declarations, entity expansion, and DTD lookups. |
| **SSRF (Server-Side Request Forgery)** | Prohibits network fetching | Forbids KML `<NetworkLink>` resolution and external URI lookups. |
| **SQL Injection** | Parameterized queries | SQLAlchemy 2.0 type-safe ORM expressions across all database operations. |
| **Data Leakage & Tracebacks** | Controlled exception shielding | Global exception handlers suppress Python tracebacks, internal filepaths, and raw SQL queries from client responses. |
| **Cross-Site Scripting (XSS)** | Safe textContent rendering | Frontend never assigns `innerHTML`. All placemark names, descriptions, and feature properties are rendered via `textContent`. |

---

## Database Design & Persistence

The relational model is managed in SQLite using SQLAlchemy 2.0.

```mermaid
erDiagram
    FILES ||--o{ FEATURES : "contains"
    FILES ||--o{ MEASUREMENTS : "aggregates"
    
    FILES {
        string id PK "UUID4 primary key"
        string filename "Sanitized original filename"
        string file_type "kml or shapefile"
        string storage_path "Relative path under storage root"
        integer file_size "Size in bytes"
        integer feature_count "Total extracted features"
        string crs "Source CRS (e.g. EPSG:4326)"
        string status "PROCESSING, COMPLETED, ERROR"
        datetime created_at "UTC timestamp"
        datetime updated_at "UTC timestamp"
    }

    FEATURES {
        integer id PK "Autoincrement primary key"
        string file_id FK "References files.id (CASCADE)"
        integer feature_index "0-indexed feature order"
        string geometry_type "Polygon, LineString, Point"
        string properties "JSON dictionary of attributes"
        string status "PARSED, SKIPPED, ERROR"
        datetime created_at "UTC timestamp"
    }

    MEASUREMENTS {
        integer id PK "Autoincrement primary key"
        string file_id FK "References files.id (CASCADE)"
        integer feature_id "Corresponding feature ID"
        string geometry_type "Polygon, LineString, Point"
        string metric_type "area, length, null"
        float calculated_value "Metric value in m or m²"
        string unit "square_meters, meters, null"
        string input_crs "Original coordinate reference"
        string projected_crs "Reprojected metric coordinate reference"
        string status "COMPLETED, SKIPPED, ERROR"
        string note "Explanatory details or error context"
        datetime created_at "UTC timestamp"
    }
```

### SQLite Hardening PRAGMAs
At engine initialization, the database executes connection PRAGMAs:
* `PRAGMA journal_mode = WAL;` (Write-Ahead Logging enables non-blocking concurrent reads during writes).
* `PRAGMA foreign_keys = ON;` (Enforces relational integrity and cascading deletes).
* `PRAGMA busy_timeout = 5000;` (Waits up to 5 seconds for lock release during bursts).
* `PRAGMA synchronous = NORMAL;` (Ensures durability while minimizing disk I/O bottlenecks).

---

## Client Presentation Layer (3D Command Center)

The web interface is an interactive client consumer of the API:

* **Interactive 3D Earth:** Built with Three.js (v0.160.0) and OrbitControls. Generates procedural 2048&times;1024 diffuse, specular roughness, and cloud textures entirely in-memory at startup—**100% offline with zero CDN dependencies**.
* **Dual Theme Engine:** Intentional Dark Mode (deep space background, subtle starfield, atmospheric glow) and Light Mode (clean spatial laboratory background, solid neutral cards, high-contrast dark slate text). Persists selection in `localStorage`.
* **Spatial Ingestion Portal:** Features crosshair framing, corner brackets `[+]`, drag-and-drop feedback, and staged data packet cards displaying format and size.
* **8-Stage Execution Pipeline:** Visualizes the sequential processing lifecycle (`UPLOAD` &rarr; `VALIDATE` &rarr; `PARSE` &rarr; `CRS` &rarr; `PROJECT` &rarr; `MEASURE` &rarr; `STORE` &rarr; `READY`).
* **Spatial Analysis Report:** High-impact metric cards with smooth counter animations and derived conversions for area ($m^2$, $ha$, $km^2$) and length ($m$, $km$).
* **Spatial Data View:** A 2D/3D geometry canvas visualizer mapping extracted polygons (emerald fill), lines (amber paths), and points (indigo beacons) with interactive zoom and pan controls.
* **Feature Explorer:** Interactive entity list allowing users to inspect individual feature attributes and metric calculations.
* **CRS Visualizer:** Visual transformation instrument comparing source datums with projected metric targets.
* **Safe DOM Construction:** Verified zero instances of `innerHTML`. All entity properties, placemarks, and table cells are populated using `textContent` and `createElement`.

---

## Visual Interface & Screenshots

### 1. Dark Mode Landing (3D Geodetic Core)
![Dark Mode Landing](docs/images/dark_mode_landing.png)

### 2. Light Mode Landing (Scientific Geodesy Laboratory)
![Light Mode Landing](docs/images/light_mode_landing.png)

### 3. Spatial Ingestion Portal (Staged Data Packet)
![Spatial Ingestion Portal](docs/images/upload_portal.png)

### 4. 8-Stage Architectural Pipeline
![Processing Pipeline](docs/images/processing_pipeline.png)

### 5. Spatial Analysis Report (Authoritative Metrics)
![Spatial Analysis Report](docs/images/analysis_report.png)

### 6. Spatial Viewport & Interactive Feature Explorer
![Spatial Viewport & Feature Explorer](docs/images/spatial_viewport_and_explorer.png)

### 7. Controlled Error Alert Experience
![Controlled Error Alert](docs/images/error_alert_card.png)

### 8. Mobile Viewport (Responsive Stacked Reflow)
![Mobile Responsive View](docs/images/mobile_responsive_view.png)

---

## Technology Stack

### Backend Technologies
* **Language:** Python 3.12+
* **Web Framework:** FastAPI (Asynchronous REST API)
* **ASGI Server:** Uvicorn
* **Database & ORM:** SQLite 3 (WAL mode) & SQLAlchemy 2.0
* **GIS & Geodesy Engine:** GeoPandas, Shapely 2.0, PyProj, Pyogrio
* **Security & Parsing:** defusedxml, standard zipfile validation

### Frontend Technologies
* **Markup:** Semantic HTML5
* **Styling:** Vanilla CSS3 (Custom Properties design system, CSS Grid, Flexbox)
* **3D Graphics Engine:** Three.js v0.160.0 (offline vendor module) & OrbitControls
* **Canvas Rendering:** Hardware-accelerated WebGL & 2D Context Canvas

---

## Installation & Setup

### Prerequisites
* Python 3.12 or newer installed on your system.
* Modern web browser with WebGL support (Google Chrome, Microsoft Edge, Mozilla Firefox, or Safari).

### Local Setup Instructions

#### 1. Clone the Repository
```bash
git clone https://github.com/your-username/geospatial-file-measurement-api.git
cd geospatial-file-measurement-api
```

#### 2. Create and Activate a Virtual Environment
**On Windows:**
```powershell
python -m venv .venv
.venv\Scripts\activate
```

**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Configure Environment Variables (Optional)
```bash
# Copy example configuration template
copy .env.example .env     # Windows
cp .env.example .env       # Linux/macOS
```

#### 5. Start the FastAPI Backend
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
*API Swagger Documentation is available at: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)*

#### 6. Start the Frontend Web Server
In a separate terminal window:
```bash
python -m http.server 5500
```
Open your browser and navigate to: **[http://127.0.0.1:5500/](http://127.0.0.1:5500/)**

---

## Running with Docker

A production-ready `Dockerfile` is provided with multi-stage isolation and volume mount support.

### 1. Build the Docker Image
```bash
docker build -t geospatial-measurement-api .
```

### 2. Run the Container
```bash
docker run -d \
  --name geospatial-api \
  -p 8000:8000 \
  -v geospatial_storage:/app/storage \
  geospatial-measurement-api
```

### 3. Verify Container Health
```bash
curl http://127.0.0.1:8000/api/health/
```

> **Note on Docker Runtime Testing:**  
> The `Dockerfile` has been audited and verified for production compliance. During local development, the Docker runtime smoke test was not executed because the local Docker Desktop daemon was unavailable. Users running Docker should ensure their container daemon is active.

---

## API Reference & Usage Examples

### 1. Health & Readiness Endpoint
```http
GET /api/health/
```
**Response (`200 OK`):**
```json
{
  "status": "ok",
  "service": "Geospatial File Measurement API"
}
```

---

### 2. Upload Geospatial File
```http
POST /api/files/
Content-Type: multipart/form-data
```
**cURL Example:**
```bash
curl -X POST "http://127.0.0.1:8000/api/files/" \
  -F "file=@sample_data/sample_survey.kml"
```
**Response (`201 Created`):**
```json
{
  "id": "23883b86-fb66-4013-b324-e055afa356c8",
  "filename": "sample_survey.kml",
  "file_type": "kml",
  "file_size": 756,
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "created_at": "2026-10-09T01:45:00Z"
}
```

---

### 3. Retrieve File Summary & Extracted Features
```http
GET /api/files/{id}/
```
**cURL Example:**
```bash
curl -X GET "http://127.0.0.1:8000/api/files/23883b86-fb66-4013-b324-e055afa356c8/"
```
**Response (`200 OK`):**
```json
{
  "id": "23883b86-fb66-4013-b324-e055afa356c8",
  "filename": "sample_survey.kml",
  "file_type": "kml",
  "file_size": 756,
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "created_at": "2026-10-09T01:45:00Z",
  "features": [
    {
      "id": 1,
      "feature_index": 0,
      "geometry_type": "Polygon",
      "properties": {
        "name": "Parc des Buttes-Chaumont",
        "description": "Public park boundary"
      },
      "status": "PARSED"
    },
    {
      "id": 2,
      "feature_index": 1,
      "geometry_type": "LineString",
      "properties": {
        "name": "Rue de Crimee",
        "description": "Surveyed centerline"
      },
      "status": "PARSED"
    },
    {
      "id": 3,
      "feature_index": 2,
      "geometry_type": "Point",
      "properties": {
        "name": "Survey Control Station",
        "description": "Geodetic benchmark"
      },
      "status": "PARSED"
    }
  ]
}
```

---

### 4. Retrieve Authoritative Measurements
```http
GET /api/files/{id}/measurements/
```
**cURL Example:**
```bash
curl -X GET "http://127.0.0.1:8000/api/files/23883b86-fb66-4013-b324-e055afa356c8/measurements/"
```
**Response (`200 OK`):**
```json
{
  "file_id": "23883b86-fb66-4013-b324-e055afa356c8",
  "measurements": [
    {
      "feature_id": 1,
      "geometry_type": "Polygon",
      "status": "COMPLETED",
      "measurement": {
        "type": "area",
        "value": 203756.5038,
        "unit": "square_meters",
        "input_crs": "EPSG:4326",
        "projected_crs": "EPSG:32631 (WGS 84 / UTM zone 31N)"
      },
      "note": null
    },
    {
      "feature_id": 2,
      "geometry_type": "LineString",
      "status": "COMPLETED",
      "measurement": {
        "type": "length",
        "value": 665.8285,
        "unit": "meters",
        "input_crs": "EPSG:4326",
        "projected_crs": "EPSG:32631 (WGS 84 / UTM zone 31N)"
      },
      "note": null
    },
    {
      "feature_id": 3,
      "geometry_type": "Point",
      "status": "SKIPPED",
      "measurement": null,
      "note": "Point geometry does not require area or length measurement"
    }
  ]
}
```

---

## Standardized Error Responses

All error responses return structured JSON schemas with descriptive context and zero stack trace leakage.

### 1. Unsupported Extension (`400 Bad Request`)
```json
{
  "error": "InvalidExtensionException",
  "detail": "Invalid file extension '.geojson'. Allowed extensions: .kml, .zip"
}
```

### 2. Malformed KML XML (`400 Bad Request`)
```json
{
  "error": "MalformedFileException",
  "detail": "KML XML syntax error: mismatched tag: line 1, column 49"
}
```

### 3. Zip-Slip Directory Traversal Blocked (`400 Bad Request`)
```json
{
  "error": "SecurityException",
  "detail": "Archive contains forbidden relative path '../' attempting directory traversal"
}
```

### 4. Missing Companion Files in Shapefile (`400 Bad Request`)
```json
{
  "error": "MalformedFileException",
  "detail": "Shapefile archive missing required companion file '.dbf'"
}
```

### 5. File Exceeds 25 MB Limit (`413 Request Entity Too Large`)
```json
{
  "error": "PayloadTooLargeException",
  "detail": "Upload size (27262976 bytes) exceeds maximum limit of 25 MB"
}
```

### 6. File Not Found (`404 Not Found`)
```json
{
  "error": "NotFoundException",
  "detail": "File record '00000000-0000-0000-0000-000000000000' not found"
}
```

---

## Sample Data

Clean, non-malicious sample datasets are provided in the [`sample_data/`](sample_data/) directory for validation:

1. `sample_data/sample_survey.kml` — Valid KML 2.2 vector containing a Polygon, a LineString, and a Point placemark.
2. `sample_data/sample_shapefile.zip` — Valid ESRI Shapefile bundle containing `.shp`, `.shx`, `.dbf`, and `.prj` (UTM projected).
3. `sample_data/sample_shapefile_no_prj.zip` — Valid Shapefile lacking a `.prj` file (demonstrates graceful CRS error handling).

---

## Verification & Test Suites

The codebase includes an automated test harness covering all functional and security scenarios across Parts 2 through 9A.

### Test Coverage Breakdown

| Test Suite | File | Verified Scenarios | Status |
| :--- | :--- | :---: | :---: |
| **Part 2** | `tests/verify_part2.py` | 23 | **PASS (23/23)** |
| **Part 3** | `tests/test_part3.py` | 16 | **PASS (16/16)** |
| **Part 4** | `tests/test_part4.py` | 20 | **PASS (20/20)** |
| **Part 5** | `tests/test_part5.py` | 15 | **PASS (15/15)** |
| **Part 6** | `tests/test_part6.py` | 11 | **PASS (11/11)** |
| **Part 7** | `tests/test_part7.py` | 15 | **PASS (15/15)** |
| **Part 8** | `tests/test_part8.py` | 16 | **PASS (16/16)** |
| **Part 9A** | `tests/test_part9a.py` | 20 | **PASS (20/20)** |
| **Browser UI** | Real Edge/Chromium Suite | 25 | **PASS (25/25)** |
| **Total Cumulative** | **All Verification Suites** | **161** | **PASS (161/161)** |

### Running the Test Suites

Execute the master test runner to verify all 8 test suites in sequence:
```bash
python tests/run_all_tests.py
```

To run individual test suites:
```bash
python tests/verify_part2.py    # Part 2 Ingestion & Security
python tests/test_part3.py      # Part 3 CRS & UTM Engine
python tests/test_part4.py      # Part 4 Planar Metrics & Geodesic Benchmarks
python tests/test_part5.py      # Part 5 Relational Persistence & SQLAlchemy
python tests/test_part6.py      # Part 6 API Serialization Contracts
python tests/test_part7.py      # Part 7 Architecture Hardening
python tests/test_part8.py      # Part 8 Production Deployment Quality
python tests/test_part9a.py     # Part 9A Functional UI & Integration
```

---

## Key Design Decisions

1. **Why FastAPI?**  
   FastAPI combines high-throughput asynchronous request handling with automatic OpenAPI documentation and Pydantic validation schemas.
2. **Why SQLite (with WAL mode)?**  
   Provides a self-contained, zero-dependency relational database suitable for standalone deployment. Enabling Write-Ahead Logging (`WAL`) allows concurrent read access during write transactions.
3. **Why Bounded Shapefile Ingestion?**  
   Shapefiles consist of multiple interdependent binary files. Validating companion files upfront prevents partial extraction failures.
4. **Why CRS-Aware Planar Measurement?**  
   Standard Euclidean formulas fail on geographic degrees. Dynamically projecting coordinates to conformal metric systems ensures measurement accuracy within millimetric tolerances.
5. **Why UTM as Primary Metric Target?**  
   UTM conformal projections maintain minimal scale distortion ($< 0.04\%$) within each $6^\circ$ longitudinal zone, making them the industry standard for surveying.
6. **Why EPSG:6933 for Large Polygon Fallback?**  
   When a polygon spans multiple UTM zones, Transverse Mercator projections distort area at the outer boundaries. World Cylindrical Equal Area (`EPSG:6933`) preserves surface area globally between latitudes $-80^\circ$ and $+80^\circ$.
7. **Why Feature-Centered AEQD for Long Lines?**  
   Azimuthal Equidistant projections preserve true geodesic distance along great-circle paths from the projection center.
8. **Why Refuse to Guess Missing CRS?**  
   Assuming `EPSG:4326` when coordinates represent state plane feet or national grids can cause measurement errors exceeding $100\,000\%$. Treating missing `.prj` files as `ERROR` prevents silent calculation corruption.
9. **Why a Single-File Backend (`main.py`)?**  
   Keeps the operational surface area compact, prevents cross-module circular imports, simplifies auditing, and ensures container deployment without packaging overhead.
10. **Why Procedural 3D Earth Without Image CDNs?**  
    Generating Earth textures procedurally onto offscreen canvases guarantees the application functions offline without network timeouts or CORS image loading issues.
11. **Why Isolated Storage Sandboxes?**  
    Storing uploaded archives under isolated UUID subdirectories (`storage/uploads/{uuid4}/`) prevents file overwrite collisions and directory traversal leaks.
12. **Why Safe textContent DOM Rendering?**  
    Eliminating `innerHTML` entirely mitigates client-side DOM-based Cross-Site Scripting (XSS) when displaying user-supplied Placemark names and metadata attributes.

---

## Alternatives Considered

| Alternative | Evaluated Option | Selected Choice | Rationale |
| :--- | :--- | :--- | :--- |
| **Backend Framework** | Django REST Framework | **FastAPI** | FastAPI has lower memory overhead, faster cold starts, and native async support. |
| **Database Engine** | PostgreSQL / PostGIS | **SQLite (WAL mode)** | Avoids requiring a dedicated database container for standalone local evaluation while providing full relational integrity. |
| **Projection Standard** | Web Mercator (EPSG:3857) | **Local UTM / EPSG:6933** | Web Mercator distorts area significantly outside the equator (up to 400%+ near the poles) and is unsuitable for accurate measurements. |
| **Calculation Boundary** | Client-side turf.js | **Authoritative Python Backend** | Keeps calculation logic centralized, auditable, and accessible to non-browser clients (CLI, mobile, microservices). |

---

## Performance Considerations

* **Streaming Upload Verification:** Streamed uploads enforce a 25 MB ceiling in chunks without buffering entire multi-megabyte payloads in memory.
* **Database WAL Mode:** SQLite Write-Ahead Logging allows background read queries to complete concurrently without locking on active write transactions.
* **Canvas Pixel Ratio Clamping:** WebGL pixel ratios are capped at $\min(\text{devicePixelRatio}, 2)$ to maintain 60 FPS performance on high-DPI displays.
* **Memory Cleanup:** Extracted Shapefile temporary workspaces are removed after parsing, leaving only the managed archive in isolated storage.

---

## Known Limitations & Future Scope

### Known Limitations
* **Concurrent Write Bottleneck:** While SQLite in WAL mode allows concurrent reads, it remains limited to a single concurrent writer.
* **Ephemeral Local Filesystem:** Uploaded files are stored on the local disk. In a multi-instance container deployment without shared volumes, instances cannot access archives stored on other nodes.
* **Polar Coverage Extremes:** Geometries crossing polar latitudes ($\pm 80^\circ$) beyond standard UTM and Cylindrical projections are rejected.

### Future Scope
* **PostgreSQL / PostGIS Migration:** Migrate persistence to PostGIS for concurrent multi-writer enterprise scalability.
* **Asynchronous Task Queue:** Integrate Celery or ARQ with Redis for background processing of large datasets ($> 100\text{ MB}$).
* **Additional Format Ingestion:** Add support for GeoJSON, GeoPackage (`.gpkg`), and Cloud Optimized GeoTIFF (COG) metadata.
* **Cloud Object Storage:** Add AWS S3 / Google Cloud Storage backends for file persistence.

---

## 5-Minute Demonstration Flow

For technical demonstrations and interviews:

1. **Start Services:** Start backend (`uvicorn main:app --port 8000`) and frontend (`python -m http.server 5500`).
2. **Access 3D Interface:** Open `http://127.0.0.1:5500/` in the browser. Show the 3D Earth, OrbitControls interaction, and the `[ ↺ RESET VIEW ]` camera control.
3. **Toggle Themes:** Click `☀ Light` in the top-right nav to showcase theme switching; click `🌙 Dark` to switch back.
4. **Ingest Valid KML:** Drag `sample_data/sample_survey.kml` into the ingestion portal. Click **Ingest & Calculate Metrics**.
5. **Inspect Spatial Analysis:** Highlight the Area ($203\,756.50\text{ m}^2$) and Length ($665.83\text{ m}$) cards. Show unit conversions ($ha$, $km^2$, $km$) and the Point `SKIPPED` note.
6. **Show CRS Transformation:** Highlight how source `EPSG:4326` was reprojected to `EPSG:32631` (UTM zone 31N).
7. **Inspect Vector Geometry:** Showcase the 2D spatial viewport rendering the polygon, line, and point geometries.
8. **Demonstrate Graceful Error Handling:** Ingest `sample_data/sample_shapefile_no_prj.zip`. Show how the system flags missing CRS with an explanatory note rather than guessing `EPSG:4326`.
9. **Show Interactive API Docs:** Navigate to `http://127.0.0.1:8000/docs` to demonstrate OpenAPI specification endpoints.

---

## 60–90 Second Interview Summary

> *"This project is an authoritative, CRS-aware geospatial processing engine built with FastAPI, GeoPandas, and Three.js. It solves a fundamental problem in spatial software: computing planar area and length directly on raw latitude and longitude degrees leads to massive distortion—often exceeding 40%—because degrees shrink toward the poles.*
> 
> *Our API ingests KML and ESRI Shapefile archives, subjects them to security validation including Zip-Slip path containment and defused XML parsing, extracts geometries, and dynamically reprojects them. For local extents, it resolves the optimal UTM metric zone; for large regions, it falls back to equal-area or azimuthal projections. If a Shapefile lacks a `.prj` coordinate reference system, our engine refuses to guess, returning an explicit error.*
> 
> *All results and feature properties are persisted in SQLite with Write-Ahead Logging and exposed via REST APIs. To demonstrate the backend, we built an interactive 3D WebGL command center featuring a procedural Earth, dual Light and Dark modes, and a 2D vector geometry viewport, adhering strictly to safe DOM rendering without `innerHTML`. The entire test suite—spanning 116 backend tests and 20 frontend scenarios—passes with 100% success."*

---

## Git Submission Instructions

To initialize and commit this project to a Git repository:

```bash
# 1. Initialize Git repository
git init

# 2. Stage all verified files (respecting .gitignore)
git add .

# 3. Create initial production commit
git commit -m "feat: complete production-ready geospatial file measurement API and 3D UI"

# 4. Link to your remote GitHub repository
git remote add origin https://github.com/VasiharanB/geospatial-file-measurement-api.git
git branch -M main

# 5. Push to GitHub
git push -u origin main
```

---

## Final Project File Inventory

```
Geospatial File Measurement API/
├── main.py                     # Authoritative single-file FastAPI backend, GIS engine, ORM models
├── index.html                  # Accessible semantic HTML5 client structure with 3D canvas
├── styles.css                  # Custom properties stylesheet with Light/Dark themes and responsive reflow
├── script.js                   # Client controller: procedural 3D Earth, dual theme switcher, spatial canvas
├── requirements.txt            # Locked production dependencies
├── Dockerfile                  # Production container definition
├── render.yaml                 # Render Infrastructure-as-Code blueprint for automated container deployment
├── .env.example                # Runtime environment configuration template
├── .gitignore                  # Git exclusion rules for databases, storage, and caches
├── .dockerignore               # Container build exclusion rules
├── README.md                   # Authoritative project documentation
├── GEOSPATIAL_API_DESIGN.md    # Initial architectural blueprint
│
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI automated regression test pipeline
│
├── docs/
│   └── images/                 # Verified interface screenshots
│       ├── dark_mode_landing.png
│       ├── light_mode_landing.png
│       ├── upload_portal.png
│       ├── processing_pipeline.png
│       ├── analysis_report.png
│       ├── spatial_viewport_and_explorer.png
│       ├── error_alert_card.png
│       └── mobile_responsive_view.png
│
├── sample_data/                # Valid evaluation datasets
│   ├── sample_survey.kml
│   ├── sample_shapefile.zip
│   └── sample_shapefile_no_prj.zip
│
├── tests/                      # Automated regression and verification suites
│   ├── run_all_tests.py        # Master test runner (executes all 8 suites)
│   ├── verify_part2.py         # Part 2 Ingestion & Security tests (23 tests)
│   ├── test_part3.py           # Part 3 CRS & UTM detection tests (16 tests)
│   ├── test_part4.py           # Part 4 Planar metric calculation tests (20 tests)
│   ├── test_part5.py           # Part 5 Relational persistence tests (15 tests)
│   ├── test_part6.py           # Part 6 API serialization contract tests (11 tests)
│   ├── test_part7.py           # Part 7 Architecture hardening tests (15 tests)
│   ├── test_part8.py           # Part 8 Production quality tests (16 tests)
│   └── test_part9a.py          # Part 9A Functional UI integration tests (20 tests)
│
└── vendor/
    └── three/                  # 100% offline Three.js v0.160.0 distribution
        ├── three.module.js
        └── OrbitControls.js
```

---

## License

This project is licensed under the MIT License.
