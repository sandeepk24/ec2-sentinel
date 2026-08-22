"""
Actionable resource suggestions — pinpoint apps and give copy-paste commands.
"""

from dataclasses import dataclass
from typing import Optional

from collectors.docker import cleanup_suggestions, reclaimable_bytes


@dataclass
class ActionSuggestion:
    severity: str          # info | warning | critical
    category: str          # cpu | memory | disk | docker | io
    title: str
    command: str
    description: str
    process_name: str = ""
    pid: Optional[int] = None


def _proc_display(name: str, cmdline: str) -> str:
    """Human label for a process — prefer cmdline hint over comm name."""
    if cmdline and cmdline != name:
        short = cmdline.split()[0].rsplit("/", 1)[-1] if cmdline.split() else name
        if short and short != name:
            return f"{name} ({short})"
    return name


def _is_java(name: str, cmdline: str) -> bool:
    blob = f"{name} {cmdline}".lower()
    return "java" in blob


def resource_suggestions(
    system,
    top_report,
    docker_report=None,
    thresholds: Optional[dict] = None,
) -> list[ActionSuggestion]:
    """Build severity-ranked suggestions for CPU, memory, and disk pressure."""
    t = thresholds or {}
    cpu = system.cpu
    mem = system.memory
    suggestions: list[ActionSuggestion] = []

    top_cpu = top_report.by_cpu if top_report else []
    top_mem = top_report.by_memory if top_report else []
    leader_cpu = top_cpu[0] if top_cpu else None
    leader_mem = top_mem[0] if top_mem else None

    cpu_warn = t.get("cpu_warn", 80)
    cpu_crit = t.get("cpu_crit", 95)
    mem_warn = t.get("memory_warn", 80)
    mem_crit = t.get("memory_crit", 95)
    disk_warn = t.get("disk_warn", 75)
    disk_crit = t.get("disk_crit", 90)

    # ------------------------------------------------------------------ CPU hotspots
    if leader_cpu and (
        cpu.usage_percent >= cpu_warn
        or cpu.load_avg_1 > cpu.core_count
        or leader_cpu.cpu_percent >= 25
    ):
        label = _proc_display(leader_cpu.name, leader_cpu.cmdline)
        sev = "critical" if cpu.usage_percent >= cpu_crit or leader_cpu.cpu_percent >= 50 else "warning"
        suggestions.append(ActionSuggestion(
            severity=sev,
            category="cpu",
            title=f"{label} using {leader_cpu.cpu_percent}% CPU (pid {leader_cpu.pid})",
            command=f"top -H -p {leader_cpu.pid}",
            description=(
                f"Hottest process over {top_report.sample_seconds if top_report else 1}s sample. "
                "Shows per-thread CPU to find the busy thread."
            ),
            process_name=leader_cpu.name,
            pid=leader_cpu.pid,
        ))
        if _is_java(leader_cpu.name, leader_cpu.cmdline):
            suggestions.append(ActionSuggestion(
                severity=sev,
                category="cpu",
                title=f"Thread dump for Java process {leader_cpu.pid}",
                command=f"jstack {leader_cpu.pid} | head -200",
                description="Capture stack traces to see which Java code is burning CPU.",
                process_name=leader_cpu.name,
                pid=leader_cpu.pid,
            ))
        else:
            suggestions.append(ActionSuggestion(
                severity="info",
                category="cpu",
                title=f"Inspect {label} command line and open files",
                command=f"ps -p {leader_cpu.pid} -o pid,user,%cpu,rss,cmd && lsof -p {leader_cpu.pid} 2>/dev/null | head -20",
                description="Confirm what the process is doing before restarting or killing it.",
                process_name=leader_cpu.name,
                pid=leader_cpu.pid,
            ))

    for p in top_cpu[1:3]:
        if p.cpu_percent < 15:
            break
        label = _proc_display(p.name, p.cmdline)
        suggestions.append(ActionSuggestion(
            severity="info",
            category="cpu",
            title=f"{label} also high at {p.cpu_percent}% CPU",
            command=f"ps -p {p.pid} -o pid,%cpu,rss,cmd",
            description="Secondary CPU consumer — check if expected load or runaway worker.",
            process_name=p.name,
            pid=p.pid,
        ))

    if cpu.iowait_percent >= 10 and leader_cpu:
        suggestions.append(ActionSuggestion(
            severity="warning" if cpu.iowait_percent >= 20 else "info",
            category="io",
            title=f"Disk I/O wait at {cpu.iowait_percent}% — check heavy writers",
            command="iotop -oPa 2>/dev/null || (command -v docker >/dev/null && docker stats --no-stream)",
            description=(
                "High iowait means storage latency, not CPU saturation. "
                "Find processes doing heavy disk writes."
            ),
        ))

    if cpu.steal_percent >= 5:
        suggestions.append(ActionSuggestion(
            severity="critical" if cpu.steal_percent >= 10 else "warning",
            category="cpu",
            title=f"CPU steal at {cpu.steal_percent}% — instance may need resize",
            command="curl -s http://169.254.169.254/latest/meta-data/instance-type",
            description=(
                "Steal time means the hypervisor withheld CPU (common on T-series "
                "when credits run out). Check CloudWatch CPUCreditBalance."
            ),
        ))

    # ------------------------------------------------------------------ Memory hotspots
    if leader_mem and (
        mem.used_percent >= mem_warn
        or mem.swap_used_percent >= 10
        or leader_mem.memory_percent >= 10
    ):
        label = _proc_display(leader_mem.name, leader_mem.cmdline)
        sev = (
            "critical"
            if mem.used_percent >= mem_crit or mem.swap_used_percent >= 30
            else "warning"
        )
        suggestions.append(ActionSuggestion(
            severity=sev,
            category="memory",
            title=f"{label} using {leader_mem.memory_mb} MB ({leader_mem.memory_percent}% RAM)",
            command=f"ps -p {leader_mem.pid} -o pid,user,rss,vsz,%mem,cmd",
            description="Largest RSS consumer — prime suspect for memory pressure or OOM risk.",
            process_name=leader_mem.name,
            pid=leader_mem.pid,
        ))
        if _is_java(leader_mem.name, leader_mem.cmdline):
            suggestions.append(ActionSuggestion(
                severity=sev,
                category="memory",
                title=f"Heap summary for Java pid {leader_mem.pid}",
                command=f"jcmd {leader_mem.pid} GC.heap_info 2>/dev/null || jmap -heap {leader_mem.pid} 2>/dev/null | head -40",
                description="Check if the JVM heap is oversized or leaking before restarting.",
                process_name=leader_mem.name,
                pid=leader_mem.pid,
            ))
        elif mem.used_percent >= mem_crit or mem.swap_used_percent >= 30:
            suggestions.append(ActionSuggestion(
                severity="warning",
                category="memory",
                title=f"Consider restarting {label} to reclaim memory",
                command=f"kill -TERM {leader_mem.pid}  # graceful; use systemctl restart <service> if managed",
                description=(
                    "Only restart after confirming the service can tolerate it. "
                    "Prefer resizing the instance if memory is chronically tight."
                ),
                process_name=leader_mem.name,
                pid=leader_mem.pid,
            ))

    for p in top_mem[1:3]:
        if p.memory_percent < 5:
            break
        label = _proc_display(p.name, p.cmdline)
        suggestions.append(ActionSuggestion(
            severity="info",
            category="memory",
            title=f"{label} using {p.memory_mb} MB RAM",
            command=f"ps -p {p.pid} -o pid,rss,%mem,cmd",
            description="Additional memory consumer worth watching.",
            process_name=p.name,
            pid=p.pid,
        ))

    if mem.oom_kill_count > 0:
        suggestions.append(ActionSuggestion(
            severity="warning",
            category="memory",
            title=f"{mem.oom_kill_count} OOM kill(s) since boot",
            command="dmesg -T | grep -i 'killed process' | tail -10",
            description="Shows which processes the kernel killed when RAM ran out.",
        ))

    # ------------------------------------------------------------------ Disk pressure
    for d in system.disks:
        if d.mount.startswith("/proc") or d.mount.startswith("/sys"):
            continue
        if d.used_percent < disk_warn:
            continue

        sev = "critical" if d.used_percent >= disk_crit else "warning"
        suggestions.append(ActionSuggestion(
            severity=sev,
            category="disk",
            title=f"{d.mount} at {d.used_percent}% — find large directories",
            command=f"du -xh {d.mount} --max-depth=1 2>/dev/null | sort -h | tail -15",
            description=(
                f"Only {d.free_bytes / (1024 ** 3):.1f} GB free on {d.mount}. "
                "Lists the biggest top-level folders."
            ),
        ))
        suggestions.append(ActionSuggestion(
            severity=sev,
            category="disk",
            title=f"Safe cleanup preview on {d.mount}",
            command="./scripts/disk-cleanup.sh --days 7",
            description=(
                "Dry-run: Jenkins workspaces, rotated logs, package caches, Docker. "
                "Add --execute to actually delete."
            ),
        ))
        if d.mount in ("/", "/var"):
            suggestions.append(ActionSuggestion(
                severity="info",
                category="disk",
                title="Shrink systemd journal if logs grew large",
                command="journalctl --disk-usage && journalctl --vacuum-time=7d",
                description="Journal logs often fill /var on long-running build servers.",
            ))

    # ------------------------------------------------------------------ Docker disk (reuse collector suggestions)
    if docker_report and docker_report.available:
        reclaim_gb = reclaimable_bytes(docker_report.disk) / (1024 ** 3)
        if reclaim_gb >= 1 or docker_report.dangling_count > 0:
            for ds in cleanup_suggestions(docker_report, t):
                suggestions.append(ActionSuggestion(
                    severity=ds.severity if ds.severity != "info" else "info",
                    category="docker",
                    title=ds.title,
                    command=ds.command,
                    description=ds.description,
                ))

    # Deduplicate by command while preserving order
    seen: set[str] = set()
    unique: list[ActionSuggestion] = []
    for s in suggestions:
        key = s.command
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    unique.sort(key=lambda s: severity_rank.get(s.severity, 3))
    return unique[:12]
