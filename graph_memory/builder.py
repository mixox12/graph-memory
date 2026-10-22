from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .client import GraphRagClient, DEFAULT_HTTP_URI, DEFAULT_USER, DEFAULT_PASSWORD
from .sync import sync_graph_to_neo4j

ROOT_DIR = Path.home()
DEFAULT_OUTPUT_JSON = ROOT_DIR / "graphify-out" / "graph.json"


def extract_root_scripts(root_dir: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse top-level Python and Shell automation scripts in the user workspace."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    py_files = sorted(root_dir.glob("*.py"))
    sh_files = sorted(root_dir.glob("*.sh"))
    js_files = sorted(root_dir.glob("*.js"))

    print(f"🔍 Parsing {len(py_files)} Python, {len(sh_files)} Shell, {len(js_files)} JS scripts in {root_dir}...")

    for f in py_files:
        rel_path = f.name
        file_node_id = f"mac_root_{f.stem}"
        nodes.append({
            "id": file_node_id,
            "name": f.name,
            "label": f.name,
            "file": str(f),
            "source_file": rel_path,
            "source_location": "L1",
            "file_type": "python",
            "project": "mac-root",
            "community": 1,
            "community_name": "Root Agents & Automation",
            "degree": 0,
            "description": f"Workspace root Python script: {f.name}",
        })

        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                code_content = fh.read()
            tree = ast.parse(code_content, filename=str(f))

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_id = f"{file_node_id}_{node.name.lower()}"
                    nodes.append({
                        "id": class_id,
                        "name": node.name,
                        "label": node.name,
                        "file": str(f),
                        "source_file": rel_path,
                        "source_location": f"L{node.lineno}",
                        "file_type": "class",
                        "project": "mac-root",
                        "community": 1,
                        "community_name": "Root Agents & Automation",
                        "description": f"Class {node.name} defined in {f.name}",
                    })
                    edges.append({
                        "source": file_node_id,
                        "target": class_id,
                        "relation": "defines_class",
                        "source_file": rel_path,
                        "source_location": f"L{node.lineno}",
                        "weight": 1.0,
                    })

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_id = f"{file_node_id}_{node.name.lower()}"
                    nodes.append({
                        "id": func_id,
                        "name": f"{node.name}()",
                        "label": f"{node.name}()",
                        "file": str(f),
                        "source_file": rel_path,
                        "source_location": f"L{node.lineno}",
                        "file_type": "function",
                        "project": "mac-root",
                        "community": 1,
                        "community_name": "Root Agents & Automation",
                        "description": f"Function {node.name}() defined in {f.name}",
                    })
                    edges.append({
                        "source": file_node_id,
                        "target": func_id,
                        "relation": "defines_function",
                        "source_file": rel_path,
                        "source_location": f"L{node.lineno}",
                        "weight": 1.0,
                    })

                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        mod_name = alias.name
                        mod_id = f"import_{mod_name.replace('.', '_')}"
                        edges.append({
                            "source": file_node_id,
                            "target": mod_id,
                            "relation": "imports",
                            "source_file": rel_path,
                            "source_location": f"L{node.lineno}",
                            "weight": 0.8,
                        })

                elif isinstance(node, ast.ImportFrom):
                    mod_name = node.module or ""
                    mod_id = f"import_{mod_name.replace('.', '_')}"
                    edges.append({
                        "source": file_node_id,
                        "target": mod_id,
                        "relation": "imports_from",
                        "source_file": rel_path,
                        "source_location": f"L{node.lineno}",
                        "weight": 0.8,
                    })
        except Exception:
            pass

    for f in sh_files:
        file_node_id = f"mac_root_{f.stem}"
        nodes.append({
            "id": file_node_id,
            "name": f.name,
            "label": f.name,
            "file": str(f),
            "source_file": f.name,
            "source_location": "L1",
            "file_type": "shell",
            "project": "mac-root",
            "community": 2,
            "community_name": "Root Shell Scripts & Setup",
            "degree": 0,
            "description": f"Workspace shell script: {f.name}",
        })

    for f in js_files:
        file_node_id = f"mac_root_{f.stem}"
        nodes.append({
            "id": file_node_id,
            "name": f.name,
            "label": f.name,
            "file": str(f),
            "source_file": f.name,
            "source_location": "L1",
            "file_type": "javascript",
            "project": "mac-root",
            "community": 1,
            "community_name": "Root Agents & Automation",
            "degree": 0,
            "description": f"Workspace JavaScript script: {f.name}",
        })

    return nodes, edges


def build_master_graph(
    output_path: Path = DEFAULT_OUTPUT_JSON,
    sync_to_neo4j: bool = True,
    http_uri: str = DEFAULT_HTTP_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
) -> Dict[str, Any]:
    print("🌟 Building Master Knowledge Graph...")
    all_nodes: Dict[str, Dict[str, Any]] = {}
    all_edges: List[Dict[str, Any]] = []

    # 1. Project definitions
    project_sources = [
        {"name": "relay-prod", "path": ROOT_DIR / "relay-prod" / "graphify-out" / "graph.json"},
        {"name": "rag-graph", "path": ROOT_DIR / "Desktop" / "rag-graph" / "graphify-out" / "graph.json"},
        {"name": "clawhub", "path": ROOT_DIR / "clawhub" / "graphify-out" / "graph.json"},
        {"name": "FilmAgent2_Full_Project", "path": ROOT_DIR / "Desktop" / "FilmAgent2_Full_Project" / "graphify-out" / "graph.json"},
        {"name": "mr-mac-agent", "path": ROOT_DIR / "Desktop" / "mr mac agent" / "graphify-out" / "graph.json"},
        {"name": "gemc", "path": ROOT_DIR / "Desktop" / "gemc" / "graphify-out" / "graph.json"},
    ]

    root_nodes, root_edges = extract_root_scripts(ROOT_DIR)
    for n in root_nodes:
        all_nodes[n["id"]] = n
    all_edges.extend(root_edges)

    for p in project_sources:
        p_name = p["name"]
        p_path = p["path"]
        if not p_path.exists():
            continue

        with open(p_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        p_nodes = data.get("nodes", [])
        p_edges = data.get("edges", []) or data.get("links", [])

        proj_node_id = f"project_{p_name}"
        all_nodes[proj_node_id] = {
            "id": proj_node_id,
            "name": p_name,
            "label": p_name,
            "file": str(p_path.parent.parent),
            "source_file": "",
            "file_type": "project",
            "project": p_name,
            "community": 0,
            "community_name": "Workspaces",
            "description": f"Master Workspace Project: {p_name}",
        }

        for n in p_nodes:
            nid = str(n.get("id") or n.get("name") or "")
            if not nid:
                continue
            scoped_id = f"{p_name}_{nid}" if not nid.startswith(f"{p_name}_") else nid
            all_nodes[scoped_id] = {
                "id": scoped_id,
                "name": str(n.get("name") or n.get("label") or nid),
                "label": str(n.get("label") or n.get("name") or "Entity"),
                "file": str(n.get("file") or n.get("source_file") or ""),
                "source_file": str(n.get("source_file") or n.get("file") or ""),
                "source_location": str(n.get("source_location") or ""),
                "file_type": str(n.get("file_type") or "code"),
                "project": p_name,
                "community": n.get("community"),
                "community_name": str(n.get("community_name") or ""),
                "degree": n.get("degree") or 0,
                "description": str(n.get("description") or n.get("summary") or ""),
            }

        for e in p_edges:
            s = str(e.get("source") or "")
            t = str(e.get("target") or "")
            if not s or not t:
                continue
            scoped_s = f"{p_name}_{s}" if not s.startswith(f"{p_name}_") else s
            scoped_t = f"{p_name}_{t}" if not t.startswith(f"{p_name}_") else t
            all_edges.append({
                "source": scoped_s,
                "target": scoped_t,
                "relation": str(e.get("relation") or e.get("type") or "RELATES_TO"),
                "weight": float(e.get("weight") or 1.0),
                "source_file": str(e.get("source_file") or ""),
                "source_location": str(e.get("source_location") or ""),
                "project": p_name,
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "directed": True,
        "multigraph": True,
        "graph": {"name": "Master Workspace Knowledge Graph", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")},
        "nodes": list(all_nodes.values()),
        "edges": all_edges,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"💾 Master graph saved to {output_path} ({len(all_nodes):,} nodes, {len(all_edges):,} edges).")

    if sync_to_neo4j:
        return sync_graph_to_neo4j(output_path, http_uri=http_uri, user=user, password=password)

    return {"ok": True, "totalNodes": len(all_nodes), "totalEdges": len(all_edges)}


def main():
    parser = argparse.ArgumentParser(description="Build and sync master knowledge graph")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output path for master graph.json")
    parser.add_argument("--no-sync", action="store_true", help="Do not sync to Neo4j automatically")
    args = parser.parse_args()

    build_master_graph(output_path=args.out, sync_to_neo4j=not args.no_sync)


if __name__ == "__main__":
    main()
