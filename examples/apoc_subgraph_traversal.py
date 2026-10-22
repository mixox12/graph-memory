#!/usr/bin/env python3
"""
examples/apoc_subgraph_traversal.py
===================================
Demonstrates APOC subgraph expansion and deep neighborhood traversal
using Graph Memory client against local Neo4j.
"""

from graph_memory.client import GraphRagClient


def main():
    client = GraphRagClient(http_uri="http://127.0.0.1:7474")

    print("🔍 Testing APOC plugin availability...")
    proc_check = client.run_cypher(
        "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.path' RETURN name LIMIT 5"
    )
    if not proc_check:
        print("⚠️ APOC procedures not detected or restricted.")
        return

    print(f"✅ Found {len(proc_check)} APOC path procedures. Sample:")
    for row in proc_check:
        print(f"  - {row['name']}")

    # 1. Expand subgraph around a top entity
    print("\n🕸️ Expanding 2-hop neighborhood using apoc.path.subgraphAll...")
    cypher = """
    MATCH (root:Entity)
    WHERE root.degree > 15
    WITH root LIMIT 1
    CALL apoc.path.subgraphAll(root, {
        maxLevel: 2,
        relationshipFilter: 'CALLS|IMPORTS|CONTAINS'
    })
    YIELD nodes, relationships
    RETURN root.name AS rootName,
           size(nodes) AS subNodesCount,
           size(relationships) AS subRelsCount
    """
    try:
        res = client.run_cypher(cypher)
        if res:
            row = res[0]
            print(f"Root: {row.get('rootName')}")
            print(f"Subgraph Nodes: {row.get('subNodesCount')}")
            print(f"Subgraph Relationships: {row.get('subRelsCount')}")
        else:
            print("No high-degree nodes found for subgraph expansion.")
    except Exception as e:
        print(f"APOC expansion query notice: {e}")


if __name__ == "__main__":
    main()
