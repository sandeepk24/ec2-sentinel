# EC2 Sentinel 🛡️

**The EC2 health monitoring toolkit built by DevOps engineers who are tired of finding out about problems from angry Slack messages.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## The Problem We All Know

It's 3 AM. PagerDuty fires. The Bamboo build server ran out of disk space 4 hours ago. 
Jenkins hasn't built anything since Tuesday. The JBoss instance serving the payment 
API has been at 98% memory for 6 hours, and nobody noticed because CloudWatch alarms 
were set to "breaching" on a threshold that hasn't been updated since 2019.

**You've been there. We've all been there.**

EC2 Sentinel is the monitoring agent you install on Day 1 and forget about — until 
it saves your weekend by catching the disk fill at 75%, the zombie Tomcat process, 
or the Spring Boot app that's been OOM-killed and restarted 14 times since midnight.

```
┌─────────────────────────────────────────────────────────┐
│                    EC2 SENTINEL                         │
│                                                         │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│   │   CPU    │  │  MEMORY  │  │   DISK   │             │
│   │  ██░░░   │  │  █████░  │  │  ███░░░  │             │
│   │   34%    │  │   82%    │  │   61%    │             │
│   └──────────┘  └──────────┘  └──────────┘             │
│                                                         │
│   PROCESSES           PORTS          LOG PATTERNS       │
│   ✅ tomcat (pid 1842) ✅ 8080       ⚠️  3 OOM events  │
│   ✅ jenkins (pid 904) ✅ 8443       ⚠️  disk warn x7  │
│   ❌ jboss (MISSING)   ❌ 9990       ✅  no crit errors │
│                                                         │
│   Last scan: 2 min ago │ Alerts: 2 firing │ Uptime: 47d│
└─────────────────────────────────────────────────────────┘
```

## Web Dashboard — Dark Mode Preview

<p align="center">
  <a href="docs/dashboard-preview-dark.html">
    <img src="docs/assets/dashboard-dark.png" alt="EC2 Sentinel dark mode web dashboard with live CPU and memory charts, executive diagnosis, and host health verdict" width="920"/>
  </a>
</p>

<p align="center">
  <strong>Live React dashboard</strong> — charts, executive diagnosis, top consumers, Docker status, and a plain-English “why is this slow?” summary.<br/>
  <a href="docs/dashboard-preview-dark.html">Open interactive HTML preview →</a>
</p>

**Try it in under a minute:**

```bash
curl -sSL https://raw.githubusercontent.com/sandeepk24/ec2-sentinel/main/install.sh | bash
cd ec2-sentinel && python sentinel.py --web
# → http://127.0.0.1:8765
```

No AWS API keys. No central server. Install on the instance, open the browser, done.

## Who Is This For?

If your daily routine looks anything like this, EC2 Sentinel was built for you:

- **SSH into 5-15 EC2 instances** before your first coffee
- **Babysit CI/CD servers** — Bamboo, Jenkins, ArgoCD, GitLab Runners
- **Monitor app servers** — JBoss, Tomcat, Spring Boot, Node.js services
- **Watch source control infra** — Bitbucket, GitLab, Gitea self-hosted instances
- **Chase down disk space** on build servers that accumulate artifacts like hoarders
- **Restart zombie processes** that died silently over the weekend
- **Explain to management** why the server went down (with actual data this time)

## What It Monitors

| Category | What's Checked | Why It Matters |
|----------|---------------|----------------|
| **CPU** | Usage breakdown (user/system/iowait/steal), load, top burners | Not just "% busy" — shows *where* cycles go and who is burning them. |
| **Memory** | Apps vs cache vs available, swap, OOM, top RSS | Explains real pressure vs "Linux ate my RAM" cache myths. |
| **Diagnosis** | Plain-English "why is this slow?" + talk track | Juniors can articulate the outage without guessing. |
| **Disk** | Usage per mount, inode count, growth rate prediction | "/var/log filled up" is the #1 preventable outage. |
| **Processes** | Named service health, PID tracking, restart detection | That JBoss instance restarted 5 times today? Now you'll know. |
| **Ports** | TCP listener checks for known services | Tomcat not listening on 8080? Catch it before users do. |
| **Logs** | Pattern scanning for errors, OOM, disk warnings | Grep at scale — find "OutOfMemoryError" across 30 log files. |
| **Docker** | Containers, images, disk usage, health checks | Build servers and app hosts running Docker — catch stopped or unhealthy containers. |
| **Network** | Connectivity to downstream dependencies | Your app is up but can't reach the database? That's this. |

