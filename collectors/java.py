"""
Java / JDK collector: discover installed runtimes and running JVM processes.

Finds java binaries on PATH and common install locations, runs `java -version`,
detects JDK vs JRE via `javac`, and scans /proc for running JVMs (like
`ps -ef | grep java`) with PID, binary path, and command line.
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_SEARCH_PATHS = [
    "/usr/bin",
    "/usr/lib/jvm",
    "/usr/local",
    "/opt",
    "/opt/java",
    "/usr/lib64/jvm",
]


@dataclass
class JavaInstallation:
    path: str
    version: str
    vendor: str
    runtime_name: str
    raw_version: str
    is_jdk: bool = False
    javac_version: Optional[str] = None

    @property
    def display(self) -> str:
        kind = "JDK" if self.is_jdk else "JRE"
        return f"{self.vendor} {self.version} ({kind})"


@dataclass
class JavaProcess:
    pid: int
    name: str
    java_path: Optional[str]
    version: Optional[str]
    cmdline: str


@dataclass
class JavaReport:
    timestamp: str
    enabled: bool
    available: bool
    error: str = ""
    java_home: Optional[str] = None
    default_java: Optional[str] = None
    installations: list[JavaInstallation] = field(default_factory=list)
    processes: list[JavaProcess] = field(default_factory=list)

    @property
    def installation_count(self) -> int:
        return len(self.installations)

    @property
    def jdk_count(self) -> int:
        return sum(1 for j in self.installations if j.is_jdk)


def _parse_version_output(output: str) -> tuple[str, str, str]:
    """Return (version, vendor, runtime_name) from `java -version` output."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    first = lines[0] if lines else ""
    runtime_name = first

    vendor = "Unknown"
    lower = output.lower()
    if "amazon corretto" in lower or "corretto" in lower:
        vendor = "Amazon Corretto"
    elif "openjdk" in lower:
        vendor = "OpenJDK"
    elif "oracle" in lower:
        vendor = "Oracle"
    elif "temurin" in lower or "adoptium" in lower:
        vendor = "Eclipse Temurin"
    elif "zulu" in lower:
        vendor = "Azul Zulu"
    elif "graalvm" in lower:
        vendor = "GraalVM"
    elif "java" in lower:
        vendor = "Java"

    version = ""
    quoted = re.search(r'version "([^"]+)"', output)
    if quoted:
        version = quoted.group(1)
    else:
        bare = re.search(r"(?:openjdk|java|javac)\s+(\d+(?:\.\d+)*)", first, re.I)
        if bare:
            version = bare.group(1)

    if not version and len(lines) > 1:
        runtime_line = re.search(r'(\d+(?:\.\d+){0,3}(?:[_\-]\d+)*)', lines[1])
        if runtime_line:
            version = runtime_line.group(1)

    return version or "unknown", vendor, runtime_name


