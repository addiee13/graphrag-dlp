# GraphRAG DLP frontend

React + Vite + TypeScript knowledge workspace with a server-issued demo session, streaming answers, authenticated source drawer, Cytoscape evidence graph, safe query inspector, and role-gated document ingestion.

```sh
npm ci
npm run dev
npm test
npm run build
```

Run commands from `frontend/`. Vite serves `http://127.0.0.1:5173` and proxies `/api` to `http://127.0.0.1:8000`. Set `API_PROXY_TARGET` when starting Vite to use another local backend. Production hosting must route `/api/v1` to the backend, or set `VITE_API_BASE_URL` to its trusted API URL at build time and configure the backend's CORS allowlist. The preview server serves static assets only; it requires an API reverse proxy or an explicit API URL.

The only demo login body is `{ "identity_id": "<server-listed-id>" }`. Tokens remain in memory. Identity changes discard the mounted workspace, cancel requests, and clear answer, graph, source, ingestion, and inspector state. The API is the authorization authority; hiding ingestion controls is only a usability measure. Demo identity endpoints may be disabled in production; this UI does not invent a session or accept custom clearance claims.

Only graphs provided by the chat stream are rendered. The UI neither adds hypothetical entities nor reports blocked resources. Source references are inert text; citations retrieve `/sources/{document_id}` using the session token. Responses and source text render as text rather than executable HTML.

The operational mode and optional adapter values come from health/stream metadata. No-key deterministic synthesis is explicitly labeled. An unavailable API is an error state, with no sample responses or fabricated graph.

Tests use mocked HTTP fixtures to check transport framing and session isolation. They do not substitute for live backend and browser integration checks.
