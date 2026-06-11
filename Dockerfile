# VM-Tips 2026 - Dockerfile
# Multi-stage not needed, simple and small for Raspberry Pi (arm64)
FROM python:3.12-slim

WORKDIR /app

# Install system deps (for sqlite etc, though mostly included)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app/ ./app/

# Create data dir for volume mount (SQLite)
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/vmtips.db

EXPOSE 8000

# Use uvicorn directly
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
