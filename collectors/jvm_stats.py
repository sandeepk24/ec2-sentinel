"""
JVM runtime stats via jcmd (and /proc fallbacks).

Collects heap usage, GC activity, threads, uptime, JVM args, and heap flags
for running Java processes when jcmd is available.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class JavaJvmStats:
    pid: int
    available: bool = False
    error: str = ""
    source: str = ""  # jcmd | proc-only
  # Heap (bytes)
    heap_used_bytes: Optional[int] = None
    heap_max_bytes: Optional[int] = None
    heap_committed_bytes: Optional[int] = None
    heap_used_percent: Optional[float] = None
    heap_config: str = ""  # -Xmx/-Xms summary from VM.flags
    # GC
    young_gc_count: Optional[int] = None
    full_gc_count: Optional[int] = None
    gc_time_ms: Optional[float] = None
    gc_time_percent: Optional[float] = None  # gc_time / uptime
    # Threads & uptime
    thread_count: Optional[int] = None
    uptime_seconds: Optional[float] = None
    jvm_args: str = ""  # VM.command_line or parsed cmdline flags
    # Flags
    heap_pressure: bool = False
    excessive_gc: bool = False
    high_threads: bool = False
    issues: list[str] = field(default_factory=list)


def _find_jcmd(java_path: Optional[str], java_home: Optional[str]) -> Optional[str]:
    candidates: list[str] = []
    if java_path:
        candidates.append(str(Path(java_path).parent / "jcmd"))
    if java_home:
        candidates.append(str(Path(java_home) / "bin" / "jcmd"))
    which = __import__("shutil").which("jcmd")
    if which:
        candidates.append(which)
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _run_jcmd(jcmd: str, pid: int, subcmd: str, timeout: float = 8.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [jcmd, str(pid), subcmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (result.stdout or "").strip()
        if result.returncode != 0:
            err = (result.stderr or out or "").strip()
            return False, err
        return True, out
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _proc_thread_count(pid: int) -> Optional[int]:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("Threads:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _parse_uptime(output: str) -> Optional[float]:
    # "12345.678 s" or "12345.678"
    m = re.search(r"([\d.]+)\s*s", output)
    if m:
        return float(m.group(1))
    m = re.search(r"^([\d.]+)$", output.strip().splitlines()[-1])
    return float(m.group(1)) if m else None


def _parse_heap_info(output: str) -> dict:
    """Parse jcmd GC.heap_info text into used/max/committed bytes."""
    used = 0
    committed = 0
    max_heap = 0
    current_section = ""

    for line in output.splitlines():
        lower = line.lower().strip()
        if "heap" in lower and "capacity" in lower:
            current_section = "heap"
        elif "eden" in lower or "old" in lower or "survivor" in lower:
            current_section = lower.split(":")[0].strip()

        cap = re.search(r"capacity \(bytes\):\s*(\d+)", line)
        used_m = re.search(r"used\s+\(bytes\):\s*(\d+)", line)
        if used_m:
            used += int(used_m.group(1))
        if cap:
            committed += int(cap.group(1))

        # G1 / some JVMs report total max differently
        max_m = re.search(r"MaxHeapSize\s*=\s*(\d+)", line)
        if max_m:
            max_heap = max(max_heap, int(max_m.group(1)))

    # If we only got committed, use it as max estimate when max unknown
    if max_heap == 0 and committed > 0:
        max_heap = committed

    return {
        "heap_used_bytes": used or None,
        "heap_committed_bytes": committed or None,
        "heap_max_bytes": max_heap or committed or None,
    }


def _parse_vm_flags(output: str) -> str:
    """Compact heap-related flags from VM.flags."""
    flags: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if any(k in line for k in ("-Xmx", "-Xms", "-Xss", "-XX:Max", "-XX:+Use", "Heap")):
            flags.append(line)
    return " ".join(flags[:12])


def _parse_jstat_gcutil(output: str) -> dict:
    """Parse jstat -gcutil last line for GC counts and time."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if len(lines) < 2:
        return {}
    header = lines[0].split()
    values = lines[-1].split()
    if len(values) != len(header):
        return {}
    data = dict(zip(header, values))
    try:
        ygc = int(float(data.get("YGC", 0)))
        fgc = int(float(data.get("FGC", 0)))
        gct = float(data.get("GCT", 0)) * 1000  # seconds → ms
        return {"young_gc_count": ygc, "full_gc_count": fgc, "gc_time_ms": gct}
    except (ValueError, TypeError):
        return {}


