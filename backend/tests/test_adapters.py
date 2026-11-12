import json
import os
import httpx
import pytest
from backend.app.adapters import GroqAdapter, FlashRankAdapter, run_langgraph, Neo4jAdapter
from backend.app.store import Store
from backend.app.security import IDENTITIES
from backend.app.cypher import parse, execute_local

def test_groq_http_mock_context_only_authorized():
    store = Store(":memory:", "p" * 64)
    from backend.app.retrieval import search
    results = search(store, IDENTITIES["contractor"], "Chimera payment terms")
    captured = []
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "AWS and Snowflake are vendors [1]. Available sources do not provide terms."}}]})
    provider = GroqAdapter("test-key", "llama-3.3-70b-versatile", httpx.MockTransport(respond))
    assert "vendors" in provider.answer("Chimera terms", results)
    assert "$40k" not in json.dumps(captured)
    assert "ORBIT_CANARY" not in json.dumps(captured)
    assert captured[0]["messages"][0]["role"] == "system"
    assert "untrusted" in captured[0]["messages"][0]["content"]

def test_groq_invalid_model_and_http_failure():
    with pytest.raises(ValueError): GroqAdapter("key", "llama-3.1-70b-versatile")
    adapter = GroqAdapter("key", "llama-3.3-70b-versatile", httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(httpx.HTTPStatusError): adapter.answer("query", [])

def test_flashrank_requires_frozen_model(tmp_path):
    with pytest.raises(RuntimeError, match="provisioned"): FlashRankAdapter(str(tmp_path))

def test_real_optional_langgraph():
    pytest.importorskip("langgraph")
    assert run_langgraph(lambda question: [{"text": question}], "authorized evidence") == [{"text": "authorized evidence"}]

@pytest.mark.skipif(not os.getenv("NEO4J_TEST_URI"), reason="Release worker supplies bounded Neo4j integration service")
def test_actual_neo4j_abac_parity_and_provenance():
    store = Store(":memory:", "p" * 64)
    adapter = Neo4jAdapter(os.environ["NEO4J_TEST_URI"], os.getenv("NEO4J_TEST_USER", "neo4j"), os.environ["NEO4J_TEST_PASSWORD"])
    try:
        adapter.driver.verify_connectivity()
        adapter.sync_fixture(store)
        cases = [
            ("MATCH (n) RETURN n.name", {}),
            ("MATCH (p:Project)-[r:CONTRACTS]->(v:Vendor) RETURN p.name, v.name", {}),
            ("MATCH (a:Person)-[r:LEADS]->(p:Project)-[s:ACQUIRES]->(c:Company) WHERE a.name = $person RETURN a.name, c.name", {"person": "Alice"}),
            ("MATCH (n) WHERE n.name = 'AWS' OR n.name = 'Snowflake' AND n.name = 'bad' RETURN n.name", {}),
            ("MATCH (:Person)-[:LEADS]->(p:Project) RETURN p.name", {}),
            ("MATCH (n) WHERE n.name = ' RETURN ' RETURN n.name", {}),
            ("MATCH (n) WHERE n.name = $needle RETURN n.name", {"needle": "AWS' RETURN \\ unicode雪"}),
            ("MATCH (n) WHERE NOT (n.source = 'absent') RETURN n.name", {}),
        ]
        for identity in IDENTITIES.values():
            docs, nodes, edges = store.view(identity)
            for raw, params in cases:
                plan = parse(raw, params, identity)
                plan.parameters["auth_document_ids"] = list(docs)
                local = execute_local(plan, nodes, edges)
                remote = adapter.execute(plan, store, identity)
                assert sorted(map(json.dumps, remote)) == sorted(map(json.dumps, local))
        # Corrupt relationship department and cross-tenant source provenance; both engines deny.
        for mutation in ("department", "source_document_ids"):
            edge = next(e for e in store.all("edges") if e["id"] == "edge_aws")
            edge[mutation] = "finance" if mutation == "department" else ["doc_other_canary"]
            store.put("edges", edge)
            adapter.sync_fixture(store)
            plan = parse("MATCH (p:Project)-[r:CONTRACTS]->(v:Vendor) WHERE v.name = 'AWS' RETURN v.name", {}, IDENTITIES["contractor"])
            assert adapter.execute(plan, store, IDENTITIES["contractor"]) == []
    finally:
        adapter.close()

def test_groq_actual_stream_protocol_mock():
    captured = []
    def respond(request):
        captured.append(json.loads(request.content))
        content = 'data: {"choices":[{"delta":{"content":"AWS "}}]}\n\ndata: {"choices":[{"delta":{"content":"[1]"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=content, headers={"Content-Type": "text/event-stream"})
    provider = GroqAdapter("test-key", "llama-3.3-70b-versatile", httpx.MockTransport(respond))
    assert list(provider.stream("vendors", [{"text": "AWS vendor"}])) == ["AWS ", "[1]"]
    assert captured[0]["stream"] is True


@pytest.mark.skipif(not os.getenv("NEO4J_TEST_URI"), reason="Release worker supplies bounded Neo4j integration service")
def test_actual_neo4j_runtime_chat_graph(monkeypatch):
    from backend.app.main import create_app
    from backend.app.security import Settings
    from fastapi.testclient import TestClient
    monkeypatch.setenv("NEO4J_URI", os.environ["NEO4J_TEST_URI"])
    monkeypatch.setenv("NEO4J_PASSWORD", os.environ["NEO4J_TEST_PASSWORD"])
    app = create_app(Settings(db_path=":memory:"))
    provision = Neo4jAdapter(os.environ["NEO4J_TEST_URI"], "neo4j", os.environ["NEO4J_TEST_PASSWORD"])
    try:
        provision.sync_fixture(app.state.store)
        client = TestClient(app)
        token = client.post("/api/v1/auth/token", json={"identity_id": "vp"}).json()["access_token"]
        response = client.post("/api/v1/chat", headers={"Authorization": "Bearer " + token}, json={"message": "What acquisition did Alice approve?"})
        assert response.status_code == 200
        assert "CyberCorp" in response.text and "authorized_graph_neo4j" in response.text
        token = client.post("/api/v1/auth/token", json={"identity_id": "contractor"}).json()["access_token"]
        graph = client.get("/api/v1/graph/subgraph", headers={"Authorization": "Bearer " + token})
        assert "$40k" not in graph.text
        assert client.get("/api/v1/health").json()["adapters"]["neo4j_connected"] is True
    finally:
        provision.close()

@pytest.mark.skipif(not os.getenv("NEO4J_TEST_URI"), reason="Release worker supplies bounded Neo4j integration service")
def test_actual_neo4j_ingest_automatic_separate_writer(monkeypatch):
    from backend.app.main import create_app
    from backend.app.security import Settings
    from fastapi.testclient import TestClient
    monkeypatch.setenv("NEO4J_URI", os.environ["NEO4J_TEST_URI"])
    monkeypatch.setenv("NEO4J_PASSWORD", os.environ["NEO4J_TEST_PASSWORD"])
    # Dedicated Community development DB has one administrator; production needs
    # distinct read-only and provisioning principals. Code uses distinct drivers.
    monkeypatch.setenv("NEO4J_WRITE_USER", "neo4j")
    monkeypatch.setenv("NEO4J_WRITE_PASSWORD", os.environ["NEO4J_TEST_PASSWORD"])
    app = create_app(Settings(db_path=":memory:"))
    client = TestClient(app)
    token = client.post("/api/v1/auth/token", json={"identity_id": "admin"}).json()["access_token"]
    h = {"Authorization": "Bearer " + token}
    for content in ("Leena leads Project Aurora.", "Project Aurora is acquiring HorizonLabs."):
        r = client.post("/api/v1/ingest", headers=h, json=dict(title="Aurora evidence", content=content, classification_level=2, department="engineering"))
        assert r.status_code == 201 and r.json()["graph_indexing"] == "indexed"
    r = client.post("/api/v1/query/cypher", headers=h, json={"cypher": "MATCH (a:Person)-[r:LEADS]->(p:Project)-[s:ACQUIRES]->(c:Company) WHERE a.name = 'Leena' RETURN c.name"})
    assert r.json()["rows"] == [["HorizonLabs"]]
    response = client.post("/api/v1/chat", headers=h, json={"message": "What acquisition does Leena lead?"})
    assert "HorizonLabs" in response.text

@pytest.mark.skipif(not os.getenv("FLASHRANK_TEST_MODEL_DIR"), reason="Explicit frozen local TinyBERT model not provisioned")
def test_actual_frozen_flashrank_offline(monkeypatch):
    # Runtime must remain offline even with a ready optional model.
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Unexpected runtime download")))
    adapter = FlashRankAdapter(os.environ["FLASHRANK_TEST_MODEL_DIR"])
    documents = [{"text": "Cloud infrastructure is provided by AWS."}, {"text": "Alice leads Project Titan."}]
    results = adapter.rerank("Who provides cloud infrastructure?", documents)
    assert results[0]["text"] == documents[0]["text"]
    assert results[0]["rerank_score"] > results[1]["rerank_score"]

def test_flashrank_runtime_missing_model_truthful_fallback(monkeypatch, tmp_path):
    from backend.app.main import create_app
    from backend.app.security import Settings
    from fastapi.testclient import TestClient
    monkeypatch.setenv("FLASHRANK_MODEL_DIR", str(tmp_path / "unprovisioned"))
    client = TestClient(create_app(Settings(db_path=":memory:")))
    health = client.get("/api/v1/health").json()
    assert health["adapters"]["flashrank"] == "disabled_model_unavailable"
    assert health["adapters"]["reranker"] == "lexical_rrf"
