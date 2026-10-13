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
import hashlib
import io
import logging
import math
import os
import re
import secrets
import shutil
import tempfile
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import argon2

# Web & API Framework
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status, Path as APIPath
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("geospatial_api")
logging.basicConfig(level=logging.INFO)

# Persistence
from sqlalchemy import (
    JSON,
    Boolean,
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
    func,
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
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# Ensure storage directory exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Developer Platform & Authentication Secrets
API_KEY_PEPPER = os.environ.get("API_KEY_PEPPER", "gfm_dev_pepper_default_secret_32char_minimum")
AUTH_SECRET_KEY = os.environ.get("AUTH_SECRET_KEY", "gfm_session_secret_default_32char_minimum")
AUTH_TOKEN_EXPIRE_DAYS = int(os.environ.get("AUTH_TOKEN_EXPIRE_DAYS", "7"))


# ==============================================================================
# 3. DATABASE SETUP & CRYPTOGRAPHIC SECURITY HELPERS
# ==============================================================================

_engine_kwargs: Dict[str, Any] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL connection pool settings for durable restart handling
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
    _engine_kwargs["pool_recycle"] = 1800

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

# Argon2id password hasher instance
_password_hasher = argon2.PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    type=argon2.Type.ID,
)


def hash_password(password: str) -> str:
    """Hash plaintext password using Argon2id."""
    return _password_hasher.hash(password)


def verify_password(password: str, hash_str: str) -> bool:
    """Verify password against Argon2id hash with timing attack resistance."""
    try:
        return _password_hasher.verify(hash_str, password)
    except Exception:
        return False


def hash_session_token(token: str) -> str:
    """Compute SHA-256 digest of session token with server secret."""
    return hashlib.sha256((AUTH_SECRET_KEY + token).encode("utf-8")).hexdigest()


def hash_api_key(raw_key: str) -> str:
    """Compute SHA-256 digest of raw API key with deployment pepper."""
    return hashlib.sha256((API_KEY_PEPPER + raw_key).encode("utf-8")).hexdigest()


def generate_api_key(environment: str = "live") -> Tuple[str, str, str, str]:
    """
    Generate cryptographically secure API key with 256 bits of CSPRNG entropy.
    Returns: (raw_key, prefix, last_four, key_hash)
    """
    prefix = "gfm_live_" if environment == "live" else "gfm_test_"
    entropy = secrets.token_hex(32)  # 32 bytes = 256 bits of CSPRNG entropy (64 hex characters)
    raw_key = f"{prefix}{entropy}"
    last_four = raw_key[-4:]
    key_hash = hash_api_key(raw_key)
    return raw_key, prefix, last_four, key_hash


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

    # Multi-tenant developer platform ownership (nullable for legacy public uploads)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)

    features = relationship(
        "FeatureRecord", back_populates="file", cascade="all, delete-orphan", order_by="FeatureRecord.feature_index"
    )
    measurements = relationship(
        "MeasurementRecord", back_populates="file", cascade="all, delete-orphan", order_by="MeasurementRecord.feature_index"
    )
    project = relationship("ProjectRecord", back_populates="files")


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


class UserRecord(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    projects = relationship("ProjectRecord", back_populates="owner", cascade="all, delete-orphan")
    sessions = relationship("SessionRecord", back_populates="user", cascade="all, delete-orphan")


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)

    user = relationship("UserRecord", back_populates="sessions")