def _run_jstat(java_path: Optional[str], pid: int) -> dict:
    jstat = None
    if java_path:
        candidate = str(Path(java_path).parent / "jstat")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            jstat = candidate
    if not jstat:
        jstat = __import__("shutil").which("jstat")
    if not jstat:
        return {}
    try:
        result = subprocess.run(
            [jstat, "-gcutil", str(pid), "250", "2"],
            capture_output=True,
            text=True,
            timeout=6,
        )
        if result.returncode != 0:
            return {}
        return _parse_jstat_gcutil(result.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return {}


def _evaluate_stats(
    stats: JavaJvmStats,
    cfg: dict,
) -> None:
    heap_warn = cfg.get("heap_warn_percent", 85)
    heap_crit = cfg.get("heap_crit_percent", 95)
    thread_warn = cfg.get("thread_warn", 500)
    thread_crit = cfg.get("thread_crit", 1000)
    gc_time_warn = cfg.get("gc_time_warn_percent", 15)
    full_gc_warn = cfg.get("full_gc_warn", 10)

    if stats.heap_used_percent is not None:
        if stats.heap_used_percent >= heap_crit:
            stats.heap_pressure = True
            stats.issues.append(
                f"Heap at {stats.heap_used_percent:.0f}% (critical ≥{heap_crit}%)"
            )
        elif stats.heap_used_percent >= heap_warn:
            stats.heap_pressure = True
            stats.issues.append(
                f"Heap at {stats.heap_used_percent:.0f}% (warning ≥{heap_warn}%)"
            )

    if stats.thread_count is not None:
        if stats.thread_count >= thread_crit:
            stats.high_threads = True
            stats.issues.append(
                f"{stats.thread_count} threads (critical ≥{thread_crit})"
            )
        elif stats.thread_count >= thread_warn:
            stats.high_threads = True
            stats.issues.append(
                f"{stats.thread_count} threads (warning ≥{thread_warn})"
            )

    if stats.gc_time_percent is not None and stats.gc_time_percent >= gc_time_warn:
        stats.excessive_gc = True
        stats.issues.append(
            f"GC time {stats.gc_time_percent:.1f}% of uptime (≥{gc_time_warn}%)"
        )

    if stats.full_gc_count is not None and stats.full_gc_count >= full_gc_warn:
        stats.excessive_gc = True
        stats.issues.append(
            f"{stats.full_gc_count} full GC cycles (≥{full_gc_warn})"
        )


def collect_jvm_stats(
    pid: int,
    java_path: Optional[str] = None,
    java_home: Optional[str] = None,
    cmdline: str = "",
    java_cfg: Optional[dict] = None,
) -> JavaJvmStats:
    """Collect JVM stats for one process; best-effort via jcmd."""
    cfg = java_cfg or {}
    stats = JavaJvmStats(pid=pid)
    stats.thread_count = _proc_thread_count(pid)

    jcmd = _find_jcmd(java_path, java_home)
    if not jcmd:
        stats.source = "proc-only"
        stats.available = stats.thread_count is not None
        if not stats.available:
            stats.error = "jcmd not found"
        return stats

    ok, uptime_out = _run_jcmd(jcmd, pid, "VM.uptime")
    if ok:
        stats.uptime_seconds = _parse_uptime(uptime_out)
        stats.source = "jcmd"

    ok, heap_out = _run_jcmd(jcmd, pid, "GC.heap_info")
    if ok:
        heap = _parse_heap_info(heap_out)
        stats.heap_used_bytes = heap.get("heap_used_bytes")
        stats.heap_max_bytes = heap.get("heap_max_bytes")
        stats.heap_committed_bytes = heap.get("heap_committed_bytes")
        if stats.heap_used_bytes and stats.heap_max_bytes:
            stats.heap_used_percent = round(
                (stats.heap_used_bytes / stats.heap_max_bytes) * 100, 1
            )

    ok, flags_out = _run_jcmd(jcmd, pid, "VM.flags")
    if ok:
        stats.heap_config = _parse_vm_flags(flags_out)

    ok, cmd_out = _run_jcmd(jcmd, pid, "VM.command_line")
    if ok and cmd_out:
        stats.jvm_args = cmd_out[:500]
    elif cmdline:
        # Extract JVM flags from proc cmdline
        parts = cmdline.split()
        flags = [p for p in parts if p.startswith("-X") or p.startswith("-XX:")]
        stats.jvm_args = " ".join(flags[:20]) or cmdline[:300]

    jstat_data = _run_jstat(java_path, pid)
    if jstat_data:
        stats.young_gc_count = jstat_data.get("young_gc_count")
        stats.full_gc_count = jstat_data.get("full_gc_count")
        stats.gc_time_ms = jstat_data.get("gc_time_ms")
        if stats.gc_time_ms and stats.uptime_seconds and stats.uptime_seconds > 0:
            stats.gc_time_percent = round(
                (stats.gc_time_ms / 1000 / stats.uptime_seconds) * 100, 2
            )

    stats.available = any([
        stats.heap_used_percent is not None,
        stats.uptime_seconds is not None,
        stats.jvm_args,
        stats.thread_count is not None,
    ])
    if not stats.available:
        stats.error = "jcmd returned no usable data"

    _evaluate_stats(stats, cfg)
    return stats


def jvm_stats_to_dict(stats: JavaJvmStats) -> dict:
    return {
        "available": stats.available,
        "error": stats.error,
        "source": stats.source,
        "heap_used_bytes": stats.heap_used_bytes,
        "heap_max_bytes": stats.heap_max_bytes,
        "heap_committed_bytes": stats.heap_committed_bytes,
        "heap_used_percent": stats.heap_used_percent,
        "heap_config": stats.heap_config,
        "young_gc_count": stats.young_gc_count,
        "full_gc_count": stats.full_gc_count,
        "gc_time_ms": stats.gc_time_ms,
        "gc_time_percent": stats.gc_time_percent,
        "thread_count": stats.thread_count,
        "uptime_seconds": stats.uptime_seconds,
        "jvm_args": stats.jvm_args,
        "heap_pressure": stats.heap_pressure,
        "excessive_gc": stats.excessive_gc,
        "high_threads": stats.high_threads,
        "issues": list(stats.issues),
    }
