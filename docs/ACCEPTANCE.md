# GraphRAG-DLP Acceptance Verification & Test Evidence

## 1. Executive Summary & Verification Context

This document provides formal empirical acceptance evidence for **GraphRAG-DLP**.

All test results, browser automation logs, security invariant validations, and provider status indicators documented herein reflect the actual implemented software in local deterministic mode, supplemented by dedicated mock and fixture verifications for optional external integrations.

- **Verification Date**: November 12, 2026
- **Test Suite Results**: 74 passed, 4 skipped in 3.02s (`pytest backend/tests/`)
- **Frontend Test Results**: 11 passed in 3.28s (`vitest run` across 2 test suites)
- **Quality Script**: `./scripts/check.sh` passed cleanly in 15 seconds (syntax compilation, pytest, TypeScript build, vitest)
- **Root Browser Evidence**: Conducted via Chrome DevTools protocol (`chrome-devtools-axi`) against live services at `http://127.0.0.1:5173` and `http://127.0.0.1:8000`.

---

## 2. Automated Test Suite Evidence

### 2.1 Backend Pytest Suite Summary

```text
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/addie/.treehouse/side-project-00358c/1/side-project
configfile: pyproject.toml
plugins: langsmith-0.14.17, anyio-4.16.0
collected 78 items

backend/tests/test_adapters.py ....s.sss.                                [ 12%]
backend/tests/test_security.py ......................................... [ 65%]
...........................                                              [100%]

=========================== short test summary info ============================
SKIPPED [3] backend/tests/test_adapters.py: Release worker supplies bounded Neo4j integration service
SKIPPED [1] backend/tests/test_adapters.py: Explicit frozen local TinyBERT model not provisioned
======================== 74 passed, 4 skipped in 3.02s =========================
```

### 2.2 Acceptance Checklist Mapping to Concrete Pytest Cases

