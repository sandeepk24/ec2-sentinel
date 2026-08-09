"""
System-level health collection: CPU, memory, disk, swap, network, EC2 metadata.

This is the bread and butter — the stuff you check first when you SSH into a box.
"""

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes — every collector returns structured data, never raw dicts
# ---------------------------------------------------------------------------

@dataclass
class CpuSnapshot:
    usage_percent: float
    core_count: int
    load_avg_1: float
    load_avg_5: float
    load_avg_15: float
    steal_percent: float  # nonzero = noisy neighbor or T-series credit exhaustion

    @property
    def load_per_core(self) -> float:
        return round(self.load_avg_1 / max(self.core_count, 1), 2)

    @property
    def is_overloaded(self) -> bool:
        return self.load_avg_1 > self.core_count


@dataclass
class MemorySnapshot:
    total_bytes: int
    available_bytes: int
    used_bytes: int
    swap_total_bytes: int
    swap_used_bytes: int
    oom_kill_count: int  # from /proc — how many OOM kills since boot

    @property
    def used_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return round((self.used_bytes / self.total_bytes) * 100, 1)

    @property
    def swap_used_percent(self) -> float:
        if self.swap_total_bytes == 0:
            return 0.0
        return round((self.swap_used_bytes / self.swap_total_bytes) * 100, 1)

    def _fmt(self, b: int) -> str:
        gb = b / (1024 ** 3)
        return f"{gb:.1f} GB"

    @property
    def summary(self) -> str:
        return f"{self._fmt(self.used_bytes)} / {self._fmt(self.total_bytes)} ({self.used_percent}%)"


@dataclass
class DiskPartition:
    mount: str
    device: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    inode_used_percent: float
    growth_rate_bytes_per_day: Optional[float] = None  # predicted from history

    @property
    def used_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return round((self.used_bytes / self.total_bytes) * 100, 1)

    @property
    def days_until_full(self) -> Optional[float]:
        if self.growth_rate_bytes_per_day and self.growth_rate_bytes_per_day > 0:
            return round(self.free_bytes / self.growth_rate_bytes_per_day, 1)
        return None


@dataclass
class Ec2Metadata:
    instance_id: str = "unknown"
    instance_type: str = "unknown"
    region: str = "unknown"
    availability_zone: str = "unknown"
    ami_id: str = "unknown"
    private_ip: str = "unknown"
    hostname: str = "unknown"


