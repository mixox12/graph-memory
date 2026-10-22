#!/usr/bin/env python3
"""
graph_memory.mcp_server
=======================
Stdio Model Context Protocol (MCP) server for Graph Memory.
Provides 3 core tools to LLMs and agents (Claude Code, Gemini Argon, Antigravity):
  1. graph_builder: Multi-workspace AST scanner, graph builder, and Neo4j batch synchronizer
  2. memory_manager: Persistent episodic & semantic memory engine (:Entity:Memory)
  3. rag_retrieval: Hybrid graph & semantic retrieval, path exploration, node deep-dives
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from graph_memory import __version__
from graph_memory.client import GraphRagClient
from graph_memory.engine import GraphRagEngine
from graph_memory.sync import sync_graph_to_neo4j
from graph_memory.builder import build_master_graph

SERVER_NAME = "graph-memory-mcp"
PROTOCOL_VERSION = "2024-11-05"

TOOLS_SPEC = [
    {
        "name": "graph_builder",
        "description": "Build or rebuild the knowledge graph from source workspaces by extracting AST nodes (functions, structs, classes, modules, calls, imports), and sync directly to local Neo4j.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Output path for the generated JSON graph file. Defaults to ~/graphify-out/graph.json.",
                },
                "sync_to_neo4j": {
                    "type": "boolean",
                    "description": "Whether to immediately sync the generated graph into Neo4j. Defaults to true.",
                },
            },
        },
    },
    {
        "name": "memory_manager",
        "description": "Read, store, and manage persistent episodic memory nodes (:Entity:Memory) in Neo4j with timestamps, categories, and bidirectional links to code entities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["store", "search", "retrieve", "delete"],
                    "description": "Action to perform on memory.",
                },
                "content": {
                    "type": "string",
                    "description": "The memory content to store or search text.",
                },
                "category": {
                    "type": "string",
                    "description": "Category tag for the memory (e.g. 'architecture', 'decision', 'bugfix', 'user_preference').",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional code entity ID to link this memory to via [:RELATES_TO].",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of memories to return (default: 10).",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "rag_retrieval",
        "description": "Retrieve structural and semantic knowledge from the graph using hybrid search, shortest-path calculation, node explanation (callers/dependencies), or read-only Cypher.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["query", "path", "explain", "stats", "cypher"],
                    "description": "Retrieval mode.",
                },
                "query": {
                    "type": "string",
                    "description": "Search text (for mode='query') or Cypher query string (for mode='cypher').",
                },
                "source": {
                    "type": "string",
                    "description": "Source node name or ID (for mode='path').",
                },
                "target": {
                    "type": "string",
                    "description": "Target node name or ID (for mode='path').",
                },
                "node_id": {
                    "type": "string",
                    "description": "Target node ID to explain (for mode='explain').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to retrieve (default: 10).",
                },
            },
            "required": ["mode"],
        },
    },
]


class McpServer:
    def __init__(self) -> None:
        http_uri = os.getenv("NEO4J_HTTP_URI", "http://127.0.0.1:7474")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")

        self.client = GraphRagClient(http_uri=http_uri, user=user, password=password)
        self.engine = GraphRagEngine(http_uri=http_uri, user=user, password=password)

    def handle_initialize(self, req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": __version__,
                },
            },
        }

    def handle_tools_list(self, req_id: Any) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS_SPEC,
            },
        }

    def handle_tool_call(self, req_id: Any, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "graph_builder":
                res = self._execute_graph_builder(args)
            elif name == "memory_manager":
                res = self._execute_memory_manager(args)
            elif name == "rag_retrieval":
                res = self._execute_rag_retrieval(args)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{name}' not found"},
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(res, indent=2)},
                    ],
                    "isError": False,
                },
            }
        except Exception as err:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": f"Error executing tool '{name}': {str(err)}"},
                    ],
                    "isError": True,
                },
            }

    def _execute_graph_builder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        output_path_str = args.get("output_path")
        out_p = Path(output_path_str) if output_path_str else (Path.home() / "graphify-out" / "graph.json")
        sync_to_neo4j = args.get("sync_to_neo4j", True)

        res = build_master_graph(
            output_path=out_p,
            sync_to_neo4j=sync_to_neo4j,
            http_uri=self.client.http_uri,
            user=self.client.user,
            password=self.client.password,
        )
        return {"ok": True, "output": str(out_p), "result": res}

    def _execute_memory_manager(self, args: Dict[str, Any]) -> Dict[str, Any]:
        action = args.get("action")
        content = args.get("content", "")
        category = args.get("category", "general")
        entity_id = args.get("entity_id")
        limit = int(args.get("limit", 10))

        if action == "store":
            if not content:
                raise ValueError("content is required to store memory")
            mem_id = f"mem_{int(time.time() * 1000)}"
            cypher = """
            CREATE (m:Entity:Memory {
                id: $id,
                content: $content,
                category: $category,
                timestamp: datetime(),
                created_at: timestamp()
            })
            RETURN m.id AS id, m.content AS content, m.category AS category
            """
            created = self.client.run_cypher(cypher, {"id": mem_id, "content": content, "category": category})

            linked = False
            if entity_id:
                link_cypher = """
                MATCH (m:Entity:Memory {id: $mem_id})
                MATCH (e:Entity {id: $entity_id})
                MERGE (m)-[:RELATES_TO]->(e)
                RETURN count(*) AS cnt
                """
                l_res = self.client.run_cypher(link_cypher, {"mem_id": mem_id, "entity_id": entity_id})
                linked = bool(l_res and l_res[0].get("cnt", 0) > 0)

            return {
                "stored": True,
                "memory_id": mem_id,
                "category": category,
                "linked_to_entity": entity_id if linked else None,
            }

        elif action in ("search", "retrieve"):
            if content:
                cypher = """
                MATCH (m:Entity:Memory)
                WHERE toLower(m.content) CONTAINS toLower($query) OR m.category = $category
                OPTIONAL MATCH (m)-[:RELATES_TO]->(e:Entity)
                RETURN m.id AS id, m.content AS content, m.category AS category,
                       toString(m.timestamp) AS timestamp, e.id AS related_entity
                ORDER BY m.created_at DESC
                LIMIT $limit
                """
                params = {"query": content, "category": category, "limit": limit}
            else:
                cypher = """
                MATCH (m:Entity:Memory)
                OPTIONAL MATCH (m)-[:RELATES_TO]->(e:Entity)
                RETURN m.id AS id, m.content AS content, m.category AS category,
                       toString(m.timestamp) AS timestamp, e.id AS related_entity
                ORDER BY m.created_at DESC
                LIMIT $limit
                """
                params = {"limit": limit}

            memories = self.client.run_cypher(cypher, params)
            return {"count": len(memories), "memories": memories}

        elif action == "delete":
            mem_id = args.get("entity_id") or content
            if not mem_id:
                raise ValueError("Must provide memory ID in entity_id or content to delete")
            cypher = """
            MATCH (m:Entity:Memory {id: $id})
            DETACH DELETE m
            RETURN count(*) AS deleted
            """
            del_res = self.client.run_cypher(cypher, {"id": mem_id})
            cnt = del_res[0].get("deleted", 0) if del_res else 0
            return {"deleted": cnt > 0, "count": cnt}

        else:
            raise ValueError(f"Unknown memory action: {action}")

    def _execute_rag_retrieval(self, args: Dict[str, Any]) -> Dict[str, Any]:
        mode = args.get("mode")
        limit = int(args.get("limit", 10))

        if mode == "query":
            q = args.get("query", "")
            return self.engine.query(question=q, top_k=limit)

        elif mode == "path":
            src = args.get("source", "")
            tgt = args.get("target", "")
            if not src or not tgt:
                raise ValueError("source and target are required for path retrieval")
            return self.engine.shortest_path(src, tgt)

        elif mode == "explain":
            nid = args.get("node_id") or args.get("query", "")
            if not nid:
                raise ValueError("node_id is required for explain mode")
            return self.engine.explain_node(nid)

        elif mode == "stats":
            return self.engine.get_stats()

        elif mode == "cypher":
            c_query = args.get("query", "")
            if not c_query:
                raise ValueError("query is required for cypher mode")
            # Enforce read-only constraint on retrieval
            forbidden = ["CREATE", "SET", "DELETE", "DROP", "DETACH", "MERGE", "REMOVE"]
            tokens = [t.strip().upper() for t in c_query.split()]
            for f in forbidden:
                if f in tokens:
                    raise PermissionError(f"Cypher write statement '{f}' not permitted in rag_retrieval tool.")
            data = self.client.run_cypher(c_query)
            return {"rows_returned": len(data), "data": data[:limit]}

        else:
            raise ValueError(f"Unknown retrieval mode: {mode}")


def run_mcp_server() -> int:
    server = McpServer()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            resp = server.handle_initialize(req_id, params)
        elif method == "tools/list":
            resp = server.handle_tools_list(req_id)
        elif method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            resp = server.handle_tool_call(req_id, name, arguments)
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        elif method == "notifications/initialized":
            continue
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"},
            }

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(run_mcp_server())
