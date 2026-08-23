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
    user_percent: float = 0.0
    system_percent: float = 0.0
    iowait_percent: float = 0.0
    idle_percent: float = 0.0
    irq_percent: float = 0.0

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
    buffers_bytes: int = 0
    cached_bytes: int = 0
    free_bytes: int = 0
    shared_bytes: int = 0
    # App memory ≈ used - buffers - cached (rough, for storytelling)
    app_bytes: int = 0

    @property
    def used_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return round((self.used_bytes / self.total_bytes) * 100, 1)

    @property
    def available_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return round((self.available_bytes / self.total_bytes) * 100, 1)

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
    cloud_provider: str = "unknown"  # aws | gcp | azure | local | unknown
    detection_source: str = ""       # imdsv2 | imdsv1 | cloud-init | local


@dataclass
class OsInfo:
    """Auto-detected Linux (or host) OS flavor and version."""
    name: str = "unknown"            # PrettyName e.g. "Ubuntu 22.04.4 LTS"
    id: str = "unknown"              # ubuntu, amzn, rhel, debian, rocky, sles…
    id_like: str = ""                # debian / rhel fedora
    version: str = "unknown"         # human version string
    version_id: str = "unknown"      # 22.04, 9, 2023.3.20240304
    version_codename: str = ""       # jammy, bookworm
    family: str = "unknown"          # debian | rhel | suse | amazon | other
    kernel: str = "unknown"          # uname -r
    arch: str = "unknown"            # x86_64, aarch64
    platform: str = "unknown"        # linux | darwin | windows | other

    @property
    def display(self) -> str:
        """Compact label for dashboards: 'Ubuntu 22.04 (jammy) · 5.15.0-x86_64'."""
        parts = []
        if self.name and self.name != "unknown":
            parts.append(self.name)
        elif self.id != "unknown":
            ver = self.version_id if self.version_id != "unknown" else self.version
            parts.append(f"{self.id} {ver}".strip())
        else:
            parts.append(self.platform)
        detail = []
        if self.version_codename:
            detail.append(self.version_codename)
        if self.arch and self.arch != "unknown":
            detail.append(self.arch)
        if detail and parts:
            parts[0] = f"{parts[0]} ({', '.join(detail)})"
        if self.kernel and self.kernel != "unknown":
            parts.append(f"kernel {self.kernel}")
        return " · ".join(parts) if parts else "unknown"


