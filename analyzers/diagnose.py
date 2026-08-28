"""
Why-is-this-slow diagnosis for junior engineers.

Turns raw metrics into plain-English findings you can read aloud on a call.
"""

from dataclasses import dataclass, field
from typing import Optional

from analyzers.suggestions import ActionSuggestion, resource_suggestions, _proc_display
from collectors.docker import cleanup_suggestions, reclaimable_bytes


@dataclass
class Finding:
    severity: str          # ok | info | warning | critical
    category: str          # cpu | memory | disk | docker | io | capacity
    title: str             # short headline
    what: str              # what we observed
    why_it_matters: str    # impact in plain English
    say_this: str          # what a junior can say to explain it
    next_step: str         # concrete action


@dataclass
class Diagnosis:
    headline: str
    summary: str           # 1–2 sentence elevator pitch
    health: str            # healthy | degraded | critical
    findings: list[Finding] = field(default_factory=list)
    cpu_story: str = ""
    memory_story: str = ""
    talk_track: list[str] = field(default_factory=list)
    suggestions: list[ActionSuggestion] = field(default_factory=list)


def _cpu_offender(top_report) -> str:
    if not top_report or not top_report.by_cpu:
        return ""
    p = top_report.by_cpu[0]
    return f"{_proc_display(p.name, p.cmdline)} (pid {p.pid}, {p.cpu_percent}% CPU)"


def _mem_offender(top_report) -> str:
    if not top_report or not top_report.by_memory:
        return ""
    p = top_report.by_memory[0]
    return f"{_proc_display(p.name, p.cmdline)} (pid {p.pid}, {p.memory_mb} MB)"


def _fmt_gb(b: int) -> str:
    return f"{b / (1024 ** 3):.1f} GB"


