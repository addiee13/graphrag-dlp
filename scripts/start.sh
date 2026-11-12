#!/usr/bin/env bash
# ==============================================================================
# GraphRAG-DLP Production Startup Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8000}"
export DLP_DB_PATH="${DLP_DB_PATH:-${ROOT_DIR}/backend/data/graph.sqlite3}"
export APP_ENV="${APP_ENV:-demo}"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

echo "=================================================================="
echo " Starting GraphRAG-DLP (Production / Single Origin Mode)"
echo " Environment: ${APP_ENV}"
echo " Host:        ${HOST}"
echo " Port:        ${PORT}"
echo " SQLite DB:   ${DLP_DB_PATH}"
echo "=================================================================="

# Ensure database directory exists with restricted permissions
DB_DIR="$(dirname "${DLP_DB_PATH}")"
mkdir -p "${DB_DIR}"
chmod 700 "${DB_DIR}" 2>/dev/null || true

# Session signing key note
KEY_PATH="${DLP_DB_PATH}.key"
if [[ -z "${JWT_SECRET:-}" ]]; then
    if [[ -f "${KEY_PATH}" ]]; then
        echo "Using existing persisted session signing key at: ${KEY_PATH}"
    else
        echo "JWT_SECRET unset: a secure random 32-character key will be safely generated"
        echo "and persisted with 0600 permissions at: ${KEY_PATH}"
    fi
else
    echo "Using configured JWT_SECRET from environment."
fi

# Verify production frontend bundle
DIST_DIR="${ROOT_DIR}/frontend/dist"
API_ONLY="${API_ONLY:-0}"

if [[ -d "${DIST_DIR}" && -f "${DIST_DIR}/index.html" ]]; then
    echo "Found built frontend static bundle at: ${DIST_DIR}"
    echo "Single-origin serving active: Web Portal & API at http://${HOST}:${PORT}"
elif [[ "${API_ONLY}" == "1" || "${API_ONLY}" == "true" ]]; then
    echo "API_ONLY=1 set: Starting in API-only mode without frontend static bundle."
else
    echo "ERROR: Frontend production bundle not found at: ${DIST_DIR}" >&2
    echo "To build frontend assets, run: npm --prefix frontend run build" >&2
    echo "To start in API-only mode without frontend UI, set API_ONLY=1" >&2
    exit 1
fi

# Detect portable Python binary
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -f "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v uv >/dev/null 2>&1 && [[ -f "${ROOT_DIR}/pyproject.toml" ]]; then
    exec uv run --no-sync python3 -m uvicorn scripts.prod_server:get_prod_app --factory --host "${HOST}" --port "${PORT}"
fi

exec "${PYTHON_BIN}" -m uvicorn scripts.prod_server:get_prod_app --factory --host "${HOST}" --port "${PORT}"
