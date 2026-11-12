# GraphRAG-DLP

**GraphRAG-DLP** is a privacy-preserving hybrid Knowledge Graph and Retrieval-Augmented Generation (RAG) platform. It provides Attribute-Based Access Control (ABAC), tenant isolation, cryptographic source provenance verification, and a restricted Cypher AST security rewriting engine to guarantee Data Loss Prevention (DLP) across all retrieved nodes, relationships, citations, and prompt contexts.

---

## Key Capabilities

* **Deterministic Local Zero-Key Default:** Fully functional out of the box with zero external API keys, cloud services, or network dependencies. Uses an embedded SQLite graph store and pure-Python TF-IDF cosine sparse vector index.
* **Strict Attribute-Based Access Control (ABAC):** Multi-tenant policy enforcement verifying tenant identity, clearance levels (1–4), and department memberships on every graph node, edge, and document chunk.
* **Restricted Cypher AST Engine:** Enforces safe Cypher subsets, injecting tenant and clearance predicates directly into query ASTs, enforcing hop bounds ($\le 3$), and preventing injection or data leakage.
* **Single-Origin Production Packaging:** Unified Docker container serving both the React/Vite Cytoscape.js frontend and FastAPI backend on the same origin (`http://127.0.0.1:8000`).
* **Bounded Neo4j Profile:** Optional Neo4j 5.26 Community profile strictly bounded to 512MiB heap and 128MiB pagecache (capped at 1GiB total container RAM) to safely run on standard 8GB development machines.
* **Truthful Provider Reporting:** Never fakes external connectivity. Missing API keys (Groq, FlashRank) are explicitly reported in `/api/v1/health`.

---

## Architecture Overview

```
                   +-----------------------------------------------+
                   |      Frontend SPA (React 19 + Cytoscape)       |
                   |      Single Origin: http://127.0.0.1:8000     |
                   +-----------------------+-----------------------+
                                           |
                                 REST & SSE (/api/v1)
                                           v
                   +-----------------------------------------------+
                   |          FastAPI Gateway & DLP Core           |
                   |  - JWT ABAC Middleware (Server-Side Policy)   |
                   |  - Restricted Cypher AST Rewriting Engine     |
                   |  - Anti-Oracle Redaction & Provenance Vault   |
                   +-----------+-----------------------+-----------+
                               |                       |
                 +-------------+-------------+         |
                 |                           |         |
                 v                           v         v
     +-----------------------+   +-------------------+ |
     | Deterministic Engine  |   | Real Sparse Index | |
     | SQLite Persistent DB  |   | TF-IDF / Cosine   | |
     | Local Extractive LLM  |   | Lexical RRF Rank  | |
     +-----------------------+   +-------------------+ |
                                                       |
                          Optional Production Adapters  |
                          ----------------------------+
                          | Neo4j 5.26 (Read-Only)    |
                          | Groq LLM (Llama 3.3)      |
                          +---------------------------+
```

---

## Quickstart

### Prerequisites

