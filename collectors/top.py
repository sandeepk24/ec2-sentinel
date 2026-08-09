"""
Top resource consumers — answers "where is the CPU/memory going?"

Samples /proc for ~1s to get real CPU%, ranks by RSS for memory.
No psutil.
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TopProcess:
    pid: int
    name: str
    cmdline: str
    cpu_percent: float
    memory_bytes: int
    memory_percent: float
    user: str = ""

    @property
    def memory_mb(self) -> float:
        return round(self.memory_bytes / (1024 * 1024), 1)


@dataclass
class TopReport:
    timestamp: str
    by_cpu: list[TopProcess] = field(default_factory=list)
    by_memory: list[TopProcess] = field(default_factory=list)
    sample_seconds: float = 1.0


def _read_proc_ticks(pid: int) -> Optional[int]:
    try:
        content = Path(f"/proc/{pid}/stat").read_text()
        close = content.rfind(")")
        fields = content[close + 2:].split()
        utime = int(fields[11])
        stime = int(fields[12])
        return utime + stime
    except (OSError, PermissionError, ValueError, IndexError):
        return None


def _read_rss(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, PermissionError, ValueError, IndexError):
        pass
    return 0


def _read_name_cmd(pid: int) -> tuple[str, str]:
    name = str(pid)
    cmdline = ""
    try:
        name = Path(f"/proc/{pid}/comm").read_text().strip() or name
    except (OSError, PermissionError):
        pass
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_text()
        cmdline = raw.replace("\x00", " ").strip()[:120]
    except (OSError, PermissionError):
        pass
    return name, cmdline or name


def _list_pids() -> list[int]:
    pids = []
    try:
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                pids.append(int(entry.name))
    except OSError:
        pass
    return pids


def collect_top(limit: int = 8, sample_seconds: float = 1.0) -> TopReport:
    """
    Sample process CPU over sample_seconds and return top consumers by CPU and memory.
    """
    clk = os.sysconf("SC_CLK_TCK")
    mem_total = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                    break
    except (OSError, ValueError, IndexError):
        pass

    pids = _list_pids()
    t0: dict[int, int] = {}
    for pid in pids:
        ticks = _read_proc_ticks(pid)
        if ticks is not None:
            t0[pid] = ticks

    time.sleep(max(sample_seconds, 0.3))

    cpu_rows: list[TopProcess] = []
    mem_rows: list[TopProcess] = []

    for pid in list(t0.keys()):
        t1 = _read_proc_ticks(pid)
        if t1 is None:
            continue
        delta = max(t1 - t0[pid], 0)
        cpu_pct = round((delta / clk / sample_seconds) * 100, 1)
        rss = _read_rss(pid)
        name, cmdline = _read_name_cmd(pid)
        mem_pct = round((rss / mem_total) * 100, 1) if mem_total else 0.0

        # Skip kernel threads / empty shells with nothing useful
        if cpu_pct <= 0 and rss <= 0:
            continue

        proc = TopProcess(
            pid=pid,
            name=name,
            cmdline=cmdline,
            cpu_percent=cpu_pct,
            memory_bytes=rss,
            memory_percent=mem_pct,
        )
        if cpu_pct > 0:
            cpu_rows.append(proc)
        if rss > 0:
            mem_rows.append(proc)

    cpu_rows.sort(key=lambda p: p.cpu_percent, reverse=True)
    mem_rows.sort(key=lambda p: p.memory_bytes, reverse=True)

    return TopReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        by_cpu=cpu_rows[:limit],
        by_memory=mem_rows[:limit],
        sample_seconds=sample_seconds,
    )
