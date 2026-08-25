"""
Terminal dashboard: render health reports as clean, colorized console output.

No fancy TUI framework needed — just ANSI codes and careful alignment.
Works over SSH, works in screen/tmux, works on a bad day at 3 AM.
"""

import sys
from typing import Optional

from collectors.docker import DockerReport
from collectors.java import JavaReport
from collectors.system import SystemReport
from collectors.process import ProcessReport
from collectors.logs import LogReport
from collectors.ports import PortReport
from collectors.top import TopReport


# ---------------------------------------------------------------------------
# ANSI color helpers — works in any modern terminal
# ---------------------------------------------------------------------------

class C:
    """ANSI color codes. Degrades gracefully if terminal doesn't support them."""
    RESET    = "\033[0m"
    BOLD     = "\033[1m"
    DIM      = "\033[2m"
    RED      = "\033[91m"
    GREEN    = "\033[92m"
    YELLOW   = "\033[93m"
    BLUE     = "\033[94m"
    CYAN     = "\033[96m"
    WHITE    = "\033[97m"

    @classmethod
    def disable(cls):
        for attr in ("RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW",
                      "BLUE", "CYAN", "WHITE"):
            setattr(cls, attr, "")


# Disable colors if not a TTY (piping to file, etc.)
if not sys.stdout.isatty():
    C.disable()


def _status_icon(ok: bool, warn: bool = False) -> str:
    if not ok:
        return f"{C.RED}❌{C.RESET}"
    if warn:
        return f"{C.YELLOW}⚠️ {C.RESET}"
    return f"{C.GREEN}✅{C.RESET}"


def _bar(percent: float, width: int = 20) -> str:
    filled = int(percent / 100 * width)
    empty = width - filled
    if percent >= 90:
        color = C.RED
    elif percent >= 75:
        color = C.YELLOW
    else:
        color = C.GREEN
    return f"{color}{'█' * filled}{'░' * empty}{C.RESET}"


def _fmt_bytes(b: int) -> str:
    gb = b / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f} GB"
    mb = b / (1024 ** 2)
    return f"{mb:.0f} MB"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_header(system: SystemReport) -> str:
    ec2 = system.ec2
    osinfo = system.os
    lines = [
        f"\n{C.BOLD}{'━' * 50}{C.RESET}",
        f"  {C.BOLD}{C.CYAN}EC2 SENTINEL{C.RESET} — Health Report",
        f"  Host: {C.BOLD}{ec2.hostname}{C.RESET}   Instance: {ec2.instance_id}",
        f"  Region: {ec2.region}    Type: {C.BOLD}{ec2.instance_type}{C.RESET}"
        f"  ({ec2.cloud_provider}/{ec2.detection_source or 'n/a'})",
        f"  OS: {C.BOLD}{osinfo.display}{C.RESET}",
        f"  Scan time: {system.timestamp}",
        f"{C.BOLD}{'━' * 50}{C.RESET}",
    ]
    return "\n".join(lines)


