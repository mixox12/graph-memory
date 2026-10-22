"""
tests.test_engine
=================
Unit tests for GraphRagEngine, AST scanner, and graph building utilities.
"""

import json
import os
import tempfile
from pathlib import Path
import pytest

from graph_memory.client import GraphRagClient
from graph_memory.engine import GraphRagEngine
from graph_memory.builder import extract_root_scripts, build_master_graph


class DummyClient(GraphRagClient):
    def __init__(self):
        super().__init__(http_uri="http://127.0.0.1:7474")

    def run_cypher(self, statement: str, params=None, timeout=15):
        if "count(n) AS nodeCount" in statement:
            return [{"nodeCount": 100}]
        elif "count(r) AS relCount" in statement:
            return [{"relCount": 250}]
        elif "CALL db.labels()" in statement:
            return [{"label": "Entity"}, {"label": "File"}, {"label": "Function"}]
        elif "shortestPath" in statement:
            return [{
                "nodes": ["NodeA", "NodeB"],
                "rels": ["CALLS"],
                "hops": 1
            }]
        elif "WHERE n.id = $node_id" in statement:
            return [{
                "id": "play_head_fn",
                "name": "update_playhead",
                "labels": ["Function"],
                "community": 1,
                "outgoing": [{"rel": "CALLS", "target": "render_frame"}],
                "incoming": [{"rel": "CALLS", "source": "timeline_tick"}],
            }]
        elif "ORDER BY degree DESC" in statement:
            return [
                {"name": "TimelineApp", "labels": ["Class"], "community": 1, "degree": 42}
            ]
        elif "WHERE n.community IS NOT NULL" in statement:
            return [
                {"communityId": 1, "memberCount": 25, "topMembers": ["TimelineApp", "Engine"]}
            ]
        return []


def test_engine_stats_with_dummy_client():
    engine = GraphRagEngine()
    engine.client = DummyClient()
    stats = engine.get_stats()
    assert stats["ok"] is True
    assert stats["neo4j"]["totalNodes"] == 100
    assert stats["neo4j"]["totalRelationships"] == 250
    assert "Entity" in stats["neo4j"]["labels"]


def test_engine_shortest_path():
    engine = GraphRagEngine()
    engine.client = DummyClient()
    res = engine.shortest_path("NodeA", "NodeB")
    assert res["found"] is True
    assert res["hops"] == 1
    assert res["rels"] == ["CALLS"]


def test_engine_explain_node():
    engine = GraphRagEngine()
    engine.client = DummyClient()
    res = engine.explain_node("play_head_fn")
    assert res["found"] is True
    assert res["name"] == "update_playhead"
    assert len(res["outgoing"]) == 1
    assert res["outgoing"][0]["target"] == "render_frame"


def test_ast_script_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create sample python file
        py_file = tmp_path / "video_agent.py"
        py_file.write_text("""
import os
import sys

class VideoPipeline:
    def process_frame(self, frame_id):
        return os.path.exists(str(frame_id))

def run_timeline():
    vp = VideoPipeline()
    vp.process_frame(1)
""", encoding="utf-8")

        nodes, edges = extract_root_scripts(tmp_path)
        assert len(nodes) > 0
        node_names = [n["name"] for n in nodes]
        assert "video_agent.py" in node_names
        # Check extracted classes/functions
        extracted_labels = [n["label"] for n in nodes]
        assert any("VideoPipeline" in lbl for lbl in extracted_labels)
        assert any("run_timeline" in lbl for lbl in extracted_labels)