class ProjectRecord(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, index=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    tier = Column(String(50), default="free")
    daily_request_limit = Column(Integer, default=1000)
    monthly_request_limit = Column(Integer, default=10000)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("UserRecord", back_populates="projects")
    api_keys = relationship("APIKeyRecord", back_populates="project", cascade="all, delete-orphan")
    files = relationship("FileRecord", back_populates="project")
    usage_records = relationship("UsageRecord", back_populates="project")


class APIKeyRecord(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    key_prefix = Column(String(20), nullable=False)
    last_four = Column(String(10), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    scopes = Column(JSON, default=lambda: ["read", "write"])
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    project = relationship("ProjectRecord", back_populates="api_keys")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    api_key_id = Column(String(36), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, nullable=True)
    bytes_uploaded = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    project = relationship("ProjectRecord", back_populates="usage_records")


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


# --- Developer Platform Schemas ---

class UserRegisterRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)


class UserLoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    daily_request_limit: Optional[int] = Field(None, ge=1, le=1000000)
    monthly_request_limit: Optional[int] = Field(None, ge=1, le=10000000)


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    daily_request_limit: Optional[int] = Field(None, ge=1, le=1000000)
    monthly_request_limit: Optional[int] = Field(None, ge=1, le=10000000)
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tier: str
    daily_request_limit: int
    monthly_request_limit: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    projects: List[ProjectResponse]
    total: int


class APIKeyCreateRequest(BaseModel):
    name: str
    environment: str = "live"
    scopes: Optional[List[str]] = Field(default_factory=lambda: ["read", "write"])
    expires_in_days: Optional[int] = None


class APIKeyCreatedResponse(BaseModel):
    id: str
    name: str
    key: str  # Revealed ONLY ONCE on generation!
    key_prefix: str
    last_four: str
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime] = None


class APIKeyMetadataResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    last_four: str
    scopes: List[str]
    is_revoked: bool
    revoked_at: Optional[datetime] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class APIKeyListResponse(BaseModel):
    keys: List[APIKeyMetadataResponse]
    total: int


class ProjectUsageResponse(BaseModel):
    project_id: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    bytes_uploaded: int
    daily_limit: int
    monthly_limit: int
    requests_today: int
    requests_this_month: int


class DeveloperFileSummaryResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: Optional[str] = None
    status: str
    created_at: datetime


class DeveloperFileListResponse(BaseModel):
    files: List[DeveloperFileSummaryResponse]
    total: int


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


class SecurityException(GeospatialAPIError):
    def __init__(self, message: str = "Security validation error"):
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST)


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
            if (
                re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text)
                or text.startswith(("\\\\", "//", "data:", "javascript:", "vbscript:", "netdoc:"))
            ):
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
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
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
            user_id=user_id,
            project_id=project_id,
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
                        if hasattr(v, "item") and callable(getattr(v, "item")):
                            try:
                                v = v.item()
                            except (ValueError, TypeError, AttributeError):
                                logger.debug("Could not convert property value via .item(), keeping raw representation")
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
    Base.metadata.create_all(bind=engine)
    try:
        from migrations import run_migrations
        run_migrations(engine)
    except Exception as e:
        logger.warning(f"Startup migration execution note: {e}")
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


# ==============================================================================
# DEFENSIVE SECURITY MIDDLEWARE: HEADERS & RATE LIMITING
# ==============================================================================

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Inject defensive HTTP security response headers."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    if request.url.path.startswith("/api/"):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


UPLOAD_RATE_LIMIT_PER_MINUTE = _parse_env_int("UPLOAD_RATE_LIMIT_PER_MINUTE", 60)
READ_RATE_LIMIT_PER_MINUTE = _parse_env_int("READ_RATE_LIMIT_PER_MINUTE", 300)
RATE_LIMIT_PER_MINUTE = READ_RATE_LIMIT_PER_MINUTE

_rate_limit_lock = asyncio.Lock()
_ip_upload_timestamps: Dict[str, List[float]] = {}
_ip_read_timestamps: Dict[str, List[float]] = {}


