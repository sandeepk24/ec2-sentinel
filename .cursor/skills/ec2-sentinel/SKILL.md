---
name: ec2-sentinel
description: >-
  Develop, extend, and troubleshoot EC2 Sentinel — a lightweight EC2 instance
  health monitor (CPU, memory, disk, processes, ports, logs) with Slack/Email/
  PagerDuty alerting. Use when working in this repo, adding collectors, alert
  channels, config options, bash scripts, systemd install, or fixing import/
  layout issues.
---

# EC2 Sentinel

EC2 Sentinel is a Python 3.9+ Linux health agent for DevOps engineers monitoring
build servers, app servers, and CI/CD infrastructure on EC2. It fills gaps
CloudWatch leaves: process-level checks, port listeners, log pattern scanning,
PID restart detection, disk growth prediction, and CPU steal time.

## Project Layout

```
ec2-sentinel/
├── sentinel.py              # CLI entry point and orchestrator
├── alerts.py                # Alert dispatch (Slack, email, PagerDuty, webhook)
├── config.example.yaml
├── collectors/              # Health data collectors
│   ├── system.py
│   ├── process.py
│   ├── logs.py
│   └── ports.py
├── reporters/
│   └── dashboard.py         # Terminal output
├── scripts/
│   ├── quick-check.sh
│   └── disk-cleanup.sh
├── systemd/
│   └── ec2-sentinel.service
└── .github/workflows/ci.yml
```

## Architecture

```
sentinel.py (orchestrator)
  ├── collectors/system.py   → SystemReport (CPU, mem, disk, EC2 metadata)
  ├── collectors/process.py  → ProcessReport (named services, PID history)
  ├── collectors/logs.py     → LogReport (pattern scan, incremental offsets)
  ├── collectors/ports.py    → PortReport (TCP connect checks)
  ├── reporters/dashboard.py → render_full_report() (ANSI terminal output)
  └── alerts.py              → Alert dataclass + dispatch_alerts()
```

**Data flow per scan cycle:**
1. Load YAML config (or defaults)
2. Run all collectors → structured dataclass reports
3. `generate_alerts()` in `sentinel.py` evaluates thresholds
4. Render terminal/JSON output
5. `dispatch_alerts()` if any alert channel is enabled

## Design Constraints (Do Not Violate)

- **Dependencies:** stdlib + `PyYAML` only. No psutil, no rich, no requests.
- **Data sources:** Read `/proc`, `/sys`, EC2 IMDS (`169.254.169.254`). Use
  `urllib.request`, `socket`, `subprocess` sparingly.
- **Return types:** Collectors return `@dataclass` report objects, never raw dicts.
- **State files:** Persist incremental state under `/tmp/ec2_sentinel_*.json`
  (PID history, log offsets, disk growth, alert dedup). Fail gracefully on
  read/write errors.
- **Terminal output:** ANSI codes via `C` class in dashboard; disable when not a TTY.
- **Secrets:** Config supports `${ENV_VAR}` substitution. Never commit `config.yaml`.

## Run Modes

| Mode | Command | Behavior |
|------|---------|----------|
| Once | `python sentinel.py --once` | Single scan, human report |
| JSON | `python sentinel.py --once --json` | JSON to stdout |
| Watch | `python sentinel.py --watch` | Clears screen, refreshes every `interval_seconds` |
| Daemon | `python sentinel.py --daemon` | Logs to file, dispatches alerts in loop |

**Exit codes (`--once`):** `0` = healthy, `1` = warnings, `2` = critical.

**Config search order:** `--config` flag → `./config.yaml` → `./config.yml` →
`/etc/ec2-sentinel/config.yaml` → `~/.ec2-sentinel/config.yaml` → defaults.

## Config Schema

Copy `config.example.yaml` → `config.yaml`. Key sections:

```yaml
sentinel:
  interval_seconds: 60
  hostname_override: ""
  log_file: "/var/log/ec2-sentinel.log"

thresholds:
  cpu_warn: 80; cpu_crit: 95
  memory_warn: 80; memory_crit: 95
  disk_warn: 75; disk_crit: 90
  swap_warn: 50

processes:
  - name: tomcat
    match: "org.apache.catalina"   # substring match on /proc/*/cmdline
    port: 8080                     # optional; also creates port check

extra_ports: []                   # standalone port checks, optional host

log_watch:
  patterns: ["OutOfMemoryError", ...]
  files: ["/var/log/syslog", "/var/log/tomcat*/catalina.out"]

alerts:
  slack: { enabled: false, webhook_url: "${SENTINEL_SLACK_WEBHOOK}" }
  email: { enabled: false, smtp_host: "...", to: [...] }
  pagerduty: { enabled: false, routing_key: "${SENTINEL_PD_KEY}" }
  webhook: { enabled: false, url: "..." }
```

