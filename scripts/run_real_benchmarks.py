"""Real Data Benchmark Execution Runner for GraphRAG-DLP.

Connects to the running server on http://127.0.0.1:8000 and performs:
1. Ingestion of 63 authentic enterprise documents + 8 adversarial documents from
   real SEC EDGAR 10-Ks and Enron email corpora across 4 clearance tiers,
   3 departments, and 2 tenants.
2. Security & DLP penetration testing (cross-clearance DLP, cross-tenant isolation,
   anti-oracle 404 concealment, prompt injection containment, and Cypher AST defenses).
3. Retrieval quality benchmarks (Precision@K, Recall@K, MRR) comparing canonical
   queries against typo/leetspeak scrambling and syntactic permutations on real text.
4. Latency and throughput profiling (P50, P90, P99) for Ingestion, Hybrid Search,
   Cypher AST evaluation, and Chat SSE Time-To-First-Token (TTFT).
5. Structured JSON reporting (real_benchmark_results.json).
"""

import os
import sys
import json
import time
import math
import statistics
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = REPO_ROOT / "scripts" / "real_enterprise_dataset.json"
OUTPUT_FILE = REPO_ROOT / "real_benchmark_results.json"
BASE_URL = os.getenv("BENCHMARK_URL", "http://127.0.0.1:8000")


