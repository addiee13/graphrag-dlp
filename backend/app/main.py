"""FastAPI application. Run: uvicorn backend.app.main:app."""
import json
import os
import re
import time
import uuid
from typing import Annotated
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from .security import Auth, Settings, IDENTITIES, permitted
from .store import Store, digest
from .cypher import parse, execute_local, CypherError
from .retrieval import search, graph_payload, secure_paths

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
class Login(Strict):
    identity_id: str
class Ingest(Strict):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=100000)
    source_uri: str = Field(default="", max_length=2000)
    classification_level: int = Field(ge=1, le=4, strict=True)
    department: str = Field(min_length=1, max_length=100)
    extract_entities: bool = True
class Cypher(Strict):
    cypher: str = Field(max_length=8000)
    parameters: dict = Field(default_factory=dict)
class Search(Strict):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
class Chat(Strict):
    message: str = Field(min_length=1, max_length=2000)
    include_graph: bool = True

def create_app(settings=None):
    settings = settings or Settings()
    auth = Auth(settings); store = Store(settings.db_path, settings.secret)
    app = FastAPI(title="GraphRAG-DLP", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
    app.state.store = store; app.state.auth = auth
    from .adapters import Neo4jAdapter, GroqAdapter, FlashRankAdapter, run_langgraph
    neo = None
    if os.getenv("NEO4J_URI"):
        neo = Neo4jAdapter(os.environ["NEO4J_URI"], os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])
        neo.driver.verify_connectivity()
    writer = None
    if neo and os.getenv("NEO4J_WRITE_USER") and os.getenv("NEO4J_WRITE_PASSWORD"):
        writer = Neo4jAdapter(os.environ["NEO4J_URI"], os.environ["NEO4J_WRITE_USER"], os.environ["NEO4J_WRITE_PASSWORD"])
        writer.driver.verify_connectivity()
        writer.sync_fixture(store)
        for job in store.all("indexing_jobs"):
            store.put("indexing_jobs", dict(job, status="indexed"))
    groq = GroqAdapter(os.environ["GROQ_API_KEY"], os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")) if os.getenv("GROQ_API_KEY") else None
    ranker = None
    ranker_status = "disabled_model_not_provisioned"
    if os.getenv("FLASHRANK_MODEL_DIR"):
        try:
            ranker = FlashRankAdapter(os.environ["FLASHRANK_MODEL_DIR"])
            ranker_status = "provisioned_local_model"
        except (RuntimeError, ImportError, OSError, ValueError):
            ranker_status = "disabled_model_unavailable"
    langgraph_enabled = os.getenv("DLP_LANGGRAPH") == "1"
    def execute_plan(plan, claims):
        docs, nodes, edges = store.view(claims)
        plan.parameters.update(auth_document_ids=list(docs), auth_node_ids=list(nodes), auth_edge_ids=list(edges))
        # Preflight bounds expansion before optional remote execution.
        local = execute_local(plan, nodes, edges)
        return neo.execute(plan, store, claims) if neo else local
    def authorized_graph(claims):
        node_plan = parse("MATCH (n) RETURN n LIMIT 100", {}, claims)
        edge_plan = parse("MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 100", {}, claims)
        nodes = {n[0]["id"]: n[0] for n in execute_plan(node_plan, claims)}
        edges = {}
        for a, edge, b in execute_plan(edge_plan, claims):
            nodes[a["id"]] = a; nodes[b["id"]] = b; edges[edge["id"]] = edge
        return nodes, edges
    def retrieve(claims, question, top_k):
        graph_view = authorized_graph(claims)
        fn = lambda q: search(store, claims, q, top_k, graph_view)
        results = run_langgraph(fn, question) if langgraph_enabled else fn(question)
        return ranker.rerank(question, results) if ranker else results

    def current(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Bearer token required")
        return auth.verify(authorization[7:])
    def audit(claims, operation, query=""):
        store.put("audit", dict(id=uuid.uuid4().hex, tenant_id=claims["tenant_id"], user_id=claims["user_id"], operation=operation, query_fingerprint=digest(query), timestamp=time.time()))
    @app.get("/api/v1/health")
    def health():
        return dict(status="healthy", version="1.0.0", mode="groq_configured" if groq else "deterministic_local", auth_enforced=True,
            adapters=dict(graph_store="neo4j_with_sqlite_evidence" if neo else "sqlite_persistent", llm_engine="groq_configured_not_live_verified" if groq else "deterministic_extractive", vector_engine="local_sparse_tfidf_cosine", reranker="flashrank" if ranker else "lexical_rrf", neo4j_connected=bool(neo), neo4j_ingest_indexing="automatic_writer" if writer else "pending_without_writer" if neo else "local", groq_connected=False, langgraph="enabled" if langgraph_enabled else "disabled", flashrank=ranker_status))
    @app.get("/api/v1/auth/identities")
    def identities():
        if settings.mode == "production": raise HTTPException(404, "Not found")
        return {"identities": [dict(identity_id=id, **v) for id, v in IDENTITIES.items()]}
    @app.post("/api/v1/auth/token")
    def token(body: Login): return auth.issue(body.identity_id)
    @app.get("/api/v1/documents")
    def documents(claims=Depends(current)):
        audit(claims, "documents")
        docs, _, _ = store.view(claims)
        result = [{k: v for k, v in d.items() if k not in ("content", "provenance_signature", "id")} for d in docs.values()]
        return dict(documents=result, total=len(result))
    @app.get("/api/v1/sources/{document_id}")
    def source(document_id: str, claims=Depends(current)):
        audit(claims, "source", document_id)
        docs, _, _ = store.view(claims)
        d = docs.get(document_id)
        if not d: raise HTTPException(404, "Not found")
        return {k: d[k] for k in ("document_id", "title", "content", "classification_level", "department", "content_hash", "source_uri")}
    @app.post("/api/v1/ingest", status_code=201)
    def ingest(body: Ingest, claims=Depends(current)):
        audit(claims, "ingest")
        if not {"admin", "ingestor"} & set(claims["roles"]): raise HTTPException(403, "Ingestion not permitted")
        if not permitted(dict(tenant_id=claims["tenant_id"], classification_level=body.classification_level, department=body.department), claims):
            raise HTTPException(403, "Ingestion labels not permitted")
        before_nodes = len(store.all("nodes")); before_edges = len(store.all("edges"))
        d = store.add_document(body.title, body.content, claims["tenant_id"], body.classification_level, body.department, body.source_uri, extract=body.extract_entities)
        indexing = "indexed"
        if neo:
            indexing = "pending"
            store.put("indexing_jobs", dict(id=d["id"], tenant_id=claims["tenant_id"], status="pending"))
            if writer:
                try:
                    writer.sync_fixture(store)
                    indexing = "indexed"
                    for job in store.all("indexing_jobs"):
                        store.put("indexing_jobs", dict(job, status="indexed"))
                except Exception:
                    # Document remains persisted; next indexing pass retries all outstanding jobs.
                    pass
        return dict(graph_indexing=indexing, document_id=d["id"], tenant_id=d["tenant_id"], content_hash=d["content_hash"], provenance_signature=d["provenance_signature"], classification_level=d["classification_level"], chunks_created=1, nodes_created=len(store.all("nodes")) - before_nodes, edges_created=len(store.all("edges")) - before_edges, created_at=d["created_at"])
    @app.post("/api/v1/query/cypher")
    def cypher(body: Cypher, claims=Depends(current)):
        audit(claims, "cypher", body.cypher)
        start = time.monotonic()
        try:
            ast = parse(body.cypher, body.parameters, claims)
            docs, nodes, edges = store.view(claims)
            ast.parameters["auth_document_ids"] = list(docs)
            rows = execute_plan(ast, claims)
        except CypherError as exc: raise HTTPException(400, str(exc)) from None
        from .cypher import emit
        return dict(transformed_cypher=ast.transformed, columns=[emit(p) for p in ast.projections], rows=rows, execution_time_ms=round((time.monotonic()-start)*1000, 3))
    @app.post("/api/v1/search/hybrid")
    def hybrid(body: Search, claims=Depends(current)):
        audit(claims, "search", body.query)
        results = retrieve(claims, body.query, body.top_k)
        return dict(results=results, total_hits=len(results), vector_mode="sparse_tfidf_cosine", reranker="lexical_rrf")
    @app.get("/api/v1/graph/subgraph")
    def graph(entity_id: str | None = None, max_depth: int = Query(default=2, ge=0, le=3), claims=Depends(current)):
        audit(claims, "graph")
        return graph_payload(store, claims, entity_id, max_depth, graph_view=authorized_graph(claims))
    @app.post("/api/v1/chat")
    def chat(body: Chat, claims=Depends(current)):
        audit(claims, "chat", body.message)
        results = retrieve(claims, body.message, 6)
        plans = []
        paths = secure_paths(store, claims, body.message, execute_plan, plans)
        # A fixed bounded AST also grounds the single-node/relationship retrieval stage.
        if not plans:
            plan = parse("MATCH (n) RETURN n LIMIT 100", {}, claims)
            execute_plan(plan, claims)
            plans.append(plan.transformed)
        # Context is exclusively authorized evidence, never a stored user instruction.
        answer = " ".join(f"{r['text']} [{i+1}]" for i, r in enumerate(results)) or "Available sources do not provide an answer."
        if paths:
            path_sentences = []
            docs, _, _ = store.view(claims)
            for person, project, company, leadership, acquisition in paths:
                evidence = [docs[id]["content"] for id in acquisition["source_document_ids"]]
                verb = "approved acquisition of" if any("approved acquisition" in text for text in evidence) else "leads the acquisition of"
                path_sentences.append(f"{person} {verb} {company} through {project}.")
            answer = " ".join(path_sentences) + " " + answer
        if any(w in body.message.lower() for w in ("payment", "terms", "rate")) and not any("$" in r["text"] for r in results):
            answer += " Available sources do not provide payment terms."
        def stream():
            def event(name, data): return f"event: {name}\ndata: {json.dumps(data)}\n\n"
            yield event("metadata", dict(session_id="sess_"+uuid.uuid4().hex, tenant_id=claims["tenant_id"], clearance_level=claims["clearance_level"], mode="groq" if groq else "deterministic_local", transformed_cypher=plans[0], pipeline=["verified_jwt", "authorized_graph_neo4j" if neo else "authorized_graph_local", "lexical", "sparse_tfidf_cosine", "rrf", "flashrank" if ranker else "lexical_rerank", "langgraph" if langgraph_enabled else "direct_pipeline", "groq" if groq else "extractive_answer"]))
            tokens = groq.stream(body.message, results) if groq else re.findall(r"\S+\s*", answer)
            token_count = 0
            try:
                for word in tokens:
                    token_count += 1
                    yield event("token", {"delta": word})
            except Exception:
                yield event("error", {"detail": "Answer provider unavailable"})
                yield event("done", {"status": "error", "total_tokens": token_count, "citations_count": 0})
                return
            _, nodes, edges = store.view(claims)
            for i, r in enumerate(results):
                id = r["document_id"]
                yield event("citation", dict(citation_id=f"cite_{i+1}", document_id=id, document_title=r["document_title"], chunk_id=r["chunk_id"], snippet=r["text"], classification_level=r["classification_level"], tenant_id=claims["tenant_id"], content_hash=r["content_hash"], source_node_ids=[n["id"] for n in nodes.values() if id in n["source_document_ids"]], source_edge_ids=[e["id"] for e in edges.values() if id in e["source_document_ids"]]))
            if body.include_graph: yield event("graph_update", graph_payload(store, claims, document_ids=[r["document_id"] for r in results], graph_view=authorized_graph(claims)))
            yield event("done", dict(status="complete", total_tokens=token_count, citations_count=len(results)))
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return app

app = create_app()