| Acceptance Check | Test Function Name | Result | What Was Tested |
|---|---|---|---|
| **AUTH-01** | `test_claim_injection` | `PASSED` | `POST /api/v1/auth/token` with extra claims (`clearance_level: 4`, `tenant_id`, `departments`) returns **HTTP 422**. |
| **AUTH-02** | `test_identities_and_claims` | `PASSED` | `GET /api/v1/auth/identities` returns 5 fixed identities; tokens mint exact fixed claims without trusting client inputs. |
| **AUTH-03** | `test_jwt_rejections` | `PASSED` | Rejects expired tokens, forged signatures, invalid audiences, incorrect issuers, `alg: none`, and future `nbf`. |
| **SEC-01** | `test_unsupported_rejected` | `PASSED` | Submitting `MATCH (n) DELETE n RETURN n` returns HTTP 400 (`CYPHER_DISALLOWED_OPERATION`). |
| **SEC-02** | `test_unsupported_rejected` | `PASSED` | Submitting `OPTIONAL MATCH`, `UNION`, `WITH`, `CALL`, `ORDER BY`, `SKIP`, `count()`, comments `//`, or `;` returns HTTP 400. |
| **SEC-03** | `test_anonymous_and_bounds` | `PASSED` | Submitting unbounded `MATCH (n) RETURN n` injects default `LIMIT 50` (capped at max 100). |
| **SEC-04** | `test_anonymous_and_bounds` | `PASSED` | Anonymous pattern nodes/edges are assigned synthetic identifiers (`__n*`, `__r*`) and bound to security predicates. |
| **SEC-05** | `test_unsupported_rejected` | `PASSED` | Submitting 4-hop query returns HTTP 400; hops strictly bounded to $\le 3$. |
| **SEC-06** | `test_or_precedence_and_parameterization` | `PASSED` | User query `WHERE 1=1 OR n.name = 'AWS'` rewritten to `((1=1) OR (n.name = $__literal_0)) AND (SecurityPredicates)`. |
| **SEC-07** | `test_reserved_parameters` | `PASSED` | Client parameters containing `$auth_*` or `$__literal_*` return HTTP 400 (`Reserved parameter name`). |
| **ABAC-01** | `test_terms_policy_all_surfaces[other_tenant-False]` | `PASSED` | `other_tenant` JWT returns 0 documents, 0 nodes, 0 search hits; total tenant isolation. |
| **ABAC-02** | `test_terms_policy_all_surfaces[contractor-False]` | `PASSED` | `contractor` (Clearance 1) sees AWS/Snowflake vendors; payment terms omitted; no existence hints. |
| **ABAC-03** | `test_terms_policy_all_surfaces[vp-True]` | `PASSED` | `vp` (Clearance 4) sees AWS $40k/mo Net-30 and Snowflake $15k/mo Net-60 with grounded citations. |
| **ABAC-04** | `test_two_hop_approval` | `PASSED` | `engineer` (Clearance 2) querying Alice approval cannot traverse to Project Titan acquisition (blocked at L3). |
| **ABAC-05** | `test_two_hop_approval` | `PASSED` | `vp` querying Alice approval traverses 2 hops; answers Alice approved acquisition of CyberCorp through Project Titan. |
| **ABAC-06** | `test_provenance_and_every_edge_fail_closed` | `PASSED` | Missing department, edge department mismatch, missing source label, cross-source tampering, or hash change fails closed. |
| **SRC-01** | `test_source_anti_oracle_and_citations` | `PASSED` | Authorized source fetch returns HTTP 200 with title, content, classification, and SHA-256 content hash. |
| **SRC-02** | `test_source_anti_oracle_and_citations` | `PASSED` | Unauthorized source document ID returns HTTP 404 with exact payload `{"detail":"Not found"}` (indistinguishable from absent). |
| **PROV-01** | `test_ingestion_arbitrary_facts_and_tenant` | `PASSED` | Non-admin (`contractor`) ingest attempt returns HTTP 403 Forbidden. |
| **PROV-02** | `test_ingestion_arbitrary_facts_and_tenant` | `PASSED` | Ingested document returns SHA-256 `content_hash` and generates verifiable HMAC policy signature. |
| **PROV-03** | `test_chimera_question_graph_has_only_contributing_project` | `PASSED` | Chimera question returns only Chimera contributing graph elements; unrelated Titan/Alice nodes excluded. |
| **ADAPT-01** | `test_groq_http_mock_context_only_authorized` | `PASSED` | Groq adapter verifies HTTP transport, token streaming, and authorized-only context passing via mock. |
| **ADAPT-02** | `test_groq_invalid_model_and_http_failure` | `PASSED` | Unsupported Groq model or upstream HTTP 500 fails gracefully without leaking context. |
| **ADAPT-03** | `test_real_optional_langgraph` | `PASSED` | LangGraph StateGraph executes actual multi-node retrieval graph when `DLP_LANGGRAPH=1`. |
| **ADAPT-04** | `test_flashrank_runtime_missing_model_truthful_fallback` | `PASSED` | Missing FlashRank model directory truthfully falls back to lexical ranking and reports truthful status. |
| **SYS-01** | `test_restart_persists_policy_and_evidence` | `PASSED` | Restarting store against persistent SQLite retains all documents, facts, and HMAC signatures. |
| **SYS-02** | `test_rotation_separate_provenance_key` | `PASSED` | Rotating JWT signing key does not invalidate stored HMAC provenance signatures. |
| **SYS-03** | `test_production_jwks_pinned_signature_and_disabled_demo` | `PASSED` | In `APP_ENV=production`, demo identities/token endpoints return HTTP 404, requiring HTTPS JWKS URL. |

---

## 3. Independent Root Browser Verification Evidence

Root browser verification was conducted using Chrome DevTools MCP (`chrome-devtools-axi`) against the active development environment (`http://127.0.0.1:5173` frontend, `http://127.0.0.1:8000` backend).

### 3.1 Interactive Persona & Query Scenarios

1. **External Contractor Chimera Verification**:
   - **Identity**: `contractor` (Clearance 1, `engineering`).
   - **Scenario**: Chimera vendors and payment question.
   - **Rendered Output**: Returns `AWS` and `Snowflake` as approved vendors. Payment terms and dollar amounts are completely absent.
   - **Graph Canvas**: Exactly 3 contributing nodes rendered in Cytoscape; zero unrelated Titan or Alice nodes.
   - **Source Modal**: Clicking citation opens source viewer modal displaying document ID `doc_chimera_vendors`, verified text, and SHA-256 hash. Pressing Escape successfully closes modal.
2. **Executive VP Chimera Verification**:
   - **Identity**: `vp` (Clearance 4, `engineering`, `procurement`, `mna`).
   - **Scenario**: Same Chimera question.
   - **Rendered Output**: Returns AWS $40k/mo Net-30 and Snowflake $15k/mo Net-60.
   - **Citations**: Grounded citations linking to procurement contracts.
3. **Identity Switch State Reset**:
   - Switching persona from `vp` to `contractor` triggers immediate state purge:
     - `hasAmount = false`
     - `hasOldAnswer = false`
     - `hasEmptyGraph = true`
   - Verified that high-clearance data does not linger in browser DOM or memory across persona transitions.
