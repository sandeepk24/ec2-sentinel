"""
Process health collector: track named services, detect restarts, measure per-process resources.

The kind of monitoring that answers "is JBoss actually running, or did systemd
restart it and it's stuck in a boot loop?"
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PID_HISTORY_FILE = Path("/tmp/ec2_sentinel_pid_history.json")


@dataclass
class ProcessInfo:
    name: str              # friendly name from config (e.g., "tomcat")
    match_pattern: str     # what we searched for in the process list
    found: bool
    pid: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_bytes: Optional[int] = None
    uptime_seconds: Optional[float] = None
    restart_detected: bool = False
    previous_pid: Optional[int] = None
    command: Optional[str] = None

    @property
    def status(self) -> str:
        if not self.found:
            return "NOT_FOUND"
        if self.restart_detected:
            return "RESTARTED"
        return "RUNNING"

    @property
    def memory_mb(self) -> Optional[float]:
        if self.memory_bytes is not None:
            return round(self.memory_bytes / (1024 * 1024), 1)
        return None


@dataclass
class ProcessReport:
    timestamp: str
    processes: list[ProcessInfo]

    @property
    def missing(self) -> list[ProcessInfo]:
        return [p for p in self.processes if not p.found]

    @property
    def restarted(self) -> list[ProcessInfo]:
        return [p for p in self.processes if p.restart_detected]


def _load_pid_history() -> dict:
    if PID_HISTORY_FILE.exists():
        try:
            return json.loads(PID_HISTORY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_pid_history(history: dict) -> None:
    try:
        PID_HISTORY_FILE.write_text(json.dumps(history))
    except OSError:
        pass


def _find_process(pattern: str) -> list[dict]:
    """
    Find processes matching a pattern in their command line.
    Uses /proc directly — no dependency on psutil or pgrep.
    """
    results = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            cmdline = (entry / "cmdline").read_text()
            cmdline = cmdline.replace("\x00", " ").strip()
            if not cmdline:
                continue
            if pattern.lower() in cmdline.lower():
                results.append({"pid": pid, "cmdline": cmdline})
        except (OSError, PermissionError):
            continue
    return results


def _get_process_stats(pid: int) -> dict:
    """Get CPU% and memory for a specific PID."""
    stats = {"cpu_percent": 0.0, "memory_bytes": 0, "start_time": 0.0}

    # Memory from /proc/[pid]/status
    try:
        status_path = Path(f"/proc/{pid}/status")
        for line in status_path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                stats["memory_bytes"] = int(parts[1]) * 1024  # kB to bytes
                break
    except (OSError, PermissionError, ValueError):
        pass

    # CPU — use /proc/[pid]/stat
    # Field 14 (utime) + field 15 (stime) = total CPU ticks
    # Field 22 (starttime) = process start time in clock ticks since boot
    try:
        stat_content = Path(f"/proc/{pid}/stat").read_text()
        # Handle processes with spaces/parens in their name
        # Format: pid (comm) state fields...
        close_paren = stat_content.rfind(")")
        fields_after = stat_content[close_paren + 2:].split()

        utime = int(fields_after[11])   # field 14, 0-indexed from after state
        stime = int(fields_after[12])   # field 15
        starttime = int(fields_after[19])  # field 22

        clk_tck = os.sysconf("SC_CLK_TCK")

        # Process uptime
        with open("/proc/uptime") as f:
            system_uptime = float(f.read().split()[0])
        process_start_seconds = starttime / clk_tck
        stats["start_time"] = system_uptime - process_start_seconds

        # Simple CPU% estimate (total ticks / process lifetime)
        total_ticks = utime + stime
        total_seconds = stats["start_time"]
        if total_seconds > 0:
            stats["cpu_percent"] = round(
                (total_ticks / clk_tck / total_seconds) * 100, 1
            )

    except (OSError, PermissionError, ValueError, IndexError):
        pass

    return stats


def collect_processes(process_configs: list[dict]) -> ProcessReport:
    """
    Check health of configured processes.

    Args:
        process_configs: List of dicts with keys:
            - name: friendly name (e.g., "tomcat")
            - match: string to search in cmdline (e.g., "org.apache.catalina")
    """
    pid_history = _load_pid_history()
    results = []

    for config in process_configs:
        name = config["name"]
        pattern = config["match"]

        matches = _find_process(pattern)

        if not matches:
            results.append(ProcessInfo(
                name=name,
                match_pattern=pattern,
                found=False,
                previous_pid=pid_history.get(name, {}).get("pid"),
            ))
            continue

        # Take the first match (if multiple, it's the lowest PID — typically the parent)
        proc = matches[0]
        pid = proc["pid"]
        stats = _get_process_stats(pid)

        # Restart detection: did the PID change since last check?
        restart_detected = False
        previous_pid = None
        if name in pid_history:
            prev = pid_history[name]
            if prev.get("pid") and prev["pid"] != pid:
                restart_detected = True
                previous_pid = prev["pid"]

        # Update history
        pid_history[name] = {"pid": pid, "last_seen": datetime.now(timezone.utc).isoformat()}

        results.append(ProcessInfo(
            name=name,
            match_pattern=pattern,
            found=True,
            pid=pid,
            cpu_percent=stats["cpu_percent"],
            memory_bytes=stats["memory_bytes"],
            uptime_seconds=stats.get("start_time"),
            restart_detected=restart_detected,
            previous_pid=previous_pid,
            command=proc["cmdline"][:200],  # truncate long command lines
        ))

    _save_pid_history(pid_history)

    return ProcessReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        processes=results,
    )
