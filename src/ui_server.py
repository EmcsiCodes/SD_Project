from __future__ import annotations

import json
import os
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from src.database import Database
from src.indexing_engine import IndexingEngine
from src.input_parsing import parse_extensions, parse_patterns
from src.query_engine import QueryEngine


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    default_root: str = "."
    default_db: str = ".local_search.db"
    open_browser: bool = False


class LocalSearchHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], config: ServerConfig) -> None:
        super().__init__(server_address, LocalSearchRequestHandler)
        self.config = config
        self.asset_dir = Path(__file__).with_name("ui")


class LocalSearchRequestHandler(BaseHTTPRequestHandler):
    server: LocalSearchHttpServer

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/":
            self._serve_asset("index.html", "text/html; charset=utf-8")
            return
        if route == "/app.css":
            self._serve_asset("app.css", "text/css; charset=utf-8")
            return
        if route == "/app.js":
            self._serve_asset("app.js", "application/javascript; charset=utf-8")
            return
        if route == "/api/config":
            self._send_json(
                HTTPStatus.OK,
                {
                    "default_root": self.server.config.default_root,
                    "default_db": self.server.config.default_db,
                    "working_directory": os.getcwd(),
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found."})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        payload = self._read_json_body()
        if payload is None:
            return
        if route == "/api/index":
            self._handle_index(payload)
            return
        if route == "/api/search":
            self._handle_search(payload)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found."})

    def log_message(self, format: str, *args: object) -> None:
        print(f"[ui] {self.address_string()} - {format % args}", flush=True)

    def _handle_index(self, payload: dict[str, object]) -> None:
        root = str(payload.get("root") or self.server.config.default_root).strip()
        db_path = str(payload.get("db_path") or self.server.config.default_db).strip()
        if not root:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Root path is required."})
            return
        if not Path(root).is_dir():
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Folder not found: {root}"})
            return
        if not db_path:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Database path is required."})
            return

        ignore_extensions = parse_extensions([str(payload.get("ignore_extensions") or "")])
        ignore_patterns = parse_patterns(str(payload.get("ignore_patterns") or ""))
        include_hidden = bool(payload.get("include_hidden", False))
        try:
            max_file_size_mb = max(1, int(payload.get("max_file_size_mb") or 2))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Max file size must be a number."})
            return

        database = Database(db_path)
        engine = IndexingEngine(database)
        report = engine.index(
            root_path=root,
            ignore_extensions=ignore_extensions,
            ignore_patterns=ignore_patterns,
            include_hidden=include_hidden,
            max_file_size_mb=max_file_size_mb,
            progress_every=0,
        )
        self._send_json(
            HTTPStatus.OK,
            {
                "message": "Indexing complete.",
                "report": report,
                "root": os.path.abspath(root),
                "db_path": os.path.abspath(db_path),
            },
        )

    def _handle_search(self, payload: dict[str, object]) -> None:
        query = str(payload.get("query") or "").strip()
        if not query:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Search query is required."})
            return

        scope = str(payload.get("scope") or "all").strip().lower()
        if scope not in {"all", "filename", "content"}:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Unsupported search scope: {scope}"})
            return

        db_path = str(payload.get("db_path") or self.server.config.default_db).strip()
        if not db_path:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Database path is required."})
            return
        try:
            limit = max(1, int(payload.get("limit") or 10))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Result limit must be a number."})
            return

        database = Database(db_path)
        database.init_schema()
        engine = QueryEngine(database)
        results = engine.search(
            query_text=query,
            limit=limit,
            filename_only=scope == "filename",
            content_only=scope == "content",
        )
        self._send_json(
            HTTPStatus.OK,
            {
                "query": query,
                "scope": scope,
                "results": results,
                "formatted_results": engine.format_results(results),
            },
        )

    def _read_json_body(self) -> dict[str, object] | None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Request body must be valid JSON."})
            return None
        if not isinstance(decoded, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "JSON body must be an object."})
            return None
        return decoded

    def _serve_asset(self, asset_name: str, content_type: str) -> None:
        asset_path = self.server.asset_dir / asset_name
        if not asset_path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Missing asset: {asset_name}"})
            return
        self._send_bytes(HTTPStatus.OK, asset_path.read_bytes(), content_type)

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_ui(config: ServerConfig) -> None:
    server = LocalSearchHttpServer((config.host, config.port), config)
    display_host = "127.0.0.1" if config.host in {"0.0.0.0", "::"} else config.host
    url = f"http://{display_host}:{config.port}/"
    print(f"Local Search UI available at {url}", flush=True)
    print("Press Ctrl+C to stop the server.", flush=True)

    if config.open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping UI server.", flush=True)
    finally:
        server.server_close()