def get_client_ip(request: Request) -> str:
    """
    Safely extract client IP address:
    1. Prioritizes Cloudflare 'CF-Connecting-IP' header when present (guaranteed authentic by Cloudflare proxy edge).
    2. Falls back to direct TCP socket peer host (request.client.host).
    3. Avoids blindly trusting arbitrary client-supplied 'X-Forwarded-For' headers to prevent rate-limit bypass.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and re.match(r"^[0-9a-fA-F:.]+$", cf_ip.strip()):
        return cf_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    """In-memory sliding-window IP rate limiter for DoS defense with separate upload and read limits."""
    # Exempt OPTIONS preflight requests, health checks, and API documentation
    if request.method == "OPTIONS" or request.url.path in ("/api/health/", "/docs", "/redoc", "/openapi.json"):
        return await call_next(request)

    client_ip = get_client_ip(request)
    now = datetime.utcnow().timestamp()

    is_upload = request.method == "POST" and request.url.path.rstrip("/").endswith("/api/files")
    limit = UPLOAD_RATE_LIMIT_PER_MINUTE if is_upload else READ_RATE_LIMIT_PER_MINUTE

    async with _rate_limit_lock:
        store = _ip_upload_timestamps if is_upload else _ip_read_timestamps
        timestamps = store.get(client_ip, [])
        cutoff = now - 60.0
        timestamps = [ts for ts in timestamps if ts > cutoff]

        if len(timestamps) >= limit:
            action_label = "upload" if is_upload else "request"
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "RateLimitExceeded",
                    "detail": f"Rate limit of {limit} {action_label}s/minute exceeded for this client. Please retry later.",
                },
                headers={"Retry-After": "60"},
            )
        timestamps.append(now)
        store[client_ip] = timestamps

    return await call_next(request)


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


async def execute_file_ingestion(
    file: UploadFile,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], int]:
    """Execute upload validation, security guards, storage, and worker processing."""
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
    try:
        result = await run_in_threadpool(
            process_geospatial_file_sync,
            file_id=file_id,
            stored_path=saved_file_path,
            file_type=file_type,
            original_filename=clean_name,
            user_id=user_id,
            project_id=project_id,
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

    return result, total_bytes


@app.post(
    "/api/files/",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a geospatial file (Legacy Anonymous)",
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
    """Legacy public anonymous upload endpoint."""
    result, _ = await execute_file_ingestion(file, user_id=None, project_id=None)
    return FileUploadResponse(
        id=result["id"],
        filename=result["filename"],
        file_type=result.get("file_type", "unknown"),
        feature_count=result["feature_count"],
        crs=result["crs"],
        status=result["status"],
    )


@app.get(
    "/api/files/{id}/",
    response_model=FileDetailResponse,
    summary="Get file details and features (Legacy Anonymous)",
    description="Retrieve metadata, CRS, and feature details for an anonymously uploaded geospatial file.",
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
    """Retrieve file details by file ID for anonymous files only."""
    if not id or not id.strip() or len(id) > 128:
        raise ResourceNotFoundException("Invalid or empty file ID.")

    clean_id = id.strip()
    file_record = db.execute(select(FileRecord).where(FileRecord.id == clean_id)).scalar_one_or_none()
    if not file_record or file_record.project_id is not None:
        safe_display = re.sub(r"[^a-zA-Z0-9_\-]", "", clean_id)[:64]
        raise ResourceNotFoundException(f"File with ID '{safe_display}' was not found.")

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
    summary="Get measurements for a file (Legacy Anonymous)",
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
    """Retrieve measurement results by file ID for anonymous files only."""
    if not id or not id.strip() or len(id) > 128:
        raise ResourceNotFoundException("Invalid or empty file ID.")

    clean_id = id.strip()
    file_record = db.execute(select(FileRecord).where(FileRecord.id == clean_id)).scalar_one_or_none()
    if not file_record or file_record.project_id is not None:
        safe_display = re.sub(r"[^a-zA-Z0-9_\-]", "", clean_id)[:64]
        raise ResourceNotFoundException(f"File with ID '{safe_display}' was not found.")

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
# DEVELOPER PLATFORM AUTHENTICATION & CONTEXT DEPENDENCIES
# ==============================================================================

@dataclass
class APIKeyContext:
    key: APIKeyRecord
    project: ProjectRecord
    user_id: str


def record_api_usage(
    db: Session,
    project_id: Optional[str],
    api_key_id: Optional[str],
    user_id: Optional[str],
    endpoint: str,
    method: str,
    status_code: int,
    response_time_ms: float,
    bytes_uploaded: int = 0,
) -> None:
    """Record verified developer API usage for accounting and operational analytics."""
    try:
        usage = UsageRecord(
            project_id=project_id,
            api_key_id=api_key_id,
            user_id=user_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            bytes_uploaded=bytes_uploaded,
            timestamp=datetime.utcnow(),
        )
        db.add(usage)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to record API usage metric: {e}")
        db.rollback()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserRecord:
    """Resolve authenticated developer from Bearer token or session cookie."""
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("session_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = hash_session_token(token)
    session_rec = db.execute(
        select(SessionRecord).where(
            SessionRecord.token_hash == token_hash,
            SessionRecord.expires_at > datetime.utcnow(),
        )
    ).scalar_one_or_none()

    if not session_rec:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or is invalid. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session_rec.last_active_at = datetime.utcnow()
    db.commit()

    user = db.execute(select(UserRecord).where(UserRecord.id == session_rec.user_id)).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Developer account is deactivated or unavailable.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_api_key_context(
    request: Request,
    db: Session = Depends(get_db),
) -> APIKeyContext:
    """Authenticate incoming developer requests via X-API-Key or Bearer API key."""
    raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            candidate = auth_header[7:].strip()
            if candidate.startswith("gfm_live_") or candidate.startswith("gfm_test_"):
                raw_key = candidate

    if not raw_key or not (raw_key.startswith("gfm_live_") or raw_key.startswith("gfm_test_")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API key required. Provide via 'X-API-Key' header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_hash = hash_api_key(raw_key)
    key_rec = db.execute(select(APIKeyRecord).where(APIKeyRecord.key_hash == key_hash)).scalar_one_or_none()

    if not key_rec or key_rec.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if key_rec.expires_at and key_rec.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has expired.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == key_rec.project_id)).scalar_one_or_none()
    if not project or not project.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Associated project is inactive or disabled.",
        )

    # Enforce daily request quotas
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_requests = db.execute(
        select(func.count(UsageRecord.id)).where(
            UsageRecord.project_id == project.id,
            UsageRecord.timestamp >= today_start,
        )
    ).scalar_one() or 0

    if today_requests >= project.daily_request_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily request quota ({project.daily_request_limit}) exceeded for project '{project.name}'.",
        )

    key_rec.last_used_at = datetime.utcnow()
    # Record usage for non-upload developer endpoints (upload endpoint records its own metrics with byte counts)
    if not (request.url.path == "/api/v1/files/" and request.method == "POST"):
        record_api_usage(
            db,
            project_id=project.id,
            api_key_id=key_rec.id,
            user_id=project.owner_id,
            endpoint=request.url.path,
            method=request.method,
            status_code=200,
            response_time_ms=1.0,
            bytes_uploaded=0,
        )
    db.commit()

    return APIKeyContext(key=key_rec, project=project, user_id=project.owner_id)


# ==============================================================================
# DEVELOPER PLATFORM V1 ROUTER & ENDPOINTS
# ==============================================================================

# --- 1. Developer Identity & Authentication ---

@app.post(
    "/api/v1/auth/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new developer account",
    tags=["Developer Platform - Auth"],
)
async def register_developer(req: UserRegisterRequest, db: Session = Depends(get_db)):
    """Register a developer account with Argon2id hashing and auto-generate default project."""
    clean_email = req.email.strip().lower()
    if not re.match(r"^[\w\.\+\-]+@[\w\-]+\.[\w\.\-]+$", clean_email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address format.")
    if len(req.password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters long.")

    existing = db.execute(select(UserRecord).where(UserRecord.email == clean_email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email address already exists.")

    user_id = str(uuid.uuid4())
    user = UserRecord(
        id=user_id,
        email=clean_email,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()

    # Automatically provision default project
    default_project = ProjectRecord(
        id=str(uuid.uuid4()),
        owner_id=user.id,
        name="Default Project",
        description="Default workspace project for API keys and survey calculations",
        created_at=datetime.utcnow(),
    )
    db.add(default_project)

    # Generate initial session token
    raw_token = f"gfm_sess_{secrets.token_urlsafe(32)}"
    session_rec = SessionRecord(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(days=AUTH_TOKEN_EXPIRE_DAYS),
        created_at=datetime.utcnow(),
    )
    db.add(session_rec)
    db.commit()

    user_resp = UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )
    return AuthTokenResponse(access_token=raw_token, token_type="bearer", user=user_resp)  # nosec B106


@app.post(
    "/api/v1/auth/login",
    response_model=AuthTokenResponse,
    summary="Sign in to developer account",
    tags=["Developer Platform - Auth"],
)
async def login_developer(req: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate developer credentials and return a secure session token."""
    clean_email = req.email.strip().lower()
    user = db.execute(select(UserRecord).where(UserRecord.email == clean_email)).scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account is deactivated.")

    raw_token = f"gfm_sess_{secrets.token_urlsafe(32)}"
    session_rec = SessionRecord(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(days=AUTH_TOKEN_EXPIRE_DAYS),
        created_at=datetime.utcnow(),
    )
    db.add(session_rec)
    db.commit()

    user_resp = UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )
    return AuthTokenResponse(access_token=raw_token, token_type="bearer", user=user_resp)  # nosec B106


