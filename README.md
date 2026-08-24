# EC2 Sentinel 🛡️

**A quick health check for the EC2 box you're already SSH'd into.**

DevOps engineers spend a lot of time answering the same questions on every instance: *What's eating CPU? Why is memory full? Which process from `ps -ef` is supposed to be running but isn't?* Add Jenkins, Bamboo, Bitbucket, Tomcat, or JBoss on top of that — and half the incident is just figuring out **what** broke before you can fix it.

EC2 Sentinel runs on the instance and gives you that answer in one place. Less time digging through `/proc`, logs, and port checks. More time actually fixing things.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## What you get

- **CPU, memory, disk, swap** — usage, load, and what's consuming resources
- **Top offenders** — ranks the biggest CPU and memory hogs (~1s sample, like `top`)
- **Suggested actions** — names the hot process (pid + %) and gives copy-paste commands (`top -H`, `jstack`, `du`, `docker prune`)
- **Processes** — is Jenkins / Bamboo / Tomcat / JBoss actually running? Did it restart?
- **Java / JVM** — installed JDK/JRE versions plus running Java processes (like `ps -ef | grep java`)
- **Docker** — containers, images, dangling layers, build cache, and disk reclaimable space with cleanup tips
- **Ports** — is the service listening on the port you expect?
- **Logs** — scans for OOM, disk full, CRITICAL/FATAL patterns
- **Plain-English diagnosis** — a short "why is this slow?" summary for the team
- **Auto-detected host info** — Linux distro/version (Ubuntu, Amazon Linux, RHEL, …), EC2 instance type, region, and cloud provider
- **Alerts** — Slack, email, PagerDuty, or JSON to stdout

Runs locally on the instance. No AWS API keys. No central server required.

---

## What's new

- **OS & instance auto-detection** — reads `/etc/os-release` for distro flavor/version and resolves instance type via IMDSv2, IMDSv1, or cloud-init (works across Amazon Linux, Ubuntu, RHEL, Rocky, and local dev hosts)
- **Pinpointed resource suggestions** — diagnosis panel names the top CPU/memory offender and suggests runnable fixes (thread dumps for Java, `du` for full disks, `disk-cleanup.sh`, Docker prune commands)
- **Docker disk waste reporting** — dashboard shows build cache, dangling images, reclaimable space, and severity-ranked cleanup commands
- **Running Java processes** — lists every JVM on the box (PID, binary, command line), like `ps -ef | grep java`, even when no JDK is installed
- **Top CPU/memory panel** — dashboard shows which processes are eating the instance, with a plain-English explanation
- **5-minute refresh** — dashboard polls every 5 minutes; older configs using 30/60s intervals upgrade to 5 minutes on load

---

## Minimum requirements

| | |
|---|---|
| **OS** | Linux on EC2 — Amazon Linux 2/2023, Ubuntu 20.04+, RHEL 8+, Rocky, Alma, Debian (auto-detected via `/etc/os-release`) |
| **Python** | 3.9+ with `pip` |
| **Dependencies** | One package: `PyYAML` (everything else is Python stdlib + `/proc`) |
| **AWS / IAM** | None — no API keys, no boto3, no CloudWatch agent. Instance type/region from IMDS or cloud-init |
| **Root** | Not required to run scans; `sudo` only if you install to `/opt` or use systemd |
| **Disk / RAM** | Negligible — no database, no heavy agents |

**Optional:** Docker CLI (for container checks), read access to log paths in your config, outbound HTTPS (for Slack/PagerDuty alerts).

**No Python?** Bash-only quick check — no install:

```bash
curl -sSL https://raw.githubusercontent.com/sandeepk24/ec2-sentinel/main/scripts/quick-check.sh | bash
```

---

## Install

**One command on the EC2 instance:**

```bash
curl -sSL https://raw.githubusercontent.com/sandeepk24/ec2-sentinel/main/install.sh | sudo bash
```

Installs to `/opt/ec2-sentinel`, adds the `ec2-sentinel` command, and creates `config.yaml`.