def render_system(system: SystemReport, thresholds: dict) -> str:
    cpu = system.cpu
    mem = system.memory

    cpu_warn = cpu.usage_percent >= thresholds.get("cpu_warn", 80)
    cpu_crit = cpu.usage_percent >= thresholds.get("cpu_crit", 95)
    mem_warn = mem.used_percent >= thresholds.get("memory_warn", 80)

    lines = [
        f"\n  {C.BOLD}SYSTEM{C.RESET}",
        f"  ├─ CPU {'.' * 14} {_bar(cpu.usage_percent, 15)} {cpu.usage_percent}%"
        f"  ({cpu.core_count} cores, load: {cpu.load_avg_1})"
        f"  {_status_icon(not cpu_crit, cpu_warn)}",
        f"  │  {C.DIM}↳ user {cpu.user_percent}% · system {cpu.system_percent}% · "
        f"iowait {cpu.iowait_percent}% · steal {cpu.steal_percent}% · "
        f"idle {cpu.idle_percent}%{C.RESET}",
    ]

    if cpu.steal_percent > 1.0:
        lines.append(
            f"  │  {C.YELLOW}↳ Steal time: {cpu.steal_percent}% "
            f"(EC2 CPU throttling / credit exhaustion){C.RESET}"
        )
    if cpu.iowait_percent >= 10:
        lines.append(
            f"  │  {C.YELLOW}↳ High iowait — CPU waiting on disk/EBS{C.RESET}"
        )

    lines.append(
        f"  ├─ Memory {'.' * 11} {_bar(mem.used_percent, 15)} "
        f"{_fmt_bytes(mem.used_bytes)} / {_fmt_bytes(mem.total_bytes)}  ({mem.used_percent}%)"
        f"  {_status_icon(not mem_warn, mem_warn)}"
    )
    lines.append(
        f"  │  {C.DIM}↳ apps ~{_fmt_bytes(mem.app_bytes)} · cache {_fmt_bytes(mem.cached_bytes)} · "
        f"available {_fmt_bytes(mem.available_bytes)}{C.RESET}"
    )

    if mem.swap_used_percent > thresholds.get("swap_warn", 50) or mem.swap_used_percent >= 10:
        color = C.RED if mem.swap_used_percent >= 30 else C.YELLOW
        lines.append(
            f"  │  {color}↳ Swap: {_fmt_bytes(mem.swap_used_bytes)} / "
            f"{_fmt_bytes(mem.swap_total_bytes)} ({mem.swap_used_percent}%){C.RESET}"
        )

    if mem.oom_kill_count > 0:
        lines.append(
            f"  │  {C.RED}↳ OOM kills since boot: {mem.oom_kill_count}{C.RESET}"
        )

    lines.append(f"  └─ Uptime {'.' * 11} {system.uptime_human}")

    return "\n".join(lines)


def render_disks(system: SystemReport, thresholds: dict) -> str:
    lines = [f"\n  {C.BOLD}DISK{C.RESET}"]
    disks = system.disks

    for i, d in enumerate(disks):
        prefix = "└─" if i == len(disks) - 1 else "├─"
        warn = d.used_percent >= thresholds.get("disk_warn", 75)
        crit = d.used_percent >= thresholds.get("disk_crit", 90)

        mount_display = d.mount.ljust(8)
        lines.append(
            f"  {prefix} {mount_display} {'.' * 8} {_bar(d.used_percent, 15)} "
            f"{d.used_percent}%  ({_fmt_bytes(d.used_bytes)} / {_fmt_bytes(d.total_bytes)})"
            f"  {_status_icon(not crit, warn)}"
        )

        connector = "│ " if i < len(disks) - 1 else "  "
        if d.growth_gb_per_day is not None:
            trend = d.trend or "unknown"
            color = C.RED if trend == "growing" and (d.days_until_full or 999) < 14 else (
                C.YELLOW if trend == "growing" else C.DIM
            )
            growth_line = (
                f"  {connector} {color}↳ Trend {trend}: {d.growth_gb_per_day:+.2f} GB/day"
            )
            milestones = []
            if d.days_until_80 is not None:
                milestones.append(f"80% ~{d.days_until_80:.0f}d")
            if d.days_until_90 is not None:
                milestones.append(f"90% ~{d.days_until_90:.0f}d")
            if d.days_until_95 is not None:
                milestones.append(f"95% ~{d.days_until_95:.0f}d")
            if milestones:
                growth_line += f" · {' · '.join(milestones)}"
            if d.predicted_full_date and d.trend == "growing":
                growth_line += f" · full ~{d.predicted_full_date}"
            growth_line += f"{C.RESET}"
            lines.append(growth_line)
        elif d.days_until_full is not None and d.days_until_full < 30:
            color = C.RED if d.days_until_full < 7 else C.YELLOW
            lines.append(
                f"  {connector} {color}↳ Predicted full in {d.days_until_full:.0f} days "
                f"(growth: {_fmt_bytes(int(d.growth_rate_bytes_per_day or 0))}/day){C.RESET}"
            )

        if d.inode_used_percent > 85:
            lines.append(
                f"  {connector} {C.YELLOW}↳ Inode usage: {d.inode_used_percent}%{C.RESET}"
            )

    return "\n".join(lines)