@app.get(
    "/api/v1/auth/me",
    response_model=UserResponse,
    summary="Get current authenticated developer profile",
    tags=["Developer Platform - Auth"],
)
async def get_me(current_user: UserRecord = Depends(get_current_user)):
    """Return profile for active session."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


@app.post(
    "/api/v1/auth/logout",
    summary="Sign out of developer account",
    tags=["Developer Platform - Auth"],
)
async def logout_developer(
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Invalidate current session token."""
    auth_header = request.headers.get("Authorization")
    token = auth_header[7:].strip() if auth_header and auth_header.startswith("Bearer ") else request.cookies.get("session_token")
    if token:
        token_hash = hash_session_token(token)
        session_rec = db.execute(select(SessionRecord).where(SessionRecord.token_hash == token_hash)).scalar_one_or_none()
        if session_rec:
            db.delete(session_rec)
            db.commit()
    return {"status": "ok", "message": "Signed out successfully."}


@app.post(
    "/api/v1/auth/change-password",
    summary="Change developer password",
    tags=["Developer Platform - Auth"],
)
async def change_password(
    req: ChangePasswordRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update password and invalidate all active sessions."""
    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password does not match.")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters long.")

    current_user.password_hash = hash_password(req.new_password)
    # Revoke sessions
    for sess in current_user.sessions:
        db.delete(sess)
    db.commit()
    return {"status": "ok", "message": "Password changed successfully. Please sign in again."}


# --- 2. Developer Project Management ---

@app.post(
    "/api/v1/projects/",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new developer project",
    tags=["Developer Platform - Projects"],
)
async def create_project(
    req: ProjectCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new tenant project owned by the authenticated developer."""
    if not req.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project name is required.")

    project = ProjectRecord(
        id=str(uuid.uuid4()),
        owner_id=current_user.id,
        name=req.name.strip(),
        description=req.description,
        is_active=True,
        tier="free",
        daily_request_limit=req.daily_request_limit if req.daily_request_limit is not None else 1000,
        monthly_request_limit=req.monthly_request_limit if req.monthly_request_limit is not None else 10000,
        created_at=datetime.utcnow(),
    )
    db.add(project)
    db.commit()
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        tier=project.tier,
        daily_request_limit=project.daily_request_limit,
        monthly_request_limit=project.monthly_request_limit,
        is_active=project.is_active,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@app.get(
    "/api/v1/projects/",
    response_model=ProjectListResponse,
    summary="List developer projects",
    tags=["Developer Platform - Projects"],
)
async def list_projects(
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all projects owned by the authenticated developer."""
    projects = db.execute(
        select(ProjectRecord).where(ProjectRecord.owner_id == current_user.id).order_by(ProjectRecord.created_at.desc())
    ).scalars().all()

    resp_list = [
        ProjectResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            tier=p.tier,
            daily_request_limit=p.daily_request_limit,
            monthly_request_limit=p.monthly_request_limit,
            is_active=p.is_active,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in projects
    ]
    return ProjectListResponse(projects=resp_list, total=len(resp_list))


@app.get(
    "/api/v1/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
    tags=["Developer Platform - Projects"],
)
async def get_project(
    project_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve details for a specific project. Enforces ownership verification."""
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        tier=project.tier,
        daily_request_limit=project.daily_request_limit,
        monthly_request_limit=project.monthly_request_limit,
        is_active=project.is_active,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@app.patch(
    "/api/v1/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Update project metadata",
    tags=["Developer Platform - Projects"],
)
async def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update name or description for a project. Enforces ownership."""
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if req.name is not None and req.name.strip():
        project.name = req.name.strip()
    if req.description is not None:
        project.description = req.description
    if req.daily_request_limit is not None:
        project.daily_request_limit = req.daily_request_limit
    if req.monthly_request_limit is not None:
        project.monthly_request_limit = req.monthly_request_limit
    if req.is_active is not None:
        project.is_active = req.is_active
    project.updated_at = datetime.utcnow()
    db.commit()

    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        tier=project.tier,
        daily_request_limit=project.daily_request_limit,
        monthly_request_limit=project.monthly_request_limit,
        is_active=project.is_active,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@app.delete(
    "/api/v1/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
    tags=["Developer Platform - Projects"],
)
async def delete_project(
    project_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete project and associated API keys. Enforces ownership."""
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 3. API Key Management ---

@app.post(
    "/api/v1/projects/{project_id}/api-keys/",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new API key for a project",
    tags=["Developer Platform - API Keys"],
)
async def create_api_key(
    project_id: str,
    req: APIKeyCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate a new API key.
    The raw key is returned STRICTLY ONCE in this response and is never stored in recoverable plaintext.
    """
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    raw_key, prefix, last_four, key_hash = generate_api_key(req.environment)
    expires_at = None
    if req.expires_in_days and req.expires_in_days > 0:
        expires_at = datetime.utcnow() + timedelta(days=req.expires_in_days)

    key_rec = APIKeyRecord(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=req.name.strip() if req.name else "API Key",
        key_prefix=prefix,
        last_four=last_four,
        key_hash=key_hash,
        scopes=req.scopes or ["read", "write"],
        is_revoked=False,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
    )
    db.add(key_rec)
    db.commit()

    return APIKeyCreatedResponse(
        id=key_rec.id,
        name=key_rec.name,
        key=raw_key,
        key_prefix=key_rec.key_prefix,
        last_four=key_rec.last_four,
        scopes=key_rec.scopes or ["read", "write"],
        created_at=key_rec.created_at,
        expires_at=key_rec.expires_at,
    )


@app.get(
    "/api/v1/projects/{project_id}/api-keys/",
    response_model=APIKeyListResponse,
    summary="List API keys for a project",
    tags=["Developer Platform - API Keys"],
)
async def list_api_keys(
    project_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List API key metadata for a project. Never exposes stored secrets."""
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    keys = db.execute(
        select(APIKeyRecord).where(APIKeyRecord.project_id == project.id).order_by(APIKeyRecord.created_at.desc())
    ).scalars().all()

    resp_keys = [
        APIKeyMetadataResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            last_four=k.last_four,
            scopes=k.scopes or ["read", "write"],
            is_revoked=k.is_revoked,
            revoked_at=k.revoked_at,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
        )
        for k in keys
    ]
    return APIKeyListResponse(keys=resp_keys, total=len(resp_keys))


@app.post(
    "/api/v1/projects/{project_id}/api-keys/{key_id}/revoke",
    summary="Revoke an API key immediately",
    tags=["Developer Platform - API Keys"],
)
async def revoke_api_key(
    project_id: str,
    key_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Immediately revoke an API key. Enforces project and key ownership."""
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    key_rec = db.execute(
        select(APIKeyRecord).where(APIKeyRecord.id == key_id, APIKeyRecord.project_id == project.id)
    ).scalar_one_or_none()
    if not key_rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")

    key_rec.is_revoked = True
    key_rec.revoked_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "message": "API key has been revoked successfully."}


@app.post(
    "/api/v1/projects/{project_id}/api-keys/{key_id}/rotate",
    response_model=APIKeyCreatedResponse,
    summary="Rotate an API key (revoke old, generate new)",
    tags=["Developer Platform - API Keys"],
)
async def rotate_api_key(
    project_id: str,
    key_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atomically revoke the existing key and generate a fresh replacement."""
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    old_key = db.execute(
        select(APIKeyRecord).where(APIKeyRecord.id == key_id, APIKeyRecord.project_id == project.id)
    ).scalar_one_or_none()
    if not old_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")

    # Revoke old key
    old_key.is_revoked = True
    old_key.revoked_at = datetime.utcnow()

    # Generate new key
    raw_key, prefix, last_four, key_hash = generate_api_key(
        "live" if old_key.key_prefix == "gfm_live_" else "test"
    )
    new_key = APIKeyRecord(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=f"{old_key.name} (Rotated)",
        key_prefix=prefix,
        last_four=last_four,
        key_hash=key_hash,
        scopes=old_key.scopes or ["read", "write"],
        is_revoked=False,
        created_at=datetime.utcnow(),
        expires_at=old_key.expires_at,
    )
    db.add(new_key)
    db.commit()

    return APIKeyCreatedResponse(
        id=new_key.id,
        name=new_key.name,
        key=raw_key,
        key_prefix=new_key.key_prefix,
        last_four=new_key.last_four,
        scopes=new_key.scopes or ["read", "write"],
        created_at=new_key.created_at,
        expires_at=new_key.expires_at,
    )


# --- 4. Usage Analytics ---

@app.get(
    "/api/v1/projects/{project_id}/usage",
    response_model=ProjectUsageResponse,
    summary="Get real-time project usage analytics and quota metrics",
    tags=["Developer Platform - Usage"],
)
async def get_project_usage(
    project_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aggregate actual API request counts, uploaded bytes, and quota metrics for a project."""
    project = db.execute(select(ProjectRecord).where(ProjectRecord.id == project_id)).scalar_one_or_none()
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_requests = db.execute(
        select(func.count(UsageRecord.id)).where(UsageRecord.project_id == project.id)
    ).scalar_one() or 0

    successful_requests = db.execute(
        select(func.count(UsageRecord.id)).where(
            UsageRecord.project_id == project.id,
            UsageRecord.status_code >= 200,
            UsageRecord.status_code < 400,
        )
    ).scalar_one() or 0

    failed_requests = db.execute(
        select(func.count(UsageRecord.id)).where(
            UsageRecord.project_id == project.id,
            UsageRecord.status_code >= 400,
        )
    ).scalar_one() or 0

    bytes_uploaded = db.execute(
        select(func.sum(UsageRecord.bytes_uploaded)).where(UsageRecord.project_id == project.id)
    ).scalar_one() or 0

    requests_today = db.execute(
        select(func.count(UsageRecord.id)).where(
            UsageRecord.project_id == project.id,
            UsageRecord.timestamp >= today_start,
        )
    ).scalar_one() or 0

    requests_this_month = db.execute(
        select(func.count(UsageRecord.id)).where(
            UsageRecord.project_id == project.id,
            UsageRecord.timestamp >= month_start,
        )
    ).scalar_one() or 0

    return ProjectUsageResponse(
        project_id=project.id,
        total_requests=total_requests,
        successful_requests=successful_requests,
        failed_requests=failed_requests,
        bytes_uploaded=int(bytes_uploaded),
        daily_limit=project.daily_request_limit,
        monthly_limit=project.monthly_request_limit,
        requests_today=requests_today,
        requests_this_month=requests_this_month,
    )


# --- 5. Versioned Geospatial API Routes (API-Key Protected & Tenant Isolated) ---

@app.post(
    "/api/v1/files/",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process geospatial file (API-Key Protected)",
    description="Upload a .kml file or a .zip containing an ESRI Shapefile. Associates survey data with the authenticated developer project.",
    tags=["Developer Platform - Files"],
)
async def developer_upload_file(
    file: UploadFile = File(..., description="Geospatial file (.kml or .zip Shapefile) to process"),
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: Session = Depends(get_db),
):
    """Ingest geospatial file under authenticated tenant project."""
    start_time = time.time()
    try:
        result, byte_count = await execute_file_ingestion(file, user_id=ctx.user_id, project_id=ctx.project.id)
        elapsed_ms = (time.time() - start_time) * 1000.0
        record_api_usage(
            db,
            project_id=ctx.project.id,
            api_key_id=ctx.key.id,
            user_id=ctx.user_id,
            endpoint="/api/v1/files/",
            method="POST",
            status_code=201,
            response_time_ms=elapsed_ms,
            bytes_uploaded=byte_count,
        )
        return FileUploadResponse(
            id=result["id"],
            filename=result["filename"],
            file_type=result.get("file_type", "unknown"),
            feature_count=result["feature_count"],
            crs=result["crs"],
            status=result["status"],
        )
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000.0
        status_code = getattr(e, "status_code", 400)
        record_api_usage(
            db,
            project_id=ctx.project.id,
            api_key_id=ctx.key.id,
            user_id=ctx.user_id,
            endpoint="/api/v1/files/",
            method="POST",
            status_code=status_code,
            response_time_ms=elapsed_ms,
            bytes_uploaded=0,
        )
        raise


@app.get(
    "/api/v1/files/",
    response_model=DeveloperFileListResponse,
    summary="List files belonging to the authenticated project",
    tags=["Developer Platform - Files"],
)
async def list_project_files(
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: Session = Depends(get_db),
):
    """List all survey files associated with the active API key's project."""
    files = db.execute(
        select(FileRecord).where(FileRecord.project_id == ctx.project.id).order_by(FileRecord.created_at.desc())
    ).scalars().all()

    resp_files = [
        DeveloperFileSummaryResponse(
            id=f.id,
            filename=f.filename,
            file_type=f.file_type,
            feature_count=f.feature_count,
            crs=f.crs,
            status=f.status,
            created_at=f.created_at,
        )
        for f in files
    ]
    return DeveloperFileListResponse(files=resp_files, total=len(resp_files))


@app.get(
    "/api/v1/files/{id}/",
    response_model=FileDetailResponse,
    summary="Get file details (Tenant-Isolated)",
    tags=["Developer Platform - Files"],
)
async def get_developer_file_detail(
    id: str = APIPath(..., description="Unique file UUID"),
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: Session = Depends(get_db),
):
    """Retrieve file details. Enforces project-level tenant ownership."""
    if not id or not id.strip() or len(id) > 128:
        raise ResourceNotFoundException("Invalid or empty file ID.")

    clean_id = id.strip()
    file_record = db.execute(select(FileRecord).where(FileRecord.id == clean_id)).scalar_one_or_none()
    if not file_record or file_record.project_id != ctx.project.id:
        raise ResourceNotFoundException("File not found.")

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
    "/api/v1/files/{id}/measurements/",
    response_model=FileMeasurementListResponse,
    summary="Get measurements (Tenant-Isolated)",
    tags=["Developer Platform - Files"],
)
async def get_developer_file_measurements(
    id: str = APIPath(..., description="Unique file UUID"),
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: Session = Depends(get_db),
):
    """Retrieve geometric measurements. Enforces project-level tenant ownership."""
    if not id or not id.strip() or len(id) > 128:
        raise ResourceNotFoundException("Invalid or empty file ID.")

    clean_id = id.strip()
    file_record = db.execute(select(FileRecord).where(FileRecord.id == clean_id)).scalar_one_or_none()
    if not file_record or file_record.project_id != ctx.project.id:
        raise ResourceNotFoundException("File not found.")

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


@app.delete(
    "/api/v1/files/{id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Securely delete a file and associated data (Tenant-Isolated)",
    tags=["Developer Platform - Files"],
)
async def delete_developer_file(
    id: str = APIPath(..., description="Unique file UUID"),
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: Session = Depends(get_db),
):
    """Securely purge file record, features, measurements, and disk files. Enforces ownership."""
    clean_id = id.strip()
    file_record = db.execute(select(FileRecord).where(FileRecord.id == clean_id)).scalar_one_or_none()
    if not file_record or file_record.project_id != ctx.project.id:
        raise ResourceNotFoundException("File not found.")

    file_store_dir = (STORAGE_DIR / file_record.id).resolve()
    if file_store_dir.exists() and str(file_store_dir).startswith(str(STORAGE_DIR)):
        shutil.rmtree(file_store_dir, ignore_errors=True)

    db.delete(file_record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 6. Developer Console UI Routes ---

@app.get("/console", response_class=HTMLResponse, summary="Developer Console Web UI", tags=["Developer Console"])
@app.get("/portal", response_class=HTMLResponse, summary="Developer Portal Web UI", tags=["Developer Console"])
async def serve_developer_console():
    """Serve the self-service Developer Console."""
    portal_path = BASE_DIR / "portal.html"
    if portal_path.exists():
        return FileResponse(str(portal_path), media_type="text/html")
    return HTMLResponse("<h1>Developer Console</h1><p>portal.html not found</p>", status_code=200)


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
