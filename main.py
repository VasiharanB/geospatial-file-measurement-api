"""
Geospatial File Measurement API
===============================
A production-quality single-file FastAPI backend for ingesting, validating,
and calculating geometric measurements (area, length) from KML and ESRI Shapefiles.

Key Capabilities:
- Accepts .kml and .zip (containing Shapefile components).
- Hardened upload and extraction security (Zip-Slip defense, decompression bomb guard,
  file size limits, magic byte validation, XXE-safe KML parsing).
- Automated CRS detection and coordinate transformation (never computes planar metrics
  directly on latitude/longitude degrees; dynamically selects local UTM zones or equal-area projections).
- Graceful feature-level degradation (corrupted/unsupported geometries do not abort the file).
- Relational persistence in SQLite (WAL mode) using SQLAlchemy 2.0.
"""

from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

# Web & API Framework
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status, Path as APIPath
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("geospatial_api")
logging.basicConfig(level=logging.INFO)

# Persistence
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

# Geospatial & XML Processing
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
import geopandas as gpd
import pyogrio
import pyproj
import shapely
import shapely.ops
from shapely.geometry import mapping
from shapely.validation import make_valid


# ==============================================================================
# 2. CONFIGURATION & CONSTANTS
# ==============================================================================

def _parse_env_int(key: str, default: int, min_val: int = 1) -> int:
    val_str = os.environ.get(key)
    if val_str is None:
        return default
    try:
        val = int(val_str)
        if val < min_val:
            raise ValueError(f"Environment variable '{key}' must be >= {min_val}, got {val}")
        return val
    except ValueError as e:
        logger.error(f"Configuration error for {key}: {e}")
        raise


def _parse_env_float(key: str, default: float, min_val: float = 1.0) -> float:
    val_str = os.environ.get(key)
    if val_str is None:
        return default
    try:
        val = float(val_str)
        if val < min_val:
            raise ValueError(f"Environment variable '{key}' must be >= {min_val}, got {val}")
        return val
    except ValueError as e:
        logger.error(f"Configuration error for {key}: {e}")
        raise


MAX_UPLOAD_SIZE_BYTES = _parse_env_int("MAX_UPLOAD_SIZE_BYTES", 25 * 1024 * 1024)  # 25 MB max upload
MAX_DECOMPRESSED_SIZE_BYTES = _parse_env_int("MAX_DECOMPRESSED_SIZE_BYTES", 100 * 1024 * 1024)  # 100 MB max uncompressed ZIP
MAX_ZIP_COMPRESSION_RATIO = _parse_env_float("MAX_ZIP_COMPRESSION_RATIO", 100.0)  # Max compression ratio against zip bombs
ALLOWED_EXTENSIONS = {".kml", ".zip"}

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = Path(os.environ.get("GEOSPATIAL_STORAGE_DIR", str(BASE_DIR / "storage" / "uploads"))).resolve()
DB_PATH = Path(os.environ.get("GEOSPATIAL_DB_PATH", str(BASE_DIR / "geospatial.db"))).resolve()
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")

# Ensure storage directory exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# 3. DATABASE SETUP (SQLAlchemy 2.0 with SQLite WAL mode)
# ==============================================================================

