export function fmtBytes(b: number | undefined): string {
  if (!b) return "—";
  const gb = b / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(b / 1024 ** 2)} MB`;
}

export function fmtUptime(sec: number | undefined): string {
  if (!sec) return "—";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

export function fmtTime(iso: string | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "medium",
    });
  } catch {
    return iso;
  }
}

export type Level = "ok" | "warn" | "crit";

export function levelForPercent(
  pct: number,
  warn: number,
  crit: number,
): Level {
  if (pct >= crit) return "crit";
  if (pct >= warn) return "warn";
  return "ok";
}

export const levelStyles: Record<
  Level,
  { bar: string; text: string; glow: string; ring: string }
> = {
  ok: {
    bar: "from-emerald-400 via-teal-400 to-cyan-400",
    text: "text-emerald-300",
    glow: "shadow-emerald-500/40",
    ring: "ring-emerald-400/30",
  },
  warn: {
    bar: "from-amber-400 via-orange-400 to-yellow-400",
    text: "text-amber-300",
    glow: "shadow-amber-500/40",
    ring: "ring-amber-400/30",
  },
  crit: {
    bar: "from-rose-500 via-red-500 to-orange-500",
    text: "text-rose-300",
    glow: "shadow-rose-500/50",
    ring: "ring-rose-400/40",
  },
};

type VerdictStatus = "ok" | "warning" | "critical";

export const verdictStyles: Record<
  VerdictStatus,
  { badge: string; label: string }
> = {
  ok: {
    badge: "bg-emerald-500/20 text-emerald-200 ring-emerald-400/40",
    label: "All clear",
  },
  warning: {
    badge: "bg-amber-500/20 text-amber-100 ring-amber-400/40",
    label: "Warning",
  },
  critical: {
    badge: "bg-rose-500/25 text-rose-100 ring-rose-400/50",
    label: "Critical",
  },
};

export function statusColor(status: string): string {
  if (status === "NOT_FOUND" || status === "CLOSED" || status === "exited" || status === "dead")
    return "text-rose-300";
  if (status === "RESTARTED" || status === "SLOW" || status === "restarting")
    return "text-amber-300";
  if (status === "running" || status === "RUNNING" || status === "OPEN")
    return "text-emerald-300";
  return "text-slate-400";
}

export function dockerStateColor(state: string, health?: string | null): string {
  if (health === "unhealthy" || state === "dead") return "text-rose-300";
  if (state === "restarting" || state === "paused") return "text-amber-300";
  if (state === "running") return "text-emerald-300";
  return "text-slate-400";
}