def render_processes(proc_report: ProcessReport) -> str:
    lines = [f"\n  {C.BOLD}PROCESSES{C.RESET}"]

    for i, p in enumerate(proc_report.processes):
        prefix = "└─" if i == len(proc_report.processes) - 1 else "├─"

        if not p.found:
            lines.append(
                f"  {prefix} {p.name} (EXPECTED) {'.' * max(1, 20 - len(p.name))} "
                f"{_status_icon(False)} {C.RED}NOT FOUND{C.RESET}"
            )
        else:
            mem_str = f"{p.memory_mb:.0f}M" if p.memory_mb else "?"
            cpu_str = f"{p.cpu_percent:.0f}%" if p.cpu_percent is not None else "?"
            status_str = "RUNNING"
            icon = _status_icon(True)

            if p.restart_detected:
                status_str = f"{C.YELLOW}RESTARTED{C.RESET} (was pid {p.previous_pid})"
                icon = _status_icon(True, warn=True)

            lines.append(
                f"  {prefix} {p.name} (pid {p.pid}) {'.' * max(1, 15 - len(p.name))} "
                f"{icon} {status_str}  (cpu: {cpu_str}, mem: {mem_str})"
            )

    return "\n".join(lines)


def render_diagnosis(diagnosis) -> str:
    if diagnosis is None:
        return ""
    health_color = C.GREEN
    if diagnosis.health == "critical":
        health_color = C.RED
    elif diagnosis.health == "degraded":
        health_color = C.YELLOW

    lines = [
        f"\n  {C.BOLD}WHY IS THIS SLOW?{C.RESET}  {health_color}{diagnosis.headline}{C.RESET}",
        f"  {C.CYAN}{diagnosis.summary}{C.RESET}",
        f"\n  {C.BOLD}WHERE IS THE CPU GOING?{C.RESET}",
        f"  {diagnosis.cpu_story}",
        f"\n  {C.BOLD}WHERE IS THE MEMORY GOING?{C.RESET}",
        f"  {diagnosis.memory_story}",
    ]

    actionable = [f for f in diagnosis.findings if f.severity in ("critical", "warning")]
    if actionable:
        lines.append(f"\n  {C.BOLD}SAY THIS ON THE CALL{C.RESET}")
        for i, f in enumerate(actionable[:5]):
            icon = "❌" if f.severity == "critical" else "⚠️ "
            lines.append(f"  {icon} {f.say_this}")
            lines.append(f"     → {C.DIM}{f.next_step}{C.RESET}")

    return "\n".join(lines)


def render_top(top_report: Optional[TopReport]) -> str:
    if top_report is None:
        return ""
    lines = [f"\n  {C.BOLD}TOP CONSUMERS{C.RESET} (sampled {top_report.sample_seconds:.1f}s)"]

    lines.append(f"  {C.DIM}By CPU{C.RESET}")
    if not top_report.by_cpu:
        lines.append(f"  └─ {C.DIM}quiet — no significant CPU users{C.RESET}")
    else:
        for i, p in enumerate(top_report.by_cpu[:6]):
            prefix = "└─" if i == min(len(top_report.by_cpu), 6) - 1 else "├─"
            lines.append(
                f"  {prefix} {p.cpu_percent:5.1f}%  pid {p.pid:<6}  {p.name:<16}  "
                f"{C.DIM}{p.cmdline[:40]}{C.RESET}"
            )

    lines.append(f"  {C.DIM}By memory (RSS){C.RESET}")
    if not top_report.by_memory:
        lines.append(f"  └─ {C.DIM}no memory data{C.RESET}")
    else:
        for i, p in enumerate(top_report.by_memory[:6]):
            prefix = "└─" if i == min(len(top_report.by_memory), 6) - 1 else "├─"
            lines.append(
                f"  {prefix} {p.memory_mb:7.1f} MB ({p.memory_percent:4.1f}%)  "
                f"pid {p.pid:<6}  {p.name}"
            )

    return "\n".join(lines)


