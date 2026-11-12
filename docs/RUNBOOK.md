# GraphRAG-DLP Operations Runbook & Deployment Guide

## 1. System Overview & Operational Architecture

**GraphRAG-DLP** is a secure, multi-tenant hybrid Knowledge Graph and Retrieval-Augmented Generation (RAG) platform. It provides fine-grained Attribute-Based Access Control (ABAC), tenant isolation, Cypher AST query restriction, cryptographic provenance verification, and deterministic extractive synthesis.

This runbook covers local development, quality verification, configuration parameters, optional external adapters, operational troubleshooting, and production deployment boundaries.

---

## 2. Quickstart & Local Development

### 2.1 Prerequisites
- **Python**: Version 3.11+ (Python 3.13 recommended)
- **Node.js**: Version 20+ LTS
- **Package Managers**: `uv` (for Python dependency management) and `npm` (for frontend)

### 2.2 Development Environment Execution

The project provides an automated development script (`scripts/dev.sh`) that starts both the FastAPI backend (`http://127.0.0.1:8000`) and the Vite frontend (`http://127.0.0.1:5173`) with automatic proxying and clean signal trapping:

```sh
./scripts/dev.sh
```

Alternatively, start services individually:

1. **Backend**:
   ```sh
   uv sync --locked --extra test
   uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
   ```
2. **Frontend**:
   ```sh
   (cd frontend && npm ci)
   (cd frontend && npm run dev)
   ```

3. **Verify Health Endpoint**:
   ```sh
   curl -s http://127.0.0.1:8000/api/v1/health | jq .
   ```
   *Expected response:*
   ```json
   {
     "status": "healthy",
     "mode": "deterministic_local",
     "neo4j": "disabled",
     "groq": "disabled",
     "flashrank": "fallback_lexical",
     "langgraph": "disabled"
   }
   ```

### 2.3 Single-Origin Production Serving

For unified production hosting where FastAPI serves both API endpoints and the precompiled React single-page application from a single port:

```sh
# 1. Build frontend distribution assets
(cd frontend && npm run build)

# 2. Launch production server
./scripts/start.sh
```
The application will be accessible at `http://127.0.0.1:8000`.

---

## 3. Automated Quality Verification & Checks

GraphRAG-DLP includes a single, serial, bounded quality validation script (`./scripts/check.sh`) designed to run safely in resource-constrained (8GB RAM) development environments.

### 3.1 Running the Quality Gate

```sh
# Fast default mode (syntax compilation, pytest, TypeScript build, vitest)
./scripts/check.sh

# Full mode (enforces locked package sync and full test builds)
./scripts/check.sh --full

# Targeted checks
./scripts/check.sh --backend-only
./scripts/check.sh --frontend-only
```

### 3.2 Individual Test Executions

- **Backend Pytest Suite (Default Local Mode)**:
  ```sh
  uv run pytest backend/tests/ -v
  ```
  *Baseline result*: 74 passed, 4 skipped in ~2.0s.

- **Full Optional Provider Test Suite**:
  ```sh
  FLASHRANK_TEST_MODEL_DIR=/path/to/models \
  NEO4J_TEST_URI=bolt://127.0.0.1:7687 \
  NEO4J_TEST_PASSWORD='<password>' \
  uv run --extra test --extra providers pytest backend/tests/ -q
  ```
  *Result*: 78 passed in ~3.0s.

- **Frontend Vitest Suite**:
  ```sh
  (cd frontend && npm test -- --run)
  ```
  *Baseline result*: 2 test suites, 11 tests passed in ~3.0s.

---

## 4. Configuration & Environment Variables

All settings can be supplied via environment variables or a `.env` file at the repository root.