## Deployment Model — Read This First

> **Disclaimer:** EC2 Sentinel is a **local on-instance agent**. It does **not** SSH into
> servers, connect to AWS APIs, or provide a central multi-host dashboard out of the box.
> If you're looking for a tool that polls your fleet from one place, this isn't it — and
> that's intentional.

### How it actually works

EC2 Sentinel runs **on each EC2 instance you want to monitor**. It reads that machine's
own resources directly — `/proc`, local log files, TCP port checks, and the EC2 Instance
Metadata Service (IMDS at `169.254.169.254`). No AWS credentials, boto3, or remote access
required.

```
  You (SSH once to install)          Each EC2 instance runs its own Sentinel
         │                                    │
         ▼                                    ▼
  ┌─────────────┐              ┌──────────────────────────────┐
  │ install.sh  │─────────────▶│  Sentinel on instance A    │──▶ Slack / PagerDuty
  │  or Ansible │              │  (monitors itself locally) │
  └─────────────┘              └──────────────────────────────┘
         │
         └────────────────────▶┌──────────────────────────────┐
                              │  Sentinel on instance B    │──▶ Slack / PagerDuty
                              │  (monitors itself locally) │
                              └──────────────────────────────┘
```

### To monitor 10 EC2 instances

Install Sentinel on **all 10**. Each instance:

1. Collects its own CPU, memory, disk, process, port, and log data
2. Evaluates thresholds from its own `config.yaml`
3. Sends its own alerts (Slack, email, PagerDuty, webhook, or JSON to stdout)

Common install paths:

| Method | When to use |
|--------|-------------|
| `install.sh --systemd` | Manual or one-off setup |
| EC2 user-data | Auto-install on launch |
| Ansible / Terraform | Fleet rollout |

### What it does NOT do

| Expectation | Reality |
|-------------|---------|
| SSH into remote servers | ❌ No SSH client — runs locally only |
| Discover EC2 instances via AWS API | ❌ No boto3 or IAM permissions needed |
| Central web dashboard for all hosts | ❌ No remote polling — use `--web` on one box + `--reports-dir` for fleet JSON |
| Replace CloudWatch entirely | ❌ Complements CloudWatch with on-box checks CloudWatch misses |

The README mentions SSH because **you** SSH in to install or troubleshoot — Sentinel
itself never opens SSH sessions. The only optional remote behavior is a TCP port check
to another host (e.g. a database on `10.0.1.100`), which is not SSH.

### Want a central dashboard?

Run the **local web dashboard** on one machine:

```bash
# Live view of this instance (opens http://127.0.0.1:8765 in your browser)
python sentinel.py --web

# Aggregate JSON reports from your fleet (one JSON file per instance)
python sentinel.py --web --reports-dir /var/log/ec2-sentinel/fleet/
```

On each monitored instance, drop periodic JSON via cron:

```bash
*/5 * * * * /opt/ec2-sentinel/sentinel.py --once --json > /var/log/ec2-sentinel/fleet/$(hostname).json
```

Copy or sync those files to the dashboard host's `--reports-dir` to see every box in one browser tab.
For a hosted fleet view, you can also pipe `--once --json` into CloudWatch, Datadog, or a log aggregator.

## Quick Start

### One-Line Install (recommended)

```bash
curl -sSL https://raw.githubusercontent.com/sandeepk24/ec2-sentinel/main/install.sh | bash
```

### Manual Install

```bash
git clone https://github.com/sandeepk24/ec2-sentinel.git
cd ec2-sentinel
pip install -r requirements.txt
cp config.example.yaml config.yaml   # edit this
```

### First Run

```bash
# Quick health check — see results immediately
python sentinel.py --once

# Watch mode — continuous monitoring with terminal dashboard
python sentinel.py --watch

# Daemon mode — background monitoring with alerting
python sentinel.py --daemon

# Web dashboard — view everything in your browser at http://127.0.0.1:8765
python sentinel.py --web
```

The dashboard is a **dynamic SPA** (not a static snapshot):

