"""
Disk growth prediction from a local rolling sample history.

Estimates GB/day growth, days until 80/90/95% utilization, trend direction,
and a predicted exhaustion date — without any cloud APIs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


HISTORY_FILE = Path("/tmp/ec2_sentinel_disk_history.json")
DEFAULT_MAX_SAMPLES = 72
DEFAULT_MIN_SAMPLES = 2
DEFAULT_MIN_ELAPSED_SECONDS = 300  # need ≥5 minutes of history


@dataclass
class DiskGrowthPrediction:
    growth_rate_bytes_per_day: Optional[float] = None
    growth_gb_per_day: Optional[float] = None
    trend: str = "unknown"  # growing | stable | shrinking | unknown
    days_until_80: Optional[float] = None
    days_until_90: Optional[float] = None
    days_until_95: Optional[float] = None
    days_until_full: Optional[float] = None
    predicted_full_date: Optional[str] = None  # YYYY-MM-DD UTC
    sample_count: int = 0
    ready: bool = False


def _load_raw() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _save_raw(data: dict) -> None:
    try:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "mounts": data,
        }
        HISTORY_FILE.write_text(json.dumps(payload))
    except OSError:
        pass


def _mount_samples(raw: dict) -> dict:
    """
    Normalize on-disk formats to {mount: [ {ts, used_bytes, total_bytes}, ... ]}.

    Supports:
      - new: {"mounts": {mount: [samples...]}} or {"mounts": {mount: {"samples": [...]}}}
      - legacy flat: {mount: [used, ts]} or {mount: {"samples": [...]}}
    """
    if "mounts" in raw and isinstance(raw["mounts"], dict):
        source = raw["mounts"]
    else:
        source = {k: v for k, v in raw.items() if k != "updated_at"}

    out: dict[str, list[dict]] = {}
    for mount, entry in source.items():
        samples: list[dict] = []
        if isinstance(entry, dict) and "samples" in entry:
            entry = entry["samples"]
        if isinstance(entry, list) and len(entry) == 2 and not isinstance(entry[0], dict):
            # legacy single sample: [used_bytes, timestamp]
            try:
                samples = [{"ts": float(entry[1]), "used_bytes": int(entry[0]), "total_bytes": 0}]
            except (TypeError, ValueError, IndexError):
                samples = []
        elif isinstance(entry, list):
            for s in entry:
                if not isinstance(s, dict):
                    continue
                try:
                    samples.append({
                        "ts": float(s["ts"]),
                        "used_bytes": int(s["used_bytes"]),
                        "total_bytes": int(s.get("total_bytes") or 0),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
        out[mount] = samples
    return out


def load_disk_history() -> dict[str, list[dict]]:
    return _mount_samples(_load_raw())


def save_disk_history(mounts: dict[str, list[dict]], max_samples: int = DEFAULT_MAX_SAMPLES) -> None:
    trimmed = {}
    for mount, samples in mounts.items():
        samples = sorted(samples, key=lambda s: s["ts"])
        if len(samples) > max_samples:
            samples = samples[-max_samples:]
        trimmed[mount] = samples
    _save_raw(trimmed)


def _growth_bytes_per_day(samples: list[dict]) -> Optional[float]:
    """Linear slope of used_bytes vs time → bytes/day (can be negative)."""
    if len(samples) < DEFAULT_MIN_SAMPLES:
        return None
    ordered = sorted(samples, key=lambda s: s["ts"])
    t0 = ordered[0]["ts"]
    elapsed = ordered[-1]["ts"] - t0
    if elapsed < DEFAULT_MIN_ELAPSED_SECONDS:
        return None

    # Simple linear regression: used = a + b * (t - t0)
    xs = [s["ts"] - t0 for s in ordered]
    ys = [float(s["used_bytes"]) for s in ordered]
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-9:
        return None
    slope_per_sec = (n * sum_xy - sum_x * sum_y) / denom
    return slope_per_sec * 86400.0


def _days_until_bytes(used: int, target_bytes: float, growth_bpd: float) -> Optional[float]:
    if growth_bpd is None or growth_bpd <= 0:
        return None
    if used >= target_bytes:
        return 0.0
    return round((target_bytes - used) / growth_bpd, 1)


def _days_until_percent(
    used: int, total: int, growth_bpd: Optional[float], pct: float,
) -> Optional[float]:
    if not total or growth_bpd is None:
        return None
    return _days_until_bytes(used, total * (pct / 100.0), growth_bpd)


def _trend_label(growth_gb_per_day: Optional[float]) -> str:
    if growth_gb_per_day is None:
        return "unknown"
    # ~50 MB/day band counts as stable noise
    if growth_gb_per_day > 0.05:
        return "growing"
    if growth_gb_per_day < -0.05:
        return "shrinking"
    return "stable"


def _full_date(days: Optional[float]) -> Optional[str]:
    if days is None:
        return None
    when = datetime.now(timezone.utc) + timedelta(days=max(days, 0))
    return when.date().isoformat()


def predict_disk_growth(
    used_bytes: int,
    total_bytes: int,
    samples: list[dict],
) -> DiskGrowthPrediction:
    """Compute growth metrics for one mount from its sample history."""
    growth_bpd = _growth_bytes_per_day(samples)
    growth_gb = round(growth_bpd / (1024 ** 3), 3) if growth_bpd is not None else None
    trend = _trend_label(growth_gb)

    days_80 = _days_until_percent(used_bytes, total_bytes, growth_bpd, 80)
    days_90 = _days_until_percent(used_bytes, total_bytes, growth_bpd, 90)
    days_95 = _days_until_percent(used_bytes, total_bytes, growth_bpd, 95)
    days_full = _days_until_percent(used_bytes, total_bytes, growth_bpd, 100)

    ready = growth_bpd is not None
    return DiskGrowthPrediction(
        growth_rate_bytes_per_day=round(growth_bpd, 1) if growth_bpd is not None else None,
        growth_gb_per_day=growth_gb,
        trend=trend,
        days_until_80=days_80,
        days_until_90=days_90,
        days_until_95=days_95,
        days_until_full=days_full,
        predicted_full_date=_full_date(days_full) if growth_bpd and growth_bpd > 0 else None,
        sample_count=len(samples),
        ready=ready,
    )


def record_disk_sample(
    history: dict[str, list[dict]],
    mount: str,
    used_bytes: int,
    total_bytes: int,
    now: Optional[float] = None,
    max_samples: int = DEFAULT_MAX_SAMPLES,
) -> list[dict]:
    """Append a sample for mount and return the updated sample list."""
    now = now if now is not None else time.time()
    samples = list(history.get(mount, []))
    samples.append({
        "ts": now,
        "used_bytes": int(used_bytes),
        "total_bytes": int(total_bytes),
    })
    samples = sorted(samples, key=lambda s: s["ts"])
    if len(samples) > max_samples:
        samples = samples[-max_samples:]
    history[mount] = samples
    return samples