@dataclass
class SystemReport:
    timestamp: str
    cpu: CpuSnapshot
    memory: MemorySnapshot
    disks: list[DiskPartition]
    ec2: Ec2Metadata
    uptime_seconds: float
    os: OsInfo = field(default_factory=OsInfo)

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
    total = max(sum(deltas), 1)
    # user, nice, system, idle, iowait, irq, softirq, steal
    user = deltas[0] + deltas[1]
    system = deltas[2]
    idle = deltas[3]
    iowait = deltas[4]
    irq = deltas[5] + deltas[6]
    steal = deltas[7] if len(deltas) > 7 else 0

    def pct(v: int) -> float:
        return round((v / total) * 100, 1)

    usage = round(((total - idle - iowait) / total) * 100, 1)
    core_count = os.cpu_count() or 1
    load1, load5, load15 = os.getloadavg()

    return CpuSnapshot(
        usage_percent=usage,
        core_count=core_count,
        load_avg_1=round(load1, 2),
        load_avg_5=round(load5, 2),
        load_avg_15=round(load15, 2),
        steal_percent=pct(steal),
        user_percent=pct(user),
        system_percent=pct(system),
        iowait_percent=pct(iowait),
        idle_percent=pct(idle),
        irq_percent=pct(irq),
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
    free = info.get("MemFree", 0)
    buffers = info.get("Buffers", 0)
    cached = info.get("Cached", 0) + info.get("SReclaimable", 0)
    shared = info.get("Shmem", 0)
    used = total - available
    # Rough app footprint: what's not free and not reclaimable cache/buffers
    app = max(total - free - buffers - cached, 0)
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
        buffers_bytes=buffers,
        cached_bytes=cached,
        free_bytes=free,
        shared_bytes=shared,
        app_bytes=app,
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
    Fetch EC2 instance metadata via IMDSv2, with IMDSv1 and cloud-init fallbacks.

    Auto-detects instance type, region, and cloud provider. Works on Amazon Linux,
    Ubuntu, RHEL, etc. Falls back gracefully when not on a cloud instance.
    """
    meta = Ec2Metadata()

    if _try_imdsv2(meta):
        meta.cloud_provider = "aws"
        meta.detection_source = "imdsv2"
        return meta

    if _try_imdsv1(meta):
        meta.cloud_provider = "aws"
        meta.detection_source = "imdsv1"
        return meta

    if _try_cloud_init(meta):
        return meta

    # Local / non-cloud host
    import socket
    import platform as plat
    meta.cloud_provider = "local"
    meta.detection_source = "local"
    meta.hostname = socket.gethostname()
    try:
        meta.private_ip = socket.gethostbyname(meta.hostname)
    except OSError:
        meta.private_ip = "unknown"
    # Surface machine class when not on EC2 so dashboards aren't blank
    machine = plat.machine() or "unknown"
    meta.instance_type = f"local/{machine}"
    return meta


def _imds_get(path: str, token: Optional[str] = None, timeout: float = 2.0) -> str:
    headers = {}
    if token:
        headers["X-aws-ec2-metadata-token"] = token
    req = urllib.request.Request(
        f"http://169.254.169.254/latest/meta-data/{path}",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode().strip()


def _fill_aws_meta(meta: Ec2Metadata, getter) -> None:
    """Populate Ec2Metadata fields from a path→value getter."""
    try:
        meta.instance_id = getter("instance-id") or meta.instance_id
    except Exception:
        pass
    try:
        meta.instance_type = getter("instance-type") or meta.instance_type
    except Exception:
        pass
    try:
        meta.availability_zone = getter("placement/availability-zone") or meta.availability_zone
        if meta.availability_zone and meta.availability_zone != "unknown":
            meta.region = meta.availability_zone[:-1]
    except Exception:
        pass
    try:
        meta.ami_id = getter("ami-id") or meta.ami_id
    except Exception:
        pass
    try:
        meta.private_ip = getter("local-ipv4") or meta.private_ip
    except Exception:
        pass
    try:
        meta.hostname = getter("hostname") or meta.hostname
    except Exception:
        pass


def _try_imdsv2(meta: Ec2Metadata) -> bool:
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(token_req, timeout=2) as resp:
            token = resp.read().decode()

        def _get(path: str) -> str:
            return _imds_get(path, token=token)

        _fill_aws_meta(meta, _get)
        return meta.instance_type != "unknown" or meta.instance_id != "unknown"
    except Exception:
        return False


def _try_imdsv1(meta: Ec2Metadata) -> bool:
    """Older EC2 / some AMIs still allow IMDSv1 without a session token."""
    try:
        def _get(path: str) -> str:
            return _imds_get(path, token=None)

        _fill_aws_meta(meta, _get)
        return meta.instance_type != "unknown" or meta.instance_id != "unknown"
    except Exception:
        return False


def _try_cloud_init(meta: Ec2Metadata) -> bool:
    """
    Read cloud-init instance-data.json when IMDS is blocked (common with
    hop-limit / IMDSv2-required misconfig). Present on most cloud AMIs.
    """
    candidates = [
        Path("/run/cloud-init/instance-data.json"),
        Path("/var/lib/cloud/instance/instance-data.json"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue

        v1 = data.get("v1") or {}
        ds = data.get("ds") or {}
        meta_data = ds.get("meta-data") or ds.get("meta_data") or {}

        cloud_name = (v1.get("cloud_name") or data.get("cloud-name") or "").lower()
        if "aws" in cloud_name or "ec2" in cloud_name or meta_data.get("instance-type"):
            meta.cloud_provider = "aws"
        elif "azure" in cloud_name:
            meta.cloud_provider = "azure"
        elif "gce" in cloud_name or "gcp" in cloud_name:
            meta.cloud_provider = "gcp"
        else:
            meta.cloud_provider = cloud_name or "unknown"

        meta.instance_id = (
            str(v1.get("instance_id") or meta_data.get("instance-id") or meta.instance_id)
        )
        meta.instance_type = str(
            v1.get("instance_type")
            or meta_data.get("instance-type")
            or meta_data.get("instanceType")
            or meta.instance_type
        )

        placement = meta_data.get("placement") if isinstance(meta_data.get("placement"), dict) else {}
        region = v1.get("region") or placement.get("region") or meta_data.get("region")
        if region:
            meta.region = str(region)

        az = v1.get("availability_zone") or placement.get("availability-zone") or placement.get("availabilityZone")
        if az:
            meta.availability_zone = str(az)
            if meta.region == "unknown" and len(str(az)) > 1:
                meta.region = str(az)[:-1]

        meta.hostname = str(v1.get("hostname") or meta.hostname)
        if meta.hostname == "unknown":
            import socket
            meta.hostname = socket.gethostname()

        meta.detection_source = "cloud-init"
        return meta.instance_type != "unknown" or meta.instance_id != "unknown"

    return False


def collect_os_info() -> OsInfo:
    """
    Auto-detect Linux distribution flavor and version across Amazon Linux,
    Ubuntu, Debian, RHEL, Rocky, Alma, SLES, and others.

    Primary source: /etc/os-release (systemd standard). Fallbacks cover older
    RHEL-family releases and non-Linux hosts (macOS/dev laptops).
    """
    import platform as plat

    info = OsInfo()
    system = plat.system().lower()
    info.platform = {
        "linux": "linux",
        "darwin": "darwin",
        "windows": "windows",
    }.get(system, system or "other")
    info.kernel = plat.release() or "unknown"
    info.arch = plat.machine() or "unknown"

    os_release = _parse_os_release()
    if os_release:
        info.name = os_release.get("PRETTY_NAME") or os_release.get("NAME") or info.name
        info.id = (os_release.get("ID") or info.id).lower()
        info.id_like = (os_release.get("ID_LIKE") or "").lower()
        info.version = os_release.get("VERSION") or info.version
        info.version_id = os_release.get("VERSION_ID") or info.version_id
        info.version_codename = (
            os_release.get("VERSION_CODENAME")
            or os_release.get("UBUNTU_CODENAME")
            or ""
        ).lower()
        info.family = _os_family(info.id, info.id_like)
        return info

    # Legacy RHEL / Amazon Linux without modern os-release
    import re
    for legacy in (
        Path("/etc/system-release"),
        Path("/etc/redhat-release"),
        Path("/etc/centos-release"),
        Path("/etc/SuSE-release"),
    ):
        if not legacy.exists():
            continue
        try:
            text = legacy.read_text().strip().splitlines()[0]
        except OSError:
            continue
        if not text:
            continue
        info.name = text
        lower = text.lower()
        if "amazon" in lower:
            info.id = "amzn"
            info.family = "amazon"
        elif "red hat" in lower or "rhel" in lower:
            info.id = "rhel"
            info.family = "rhel"
        elif "centos" in lower:
            info.id = "centos"
            info.family = "rhel"
        elif "suse" in lower:
            info.id = "sles"
            info.family = "suse"
        m = re.search(r"(\d+(?:\.\d+)*)", text)
        if m:
            info.version_id = m.group(1)
            info.version = m.group(1)
        return info

    # macOS / other
    if info.platform == "darwin":
        info.id = "macos"
        info.family = "darwin"
        info.name = f"macOS {plat.mac_ver()[0]}" if plat.mac_ver()[0] else "macOS"
        info.version = plat.mac_ver()[0] or info.version
        info.version_id = info.version
    elif info.platform == "linux":
        info.name = f"Linux {info.kernel}"
        info.id = "linux"
        info.family = "other"
    else:
        info.name = f"{plat.system()} {plat.release()}".strip()
        info.id = info.platform

    return info


def _parse_os_release() -> dict:
    """Parse KEY=VALUE lines from os-release files."""
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        if not path.exists():
            continue
        try:
            raw = path.read_text()
        except OSError:
            continue
        result = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            result[key.strip()] = val
        if result:
            return result
    return {}


def _os_family(os_id: str, id_like: str) -> str:
    """Map distro id to a coarse family for package-manager-aware tips."""
    blob = f"{os_id} {id_like}".lower()
    if os_id in ("amzn", "amazon") or "amazon" in blob:
        return "amazon"
    if any(x in blob for x in ("rhel", "centos", "rocky", "alma", "fedora", "oracle")):
        return "rhel"
    if any(x in blob for x in ("debian", "ubuntu", "pop", "linuxmint", "raspbian")):
        return "debian"
    if any(x in blob for x in ("sles", "suse", "opensuse")):
        return "suse"
    if "arch" in blob:
        return "arch"
    return "other"


def collect_uptime() -> float:
    """Return system uptime in seconds."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError):
        # macOS / non-Linux
        try:
            import subprocess
            out = subprocess.check_output(["sysctl", "-n", "kern.boottime"], text=True, timeout=2)
            # { sec = 123, usec = 0 } Thu Jan 1 ...
            import re
            m = re.search(r"sec\s*=\s*(\d+)", out)
            if m:
                return max(time.time() - int(m.group(1)), 0.0)
        except Exception:
            pass
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
        os=collect_os_info(),
    )
