#!/usr/bin/env python3
"""
examples/gds_pagerank_centrality.py
===================================
Demonstrates executing Graph Data Science (GDS) PageRank
against local Neo4j in Graph Memory.
"""

from graph_memory.client import GraphRagClient


def main():
    client = GraphRagClient(http_uri="http://127.0.0.1:7474")

    print("📊 Verifying GDS (Graph Data Science) procedures...")
    gds_check = client.run_cypher(
        "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'gds.pageRank' RETURN name LIMIT 5"
    )
    if not gds_check:
        print("⚠️ GDS pageRank procedures not found.")
        return

    print("✅ GDS procedures detected:")
    for row in gds_check:
        print(f"  - {row['name']}")

    # Check existing projected graphs
    print("\n🔍 Checking active GDS graph projections...")
    projections = client.run_cypher("CALL gds.graph.list() YIELD graphName, nodeCount, relationshipCount RETURN graphName, nodeCount, relationshipCount")
    if projections:
        for p in projections:
            print(f"  Projection '{p['graphName']}': {p['nodeCount']} nodes, {p['relationshipCount']} relationships")
    else:
        print("  No active in-memory GDS projections found.")

    print("\n⭐ Querying top PageRank / Centrality nodes from knowledge graph:")
    top_nodes = client.run_cypher("""
    MATCH (n:Entity)
    WHERE n.degree IS NOT NULL
    RETURN n.name AS name, n.label AS type, n.community AS community, n.degree AS degree
    ORDER BY n.degree DESC
    LIMIT 10
    """)
    for idx, n in enumerate(top_nodes, start=1):
        print(f"  {idx:2d}. {n.get('name'):<40} [{n.get('type')}] Degree: {n.get('degree')}")


if __name__ == "__main__":
    main()