**Run it:**

```bash
sudo ec2-sentinel --once          # health report in the terminal
sudo ec2-sentinel --web           # dashboard → http://127.0.0.1:8765
sudo ec2-sentinel --daemon        # background monitoring + alerts
```

Edit `/opt/ec2-sentinel/config.yaml` for your Jenkins, Bamboo, Tomcat, etc.

**Run as a service (optional):**

```bash
curl -sSL https://raw.githubusercontent.com/sandeepk24/ec2-sentinel/main/install.sh | sudo bash -s -- --systemd
sudo systemctl status ec2-sentinel
```

Without `sudo`, the installer uses `~/.ec2-sentinel` instead of `/opt/ec2-sentinel`.

---

## Dashboard

<p align="center">
  <a href="docs/dashboard-preview-dark.html">
    <img src="docs/assets/dashboard-dark.png" alt="EC2 Sentinel web dashboard" width="920"/>
  </a>
</p>

<p align="center">
  Live charts, process status, suggested actions, Docker cleanup tips, and a plain-English diagnosis — <a href="docs/dashboard-preview-dark.html">open preview →</a>
</p>

Auto-refreshes every 5 minutes. Manual refresh anytime. Built React UI — no Node needed at runtime.

The dashboard header shows **auto-detected OS** (e.g. Ubuntu 22.04, Amazon Linux 2023) and **instance type** (e.g. `m5.xlarge`). The diagnosis panel includes a **Suggested actions** tile that pinpoints which app is burning CPU or memory and lists copy-paste commands to investigate or clean up.

---

## Configure what matters on *this* server

Edit `config.yaml` and name the services you care about:

```yaml
sentinel:
  interval_seconds: 300          # scan every 5 minutes

processes:
  - name: jenkins
    match: "jenkins.war"
    port: 8443
  - name: bamboo
    match: "bamboo"
    port: 8085
  - name: tomcat
    match: "org.apache.catalina"
    port: 8080

java:
  enabled: true
  track_processes: true          # list running JVMs (ps -ef | grep java)

log_watch:
  patterns:
    - "OutOfMemoryError"
    - "No space left on device"
    - "CRITICAL"
  files:
    - /var/log/syslog
    - /var/log/jenkins/jenkins.log

alerts:
  slack:
    enabled: true
    webhook_url: "${SENTINEL_SLACK_WEBHOOK}"
```

See `config.example.yaml` for thresholds, Docker checks (cache/dangling image alerts), Java/JDK detection, and more.

**Docker thresholds** (optional):

```yaml
docker:
  enabled: true
  disk_reclaim_warn_gb: 5        # alert when reclaimable Docker disk exceeds this
  cache_warn_gb: 2               # alert when build cache is large
  dangling_warn_count: 5         # alert when untagged images pile up
  images_warn_count: 50
```

---

## How it works

EC2 Sentinel is an **on-instance agent**. Install it on each EC2 you want to watch. It reads local `/proc`, log files, port state, and (optionally) the Docker CLI — it does not SSH into other hosts or call AWS APIs.

On startup each scan auto-detects:

| Signal | Source |
|--------|--------|
| Linux distro & version | `/etc/os-release` (fallback: `/etc/redhat-release`, etc.) |
| Kernel & arch | `uname` / `/proc` |
| EC2 instance type & region | IMDSv2 → IMDSv1 → cloud-init `instance-data.json` |
| Top CPU/memory consumers | `/proc` sampling (~1s) |

```
  install on instance  →  scan CPU / mem / disk / processes / ports / logs / docker  →  terminal, web UI, or alert
```

**Monitor multiple instances:** run `ec2-sentinel --once --json` on each box (cron works well), sync the JSON files to one host, then:

```bash
ec2-sentinel --web --reports-dir /path/to/fleet-json/
```

---

## Contributing

Got a check you run manually on every incident? Open a PR — PRs welcome for new collectors, alert channels, and app-specific checks.

## License

MIT