@dataclass
class SystemReport:
    timestamp: str
    cpu: CpuSnapshot
    memory: MemorySnapshot
    disks: list[DiskPartition]
    ec2: Ec2Metadata
    uptime_seconds: float

    @property
    def uptime_human(self) -> str:
        s = int(self.uptime_seconds)
        days, remainder = divmod(s, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m {secs}s"


# ---------------------------------------------------------------------------
# History file for disk growth tracking
# ---------------------------------------------------------------------------

DISK_HISTORY_FILE = Path("/tmp/ec2_sentinel_disk_history.json")


def _load_disk_history() -> dict:
    if DISK_HISTORY_FILE.exists():
        try:
            return json.loads(DISK_HISTORY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_disk_history(history: dict) -> None:
    try:
        DISK_HISTORY_FILE.write_text(json.dumps(history))
    except OSError:
        pass  # best effort — /tmp might be read-only in edge cases


# ---------------------------------------------------------------------------
# Collectors — each reads from /proc or /sys, no psutil dependency
# ---------------------------------------------------------------------------

def collect_cpu() -> CpuSnapshot:
    """Read CPU usage from /proc/stat with a 0.5s sample window."""
    def _read_stat():
        with open("/proc/stat") as f:
            parts = f.readline().split()
        # user, nice, system, idle, iowait, irq, softirq, steal
        vals = [int(x) for x in parts[1:9]]
        return vals

    t1 = _read_stat()
    time.sleep(0.5)
    t2 = _read_stat()

    deltas = [t2[i] - t1[i] for i in range(len(t1))]
    total = sum(deltas)
    idle = deltas[3] + deltas[4]  # idle + iowait
    steal = deltas[7] if len(deltas) > 7 else 0

    usage = round(((total - idle) / max(total, 1)) * 100, 1)
    steal_pct = round((steal / max(total, 1)) * 100, 1)
    core_count = os.cpu_count() or 1
    load1, load5, load15 = os.getloadavg()

    return CpuSnapshot(
        usage_percent=usage,
        core_count=core_count,
        load_avg_1=round(load1, 2),
        load_avg_5=round(load5, 2),
        load_avg_15=round(load15, 2),
        steal_percent=steal_pct,
    )


def collect_memory() -> MemorySnapshot:
    """Read memory stats from /proc/meminfo."""
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            parts = line.split()
            key = parts[0].rstrip(":")
            val = int(parts[1]) * 1024  # convert kB to bytes
            info[key] = val

    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    used = total - available
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = swap_total - swap_free

    # Count OOM kills from kernel log (best effort)
    oom_count = 0
    try:
        with open("/proc/vmstat") as f:
            for line in f:
                if line.startswith("oom_kill"):
                    oom_count = int(line.split()[1])
                    break
    except (OSError, ValueError, IndexError):
        pass

    return MemorySnapshot(
        total_bytes=total,
        available_bytes=available,
        used_bytes=used,
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
        oom_kill_count=oom_count,
    )


def collect_disks(mounts: Optional[list[str]] = None) -> list[DiskPartition]:
    """
    Collect disk usage for specified mount points.
    If mounts is None, auto-detect real filesystems (skip tmpfs, devtmpfs, etc).
    """
    # Auto-detect mounts from /proc/mounts
    if mounts is None:
        mounts = []
        skip_fs = {"tmpfs", "devtmpfs", "sysfs", "proc", "cgroup", "cgroup2",
                    "overlay", "squashfs", "devpts", "securityfs", "debugfs",
                    "pstore", "bpf", "hugetlbfs", "mqueue", "configfs", "fusectl"}
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] not in skip_fs:
                        mount = parts[1]
                        if not mount.startswith("/snap") and not mount.startswith("/sys"):
                            mounts.append(mount)
        except OSError:
            mounts = ["/"]

    # Deduplicate while preserving order
    seen = set()
    unique_mounts = []
    for m in mounts:
        if m not in seen:
            seen.add(m)
            unique_mounts.append(m)

    history = _load_disk_history()
    now = time.time()
    partitions = []

    for mount in unique_mounts:
        try:
            stat = os.statvfs(mount)
        except OSError:
            continue

        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize  # available to non-root
        used = total - (stat.f_bfree * stat.f_frsize)

        # Inode usage
        inode_total = stat.f_files
        inode_free = stat.f_favail
        inode_used_pct = 0.0
        if inode_total > 0:
            inode_used_pct = round(((inode_total - inode_free) / inode_total) * 100, 1)

        # Device name
        device = "unknown"
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == mount:
                        device = parts[0]
                        break
        except OSError:
            pass

        # Disk growth prediction
        growth_rate = None
        key = mount
        if key in history:
            prev_used, prev_time = history[key]
            elapsed = now - prev_time
            if elapsed > 300:  # at least 5 minutes between samples
                delta = used - prev_used
                if delta > 0:
                    growth_rate = (delta / elapsed) * 86400  # bytes per day

        # Update history
        history[key] = (used, now)

        partitions.append(DiskPartition(
            mount=mount,
            device=device,
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            inode_used_percent=inode_used_pct,
            growth_rate_bytes_per_day=growth_rate,
        ))

    _save_disk_history(history)
    return partitions


def collect_ec2_metadata() -> Ec2Metadata:
    """
    Fetch EC2 instance metadata via IMDSv2.
    Falls back gracefully if not on EC2 or IMDS is disabled.
    """
    meta = Ec2Metadata()

    try:
        # IMDSv2: get token first
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(token_req, timeout=2) as resp:
            token = resp.read().decode()

        def _get(path: str) -> str:
            req = urllib.request.Request(
                f"http://169.254.169.254/latest/meta-data/{path}",
                headers={"X-aws-ec2-metadata-token": token},
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.read().decode().strip()

        meta.instance_id = _get("instance-id")
        meta.instance_type = _get("instance-type")
        meta.availability_zone = _get("placement/availability-zone")
        meta.region = meta.availability_zone[:-1]  # strip AZ suffix
        meta.ami_id = _get("ami-id")
        meta.private_ip = _get("local-ipv4")
        meta.hostname = _get("hostname")

    except Exception:
        # Not on EC2, or IMDS disabled — that's fine
        import socket
        meta.hostname = socket.gethostname()
        meta.private_ip = socket.gethostbyname(socket.gethostname())

    return meta


def collect_uptime() -> float:
    """Return system uptime in seconds."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Main collection entry point
# ---------------------------------------------------------------------------

def collect_system(disk_mounts: Optional[list[str]] = None) -> SystemReport:
    """Run all system collectors and return a unified report."""
    return SystemReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        cpu=collect_cpu(),
        memory=collect_memory(),
        disks=collect_disks(disk_mounts),
        ec2=collect_ec2_metadata(),
        uptime_seconds=collect_uptime(),
    )
