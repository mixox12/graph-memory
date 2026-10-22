from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client import GraphRagClient, DEFAULT_HTTP_URI, DEFAULT_USER, DEFAULT_PASSWORD
from .engine import resolve_default_graph_json

BATCH_SIZE = 500


def sync_graph_to_neo4j(
    graph_path: Path,
    http_uri: str = DEFAULT_HTTP_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    batch_size: int = BATCH_SIZE,
) -> Dict[str, Any]:
    """Sync Graphify AST knowledge graph JSON into Neo4j in high-speed batch UNWIND transactions."""
    if not graph_path.exists():
        raise FileNotFoundError(f"Graph file '{graph_path}' not found.")

    start_time = time.time()
    client = GraphRagClient(http_uri=http_uri, user=user, password=password)

    print(f"📖 Reading Graphify graph: {graph_path}")
    with open(graph_path, "r", encoding="utf-8") as f:
        graph_data = json.load(f)

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", []) or graph_data.get("links", [])
    print(f"Loaded {len(nodes):,} nodes and {len(edges):,} edges.")

    # 1. Ensure Schema Constraints & Indexes
    print("⚙️ Ensuring schema indexes...")
    try:
        client.run_cypher("CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
        client.run_cypher("CREATE INDEX entity_name_index IF NOT EXISTS FOR (e:Entity) ON (e.name)")
        client.run_cypher("CREATE INDEX entity_project_index IF NOT EXISTS FOR (e:Entity) ON (e.project)")
        client.run_cypher("CREATE INDEX entity_community_index IF NOT EXISTS FOR (e:Entity) ON (e.community)")
    except Exception as e:
        print(f"Index notice: {e}")

    # 2. Ingest Nodes in Batches
    print(f"🚀 Ingesting {len(nodes):,} nodes in batches of {batch_size}...")
    node_query = """
    UNWIND $batch AS item
    MERGE (n:Entity {id: item.id})
    SET n.name = coalesce(item.name, item.id),
        n.label = coalesce(item.label, 'Entity'),
        n.file = coalesce(item.file, item.source_file, ''),
        n.source_file = coalesce(item.source_file, item.file, ''),
        n.source_location = coalesce(item.source_location, ''),
        n.file_type = coalesce(item.file_type, 'code'),
        n.project = coalesce(item.project, 'default'),
        n.community = item.community,
        n.community_name = coalesce(item.community_name, ''),
        n.degree = item.degree,
        n.description = coalesce(item.description, '')
    """
    for i in range(0, len(nodes), batch_size):
        batch = []
        for n in nodes[i : i + batch_size]:
            nid = n.get("id") or n.get("name")
            if not nid:
                continue
            batch.append({
                "id": str(nid),
                "name": str(n.get("name") or n.get("label") or nid),
                "label": str(n.get("label") or n.get("name") or "Entity"),
                "file": str(n.get("file") or n.get("source_file") or ""),
                "source_file": str(n.get("source_file") or n.get("file") or ""),
                "source_location": str(n.get("source_location") or ""),
                "file_type": str(n.get("file_type") or "code"),
                "project": str(n.get("project") or "default"),
                "community": n.get("community"),
                "community_name": str(n.get("community_name") or ""),
                "degree": n.get("degree") or 0,
                "description": str(n.get("description") or n.get("summary") or ""),
            })
        if batch:
            client.run_cypher(node_query, {"batch": batch})
            if (i // batch_size) % 10 == 0 or (i + batch_size) >= len(nodes):
                print(f"  • Synced {min(i + batch_size, len(nodes)):,}/{len(nodes):,} nodes...")

    # 3. Ingest Edges in Batches
    print(f"🔗 Ingesting {len(edges):,} relationships in batches of {batch_size}...")
    edge_query = """
    UNWIND $batch AS edge
    MERGE (s:Entity {id: edge.source})
    MERGE (t:Entity {id: edge.target})
    MERGE (s)-[r:RELATION {type: edge.relation}]->(t)
    SET r.weight = coalesce(edge.weight, 1.0),
        r.source_file = coalesce(edge.source_file, ''),
        r.source_location = coalesce(edge.source_location, ''),
        r.project = coalesce(edge.project, '')
    """
    for i in range(0, len(edges), batch_size):
        batch = []
        for e in edges[i : i + batch_size]:
            s = e.get("source")
            t = e.get("target")
            if not s or not t:
                continue
            batch.append({
                "source": str(s),
                "target": str(t),
                "relation": str(e.get("relation") or e.get("type") or "RELATES_TO"),
                "weight": float(e.get("weight") or 1.0),
                "source_file": str(e.get("source_file") or ""),
                "source_location": str(e.get("source_location") or ""),
                "project": str(e.get("project") or ""),
            })
        if batch:
            client.run_cypher(edge_query, {"batch": batch})
            if (i // batch_size) % 20 == 0 or (i + batch_size) >= len(edges):
                print(f"  • Synced {min(i + batch_size, len(edges)):,}/{len(edges):,} relationships...")

    elapsed = time.time() - start_time
    print(f"✨ Successfully synced into Neo4j in {elapsed:.2f}s!")
    return {
        "ok": True,
        "nodesSynced": len(nodes),
        "edgesSynced": len(edges),
        "elapsedSeconds": elapsed,
    }


def main():
    parser = argparse.ArgumentParser(description="Sync Graphify AST knowledge graph into Neo4j")
    parser.add_argument("--graph", type=Path, default=resolve_default_graph_json(), help="Path to graph.json")
    parser.add_argument("--http-uri", default=DEFAULT_HTTP_URI, help="Neo4j HTTP endpoint (e.g. http://127.0.0.1:7474)")
    parser.add_argument("--user", default=DEFAULT_USER, help="Neo4j username")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Neo4j password")
    args = parser.parse_args()

    sync_graph_to_neo4j(
        graph_path=args.graph,
        http_uri=args.http_uri,
        user=args.user,
        password=args.password,
    )


if __name__ == "__main__":
    main()

sync_graphify_to_neo4j = sync_graph_to_neo4j

