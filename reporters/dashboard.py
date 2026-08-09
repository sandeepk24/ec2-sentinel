"""
Terminal dashboard: render health reports as clean, colorized console output.

No fancy TUI framework needed — just ANSI codes and careful alignment.
Works over SSH, works in screen/tmux, works on a bad day at 3 AM.
"""

import sys
from typing import Optional

from collectors.system import SystemReport
from collectors.process import ProcessReport
from collectors.logs import LogReport
from collectors.ports import PortReport


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
    lines = [
        f"\n{C.BOLD}{'━' * 50}{C.RESET}",
        f"  {C.BOLD}{C.CYAN}EC2 SENTINEL{C.RESET} — Health Report",
        f"  Host: {C.BOLD}{ec2.hostname}{C.RESET}   Instance: {ec2.instance_id}",
        f"  Region: {ec2.region}    Type: {ec2.instance_type}",
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
    ]

    if cpu.steal_percent > 1.0:
        lines.append(
            f"  │  {C.YELLOW}↳ Steal time: {cpu.steal_percent}% "
            f"(EC2 CPU throttling detected){C.RESET}"
        )

    lines.append(
        f"  ├─ Memory {'.' * 11} {_bar(mem.used_percent, 15)} "
        f"{_fmt_bytes(mem.used_bytes)} / {_fmt_bytes(mem.total_bytes)}  ({mem.used_percent}%)"
        f"  {_status_icon(not mem_warn, mem_warn)}"
    )

    if mem.swap_used_percent > thresholds.get("swap_warn", 50):
        lines.append(
            f"  │  {C.YELLOW}↳ Swap: {_fmt_bytes(mem.swap_used_bytes)} / "
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

        if d.days_until_full is not None and d.days_until_full < 30:
            connector = "│ " if i < len(disks) - 1 else "  "
            color = C.RED if d.days_until_full < 7 else C.YELLOW
            lines.append(
                f"  {connector} {color}↳ Predicted full in {d.days_until_full:.0f} days "
                f"(growth: {_fmt_bytes(int(d.growth_rate_bytes_per_day or 0))}/day){C.RESET}"
            )

        if d.inode_used_percent > 85:
            connector = "│ " if i < len(disks) - 1 else "  "
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


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

def render_full_report(
    system: SystemReport,
    proc_report: ProcessReport,
    port_report: PortReport,
    log_report: LogReport,
    thresholds: dict,
) -> str:
    """Render the complete terminal dashboard."""
    sections = [
        render_header(system),
        render_system(system, thresholds),
        render_disks(system, thresholds),
        render_processes(proc_report),
        render_ports(port_report),
        render_logs(log_report),
        render_verdict(system, proc_report, port_report, log_report, thresholds),
    ]
    return "\n".join(sections)