def render_docker(docker_report: DockerReport) -> str:
    if not docker_report.available:
        if docker_report.error == "disabled in config":
            return ""
        return f"\n  {C.BOLD}DOCKER{C.RESET}\n  └─ {C.DIM}Not available ({docker_report.error}){C.RESET}"

    lines = [
        f"\n  {C.BOLD}DOCKER{C.RESET} (v{docker_report.server_version})",
        f"  ├─ Containers {'.' * 8} {docker_report.running_count} running, "
        f"{docker_report.stopped_count} stopped",
        f"  ├─ Images {'.' * 13} {len(docker_report.images)}",
        f"  ├─ Disk {'.' * 15} images {docker_report.disk.images_size} "
        f"({docker_report.disk.images_reclaimable} reclaimable)",
    ]

    for i, c in enumerate(docker_report.containers[:8]):
        prefix = "└─" if i == min(len(docker_report.containers), 8) - 1 else "├─"
        if c.is_running:
            icon = _status_icon(True, c.is_unhealthy or c.state == "restarting")
            state = c.state.upper()
            if c.is_unhealthy:
                state = f"{C.RED}UNHEALTHY{C.RESET}"
            elif c.state == "restarting":
                state = f"{C.YELLOW}RESTARTING{C.RESET}"
            else:
                state = f"{C.GREEN}{state}{C.RESET}"
        else:
            icon = _status_icon(False)
            state = f"{C.RED}{c.state.upper()}{C.RESET}"

        name = c.name[:24]
        image = c.image[:30]
        lines.append(
            f"  {prefix} {name} {'.' * max(1, 18 - len(name))} "
            f"{icon} {state}  {C.DIM}{image}{C.RESET}"
        )

    if len(docker_report.containers) > 8:
        lines.append(f"  {C.DIM}  … and {len(docker_report.containers) - 8} more{C.RESET}")

    return "\n".join(lines)


def render_java(java_report: JavaReport) -> str:
    if not java_report.enabled:
        return ""

    if not java_report.available:
        if java_report.error == "disabled in config":
            return ""
        if java_report.processes:
            lines = [f"\n  {C.BOLD}RUNNING JAVA PROCESSES{C.RESET} (ps -ef | grep java)"]
            for i, proc in enumerate(java_report.processes[:8]):
                prefix = "└─" if i == min(len(java_report.processes), 8) - 1 else "├─"
                cmd = proc.cmdline[:50] + ("…" if len(proc.cmdline) > 50 else "")
                lines.append(
                    f"  {prefix} pid {proc.pid} {proc.name} {C.DIM}{cmd}{C.RESET}"
                )
            return "\n".join(lines)
        msg = java_report.error or "not found"
        home = f"  JAVA_HOME: {java_report.java_home}" if java_report.java_home else ""
        return f"\n  {C.BOLD}JAVA / JDK{C.RESET}\n  └─ {C.YELLOW}Not detected ({msg}){C.RESET}{home}"

    lines = [
        f"\n  {C.BOLD}JAVA / JDK{C.RESET} "
        f"({java_report.installation_count} runtime(s), {java_report.jdk_count} JDK)",
    ]
    if java_report.java_home:
        lines.append(f"  ├─ JAVA_HOME {'.' * 10} {java_report.java_home}")
    if java_report.default_java:
        lines.append(f"  ├─ Default java {'.' * 7} {java_report.default_java}")

    for i, inst in enumerate(java_report.installations[:8]):
        is_last = i == min(len(java_report.installations), 8) - 1 and not java_report.processes
        prefix = "└─" if is_last else "├─"
        kind = "JDK" if inst.is_jdk else "JRE"
        kind_color = f"{C.GREEN}{kind}{C.RESET}" if inst.is_jdk else f"{C.CYAN}{kind}{C.RESET}"
        ver = f"{inst.vendor} {inst.version}"
        path = inst.path
        if len(path) > 42:
            path = "…" + path[-41:]
        lines.append(
            f"  {prefix} {ver} {'.' * max(1, 24 - len(ver))} "
            f"{kind_color}  {C.DIM}{path}{C.RESET}"
        )
        if inst.javac_version and inst.javac_version != inst.version:
            lines.append(f"  {C.DIM}     javac {inst.javac_version}{C.RESET}")

    if len(java_report.installations) > 8:
        lines.append(f"  {C.DIM}  … and {len(java_report.installations) - 8} more{C.RESET}")

    if java_report.processes:
        lines.append(
            f"  ├─ Running JVMs {'.' * 8} {len(java_report.processes)} "
            f"{C.DIM}(ps -ef | grep java){C.RESET}"
        )
        for i, proc in enumerate(java_report.processes[:5]):
            prefix = "└─" if i == min(len(java_report.processes), 5) - 1 else "├─"
            ver = proc.version or "?"
            name = proc.name[:16]
            lines.append(
                f"  {prefix} pid {proc.pid} {name} {'.' * max(1, 10 - len(name))} "
                f"{C.DIM}Java {ver}{C.RESET}"
            )

    return "\n".join(lines)