| Layer | Stack |
|-------|--------|
| UI | React 19 + TypeScript + Vite 6 + Tailwind CSS 4 |
| Data | TanStack Query (live polling of `/api/health`) |
| Charts | Recharts (CPU/memory history while the page is open) |
| Motion | Framer Motion |
| Icons | Lucide |
| State | Zustand (client-side metric history) |

It auto-refreshes, shows a countdown to the next poll, and supports manual refresh.
No Node required at runtime — built assets live in `reporters/web/dist/`.

**Develop the UI locally:**

```bash
# Terminal 1 — API server
python sentinel.py --web --no-browser

# Terminal 2 — hot reload frontend
cd reporters/web-ui && npm install && npm run dev
# Opens http://localhost:5173 (proxies /api to :8765)
```

**Rebuild after UI changes:**

```bash
cd reporters/web-ui && npm run build
```

### What You'll See

```
$ python sentinel.py --once

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EC2 SENTINEL — Health Report
  Host: ip-10-0-1-47   Instance: i-0a1b2c3d4e
  Region: us-east-1    Type: m5.xlarge
  Scan time: 2026-08-09 14:32:01 UTC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SYSTEM
  ├─ CPU .............. 34.2%  (4 cores, load avg: 1.82)
  ├─ Memory ........... 6.1 / 8.0 GB  (76.3%)
  ├─ Swap ............. 0.2 / 2.0 GB  (10.0%)
  └─ Uptime ........... 47 days, 3:14:22

  DISK
  ├─ /     ............ 61.3%   (18.4 / 30.0 GB)  ✅
  ├─ /var  ............ 78.9%   (23.7 / 30.0 GB)  ⚠️  WARN
  └─ /tmp  ............ 12.1%   ( 1.2 / 10.0 GB)  ✅

  PROCESSES
  ├─ tomcat (pid 1842) ............... ✅ RUNNING   (cpu: 12%, mem: 1.2G)
  ├─ jenkins (pid 904) ............... ✅ RUNNING   (cpu:  3%, mem: 2.1G)
  ├─ jboss (EXPECTED) ................ ❌ NOT FOUND
  └─ springboot-api (pid 2201) ....... ✅ RUNNING   (cpu:  8%, mem: 0.8G)

  PORTS
  ├─ 8080 (tomcat) .... ✅ LISTENING
  ├─ 8443 (jenkins) ... ✅ LISTENING
  ├─ 9990 (jboss) ..... ❌ CLOSED — process missing
  └─ 8081 (api) ....... ✅ LISTENING

  LOG PATTERNS (last 1h)
  ├─ OutOfMemoryError .......... 3 hits  ⚠️  [/var/log/tomcat/catalina.out]
  ├─ disk space ................ 7 hits  ⚠️  [/var/log/syslog]
  └─ CRITICAL|FATAL ............ 0 hits  ✅

  ──────────────────────────────────────────
  VERDICT: 3 warnings, 1 critical
  Action needed: jboss process missing, /var disk at 78.9%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Configuration

EC2 Sentinel uses a single YAML config file. Here's the philosophy: **monitor what matters to YOU, not what a vendor thinks matters.**

```yaml
# config.yaml — tell Sentinel what to watch
sentinel:
  interval_seconds: 60          # how often to scan
  hostname_override: "build-server-01"  # friendly name

thresholds:
  cpu_warn: 80
  cpu_crit: 95
  memory_warn: 80
  memory_crit: 95
  disk_warn: 75                 # catch it early
  disk_crit: 90                 # you're in trouble
  swap_warn: 50

# The services YOU care about on THIS server
processes:
  - name: tomcat
    match: "org.apache.catalina"
    port: 8080
  - name: jenkins
    match: "jenkins.war"
    port: 8443
  - name: jboss
    match: "jboss.home"
    port: 9990
  - name: springboot-api
    match: "myapp.jar"
    port: 8081

# Log files to scan for trouble
log_watch:
  patterns:
    - "OutOfMemoryError"
    - "No space left on device"
    - "CRITICAL"
    - "FATAL"
    - "Connection refused"
    - "Too many open files"
  files:
    - /var/log/syslog
    - /var/log/tomcat*/catalina.out
    - /var/log/jenkins/jenkins.log
    - /opt/jboss/standalone/log/server.log