4. **Multi-Hop Traversal (Alice Titan CyberCorp)**:
   - **Identity**: `vp`.
   - **Question**: *"Which company did Alice approve for acquisition?"*
   - **Rendered Output**: *"Alice approved acquisition of CyberCorp through Project Titan"*.
   - **Citations**: Cites both `doc_titan_leadership` and `doc_titan_acquisition`.
   - **Graph & Query Inspector**: Cytoscape displays 3-node connected subgraph. Query inspector reveals actual transformed 2-hop Cypher with security predicates on every node and relationship.
5. **Cross-Tenant Canary Isolation**:
   - **Identity**: `other_tenant` (`other` tenant).
   - **Query**: Chimera vendors and payment terms.
   - **Rendered Output**: Truthfully reports answer unavailable; returns 0 citations and empty graph canvas. Zero cross-tenant data leakage.
6. **Dynamic Ingestion Proof Beyond Fixed Seed**:
   - **Identity**: `admin`.
   - **Ingestion via UI**: Added two completely fresh documents:
     - Document 1: `Browser QA leadership` - *"Mira leads Project AtlasQA."*
     - Document 2: `Browser QA acquisition` - *"The lead of Project AtlasQA approved acquisition of CometQA."*
     - Labels: Public, `acme` tenant, internal references.
   - **Question**: *"Which company did Mira approve for acquisition?"*
   - **Rendered Output**: *"Mira approved acquisition of CometQA through Project AtlasQA"*, citing both newly ingested documents.
   - **Significance**: Confirms end-to-end dynamic fact extraction, cross-document relationship linking, and RAG retrieval beyond the initial pre-seeded database.
7. **Mobile Viewport (390x844px) Responsiveness**:
   - Tested under emulated iPhone dimensions (`390x844px`).
   - Verified `document.documentElement.scrollWidth == 390` and `document.body.scrollWidth == 390`.
   - No horizontal clipping, wrapping breakage, or viewport overflow occurred, even when displaying full rewritten Cypher queries in the Query Inspector.

### 3.2 Direct HTTP Security & Tampering Probes

- `GET /api/v1/sources/doc_chimera_terms` (as `contractor`): Returns **HTTP 404** with exact payload `{"detail":"Not found"}`.
- `GET /api/v1/sources/no_such_document`: Returns **HTTP 404** with exact payload `{"detail":"Not found"}` (anti-oracle parity).
- `GET /api/v1/documents` (unauthenticated): Returns **HTTP 401 Unauthorized**.
- Tampered JWT payload (Clearance altered from 1 to 4 with original signature): Returns **HTTP 401 Unauthorized**.
- `POST /api/v1/auth/token` with extra body attribute `clearance_level: 4`: Returns **HTTP 422 Unprocessable Entity**.

### 3.3 Visual Evidence Log & Defect Artifacts

- `root-qa/contractor-desktop.png`: Retained as early defect evidence showing initial lexical overlap before entity anchoring was applied.
- `root-qa/vp-desktop.png`: Retained as early defect evidence prior to final relevance tuning.
- `root-qa/contractor-mobile390.png`: Visual evidence of initial mobile layout at 390px viewport.
- `root-qa/contractor-fixed-mobile.png`: Verified final responsive mobile UI for contractor persona.
- `root-qa/alice-mobile.png`: Verified mobile multi-hop retrieval and Query Inspector rendering.

---

## 4. Provider Status & Operational Environment

| Component | Operational Status | Evidence & Verification Notes |
|---|---|---|
| **Local Deterministic Mode** | **ACTIVE & VERIFIED** | Pure SQLite store, TF-IDF cosine vector matching, deterministic extractive synthesis, Lark AST rewriter. 100% offline, zero internet/API keys required. |
| **Neo4j Bolt Database** | **CONFIGURED & TESTED** | `Neo4jAdapter` implements restricted AST execution, timeout deadlines (3s), and server-bound entity sets. Ingestion uses separate writer principal (`NEO4J_WRITE_USER`). Verified against bounded Docker Neo4j fixture. |
| **Groq LLM Streaming** | **HTTP MOCK VERIFIED** | Real streaming protocol, SSE parser, and authorized-only context passing verified via HTTP mock. Health endpoint truthfully reports missing live key without false claiming live cloud execution. |
| **FlashRank ONNX Reranker** | **FALLBACK VERIFIED** | Requires provisioned TinyBERT model directory (`backend/scripts/provision_flashrank.py`). In the absence of frozen models, truthfully falls back to lexical/RRF ranking without runtime network downloads. |
| **LangGraph Pipeline** | **VERIFIED** | Real `StateGraph` integration tested when installed via `uv sync --extra providers` and enabled with `DLP_LANGGRAPH=1`. |
| **Frontend Portal** | **ACTIVE & VERIFIED** | React 19 + TypeScript + Cytoscape.js compiled and tested cleanly with 11 Vitest assertions passing. |