def render_ports(port_report: PortReport) -> str:
    lines = [f"\n  {C.BOLD}PORTS{C.RESET}"]

    for i, check in enumerate(port_report.checks):
        prefix = "└─" if i == len(port_report.checks) - 1 else "├─"

        if check.is_open:
            status = f"{C.GREEN}LISTENING{C.RESET}"
            if check.response_ms > 500:
                status = f"{C.YELLOW}SLOW ({check.response_ms:.0f}ms){C.RESET}"
            icon = _status_icon(True, check.response_ms > 500)
        else:
            status = f"{C.RED}CLOSED{C.RESET}"
            icon = _status_icon(False)

        lines.append(
            f"  {prefix} {check.port} ({check.service_name}) {'.' * max(1, 12 - len(check.service_name))} "
            f"{icon} {status}"
        )

    return "\n".join(lines)


def render_logs(log_report: LogReport) -> str:
    lines = [f"\n  {C.BOLD}LOG PATTERNS{C.RESET} (incremental scan)"]

    if not log_report.matches:
        lines.append(f"  └─ {C.GREEN}No matching patterns found{C.RESET}  ✅")
    else:
        for i, m in enumerate(log_report.matches):
            prefix = "└─" if i == len(log_report.matches) - 1 else "├─"
            icon = _status_icon(True, warn=True)
            lines.append(
                f"  {prefix} {m.pattern} {'.' * max(1, 25 - len(m.pattern))} "
                f"{m.count} hit{'s' if m.count > 1 else ''}  {icon}  [{m.file}]"
            )

    lines.append(
        f"  {C.DIM}({log_report.files_scanned} files scanned in "
        f"{log_report.scan_duration_ms:.0f}ms){C.RESET}"
    )

    return "\n".join(lines)


def render_verdict(
    system: SystemReport,
    proc_report: ProcessReport,
    port_report: PortReport,
    log_report: LogReport,
    docker_report: DockerReport,
    thresholds: dict,
) -> str:
    """Summarize: how many warnings, how many criticals, what needs action."""
    warnings = []
    criticals = []

    # CPU
    if system.cpu.usage_percent >= thresholds.get("cpu_crit", 95):
        criticals.append(f"CPU at {system.cpu.usage_percent}%")
    elif system.cpu.usage_percent >= thresholds.get("cpu_warn", 80):
        warnings.append(f"CPU at {system.cpu.usage_percent}%")

    if system.cpu.steal_percent > 5:
        warnings.append(f"CPU steal time {system.cpu.steal_percent}%")

    # Memory
    if system.memory.used_percent >= thresholds.get("memory_crit", 95):
        criticals.append(f"Memory at {system.memory.used_percent}%")
    elif system.memory.used_percent >= thresholds.get("memory_warn", 80):
        warnings.append(f"Memory at {system.memory.used_percent}%")

    # Disk
    for d in system.disks:
        if d.used_percent >= thresholds.get("disk_crit", 90):
            criticals.append(f"{d.mount} disk at {d.used_percent}%")
        elif d.used_percent >= thresholds.get("disk_warn", 75):
            warnings.append(f"{d.mount} disk at {d.used_percent}%")

    # Processes
    for p in proc_report.missing:
        criticals.append(f"{p.name} process missing")
    for p in proc_report.restarted:
        warnings.append(f"{p.name} restarted (was pid {p.previous_pid})")

    # Ports
    for c in port_report.failed:
        criticals.append(f"Port {c.port} ({c.service_name}) closed")

    # Logs
    if log_report.total_hits > 0:
        warnings.append(f"{log_report.total_hits} log pattern matches")

    if docker_report.available:
        for exp in docker_report.missing_expected:
            if not exp.found:
                criticals.append(f"Docker container missing: {exp.name}")
            elif not exp.running:
                criticals.append(f"Docker container stopped: {exp.name}")
        for c in docker_report.unhealthy:
            criticals.append(f"Docker unhealthy: {c.name}")
        for c in docker_report.containers:
            if c.state == "restarting":
                warnings.append(f"Docker restarting: {c.name}")

    lines = [f"\n  {'─' * 45}"]

    if not warnings and not criticals:
        lines.append(f"  {C.GREEN}{C.BOLD}VERDICT: All clear ✅{C.RESET}")
    else:
        parts = []
        if criticals:
            parts.append(f"{C.RED}{len(criticals)} critical{C.RESET}")
        if warnings:
            parts.append(f"{C.YELLOW}{len(warnings)} warning{'s' if len(warnings) > 1 else ''}{C.RESET}")

        lines.append(f"  {C.BOLD}VERDICT:{C.RESET} {', '.join(parts)}")

        for c in criticals:
            lines.append(f"  {C.RED}  ❌ {c}{C.RESET}")
        for w in warnings:
            lines.append(f"  {C.YELLOW}  ⚠️  {w}{C.RESET}")

    lines.append(f"{C.BOLD}{'━' * 50}{C.RESET}\n")

    return "\n".join(lines)