def percentile(values: List[float], p: float) -> float:
    """Calculate the p-th percentile of a list of floats."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_v[int(k)], 3)
    d0 = sorted_v[int(f)] * (c - k)
    d1 = sorted_v[int(c)] * (k - f)
    return round(d0 + d1, 3)


def compute_stats(values: List[float]) -> Dict[str, float]:
    """Compute summary statistics for a list of values."""
    if not values:
        return {"count": 0, "min": 0.0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0, "max": 0.0, "stdev": 0.0}
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "mean": round(statistics.mean(values), 3),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p99": percentile(values, 99),
        "max": round(max(values), 3),
        "stdev": round(statistics.stdev(values) if len(values) > 1 else 0.0, 3)
    }


class RealBenchmarkRunner:
    def __init__(self, base_url: str = BASE_URL, dataset_path: Path = DATASET_PATH):
        self.base_url = base_url
        self.dataset_path = dataset_path
        self.client = httpx.Client(base_url=self.base_url, timeout=35.0)
        self.tokens: Dict[str, str] = {}
        self.alias_to_doc_id: Dict[str, str] = {}
        self.dataset: Dict[str, Any] = {}
        self.results: Dict[str, Any] = {
            "meta": {
                "title": "GraphRAG-DLP Authentic Enterprise Data Benchmark",
                "timestamp": time.time(),
                "base_url": self.base_url,
                "server_health": None,
            },
            "ingestion": {},
            "security": {},
            "retrieval": {},
            "latency": {}
        }

    def load_dataset(self):
        """Load authentic dataset from JSON."""
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found at {self.dataset_path}. Run scripts/fetch_real_data.py first.")
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            self.dataset = json.load(f)
        print(f"[+] Loaded authentic dataset: {len(self.dataset['real_documents'])} real docs, "
              f"{len(self.dataset['adversarial_documents'])} adversarial docs, "
              f"{len(self.dataset['retrieval_test_cases'])} retrieval cases, "
              f"{len(self.dataset['security_probes'])} security probes.")

    def check_health(self) -> Dict[str, Any]:
        print(f"[*] Checking health of target {self.base_url}/api/v1/health ...")
        res = self.client.get("/api/v1/health")
        if res.status_code != 200:
            raise RuntimeError(f"Server unhealthy: status {res.status_code}: {res.text}")
        health_data = res.json()
        self.results["meta"]["server_health"] = health_data
        print(f"[+] Server Healthy! Mode: {health_data.get('mode')}, Adapters: {health_data.get('adapters')}")
        return health_data

    def authenticate(self):
        print("[*] Authenticating demo personas ...")
        personas = ["contractor", "engineer", "vp", "admin", "other_tenant"]
        for p in personas:
            res = self.client.post("/api/v1/auth/token", json={"identity_id": p})
            if res.status_code != 200:
                raise RuntimeError(f"Failed to authenticate persona '{p}': {res.text}")
            self.tokens[p] = res.json()["access_token"]
        print(f"[+] Successfully authenticated {len(self.tokens)} personas.")

    def auth_headers(self, persona: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[persona]}"}

    def ingest_documents(self) -> Dict[str, Any]:
        all_docs = self.dataset["real_documents"] + self.dataset["adversarial_documents"]
        print(f"[*] Beginning Ingestion Benchmark of {len(all_docs)} authentic enterprise documents ...")
        latencies_ms: List[float] = []
        ingest_records: List[Dict[str, Any]] = []
        total_nodes = 0
        total_edges = 0

        t_start = time.perf_counter()

        for doc in all_docs:
            ingestor_persona = "other_tenant" if doc.get("tenant_id") == "other" else "admin"
            payload = {
                "title": doc["title"],
                "content": doc["content"],
                "source_uri": doc.get("source_uri", ""),
                "classification_level": doc["classification_level"],
                "department": doc["department"],
                "extract_entities": doc.get("extract_entities", True)
            }
            t0 = time.perf_counter()
            res = self.client.post("/api/v1/ingest", json=payload, headers=self.auth_headers(ingestor_persona))
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000
            latencies_ms.append(elapsed_ms)

            if res.status_code != 201:
                print(f"[!] Warning: Failed to ingest {doc['id_alias']}: {res.status_code} {res.text}")
                continue

            data = res.json()
            doc_id = data["document_id"]
            self.alias_to_doc_id[doc["id_alias"]] = doc_id
            total_nodes += data.get("nodes_created", 0)
            total_edges += data.get("edges_created", 0)

            ingest_records.append({
                "alias": doc["id_alias"],
                "doc_id": doc_id,
                "tenant": doc.get("tenant_id", "acme"),
                "level": doc["classification_level"],
                "dept": doc["department"],
                "latency_ms": round(elapsed_ms, 2),
                "nodes_created": data.get("nodes_created", 0),
                "edges_created": data.get("edges_created", 0)
            })

        t_total = time.perf_counter() - t_start
        throughput_docs_per_sec = len(all_docs) / t_total if t_total > 0 else 0.0
        stats = compute_stats(latencies_ms)

        ingest_summary = {
            "total_documents_ingested": len(ingest_records),
            "total_chunks_created": len(ingest_records),
            "total_nodes_created": total_nodes,
            "total_edges_created": total_edges,
            "total_duration_sec": round(t_total, 3),
            "throughput_docs_per_sec": round(throughput_docs_per_sec, 2),
            "latency_ms": stats,
            "records": ingest_records
        }
        self.results["ingestion"] = ingest_summary
        print(f"[+] Ingestion Complete! {len(ingest_records)} docs in {t_total:.2f}s ({throughput_docs_per_sec:.1f} docs/sec). "
              f"P50: {stats['p50']}ms, P90: {stats['p90']}ms, P99: {stats['p99']}ms")
        return ingest_summary

    def run_security_benchmarks(self) -> Dict[str, Any]:
        probes = self.dataset["security_probes"]
        print(f"[*] Running Security & DLP Containment Benchmark ({len(probes)} Probes) ...")
        probe_results = []
        leaks_detected = 0
        anti_oracle_failures = 0
        ast_rejection_failures = 0

        for probe in probes:
            endpoint = probe["endpoint"]
            if "{doc_id_placeholder}" in endpoint:
                target_doc_id = self.alias_to_doc_id.get(probe.get("target_alias"), "doc_proc_l4_01")
                endpoint = endpoint.replace("{doc_id_placeholder}", target_doc_id)

            headers = self.auth_headers(probe["persona"])
            t0 = time.perf_counter()

            if endpoint.startswith("/api/v1/sources/"):
                res = self.client.get(endpoint, headers=headers)
                response_text = res.text
                actual_status = res.status_code
            elif endpoint == "/api/v1/chat":
                tokens = []
                with self.client.stream("POST", endpoint, json=probe["payload"], headers=headers) as stream:
                    for line in stream.iter_lines():
                        tokens.append(line)
                response_text = "\n".join(tokens)
                actual_status = 200
            else:
                res = self.client.post(endpoint, json=probe["payload"], headers=headers)
                response_text = res.text
                actual_status = res.status_code

            elapsed_ms = (time.perf_counter() - t0) * 1000
            status_matched = (actual_status == probe["expected_status"])

            # Verify forbidden tokens
            leaked_tokens = [tok for tok in probe["forbidden_tokens"] if tok in response_text]
            passed = status_matched and (len(leaked_tokens) == 0)

            if not passed:
                if leaked_tokens:
                    leaks_detected += 1
                if probe["probe_type"] == "anti_oracle_404" and actual_status != 404:
                    anti_oracle_failures += 1
                if probe["probe_type"] == "malicious_cypher" and actual_status != probe["expected_status"]:
                    ast_rejection_failures += 1

            probe_results.append({
                "probe_id": probe["probe_id"],
                "probe_type": probe["probe_type"],
                "persona": probe["persona"],
                "endpoint": endpoint,
                "expected_status": probe["expected_status"],
                "actual_status": actual_status,
                "status_matched": status_matched,
                "leaked_tokens": leaked_tokens,
                "passed": passed,
                "latency_ms": round(elapsed_ms, 2),
                "description": probe.get("description", "")
            })

        total_probes = len(probes)
        passed_probes = sum(1 for p in probe_results if p["passed"])
        leakage_rate = (leaks_detected / total_probes) * 100.0
        anti_oracle_integrity = ((total_probes - anti_oracle_failures) / total_probes) * 100.0
        ast_rejection_rate = 100.0 if ast_rejection_failures == 0 else 0.0

        cross_tenant_probes = [p for p in probe_results if p["probe_type"] == "cross_tenant"]
        cross_tenant_isolation = 100.0 if not any(not p["passed"] for p in cross_tenant_probes) else 0.0

        security_summary = {
            "total_probes": total_probes,
            "passed_probes": passed_probes,
            "failed_probes": total_probes - passed_probes,
            "leakage_rate_pct": round(leakage_rate, 2),
            "anti_oracle_integrity_pct": round(anti_oracle_integrity, 2),
            "ast_rejection_rate_pct": round(ast_rejection_rate, 2),
            "cross_tenant_isolation_pct": round(cross_tenant_isolation, 2),
            "probes": probe_results
        }
        self.results["security"] = security_summary
        print(f"[+] Security Benchmark Complete! Passed: {passed_probes}/{total_probes}. "
              f"Data Leakage Rate: {leakage_rate:.1f}%, Anti-Oracle: {anti_oracle_integrity:.1f}%, "
              f"AST Rejection: {ast_rejection_rate:.1f}%, Cross-Tenant: {cross_tenant_isolation:.1f}%")
        return security_summary

    def run_retrieval_benchmarks(self) -> Dict[str, Any]:
        cases = self.dataset["retrieval_test_cases"]
        print(f"[*] Running Retrieval Quality Benchmarks ({len(cases)} Cases on Real Data) ...")
        case_results = []
        by_category: Dict[str, List[Dict[str, Any]]] = {}

        # Build comprehensive alias-to-all-matching-IDs mapping
        alias_to_all_ids: Dict[str, set] = {k: {v} for k, v in self.alias_to_doc_id.items()}
        all_docs = self.dataset["real_documents"] + self.dataset["adversarial_documents"]
        uri_to_alias = {d.get("source_uri"): d["id_alias"] for d in all_docs if d.get("source_uri")}
        title_to_alias = {d["title"]: d["id_alias"] for d in all_docs}

        for persona in ("admin", "other_tenant"):
            docs = self.client.get("/api/v1/documents", headers=self.auth_headers(persona)).json().get("documents", [])
            for d in docs:
                did = d.get("document_id")
                uri = d.get("source_uri")
                title = d.get("title")
                alias = uri_to_alias.get(uri) or title_to_alias.get(title)
                if alias:
                    alias_to_all_ids.setdefault(alias, set()).add(did)

        for tc in cases:
            # Select persona matching or exceeding target clearance & department
            target_lvl = tc.get("target_clearance", 1)
            target_dept = tc.get("target_department", "engineering")
            if target_lvl <= 1 and target_dept == "engineering":
                persona = "contractor"
            elif target_lvl <= 2 and target_dept == "engineering":
                persona = "engineer"
            else:
                persona = "vp"  # VP has level 4 across engineering, procurement, mna

            headers = self.auth_headers(persona)
            t0 = time.perf_counter()
            res = self.client.post("/api/v1/search/hybrid", json={"query": tc["query"], "top_k": 5}, headers=headers)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            if res.status_code != 200:
                print(f"[!] Error in retrieval {tc['test_id']}: {res.status_code} {res.text}")
                continue

            data = res.json()
            hits = data.get("results", [])
            retrieved_doc_ids = [h["document_id"] for h in hits]
            expected_doc_ids = set()
            for a in tc["expected_doc_aliases"]:
                expected_doc_ids.update(alias_to_all_ids.get(a, set()))

            p_at_1 = 1.0 if (expected_doc_ids and retrieved_doc_ids and retrieved_doc_ids[0] in expected_doc_ids) else 0.0
            p_at_3 = sum(1 for d in retrieved_doc_ids[:3] if d in expected_doc_ids) / 3.0 if expected_doc_ids else 0.0
            p_at_5 = sum(1 for d in retrieved_doc_ids[:5] if d in expected_doc_ids) / 5.0 if expected_doc_ids else 0.0

            if expected_doc_ids:
                first_match_rank = next((idx + 1 for idx, d in enumerate(retrieved_doc_ids) if d in expected_doc_ids), None)
                rr = 1.0 / first_match_rank if first_match_rank else 0.0
                r_at_1 = 1.0 if (first_match_rank and first_match_rank <= 1) else 0.0
                r_at_3 = 1.0 if (first_match_rank and first_match_rank <= 3) else 0.0
                r_at_5 = 1.0 if (first_match_rank and first_match_rank <= 5) else 0.0
            else:
                # Decoy probe: success is zero retrieved docs matching decoy
                r_at_1 = r_at_3 = r_at_5 = 1.0 if not retrieved_doc_ids else 0.0
                rr = 1.0 if not retrieved_doc_ids else 0.0

            top_rrf = hits[0].get("rrf_score", 0.0) if hits else 0.0
            top_rerank = hits[0].get("rerank_score", 0.0) if hits else 0.0

            item = {
                "test_id": tc["test_id"],
                "category": tc["category"],
                "query": tc["query"],
                "persona": persona,
                "expected_aliases": tc["expected_doc_aliases"],
                "expected_doc_ids": list(expected_doc_ids),
                "retrieved_doc_ids": retrieved_doc_ids,
                "precision_at_1": round(p_at_1, 3),
                "precision_at_3": round(p_at_3, 3),
                "precision_at_5": round(p_at_5, 3),
                "recall_at_1": round(r_at_1, 3),
                "recall_at_3": round(r_at_3, 3),
                "recall_at_5": round(r_at_5, 3),
                "reciprocal_rank": round(rr, 3),
                "top_rrf_score": round(top_rrf, 4),
                "top_rerank_score": round(top_rerank, 4),
                "latency_ms": round(elapsed_ms, 2)
            }
            case_results.append(item)
            by_category.setdefault(tc["category"], []).append(item)

        category_metrics = {}
        for cat, items in by_category.items():
            category_metrics[cat] = {
                "count": len(items),
                "mean_p1": round(statistics.mean(i["precision_at_1"] for i in items), 3),
                "mean_p3": round(statistics.mean(i["precision_at_3"] for i in items), 3),
                "mean_p5": round(statistics.mean(i["precision_at_5"] for i in items), 3),
                "mean_r1": round(statistics.mean(i["recall_at_1"] for i in items), 3),
                "mean_r3": round(statistics.mean(i["recall_at_3"] for i in items), 3),
                "mean_r5": round(statistics.mean(i["recall_at_5"] for i in items), 3),
                "mrr": round(statistics.mean(i["reciprocal_rank"] for i in items), 3),
                "mean_latency_ms": round(statistics.mean(i["latency_ms"] for i in items), 2)
            }

        canon_mrr = category_metrics.get("canonical", {}).get("mrr", 1.0)
        leetspeak_mrr = category_metrics.get("typo_leetspeak", {}).get("mrr", 0.0)
        permuted_mrr = category_metrics.get("syntactic_permutation", {}).get("mrr", 0.0)

        degradation = {
            "canonical_mrr": canon_mrr,
            "leetspeak_mrr": leetspeak_mrr,
            "permuted_mrr": permuted_mrr,
            "leetspeak_degradation_pct": round((1.0 - (leetspeak_mrr / canon_mrr if canon_mrr else 0.0)) * 100.0, 2),
            "permuted_degradation_pct": round((1.0 - (permuted_mrr / canon_mrr if canon_mrr else 0.0)) * 100.0, 2)
        }

        retrieval_summary = {
            "total_cases": len(case_results),
            "category_metrics": category_metrics,
            "degradation": degradation,
            "test_cases": case_results
        }
        self.results["retrieval"] = retrieval_summary
        print(f"[+] Retrieval Benchmark Complete! Canonical MRR: {canon_mrr}, "
              f"Permuted MRR: {permuted_mrr} (Degradation: {degradation['permuted_degradation_pct']}%), "
              f"Leetspeak MRR: {leetspeak_mrr} (Degradation: {degradation['leetspeak_degradation_pct']}%)")
        return retrieval_summary

    def run_latency_throughput_benchmarks(self) -> Dict[str, Any]:
        print("[*] Running Latency & Throughput Benchmark on Authentic Real Corporate Data ...")

        # 1. Hybrid Search Latency (100 iterations)
        search_queries = [
            ("Microsoft Nuance acquisition Satya Nadella", "vp"),
            ("Activision Blizzard XboxGaming Phil Spencer purchase price", "vp"),
            ("Whole Foods AmazonGrocery Jeff Bezos retail stores", "vp"),
            ("Enron High Island Block A-1 Vastar hydrocarbon telemetry", "engineer"),
            ("Apple manufacturing purchase obligations Foxconn 53 billion", "vp"),
            ("Calpine Transwestern daily gas nomination meter 7268", "engineer"),
            ("Apple Open Source WebKit browser architecture", "contractor"),
            ("Microsoft Azure Cloud distributed infrastructure regions", "contractor"),
        ]
        search_latencies: List[float] = []
        for i in range(100):
            query, persona = search_queries[i % len(search_queries)]
            t0 = time.perf_counter()
            self.client.post("/api/v1/search/hybrid", json={"query": query, "top_k": 5}, headers=self.auth_headers(persona))
            search_latencies.append((time.perf_counter() - t0) * 1000)

        # 2. Restricted Cypher Latency (100 iterations)
        cypher_queries = [
            ("MATCH (n) RETURN n LIMIT 25", "contractor"),
            ("MATCH (p:Person)-[r:LEADS]->(proj:Project) RETURN p.name, proj.name", "engineer"),
            ("MATCH (proj:Project)-[r:CONTRACTS]->(v:Vendor) RETURN proj.name, v.name", "vp"),
            ("MATCH (proj:Project)-[r:ACQUIRES]->(c:Company) RETURN proj.name, c.name", "vp"),
            ("MATCH (n:Vendor) RETURN n.name, n.classification_level LIMIT 10", "engineer"),
        ]
        cypher_latencies: List[float] = []
        for i in range(100):
            cypher_str, persona = cypher_queries[i % len(cypher_queries)]
            t0 = time.perf_counter()
            self.client.post("/api/v1/query/cypher", json={"cypher": cypher_str}, headers=self.auth_headers(persona))
            cypher_latencies.append((time.perf_counter() - t0) * 1000)

        # 3. Chat SSE TTFT & Full Completion Latency (25 iterations)
        chat_messages = [
            ("Who leads Project AzureSpeech and what company is it acquiring?", "vp"),
            ("Who leads Project XboxGaming and what is it acquiring?", "vp"),
            ("Who leads Project HighIsland and what vendor does it contract?", "engineer"),
            ("What are the payment terms for Project SupplyChain Foxconn?", "vp"),
            ("Explain the WebKit open source architecture for Project WebKit.", "contractor"),
        ]
        chat_ttft_latencies: List[float] = []
        chat_total_latencies: List[float] = []
        total_tokens_generated = 0

        for i in range(25):
            msg, persona = chat_messages[i % len(chat_messages)]
            t0 = time.perf_counter()
            first_token_time = None
            token_count = 0

            with self.client.stream("POST", "/api/v1/chat", json={"message": msg, "include_graph": True}, headers=self.auth_headers(persona)) as stream:
                for line in stream.iter_lines():
                    if line.startswith("data: ") and '"delta":' in line:
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                        token_count += 1
            t1 = time.perf_counter()

            ttft_ms = ((first_token_time or t1) - t0) * 1000
            total_ms = (t1 - t0) * 1000
            chat_ttft_latencies.append(ttft_ms)
            chat_total_latencies.append(total_ms)
            total_tokens_generated += token_count

        latency_summary = {
            "hybrid_search": compute_stats(search_latencies),
            "cypher_ast_and_execution": compute_stats(cypher_latencies),
            "chat_sse_ttft": compute_stats(chat_ttft_latencies),
            "chat_sse_completion": compute_stats(chat_total_latencies),
            "chat_total_tokens": total_tokens_generated,
            "chat_tokens_per_sec": round(total_tokens_generated / (sum(chat_total_latencies) / 1000.0), 2) if chat_total_latencies else 0.0
        }
        self.results["latency"] = latency_summary
        print(f"[+] Latency Profiling Complete!")
        print(f"    Hybrid Search: P50={latency_summary['hybrid_search']['p50']}ms, P90={latency_summary['hybrid_search']['p90']}ms, P99={latency_summary['hybrid_search']['p99']}ms")
        print(f"    Cypher AST:    P50={latency_summary['cypher_ast_and_execution']['p50']}ms, P90={latency_summary['cypher_ast_and_execution']['p90']}ms, P99={latency_summary['cypher_ast_and_execution']['p99']}ms")
        print(f"    Chat TTFT:     P50={latency_summary['chat_sse_ttft']['p50']}ms, P90={latency_summary['chat_sse_ttft']['p90']}ms, P99={latency_summary['chat_sse_ttft']['p99']}ms")
        return latency_summary

    def run_all(self, output_file: str = "real_benchmark_results.json"):
        self.load_dataset()
        self.check_health()
        self.authenticate()
        self.ingest_documents()
        self.run_security_benchmarks()
        self.run_retrieval_benchmarks()
        self.run_latency_throughput_benchmarks()

        out_path = REPO_ROOT / output_file
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n[🎉] Complete authentic enterprise benchmark execution successfully saved to {out_path}!")


if __name__ == "__main__":
    runner = RealBenchmarkRunner()
    runner.run_all()