| Variable | Default Value | Description |
|---|---|---|
| `APP_ENV` | `demo` | Deployment environment (`demo`, `development`, or `production`). In `production`, demo token and identity endpoints are strictly disabled. Strict unknown values fail fast on startup. |
| `DLP_DB_PATH` | `backend/data/graph.sqlite3` | Filesystem path for the persistent SQLite database. Created with mode 0600. |
| `JWT_SECRET` | *(auto-generated)* | Development HMAC signing key. In local mode, persisted atomically to `backend/data/graph.sqlite3.key` with permissions `0600`. |
| `JWT_JWKS_URL` | `None` | Production HTTPS endpoint for IdP JSON Web Key Sets (JWKS). Required when `APP_ENV=production`. |
| `JWT_ALGORITHM` | `RS256` | JWT algorithm (`HS256` for local dev, `RS256` or `ES256` for production JWKS). |
| `JWT_ISSUER` | `graphrag-dlp-demo` | Validated JWT `iss` claim. |
| `JWT_AUDIENCE` | `graphrag-dlp` | Validated JWT `aud` claim. |
| `NEO4J_URI` | `None` | Bolt URI for external Neo4j database (e.g. `bolt://127.0.0.1:7687`). |
| `NEO4J_USER` | `None` | Read-only database principal used for query execution. |
| `NEO4J_PASSWORD` | `None` | Password for the read-only Neo4j principal. |
| `NEO4J_WRITE_USER` | `None` | Separate database user with write permissions for ingestion indexing and provisioning. |
| `NEO4J_WRITE_PASSWORD` | `None` | Password for the provisioning/ingestion writer. |
| `GROQ_API_KEY` | `None` | API key for Groq inference provider. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Supported Groq model (`llama-3.3-70b-versatile` or `llama-3.1-8b-instant`). |
| `DLP_LANGGRAPH` | `0` | Set to `1` to activate LangGraph StateGraph retrieval stage (requires `providers` extra). |
| `FLASHRANK_MODEL_DIR` | `None` | Directory path containing pre-provisioned, frozen TinyBERT ONNX model files. |

---

## 5. Storage, Filesystem Permissions & Keys

GraphRAG-DLP separates authentication signing keys from evidence provenance keys:

1. **Authentication Key (`backend/data/*.key`)**:
   - Used for signing local demo tokens in development.
   - Initialized via atomic file creation (`mkstemp` + `os.link`) with mode `0600`.
2. **Provenance HMAC Key (`backend/data/*.provenance-key`)**:
   - Protects classification levels, departments, and tenant policy labels against SQLite offline tampering.
   - Initialized with mode `0600`.
   - **Key Rotation**: Rotating the JWT authentication signing key does not invalidate stored provenance signatures.
3. **Database Files (`backend/data/graph.sqlite3`)**:
   - Persistent SQLite file containing documents, graph entities, edges, chunks, and audit hashes.
   - Directory permissions should be restricted to the operating system user running the backend process (`chmod 700 backend/data`).

---

## 6. Optional External Providers

### 6.1 Neo4j Bolt Database Configuration

GraphRAG-DLP supports Neo4j as an optional structured graph store, using SQLite as the authoritative provenance and policy ledger:

1. **Dedicated Database Principals**:
   - **Query Execution**: Connect via `NEO4J_USER` configured with read-only access. In application execution, `execute_read` specifies transaction routing intent.
   - **Ingestion & Provisioning**: Set `NEO4J_WRITE_USER` and `NEO4J_WRITE_PASSWORD`. Authenticated document ingestion automatically indexes extracted facts. If writer credentials are not configured, ingestion records persist in SQLite with `graph_indexing: "pending"`.
2. **Community vs. Enterprise RBAC Boundary**:
   - Neo4j Community Edition does not support per-user granular RBAC or procedure whitelisting. In Community deployments, isolation relies on application-level AST transformation combined with driver-level read routing.
   - Neo4j Enterprise Edition is recommended for production environments requiring native database-level principal restrictions.
3. **Running Acceptance Parity Tests**:
   ```sh
   NEO4J_TEST_URI=bolt://127.0.0.1:7687 \
   NEO4J_TEST_PASSWORD='<dedicated-local-test-password>' \
   uv run pytest backend/tests/ -k neo4j
   ```

