#!/usr/bin/env bash
# ==============================================================================
# GraphRAG-DLP Development Runner
# ==============================================================================
# Starts backend on 127.0.0.1:8000 and frontend on 127.0.0.1:5173 with proxy.
# Cleanly traps exit signals to shut down both processes.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_PORT="5173"

export APP_ENV="${APP_ENV:-demo}"
export HOST="${BACKEND_HOST}"
export PORT="${BACKEND_PORT}"
export DLP_DB_PATH="${DLP_DB_PATH:-${ROOT_DIR}/backend/data/graph.sqlite3}"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
export API_PROXY_TARGET="http://${BACKEND_HOST}:${BACKEND_PORT}"

echo "=================================================================="
echo " Starting GraphRAG-DLP Development Environment"
echo " Backend:   http://${BACKEND_HOST}:${BACKEND_PORT}"
echo " Frontend:  http://127.0.0.1:${FRONTEND_PORT}"
echo " DB Path:   ${DLP_DB_PATH}"
echo " Mode:      Deterministic Local (Zero API Keys Required)"
echo "=================================================================="

# Detect Python runner
PYTHON_BIN="python3"
if command -v uv >/dev/null 2>&1 && [[ -f "${ROOT_DIR}/pyproject.toml" && ! -d "${ROOT_DIR}/.venv" ]]; then
    echo "Syncing Python dependencies with uv..."
    ( cd "${ROOT_DIR}" && uv sync )
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -f "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi

# Ensure frontend dependencies are installed
if [[ -d "${ROOT_DIR}/frontend" && ! -d "${ROOT_DIR}/frontend/node_modules" ]]; then
    echo "Installing frontend dependencies..."
    ( cd "${ROOT_DIR}/frontend" && npm install )
fi

# Ensure database directory exists
mkdir -p "$(dirname "${DLP_DB_PATH}")"

# Track child PIDs for clean exit
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo "Shutting down development servers..."
    if [[ -n "${BACKEND_PID}" ]]; then
        kill "${BACKEND_PID}" 2>/dev/null || true
    fi
    if [[ -n "${FRONTEND_PID}" ]]; then
        kill "${FRONTEND_PID}" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    echo "Servers stopped cleanly."
}
trap cleanup SIGINT SIGTERM EXIT

# Start backend
echo "Starting FastAPI backend with uvicorn on ${BACKEND_HOST}:${BACKEND_PORT}..."
(
    cd "${ROOT_DIR}"
    exec "${PYTHON_BIN}" -m uvicorn backend.app.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload
) &
BACKEND_PID=$!

# Start frontend
if [[ -d "${ROOT_DIR}/frontend" ]]; then
    echo "Starting Vite frontend dev server on http://127.0.0.1:${FRONTEND_PORT}..."
    (
        cd "${ROOT_DIR}/frontend"
        exec npm run dev
    ) &
    FRONTEND_PID=$!
fi

echo "Development environment active. Press Ctrl+C to stop."
wait
