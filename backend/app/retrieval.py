"""Sparse TF-IDF cosine, lexical and bounded graph retrieval with reciprocal rank fusion."""
from collections import Counter
import math
import re

LEET_MAP = {
    '@': 'a',
    '4': 'a',
    '3': 'e',
    '1': 'i',
    '0': 'o',
    '5': 's',
    '7': 't',
}

def terms(text):
    raw_tokens = re.findall(r"[a-z0-9@$]+", text.lower())
    results = []
    for tok in raw_tokens:
        sub_words = re.findall(r"[a-z0-9]+", tok)
        results.extend(sub_words)
        is_pure_num = tok.isdigit() or (tok.startswith("$") and tok[1:].replace(".", "", 1).isdigit())
        if not is_pure_num and any(c in tok for c in LEET_MAP):
            decoded = tok.lstrip("$")
            for k, v in LEET_MAP.items():
                decoded = decoded.replace(k, v)
            for dw in re.findall(r"[a-z0-9]+", decoded):
                if dw not in results:
                    results.append(dw)
    return results

def levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev[j + 1] + 1
            deletions = curr[j] + 1
            substitutions = prev[j] + (c1 != c2)
            curr.append(min(insertions, deletions, substitutions))
        prev = curr
    return prev[-1]

STOPWORDS = {"a", "an", "the", "what", "which", "who", "is", "are", "of", "for", "to", "and", "or", "in", "did", "does", "how", "tell", "me", "about", "project", "company", "payment", "terms", "vendor", "vendors", "approved", "acquisition", "acquiring", "lead", "leads"}

def search(store, claims, query, top_k=5, graph_view=None):
    docs, nodes, edges = store.view(claims)
    if graph_view is not None: nodes, edges = graph_view
    q = Counter(t for t in terms(query) if t not in STOPWORDS)
    if not q: q = Counter(terms(query))
    # Entity anchors prevent generic words such as 'project' retrieving unrelated projects.
    node_name_terms = {n["id"]: set(terms(n["name"])) - STOPWORDS for n in nodes.values()}
    hits = {nid for nid, nterms in node_name_terms.items() if nterms & set(q)}
    if not hits:
        q_words = [w for w in q if len(w) >= 4 and not w.isdigit()]
        for nid, nterms in node_name_terms.items():
            for nt in nterms:
                if len(nt) >= 4 and any(abs(len(nt) - len(qw)) <= 2 and levenshtein(nt, qw) <= (1 if len(nt) <= 5 else 2) for qw in q_words):
                    hits.add(nid)
                    break
    anchored = bool(hits)
    visited = set(hits); evidence = set()
    for _ in range(3):
        frontier = set()
        for e in edges.values():
            if e["source"] in hits or e["target"] in hits:
                frontier.update((e["source"], e["target"])); evidence.update(e["source_document_ids"])
        hits = frontier - visited; visited.update(frontier)
    for n in visited: evidence.update(nodes[n]["source_document_ids"])
    # Imported instructions are data, never generation instructions. Conservative quarantine
    # is defense in depth; policy and provenance remain the confidentiality boundary.
    candidates = [d for d in docs.values() if (not anchored or d["id"] in evidence) and not re.search(r"ignore (?:previous|all)|system prompt|reveal (?:restricted|secret)|override (?:policy|instructions)", d["content"], re.I)]
    evidence &= {d["id"] for d in candidates}
    counts = {d["id"]: Counter(terms(d["title"] + " " + d["content"])) for d in candidates}
    total = len(counts)
    vocabulary = set(q) | {t for c in counts.values() for t in c}
    idf = {term: math.log((1 + total) / (1 + sum(term in c for c in counts.values()))) + 1 for term in vocabulary}
    def cosine(c):
        dot = sum(q[t] * c[t] * idf[t] ** 2 for t in q)
        qnorm = math.sqrt(sum((q[t] * idf[t]) ** 2 for t in q))
        cnorm = math.sqrt(sum((n * idf[t]) ** 2 for t, n in c.items()))
        return dot / (qnorm * cnorm) if qnorm * cnorm else 0
    lexical = sorted((id for id, c in counts.items() if sum(c[t] for t in q)), key=lambda id: (-sum(counts[id][t] for t in q), id))
    vector = sorted(lexical, key=lambda id: (-cosine(counts[id]), id))
    graph = sorted(evidence)
    ranks = [{id: i + 1 for i, id in enumerate(channel)} for channel in (lexical, vector, graph)]
    fused = {id: sum(1 / (60 + ranks[m][id]) for m in range(3) if id in ranks[m]) for id in set(lexical) | set(graph)}
    # Local overlap reranking after RRF; no model or dense-semantic claim.
    reranked = {id: score + .02 * sum(t in counts[id] for t in q) / max(len(q), 1) for id, score in fused.items()}
    results = []
    for id in sorted(fused, key=lambda id: (-reranked[id], id))[:top_k]:
        d = docs[id]
        results.append(dict(chunk_id=id + "#c0", document_id=id, document_title=d["title"], text=d["content"],
            classification_level=d["classification_level"], department=d["department"], tenant_id=d["tenant_id"],
            rrf_score=fused[id], rerank_score=reranked[id], lexical_rank=ranks[0].get(id), semantic_rank=ranks[1].get(id), graph_rank=ranks[2].get(id),
            content_hash=d["content_hash"]))
    return results