def build_verdict_dict(
    system: SystemReport,
    proc_report: ProcessReport,
    port_report: PortReport,
    log_report: LogReport,
    docker_report: DockerReport,
    thresholds: dict,
) -> dict:
    """Structured verdict for JSON / web dashboard."""
    warnings = []
    criticals = []

    if system.cpu.usage_percent >= thresholds.get("cpu_crit", 95):
        criticals.append(f"CPU at {system.cpu.usage_percent}%")
    elif system.cpu.usage_percent >= thresholds.get("cpu_warn", 80):
        warnings.append(f"CPU at {system.cpu.usage_percent}%")

    if system.cpu.steal_percent > 5:
        warnings.append(f"CPU steal time {system.cpu.steal_percent}%")

    if system.memory.used_percent >= thresholds.get("memory_crit", 95):
        criticals.append(f"Memory at {system.memory.used_percent}%")
    elif system.memory.used_percent >= thresholds.get("memory_warn", 80):
        warnings.append(f"Memory at {system.memory.used_percent}%")

    for d in system.disks:
        if d.used_percent >= thresholds.get("disk_crit", 90):
            criticals.append(f"{d.mount} disk at {d.used_percent}%")
        elif d.used_percent >= thresholds.get("disk_warn", 75):
            warnings.append(f"{d.mount} disk at {d.used_percent}%")

    for p in proc_report.missing:
        criticals.append(f"{p.name} process missing")
    for p in proc_report.restarted:
        warnings.append(f"{p.name} restarted (was pid {p.previous_pid})")

    for c in port_report.failed:
        criticals.append(f"Port {c.port} ({c.service_name}) closed")

    if log_report.total_hits > 0:
        warnings.append(f"{log_report.total_hits} log pattern matches")

    if docker_report.available:
        for exp in docker_report.missing_expected:
            if not exp.found:
                criticals.append(f"Docker container missing: {exp.name}")
            elif not exp.running:
                criticals.append(f"Docker container stopped: {exp.name}")
        for c in docker_report.unhealthy:
            criticals.append(f"Docker unhealthy: {c.name}")
        for c in docker_report.containers:
            if c.state == "restarting":
                warnings.append(f"Docker restarting: {c.name}")

    if criticals:
        status = "critical"
    elif warnings:
        status = "warning"
    else:
        status = "ok"

    return {"status": status, "warnings": warnings, "criticals": criticals}


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

def render_full_report(
    system: SystemReport,
    proc_report: ProcessReport,
    port_report: PortReport,
    log_report: LogReport,
    docker_report: DockerReport,
    thresholds: dict,
    top_report: Optional[TopReport] = None,
    diagnosis=None,
    java_report: Optional[JavaReport] = None,
) -> str:
    """Render the complete terminal dashboard."""
    sections = [
        render_header(system),
        render_diagnosis(diagnosis),
        render_system(system, thresholds),
        render_top(top_report),
        render_disks(system, thresholds),
        render_processes(proc_report),
        render_java(java_report) if java_report else "",
        render_docker(docker_report),
        render_ports(port_report),
        render_logs(log_report),
        render_verdict(
            system, proc_report, port_report, log_report, docker_report, thresholds
        ),
    ]
    return "\n".join(sections)
