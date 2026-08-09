"""
Local web dashboard — serve HTML health view at http://127.0.0.1:8765

Uses only stdlib (http.server). No Flask, no Node at runtime.
"""

import json
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

WEB_ROOT = Path(__file__).parent / "web"
WEB_DIST = WEB_ROOT / "dist"
WEB_FALLBACK = WEB_ROOT / "dashboard.html"

MIME_OVERRIDES = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


class SentinelWebHandler(BaseHTTPRequestHandler):
    """HTTP handler for dashboard static assets and /api/health JSON."""

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            payload = self.server.get_health()  # type: ignore[attr-defined]
            self._serve_json(payload)
            return

        if WEB_DIST.exists() and (WEB_DIST / "index.html").exists():
            self._serve_static(path)
        elif path in ("/", "/index.html"):
            self._serve_file(WEB_FALLBACK, "text/html; charset=utf-8")
        else:
            self.send_error(404, "Not Found")

    def _serve_static(self, url_path: str) -> None:
        """Serve built Vite assets from reporters/web/dist."""
        rel = url_path.lstrip("/") or "index.html"
        candidate = (WEB_DIST / rel).resolve()

        # Prevent path traversal
        try:
            candidate.relative_to(WEB_DIST.resolve())
        except ValueError:
            self.send_error(403, "Forbidden")
            return

        if candidate.is_dir():
            candidate = candidate / "index.html"

        if not candidate.exists() or not candidate.is_file():
            # SPA fallback for client-side routes
            candidate = WEB_DIST / "index.html"
            if not candidate.exists():
                self.send_error(404, "Dashboard not built")
                return

        suffix = candidate.suffix.lower()
        content_type = MIME_OVERRIDES.get(
            suffix, mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        )
        self._serve_file(candidate, content_type)

    def _serve_file(self, filepath: Path, content_type: str) -> None:
        if not filepath.exists():
            self.send_error(404, f"Missing {filepath.name}")
            return
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        cache = "no-store" if filepath.suffix == ".html" else "public, max-age=86400"
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _serve_json(self, payload: dict) -> None:
        data = json.dumps(payload, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        pass  # keep console quiet


def load_fleet_reports(reports_dir: Optional[Path]) -> list[dict]:
    """Load JSON health reports dropped by other Sentinel instances."""
    if not reports_dir or not reports_dir.is_dir():
        return []

    fleet = []
    for path in sorted(reports_dir.glob("*.json")):
        try:
            report = json.loads(path.read_text())
            fleet.append({
                "source": "file",
                "filename": path.name,
                "report": report,
            })
        except (json.JSONDecodeError, OSError):
            continue
    return fleet


def run_web_server(
    get_health: Callable[[], dict],
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Start the local dashboard server and block until interrupted."""
    server = ThreadingHTTPServer((host, port), SentinelWebHandler)
    server.get_health = get_health  # type: ignore[attr-defined]

    url = f"http://{host}:{port}/"
    print(f"\n  EC2 Sentinel web dashboard: {url}")
    print(f"  API: {url}api/health")
    if not (WEB_DIST / "index.html").exists():
        print("  Note: React dashboard not built — run: cd reporters/web-ui && npm install && npm run build")
    print("  Press Ctrl+C to stop.\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except OSError:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Web dashboard stopped.\n")
    finally:
        server.server_close()
