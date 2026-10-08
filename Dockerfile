# Production Dockerfile for Geospatial File Measurement API
FROM python:3.11-slim

# Environment flags for optimal container execution
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    GEOSPATIAL_STORAGE_DIR=/app/storage/uploads \
    GEOSPATIAL_DB_PATH=/app/geospatial.db

WORKDIR /app

# Install minimal OS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Ensure persistent storage directories exist
RUN mkdir -p /app/storage/uploads

# Copy single-file FastAPI implementation
COPY main.py .

# Expose default HTTP port
EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/health/ || exit 1

# Production command (reload disabled)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
