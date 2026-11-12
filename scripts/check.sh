#!/usr/bin/env bash
# scripts/check.sh - Fast, serial, bounded quality checks for GraphRAG-DLP
# Designed for 8GB development environments with clear prerequisites and no false greens.

set -euo pipefail

MODE="fast"
RUN_BACKEND=true
RUN_FRONTEND=true

# Parse arguments
for arg in "$@"; do
  case "$arg" in
    --full)
      MODE="full"
      ;;
    --backend-only)
      RUN_FRONTEND=false
      ;;
    --frontend-only)
      RUN_BACKEND=false
      ;;
    -h|--help)
      cat << 'USAGE'
Usage: ./scripts/check.sh [OPTIONS]

Options:
  --full           Run comprehensive checks (locked sync, full build, tests)
  --backend-only   Run only backend checks
  --frontend-only  Run only frontend checks
  -h, --help       Show this help message

Default: Fast targeted checks (bounded, serial execution).
Prerequisites: uv (for backend), node + npm (for frontend).
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"

echo "=== GraphRAG-DLP Quality Checks (mode: $MODE) ==="
START_TIME=$(date +%s)

CHECK_COUNT=0

# --- Backend Checks ---
if [ "$RUN_BACKEND" = true ]; then
  echo ""
  echo "--- Backend Checks ---"
  if [ ! -f "pyproject.toml" ]; then
    echo "[backend] ERROR: pyproject.toml not found in repository root." >&2
    echo "          Action required: Backend code must provide pyproject.toml." >&2
    exit 1
  fi

  if ! command -v uv >/dev/null 2>&1; then
    echo "[backend] ERROR: 'uv' is not installed or not in PATH." >&2
    echo "          Action required: Install uv (curl -LsSf https://astral.sh/uv/install.sh or brew install uv)." >&2
    exit 1
  fi

  if [ "$MODE" = "full" ]; then
    if [ ! -f "uv.lock" ]; then
      echo "[backend] ERROR: uv.lock not found in repository root." >&2
      echo "          Action required: Run 'uv lock' to generate reproducible lockfile." >&2
      exit 1
    fi
    echo "[backend] Synchronizing dependencies with test extra (uv sync --locked --extra test)..."
    uv sync --locked --extra test
  fi

  echo "[backend] Checking Python syntax across backend..."
  if [ -d "backend" ]; then
    python3 -m compileall -q backend/
    CHECK_COUNT=$((CHECK_COUNT + 1))
    echo "[backend] Python syntax check: PASS"
  else
    echo "[backend] ERROR: backend/ directory not found." >&2
    exit 1
  fi

  echo "[backend] Running pytest (serial, bounded)..."
  uv run pytest -v -o "addopts=" --override-ini="addopts="
  CHECK_COUNT=$((CHECK_COUNT + 1))
  echo "[backend] Pytest: PASS"
fi

# --- Frontend Checks ---
if [ "$RUN_FRONTEND" = true ]; then
  echo ""
  echo "--- Frontend Checks ---"
  if [ ! -d "frontend" ] || [ ! -f "frontend/package.json" ]; then
    echo "[frontend] ERROR: frontend/package.json not found." >&2
    echo "           Action required: Frontend code must provide frontend/package.json." >&2
    exit 1
  fi

  if [ ! -f "frontend/package-lock.json" ]; then
    echo "[frontend] ERROR: frontend/package-lock.json not found." >&2
    echo "           Action required: frontend must provide reproducible package-lock.json." >&2
    exit 1
  fi

  if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
    echo "[frontend] ERROR: Node.js or npm is not installed or not in PATH." >&2
    echo "           Action required: Install Node.js LTS (brew install node)." >&2
    exit 1
  fi

  if [ ! -d "frontend/node_modules" ] || [ "$MODE" = "full" ]; then
    echo "[frontend] Installing reproducible dependencies via 'npm ci'..."
    (cd frontend && npm ci)
  fi

  # Typecheck / Build
  echo "[frontend] Running TypeScript compiler check / build..."
  (cd frontend && npm run build)
  CHECK_COUNT=$((CHECK_COUNT + 1))
  echo "[frontend] Frontend build: PASS"

  # Frontend tests
  echo "[frontend] Running frontend tests (npm test)..."
  (cd frontend && npm test)
  CHECK_COUNT=$((CHECK_COUNT + 1))
  echo "[frontend] Frontend tests: PASS"
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "=== Check Summary ==="
echo "Executed in: ${DURATION}s"
echo "Checks passed: ${CHECK_COUNT}"
echo "All executed quality checks passed cleanly."
