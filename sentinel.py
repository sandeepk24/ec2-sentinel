#!/usr/bin/env python3
"""
EC2 Sentinel — EC2 instance health monitoring for DevOps engineers.

Usage:
    python sentinel.py --once            # single health check, exit
    python sentinel.py --watch           # continuous terminal dashboard
    python sentinel.py --daemon          # background mode with alerting
    python sentinel.py --once --json     # JSON output for piping

See README.md for full documentation.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from alerts import Alert, dispatch_alerts
from collectors.system import collect_system
from collectors.process import collect_processes
from collectors.logs import collect_logs
from collectors.ports import collect_ports
from reporters.dashboard import render_full_report

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATHS = [
    Path("config.yaml"),
    Path("config.yml"),
    Path("/etc/ec2-sentinel/config.yaml"),
    Path(os.path.expanduser("~/.ec2-sentinel/config.yaml")),
]

DEFAULT_THRESHOLDS = {
    "cpu_warn": 80,
    "cpu_crit": 95,
    "memory_warn": 80,
    "memory_crit": 95,
    "disk_warn": 75,
    "disk_crit": 90,
    "swap_warn": 50,
}

DEFAULT_LOG_PATTERNS = [
    "OutOfMemoryError",
    "No space left on device",
    "CRITICAL",
    "FATAL",
    "Connection refused",
    "Too many open files",
]

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str | None = None) -> dict:
    """Load YAML config, falling back to defaults."""
    if config_path:
        path = Path(config_path)
        if not path.exists():
            print(f"Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        with open(path) as f:
            return yaml.safe_load(f) or {}

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f) or {}

    # No config file — run with sensible defaults
    return {}


def get_thresholds(config: dict) -> dict:
    return {**DEFAULT_THRESHOLDS, **config.get("thresholds", {})}


def get_process_configs(config: dict) -> list[dict]:
    """Build process + port config from YAML."""
    return config.get("processes", [])


def get_port_configs(config: dict) -> list[dict]:
    """Extract port checks from process configs."""
    ports = []
    for proc in config.get("processes", []):
        if "port" in proc:
            ports.append({"name": proc["name"], "port": proc["port"]})
    # Add any standalone port checks
    for extra in config.get("extra_ports", []):
        ports.append(extra)
    return ports


def get_log_config(config: dict) -> tuple[list[str], list[str]]:
    log_cfg = config.get("log_watch", {})
    patterns = log_cfg.get("patterns", DEFAULT_LOG_PATTERNS)
    files = log_cfg.get("files", ["/var/log/syslog", "/var/log/messages"])
    return patterns, files


# ---------------------------------------------------------------------------
# Alert generation
# ---------------------------------------------------------------------------

def generate_alerts(system, proc_report, port_report, log_report, thresholds, hostname) -> list[Alert]:
    """Evaluate all reports against thresholds, produce alerts."""
    alerts = []
    now = datetime.now(timezone.utc).isoformat()

    # CPU
    if system.cpu.usage_percent >= thresholds["cpu_crit"]:
        alerts.append(Alert(
            severity="critical", title="CPU Critical",
            message=f"CPU usage at {system.cpu.usage_percent}% "
                    f"(load avg: {system.cpu.load_avg_1}, {system.cpu.core_count} cores)",
            hostname=hostname, timestamp=now, source="system.cpu",
        ))
    elif system.cpu.usage_percent >= thresholds["cpu_warn"]:
        alerts.append(Alert(
            severity="warning", title="CPU Warning",
            message=f"CPU usage at {system.cpu.usage_percent}%",
            hostname=hostname, timestamp=now, source="system.cpu",
        ))

    # CPU steal
    if system.cpu.steal_percent > 5:
        alerts.append(Alert(
            severity="warning", title="CPU Steal Time High",
            message=f"Steal time at {system.cpu.steal_percent}% — "
                    "possible T-series credit exhaustion or noisy neighbor",
            hostname=hostname, timestamp=now, source="system.cpu",
        ))

    # Memory
    if system.memory.used_percent >= thresholds["memory_crit"]:
        alerts.append(Alert(
            severity="critical", title="Memory Critical",
            message=f"Memory at {system.memory.used_percent}% "
                    f"({system.memory.summary})",
            hostname=hostname, timestamp=now, source="system.memory",
        ))
    elif system.memory.used_percent >= thresholds["memory_warn"]:
        alerts.append(Alert(
            severity="warning", title="Memory Warning",
            message=f"Memory at {system.memory.used_percent}%",
            hostname=hostname, timestamp=now, source="system.memory",
        ))

    # OOM kills
    if system.memory.oom_kill_count > 0:
        alerts.append(Alert(
            severity="warning", title="OOM Kills Detected",
            message=f"{system.memory.oom_kill_count} OOM kill(s) since boot",
            hostname=hostname, timestamp=now, source="system.memory",
        ))

    # Disk
    for d in system.disks:
        if d.used_percent >= thresholds["disk_crit"]:
            msg = f"{d.mount} at {d.used_percent}%"
            if d.days_until_full is not None:
                msg += f" — predicted full in {d.days_until_full:.0f} days"
            alerts.append(Alert(
                severity="critical", title=f"Disk Critical: {d.mount}",
                message=msg, hostname=hostname, timestamp=now, source="system.disk",
            ))
        elif d.used_percent >= thresholds["disk_warn"]:
            alerts.append(Alert(
                severity="warning", title=f"Disk Warning: {d.mount}",
                message=f"{d.mount} at {d.used_percent}%",
                hostname=hostname, timestamp=now, source="system.disk",
            ))

    # Missing processes
    for p in proc_report.missing:
        alerts.append(Alert(
            severity="critical", title=f"Process Missing: {p.name}",
            message=f"Expected process '{p.name}' (match: {p.match_pattern}) not found",
            hostname=hostname, timestamp=now, source="process",
        ))

    # Restarted processes
    for p in proc_report.restarted:
        alerts.append(Alert(
            severity="warning", title=f"Process Restarted: {p.name}",
            message=f"{p.name} PID changed from {p.previous_pid} to {p.pid}",
            hostname=hostname, timestamp=now, source="process",
        ))

    # Closed ports
    for c in port_report.failed:
        alerts.append(Alert(
            severity="critical", title=f"Port Closed: {c.port}",
            message=f"Port {c.port} ({c.service_name}) is not accepting connections",
            hostname=hostname, timestamp=now, source="ports",
        ))

    # Log pattern hits
    for m in log_report.matches:
        alerts.append(Alert(
            severity="warning", title=f"Log Pattern: {m.pattern}",
            message=f"{m.count} occurrence(s) in {m.file}\n"
                    f"Last match: {m.last_line[:200]}",
            hostname=hostname, timestamp=now, source="logs",
        ))

    return alerts


# ---------------------------------------------------------------------------
# Report serialization
# ---------------------------------------------------------------------------

def report_to_dict(system, proc_report, port_report, log_report) -> dict:
    """Convert all reports to a JSON-serializable dict."""
    return {
        "timestamp": system.timestamp,
        "host": {
            "hostname": system.ec2.hostname,
            "instance_id": system.ec2.instance_id,
            "instance_type": system.ec2.instance_type,
            "region": system.ec2.region,
            "uptime_seconds": system.uptime_seconds,
        },
        "cpu": {
            "usage_percent": system.cpu.usage_percent,
            "cores": system.cpu.core_count,
            "load_avg": [system.cpu.load_avg_1, system.cpu.load_avg_5, system.cpu.load_avg_15],
            "steal_percent": system.cpu.steal_percent,
        },
        "memory": {
            "used_percent": system.memory.used_percent,
            "used_bytes": system.memory.used_bytes,
            "total_bytes": system.memory.total_bytes,
            "swap_used_percent": system.memory.swap_used_percent,
            "oom_kills": system.memory.oom_kill_count,
        },
        "disks": [
            {
                "mount": d.mount,
                "used_percent": d.used_percent,
                "used_bytes": d.used_bytes,
                "total_bytes": d.total_bytes,
                "days_until_full": d.days_until_full,
            }
            for d in system.disks
        ],
        "processes": [
            {
                "name": p.name,
                "status": p.status,
                "pid": p.pid,
                "cpu_percent": p.cpu_percent,
                "memory_mb": p.memory_mb,
                "restart_detected": p.restart_detected,
            }
            for p in proc_report.processes
        ],
        "ports": [
            {
                "port": c.port,
                "service": c.service_name,
                "status": c.status,
                "response_ms": c.response_ms,
            }
            for c in port_report.checks
        ],
        "log_matches": [
            {
                "pattern": m.pattern,
                "count": m.count,
                "file": m.file,
                "last_line": m.last_line[:200],
            }
            for m in log_report.matches
        ],
    }


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def run_once(config: dict, output_json: bool = False) -> int:
    """Single health check. Returns exit code (0=ok, 1=warnings, 2=critical)."""
    thresholds = get_thresholds(config)
    process_cfgs = get_process_configs(config)
    port_cfgs = get_port_configs(config)
    log_patterns, log_files = get_log_config(config)

    # Collect
    system = collect_system()
    proc_report = collect_processes(process_cfgs)
    port_report = collect_ports(port_cfgs)
    log_report = collect_logs(log_patterns, log_files)

    hostname = config.get("sentinel", {}).get("hostname_override", system.ec2.hostname)

    if output_json:
        data = report_to_dict(system, proc_report, port_report, log_report)
        print(json.dumps(data, indent=2))
    else:
        print(render_full_report(system, proc_report, port_report, log_report, thresholds))

    # Generate and dispatch alerts
    alerts = generate_alerts(system, proc_report, port_report, log_report, thresholds, hostname)
    alert_cfg = config.get("alerts", {})
    if alerts and any(v.get("enabled") for v in alert_cfg.values()):
        dispatch_alerts(alerts, alert_cfg)

    # Exit code reflects health
    has_critical = any(a.severity == "critical" for a in alerts)
    has_warning = any(a.severity == "warning" for a in alerts)
    if has_critical:
        return 2
    if has_warning:
        return 1
    return 0


def run_watch(config: dict) -> None:
    """Continuous terminal dashboard — clears and re-renders each cycle."""
    interval = config.get("sentinel", {}).get("interval_seconds", 30)

    # Handle Ctrl+C gracefully
    running = True

    def _handle_signal(sig, frame):
        nonlocal running
        running = False
        print(f"\n  Sentinel stopped. Goodbye.\n")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    thresholds = get_thresholds(config)
    process_cfgs = get_process_configs(config)
    port_cfgs = get_port_configs(config)
    log_patterns, log_files = get_log_config(config)

    while running:
        # Clear screen
        os.system("clear" if os.name != "nt" else "cls")

        system = collect_system()
        proc_report = collect_processes(process_cfgs)
        port_report = collect_ports(port_cfgs)
        log_report = collect_logs(log_patterns, log_files)

        print(render_full_report(system, proc_report, port_report, log_report, thresholds))
        print(f"  Refreshing every {interval}s. Press Ctrl+C to stop.")

        # Generate alerts in watch mode too
        hostname = config.get("sentinel", {}).get("hostname_override", system.ec2.hostname)
        alerts = generate_alerts(system, proc_report, port_report, log_report, thresholds, hostname)
        alert_cfg = config.get("alerts", {})
        if alerts and any(v.get("enabled") for v in alert_cfg.values()):
            dispatch_alerts(alerts, alert_cfg)

        time.sleep(interval)


def run_daemon(config: dict) -> None:
    """Background daemon mode — logs to file, dispatches alerts."""
    log_file = config.get("sentinel", {}).get("log_file", "/var/log/ec2-sentinel.log")
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("ec2-sentinel")
    logger.info("EC2 Sentinel daemon started")

    interval = config.get("sentinel", {}).get("interval_seconds", 60)

    running = True

    def _handle_signal(sig, frame):
        nonlocal running
        running = False
        logger.info("Shutdown signal received")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    thresholds = get_thresholds(config)
    process_cfgs = get_process_configs(config)
    port_cfgs = get_port_configs(config)
    log_patterns, log_files = get_log_config(config)

    while running:
        try:
            system = collect_system()
            proc_report = collect_processes(process_cfgs)
            port_report = collect_ports(port_cfgs)
            log_report = collect_logs(log_patterns, log_files)

            hostname = config.get("sentinel", {}).get("hostname_override", system.ec2.hostname)
            alerts = generate_alerts(
                system, proc_report, port_report, log_report, thresholds, hostname
            )

            if alerts:
                for a in alerts:
                    logger.warning(f"[{a.severity}] {a.title}: {a.message}")

                alert_cfg = config.get("alerts", {})
                if any(v.get("enabled") for v in alert_cfg.values()):
                    results = dispatch_alerts(alerts, alert_cfg)
                    logger.info(f"Alert dispatch results: {results}")
            else:
                logger.info("Health check passed — all clear")

            # Also write JSON report to stdout for log aggregation
            data = report_to_dict(system, proc_report, port_report, log_report)
            logger.debug(json.dumps(data))

        except Exception as e:
            logger.exception(f"Scan cycle failed: {e}")

        time.sleep(interval)

    logger.info("EC2 Sentinel daemon stopped")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="EC2 Sentinel — EC2 instance health monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sentinel.py --once                 # quick health check
  python sentinel.py --watch                # live terminal dashboard
  python sentinel.py --daemon               # background monitoring
  python sentinel.py --once --json          # JSON for piping/logging
  python sentinel.py --config /etc/myconfig.yaml --once
        """,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run once and exit")
    mode.add_argument("--watch", action="store_true", help="Continuous terminal dashboard")
    mode.add_argument("--daemon", action="store_true", help="Background daemon with alerting")

    parser.add_argument("--config", "-c", help="Path to config YAML file")
    parser.add_argument("--json", action="store_true", help="Output as JSON (with --once)")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.once:
        exit_code = run_once(config, output_json=args.json)
        sys.exit(exit_code)
    elif args.watch:
        run_watch(config)
    elif args.daemon:
        run_daemon(config)


if __name__ == "__main__":
    main()