# Where to send alerts
alerts:
  slack:
    enabled: true
    webhook_url: "${SENTINEL_SLACK_WEBHOOK}"  # use env var
    channel: "#ops-alerts"
  email:
    enabled: false
    smtp_host: "smtp.company.com"
    to: ["oncall@company.com"]
  pagerduty:
    enabled: false
    routing_key: "${SENTINEL_PD_KEY}"
```

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                        sentinel.py                             │
│                     (orchestrator)                              │
│                                                                │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │  Collector   │ │  Collector   │ │  Collector   │             │
│  │   system     │ │  process     │ │    logs      │             │
│  │  (CPU/Mem/   │ │  (PID track, │ │  (pattern    │             │
│  │   Disk/Net)  │ │   restarts)  │ │   scanner)   │             │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘            │
│         │                │                │                     │
│         ▼                ▼                ▼                     │
│  ┌─────────────────────────────────────────────┐               │
│  │            Health Report (dict)             │               │
│  └──────────────────┬──────────────────────────┘               │
│                     │                                           │
│         ┌───────────┼───────────┐                              │
│         ▼           ▼           ▼                              │
│  ┌───────────┐ ┌─────────┐ ┌─────────┐                        │
│  │  Terminal  │ │  Alert  │ │  JSON   │                        │
│  │ Dashboard  │ │ Dispatch│ │  Log    │                        │
│  │ (rich tui) │ │ (slack/ │ │ (file/  │                        │
│  │            │ │  email) │ │ stdout) │                        │
│  └───────────┘ └─────────┘ └─────────┘                        │
└────────────────────────────────────────────────────────────────┘

Bash layer:
  install.sh ─── bootstrap, deps, systemd unit, cron fallback
  quick-check.sh ─── zero-dep one-liner health check (no python needed)
  disk-cleanup.sh ─── safe artifact/log cleanup for build servers
```

## Project Structure

```
ec2-sentinel/
├── sentinel.py              # Main entry point and orchestrator
├── config.example.yaml      # Example configuration
├── requirements.txt         # Python dependencies
├── alerts.py                # Slack / Email / PagerDuty dispatch
├── collectors/
│   ├── __init__.py
│   ├── system.py            # CPU, memory, disk, network, EC2 metadata
│   ├── process.py           # Service/process health and restart detection
│   ├── logs.py              # Log file pattern scanning
│   ├── ports.py             # TCP port/listener checks
│   ├── docker.py            # Docker containers, images, disk usage
│   └── top.py               # Top CPU / memory consumers
├── analyzers/
│   └── diagnose.py          # Why-is-this-slow narrative for juniors
├── reporters/
│   ├── __init__.py
│   ├── dashboard.py         # Terminal output and formatting
│   ├── web_server.py        # Local HTTP server for --web mode
│   ├── web/
│   │   └── dist/            # Built React dashboard (served by --web)
│   └── web-ui/              # React + Vite source (npm run build)
├── scripts/
│   ├── quick-check.sh       # Zero-dependency bash health check
│   └── disk-cleanup.sh      # Safe disk cleanup for build servers
├── systemd/
│   └── ec2-sentinel.service # systemd unit file
├── install.sh               # One-line installer
└── .github/
    └── workflows/
        └── ci.yml           # CI pipeline
```

## The Bash Layer — Because Sometimes Python Isn't There Yet

Not every EC2 instance has Python 3.9 and pip ready to go. The `scripts/` directory 
contains zero-dependency bash scripts for the moments when you need answers NOW.

### quick-check.sh — The First Thing You Run

```bash
# SSH into a troubled server, run this immediately
curl -sSL https://raw.githubusercontent.com/sandeepk24/ec2-sentinel/main/scripts/quick-check.sh | bash
```

This gives you CPU, memory, disk, top processes, and listening ports in under 2 seconds, with zero dependencies beyond bash and standard Linux tools.

### disk-cleanup.sh — The Safe Way to Free Space

```bash
# Preview what would be cleaned (dry run by default)
./scripts/disk-cleanup.sh

# Actually clean up
./scripts/disk-cleanup.sh --execute
```

Targets the usual suspects: old build artifacts, rotated logs, package manager caches, 
Docker build cache, and temp files. Won't touch anything less than 7 days old by default.

## Running as a Service

### systemd (recommended)

