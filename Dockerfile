# ==============================================================================
# GraphRAG-DLP Multi-Stage Production Dockerfile
# ==============================================================================
# Stage 1: Build Frontend Static Bundle
# Stage 2: Minimal Python Runtime with FastAPI backend and Static Asset Serving
# ==============================================================================

FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

COPY frontend/ ./
RUN npm run build

# ==============================================================================
# Stage 2: Production Python Runtime
# ==============================================================================
FROM python:3.13-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOST=0.0.0.0 \
    PORT=8000 \
    APP_ENV=demo \
    DLP_DB_PATH=/app/data/graph.sqlite3

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application source and scripts
COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Prepare persistent data directory
RUN mkdir -p /app/data && chmod 700 /app/data

EXPOSE 8000

CMD ["/bin/bash", "/app/scripts/start.sh"]