_engine_kwargs: Dict[str, Any] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable Write-Ahead Logging (WAL), foreign keys enforcement, busy timeout, and normal sync for SQLite only."""
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# 4. SQLALCHEMY MODELS
# ==============================================================================

class FileRecord(Base):
    __tablename__ = "files"

    id = Column(String(36), primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # "kml" or "shapefile_zip"
    crs = Column(String(100), nullable=True)
    feature_count = Column(Integer, default=0)
    status = Column(String(50), default="PROCESSING")  # "COMPLETED", "FAILED"
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    features = relationship(
        "FeatureRecord", back_populates="file", cascade="all, delete-orphan", order_by="FeatureRecord.feature_index"
    )
    measurements = relationship(
        "MeasurementRecord", back_populates="file", cascade="all, delete-orphan", order_by="MeasurementRecord.feature_index"
    )


class FeatureRecord(Base):
    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint("file_id", "feature_index", name="uq_features_file_idx"),
        Index("ix_features_file_idx", "file_id", "feature_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_index = Column(Integer, nullable=False)
    geometry_type = Column(String(50), nullable=False)
    geometry_geojson = Column(JSON, nullable=True)
    properties = Column(JSON, nullable=True)
    status = Column(String(50), default="VALID")  # "VALID", "UNSUPPORTED", "INVALID"
    error_message = Column(Text, nullable=True)

    file = relationship("FileRecord", back_populates="features")


class MeasurementRecord(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint("file_id", "feature_index", name="uq_measurements_file_idx"),
        Index("ix_measurements_file_idx", "file_id", "feature_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    feature_index = Column(Integer, nullable=False)
    geometry_type = Column(String(50), nullable=False)
    measurement_type = Column(String(20), nullable=False)  # "area", "length", "none"
    measurement_value = Column(Float, nullable=True)  # in square meters or meters
    unit = Column(String(50), nullable=True)  # "square_meters", "meters", None
    input_crs = Column(String(100), nullable=True)
    projected_crs = Column(String(100), nullable=True)
    status = Column(String(50), default="COMPLETED")  # "COMPLETED", "SKIPPED", "UNSUPPORTED", "ERROR"
    note = Column(Text, nullable=True)

    file = relationship("FileRecord", back_populates="measurements")


# ==============================================================================
# 5. PYDANTIC SCHEMAS (DTOs)
# ==============================================================================

class MeasurementDetail(BaseModel):
    type: str  # "area", "length", "none"
    value: Optional[float] = None
    unit: Optional[str] = None
    input_crs: Optional[str] = None
    projected_crs: Optional[str] = None


class FeatureMeasurementResponse(BaseModel):
    feature_id: int
    geometry_type: str
    status: str
    measurement: Optional[MeasurementDetail] = None
    note: Optional[str] = None


class FileMeasurementListResponse(BaseModel):
    file_id: str
    filename: str
    status: str
    total_features: int
    measurements: List[FeatureMeasurementResponse]


class FeatureDetailResponse(BaseModel):
    feature_id: int
    geometry_type: str
    geometry: Optional[Dict[str, Any]] = None
    crs: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    status: str
    error_message: Optional[str] = None


class FileDetailResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    features: List[FeatureDetailResponse]


class FileUploadResponse(BaseModel):
    id: str
    filename: str
    file_type: Optional[str] = None
    feature_count: int
    crs: Optional[str] = None
    status: str


class ErrorResponse(BaseModel):
    error: str
    detail: str


class HealthResponse(BaseModel):
    status: str
    service: str


# ==============================================================================
# 6. CUSTOM DOMAIN EXCEPTIONS
# ==============================================================================

class GeospatialAPIError(Exception):
    """Base exception for all application-specific errors."""
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class UnsupportedFileTypeException(GeospatialAPIError):
    def __init__(self, message: str = "Unsupported file type"):
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST)


class FileTooLargeException(GeospatialAPIError):
    def __init__(self, message: str = "File size exceeds maximum allowed limit"):
        super().__init__(message, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)


class MalformedFileException(GeospatialAPIError):
    def __init__(self, message: str = "Uploaded file is malformed or corrupted"):
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST)


class UnprocessableGeospatialException(GeospatialAPIError):
    def __init__(self, message: str = "No valid features could be extracted"):
        super().__init__(message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


class ResourceNotFoundException(GeospatialAPIError):
    def __init__(self, message: str = "Requested resource not found"):
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)


# ==============================================================================
# 7. SECURITY & UPLOAD UTILITIES
# ==============================================================================

def sanitize_filename(filename: str) -> str:
    """Sanitize the incoming filename to prevent path traversal and shell injection."""
    cleaned = Path(filename).name
    # Strip any characters that aren't alphanumeric, dash, underscore, dot, or space
    cleaned = re.sub(r"[^a-zA-Z0-9_\-\. ]", "_", cleaned)
    if not cleaned or cleaned.startswith("."):
        cleaned = f"file_{uuid.uuid4().hex[:8]}"
    return cleaned


def validate_file_magic_bytes(header: bytes, ext: str) -> None:
    """Inspect magic bytes to ensure file content corresponds to the declared extension."""
    if ext == ".zip":
        # ZIP magic numbers: PK\x03\x04, PK\x05\x06 (empty archive), or PK\x07\x08 (spanned)
        if not (header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06") or header.startswith(b"PK\x07\x08")):
            raise MalformedFileException("File has a .zip extension but does not contain a valid ZIP magic header.")
    elif ext == ".kml":
        # KML is XML. Must start with XML declaration or <kml tag (case-insensitive)
        snippet = header[:1024].strip().lower()
        if not (snippet.startswith(b"<?xml") or snippet.startswith(b"<kml") or b"<kml" in snippet):
            raise MalformedFileException("File has a .kml extension but does not contain valid KML/XML markup.")


def validate_and_sanitize_kml(content: bytes) -> None:
    """
    Parse KML using defusedxml to block XML External Entity (XXE) attacks,
    billion laughs expansion, and DTD entity inclusion.
    Also verifies:
    1. Content is well-formed XML.
    2. Root element is <kml> (rejecting arbitrary non-KML XML like <note>, <svg>, <html>).
    3. Blocks remote external network fetching (SSRF) via NetworkLink with remote hrefs.
    """
    if not content or not content.strip():
        raise MalformedFileException("Uploaded KML file is empty.")

    try:
        root = ET.fromstring(content)
    except DefusedXmlException as e:
        raise MalformedFileException(f"KML XML failed security validation (disallowed XML construct): {str(e)}")
    except Exception as e:
        raise MalformedFileException(f"KML XML syntax error: {str(e)}")

    # Verify root element is <kml>
    tag = root.tag
    local_tag = tag.split("}")[-1] if "}" in tag else tag
    if local_tag.lower() != "kml":
        raise MalformedFileException(
            f"Invalid KML document: root element must be <kml>, found <{local_tag}>."
        )

    # Disallow remote external network fetching (SSRF prevention)
    for elem in root.iter():
        elem_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if elem_tag.lower() in ("networklink", "href"):
            text = (elem.text or "").strip().lower()
            if text.startswith(("http://", "https://", "ftp://", "file://", "\\\\")):
                raise MalformedFileException(
                    "KML contains external network link/resource references, which are forbidden for security."
                )


# ==============================================================================
# 8. SAFE ZIP EXTRACTION (Zip-Slip & Decompression Bomb Protection)
# ==============================================================================

def find_companion_file(parent_dir: Path, stem: str, ext: str) -> Optional[Path]:
    """Find a companion file in parent_dir matching stem and extension, case-insensitively."""
    target_ext = ext.lower()
    target_stem = stem.lower()
    for f in parent_dir.iterdir():
        if f.is_file() and f.stem.lower() == target_stem and f.suffix.lower() == target_ext:
            return f
    return None


def safe_extract_shapefile_zip(zip_bytes: bytes, target_dir: Path) -> Path:
    """
    Safely extract a ZIP containing a Shapefile:
    1. Prevents Zip-Slip path traversal using os.path.commonpath and path normalization.
    2. Rejects absolute paths and Windows drive letter injections.
    3. Enforces decompression size limits and compression ratios against Zip bombs.
    4. Safely ignores non-shapefile files (e.g. README.txt, metadata) and macOS resource forks.
    5. Verifies mandatory Shapefile companion files (.shp, .shx, .dbf) case-insensitively.
    Returns the Path to the primary .shp file.
    """
    target_dir_resolved = target_dir.resolve()
    target_dir_str = str(target_dir_resolved)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            total_uncompressed_size = 0
            compressed_size = max(len(zip_bytes), 1)

            # Pre-extraction inspection
            for member in zf.infolist():
                total_uncompressed_size += member.file_size
                if total_uncompressed_size > MAX_DECOMPRESSED_SIZE_BYTES:
                    raise MalformedFileException("ZIP uncompressed size exceeds maximum allowable limit (Zip Bomb protection).")

                # Check compression ratio for bombs
                if member.compress_size > 0:
                    ratio = member.file_size / member.compress_size
                    if ratio > MAX_ZIP_COMPRESSION_RATIO:
                        raise MalformedFileException("ZIP contains an excessively compressed member (Zip Bomb protection).")

                # Path normalization: normalize backslashes to forward slashes
                norm_name = member.filename.replace("\\", "/")

                # Reject absolute paths or Windows drive letters
                if norm_name.startswith("/") or (len(norm_name) > 1 and norm_name[1] == ":"):
                    raise MalformedFileException(
                        f"Potential directory traversal (absolute path) detected in member '{member.filename}'."
                    )

                # Zip-Slip check: Ensure extracted path stays strictly within target_dir using commonpath
                extracted_path = (target_dir_resolved / norm_name).resolve()
                try:
                    common = os.path.commonpath([target_dir_str, str(extracted_path)])
                except ValueError:
                    # Raised by os.path.commonpath on Windows if paths are on different drives
                    raise MalformedFileException(
                        f"Potential directory traversal (Zip-Slip) detected in member '{member.filename}'."
                    )

                if common != target_dir_str:
                    raise MalformedFileException(
                        f"Potential directory traversal (Zip-Slip) detected in member '{member.filename}'."
                    )

            # Safe extraction
            zf.extractall(path=target_dir_resolved)

    except zipfile.BadZipFile:
        raise MalformedFileException("Uploaded ZIP archive is corrupted or invalid.")

    # Locate real .shp files, ignoring macOS resource forks (__MACOSX) and hidden files
    all_files = list(target_dir_resolved.rglob("*"))
    candidate_shp_files = [
        f for f in all_files
        if f.is_file()
        and f.suffix.lower() == ".shp"
        and not f.name.startswith(".")
        and "__macosx" not in [p.lower() for p in f.parts]
    ]

    if not candidate_shp_files:
        raise MalformedFileException("Shapefile archive must contain at least one valid '.shp' file.")

    # Check for valid shapefiles with mandatory companion files (.shx and .dbf)
    valid_shapefiles = []
    for shp in candidate_shp_files:
        stem = shp.stem
        parent = shp.parent
        has_shx = find_companion_file(parent, stem, ".shx") is not None
        has_dbf = find_companion_file(parent, stem, ".dbf") is not None
        if has_shx and has_dbf:
            valid_shapefiles.append(shp)

    if not valid_shapefiles:
        # None of the candidate .shp files have both .shx and .dbf
        # Check what's missing for the primary candidate to return a clear, helpful error message
        primary_cand = sorted(candidate_shp_files, key=lambda p: (len(p.parts), p.name))[0]
        missing = []
        if not find_companion_file(primary_cand.parent, primary_cand.stem, ".shx"):
            missing.append(".shx")
        if not find_companion_file(primary_cand.parent, primary_cand.stem, ".dbf"):
            missing.append(".dbf")
        raise MalformedFileException(
            f"Shapefile '{primary_cand.name}' is incomplete. Missing mandatory companion file(s): {', '.join(missing)}."
        )

    # If multiple valid datasets exist (e.g. roads.shp and parcels.shp), safely select the topmost/primary one
    primary_shp = sorted(valid_shapefiles, key=lambda p: (len(p.parts), p.name))[0]
    return primary_shp


# ==============================================================================
# 9. COORDINATE REFERENCE SYSTEM (CRS) STRATEGY & REPROJECTION
# ==============================================================================
"""
CRS STRATEGY RATIONALE:
1. Why NEVER calculate area or distance on EPSG:4326?
   EPSG:4326 uses angular degrees (latitude, longitude).
   1 degree of longitude is ~111 km at the equator, but shrinks to ~78 km at 45° latitude,
   and collapses to 0 km at the poles. Planar Euclidean calculations (dx * dy or sqrt(dx^2 + dy^2))
   on degrees yield distorted "square degrees" that lack physical meaning.

