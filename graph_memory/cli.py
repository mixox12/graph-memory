#!/usr/bin/env python3
"""
graph_memory.cli
================
Unified Command Line Interface for Graph Memory & Neo4j Graph RAG Engine.

Commands:
    stats          Show graph statistics (node counts, edges, god nodes, communities)
    query          Execute hybrid graph & semantic search
    path           Find the shortest path between two nodes
    explain        Deep-dive into a node's dependencies and callers
    pagerank       Display PageRank / degree centrality scores
    communities    Detect and list Louvain communities
    sync           Sync a graphify JSON file into Neo4j
    build-master   Scan codebases, extract ASTs, and build unified master graph
    cypher         Execute a raw Cypher query against local Neo4j
    ui             Launch the hardened local Web UI Studio
    mcp            Run the Model Context Protocol (MCP) server on stdio
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from graph_memory import __version__
from graph_memory.client import GraphRagClient
from graph_memory.engine import GraphRagEngine
from graph_memory.sync import sync_graph_to_neo4j
from graph_memory.builder import build_master_graph
from graph_memory.server import start_server


def get_default_engine(args: argparse.Namespace) -> GraphRagEngine:
    http_uri = getattr(args, "http_url", "http://127.0.0.1:7474")
    user = getattr(args, "user", "neo4j")
    password = getattr(args, "password", "")
    return GraphRagEngine(http_uri=http_uri, user=user, password=password)


def cmd_stats(args: argparse.Namespace) -> int:
    engine = get_default_engine(args)
    stats = engine.get_stats()

    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    neo = stats.get("neo4j", {})
    loc = stats.get("localGraph", {})

    print("=" * 65)
    print(f"📊 Graph Memory Knowledge Engine (v{__version__})")
    print("=" * 65)
    print(f"Neo4j Status:       {'🟢 ONLINE' if neo.get('online') else '🔴 OFFLINE'}")
    print(f"Neo4j Total Nodes:  {neo.get('totalNodes', 0):,}")
    print(f"Neo4j Total Edges:  {neo.get('totalRelationships', 0):,}")
    plugins = neo.get("plugins", {})
    p_status = [f"{p.upper()} ({info.get('proceduresCount', 0)})" for p, info in plugins.items() if info.get("active")]
    print(f"Neo4j Plugins:      {', '.join(p_status) if p_status else 'None detected'}")
    print("-" * 65)
    print(f"Local Graph Path:   {loc.get('path', 'N/A')}")
    print(f"Local Total Nodes:  {loc.get('totalNodes', 0):,}")
    print(f"Local Total Edges:  {loc.get('totalEdges', 0):,}")
    print("-" * 65)
    god_nodes = loc.get("godNodes", []) or stats.get("god_nodes", [])
    if god_nodes:
        print("Top God Nodes (Highest Degree Centrality):")
        for idx, gn in enumerate(god_nodes[:10], start=1):
            name = gn.get("name") or gn.get("id")
            deg = gn.get("degree", 0)
            comm = gn.get("community", 0)
            print(f"  {idx:2d}. {name:<42} (degree: {deg:3d}, cluster: {comm})")
    print("=" * 65)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    engine = get_default_engine(args)
    res = engine.query(question=args.query, top_k=args.limit)

    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    print("=" * 70)
    print(f"🔍 Hybrid Graph RAG Context for: '{args.query}'")
    print("=" * 70)
    print(res.get("contextBlock", ""))
    print("=" * 70)
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    engine = get_default_engine(args)
    res = engine.shortest_path(args.source, args.target)

    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    if not res.get("found"):
        print(f"❌ No path found between '{args.source}' and '{args.target}'.")
        return 1

    nodes = res.get("nodes", [])
    rels = res.get("rels", [])
    print("=" * 70)
    print(f"📍 Shortest Path ({res.get('source', 'engine')}): '{args.source}' ➔ '{args.target}' ({res.get('hops', 0)} hops)")
    print("=" * 70)
    for i in range(len(rels)):
        curr_node = nodes[i]
        next_node = nodes[i + 1] if i + 1 < len(nodes) else "..."
        rel_type = rels[i]
        print(f"  ({curr_node}) ➔ [:{rel_type}] ➔ ({next_node})")
    print("=" * 70)
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    engine = get_default_engine(args)
    res = engine.explain_node(args.node_id)

    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    if not res.get("found"):
        print(f"❌ Entity '{args.node_id}' not found in knowledge graph.")
        return 1

    print("=" * 70)
    print(f"📖 Node Deep-Dive: {res.get('name', res.get('id'))} (Source: {res.get('source', 'engine')})")
    print("=" * 70)
    print(f"Labels:     {', '.join(res.get('labels', []))}")
    if res.get("community") is not None:
        print(f"Community:  Cluster #{res.get('community')}")

    outgoing = res.get("outgoing", [])
    incoming = res.get("incoming", [])

    print(f"\n📦 Outbound Connections ({len(outgoing)}):")
    for dep in outgoing[:12]:
        print(f"  ➔ [:{dep.get('rel')}] {dep.get('target')}")

    print(f"\n👥 Inbound Connections ({len(incoming)}):")
    for cal in incoming[:12]:
        print(f"  ⬅ [:{cal.get('rel')}] {cal.get('source')}")
    print("=" * 70)
    return 0


def cmd_pagerank(args: argparse.Namespace) -> int:
    engine = get_default_engine(args)
    scores = engine.get_pagerank(limit=args.top_k)

    if args.json:
        print(json.dumps(scores, indent=2))
        return 0

    print("=" * 70)
    print(f"⭐ Top Centrality Nodes ({len(scores)})")
    print("=" * 70)
    for idx, item in enumerate(scores, start=1):
        name = item.get("name") or item.get("id")
        deg = item.get("degree", 0)
        comm = item.get("community", 0)
        labels = item.get("labels", [])
        lbl_str = f"[{labels[0]}]" if labels else ""
        print(f"  {idx:2d}. {name:<42} {lbl_str:<12} (degree: {deg:3d}, cluster: {comm})")
    print("=" * 70)
    return 0


def cmd_communities(args: argparse.Namespace) -> int:
    engine = get_default_engine(args)
    comms = engine.get_communities(limit=args.limit)

    if args.json:
        print(json.dumps(comms, indent=2))
        return 0

    print("=" * 70)
    print(f"🏘️ Louvain Community Clusters ({len(comms)})")
    print("=" * 70)
    for comm in comms:
        cid = comm.get("communityId")
        size = comm.get("memberCount", 0)
        members = comm.get("topMembers", [])
        print(f"  Cluster #{cid:2d} ({size:4d} entities): {', '.join(members[:5])}")
    print("=" * 70)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    p = Path(args.file)
    if not p.is_file():
        print(f"❌ File not found: {args.file}")
        return 1

    print(f"🔄 Syncing '{args.file}' to Neo4j...")
    stats = sync_graph_to_neo4j(
        graph_path=p,
        http_uri=args.http_url,
        user=args.user,
        password=args.password,
        batch_size=args.batch_size,
    )
    print(f"✅ Sync complete: {stats}")
    return 0


def cmd_build_master(args: argparse.Namespace) -> int:
    print(f"🏗️ Building Master Knowledge Graph to {args.output}...")
    res = build_master_graph(
        output_path=Path(args.output),
        sync_to_neo4j=args.sync,
        http_uri=args.http_url,
        user=args.user,
        password=args.password,
    )
    print(f"✅ Master graph complete: {res}")
    return 0


def cmd_cypher(args: argparse.Namespace) -> int:
    client = GraphRagClient(
        http_uri=args.http_url,
        user=args.user,
        password=args.password,
    )
    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except Exception as e:
            print(f"❌ Invalid JSON params: {e}")
            return 1

    try:
        data = client.run_cypher(args.query, params=params)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"Rows returned: {len(data)}")
            for idx, row in enumerate(data[:30], start=1):
                print(f"[{idx}] {json.dumps(row)}")
            if len(data) > 30:
                print(f"... and {len(data) - 30} more rows.")
        return 0
    except Exception as e:
        print(f"❌ Cypher execution failed: {e}")
        return 1


def cmd_ui(args: argparse.Namespace) -> int:
    start_server(port=args.port, open_browser=not args.no_open)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from graph_memory.mcp_server import run_mcp_server
    return run_mcp_server()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-memory",
        description="Graph Memory: Production Hybrid Graph RAG, Neo4j, APOC/GDS & AST Knowledge Engine",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    # Global connection args
    parser.add_argument("--http-url", default=os.getenv("NEO4J_HTTP_URI", "http://127.0.0.1:7474"), help="Neo4j HTTP URI")
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"), help="Neo4j Username")
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""), help="Neo4j Password")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # stats
    sub_stats = subparsers.add_parser("stats", help="Show graph statistics & top god nodes")
    sub_stats.set_defaults(func=cmd_stats)

    # query
    sub_query = subparsers.add_parser("query", help="Execute hybrid semantic & graph search")
    sub_query.add_argument("query", help="Text search query")
    sub_query.add_argument("--limit", type=int, default=8, help="Max seed nodes")
    sub_query.set_defaults(func=cmd_query)

    # path
    sub_path = subparsers.add_parser("path", help="Find shortest path between two nodes")
    sub_path.add_argument("source", help="Source node ID or name")
    sub_path.add_argument("target", help="Target node ID or name")
    sub_path.set_defaults(func=cmd_path)

    # explain
    sub_explain = subparsers.add_parser("explain", help="Deep-dive into a node's dependencies and callers")
    sub_explain.add_argument("node_id", help="Node ID or name to explain")
    sub_explain.set_defaults(func=cmd_explain)

    # pagerank
    sub_pr = subparsers.add_parser("pagerank", help="Get PageRank centrality scores")
    sub_pr.add_argument("--top-k", type=int, default=15, help="Number of nodes to return")
    sub_pr.set_defaults(func=cmd_pagerank)

    # communities
    sub_comm = subparsers.add_parser("communities", help="Detect and list Louvain communities")
    sub_comm.add_argument("--limit", type=int, default=20, help="Max communities to list")
    sub_comm.set_defaults(func=cmd_communities)

    # sync
    sub_sync = subparsers.add_parser("sync", help="Sync graphify JSON into Neo4j")
    sub_sync.add_argument("file", help="Path to graph.json")
    sub_sync.add_argument("--batch-size", type=int, default=500, help="Batch size")
    sub_sync.set_defaults(func=cmd_sync)

    # build-master
    sub_build = subparsers.add_parser("build-master", help="Build master knowledge graph from workspace roots")
    sub_build.add_argument("-o", "--output", default=str(Path.home() / "graphify-out" / "graph.json"), help="Output JSON path")
    sub_build.add_argument("--sync", action="store_true", help="Sync to Neo4j automatically")
    sub_build.set_defaults(func=cmd_build_master)

    # cypher
    sub_cypher = subparsers.add_parser("cypher", help="Execute arbitrary Cypher query")
    sub_cypher.add_argument("query", help="Cypher query string")
    sub_cypher.add_argument("--params", help="JSON string of query parameters")
    sub_cypher.set_defaults(func=cmd_cypher)

    # ui
    sub_ui = subparsers.add_parser("ui", help="Launch hardened local Web UI Studio")
    sub_ui.add_argument("--port", type=int, default=8765, help="Port to listen on")
    sub_ui.add_argument("--no-open", action="store_true", help="Do not open browser")
    sub_ui.set_defaults(func=cmd_ui)

    # mcp
    sub_mcp = subparsers.add_parser("mcp", help="Run the Model Context Protocol (MCP) server over stdio")
    sub_mcp.set_defaults(func=cmd_mcp)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        ret = args.func(args)
        sys.exit(ret if isinstance(ret, int) else 0)
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(130)
    except Exception as exc:
        print(f"❌ Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
