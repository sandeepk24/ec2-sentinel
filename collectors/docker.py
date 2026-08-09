"""
Docker collector: containers, images, and disk usage via the docker CLI.

Gracefully skips when Docker is not installed or the daemon is unreachable.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DockerContainer:
    id: str
    name: str
    image: str
    state: str           # running, exited, restarting, paused, dead
    status: str            # human-readable status line
    ports: str = ""
    health: Optional[str] = None  # healthy, unhealthy, starting, none

    @property
    def is_running(self) -> bool:
        return self.state.lower() == "running"

    @property
    def is_unhealthy(self) -> bool:
        return self.health == "unhealthy" or "unhealthy" in self.status.lower()


@dataclass
class DockerImage:
    repository: str
    tag: str
    id: str
    size: str
    created_since: str = ""

    @property
    def name(self) -> str:
        if self.repository == "<none>":
            return f"<none>:{self.tag}"
        return f"{self.repository}:{self.tag}"


@dataclass
class DockerDiskUsage:
    images_size: str = "0B"
    images_reclaimable: str = "0B"
    containers_size: str = "0B"
    containers_reclaimable: str = "0B"
    volumes_size: str = "0B"
    volumes_reclaimable: str = "0B"
    build_cache_reclaimable: str = "0B"


@dataclass
class ExpectedContainer:
    name: str
    match: str
    found: bool = False
    running: bool = False
    matched_container: Optional[str] = None


@dataclass
class DockerReport:
    timestamp: str
    available: bool
    server_version: str = ""
    error: str = ""
    containers: list[DockerContainer] = field(default_factory=list)
    images: list[DockerImage] = field(default_factory=list)
    disk: DockerDiskUsage = field(default_factory=DockerDiskUsage)
    expected: list[ExpectedContainer] = field(default_factory=list)

    @property
    def running_count(self) -> int:
        return sum(1 for c in self.containers if c.is_running)

    @property
    def stopped_count(self) -> int:
        return sum(1 for c in self.containers if not c.is_running)

    @property
    def unhealthy(self) -> list[DockerContainer]:
        return [c for c in self.containers if c.is_unhealthy]

    @property
    def missing_expected(self) -> list[ExpectedContainer]:
        return [e for e in self.expected if not e.found or not e.running]


def _run_docker(args: list[str], timeout: float = 15.0) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            return False, "", err
        return True, result.stdout, ""
    except FileNotFoundError:
        return False, "", "docker CLI not found"
    except subprocess.TimeoutExpired:
        return False, "", "docker command timed out"
    except OSError as e:
        return False, "", str(e)


def _parse_health(status: str) -> Optional[str]:
    lower = status.lower()
    if "(healthy)" in lower:
        return "healthy"
    if "(unhealthy)" in lower:
        return "unhealthy"
    if "(health: starting)" in lower or "(starting)" in lower:
        return "starting"
    return None


def _list_containers() -> list[DockerContainer]:
    ok, out, _ = _run_docker(["ps", "-a", "--no-trunc", "--format", "{{json .}}"])
    if not ok:
        return []

    containers = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        name = (row.get("Names") or row.get("Name") or "").lstrip("/")
        status = row.get("Status") or row.get("State") or ""
        state = (row.get("State") or "unknown").lower()

        containers.append(DockerContainer(
            id=(row.get("ID") or "")[:12],
            name=name,
            image=row.get("Image") or "",
            state=state,
            status=status,
            ports=row.get("Ports") or "",
            health=_parse_health(status),
        ))
    return containers


def _list_images() -> list[DockerImage]:
    ok, out, _ = _run_docker(["images", "--format", "{{json .}}"])
    if not ok:
        return []

    images = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        images.append(DockerImage(
            repository=row.get("Repository") or "<none>",
            tag=row.get("Tag") or "<none>",
            id=(row.get("ID") or "")[:12],
            size=row.get("Size") or "0B",
            created_since=row.get("CreatedSince") or "",
        ))
    return images


def _parse_size_bytes(size_str: str) -> float:
    """Best-effort parse of docker size strings like '1.2GB' or '500MB'."""
    if not size_str:
        return 0.0
    m = re.match(r"^([\d.]+)\s*(B|KB|MB|GB|TB)?$", size_str.strip(), re.I)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = (m.group(2) or "B").upper()
    mult = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
    return val * mult.get(unit, 1)


def _docker_disk_usage() -> DockerDiskUsage:
    disk = DockerDiskUsage()
    ok, out, _ = _run_docker(["system", "df", "--format", "{{json .}}"])
    if ok and out.strip():
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = (row.get("Type") or "").lower()
            total = row.get("Size") or row.get("TotalCount") or "0B"
            reclaim = row.get("Reclaimable") or "0B"
            if kind == "images":
                disk.images_size = str(total)
                disk.images_reclaimable = str(reclaim).split("(")[0].strip()
            elif kind == "containers":
                disk.containers_size = str(total)
                disk.containers_reclaimable = str(reclaim).split("(")[0].strip()
            elif kind == "local volumes" or kind == "volumes":
                disk.volumes_size = str(total)
                disk.volumes_reclaimable = str(reclaim).split("(")[0].strip()
            elif kind == "build cache":
                disk.build_cache_reclaimable = str(reclaim).split("(")[0].strip()
        return disk

    # Fallback: parse plain-text `docker system df`
    ok, out, _ = _run_docker(["system", "df"])
    if not ok:
        return disk

    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        kind = parts[0].lower()
        size = parts[2] if len(parts) > 2 else "0B"
        reclaim = parts[3] if len(parts) > 3 else "0B"
        if kind == "images":
            disk.images_size = size
            disk.images_reclaimable = reclaim.split("(")[0]
        elif kind == "containers":
            disk.containers_size = size
            disk.containers_reclaimable = reclaim.split("(")[0]
        elif kind == "local":
            disk.volumes_size = size
            disk.volumes_reclaimable = reclaim.split("(")[0]
    return disk


def _match_container(match: str, container: DockerContainer) -> bool:
    m = match.lower()
    return m in container.name.lower() or m in container.image.lower()


def _resolve_expected(
    expected_configs: list[dict],
    containers: list[DockerContainer],
) -> list[ExpectedContainer]:
    results = []
    for cfg in expected_configs:
        name = cfg["name"]
        pattern = cfg["match"]
        matched = None
        for c in containers:
            if _match_container(pattern, c):
                matched = c
                break

        results.append(ExpectedContainer(
            name=name,
            match=pattern,
            found=matched is not None,
            running=matched.is_running if matched else False,
            matched_container=matched.name if matched else None,
        ))
    return results


def collect_docker(docker_config: Optional[dict] = None) -> DockerReport:
    """
    Collect Docker container, image, and disk usage information.

    Args:
        docker_config: Optional dict with keys:
            enabled (bool, default True)
            containers: list of {name, match} expected containers
    """
    cfg = docker_config or {}
    ts = datetime.now(timezone.utc).isoformat()

    if cfg.get("enabled") is False:
        return DockerReport(timestamp=ts, available=False, error="disabled in config")

    ok, version, err = _run_docker(["info", "--format", "{{.ServerVersion}}"])
    if not ok:
        return DockerReport(timestamp=ts, available=False, error=err or "docker unavailable")

    containers = _list_containers()
    images = _list_images()
    disk = _docker_disk_usage()
    expected = _resolve_expected(cfg.get("containers", []), containers)

    return DockerReport(
        timestamp=ts,
        available=True,
        server_version=version.strip(),
        containers=containers,
        images=images,
        disk=disk,
        expected=expected,
    )


def reclaimable_bytes(disk: DockerDiskUsage) -> float:
    """Total reclaimable Docker disk across images, containers, volumes, cache."""
    total = 0.0
    for val in (
        disk.images_reclaimable,
        disk.containers_reclaimable,
        disk.volumes_reclaimable,
        disk.build_cache_reclaimable,
    ):
        total += _parse_size_bytes(val.split("(")[0].strip())
    return total