2. Why NOT Web Mercator (EPSG:3857)?
   Web Mercator uses linear meters, but its conformal projection introduces massive scale
   distortion away from the equator (e.g. Greenland appears 14x larger than its actual area).

3. Explainable Selection Strategy:
   a. Source CRS Detection:
      - Shapefile: CRS is read from .prj when present. If absent, CRS is preserved as None (unknown).
        NEVER invent EPSG:4326 for a Shapefile with missing .prj.
      - KML: Standard KML coordinates are geographic WGS 84 (EPSG:4326) per OGC KML standard.
   b. Geographic vs Projected Analysis:
      - Uses PyProj CRS metadata (crs.is_geographic, crs.is_projected) rather than coordinate heuristics.
   c. WGS84 Normalization & Axis Handling:
      - Geographic coordinates are normalized to EPSG:4326 using always_xy=True (X=Longitude, Y=Latitude).
   d. Local UTM Selection:
      - If longitude span < 6° and latitude is within standard UTM limits (-80° to 84°):
        UTM Zone = floor((lon + 180) / 6) + 1 (clamped to 1..60).
        EPSG = 32600 + Zone (North) or 32700 + Zone (South).
   e. Large-Extent Fallback (EPSG:6933):
      - For geometries spanning multiple UTM zones (span >= 6°) or extending into polar latitudes:
        Fallback to World Cylindrical Equal Area (EPSG:6933), an international equal-area metric projection.
   f. Already-Projected Handling:
      - If source CRS is projected in metric units (meters), retain it directly without round-tripping through WGS84.
      - If projected in non-metric units (e.g. US survey feet), reproject to metric UTM/equal-area so measurements are metric.
   g. Missing CRS:
      - Preserves unknown CRS state and produces a clear error note without inventing coordinates.