### 6.2 Groq LLM Provider Integration

1. When configured with `GROQ_API_KEY`, the `/api/v1/chat` endpoint streams real SSE responses generated by Groq.
2. **Context Restriction**: The Groq adapter receives only pre-filtered, authorized evidence chunks.
3. **Supported Models**: `llama-3.3-70b-versatile` or `llama-3.1-8b-instant`.
4. **Mock Testing**: When credentials are not provisioned, automated tests verify the HTTP streaming transport and error handling using an explicit HTTP mock (`test_groq_http_mock_context_only_authorized`).

### 6.3 FlashRank ONNX Reranker Provisioning

To prevent unexpected network egress or non-deterministic downloads in air-gapped environments, FlashRank requires explicit, pre-provisioned offline models:

1. Provision the frozen TinyBERT model:
   ```sh
   uv run --extra providers python backend/scripts/provision_flashrank.py --cache-dir backend/data/models
   ```
2. Enable the model directory:
   ```sh
   export FLASHRANK_MODEL_DIR="backend/data/models"
   ```
3. If `FLASHRANK_MODEL_DIR` is not set or the directory is missing, the system gracefully and truthfully falls back to pure lexical/RRF ranking (`fallback_lexical`) without raising exceptions or downloading files at runtime.

---

## 7. Operational Troubleshooting & Common Defect States

### 7.1 Cypher Query Rejected (HTTP 400)
- **Symptom**: `{"detail": "Unsupported restricted Cypher grammar"}` or `{"detail": "Invalid query or reserved parameter namespace"}`
- **Cause**: Query attempted an unsupported operation (mutations, `CALL`, `OPTIONAL MATCH`, `UNION`, `WITH`, aggregations, `ORDER BY`, comments `//`, or parameter shadowing).
- **Remedy**: Constrain queries to single fixed `MATCH` patterns with $\le 3$ hops, standard property comparisons, and explicit `RETURN` variable lists.

### 7.2 Extra Fields in Token Request (HTTP 422)
- **Symptom**: `{"detail": [{"loc": ["body", "clearance_level"], "msg": "Extra inputs are not permitted"}]}`
- **Cause**: Client attempted to pass arbitrary security claims in the `POST /api/v1/auth/token` payload.
- **Remedy**: Request must contain exactly `{"identity_id": "<identity_name>"}`.

### 7.3 Source Document Returns HTTP 404
- **Symptom**: `{"detail": "Not found"}`
- **Cause**: Either the document does not exist, or the authenticated caller's clearance level is lower than the document's classification level.
- **Remedy**: This is expected anti-oracle behavior to prevent clearance enumeration. Verify caller credentials if legitimate access is expected.

### 7.4 Ingestion Returns `graph_indexing: "pending"`
- **Symptom**: Ingestion succeeds with HTTP 201, but response states `graph_indexing: "pending"`.
- **Cause**: Neo4j is configured for reads (`NEO4J_URI`), but separate writer credentials (`NEO4J_WRITE_USER`) are missing, or Neo4j was temporarily unreachable during indexing.
- **Remedy**: Facts are safely persisted in the authoritative SQLite store and searchable immediately. Configure writer credentials to allow automatic indexing retry on next startup.

---

## 8. Realistic Production Deployment Boundaries

1. **Storage & Operating System Boundary**:
   - SQLite database files and cryptographic key files rely on host operating system file access controls. Running processes must have least-privilege filesystem rights.
2. **External Identity Provider (IdP) Requirement**:
   - The built-in `/auth/token` and `/auth/identities` endpoints are designed exclusively for demo and test evaluation. Production deployments must configure `APP_ENV=production` and authenticate via an external IdP exposing an HTTPS JWKS endpoint.
3. **No Unqualified Compliance Assertions**:
   - GraphRAG-DLP provides technical DLP controls for multi-tenant graph RAG. It does not provide certified HIPAA, SOC 2, or GDPR compliance out of the box without an audited operational deployment infrastructure.