def diagnose(
    system,
    top_report,
    docker_report=None,
    proc_report=None,
    port_report=None,
    log_report=None,
    thresholds: Optional[dict] = None,
    cpu_anomaly=None,
    java_report=None,
) -> Diagnosis:
    """Build a human diagnosis from collected reports."""
    t = thresholds or {}
    cpu = system.cpu
    mem = system.memory
    findings: list[Finding] = []
    cpu_offender = _cpu_offender(top_report)
    mem_offender = _mem_offender(top_report)

    # ------------------------------------------------------------------ CPU
    if cpu.steal_percent >= 10:
        findings.append(Finding(
            severity="critical",
            category="cpu",
            title="CPU steal is high — hypervisor is taking your cycles",
            what=f"Steal time is {cpu.steal_percent}% (threshold ~5–10%).",
            why_it_matters=(
                "Your app looks fine inside the guest, but the host is withholding "
                "CPU. Common on T-series when CPU credits are exhausted, or on "
                "noisy neighbors."
            ),
            say_this=(
                f"The instance is slow because CPU steal is {cpu.steal_percent}% — "
                "we're not getting the CPU we paid for. Likely credit exhaustion "
                "or noisy neighbor. Check CloudWatch CPUCreditBalance."
            ),
            next_step="Check CPUCreditBalance; consider moving to M/C family or larger size.",
        ))
    elif cpu.steal_percent > 5:
        findings.append(Finding(
            severity="warning",
            category="cpu",
            title="Elevated CPU steal",
            what=f"Steal time is {cpu.steal_percent}%.",
            why_it_matters="Some of our CPU time is being taken by the hypervisor.",
            say_this=f"We're seeing {cpu.steal_percent}% steal — watch credits if this is a T-series.",
            next_step="Monitor CPU credits; migrate if steal stays high.",
        ))

    if cpu.iowait_percent >= 20:
        findings.append(Finding(
            severity="critical",
            category="io",
            title="CPU is waiting on disk I/O",
            what=f"iowait is {cpu.iowait_percent}% of CPU time.",
            why_it_matters=(
                "The CPU is idle waiting for disk/EBS. Looks like 'high load' "
                "but it's storage latency, not compute."
            ),
            say_this=(
                f"The server feels slow because {cpu.iowait_percent}% of CPU time "
                "is iowait — we're blocked on disk, not CPU-bound."
            ),
            next_step=(
                f"Check EBS metrics; run iotop or docker stats. "
                f"Top CPU right now: {cpu_offender}." if cpu_offender
                else "Check EBS metrics (VolumeQueueLength, Latency); look for disk-heavy processes."
            ),
        ))
    elif cpu.iowait_percent >= 10:
        findings.append(Finding(
            severity="warning",
            category="io",
            title="Noticeable disk wait (iowait)",
            what=f"iowait is {cpu.iowait_percent}%.",
            why_it_matters="Some work is stalled waiting for storage.",
            say_this=f"We're spending {cpu.iowait_percent}% of CPU time waiting on disk I/O.",
            next_step=(
                f"iotop -oPa or docker stats — top CPU process is {cpu_offender}."
                if cpu_offender
                else "Identify which process is doing heavy I/O (iotop / docker stats)."
            ),
        ))

    if cpu.load_avg_1 > cpu.core_count * 1.5:
        findings.append(Finding(
            severity="critical",
            category="cpu",
            title="Load average exceeds CPU capacity",
            what=(
                f"Load {cpu.load_avg_1} on {cpu.core_count} cores "
                f"({cpu.load_per_core}x per core)."
            ),
            why_it_matters="More runnable work than CPUs — processes queue and latency spikes.",
            say_this=(
                f"Load average is {cpu.load_avg_1} with only {cpu.core_count} cores — "
                "we're overloaded. Top CPU consumers are the first place to look."
            ),
            next_step=(
                f"Top CPU: {cpu_offender} — scale, optimize, or stop it."
                if cpu_offender
                else "Scale vertically, add replicas, or stop the top CPU burners."
            ),
        ))
    elif cpu.load_avg_1 > cpu.core_count:
        findings.append(Finding(
            severity="warning",
            category="cpu",
            title="Load average above core count",
            what=f"Load {cpu.load_avg_1} > {cpu.core_count} cores.",
            why_it_matters="Work is starting to queue; responses may get slower.",
            say_this=f"Load ({cpu.load_avg_1}) is above our {cpu.core_count} cores — we're at capacity.",
            next_step=(
                f"Top CPU: {cpu_offender} — review before load grows."
                if cpu_offender
                else "Review top CPU processes; consider scaling if sustained."
            ),
        ))

    if cpu.usage_percent >= t.get("cpu_crit", 95):
        findings.append(Finding(
            severity="critical",
            category="cpu",
            title="CPU nearly saturated",
            what=f"CPU usage at {cpu.usage_percent}% "
                 f"(user {cpu.user_percent}% / system {cpu.system_percent}%).",
            why_it_matters="Little headroom left for bursts; latency will climb.",
            say_this=(
                f"CPU is at {cpu.usage_percent}% — mostly "
                f"{'userland apps' if cpu.user_percent >= cpu.system_percent else 'kernel/system'} "
                f"({cpu.user_percent}% user / {cpu.system_percent}% system)."
            ),
            next_step=(
                f"Top CPU: {cpu_offender} — run top -H -p <pid> or jstack for Java."
                if cpu_offender
                else "Identify top CPU processes; scale or optimize the hot path."
            ),
        ))
    elif cpu.usage_percent >= t.get("cpu_warn", 80):
        findings.append(Finding(
            severity="warning",
            category="cpu",
            title="CPU running hot",
            what=f"CPU at {cpu.usage_percent}% (user {cpu.user_percent}%, system {cpu.system_percent}%).",
            why_it_matters="Approaching saturation — watch for latency.",
            say_this=f"CPU is at {cpu.usage_percent}% and climbing into the danger zone.",
            next_step=(
                f"Top CPU: {cpu_offender} — investigate before critical."
                if cpu_offender
                else "Check top CPU consumers before it hits critical."
            ),
        ))

    # ------------------------------------------------------------------ CPU anomaly (baseline)
    if cpu_anomaly and getattr(cpu_anomaly, "is_anomaly", False):
        offenders = getattr(cpu_anomaly, "offenders", []) or []
        if offenders:
            o = offenders[0]
            offender_txt = f"{o.name} (pid {o.pid}, {o.cpu_percent}% CPU)"
            next_step = f"top -H -p {o.pid}  # investigate {o.name}"
        else:
            offender_txt = "see top CPU list"
            next_step = "Review top CPU processes; compare to this host's usual load."
        findings.append(Finding(
            severity=getattr(cpu_anomaly, "severity", "warning") or "warning",
            category="cpu",
            title=(
                f"Unusual CPU spike vs baseline "
                f"({cpu_anomaly.current_percent}% now, "
                f"baseline {cpu_anomaly.baseline_percent}%)"
            ),
            what=cpu_anomaly.reason,
            why_it_matters=(
                "Static thresholds miss host-specific spikes — a quiet box jumping "
                "from 20% to 70% is often a runaway job even if under 80%."
            ),
            say_this=(
                f"CPU is {cpu_anomaly.current_percent}% versus a recent baseline of "
                f"{cpu_anomaly.baseline_percent}% on this host — unusual. "
                f"Likely offender: {offender_txt}."
            ),
            next_step=next_step,
        ))

    # ------------------------------------------------------------------ Memory
    if mem.swap_used_percent >= 30:
        findings.append(Finding(
            severity="critical",
            category="memory",
            title="Swap thrashing — memory pressure is killing performance",
            what=f"Swap is {mem.swap_used_percent}% used ({_fmt_gb(mem.swap_used_bytes)}).",
            why_it_matters=(
                "The kernel is paging to disk. Even with 'low' CPU, the box will "
                "feel painfully slow."
            ),
            say_this=(
                f"We're swap thrashing — {mem.swap_used_percent}% of swap is in use. "
                "This is why the server is slow even if CPU looks fine."
            ),
            next_step=(
                f"Top memory: {mem_offender} — free RAM or resize instance."
                if mem_offender
                else "Find top RSS processes; free memory or resize the instance."
            ),
        ))
    elif mem.swap_used_percent >= 10:
        findings.append(Finding(
            severity="warning",
            category="memory",
            title="Swap is in use",
            what=f"Swap {mem.swap_used_percent}% used.",
            why_it_matters="Memory pressure is starting; performance may degrade.",
            say_this=f"We're using swap ({mem.swap_used_percent}%) — memory is getting tight.",
            next_step=(
                f"Top memory: {mem_offender} — watch before swap grows."
                if mem_offender
                else "Watch top memory consumers; plan a resize if it grows."
            ),
        ))

    if mem.oom_kill_count > 0:
        findings.append(Finding(
            severity="warning",
            category="memory",
            title="OOM killer has fired",
            what=f"{mem.oom_kill_count} OOM kill(s) since boot.",
            why_it_matters="Processes were killed because the system ran out of memory.",
            say_this=(
                f"The OOM killer has run {mem.oom_kill_count} time(s) — something "
                "exhausted RAM and the kernel killed processes."
            ),
            next_step="Check dmesg for killed PIDs; raise memory or fix the leak.",
        ))

    if mem.used_percent >= t.get("memory_crit", 95):
        findings.append(Finding(
            severity="critical",
            category="memory",
            title="Memory critically low",
            what=(
                f"Memory {mem.used_percent}% used — "
                f"apps ~{_fmt_gb(mem.app_bytes)}, cache {_fmt_gb(mem.cached_bytes)}, "
                f"available {_fmt_gb(mem.available_bytes)}."
            ),
            why_it_matters="Risk of OOM kills and swap thrashing.",
            say_this=(
                f"Only {_fmt_gb(mem.available_bytes)} available of "
                f"{_fmt_gb(mem.total_bytes)}. Top memory hogs are listed below."
            ),
            next_step=(
                f"Top memory: {mem_offender} — restart or kill largest consumer."
                if mem_offender
                else "Kill or restart the largest consumers; resize if chronic."
            ),
        ))
    elif mem.used_percent >= t.get("memory_warn", 80):
        findings.append(Finding(
            severity="warning",
            category="memory",
            title="Memory getting tight",
            what=f"Memory {mem.used_percent}% used, {_fmt_gb(mem.available_bytes)} available.",
            why_it_matters="Less headroom for spikes and caches.",
            say_this=f"Memory is at {mem.used_percent}% — we should identify the top consumers.",
            next_step=(
                f"Top memory: {mem_offender} — review before swap."
                if mem_offender
                else "Review top RSS processes before we tip into swap."
            ),
        ))

    # ------------------------------------------------------------------ Disk
    for d in system.disks:
        if d.mount.startswith("/proc") or d.mount.startswith("/sys"):
            continue
        if d.used_percent >= t.get("disk_crit", 90):
            findings.append(Finding(
                severity="critical",
                category="disk",
                title=f"Disk almost full: {d.mount}",
                what=(
                    f"{d.mount} at {d.used_percent}% ({_fmt_gb(d.free_bytes)} free)."
                    + (
                        f" Growing {d.growth_gb_per_day:+.2f} GB/day — "
                        f"full ~{d.predicted_full_date or f'{d.days_until_full:.0f}d'}."
                        if d.growth_gb_per_day is not None and d.trend == "growing"
                        else ""
                    )
                ),
                why_it_matters="Writes fail, logs stop, databases crash — classic outage.",
                say_this=f"{d.mount} is {d.used_percent}% full — we need space now.",
                next_step=(
                    f"du -xh {d.mount} --max-depth=1 | sort -h; "
                    f"./scripts/disk-cleanup.sh; grow EBS if needed."
                ),
            ))
        elif d.used_percent >= t.get("disk_warn", 75):
            msg = f"{d.mount} at {d.used_percent}%."
            if d.days_until_full is not None:
                msg += f" Predicted full in ~{d.days_until_full:.0f} days."
            if d.growth_gb_per_day is not None:
                msg += (
                    f" Trend {d.trend}: {d.growth_gb_per_day:+.2f} GB/day"
                    f" (80% ~{d.days_until_80}d, 90% ~{d.days_until_90}d, 95% ~{d.days_until_95}d)."
                )
            findings.append(Finding(
                severity="warning",
                category="disk",
                title=f"Disk filling up: {d.mount}",
                what=msg,
                why_it_matters="Build artifacts and logs fill disks quietly.",
                say_this=f"{d.mount} is at {d.used_percent}% — we should clean before it hits critical.",
                next_step=(
                    f"du -xh {d.mount} --max-depth=1 | sort -h | tail -15; "
                    "prune Docker/build caches and rotated logs."
                ),
            ))
        elif (
            d.trend == "growing"
            and d.days_until_90 is not None
            and d.days_until_90 < 21
        ):
            findings.append(Finding(
                severity="warning",
                category="disk",
                title=f"Disk growing fast: {d.mount}",
                what=(
                    f"{d.mount} at {d.used_percent}% but climbing "
                    f"{d.growth_gb_per_day:+.2f} GB/day — "
                    f"~{d.days_until_80}d to 80%, ~{d.days_until_90}d to 90%, "
                    f"~{d.days_until_95}d to 95%"
                    + (f", full ~{d.predicted_full_date}." if d.predicted_full_date else ".")
                ),
                why_it_matters="Growth rate matters more than current % on build servers.",
                say_this=(
                    f"{d.mount} will hit 90% in about {d.days_until_90:.0f} days "
                    f"at the current growth rate."
                ),
                next_step=(
                    f"Identify large dirs on {d.mount}; schedule cleanup before "
                    f"{d.predicted_full_date or 'it fills'}."
                ),
            ))

    # ------------------------------------------------------------------ Docker
    if docker_report and docker_report.available:
        for c in docker_report.unhealthy:
            findings.append(Finding(
                severity="critical",
                category="docker",
                title=f"Unhealthy container: {c.name}",
                what=f"{c.name} ({c.image}) — {c.status}",
                why_it_matters="Service may be up but failing health checks.",
                say_this=f"Container {c.name} is unhealthy — investigate logs before users notice.",
                next_step=f"docker logs {c.name} && docker inspect {c.name}",
            ))
        for c in docker_report.containers:
            if c.state == "restarting":
                findings.append(Finding(
                    severity="warning",
                    category="docker",
                    title=f"Container restart loop: {c.name}",
                    what=f"{c.name} is restarting — {c.status}",
                    why_it_matters="Crash-loop burns CPU and drops traffic.",
                    say_this=f"{c.name} is stuck in a restart loop.",
                    next_step=f"docker logs --tail 100 {c.name}",
                ))

        reclaim_gb = reclaimable_bytes(docker_report.disk) / (1024 ** 3)
        if reclaim_gb >= 5:
            suggestions = cleanup_suggestions(docker_report)
            top_cmd = suggestions[0].command if suggestions else "docker system prune -f"
            findings.append(Finding(
                severity="warning",
                category="docker",
                title=f"Docker using {reclaim_gb:.1f} GB reclaimable disk",
                what=(
                    f"Images {docker_report.disk.images_reclaimable}, "
                    f"cache {docker_report.disk.build_cache_reclaimable}, "
                    f"volumes {docker_report.disk.volumes_reclaimable} reclaimable."
                ),
                why_it_matters="Docker layers and cache fill root volume on build servers.",
                say_this=(
                    f"Docker has {reclaim_gb:.1f} GB we can reclaim — "
                    "likely old images and build cache."
                ),
                next_step=top_cmd,
            ))

        if docker_report.dangling_count >= 5:
            findings.append(Finding(
                severity="warning",
                category="docker",
                title=f"{docker_report.dangling_count} dangling Docker images",
                what="Untagged image layers left over from rebuilds.",
                why_it_matters="Each rebuild can leave orphaned layers that accumulate.",
                say_this=f"We have {docker_report.dangling_count} dangling images eating disk.",
                next_step="docker image prune -f",
            ))

    # ------------------------------------------------------------------ Processes / ports
    if proc_report:
        for p in proc_report.missing:
            findings.append(Finding(
                severity="critical",
                category="capacity",
                title=f"Expected process missing: {p.name}",
                what=f"No process matching '{p.match_pattern}'.",
                why_it_matters="A service that should be running isn't.",
                say_this=f"{p.name} is not running — that's a service outage.",
                next_step=f"systemctl status {p.name} or restart the service.",
            ))
    if port_report:
        for c in port_report.failed:
            findings.append(Finding(
                severity="critical",
                category="capacity",
                title=f"Port closed: {c.port} ({c.service_name})",
                what=f"Nothing accepting connections on {c.port}.",
                why_it_matters="Clients will fail even if a process appears running.",
                say_this=f"Port {c.port} for {c.service_name} is closed.",
                next_step="Check if the service crashed or is bound to the wrong interface.",
            ))

    # ------------------------------------------------------------------ Java / JVM
    if java_report and java_report.enabled and java_report.processes:
        for proc in java_report.processes:
            jvm = proc.jvm
            if not jvm or not jvm.issues:
                continue
            sev = "critical" if (
                jvm.heap_pressure and (jvm.heap_used_percent or 0) >= 95
                or (jvm.thread_count or 0) >= 1000
            ) else "warning"
            heap_txt = (
                f"{jvm.heap_used_percent}% heap"
                if jvm.heap_used_percent is not None
                else "heap pressure"
            )
            findings.append(Finding(
                severity=sev,
                category="memory",
                title=f"JVM stress: pid {proc.pid} ({proc.name})",
                what="; ".join(jvm.issues),
                why_it_matters=(
                    "High heap, GC churn, or thread explosion causes latency, "
                    "timeouts, and eventual OOM on Java services."
                ),
                say_this=(
                    f"Java pid {proc.pid} shows {heap_txt}"
                    + (f", {jvm.thread_count} threads" if jvm.thread_count else "")
                    + (f", GC {jvm.gc_time_percent}% of uptime" if jvm.gc_time_percent else "")
                    + "."
                ),
                next_step=(
                    f"jcmd {proc.pid} GC.heap_info; jstack {proc.pid} | head -200"
                ),
            ))

    # ------------------------------------------------------------------ Stories
    top_cpu = top_report.by_cpu[:5] if top_report else []
    top_mem = top_report.by_memory[:5] if top_report else []

    if top_cpu:
        parts = [f"{p.name} ({p.cpu_percent}%)" for p in top_cpu[:3]]
        cpu_story = (
            f"CPU breakdown: {cpu.user_percent}% user · {cpu.system_percent}% system · "
            f"{cpu.iowait_percent}% iowait · {cpu.steal_percent}% steal · {cpu.idle_percent}% idle. "
            f"Top burners: {', '.join(parts)}."
        )
    else:
        cpu_story = (
            f"CPU breakdown: {cpu.user_percent}% user · {cpu.system_percent}% system · "
            f"{cpu.iowait_percent}% iowait · {cpu.steal_percent}% steal · {cpu.idle_percent}% idle."
        )

    if top_mem:
        parts = [f"{p.name} ({p.memory_mb} MB)" for p in top_mem[:3]]
        memory_story = (
            f"Memory map: apps ~{_fmt_gb(mem.app_bytes)} · cache {_fmt_gb(mem.cached_bytes)} · "
            f"buffers {_fmt_gb(mem.buffers_bytes)} · available {_fmt_gb(mem.available_bytes)} "
            f"of {_fmt_gb(mem.total_bytes)}. "
            f"Top RSS: {', '.join(parts)}."
        )
    else:
        memory_story = (
            f"Memory map: apps ~{_fmt_gb(mem.app_bytes)} · cache {_fmt_gb(mem.cached_bytes)} · "
            f"available {_fmt_gb(mem.available_bytes)} of {_fmt_gb(mem.total_bytes)}."
        )

    # ------------------------------------------------------------------ Health rollup
    sevs = {f.severity for f in findings}
    if "critical" in sevs:
        health = "critical"
        headline = "Something needs attention now"
    elif "warning" in sevs:
        health = "degraded"
        headline = "Degraded — explainable issues found"
    else:
        health = "healthy"
        headline = "Looking healthy"
        findings.append(Finding(
            severity="ok",
            category="capacity",
            title="No major pressure signals",
            what="CPU, memory, disk, and I/O look within normal ranges.",
            why_it_matters="You have headroom for normal traffic.",
            say_this="No red flags — the instance has headroom on CPU, memory, and disk.",
            next_step="Keep watching top consumers if latency reports come in.",
        ))

    # Elevator pitch
    crits = [f for f in findings if f.severity == "critical"]
    warns = [f for f in findings if f.severity == "warning"]
    if crits:
        summary = crits[0].say_this
    elif warns:
        summary = warns[0].say_this
    else:
        summary = (
            f"Host is healthy: CPU {cpu.usage_percent}%, "
            f"memory {mem.used_percent}% used ({_fmt_gb(mem.available_bytes)} available), "
            f"load {cpu.load_avg_1} on {cpu.core_count} cores."
        )

    talk_track = [f.say_this for f in findings if f.severity in ("critical", "warning")][:5]
    if not talk_track:
        talk_track = [summary]

    suggestions = resource_suggestions(system, top_report, docker_report, t)

    return Diagnosis(
        headline=headline,
        summary=summary,
        health=health,
        findings=findings,
        cpu_story=cpu_story,
        memory_story=memory_story,
        talk_track=talk_track,
        suggestions=suggestions,
    )


def diagnosis_to_dict(d: Diagnosis) -> dict:
    return {
        "headline": d.headline,
        "summary": d.summary,
        "health": d.health,
        "cpu_story": d.cpu_story,
        "memory_story": d.memory_story,
        "talk_track": d.talk_track,
        "suggestions": [
            {
                "severity": s.severity,
                "category": s.category,
                "title": s.title,
                "command": s.command,
                "description": s.description,
                "process_name": s.process_name,
                "pid": s.pid,
            }
            for s in d.suggestions
        ],
        "findings": [
            {
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "what": f.what,
                "why_it_matters": f.why_it_matters,
                "say_this": f.say_this,
                "next_step": f.next_step,
            }
            for f in d.findings
        ],
    }