def graph_payload(store, claims, entity_id=None, max_depth=2, document_ids=None, graph_view=None):
    _, nodes, edges = store.view(claims)
    if graph_view is not None: nodes, edges = graph_view
    if document_ids is not None:
        evidence = set(document_ids)
        edges = {id: e for id, e in edges.items() if set(e["source_document_ids"]) <= evidence}
        endpoints = {v for e in edges.values() for v in (e["source"], e["target"])}
        nodes = {id: n for id, n in nodes.items() if id in endpoints or set(n["source_document_ids"]) <= evidence}
    if entity_id:
        keep = {entity_id} & nodes.keys(); frontier = set(keep)
        for _ in range(max_depth):
            nxt = {v for e in edges.values() if e["source"] in frontier or e["target"] in frontier for v in (e["source"], e["target"])}
            frontier = nxt - keep; keep.update(nxt)
        nodes = {id: n for id, n in nodes.items() if id in keep}
    nodes = dict(list(nodes.items())[:100])
    edges = {id: e for id, e in edges.items() if e["source"] in nodes and e["target"] in nodes}
    return {"elements": {"nodes": [{"data": dict(id=n["id"], label=n["name"], type=n["type"], classification_level=n["classification_level"], department=n["department"], tenant_id=n["tenant_id"], source_document_ids=n["source_document_ids"])} for n in nodes.values()],
        "edges": [{"data": dict(id=e["id"], source=e["source"], target=e["target"], label=e["type"], classification_level=e["classification_level"], source_document_ids=e["source_document_ids"])} for e in list(edges.values())[:200]]}}


def secure_paths(store, claims, question, executor=None, plans=None):
    """Compile a fixed two-hop graph plan for mentioned persons, then run policy view."""
    from .cypher import parse, execute_local
    docs, nodes, edges = store.view(claims)
    paths = []
    for person in nodes.values():
        if person["type"] != "Person" or not (set(terms(person["name"])) & set(terms(question))):
            continue
        plan = parse("MATCH (a:Person)-[r:LEADS]->(p:Project)-[s:ACQUIRES]->(c:Company) WHERE a.name = $person RETURN a.name, p.name, c.name, r, s", {"person": person["name"]}, claims)
        plan.parameters["auth_document_ids"] = list(docs)
        if plans is not None: plans.append(plan.transformed)
        paths.extend(executor(plan, claims) if executor else execute_local(plan, nodes, edges))
    return paths
