from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_BOLT_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
DEFAULT_HTTP_URI = os.getenv("NEO4J_HTTP_URI", "http://127.0.0.1:7474")
DEFAULT_USER = os.getenv("NEO4J_USER", "neo4j")
DEFAULT_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


class GraphRagClient:
    """Client for executing Cypher transactions against local Neo4j HTTP API."""

    def __init__(
        self,
        http_uri: str = DEFAULT_HTTP_URI,
        user: str = DEFAULT_USER,
        password: str = DEFAULT_PASSWORD,
        bolt_url: Optional[str] = None,
        http_url: Optional[str] = None,
        database: str = "neo4j",
    ):
        self.http_uri = (http_url or http_uri).rstrip("/")
        self.bolt_url = bolt_url or DEFAULT_BOLT_URI
        self.database = database
        self.user = user
        self.password = password
        self._auth_header = (
            "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
            if password
            else None
        )

    def execute_cypher(
        self,
        statement: str,
        parameters: Optional[Dict[str, Any]] = None,
        timeout: int = 15,
    ) -> List[Dict[str, Any]]:
        return self.run_cypher(statement=statement, params=parameters, timeout=timeout)

    def test_connection(self) -> bool:
        try:
            res = self.run_cypher("RETURN 1 AS ping", timeout=3)
            return bool(res and res[0].get("ping") == 1)
        except Exception:
            return False

    def run_cypher(
        self,
        statement: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 15,
    ) -> List[Dict[str, Any]]:
        """Run Cypher query against /db/neo4j/tx/commit."""
        url = f"{self.http_uri}/db/neo4j/tx/commit"
        payload = json.dumps({
            "statements": [{"statement": statement, "parameters": params or {}}]
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._auth_header:
            headers["Authorization"] = self._auth_header

        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("errors"):
                    raise RuntimeError(f"Neo4j Cypher Error: {data['errors']}")
                results = []
                for res in data.get("results", []):
                    cols = res.get("columns", [])
                    for row in res.get("data", []):
                        row_vals = row.get("row", [])
                        results.append(dict(zip(cols, row_vals)))
                return results
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to Neo4j at {self.http_uri}: {e}") from e


Neo4jClient = GraphRagClient