"""

def get_crs_linear_unit(crs: Optional[pyproj.CRS]) -> Optional[str]:
    """Retrieve the primary linear unit name of a CRS if available."""
    if crs is None or not hasattr(crs, "axis_info") or not crs.axis_info:
        return None
    try:
        return crs.axis_info[0].unit_name
    except Exception:
        return None


def is_metric_crs(crs: Optional[pyproj.CRS]) -> bool:
    """Check if CRS linear units are metric (metre or meter)."""
    if crs is None:
        return False
    unit = get_crs_linear_unit(crs)
    if not unit:
        return False
    return unit.lower() in ("metre", "meter", "m")


@dataclass
class CRSResolutionResult:
    """Structured result containing source CRS, target projected CRS, and reprojected geometry."""
    source_crs: Optional[pyproj.CRS]
    source_crs_name: Optional[str]
    is_geographic: bool
    is_projected: bool
    source_linear_unit: Optional[str]
    normalized_wgs84: bool
    target_crs: Optional[pyproj.CRS]
    target_crs_name: Optional[str]
    target_linear_unit: Optional[str]
    reprojected_geom: Optional[shapely.Geometry]
    status: str  # "SUCCESS", "RETAINED_PROJECTED", "NON_METRIC_REPROJECTED", "UNKNOWN_CRS", "INVALID_GEOMETRY", "ERROR"
    note: Optional[str] = None


def detect_and_resolve_source_crs(gdf_crs: Any) -> Tuple[Optional[pyproj.CRS], Optional[str]]:
    """
    Determine the source pyproj CRS and format an informative identifier.
    Returns (None, None) when CRS is unspecified/missing (e.g. Shapefile without .prj).
    Never invents or defaults to EPSG:4326 here.
    """
    if gdf_crs is None:
        return None, None
    try:
        crs = pyproj.CRS.from_user_input(gdf_crs)
        epsg = crs.to_epsg()
        name = f"EPSG:{epsg}" if epsg else crs.name
        return crs, name
    except Exception:
        return None, str(gdf_crs)


def reproject_geometry(
    geom: Optional[shapely.Geometry],
    source_crs: Optional[pyproj.CRS],
    target_crs: Optional[pyproj.CRS],
) -> Tuple[Optional[shapely.Geometry], Optional[str]]:
    """
    Safely reproject a Shapely geometry from source_crs to target_crs.
    Uses always_xy=True to guarantee X=longitude/easting and Y=latitude/northing.
    Returns (reprojected_geometry, error_message).
    """
    if geom is None or geom.is_empty:
        return geom, None

    if source_crs is None:
        return None, "Cannot reproject geometry: source CRS is missing or undefined."

    if target_crs is None:
        return None, "Cannot reproject geometry: target CRS is missing or undefined."

    if source_crs == target_crs:
        return geom, None

    try:
        transformer = pyproj.Transformer.from_crs(source_crs, target_crs, always_xy=True)
        proj_geom = shapely.ops.transform(transformer.transform, geom)
        return proj_geom, None
    except Exception as e:
        return None, f"Coordinate transformation failed: {str(e)}"


def determine_projected_crs(
    geom: shapely.Geometry,
    source_crs: Optional[pyproj.CRS],
    metric_type: str = "area",
) -> Tuple[Optional[pyproj.CRS], Optional[str], Optional[str]]:
    """
    Determine an appropriate projected planar CRS (with metric units)
    for a given geometry based on its location, spatial extent, and measurement type.
    - Local extent (< 6° longitude span, between -80° and 84° lat):
      Local UTM zone (conformal, metric, scale factor error < 0.04% for both area and length).
    - Large extent (>= 6° longitude span or polar):
      - If metric_type == 'area': EPSG:6933 (World Cylindrical Equal Area, preserves true area globally).
      - If metric_type == 'length': PROJ:AEQD (Centered Azimuthal Equidistant, preserves true metric distances radiating from feature center).
    Returns: (target_crs, target_crs_name, note)
    """
    if source_crs is None:
        return None, None, "Dataset has no spatial reference (.prj missing). Cannot determine projected CRS."

    # 1. If source CRS is already projected:
    if source_crs.is_projected:
        source_unit = get_crs_linear_unit(source_crs)
        if is_metric_crs(source_crs):
            # Retain source projected CRS directly
            epsg = source_crs.to_epsg()
            name = f"EPSG:{epsg} ({source_crs.name})" if epsg else source_crs.name
            return source_crs, name, "Retained source metric projected CRS directly"
        else:
            # Source CRS is projected in non-metric units (e.g. US survey feet).
            # Convert geometry to WGS 84 to determine local metric UTM or fallback zone
            wgs84 = pyproj.CRS.from_epsg(4326)
            proj_geom_wgs, err = reproject_geometry(geom, source_crs, wgs84)
            if err or proj_geom_wgs is None:
                if metric_type == "length":
                    aeqd_crs = pyproj.CRS("+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m")
                    return aeqd_crs, "PROJ:AEQD (Azimuthal Equidistant: Global)", f"Reprojected from non-metric {source_unit} to AEQD"
                eq_area = pyproj.CRS.from_epsg(6933)
                return eq_area, "EPSG:6933 (World Cylindrical Equal Area - Global)", f"Reprojected from non-metric {source_unit} to EPSG:6933"

            bounds = proj_geom_wgs.bounds
            centroid = proj_geom_wgs.centroid
            lon, lat = centroid.x, centroid.y
            lon_span = abs(bounds[2] - bounds[0])

            if lon_span < 6.0 and -80.0 <= lat <= 84.0:
                zone = int(math.floor((lon + 180.0) / 6.0)) + 1
                zone = max(1, min(60, zone))
                is_north = lat >= 0.0
                epsg_code = 32600 + zone if is_north else 32700 + zone
                target = pyproj.CRS.from_epsg(epsg_code)
                name = f"EPSG:{epsg_code} (WGS 84 / UTM zone {zone}{'N' if is_north else 'S'})"
                return target, name, f"Reprojected from non-metric projected ({source_unit}) to metric UTM zone"

            if metric_type == "length":
                # Feature-centered Azimuthal Equidistant projection (AEQD)
                aeqd_crs = pyproj.CRS(f"+proj=aeqd +lat_0={lat:.6f} +lon_0={lon:.6f} +datum=WGS84 +units=m")
                name = f"PROJ:AEQD (Centered Azimuthal Equidistant: lon_0={lon:.2f}, lat_0={lat:.2f})"
                note = f"Reprojected from non-metric {source_unit} to Centered Azimuthal Equidistant for true metric distance"
                return aeqd_crs, name, note

            # Check if latitude is within EPSG:6933's published area of use (-86.0° to 86.0°)
            if abs(lat) <= 86.0 and bounds[1] >= -86.0 and bounds[3] <= 86.0:
                eq_area = pyproj.CRS.from_epsg(6933)
                return eq_area, "EPSG:6933 (World Cylindrical Equal Area - Global)", f"Reprojected from non-metric projected ({source_unit}) to EPSG:6933"

            return None, None, f"Geometry latitude ({lat:.2f}°) exceeds ±86.0°, which is outside the valid coverage of EPSG:6933 (-86° to 86°). Polar regions beyond ±86° are unsupported for planar measurement."

    # 2. Source is geographic (angular coordinates in degrees)
    if source_crs.is_geographic:
        wgs84 = pyproj.CRS.from_epsg(4326)
        if source_crs.to_epsg() != 4326:
            geom_wgs84, err = reproject_geometry(geom, source_crs, wgs84)
            if err or geom_wgs84 is None:
                geom_wgs84 = geom
        else:
            geom_wgs84 = geom

        bounds = geom_wgs84.bounds  # (minx, miny, maxx, maxy)
        centroid = geom_wgs84.centroid
        lon, lat = centroid.x, centroid.y
        lon_span = abs(bounds[2] - bounds[0])

        # Check if geometry fits within a single UTM zone (6 degrees of longitude)
        if lon_span < 6.0 and -80.0 <= lat <= 84.0:
            zone = int(math.floor((lon + 180.0) / 6.0)) + 1
            zone = max(1, min(60, zone))
            is_north = lat >= 0.0
            epsg_code = 32600 + zone if is_north else 32700 + zone
            projected = pyproj.CRS.from_epsg(epsg_code)
            hemisphere = "N" if is_north else "S"
            name = f"EPSG:{epsg_code} (WGS 84 / UTM zone {zone}{hemisphere})"
            return projected, name, None

        # Fallback for multi-zone (span >= 6°) or polar latitudes:
        if metric_type == "length":
            # Feature-centered Azimuthal Equidistant projection (AEQD):
            # Preserves true geodesic distance radiating from (lon_0, lat_0) with metric units (meters).
            # Eliminates massive cylindrical scale distortion (e.g. EPSG:4087 exhibits >40% distortion at 45° latitude).
            aeqd_crs = pyproj.CRS(f"+proj=aeqd +lat_0={lat:.6f} +lon_0={lon:.6f} +datum=WGS84 +units=m")
            name = f"PROJ:AEQD (Centered Azimuthal Equidistant: lon_0={lon:.2f}, lat_0={lat:.2f})"
            note = "Centered Azimuthal Equidistant projection preserving true metric distance for large-extent LineString"
            return aeqd_crs, name, note

        # Equal-area fallback for area measurement within EPSG:6933's published coverage (-86.0° to 86.0°)
        if abs(lat) <= 86.0 and bounds[1] >= -86.0 and bounds[3] <= 86.0:
            eq_area = pyproj.CRS.from_epsg(6933)
            return eq_area, "EPSG:6933 (World Cylindrical Equal Area - Global)", "Equal-area fallback for large longitudinal span (>= 6°) or polar latitude within ±86°"

        # Explicit rejection for extreme polar latitudes outside EPSG:6933's published area of use
        return None, None, f"Geometry latitude ({lat:.2f}°) exceeds ±86.0°, which is outside the valid coverage of EPSG:6933 (-86° to 86°). Polar regions beyond ±86° are unsupported for planar measurement."

    return None, None, f"Unsupported CRS type for '{source_crs.name}'"


def resolve_crs_and_project_geometry(
    geom: Optional[shapely.Geometry],
    source_crs: Optional[pyproj.CRS],
    source_crs_name: Optional[str],
    metric_type: str = "area",
) -> CRSResolutionResult:
    """
    Comprehensive CRS pipeline:
    1. Validates geometry and spatial reference presence.
    2. Inspects source CRS characteristics (geographic vs projected, linear units).
    3. Selects optimal target projected CRS (local UTM or measurement-specific fallback).
    4. Reprojects geometry using always_xy=True and captures full CRS metadata.
    """
    if geom is None or geom.is_empty:
        return CRSResolutionResult(
            source_crs=source_crs,
            source_crs_name=source_crs_name,
            is_geographic=source_crs.is_geographic if source_crs else False,
            is_projected=source_crs.is_projected if source_crs else False,
            source_linear_unit=get_crs_linear_unit(source_crs),
            normalized_wgs84=False,
            target_crs=None,
            target_crs_name=None,
            target_linear_unit=None,
            reprojected_geom=None,
            status="INVALID_GEOMETRY",
            note="Geometry is null or empty",
        )

    if source_crs is None:
        return CRSResolutionResult(
            source_crs=None,
            source_crs_name=None,
            is_geographic=False,
            is_projected=False,
            source_linear_unit=None,
            normalized_wgs84=False,
            target_crs=None,
            target_crs_name=None,
            target_linear_unit=None,
            reprojected_geom=None,
            status="UNKNOWN_CRS",
            note="Dataset is missing coordinate reference system (.prj). Reprojection cannot be performed without a defined spatial reference.",
        )

    is_geo = source_crs.is_geographic
    is_proj = source_crs.is_projected
    src_unit = get_crs_linear_unit(source_crs)

    target_crs, target_name, crs_note = determine_projected_crs(geom, source_crs, metric_type=metric_type)
    if target_crs is None:
        return CRSResolutionResult(
            source_crs=source_crs,
            source_crs_name=source_crs_name,
            is_geographic=is_geo,
            is_projected=is_proj,
            source_linear_unit=src_unit,
            normalized_wgs84=False,
            target_crs=None,
            target_crs_name=None,
            target_linear_unit=None,
            reprojected_geom=None,
            status="ERROR",
            note=crs_note or "Failed to determine target projected CRS",
        )

    tgt_unit = get_crs_linear_unit(target_crs)

    # If source is already projected and metric, geometry is retained directly
    if is_proj and is_metric_crs(source_crs) and source_crs == target_crs:
        return CRSResolutionResult(
            source_crs=source_crs,
            source_crs_name=source_crs_name,
            is_geographic=False,
            is_projected=True,
            source_linear_unit=src_unit,
            normalized_wgs84=False,
            target_crs=target_crs,
            target_crs_name=target_name,
            target_linear_unit=tgt_unit,
            reprojected_geom=geom,
            status="RETAINED_PROJECTED",
            note=crs_note or "Retained source metric projected CRS without reprojection",
        )

    # Perform reprojection
    proj_geom, err = reproject_geometry(geom, source_crs, target_crs)
    if err or proj_geom is None:
        return CRSResolutionResult(
            source_crs=source_crs,
            source_crs_name=source_crs_name,
            is_geographic=is_geo,
            is_projected=is_proj,
            source_linear_unit=src_unit,
            normalized_wgs84=is_geo,
            target_crs=target_crs,
            target_crs_name=target_name,
            target_linear_unit=tgt_unit,
            reprojected_geom=None,
            status="ERROR",
            note=err,
        )

    status_str = "NON_METRIC_REPROJECTED" if (is_proj and not is_metric_crs(source_crs)) else "SUCCESS"
    return CRSResolutionResult(
        source_crs=source_crs,
        source_crs_name=source_crs_name,
        is_geographic=is_geo,
        is_projected=is_proj,
        source_linear_unit=src_unit,
        normalized_wgs84=is_geo,
        target_crs=target_crs,
        target_crs_name=target_name,
        target_linear_unit=tgt_unit,
        reprojected_geom=proj_geom,
        status=status_str,
        note=crs_note,
    )


# ==============================================================================
# 10. MEASUREMENT ENGINE
# ==============================================================================

def calculate_feature_measurement(
    geom: Optional[shapely.Geometry],
    source_crs: Optional[pyproj.CRS],
    source_crs_name: Optional[str],
) -> Tuple[str, Optional[MeasurementDetail], Optional[str]]:
    """
    Calculate area (for Polygon / MultiPolygon) or length (for LineString / MultiLineString).
    Point and MultiPoint geometries return None with an informative note.
    Unsupported geometries and missing CRS datasets are reported gracefully without crashing.
    Enforces numeric safety checks (finite, non-NaN, non-negative).
    Returns: (status, measurement_detail, note)
    """
    if geom is None or geom.is_empty:
        return "INVALID", None, "Geometry is null or empty"

    geom_type = geom.geom_type

    # 1. Point / MultiPoint -> No measurement required
    if geom_type in ("Point", "MultiPoint"):
        return "SKIPPED", None, "Point geometry does not require area or length measurement"

    # 2. Check spatial reference availability
    if source_crs is None:
        return "ERROR", None, "Cannot perform spatial measurement: dataset is missing coordinate reference system (.prj)."

    # 3. Polygon / MultiPolygon -> Calculate Area in m²
    if geom_type in ("Polygon", "MultiPolygon"):
        clean_geom = geom
        was_repaired = False
        if not geom.is_valid:
            try:
                repaired = make_valid(geom)
                if repaired.geom_type == "GeometryCollection":
                    polys = [g for g in repaired.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
                    if not polys:
                        return "ERROR", None, "Invalid geometry could not be repaired into a valid polygon"
                    if len(polys) == 1:
                        clean_geom = polys[0]
                    else:
                        all_parts = []
                        for p in polys:
                            if p.geom_type == "Polygon":
                                all_parts.append(p)
                            elif p.geom_type == "MultiPolygon":
                                all_parts.extend(p.geoms)
                        clean_geom = shapely.geometry.MultiPolygon(all_parts)
                elif repaired.geom_type in ("Polygon", "MultiPolygon"):
                    clean_geom = repaired
                else:
                    return "UNSUPPORTED", None, f"Geometry repair resulted in unsupported type '{repaired.geom_type}'"
                was_repaired = True
            except Exception as e:
                return "ERROR", None, f"Geometry repair failed: {str(e)}"

        if clean_geom.is_empty:
            return "ERROR", None, "Repaired geometry is empty"

        crs_res = resolve_crs_and_project_geometry(clean_geom, source_crs, source_crs_name, metric_type="area")
        if crs_res.status in ("UNKNOWN_CRS", "ERROR", "INVALID_GEOMETRY") or crs_res.reprojected_geom is None:
            return "ERROR", None, crs_res.note or "Failed to reproject geometry for area measurement"

        try:
            raw_area = crs_res.reprojected_geom.area
            if not isinstance(raw_area, (int, float)) or not math.isfinite(raw_area) or math.isnan(raw_area) or raw_area < 0:
                return "ERROR", None, "Computed polygon area is non-finite or negative"

            area_m2 = round(float(raw_area), 4)
            note = crs_res.note
            if was_repaired:
                repair_note = "Self-intersecting geometry was automatically repaired prior to measurement"
                note = f"{repair_note}; {note}" if note else repair_note

            detail = MeasurementDetail(
                type="area",
                value=area_m2,
                unit="square_meters",
                input_crs=source_crs_name or "EPSG:4326 (assumed)",
                projected_crs=crs_res.target_crs_name,
            )
            return "COMPLETED", detail, note
        except Exception as e:
            return "ERROR", None, f"Failed to compute polygon area: {str(e)}"

    # 4. LineString / MultiLineString -> Calculate Length in meters
    if geom_type in ("LineString", "MultiLineString"):
        clean_geom = geom
        was_repaired = False
        if not geom.is_valid:
            try:
                repaired = make_valid(geom)
                if repaired.geom_type == "GeometryCollection":
                    lines = [g for g in repaired.geoms if g.geom_type in ("LineString", "MultiLineString")]
                    if not lines:
                        return "ERROR", None, "Invalid line geometry could not be repaired"
                    if len(lines) == 1:
                        clean_geom = lines[0]
                    else:
                        all_parts = []
                        for l in lines:
                            if l.geom_type == "LineString":
                                all_parts.append(l)
                            elif l.geom_type == "MultiLineString":
                                all_parts.extend(l.geoms)
                        clean_geom = shapely.geometry.MultiLineString(all_parts)
                elif repaired.geom_type in ("LineString", "MultiLineString"):
                    clean_geom = repaired
                else:
                    return "UNSUPPORTED", None, f"Line repair resulted in unsupported type '{repaired.geom_type}'"
                was_repaired = True
            except Exception as e:
                return "ERROR", None, f"Line repair failed: {str(e)}"

        if clean_geom.is_empty:
            return "ERROR", None, "Line geometry is empty"

        crs_res = resolve_crs_and_project_geometry(clean_geom, source_crs, source_crs_name, metric_type="length")
        if crs_res.status in ("UNKNOWN_CRS", "ERROR", "INVALID_GEOMETRY") or crs_res.reprojected_geom is None:
            return "ERROR", None, crs_res.note or "Failed to reproject geometry for length measurement"

        try:
            raw_length = crs_res.reprojected_geom.length
            if not isinstance(raw_length, (int, float)) or not math.isfinite(raw_length) or math.isnan(raw_length) or raw_length < 0:
                return "ERROR", None, "Computed line length is non-finite or negative"

            length_m = round(float(raw_length), 4)
            note = crs_res.note
            if was_repaired:
                repair_note = "Self-intersecting line geometry was automatically repaired prior to measurement"
                note = f"{repair_note}; {note}" if note else repair_note

            detail = MeasurementDetail(
                type="length",
                value=length_m,
                unit="meters",
                input_crs=source_crs_name or "EPSG:4326 (assumed)",
                projected_crs=crs_res.target_crs_name,
            )
            return "COMPLETED", detail, note
        except Exception as e:
            return "ERROR", None, f"Failed to compute line length: {str(e)}"

    # 5. Other / Unsupported types (e.g. GeometryCollection, LinearRing)
    return "UNSUPPORTED", None, f"Geometry type '{geom_type}' is not supported for area or length measurement"


# ==============================================================================
# 11. FILE PROCESSING & PERSISTENCE ORCHESTRATION
# ==============================================================================

def process_geospatial_file_sync(
    file_id: str,
    stored_path: Path,
    file_type: str,
    original_filename: str,
) -> Dict[str, Any]:
    """
    Synchronous processing routine (run in dedicated worker thread):
    1. Extracts / opens the geospatial dataset via GeoPandas / Pyogrio.
    2. Identifies features, attributes, geometries, and CRS.
    3. Executes the CRS reprojection and measurement engine for each feature.
    4. Manages its own dedicated SessionLocal session to avoid cross-thread session sharing.
    5. Persists FileRecord, FeatureRecord, and MeasurementRecord.
    """
    temp_dir = None
    try:
        # Determine read target
        if file_type == "shapefile_zip":
            temp_dir = Path(tempfile.mkdtemp(prefix="shp_extract_"))
            zip_bytes = stored_path.read_bytes()
            read_path = safe_extract_shapefile_zip(zip_bytes, temp_dir)
        else:
            read_path = stored_path

        # Read dataset into GeoDataFrame
        try:
            gdf = gpd.read_file(read_path)
        except Exception as e:
            logger.error(f"Failed to parse geospatial file '{original_filename}': {e}", exc_info=True)
            raise MalformedFileException("Unable to parse geospatial file: corrupted data or unreadable format.")

        feature_count = len(gdf)
        if feature_count == 0:
            raise UnprocessableGeospatialException("The uploaded file contains 0 geospatial features.")

        # Resolve Source CRS
        source_pyproj_crs, source_crs_str = detect_and_resolve_source_crs(gdf.crs)

        # Standard KML is WGS 84 (EPSG:4326) by specification
        if file_type == "kml" and source_pyproj_crs is None:
            source_pyproj_crs = pyproj.CRS.from_epsg(4326)
            source_crs_str = "EPSG:4326"

        # Initialize FileRecord
        file_record = FileRecord(
            id=file_id,
            filename=original_filename,
            file_type=file_type,
            crs=source_crs_str,
            feature_count=feature_count,
            status="COMPLETED",
            error_message=None,
        )

        # Dedicated database session for this worker thread
        with SessionLocal() as db_session:
            try:
                db_session.add(file_record)

                # Process each feature
                for idx, row in enumerate(gdf.iterfeatures()):
                    geom_dict = row.get("geometry")
                    raw_props = row.get("properties") or {}

                    # Sanitize properties (convert non-JSON-serializable types to valid JSON representations)
                    clean_props = {}
                    for k, v in raw_props.items():
                        if hasattr(v, "item"):
                            try:
                                v = v.item()
                            except Exception:
                                pass
                        if v is None:
                            clean_props[k] = None
                        elif isinstance(v, (int, bool, str)):
                            clean_props[k] = v
                        elif isinstance(v, float):
                            if math.isnan(v) or math.isinf(v):
                                clean_props[k] = None
                            else:
                                clean_props[k] = v
                        elif hasattr(v, "isoformat"):
                            clean_props[k] = v.isoformat()
                        elif isinstance(v, (bytes, bytearray)):
                            clean_props[k] = v.decode("utf-8", errors="replace")
                        else:
                            clean_props[k] = str(v)

                    geom = None
                    geom_type = "Unknown"
                    if geom_dict:
                        geom_type = geom_dict.get("type", "Unknown")
                        try:
                            geom = shapely.geometry.shape(geom_dict)
                        except Exception:
                            geom = None

                    # Calculate measurement
                    status_calc, measurement_detail, calc_note = calculate_feature_measurement(
                        geom, source_pyproj_crs, source_crs_str
                    )

                    # Feature Record
                    feature_record = FeatureRecord(
                        file_id=file_id,
                        feature_index=idx,
                        geometry_type=geom_type,
                        geometry_geojson=geom_dict,
                        properties=clean_props,
                        status="VALID" if status_calc in ("COMPLETED", "SKIPPED") else status_calc,
                        error_message=calc_note if status_calc in ("ERROR", "UNSUPPORTED", "INVALID") else None,
                    )
                    db_session.add(feature_record)

                    # Measurement Record
                    meas_type = measurement_detail.type if measurement_detail else "none"
                    meas_val = measurement_detail.value if measurement_detail else None
                    meas_unit = measurement_detail.unit if measurement_detail else None
                    in_crs = measurement_detail.input_crs if measurement_detail else source_crs_str
                    proj_crs = measurement_detail.projected_crs if measurement_detail else None

                    meas_record = MeasurementRecord(
                        file_id=file_id,
                        feature_index=idx,
                        geometry_type=geom_type,
                        measurement_type=meas_type,
                        measurement_value=meas_val,
                        unit=meas_unit,
                        input_crs=in_crs,
                        projected_crs=proj_crs,
                        status=status_calc,
                        note=calc_note,
                    )
                    db_session.add(meas_record)

                db_session.commit()
            except Exception:
                db_session.rollback()
                raise

        return {
            "id": file_id,
            "filename": original_filename,
            "file_type": file_type,
            "feature_count": feature_count,
            "crs": source_crs_str,
            "status": "COMPLETED",
        }

    finally:
        # Cleanup temporary extraction directory
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 12. FASTAPI APPLICATION SETUP & LIFESPAN
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle handler."""
    # Create SQLite database tables on startup
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    description=(
        "Production-quality backend service for uploading .kml and .zip Shapefiles, "
        "extracting features, resolving coordinate reference systems, and measuring planar areas and lengths."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
CORS_ORIGINS_ENV = os.environ.get(
    "CORS_ORIGINS",
    "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:8000,http://localhost:8000,*",
)
if CORS_ORIGINS_ENV.strip() == "*":
    ALLOWED_ORIGINS = ["*"]
    ALLOW_CREDENTIALS = False
else:
    raw_origins = [orig.strip() for orig in CORS_ORIGINS_ENV.split(",") if orig.strip()]
    ALLOWED_ORIGINS = raw_origins
    ALLOW_CREDENTIALS = False if "*" in raw_origins else True

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handlers
@app.exception_handler(GeospatialAPIError)
async def geospatial_api_error_handler(request: Request, exc: GeospatialAPIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.__class__.__name__, "detail": exc.message},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTPException", "detail": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "ValidationError", "detail": "Invalid request parameters or payload."},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "InternalServerError", "detail": "An unexpected server error occurred."},
    )


