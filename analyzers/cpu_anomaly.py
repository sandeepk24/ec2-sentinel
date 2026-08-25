"""
Lightweight CPU anomaly detection against a local rolling baseline.

Stores recent CPU samples under /tmp and flags spikes that are unusual
for *this* host — not just above a static 80%/95% threshold.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


HISTORY_FILE = Path("/tmp/ec2_sentinel_cpu_history.json")

# Sensible defaults — ~6 hours of history at a 5-minute scan interval
DEFAULT_MAX_SAMPLES = 72
DEFAULT_MIN_SAMPLES = 6
DEFAULT_Z_SCORE = 2.0
DEFAULT_MIN_DELTA = 20.0       # points above mean
DEFAULT_MIN_CURRENT = 35.0     # ignore "spikes" that are still quiet overall


@dataclass
class OffendingProcess:
    pid: int
    name: str
    cmdline: str
    cpu_percent: float


@dataclass
class CpuAnomalyResult:
    enabled: bool = True
    is_anomaly: bool = False
    ready: bool = False                 # enough history to judge
    reason: str = ""
    current_percent: float = 0.0
    baseline_percent: float = 0.0       # mean of recent samples
    baseline_stddev: float = 0.0
    delta_percent: float = 0.0          # current - baseline
    z_score: float = 0.0
    sample_count: int = 0
    severity: str = "info"              # info | warning | critical
    offenders: list[OffendingProcess] = field(default_factory=list)
    detected_at: str = ""


def _load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text())
        samples = data.get("samples", [])
        if isinstance(samples, list):
            return samples
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return []


def _save_history(samples: list[dict]) -> None:
    try:
        HISTORY_FILE.write_text(json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "samples": samples,
        }))
    except OSError:
        pass


def _mean_std(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n < 2:
        return round(mean, 2), 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return round(mean, 2), round(math.sqrt(var), 2)


def _offenders_from_top(top_report, limit: int = 5) -> list[OffendingProcess]:
    if not top_report or not getattr(top_report, "by_cpu", None):
        return []
    out: list[OffendingProcess] = []
    for p in top_report.by_cpu[:limit]:
        if p.cpu_percent <= 0:
            continue
        out.append(OffendingProcess(
            pid=p.pid,
            name=p.name,
            cmdline=(p.cmdline or "")[:120],
            cpu_percent=p.cpu_percent,
        ))
    return out


def _cfg(anomaly_cfg: Optional[dict]) -> dict:
    root = anomaly_cfg or {}
    cpu = root.get("cpu") if isinstance(root.get("cpu"), dict) else root
    return {
        "enabled": cpu.get("enabled", True) is not False,
        "max_samples": int(cpu.get("max_samples", DEFAULT_MAX_SAMPLES)),
        "min_samples": int(cpu.get("min_samples", DEFAULT_MIN_SAMPLES)),
        "z_score": float(cpu.get("z_score", DEFAULT_Z_SCORE)),
        "min_delta_percent": float(cpu.get("min_delta_percent", DEFAULT_MIN_DELTA)),
        "min_current_percent": float(cpu.get("min_current_percent", DEFAULT_MIN_CURRENT)),
    }


def detect_cpu_anomaly(
    current_percent: float,
    top_report=None,
    anomaly_cfg: Optional[dict] = None,
) -> CpuAnomalyResult:
    """
    Record the current CPU sample and compare it to this host's recent baseline.

    Anomaly when current is both:
      - meaningfully above the rolling mean (delta and/or z-score), and
      - not still "quiet" in absolute terms (min_current_percent).

    Always appends the current sample so baselines improve over time.
    """
    cfg = _cfg(anomaly_cfg)
    now = datetime.now(timezone.utc).isoformat()
    now_ts = time.time()

    if not cfg["enabled"]:
        return CpuAnomalyResult(enabled=False, detected_at=now)

    history = _load_history()
    prior_values = [
        float(s["cpu_percent"])
        for s in history
        if isinstance(s, dict) and "cpu_percent" in s
    ]

    baseline, stddev = _mean_std(prior_values)
    sample_count = len(prior_values)
    delta = round(current_percent - baseline, 2) if sample_count else 0.0
    z = round(delta / stddev, 2) if stddev > 0.05 else (999.0 if delta > 0 else 0.0)

    # Persist current sample (after reading prior baseline)
    history.append({
        "ts": now_ts,
        "iso": now,
        "cpu_percent": round(float(current_percent), 2),
    })
    max_n = max(cfg["max_samples"], cfg["min_samples"])
    if len(history) > max_n:
        history = history[-max_n:]
    _save_history(history)

    result = CpuAnomalyResult(
        enabled=True,
        ready=sample_count >= cfg["min_samples"],
        current_percent=round(float(current_percent), 2),
        baseline_percent=baseline,
        baseline_stddev=stddev,
        delta_percent=delta,
        z_score=z if sample_count >= cfg["min_samples"] else 0.0,
        sample_count=sample_count,
        offenders=_offenders_from_top(top_report),
        detected_at=now,
    )

    if not result.ready:
        result.reason = (
            f"Building baseline — {sample_count}/{cfg['min_samples']} samples "
            "collected for this host."
        )
        return result

    # Detection rules (lightweight, interpretable)
    above_z = stddev > 0.05 and z >= cfg["z_score"]
    above_delta = delta >= cfg["min_delta_percent"]
    loud_enough = current_percent >= cfg["min_current_percent"]

    if loud_enough and (above_z or above_delta):
        result.is_anomaly = True
        # Severity: big absolute jump or very high z → critical
        if current_percent >= 90 or delta >= 40 or z >= 3.5:
            result.severity = "critical"
        else:
            result.severity = "warning"

        parts = [
            f"CPU {result.current_percent}% is unusual vs this host's recent "
            f"baseline of {result.baseline_percent}% "
            f"(Δ +{result.delta_percent} pts",
        ]
        if stddev > 0.05:
            parts.append(f", z={result.z_score}")
        parts.append(f", n={result.sample_count}).")
        if result.offenders:
            top = result.offenders[0]
            parts.append(
                f" Top offender: {top.name} pid {top.pid} at {top.cpu_percent}% CPU."
            )
        result.reason = "".join(parts)
    else:
        result.reason = (
            f"CPU {result.current_percent}% is within normal range for this host "
            f"(baseline {result.baseline_percent}% ± {result.baseline_stddev}, "
            f"n={result.sample_count})."
        )

    return result


def cpu_anomaly_to_dict(result: CpuAnomalyResult) -> dict:
    return {
        "enabled": result.enabled,
        "is_anomaly": result.is_anomaly,
        "ready": result.ready,
        "reason": result.reason,
        "current_percent": result.current_percent,
        "baseline_percent": result.baseline_percent,
        "baseline_stddev": result.baseline_stddev,
        "delta_percent": result.delta_percent,
        "z_score": result.z_score,
        "sample_count": result.sample_count,
        "severity": result.severity,
        "detected_at": result.detected_at,
        "offenders": [
            {
                "pid": o.pid,
                "name": o.name,
                "cmdline": o.cmdline,
                "cpu_percent": o.cpu_percent,
            }
            for o in result.offenders
        ],
    }
