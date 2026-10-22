from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .engine import GraphRagEngine

PKG_DIR = Path(__file__).resolve().parent
REPO_DIR = PKG_DIR.parent
WEB_DIR = REPO_DIR / "web" if (REPO_DIR / "web").exists() else PKG_DIR / "web"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}

CYPHER_WRITE_GUARD = re.compile(
    r"\b(CREATE|SET|DELETE|DETACH|REMOVE|MERGE|DROP|ALTER|GRANT|REVOKE|TERMINATE|CALL\s+apoc\.trigger|CALL\s+apoc\.periodic)\b",
    re.IGNORECASE,
)


class GraphRagRequestHandler(BaseHTTPRequestHandler):
    engine: GraphRagEngine = None
    session_token: str = ""
    port: int = 8765
    _last_sync_time: float = 0.0

    def log_message(self, format, *args):
        sys.stderr.write(f"[GraphMemory-UI] {self.command} {self.path} - {args[1]}\n")

    def _get_local_origin(self) -> str:
        origin_header = self.headers.get("Origin")
        if origin_header:
            parsed = urlparse(origin_header)
            if parsed.hostname in ALLOWED_HOSTS:
                return origin_header
        return f"http://127.0.0.1:{self.port}"

    def send_json(self, status: int, payload: Any):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._get_local_origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' data: blob:;")
        self.end_headers()
        self.wfile.write(body)

    def validate_security(self, require_csrf: bool = False) -> bool:
        # 1. Host Validation (anti-DNS rebinding)
        host_header = self.headers.get("Host", "")
        host_name = host_header.split(":")[0].strip().lower()
        if host_name not in ALLOWED_HOSTS:
            self.send_json(403, {"ok": False, "error": "Security Alert: Invalid or non-local Host header."})
            return False

        # 2. Origin Validation
        origin_header = self.headers.get("Origin")
        if origin_header:
            parsed_origin = urlparse(origin_header)
            if parsed_origin.hostname not in ALLOWED_HOSTS:
                self.send_json(403, {"ok": False, "error": "Security Alert: Cross-origin request strictly rejected."})
                return False

        # 3. Referer Validation
        referer_header = self.headers.get("Referer")
        if referer_header:
            parsed_ref = urlparse(referer_header)
            if parsed_ref.hostname not in ALLOWED_HOSTS:
                self.send_json(403, {"ok": False, "error": "Security Alert: Cross-origin referer rejected."})
                return False

        # 4. CSRF / Session Check
        if require_csrf:
            token = self.headers.get("X-CSRF-Token") or self.headers.get("X-Session-Token")
            x_requested_with = self.headers.get("X-Requested-With")
            if not token and x_requested_with != "XMLHttpRequest":
                self.send_json(403, {"ok": False, "error": "Security Alert: Missing CSRF authorization header."})
                return False
            if token and token != self.session_token:
                self.send_json(403, {"ok": False, "error": "Security Alert: Invalid session CSRF token."})
                return False

        return True

    def read_json_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        except Exception:
            return {}

    def do_OPTIONS(self):
        if not self.validate_security():
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._get_local_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-CSRF-Token, X-Requested-With")
        self.end_headers()

    def do_GET(self):
        if not self.validate_security(require_csrf=False):
            return

        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/auth/token":
            self.send_json(200, {"ok": True, "token": self.session_token})
            return

        if path == "/api/stats":
            self.send_json(200, self.engine.get_stats())
            return

        if path == "/api/graph":
            search = params.get("search", [None])[0]
            limit = int(params.get("limit", [300])[0])
            self.send_json(200, self.engine.get_graph_data(limit_nodes=limit, search=search))
            return

        if path == "/api/pagerank":
            limit = int(params.get("limit", [15])[0])
            self.send_json(200, {"ok": True, "nodes": self.engine.get_pagerank(limit=limit)})
            return

        if path == "/api/communities":
            self.send_json(200, {"ok": True, "communities": self.engine.get_communities()})
            return

        # Static Web Files
        if path == "/" or path == "":
            path = "/index.html"

        clean_path = os.path.normpath(path.lstrip("/"))
        if clean_path.startswith("..") or "/../" in clean_path:
            self.send_json(403, {"ok": False, "error": "Access Denied: Path traversal detected."})
            return

        file_path = (WEB_DIR / clean_path).resolve()
        if not str(file_path).startswith(str(WEB_DIR.resolve())):
            self.send_json(403, {"ok": False, "error": "Access Denied: Out-of-bounds file access."})
            return

        if file_path.exists() and file_path.is_file():
            mime_type, _ = mimetypes.guess_type(str(file_path))
            mime_type = mime_type or "application/octet-stream"
            content = file_path.read_bytes()

            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.validate_security(require_csrf=True):
            return

        body = self.read_json_body()

        if path == "/api/query":
            question = body.get("question", "")
            top_k = int(body.get("topK", 8))
            self.send_json(200, self.engine.query(question, top_k=top_k))
            return

        if path == "/api/path":
            from_id = body.get("from", "")
            to_id = body.get("to", "")
            self.send_json(200, self.engine.shortest_path(from_id, to_id))
            return

        if path == "/api/explain":
            node_id = body.get("nodeId", "")
            self.send_json(200, self.engine.explain_node(node_id))
            return

        if path == "/api/cypher":
            statement = str(body.get("statement", "")).strip()
            allow_writes = bool(body.get("allow_writes", False))

            if not allow_writes and CYPHER_WRITE_GUARD.search(statement):
                self.send_json(403, {
                    "ok": False,
                    "error": "Security Error: Destructive or modifying Cypher operations (CREATE, SET, DELETE, MERGE, DROP) are forbidden in Web UI read-only mode."
                })
                return

            try:
                results = self.engine.run_cypher(statement)
                self.send_json(200, {"ok": True, "results": results})
            except Exception as e:
                self.send_json(400, {"ok": False, "error": str(e)})
            return

        if path == "/api/sync":
            now = time.time()
            if now - GraphRagRequestHandler._last_sync_time < 10:
                self.send_json(429, {"ok": False, "error": "Rate limit: Sync was recently requested. Please wait."})
                return
            GraphRagRequestHandler._last_sync_time = now

            from .sync import sync_graph_to_neo4j
            from .engine import resolve_default_graph_json
            subprocess.Popen([sys.executable, "-m", "graph_memory.sync", "--graph", str(resolve_default_graph_json())])
            self.send_json(200, {"ok": True, "message": "Graphify sync initiated in background"})
            return

        self.send_response(404)
        self.end_headers()


def start_server(port: int = 8765, open_browser: bool = True):
    engine = GraphRagEngine()
    session_token = secrets.token_hex(24)

    GraphRagRequestHandler.engine = engine
    GraphRagRequestHandler.session_token = session_token
    GraphRagRequestHandler.port = port

    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, GraphRagRequestHandler)
    url = f"http://127.0.0.1:{port}"

    print(f"🔒 Secure Graph Memory Studio Web UI running at {url}")
    print(f"🔑 Session Authorization Token: {session_token}")
    print("🛡️  Enforced: Localhost-only (127.0.0.1), Host validation, CSRF checks, and Read-Only Cypher guardrails.")
    print("Press Ctrl+C to stop.")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Graph Memory Studio...")
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="Run Secure Graph Memory Studio Web UI Server")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port (default: 8765)")
    parser.add_argument("--no-open", action="store_true", help="Do not automatically open browser")
    args = parser.parse_args()

    start_server(port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()

HardenedGraphRagHandler = GraphRagRequestHandler
run_server = start_server