def _run_version(binary: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [binary, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stderr or result.stdout or "").strip()
        if not output:
            return False, ""
        return True, output
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def _resolve_real(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def _discover_java_binaries(search_paths: list[str]) -> list[str]:
    candidates: set[str] = set()

    for name in ("java",):
        path = shutil.which(name)
        if path:
            candidates.add(path)

    for base in search_paths:
        root = Path(base)
        if not root.exists():
            continue

        direct = root / "java"
        if direct.is_file() and os.access(direct, os.X_OK):
            candidates.add(str(direct))

        bin_java = root / "bin" / "java"
        if bin_java.is_file() and os.access(bin_java, os.X_OK):
            candidates.add(str(bin_java))

        if root.is_dir():
            try:
                for java_bin in root.rglob("bin/java"):
                    if java_bin.is_file() and os.access(java_bin, os.X_OK):
                        candidates.add(str(java_bin))
            except OSError:
                pass

    # Dedupe symlinks pointing to the same runtime
    unique: dict[str, str] = {}
    for path in sorted(candidates):
        real = _resolve_real(path)
        unique.setdefault(real, path)
    return list(unique.values())


def _inspect_installation(java_path: str) -> Optional[JavaInstallation]:
    ok, output = _run_version(java_path)
    if not ok:
        return None

    version, vendor, runtime_name = _parse_version_output(output)
    javac_path = Path(java_path).parent / "javac"
    is_jdk = False
    javac_version = None

    if javac_path.is_file() and os.access(javac_path, os.X_OK):
        javac_ok, javac_out = _run_version(str(javac_path))
        if javac_ok:
            is_jdk = True
            javac_version, _, _ = _parse_version_output(javac_out)

    return JavaInstallation(
        path=java_path,
        version=version,
        vendor=vendor,
        runtime_name=runtime_name,
        raw_version=output.splitlines()[0] if output else "",
        is_jdk=is_jdk,
        javac_version=javac_version,
    )


def _proc_name(pid: int) -> str:
    try:
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
        if comm:
            return comm
    except OSError:
        pass
    return "java"


def _proc_exe(pid: int) -> Optional[str]:
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
        if exe.startswith("/"):
            return exe
    except OSError:
        pass
    return None


def _looks_like_java_process(cmdline: str, comm: str) -> bool:
    """True if this process looks like a running JVM (ps -ef | grep java)."""
    lower = cmdline.lower()
    if any(x in lower for x in ("grep java", "java-version", "sentinel.py")):
        return False
    if comm == "java" or lower.endswith("/java"):
        return True
    if re.search(r"(?:^|\s)(?:/[\w./+-]+/)?java(?:\s|$)", cmdline):
        return True
    return " java " in f" {lower} "


def _running_java_processes(
    installations: Optional[list[JavaInstallation]] = None,
    max_processes: int = 20,
) -> list[JavaProcess]:
    version_by_path = {
        _resolve_real(j.path): j.version for j in (installations or [])
    }
    results: list[JavaProcess] = []

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return results

    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return results

    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            cmdline = (entry / "cmdline").read_text().replace("\x00", " ").strip()
        except OSError:
            continue
        if not cmdline:
            continue
        comm = _proc_name(pid)
        if not _looks_like_java_process(cmdline, comm):
            continue

        exe = _proc_exe(pid)
        version = version_by_path.get(_resolve_real(exe)) if exe else None
        results.append(JavaProcess(
            pid=pid,
            name=comm,
            java_path=exe,
            version=version,
            cmdline=cmdline[:200],
        ))

    results.sort(key=lambda p: p.pid)
    return results[:max_processes]


def collect_java(java_config: Optional[dict] = None) -> JavaReport:
    """
    Discover Java installations and running JVM processes.

    Config keys:
        enabled: bool (default True)
        track_processes: bool (default True) — scan /proc for JVMs (like ps -ef | grep java)
        search_paths: extra directories to scan for java binaries
    """
    cfg = java_config or {}
    ts = datetime.now(timezone.utc).isoformat()

    if cfg.get("enabled") is False:
        return JavaReport(timestamp=ts, enabled=False, available=False, error="disabled in config")

    track_processes = cfg.get("track_processes", True)

    search_paths = list(DEFAULT_SEARCH_PATHS)
    search_paths.extend(cfg.get("search_paths") or [])

    java_home = os.environ.get("JAVA_HOME") or None
    if java_home:
        search_paths.insert(0, java_home)
        search_paths.insert(0, str(Path(java_home) / "bin"))

    default_java = shutil.which("java")
    installations: list[JavaInstallation] = []
    seen_real: set[str] = set()

    for path in _discover_java_binaries(search_paths):
        real = _resolve_real(path)
        if real in seen_real:
            continue
        inst = _inspect_installation(path)
        if inst:
            seen_real.add(real)
            installations.append(inst)

    installations.sort(key=lambda j: (j.vendor, j.version, j.path))

    processes = _running_java_processes(installations) if track_processes else []

    if not installations and not processes:
        return JavaReport(
            timestamp=ts,
            enabled=True,
            available=False,
            error="no Java runtime or running JVM found",
            java_home=java_home,
            default_java=default_java,
            processes=processes,
        )

    error = ""
    if not installations and processes:
        error = "installed runtimes not detected; showing running JVMs only"

    return JavaReport(
        timestamp=ts,
        enabled=True,
        available=True,
        error=error,
        java_home=java_home,
        default_java=default_java,
        installations=installations,
        processes=processes,
    )
