#!/usr/bin/env python3
"""
EC2 Sentinel — EC2 instance health monitoring for DevOps engineers.

Usage:
    python sentinel.py --once            # single health check, exit
    python sentinel.py --watch           # continuous terminal dashboard
    python sentinel.py --daemon          # background mode with alerting
    python sentinel.py --once --json     # JSON output for piping
    python sentinel.py --web             # local web dashboard (localhost:8765)

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
from analyzers.diagnose import diagnose, diagnosis_to_dict
from collectors.docker import (
    collect_docker,
    reclaimable_bytes,
    cleanup_suggestions,
    _parse_size_bytes,
    _format_bytes,
)
from collectors.java import collect_java
from collectors.system import collect_system
from collectors.process import collect_processes
from collectors.logs import collect_logs
from collectors.ports import collect_ports
from collectors.top import collect_top
from reporters.dashboard import build_verdict_dict, render_full_report
from reporters.web_server import load_fleet_reports, run_web_server

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

DEFAULT_INTERVAL_SECONDS = 300
CONFIG_VERSION = 2
LEGACY_INTERVAL_SECONDS = {30, 60}

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def normalize_config(cfg: dict | None) -> dict:
    """Apply sentinel defaults and migrate legacy scan intervals."""
    if not cfg:
        cfg = {}
    sentinel = cfg.setdefault("sentinel", {})
    version = sentinel.get("config_version", 1)

    if version < CONFIG_VERSION:
        interval = sentinel.get("interval_seconds")
        if interval is None or interval in LEGACY_INTERVAL_SECONDS:
            sentinel["interval_seconds"] = DEFAULT_INTERVAL_SECONDS
        sentinel["config_version"] = CONFIG_VERSION
    elif "interval_seconds" not in sentinel:
        sentinel["interval_seconds"] = DEFAULT_INTERVAL_SECONDS

    return cfg


def get_interval_seconds(config: dict) -> int:
    return int(
        config.get("sentinel", {}).get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    )


def load_config(config_path: str | None = None) -> dict:
    """Load YAML config, falling back to defaults."""
    if config_path:
        path = Path(config_path)
        if not path.exists():
            print(f"Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        with open(path) as f:
            return normalize_config(yaml.safe_load(f) or {})

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            with open(path) as f:
                return normalize_config(yaml.safe_load(f) or {})

    # No config file — run with sensible defaults
    return normalize_config({})


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


def get_docker_config(config: dict) -> dict:
    """Docker monitoring config — enabled by default when docker is present."""
    return config.get("docker", {"enabled": True})


def get_java_config(config: dict) -> dict:
    """Java/JDK discovery config — enabled by default."""
    return config.get("java", {"enabled": True})


# ---------------------------------------------------------------------------
# Alert generation
# ---------------------------------------------------------------------------

def generate_alerts(
    system, proc_report, port_report, log_report, docker_report, thresholds, hostname, docker_cfg,
) -> list[Alert]:
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

    # Docker
    if docker_report.available:
        for exp in docker_report.missing_expected:
            if not exp.found:
                alerts.append(Alert(
                    severity="critical", title=f"Docker Container Missing: {exp.name}",
                    message=f"Expected container '{exp.name}' (match: {exp.match}) not found",
                    hostname=hostname, timestamp=now, source="docker",
                ))
            elif not exp.running:
                alerts.append(Alert(
                    severity="critical", title=f"Docker Container Stopped: {exp.name}",
                    message=f"Container '{exp.matched_container or exp.name}' is not running",
                    hostname=hostname, timestamp=now, source="docker",
                ))

        for c in docker_report.unhealthy:
            alerts.append(Alert(
                severity="critical", title=f"Docker Unhealthy: {c.name}",
                message=f"Container {c.name} ({c.image}) — {c.status}",
                hostname=hostname, timestamp=now, source="docker",
            ))

        for c in docker_report.containers:
            if c.state == "restarting":
                alerts.append(Alert(
                    severity="warning", title=f"Docker Restarting: {c.name}",
                    message=f"Container {c.name} is in a restart loop — {c.status}",
                    hostname=hostname, timestamp=now, source="docker",
                ))

        reclaim_gb = reclaimable_bytes(docker_report.disk) / (1024 ** 3)
        disk_warn_gb = docker_cfg.get("disk_reclaim_warn_gb", 5)
        if reclaim_gb >= disk_warn_gb:
            alerts.append(Alert(
                severity="warning", title="Docker Disk Reclaimable High",
                message=f"{reclaim_gb:.1f} GB reclaimable — run docker system prune",
                hostname=hostname, timestamp=now, source="docker",
            ))

        cache_warn_gb = docker_cfg.get("cache_warn_gb", 2)
        cache_gb = _parse_size_bytes(docker_report.disk.build_cache_reclaimable) / (1024 ** 3)
        if cache_gb >= cache_warn_gb:
            alerts.append(Alert(
                severity="warning", title="Docker Build Cache High",
                message=(
                    f"{docker_report.disk.build_cache_reclaimable} build cache reclaimable "
                    "— run docker builder prune"
                ),
                hostname=hostname, timestamp=now, source="docker",
            ))

        dangling_warn = docker_cfg.get("dangling_warn_count", 5)
        if docker_report.dangling_count >= dangling_warn:
            alerts.append(Alert(
                severity="warning", title="Docker Dangling Images High",
                message=(
                    f"{docker_report.dangling_count} dangling images "
                    f"({docker_report.disk.images_reclaimable} reclaimable) "
                    "— run docker image prune"
                ),
                hostname=hostname, timestamp=now, source="docker",
            ))

        images_warn = docker_cfg.get("images_warn_count", 50)
        if len(docker_report.images) >= images_warn:
            alerts.append(Alert(
                severity="warning", title="Docker Image Count High",
                message=f"{len(docker_report.images)} images stored (threshold: {images_warn})",
                hostname=hostname, timestamp=now, source="docker",
            ))

    return alerts


# ---------------------------------------------------------------------------
# Report serialization
# ---------------------------------------------------------------------------

def report_to_dict(
    system, proc_report, port_report, log_report, docker_report,
    top_report=None, diagnosis=None, java_report=None, docker_cfg=None,
) -> dict:
    """Convert all reports to a JSON-serializable dict."""
    top_report = top_report or collect_top(limit=8, sample_seconds=0.5)
    diagnosis = diagnosis or diagnose(
        system, top_report, docker_report, proc_report, port_report, log_report,
    )

    def _top_list(rows):
        return [
            {
                "pid": p.pid,
                "name": p.name,
                "cmdline": p.cmdline,
                "cpu_percent": p.cpu_percent,
                "memory_mb": p.memory_mb,
                "memory_percent": p.memory_percent,
            }
            for p in rows
        ]

    return {
        "timestamp": system.timestamp,
        "host": {
            "hostname": system.ec2.hostname,
            "instance_id": system.ec2.instance_id,
            "instance_type": system.ec2.instance_type,
            "region": system.ec2.region,
            "availability_zone": system.ec2.availability_zone,
            "ami_id": system.ec2.ami_id,
            "cloud_provider": system.ec2.cloud_provider,
            "detection_source": system.ec2.detection_source,
            "uptime_seconds": system.uptime_seconds,
            "os": {
                "name": system.os.name,
                "id": system.os.id,
                "id_like": system.os.id_like,
                "version": system.os.version,
                "version_id": system.os.version_id,
                "version_codename": system.os.version_codename,
                "family": system.os.family,
                "kernel": system.os.kernel,
                "arch": system.os.arch,
                "platform": system.os.platform,
                "display": system.os.display,
            },
        },
        "cpu": {
            "usage_percent": system.cpu.usage_percent,
            "cores": system.cpu.core_count,
            "load_avg": [system.cpu.load_avg_1, system.cpu.load_avg_5, system.cpu.load_avg_15],
            "steal_percent": system.cpu.steal_percent,
            "user_percent": system.cpu.user_percent,
            "system_percent": system.cpu.system_percent,
            "iowait_percent": system.cpu.iowait_percent,
            "idle_percent": system.cpu.idle_percent,
            "irq_percent": system.cpu.irq_percent,
            "load_per_core": system.cpu.load_per_core,
        },
        "memory": {
            "used_percent": system.memory.used_percent,
            "used_bytes": system.memory.used_bytes,
            "total_bytes": system.memory.total_bytes,
            "available_bytes": system.memory.available_bytes,
            "available_percent": system.memory.available_percent,
            "swap_used_percent": system.memory.swap_used_percent,
            "swap_used_bytes": system.memory.swap_used_bytes,
            "oom_kills": system.memory.oom_kill_count,
            "app_bytes": system.memory.app_bytes,
            "cached_bytes": system.memory.cached_bytes,
            "buffers_bytes": system.memory.buffers_bytes,
            "free_bytes": system.memory.free_bytes,
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
        "top": {
            "by_cpu": _top_list(top_report.by_cpu),
            "by_memory": _top_list(top_report.by_memory),
            "sample_seconds": top_report.sample_seconds,
        },
        "diagnosis": diagnosis_to_dict(diagnosis),
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
        "docker": {
            "available": docker_report.available,
            "server_version": docker_report.server_version,
            "error": docker_report.error,
            "running_count": docker_report.running_count,
            "stopped_count": docker_report.stopped_count,
            "image_count": len(docker_report.images),
            "dangling_count": docker_report.dangling_count,
            "total_reclaimable": _format_bytes(reclaimable_bytes(docker_report.disk)),
            "disk": {
                "images_size": docker_report.disk.images_size,
                "images_reclaimable": docker_report.disk.images_reclaimable,
                "containers_size": docker_report.disk.containers_size,
                "containers_reclaimable": docker_report.disk.containers_reclaimable,
                "volumes_size": docker_report.disk.volumes_size,
                "volumes_reclaimable": docker_report.disk.volumes_reclaimable,
                "build_cache_size": docker_report.disk.build_cache_size,
                "build_cache_reclaimable": docker_report.disk.build_cache_reclaimable,
            },
            "cleanup_suggestions": [
                {
                    "severity": s.severity,
                    "title": s.title,
                    "command": s.command,
                    "description": s.description,
                }
                for s in cleanup_suggestions(docker_report, docker_cfg or {})
            ],
            "dangling_images": [
                {
                    "repository": img.repository,
                    "tag": img.tag,
                    "id": img.id,
                    "size": img.size,
                    "created_since": img.created_since,
                }
                for img in docker_report.dangling_images[:20]
            ],
            "containers": [
                {
                    "id": c.id,
                    "name": c.name,
                    "image": c.image,
                    "state": c.state,
                    "status": c.status,
                    "ports": c.ports,
                    "health": c.health,
                }
                for c in docker_report.containers
            ],
            "images": [
                {
                    "repository": img.repository,
                    "tag": img.tag,
                    "id": img.id,
                    "size": img.size,
                    "created_since": img.created_since,
                }
                for img in docker_report.images[:20]
            ],
        },
        "java": _java_to_dict(java_report or collect_java({"enabled": False})),
    }


def _java_to_dict(java_report) -> dict:
    return {
        "enabled": java_report.enabled,
        "available": java_report.available,
        "error": java_report.error,
        "java_home": java_report.java_home,
        "default_java": java_report.default_java,
        "installation_count": java_report.installation_count,
        "jdk_count": java_report.jdk_count,
        "installations": [
            {
                "path": j.path,
                "version": j.version,
                "vendor": j.vendor,
                "runtime_name": j.runtime_name,
                "raw_version": j.raw_version,
                "is_jdk": j.is_jdk,
                "javac_version": j.javac_version,
                "display": j.display,
            }
            for j in java_report.installations
        ],
        "processes": [
            {
                "pid": p.pid,
                "name": p.name,
                "java_path": p.java_path,
                "version": p.version,
                "cmdline": p.cmdline,
            }
            for p in java_report.processes
        ],
    }


def alert_to_dict(alert: Alert) -> dict:
    return {
        "severity": alert.severity,
        "title": alert.title,
        "message": alert.message,
        "hostname": alert.hostname,
        "timestamp": alert.timestamp,
        "source": alert.source,
    }


def run_scan(config: dict) -> dict:
    """Collect health data and return reports + alerts."""
    thresholds = get_thresholds(config)
    process_cfgs = get_process_configs(config)
    port_cfgs = get_port_configs(config)
    docker_cfg = get_docker_config(config)
    java_cfg = get_java_config(config)
    log_patterns, log_files = get_log_config(config)

    system = collect_system()
    proc_report = collect_processes(process_cfgs)
    port_report = collect_ports(port_cfgs)
    log_report = collect_logs(log_patterns, log_files)
    docker_report = collect_docker(docker_cfg)
    java_report = collect_java(java_cfg)
    top_report = collect_top(limit=8, sample_seconds=1.0)
    diagnosis = diagnose(
        system, top_report, docker_report, proc_report, port_report, log_report, thresholds,
    )
    hostname = config.get("sentinel", {}).get("hostname_override", system.ec2.hostname)
    alerts = generate_alerts(
        system, proc_report, port_report, log_report, docker_report,
        thresholds, hostname, docker_cfg,
    )

    return {
        "system": system,
        "proc_report": proc_report,
        "port_report": port_report,
        "log_report": log_report,
        "docker_report": docker_report,
        "java_report": java_report,
        "top_report": top_report,
        "diagnosis": diagnosis,
        "docker_cfg": docker_cfg,
        "thresholds": thresholds,
        "hostname": hostname,
        "alerts": alerts,
    }


def build_health_payload(config: dict, reports_dir: Path | None = None) -> dict:
    """Build JSON payload for the web dashboard API."""
    scan = run_scan(config)
    system = scan["system"]
    proc_report = scan["proc_report"]
    port_report = scan["port_report"]
    log_report = scan["log_report"]
    docker_report = scan["docker_report"]
    java_report = scan["java_report"]
    top_report = scan["top_report"]
    diagnosis = scan["diagnosis"]
    thresholds = scan["thresholds"]
    alerts = scan["alerts"]

    live = {
        "source": "live",
        "report": report_to_dict(
            system, proc_report, port_report, log_report, docker_report,
            top_report, diagnosis, java_report, scan.get("docker_cfg"),
        ),
        "alerts": [alert_to_dict(a) for a in alerts],
        "verdict": build_verdict_dict(
            system, proc_report, port_report, log_report, docker_report, thresholds
        ),
    }

    fleet_dir = reports_dir
    if fleet_dir is None:
        cfg_dir = config.get("sentinel", {}).get("reports_dir")
        if cfg_dir:
            fleet_dir = Path(cfg_dir)

    fleet = load_fleet_reports(fleet_dir)
    interval = get_interval_seconds(config)

    return {
        "live": live,
        "fleet": fleet,
        "thresholds": thresholds,
        "refresh_seconds": interval,
    }


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def run_once(config: dict, output_json: bool = False) -> int:
    """Single health check. Returns exit code (0=ok, 1=warnings, 2=critical)."""
    scan = run_scan(config)
    system = scan["system"]
    proc_report = scan["proc_report"]
    port_report = scan["port_report"]
    log_report = scan["log_report"]
    docker_report = scan["docker_report"]
    java_report = scan["java_report"]
    top_report = scan["top_report"]
    diagnosis = scan["diagnosis"]
    thresholds = scan["thresholds"]
    alerts = scan["alerts"]

    if output_json:
        data = report_to_dict(
            system, proc_report, port_report, log_report, docker_report,
            top_report, diagnosis, java_report,
        )
        print(json.dumps(data, indent=2))
    else:
        print(render_full_report(
            system, proc_report, port_report, log_report, docker_report,
            thresholds, top_report, diagnosis, java_report,
        ))

    # Dispatch alerts
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


def run_web(
    config: dict,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    reports_dir: Path | None = None,
) -> None:
    """Serve local HTML dashboard with live health data."""
    def get_health() -> dict:
        return build_health_payload(config, reports_dir)

    run_web_server(get_health, host=host, port=port, open_browser=open_browser)


# ---------------------------------------------------------------------------
def run_watch(config: dict) -> None:
    """Continuous terminal dashboard — clears and re-renders each cycle."""
    interval = get_interval_seconds(config)

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
    docker_cfg = get_docker_config(config)
    java_cfg = get_java_config(config)

    while running:
        # Clear screen
        os.system("clear" if os.name != "nt" else "cls")

        system = collect_system()
        proc_report = collect_processes(process_cfgs)
        port_report = collect_ports(port_cfgs)
        log_report = collect_logs(log_patterns, log_files)
        docker_report = collect_docker(docker_cfg)
        java_report = collect_java(java_cfg)
        top_report = collect_top(limit=8, sample_seconds=1.0)
        diagnosis = diagnose(
            system, top_report, docker_report, proc_report, port_report,
            log_report, thresholds,
        )

        print(render_full_report(
            system, proc_report, port_report, log_report, docker_report,
            thresholds, top_report, diagnosis, java_report,
        ))
        print(f"  Refreshing every {interval}s. Press Ctrl+C to stop.")

        # Generate alerts in watch mode too
        hostname = config.get("sentinel", {}).get("hostname_override", system.ec2.hostname)
        alerts = generate_alerts(
            system, proc_report, port_report, log_report, docker_report,
            thresholds, hostname, docker_cfg,
        )
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

    interval = get_interval_seconds(config)

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
    docker_cfg = get_docker_config(config)
    java_cfg = get_java_config(config)

    while running:
        try:
            system = collect_system()
            proc_report = collect_processes(process_cfgs)
            port_report = collect_ports(port_cfgs)
            log_report = collect_logs(log_patterns, log_files)
            docker_report = collect_docker(docker_cfg)
            java_report = collect_java(java_cfg)
            top_report = collect_top(limit=8, sample_seconds=1.0)
            diagnosis = diagnose(
                system, top_report, docker_report, proc_report, port_report,
                log_report, thresholds,
            )

            hostname = config.get("sentinel", {}).get("hostname_override", system.ec2.hostname)
            alerts = generate_alerts(
                system, proc_report, port_report, log_report, docker_report,
                thresholds, hostname, docker_cfg,
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

            logger.info(f"Diagnosis: {diagnosis.headline} — {diagnosis.summary}")
            data = report_to_dict(
                system, proc_report, port_report, log_report, docker_report,
                top_report, diagnosis, java_report,
            )
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
  python sentinel.py --web                  # browser dashboard at localhost:8765
  python sentinel.py --config /etc/myconfig.yaml --once
        """,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run once and exit")
    mode.add_argument("--watch", action="store_true", help="Continuous terminal dashboard")
    mode.add_argument("--daemon", action="store_true", help="Background daemon with alerting")
    mode.add_argument("--web", action="store_true", help="Local web dashboard (opens browser)")

    parser.add_argument("--config", "-c", help="Path to config YAML file")
    parser.add_argument("--json", action="store_true", help="Output as JSON (with --once)")
    parser.add_argument("--host", default="127.0.0.1", help="Web dashboard bind address (with --web)")
    parser.add_argument("--port", type=int, default=8765, help="Web dashboard port (with --web)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser (with --web)")
    parser.add_argument(
        "--reports-dir",
        help="Directory of JSON reports from other instances (with --web)",
    )

    args = parser.parse_args()
    config = load_config(args.config)

    if args.once:
        exit_code = run_once(config, output_json=args.json)
        sys.exit(exit_code)
    elif args.watch:
        run_watch(config)
    elif args.daemon:
        run_daemon(config)
    elif args.web:
        sentinel_cfg = config.get("sentinel", {})
        host = sentinel_cfg.get("web_host", args.host)
        port = sentinel_cfg.get("web_port", args.port)
        if "--host" in sys.argv:
            host = args.host
        if "--port" in sys.argv:
            port = args.port
        reports_dir = Path(args.reports_dir) if args.reports_dir else None
        if reports_dir is None and sentinel_cfg.get("reports_dir"):
            reports_dir = Path(sentinel_cfg["reports_dir"])
        run_web(
            config,
            host=host,
            port=port,
            open_browser=not args.no_browser,
            reports_dir=reports_dir,
        )


if __name__ == "__main__":
    main()
