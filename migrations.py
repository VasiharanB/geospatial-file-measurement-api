"""Database schema migration runner for Geospatial File Measurement API.

Provides idempotent, safe migrations supporting both PostgreSQL (production)
and SQLite (local development and automated testing).
"""

from __future__ import annotations

import logging
from typing import List, Set
from sqlalchemy import inspect, text, Engine

logger = logging.getLogger("geospatial_api.migrations")


def get_existing_tables(engine: Engine) -> Set[str]:
    """Retrieve existing table names in the connected database."""
    inspector = inspect(engine)
    return set(inspector.get_table_names())


def get_existing_columns(engine: Engine, table_name: str) -> Set[str]:
    """Retrieve column names for a specific table."""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def run_migrations(engine: Engine) -> None:
    """Execute idempotent schema migrations across SQLite or PostgreSQL.
    
    Ensures that existing data in 'files', 'features', and 'measurements' is preserved,
    while adding developer platform tables, tenant ownership columns, and indexes.
    """
    dialect_name = engine.dialect.name
    logger.info(f"Running database migrations for dialect: {dialect_name}")

    with engine.begin() as conn:
        # 1. Ensure migrations tracking table exists
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(50) PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                );
                """
            )
        )

        # Check applied migrations
        applied_rows = conn.execute(text("SELECT version FROM schema_migrations;")).fetchall()
        applied_versions = {row[0] for row in applied_rows}

        # Migration 001: Baseline check
        if "001_initial_geospatial" not in applied_versions:
            logger.info("Recording baseline migration 001_initial_geospatial")
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, description) "
                    "VALUES ('001_initial_geospatial', 'Initial geospatial files and measurements schema');"
                )
            )

        # Migration 002: Add tenant ownership columns to 'files' table if missing
        if "002_add_file_tenant_columns" not in applied_versions:
            logger.info("Applying migration 002_add_file_tenant_columns")
            # We check columns dynamically
            existing_tables = get_existing_tables(engine)
            if "files" in existing_tables:
                existing_cols = get_existing_columns(engine, "files")
                if "user_id" not in existing_cols:
                    logger.info("Adding column 'user_id' to table 'files'")
                    conn.execute(text("ALTER TABLE files ADD COLUMN user_id VARCHAR(36);"))
                if "project_id" not in existing_cols:
                    logger.info("Adding column 'project_id' to table 'files'")
                    conn.execute(text("ALTER TABLE files ADD COLUMN project_id VARCHAR(36);"))

            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, description) "
                    "VALUES ('002_add_file_tenant_columns', 'Add user_id and project_id columns to files table');"
                )
            )

        # Migration 003: Developer Platform Tables
        if "003_developer_platform_tables" not in applied_versions:
            logger.info("Applying migration 003_developer_platform_tables")
            
            # 1. users table
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id VARCHAR(36) PRIMARY KEY,
                        email VARCHAR(255) NOT NULL UNIQUE,
                        password_hash VARCHAR(255) NOT NULL,
                        full_name VARCHAR(255),
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            )

            # 2. sessions table
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        id VARCHAR(36) PRIMARY KEY,
                        user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        token_hash VARCHAR(64) NOT NULL UNIQUE,
                        expires_at TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(255)
                    );
                    """
                )
            )

            # 3. projects table
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        id VARCHAR(36) PRIMARY KEY,
                        owner_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        name VARCHAR(100) NOT NULL,
                        description TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        tier VARCHAR(50) DEFAULT 'free',
                        daily_request_limit INTEGER DEFAULT 1000,
                        monthly_request_limit INTEGER DEFAULT 10000,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            )

            # 4. api_keys table
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id VARCHAR(36) PRIMARY KEY,
                        project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        name VARCHAR(100) NOT NULL,
                        key_prefix VARCHAR(20) NOT NULL,
                        last_four VARCHAR(10) NOT NULL,
                        key_hash VARCHAR(64) NOT NULL UNIQUE,
                        scopes TEXT DEFAULT '["read", "write"]',
                        is_revoked BOOLEAN DEFAULT 0,
                        revoked_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_used_at TIMESTAMP,
                        expires_at TIMESTAMP
                    );
                    """
                )
            )

            # 5. usage_records table
            id_col_type = "SERIAL PRIMARY KEY" if dialect_name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS usage_records (
                        id {id_col_type},
                        project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL,
                        api_key_id VARCHAR(36) REFERENCES api_keys(id) ON DELETE SET NULL,
                        user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                        endpoint VARCHAR(255) NOT NULL,
                        method VARCHAR(10) NOT NULL,
                        status_code INTEGER NOT NULL,
                        response_time_ms FLOAT,
                        bytes_uploaded INTEGER DEFAULT 0,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            )

            # Create performance and integrity indexes safely
            indexes_to_create = [
                ("ix_users_email", "users", "email"),
                ("ix_sessions_token_hash", "sessions", "token_hash"),
                ("ix_sessions_user_id", "sessions", "user_id"),
                ("ix_projects_owner_id", "projects", "owner_id"),
                ("ix_api_keys_key_hash", "api_keys", "key_hash"),
                ("ix_api_keys_project_id", "api_keys", "project_id"),
                ("ix_usage_records_project_id", "usage_records", "project_id"),
                ("ix_usage_records_timestamp", "usage_records", "timestamp"),
            ]
            for idx_name, tbl, col in indexes_to_create:
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {tbl} ({col});"))
                except Exception as e:
                    logger.debug(f"Index {idx_name} creation note: {e}")

            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, description) "
                    "VALUES ('003_developer_platform_tables', 'Create users, sessions, projects, api_keys, and usage_records tables');"
                )
            )

    logger.info("All schema migrations completed successfully.")