```bash
sudo ./install.sh --systemd

# Then:
sudo systemctl status ec2-sentinel
sudo journalctl -u ec2-sentinel -f
```

### Cron (fallback)

```bash
# Run every 5 minutes, log to file
*/5 * * * * /opt/ec2-sentinel/sentinel.py --once --json >> /var/log/ec2-sentinel.json 2>&1
```

## Real-World Scenarios

### Scenario 1: Build Server Disk Fill

Your Bamboo/Jenkins build server accumulates artifacts. EC2 Sentinel tracks disk growth rate 
and predicts when you'll hit critical:

```
⚠️  DISK WARNING — /var at 76.2%
    Growth rate: 1.3 GB/day
    Predicted full: 18 days
    Top consumers:
      /var/lib/jenkins/workspace    12.4 GB
      /var/log                       3.2 GB
      /var/cache                     1.8 GB
    Action: Run disk-cleanup.sh or increase EBS volume
```

### Scenario 2: Silent JBoss Crash

JBoss went down at 2 AM, systemd restarted it, but nobody checked if it actually 
came back healthy:

```
❌ CRITICAL — jboss process restarted
   Previous PID: 14523 (started 2026-08-01 09:00)
   Current PID:  28891 (started 2026-08-09 02:14)
   Port 9990: CLOSED (management interface not responding)
   Log: "WFLYCTL0013: Operation timed out" (3 occurrences since 02:14)
   Action: JBoss started but management API is not responding — investigate deployment state
```

### Scenario 3: Noisy Neighbor on EC2

Your app is slow but CPU usage looks normal. EC2 Sentinel checks steal time:

```
⚠️  CPU STEAL TIME: 14.2%
    Your instance (t3.large) is experiencing CPU throttling.
    This means the hypervisor is taking cycles from your vCPUs.
    Likely causes:
      - T-series instance with exhausted CPU credits
      - Oversubscribed host (rare on dedicated/metal)
    Action: Check CPU credit balance or migrate to M/C series
```

## Alert Integrations

| Channel | Status | Notes |
|---------|--------|-------|
| **Slack** | ✅ Supported | Webhook-based, rich formatting |
| **Email** | ✅ Supported | SMTP with TLS |
| **PagerDuty** | ✅ Supported | Events API v2 |
| **Webhook** | ✅ Supported | Generic POST — wire up to anything |
| **stdout/JSON** | ✅ Built-in | Pipe to CloudWatch agent, Datadog, Splunk |

## Comparison: Why Not Just Use CloudWatch?

| Feature | CloudWatch | EC2 Sentinel |
|---------|-----------|--------------|
| Basic CPU/Disk | ✅ | ✅ |
| Process-level monitoring | ❌ (needs custom metrics) | ✅ built-in |
| Log pattern scanning | ⚠️ (CloudWatch Logs agent + filter) | ✅ single config |
| Port health checks | ❌ | ✅ built-in |
| Disk growth prediction | ❌ | ✅ built-in |
| Restart detection | ❌ | ✅ tracks PID changes |
| Steal time alerting | ❌ (metric exists, alarm is manual) | ✅ built-in |
| Cost | $3-10+/instance/month | Free |
| Setup time | 30-60 min per instance | 2 minutes |
| Works without AWS access | ❌ | ✅ |

**EC2 Sentinel doesn't replace CloudWatch** — it fills the gaps that CloudWatch 
leaves on the instance itself. Use both.

## Requirements

- **Python 3.9+** (for the full agent)
- **Bash 4+** (for the shell scripts — any modern Linux has this)
- **Linux** (tested on Amazon Linux 2/2023, Ubuntu 20.04+, RHEL 8+)
- **No root required** for monitoring (root needed for systemd install)

## Contributing

This project was born from years of SSH-ing into production EC2 instances and wishing 
this tool existed. If you've got a monitoring check you run manually every day, 
open a PR and let's automate it.

**Areas where contributions are especially welcome:**
- Windows Server support (yes, some of us run EC2 on Windows)
- Additional alert integrations (Teams, Discord, OpsGenie)
- Application-specific collectors (nginx, PostgreSQL, Redis)
- CloudWatch custom metric publishing

## License

MIT — Use it, fork it, deploy it at 3 AM.

---

**Built by DevOps engineers, for DevOps engineers.**

*If EC2 Sentinel saved your weekend, star the repo.* ⭐
