"""
tests.test_security
===================
Security regression test suite for Graph Memory Web UI and API Server.
Verifies defense against:
  1. DNS Rebinding attacks (Host header validation)
  2. Cross-Site Request Forgery (CSRF token enforcement on POST)
  3. Cross-Origin API abuse (Origin header validation)
  4. Cypher write query attacks (Read-only execution guardrails)
  5. Path traversal attacks (Directory escape protection)
"""

import http.client
import json
import secrets
import threading
import time
import pytest
from http.server import HTTPServer

from graph_memory.server import GraphRagRequestHandler
from graph_memory.engine import GraphRagEngine
from graph_memory.client import GraphRagClient


class MockEngine(GraphRagEngine):
    """Mock engine for offline security test harness."""
    def __init__(self):
        self.http_uri = "http://127.0.0.1:7474"
        self.user = "neo4j"
        self.password = ""
        self.client = GraphRagClient(http_uri=self.http_uri)
        self.local_nodes = {}
        self.local_edges = []

    def run_cypher(self, statement: str, params=None):
        return [{"status": "mock_success"}]

    def get_stats(self):
        return {"ok": True, "neo4j": {"online": True, "totalNodes": 100}}


@pytest.fixture(scope="module")
def test_server():
    server_address = ("127.0.0.1", 18765)
    token = secrets.token_hex(24)

    GraphRagRequestHandler.engine = MockEngine()
    GraphRagRequestHandler.session_token = token
    GraphRagRequestHandler.port = 18765

    httpd = HTTPServer(server_address, GraphRagRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)

    yield f"127.0.0.1:18765", token

    httpd.shutdown()


def test_host_header_validation_blocks_dns_rebinding(test_server):
    """Host headers not matching localhost/127.0.0.1 must be rejected with 403."""
    host, _ = test_server
    conn = http.client.HTTPConnection(host)
    conn.request("GET", "/api/stats", headers={"Host": "attacker.com"})
    resp = conn.getresponse()
    assert resp.status == 403
    data = json.loads(resp.read().decode())
    assert "Invalid or non-local Host header" in data.get("error", "")
    conn.close()


def test_origin_header_validation_blocks_cross_origin_requests(test_server):
    """Origin headers from foreign domains must be rejected with 403."""
    host, token = test_server
    conn = http.client.HTTPConnection(host)
    conn.request(
        "POST",
        "/api/cypher",
        body=json.dumps({"statement": "MATCH (n) RETURN n LIMIT 1"}),
        headers={
            "Host": host,
            "Origin": "https://malicious-site.org",
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
        },
    )
    resp = conn.getresponse()
    assert resp.status == 403
    data = json.loads(resp.read().decode())
    assert "Cross-origin request strictly rejected" in data.get("error", "")
    conn.close()


def test_csrf_token_enforcement(test_server):
    """POST requests without a valid CSRF token must be rejected with 403."""
    host, _ = test_server
    conn = http.client.HTTPConnection(host)
    # Request without CSRF token
    conn.request(
        "POST",
        "/api/cypher",
        body=json.dumps({"statement": "MATCH (n) RETURN n LIMIT 1"}),
        headers={
            "Host": host,
            "Content-Type": "application/json",
        },
    )
    resp = conn.getresponse()
    assert resp.status == 403
    data = json.loads(resp.read().decode())
    assert "Missing CSRF authorization header" in data.get("error", "")

    # Now fetch legitimate token from /api/auth/token
    conn.request("GET", "/api/auth/token", headers={"Host": host})
    token_resp = conn.getresponse()
    assert token_resp.status == 200
    token_data = json.loads(token_resp.read().decode())
    fetched_token = token_data.get("token")
    assert fetched_token and len(fetched_token) >= 32

    # Request with valid token should succeed
    conn.request(
        "POST",
        "/api/cypher",
        body=json.dumps({"statement": "MATCH (n) RETURN n LIMIT 1"}),
        headers={
            "Host": host,
            "Content-Type": "application/json",
            "X-CSRF-Token": fetched_token,
        },
    )
    ok_resp = conn.getresponse()
    assert ok_resp.status == 200
    conn.close()


def test_cypher_write_guardrail_blocks_mutation(test_server):
    """Any mutation Cypher query (CREATE, SET, DELETE, DROP, DETACH) must be rejected."""
    host, token = test_server
    conn = http.client.HTTPConnection(host)

    destructive_queries = [
        "MATCH (n) DETACH DELETE n",
        "CREATE (n:BadNode {name: 'test'})",
        "MATCH (n) SET n.hacked = true",
        "DROP INDEX ON :Entity(id)",
        "MERGE (n:Evil {name: 'hacked'})",
    ]

    for q in destructive_queries:
        conn.request(
            "POST",
            "/api/cypher",
            body=json.dumps({"statement": q}),
            headers={
                "Host": host,
                "Content-Type": "application/json",
                "X-CSRF-Token": token,
            },
        )
        resp = conn.getresponse()
        assert resp.status == 403
        body = json.loads(resp.read().decode())
        assert "forbidden in Web UI read-only mode" in body.get("error", "")

    conn.close()


def test_path_traversal_is_blocked(test_server):
    """Path traversal sequences (e.g. ../../) must be blocked."""
    host, _ = test_server
    conn = http.client.HTTPConnection(host)
    conn.request("GET", "/../../etc/passwd", headers={"Host": host})
    resp = conn.getresponse()
    assert resp.status in (403, 404)
    content = resp.read().decode()
    assert "root:x:0:0" not in content
    conn.close()