# ==============================================================================
# 13. API ROUTES
# ==============================================================================

@app.get(
    "/api/health/",
    response_model=HealthResponse,
    summary="Service health check",
    description="Check the operational status of the Geospatial File Measurement API and verify database connectivity.",
    tags=["Health"],
)
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint to verify backend operational readiness and database connectivity."""
    try:
        db.execute(select(1)).scalar()
    except Exception as e:
        logger.error(f"Database connectivity check failed during health check: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database connectivity failure")

    return {
        "status": "ok",
        "service": "Geospatial File Measurement API",
    }


@app.post(
    "/api/files/",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a geospatial file",
    description="Upload a .kml file or a .zip containing an ESRI Shapefile (.shp, .shx, .dbf). Extracts features, detects CRS, and computes planar measurements.",
    tags=["Files"],
    responses={
        400: {"model": ErrorResponse, "description": "Malformed, invalid, or unsupported file"},
        413: {"model": ErrorResponse, "description": "File exceeds upload size limit"},
        422: {"model": ErrorResponse, "description": "Zero parseable features found"},
        500: {"model": ErrorResponse, "description": "Internal server processing error"},
    },
)
async def upload_file(
    file: UploadFile = File(..., description="Geospatial file (.kml or .zip Shapefile) to upload and process"),
):
    """
    Accepts .kml and .zip containing a Shapefile.
    Validates, extracts, reprojects, measures, and persists.
    """
    if not file.filename:
        raise MalformedFileException("Uploaded file has no filename.")

    clean_name = sanitize_filename(file.filename)
    file_ext = Path(clean_name).suffix.lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeException(
            f"Invalid file extension '{file_ext}'. Allowed formats: .kml, .zip (containing Shapefile)."
        )

    file_type = "kml" if file_ext == ".kml" else "shapefile_zip"

    # Stream content into memory with size limitation
    chunks = []
    total_bytes = 0

    while True:
        chunk = await file.read(1024 * 64)  # 64 KB chunk
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_SIZE_BYTES:
            # Drain remaining upload stream so client/browser receives HTTP 413 cleanly without TCP connection reset
            while await file.read(1024 * 256):
                pass
            raise FileTooLargeException(f"Uploaded file exceeds maximum limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.")
        chunks.append(chunk)

    if total_bytes == 0:
        raise MalformedFileException("Uploaded file is empty (0 bytes).")

    content = b"".join(chunks)

    # Magic byte verification
    validate_file_magic_bytes(content[:1024], file_ext)

    # XML and KML structural and security validation
    if file_type == "kml":
        validate_and_sanitize_kml(content)

    # Store file in unique directory with explicit path containment verification
    file_id = str(uuid.uuid4())
    file_store_dir = (STORAGE_DIR / file_id).resolve()
    if not str(file_store_dir).startswith(str(STORAGE_DIR)):
        raise SecurityException("Directory traversal attempt detected in storage destination.")
    file_store_dir.mkdir(parents=True, exist_ok=True)
    saved_file_path = (file_store_dir / clean_name).resolve()
    if not str(saved_file_path).startswith(str(file_store_dir)):
        raise SecurityException("Filename path traversal attempt detected.")
    saved_file_path.write_bytes(content)

    # Run blocking geospatial parsing & calculation in worker thread
    # Worker thread manages its own SessionLocal session
    try:
        result = await run_in_threadpool(
            process_geospatial_file_sync,
            file_id=file_id,
            stored_path=saved_file_path,
            file_type=file_type,
            original_filename=clean_name,
        )
    except GeospatialAPIError:
        if file_store_dir.exists():
            shutil.rmtree(file_store_dir, ignore_errors=True)
        raise
    except Exception as e:
        if file_store_dir.exists():
            shutil.rmtree(file_store_dir, ignore_errors=True)
        logger.error(f"Unexpected error processing uploaded file {file_id}: {e}", exc_info=True)
        raise MalformedFileException("Failed to process geospatial file: corrupted data or unreadable format.")

    return FileUploadResponse(
        id=result["id"],
        filename=result["filename"],
        file_type=result.get("file_type", file_type),
        feature_count=result["feature_count"],
        crs=result["crs"],
        status=result["status"],
    )


@app.get(
    "/api/files/{id}/",
    response_model=FileDetailResponse,
    summary="Get file details and features",
    description="Retrieve metadata, CRS, and feature details for a processed geospatial file.",
    tags=["Files"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file ID format"},
        404: {"model": ErrorResponse, "description": "File not found"},
    },
)
async def get_file_detail(
    id: str = APIPath(..., description="Unique UUID identifier of the uploaded file"),
    db: Session = Depends(get_db),
):
    """Retrieve file details, status, and extracted features by file ID."""
    if not id or not id.strip() or len(id) > 128:
        raise ResourceNotFoundException("Invalid or empty file ID.")

    clean_id = id.strip()
    file_record = db.execute(select(FileRecord).where(FileRecord.id == clean_id)).scalar_one_or_none()
    if not file_record:
        raise ResourceNotFoundException(f"File with ID '{id}' was not found.")

    features = [
        FeatureDetailResponse(
            feature_id=feat.feature_index,
            geometry_type=feat.geometry_type,
            geometry=feat.geometry_geojson,
            crs=file_record.crs,
            properties=feat.properties or {},
            status=feat.status,
            error_message=feat.error_message,
        )
        for feat in file_record.features
    ]

    return FileDetailResponse(
        id=file_record.id,
        filename=file_record.filename,
        file_type=file_record.file_type,
        feature_count=file_record.feature_count,
        crs=file_record.crs,
        status=file_record.status,
        error_message=file_record.error_message,
        created_at=file_record.created_at,
        features=features,
    )


@app.get(
    "/api/files/{id}/measurements/",
    response_model=FileMeasurementListResponse,
    summary="Get measurements for a file",
    description="Retrieve calculated area (for Polygons) and length (for LineStrings) in metric units.",
    tags=["Measurements"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file ID format"},
        404: {"model": ErrorResponse, "description": "File not found"},
    },
)
async def get_file_measurements(
    id: str = APIPath(..., description="Unique UUID identifier of the uploaded file"),
    db: Session = Depends(get_db),
):
    """Retrieve measurement results for all features in the file."""
    if not id or not id.strip() or len(id) > 128:
        raise ResourceNotFoundException("Invalid or empty file ID.")

    clean_id = id.strip()
    file_record = db.execute(select(FileRecord).where(FileRecord.id == clean_id)).scalar_one_or_none()
    if not file_record:
        raise ResourceNotFoundException(f"File with ID '{id}' was not found.")

    measurements = []
    for meas in file_record.measurements:
        detail = None
        if meas.measurement_type in ("area", "length") and meas.measurement_value is not None:
            detail = MeasurementDetail(
                type=meas.measurement_type,
                value=meas.measurement_value,
                unit=meas.unit,
                input_crs=meas.input_crs,
                projected_crs=meas.projected_crs,
            )

        measurements.append(
            FeatureMeasurementResponse(
                feature_id=meas.feature_index,
                geometry_type=meas.geometry_type,
                status=meas.status,
                measurement=detail,
                note=meas.note,
            )
        )

    return FileMeasurementListResponse(
        file_id=file_record.id,
        filename=file_record.filename,
        status=file_record.status,
        total_features=len(measurements),
        measurements=measurements,
    )


# ==============================================================================
# 14. APPLICATION ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("UVICORN_RELOAD", "false").lower() in ("true", "1", "yes")

    # Run Uvicorn server (production-safe default without reload)
    uvicorn.run("main:app", host=host, port=port, reload=reload)