* Python >= 3.11
* Node.js >= 20 and npm
* [uv](https://github.com/astral-sh/uv) (recommended) or standard `pip`
* Docker and Docker Compose (for containerized deployments)

### 1. Installation

Clone the repository and install dependencies:

```bash
# Using Makefile
make install

# Or manually:
uv sync
cd frontend && npm install && cd ..
```

### 2. Local Development (Dual-Process with Hot Reload)

Run the backend on `127.0.0.1:8000` and the Vite development server on `127.0.0.1:5173`:

```bash
./scripts/dev.sh
# or
make dev
```

Open `http://127.0.0.1:5173` in your browser. The frontend dev server proxies all `/api` calls directly to `127.0.0.1:8000`.

### 3. Production Local Startup (Single Origin)

Build the frontend static bundle and serve both the web UI and API from a single origin on port 8000:

```bash
# Build frontend assets
npm --prefix frontend run build

# Start production server
./scripts/start.sh
# or
make start
```

Open `http://127.0.0.1:8000` to access the full application.

---

## Docker Deployment

The application is containerized using a multi-stage Dockerfile that compiles the frontend and packages it into a minimal, hardened Python runtime.

### Standard Zero-Key Deployment

To start the GraphRAG-DLP application in offline, zero-key deterministic mode:

```bash
docker compose up -d app
```

* **Application Portal:** `http://127.0.0.1:8000`
* **Health Check:** `http://127.0.0.1:8000/api/v1/health`
* **Local State:** Persistent SQLite database and signing keys are stored in the named Docker volume `graphrag_dlp_data`.
* **Security:** All host ports are strictly bound to `127.0.0.1` (loopback only).

### Optional Neo4j Profile

For environments integrating with an external graph database, a project-specific bounded Neo4j service is available via Docker Compose profiles:

```bash
# Start both application and bounded Neo4j container
docker compose --profile neo4j up -d
```

* **Neo4j Browser:** `http://127.0.0.1:7474`
* **Bolt Protocol:** `bolt://127.0.0.1:7687`
* **Credentials:** `neo4j` / `graphrag_password_local`

#### Neo4j Resource Bounding
To protect laptops and constrained environments (e.g. 8GB RAM systems), the Neo4j container is strictly bounded:
* `NEO4J_server_memory_heap_initial__size=512m`
* `NEO4J_server_memory_heap_max__size=512m`
* `NEO4J_server_memory_pagecache_size=128m`
* Container memory limit: `1024M` (max 1GiB total memory)

#### Neo4j Security Model & Production Requirements
* **`execute_read` is Routing Intent, Not Security:** Calling Neo4j's `execute_read` session transaction merely routes queries to read replicas in a cluster; it does **NOT** enforce database security or prevent arbitrary queries.
* **Read-Only Database Principal:** In production, configure a dedicated database user with strict read-only privileges and restrict all schema modification and APOC administrative procedures.
* **Community Edition Limitations:** Neo4j Community Edition does not support fine-grained role-based graph security or multi-database segregation. GraphRAG-DLP enforces tenant and ABAC security in the application layer via AST rewriting and node/edge allowlist predicates.

---

## Configuration Reference

Copy `.env.example` to `.env` to customize settings:

```bash
cp .env.example .env
```

| Environment Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `demo` | Environment mode (`demo` or `production`). In production, demo endpoints are disabled. |
| `HOST` | `127.0.0.1` | Host loopback bind address. |
| `PORT` | `8000` | Application port. |
| `DLP_DB_PATH` | `backend/data/graph.sqlite3` | Path to persistent SQLite evidence and graph store. |
| `JWT_SECRET` | *(auto-generated)* | 32+ character HMAC key. If unset, auto-generates a secure key stored with `0600` permissions at `${DLP_DB_PATH}.key`. |
| `JWT_ISSUER` | `graphrag-dlp-demo` | Expected JWT issuer claim. |
| `JWT_AUDIENCE` | `graphrag-dlp` | Expected JWT audience claim. |
| `JWT_JWKS_URL` | *(empty)* | HTTPS URL for production JWKS key set (required if `APP_ENV=production`). |
| `NEO4J_URI` | *(empty)* | Neo4j Bolt connection URI (e.g. `bolt://127.0.0.1:7687`). Unset by default for zero-key local operation. |
| `NEO4J_USER` | `neo4j` | Neo4j read user. |
| `NEO4J_PASSWORD` | `graphrag_password_local` | Neo4j read password. |
| `NEO4J_DATABASE` | `neo4j` | Neo4j database name. |
| `NEO4J_WRITE_USER` | *(empty)* | Separate Neo4j write principal for initial graph fixture provisioning and ingest. |
| `NEO4J_WRITE_PASSWORD` | *(empty)* | Separate Neo4j write password. |
| `DLP_LANGGRAPH` | `0` | Enable optional LangGraph StateGraph orchestration (`1` to enable, requires `--extra providers`). |
| `GROQ_API_KEY` | *(empty)* | Optional API key for Groq LLM answers. Unset by default. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Supported Groq model (`llama-3.3-70b-versatile` or `llama-3.1-8b-instant`). |
| `FLASHRANK_MODEL_DIR` | *(empty)* | Path to local directory containing pre-downloaded ONNX models. Provision using `python3 backend/scripts/provision_flashrank.py --cache-dir models/flashrank`. |

---

## Security Invariants

1. **Zero Client Trust:** All identity and ABAC context (clearance level, departments, tenant) are derived server-side from cryptographically verified JWT bearer tokens.
2. **Anti-Oracle Redaction:** Probing unauthorized documents returns the exact same HTTP 404 response as non-existent documents. Audit logs and error messages never leak classification levels or secret names.
3. **Restricted AST Query Grammar:** Raw Cypher queries are parsed into a strict abstract syntax tree (AST). Queries containing unauthorized operations (`UNION`, `CALL`, `WITH`, schema alterations, or unbound traversals) are rejected before execution.
4. **Traversal Protection:** Static file serving strictly validates canonical paths against the document root (`is_relative_to(dist_root)`) to prevent path traversal attacks. Unmatched `/api/*` routes strictly return JSON 404 responses.

---

## Verification & Testing

Run the comprehensive test suite across backend, frontend, and deployment layers:

```bash
# Run all unit tests
make test

# Run backend unit and adversarial security tests (63 tests)
pytest backend/tests/test_security.py -v

# Run optional adapter tests (Groq mock, FlashRank fallback, LangGraph)
pytest backend/tests/test_adapters.py -v

# Run gated Neo4j integration test against live bounded Neo4j container
make test-neo4j

# Run packaging and static file traversal security verification
python3 scripts/test_packaging.py

# Run frontend test suite (vitest)
npm --prefix frontend test -- --run
```

---

## Pre-Seeded Demo Identities

For local testing and demonstration (`APP_ENV=demo`), predefined signed identities are available via `/api/v1/auth/identities`:

| Identity ID | Role / Title | Clearance | Departments | Tenant |
|---|---|:---:|---|---|
| `contractor` | External Contractor | Level 1 | `engineering` | `acme` |
| `engineer` | Engineering Analyst | Level 2 | `engineering` | `acme` |
| `vp` | Executive VP | Level 4 | `engineering`, `procurement`, `mna` | `acme` |
| `admin` | Demo Administrator | Level 4 | `engineering`, `procurement`, `mna` | `acme` |
| `other_tenant` | Other Tenant Admin | Level 4 | `engineering`, `procurement`, `mna` | `other` |
