from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .client import GraphRagClient, DEFAULT_BOLT_URI, DEFAULT_HTTP_URI, DEFAULT_USER, DEFAULT_PASSWORD

# Default fallback search for graphify graph.json
def resolve_default_graph_json() -> Path:
    env_path = os.getenv("GRAPH_MEMORY_JSON") or os.getenv("RELAY_GRAPH_JSON")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    candidates = [
        Path("/Users/hosamtaha/graphify-out/graph.json"),
        Path("/Users/hosamtaha/relay-prod/graphify-out/graph.json"),
        Path.cwd() / "graphify-out" / "graph.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


class GraphRagEngine:
    """Core analytical and retrieval engine fusing Neo4j, APOC, GDS, GenAI, and Graphify."""

    def __init__(
        self,
        http_uri: Any = DEFAULT_HTTP_URI,
        user: str = DEFAULT_USER,
        password: str = DEFAULT_PASSWORD,
        graph_json_path: Optional[Path] = None,
    ):
        if isinstance(http_uri, GraphRagClient) or hasattr(http_uri, "run_cypher"):
            self.client = http_uri
            self.http_uri = getattr(http_uri, "http_uri", DEFAULT_HTTP_URI)
            self.user = getattr(http_uri, "user", user)
            self.password = getattr(http_uri, "password", password)
        else:
            self.http_uri = str(http_uri).rstrip("/")
            self.user = user
            self.password = password
            self.client = GraphRagClient(http_uri=self.http_uri, user=user, password=password)

        self.graph_json_path = graph_json_path or resolve_default_graph_json()
        self.local_nodes: Dict[str, Dict[str, Any]] = {}
        self.local_edges: List[Dict[str, Any]] = []
        self._load_local_graph()


    def _load_local_graph(self):
        if not self.graph_json_path.exists():
            return
        try:
            with open(self.graph_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for n in data.get("nodes", []):
                nid = str(n.get("id") or n.get("name") or "")
                if nid:
                    self.local_nodes[nid] = n
            self.local_edges = data.get("edges", []) or data.get("links", [])
        except Exception as e:
            sys.stderr.write(f"[graph_memory] Warning loading {self.graph_json_path}: {e}\n")

    def run_cypher(self, statement: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        try:
            return self.client.run_cypher(statement, params)
        except Exception:
            return []

    def get_stats(self) -> Dict[str, Any]:
        node_res = self.run_cypher("MATCH (n) RETURN count(n) AS nodeCount")
        rel_res = self.run_cypher("MATCH ()-[r]->() RETURN count(r) AS relCount")
        label_res = self.run_cypher("CALL db.labels() YIELD label RETURN label")

        # Plugin procedure counts
        apoc_res = self.run_cypher("SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc' RETURN count(name) AS c")
        gds_res = self.run_cypher("SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'gds' RETURN count(name) AS c")
        genai_res = self.run_cypher("SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'genai' RETURN count(name) AS c")
        bloom_res = self.run_cypher("SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'bloom' RETURN count(name) AS c")

        god_nodes = [
            {"id": n.get("id"), "name": n.get("name"), "degree": n.get("degree", 0), "community": n.get("community"), "file": n.get("file")}
            for n in self.local_nodes.values()
            if isinstance(n.get("degree"), (int, float)) and n.get("degree", 0) > 20
        ]
        god_nodes.sort(key=lambda x: x["degree"], reverse=True)

        total_nodes = node_res[0]["nodeCount"] if node_res else len(self.local_nodes)
        total_rels = rel_res[0]["relCount"] if rel_res else len(self.local_edges)

        return {
            "ok": True,
            "node_count": total_nodes,
            "rel_count": total_rels,
            "community_count": len(self.get_communities(limit=100)),
            "status": "online" if node_res else "local_only",
            "god_nodes": god_nodes[:15],
            "engine": "Graphify + Neo4j Hybrid RAG Memory",
            "neo4j": {
                "online": bool(node_res),
                "boltUri": DEFAULT_BOLT_URI,
                "httpUri": self.http_uri,
                "totalNodes": node_res[0]["nodeCount"] if node_res else 0,
                "totalRelationships": rel_res[0]["relCount"] if rel_res else 0,
                "labels": [r["label"] for r in label_res] if label_res else [],
                "plugins": {
                    "apoc": {"active": bool(apoc_res and apoc_res[0]["c"] > 0), "proceduresCount": apoc_res[0]["c"] if apoc_res else 0},
                    "gds": {"active": bool(gds_res and gds_res[0]["c"] > 0), "proceduresCount": gds_res[0]["c"] if gds_res else 0},
                    "genai": {"active": bool(genai_res and genai_res[0]["c"] > 0), "proceduresCount": genai_res[0]["c"] if genai_res else 0},
                    "bloom": {"active": bool(bloom_res and bloom_res[0]["c"] > 0), "proceduresCount": bloom_res[0]["c"] if bloom_res else 0},
                },
            },
            "localGraph": {
                "online": bool(self.local_nodes),
                "path": str(self.graph_json_path),
                "totalNodes": len(self.local_nodes),
                "totalEdges": len(self.local_edges),
                "godNodes": god_nodes[:12],
            },
        }


    def shortest_path(self, from_id: str, to_id: str) -> Dict[str, Any]:
        query = """
        MATCH (a), (b)
        WHERE (a.id = $from_id OR a.name = $from_id) AND (b.id = $to_id OR b.name = $to_id)
        MATCH p = shortestPath((a)-[*..6]-(b))
        RETURN [n in nodes(p) | coalesce(n.name, n.id)] AS nodes,
               [r in relationships(p) | type(r)] AS rels,
               length(p) AS hops
        LIMIT 1
        """
        rows = self.run_cypher(query, {"from_id": from_id, "to_id": to_id})
        if rows:
            return {"found": True, "source": "neo4j", **rows[0]}

        # Local BFS fallback
        queue = [[from_id]]
        visited = {from_id}
        adj: Dict[str, List[Tuple[str, str]]] = {}
        for e in self.local_edges:
            s, t, r = str(e.get("source")), str(e.get("target")), str(e.get("relation") or "RELATION")
            adj.setdefault(s, []).append((t, r))
            adj.setdefault(t, []).append((s, r))

        while queue:
            path = queue.pop(0)
            curr = path[-1]
            if curr == to_id:
                rels = []
                for i in range(len(path) - 1):
                    s_node, t_node = path[i], path[i + 1]
                    r_type = next((r for tgt, r in adj.get(s_node, []) if tgt == t_node), "RELATION")
                    rels.append(r_type)
                return {
                    "found": True,
                    "source": "local",
                    "nodes": [self.local_nodes.get(nid, {}).get("name", nid) for nid in path],
                    "rels": rels,
                    "hops": len(path) - 1,
                }
            if len(path) >= 6:
                continue
            for neighbor, _ in adj.get(curr, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return {"found": False, "hops": 0, "nodes": [], "rels": []}

    def explain_node(self, node_id: str) -> Dict[str, Any]:
        query = """
        MATCH (n)
        WHERE n.id = $node_id OR n.name = $node_id
        OPTIONAL MATCH (n)-[r]->(out)
        OPTIONAL MATCH (in)-[r_in]->(n)
        RETURN n.id AS id, coalesce(n.name, n.id) AS name, labels(n) AS labels, n.community AS community,
               collect(DISTINCT {rel: type(r), target: coalesce(out.name, out.id)})[0..15] AS outgoing,
               collect(DISTINCT {rel: type(r_in), source: coalesce(in.name, in.id)})[0..15] AS incoming
        LIMIT 1
        """
        rows = self.run_cypher(query, {"node_id": node_id})
        if rows and rows[0].get("id"):
            return {"found": True, "source": "neo4j", **rows[0]}

        if node_id in self.local_nodes:
            n = self.local_nodes[node_id]
            outgoing = [{"rel": e.get("relation", "RELATION"), "target": self.local_nodes.get(e["target"], {}).get("name", e["target"])} for e in self.local_edges if str(e.get("source")) == node_id][:15]
            incoming = [{"rel": e.get("relation", "RELATION"), "source": self.local_nodes.get(e["source"], {}).get("name", e["source"])} for e in self.local_edges if str(e.get("target")) == node_id][:15]
            return {
                "found": True,
                "source": "local",
                "id": node_id,
                "name": n.get("name", node_id),
                "labels": [n.get("label", "Entity")],
                "community": n.get("community"),
                "outgoing": outgoing,
                "incoming": incoming,
            }
        return {"found": False, "id": node_id, "name": node_id, "outgoing": [], "incoming": []}

    def get_pagerank(self, limit: int = 15) -> List[Dict[str, Any]]:
        query = """
        MATCH (n)
        RETURN coalesce(n.name, n.id) AS name,
               labels(n) AS labels,
               coalesce(n.community, 0) AS community,
               count { (n)--() } AS degree
        ORDER BY degree DESC
        LIMIT $limit
        """
        rows = self.run_cypher(query, {"limit": limit})
        if rows:
            return rows

        gods = [
            {"name": n.get("name", nid), "labels": [n.get("label", "Entity")], "community": n.get("community", 0), "degree": n.get("degree", 0)}
            for nid, n in self.local_nodes.items()
        ]
        gods.sort(key=lambda x: x["degree"], reverse=True)
        return gods[:limit]

    def get_communities(self, limit: int = 20) -> List[Dict[str, Any]]:
        query = """
        MATCH (n)
        WHERE n.community IS NOT NULL
        RETURN n.community AS communityId,
               count(n) AS memberCount,
               collect(DISTINCT coalesce(n.name, n.id))[0..5] AS topMembers
        ORDER BY memberCount DESC
        LIMIT $limit
        """
        rows = self.run_cypher(query, {"limit": limit})
        if rows:
            return rows

        comm_map: Dict[int, List[str]] = {}
        for nid, n in self.local_nodes.items():
            cid = n.get("community")
            if cid is not None:
                comm_map.setdefault(cid, []).append(n.get("name", nid))
        res = [
            {"communityId": cid, "memberCount": len(members), "topMembers": members[:5]}
            for cid, members in sorted(comm_map.items(), key=lambda x: len(x[1]), reverse=True)
        ]
        return res[:limit]

    def query(self, question: str, top_k: int = 8) -> Dict[str, Any]:
        terms = [w for w in re.sub(r"[^a-zA-Z0-9_\-\.]", " ", question.lower()).split() if len(w) >= 3 and w not in {"what", "when", "where", "which", "who", "whom", "this", "that", "with", "from", "have", "does", "how"}]

        # 1. Search seed nodes locally
        scored = []
        for nid, node in self.local_nodes.items():
            name = str(node.get("name", "")).lower()
            label = str(node.get("label", "")).lower()
            file = str(node.get("file", "")).lower()
            score = 0
            for t in terms:
                if t == name:
                    score += 10
                elif t in name:
                    score += 4
                if t in label:
                    score += 2
                if t in file:
                    score += 2
            if score > 0:
                scored.append((score, node.get("degree", 0), node))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        seed_nodes = [item[2] for item in scored[:top_k]]

        # 2. Cypher search fallback / augmentation
        if len(seed_nodes) < 5:
            c_query = """
            UNWIND $terms AS term
            MATCH (n)
            WHERE toLower(coalesce(n.name, n.id)) CONTAINS term
            RETURN coalesce(n.name, n.id) AS name, labels(n) AS labels, n.community AS community, count { (n)--() } AS degree
            ORDER BY degree DESC
            LIMIT 8
            """
            cypher_nodes = self.run_cypher(c_query, {"terms": terms})
            for cn in cypher_nodes:
                if not any((s.get("name") or s.get("id")) == cn["name"] for s in seed_nodes):
                    seed_nodes.append(cn)

        # 3. Traverse 1-2 hop relationships
        traversals = []
        seen = set()
        for n in seed_nodes[:5]:
            nid = n.get("id") or n.get("name")
            if not nid:
                continue
            exp = self.explain_node(str(nid))
            for out in exp.get("outgoing", [])[:4]:
                tup = (exp.get("name", nid), out.get("rel"), out.get("target"))
                if tup not in seen and all(tup):
                    seen.add(tup)
                    traversals.append({"source": tup[0], "relation": tup[1], "target": tup[2]})

        # 4. Synthesize Markdown context block
        lines = [
            "### 🕸️ Graph RAG Knowledge Context (Neo4j + Graphify)",
            f"**Question:** {question}",
            "",
            f"**Focal Entities ({len(seed_nodes)}):**",
        ]
        for n in seed_nodes:
            name = n.get("name") or n.get("id")
            lbl = n.get("label") or (n.get("labels") and n["labels"][0]) or "Entity"
            deg = n.get("degree", "N/A")
            comm = n.get("community", "N/A")
            fpath = n.get("file", "")
            f_info = f", `{fpath}`" if fpath else ""
            lines.append(f"- **{name}** [{lbl}] (Community {comm}, Degree {deg}{f_info})")

        if traversals:
            lines.append("")
            lines.append("**Knowledge Graph Traversal Relationships:**")
            for t in traversals:
                lines.append(f"- `{t['source']}` ➔ [:{t['relation']}] ➔ `{t['target']}`")

        markdown_context = "\n".join(lines)
        return {
            "ok": True,
            "question": question,
            "seedNodes": seed_nodes,
            "traversals": traversals,
            "contextBlock": markdown_context,
        }

    def get_graph_data(self, limit_nodes: int = 300, limit_edges: int = 600, search: Optional[str] = None) -> Dict[str, Any]:
        nodes_out = []
        edges_out = []
        selected_ids = set()

        if search:
            s_low = search.lower()
            matching_ids = {
                nid for nid, n in self.local_nodes.items()
                if s_low in str(n.get("name", "")).lower() or s_low in str(n.get("label", "")).lower() or s_low in str(n.get("file", "")).lower()
            }
            selected_ids.update(matching_ids)
            for e in self.local_edges:
                src, tgt = str(e.get("source")), str(e.get("target"))
                if src in matching_ids or tgt in matching_ids:
                    selected_ids.add(src)
                    selected_ids.add(tgt)
        else:
            sorted_nodes = sorted(self.local_nodes.values(), key=lambda x: x.get("degree", 0), reverse=True)
            for n in sorted_nodes[:limit_nodes]:
                selected_ids.add(str(n.get("id") or n.get("name")))

        for nid in list(selected_ids)[:limit_nodes]:
            n = self.local_nodes.get(nid)
            if not n:
                continue
            nodes_out.append({
                "id": nid,
                "label": n.get("name") or n.get("label") or nid,
                "title": f"<b>{n.get('name', nid)}</b><br>Type: {n.get('label')}<br>File: {n.get('file', '')}<br>Community: {n.get('community')}",
                "group": n.get("community", 0),
                "value": max(5, int(n.get("degree", 1))),
            })

        for e in self.local_edges:
            src = str(e.get("source"))
            tgt = str(e.get("target"))
            if src in selected_ids and tgt in selected_ids:
                edges_out.append({
                    "from": src,
                    "to": tgt,
                    "label": e.get("relation") or "",
                    "arrows": "to",
                })
                if len(edges_out) >= limit_edges:
                    break

        return {"ok": True, "nodes": nodes_out, "edges": edges_out}

    find_shortest_path = shortest_path
    hybrid_search = query
    get_pagerank_centrality = get_pagerank

