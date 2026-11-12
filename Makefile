# ==============================================================================
# GraphRAG-DLP Automation Makefile
# ==============================================================================
.PHONY: help install dev start build test test-backend test-frontend test-neo4j docker-build docker-up docker-down neo4j-up neo4j-down clean

SHELL := /bin/bash
PYTHON ?= python3

help:
	@echo "GraphRAG-DLP Development & Deployment Commands:"
	@echo "  make install         Install backend (uv sync) and frontend dependencies"
	@echo "  make dev             Run local development servers (Backend 8000 + Frontend 5173)"
	@echo "  make start           Run production single-origin server on port 8000"
	@echo "  make build           Build production frontend static assets"
	@echo "  make test            Run full backend and frontend unit test suites"
	@echo "  make test-backend    Run pytest backend test suite"
	@echo "  make test-frontend   Run vitest frontend test suite"
	@echo "  make test-neo4j      Run gated Neo4j parity and ABAC integration tests"
	@echo "  make neo4j-up        Start bounded project-specific Neo4j container"
	@echo "  make neo4j-down      Stop project-specific Neo4j container"
	@echo "  make docker-build    Build production multi-stage Docker image"
	@echo "  make docker-up       Run application in Docker (single-origin port 8000)"
	@echo "  make docker-down     Stop Docker containers"
	@echo "  make clean           Clean caches, build directories, and test artifacts"

install:
	@if command -v uv >/dev/null 2>&1; then \
		echo "Installing Python dependencies with uv (locked)..."; \
		uv sync --locked --extra test; \
	else \
		echo "Installing Python dependencies with pip..."; \
		$(PYTHON) -m pip install -e .; \
	fi
	@if [ -d "frontend" ]; then \
		echo "Installing frontend dependencies with npm (ci)..."; \
		(cd frontend && npm ci); \
	fi

dev:
	./scripts/dev.sh

start:
	./scripts/start.sh

build:
	@if [ -d "frontend" ]; then \
		echo "Building frontend production assets..."; \
		(cd frontend && npm run build); \
	else \
		echo "Error: frontend directory not found."; exit 1; \
	fi

test: test-backend test-frontend

test-backend:
	@echo "Running backend test suite..."
	pytest backend/tests -v

test-frontend:
	@if [ -d "frontend" ]; then \
		echo "Running frontend test suite..."; \
		(cd frontend && npm test -- --run); \
	fi

test-neo4j:
	@echo "Running gated Neo4j ABAC integration tests..."
	NEO4J_TEST_URI="bolt://127.0.0.1:7687" \
	NEO4J_TEST_USER="neo4j" \
	NEO4J_TEST_PASSWORD="graphrag_password_local" \
	pytest backend/tests/test_adapters.py -k test_actual_neo4j_abac_parity_and_provenance -v

neo4j-up:
	docker compose --profile neo4j up -d neo4j

neo4j-down:
	docker compose --profile neo4j down

docker-build:
	docker compose build

docker-up:
	docker compose up -d app

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache frontend/dist frontend/node_modules/.vite htmlcov .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
