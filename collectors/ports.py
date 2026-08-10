"""
Port health checker: verify TCP listeners for configured services.

Answers: "Is Tomcat actually listening on 8080, or did it crash and nobody noticed?"
"""

import socket
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class PortCheck:
    port: int
    service_name: str
    is_open: bool
    response_ms: float  # connect latency — slow means trouble

    @property
    def status(self) -> str:
        if not self.is_open:
            return "CLOSED"
        if self.response_ms > 1000:
            return "SLOW"
        return "OPEN"


@dataclass
class PortReport:
    timestamp: str
    checks: list[PortCheck]

    @property
    def failed(self) -> list[PortCheck]:
        return [c for c in self.checks if not c.is_open]


def check_port(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 5.0,
) -> tuple[bool, float]:
    """
    Check if a TCP port is accepting connections.
    Returns (is_open, latency_ms).
    """
    import time

    if not (1 <= port <= 65535):
        return False, 0.0

    start = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        elapsed = (time.monotonic() - start) * 1000
        sock.close()
        return result == 0, round(elapsed, 1)
    except (socket.error, OSError):
        elapsed = (time.monotonic() - start) * 1000
        return False, round(elapsed, 1)


def collect_ports(port_configs: list[dict]) -> PortReport:
    """
    Check all configured ports.

    Args:
        port_configs: List of dicts with keys:
            - name: service name (e.g., "tomcat")
            - port: TCP port number
            - host: (optional) host to check, default "127.0.0.1"
    """
    checks = []
    for config in port_configs:
        port = config["port"]
        name = config.get("name", f"port-{port}")
        host = config.get("host", "127.0.0.1")

        is_open, latency = check_port(port, host)
        checks.append(PortCheck(
            port=port,
            service_name=name,
            is_open=is_open,
            response_ms=latency,
        ))

    return PortReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        checks=checks,
    )
