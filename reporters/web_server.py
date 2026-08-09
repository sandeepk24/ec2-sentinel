"""
Local web dashboard — serve HTML health view at http://127.0.0.1:8765

Uses only stdlib (http.server). No Flask, no Node.
"""

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

DASHBOARD_HTML = Path(__file__).parent / "web" / "dashboard.html"


class SentinelWebHandler(BaseHTTPRequestHandler):
    """HTTP handler for dashboard HTML and /api/health JSON."""

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_file(DASHBOARD_HTML, "text/html; charset=utf-8")
        elif path == "/api/health":
            payload = self.server.get_health()  # type: ignore[attr-defined]
            self._serve_json(payload)
        else:
            self.send_error(404, "Not Found")

    def _serve_file(self, filepath: Path, content_type: str) -> None:
        if not filepath.exists():
            self.send_error(404, f"Missing {filepath.name}")
            return
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
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