Process `match` is case-insensitive substring on cmdline. Port checks default
to `127.0.0.1`; set `host` in `extra_ports` for remote checks.

## Alert Generation Rules

Defined in `generate_alerts()` (`sentinel.py`):

| Source | Warning | Critical |
|--------|---------|----------|
| CPU usage | ≥ `cpu_warn` | ≥ `cpu_crit` |
| CPU steal | > 5% | — |
| Memory | ≥ `memory_warn` | ≥ `memory_crit` |
| OOM kills | any since boot | — |
| Disk per mount | ≥ `disk_warn` | ≥ `disk_crit` |
| Process | PID changed (restart) | expected process missing |
| Port | — | TCP connect failed |
| Logs | any pattern hit | — |

Alerts deduplicate for 5 minutes via `/tmp/ec2_sentinel_alert_dedup.json`.

## Adding a New Collector

1. Create `collectors/<name>.py` with:
   - `@dataclass` info types + `<Name>Report` aggregate
   - `collect_<name>(...) -> <Name>Report` public entry point
   - `/proc` or `/sys` reads; no external deps
2. Wire into `sentinel.py`:
   - Import and call in `run_once`, `run_watch`, `run_daemon`
   - Add fields to `report_to_dict()` for JSON output
   - Add evaluation logic in `generate_alerts()`
   - Pass data to `render_full_report()` in dashboard
3. Add config section to `config.example.yaml` + getter in `load_config` helpers
4. Add CI smoke test in `.github/workflows/ci.yml`

## Adding an Alert Channel

1. Add `send_<channel>(alert: Alert, ...) -> bool` in `alerts.py`
2. Register in `dispatch_alerts()` with `_resolve()` for env vars
3. Document in `config.example.yaml` under `alerts:`
4. Respect dedup — call through existing dispatch loop, don't bypass

## Dashboard Changes

`reporters/dashboard.py` exports `render_full_report(system, proc, port, log, thresholds)`.
Add a section renderer (e.g. `render_network()`) and call it from `render_full_report`.
Use `C` for colors and `_status_icon()` for ✅/⚠️/❌ consistency.

## Bash Layer

Zero-dependency scripts for pre-Python triage:

| Script | Purpose |
|--------|---------|
| `quick-check.sh` | CPU, mem, disk, top procs, ports — run first on SSH |
| `disk-cleanup.sh` | Safe artifact/log cleanup; dry-run by default, `--execute` to apply |
| `install.sh` | Install to `/opt/ec2-sentinel`, optional `--systemd` |

**systemd:** `systemd/ec2-sentinel.service` — runs `--daemon`, hardened with
`ProtectSystem=strict`, `ReadWritePaths=/var/log /tmp`.

## Testing & CI

```bash
pip install -r requirements.txt
pip install flake8 mypy

flake8 . --max-line-length=120
python sentinel.py --once
python -c "from collectors.system import collect_system; print(collect_system())"
```

CI matrix: Python 3.9–3.12 on Ubuntu. Smoke tests cover imports, system
collection, port checker, log scanner. ShellCheck on `*.sh`.

## Code Style

- Section dividers: `# ---------------------------------------------------------------------------`
- Type hints on public functions; `list[dict]`, `str | None` (3.9+ via `from __future__` not used — native 3.10+ syntax in places)
- Max line length ~120 (flake8)
- Properties on dataclasses for computed fields (`used_percent`, `status`, `summary`)
- Best-effort I/O: catch `OSError`, `PermissionError`; never crash a scan cycle
- Daemon mode: wrap scan loop in try/except, log via `logging.getLogger("ec2-sentinel")`

## Common Tasks

**Add a monitored service:** Edit `config.yaml` processes list with `name`, `match`, optional `port`.

**Add log pattern:** Add to `log_watch.patterns` and ensure file path in `log_watch.files`.

**Enable Slack alerts:** Set env var, enable in config:
```bash
export SENTINEL_SLACK_WEBHOOK="https://hooks.slack.com/..."
# alerts.slack.enabled: true in config.yaml
```

**Ship as service:**
```bash
sudo ./install.sh --systemd
sudo systemctl status ec2-sentinel
sudo journalctl -u ec2-sentinel -f
```

## Files to Never Commit

- `config.yaml` / `config.yml` (secrets) — listed in `.gitignore`
- Runtime state in `/tmp/ec2_sentinel_*.json`
