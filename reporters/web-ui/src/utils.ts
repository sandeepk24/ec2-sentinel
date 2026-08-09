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
    bar: "from-emerald-500 via-teal-500 to-cyan-500",
    text: "text-emerald-700 dark:text-emerald-300",
    glow: "shadow-emerald-500/30 dark:shadow-emerald-500/40",
    ring: "ring-emerald-200 dark:ring-emerald-400/30",
  },
  warn: {
    bar: "from-amber-500 via-orange-500 to-yellow-500",
    text: "text-amber-700 dark:text-amber-300",
    glow: "shadow-amber-500/30 dark:shadow-amber-500/40",
    ring: "ring-amber-200 dark:ring-amber-400/30",
  },
  crit: {
    bar: "from-rose-600 via-red-600 to-orange-500",
    text: "text-rose-700 dark:text-rose-300",
    glow: "shadow-rose-500/35 dark:shadow-rose-500/50",
    ring: "ring-rose-200 dark:ring-rose-400/40",
  },
};

type VerdictStatus = "ok" | "warning" | "critical";

export const verdictStyles: Record<
  VerdictStatus,
  { badge: string; label: string }
> = {
  ok: {
    badge:
      "bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-200 dark:ring-emerald-400/40",
    label: "All clear",
  },
  warning: {
    badge:
      "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-500/20 dark:text-amber-100 dark:ring-amber-400/40",
    label: "Warning",
  },
  critical: {
    badge:
      "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-500/25 dark:text-rose-100 dark:ring-rose-400/50",
    label: "Critical",
  },
};

export function statusColor(status: string): string {
  if (status === "NOT_FOUND" || status === "CLOSED" || status === "exited" || status === "dead")
    return "text-rose-600 dark:text-rose-300";
  if (status === "RESTARTED" || status === "SLOW" || status === "restarting")
    return "text-amber-700 dark:text-amber-300";
  if (status === "running" || status === "RUNNING" || status === "OPEN")
    return "text-emerald-700 dark:text-emerald-300";
  return "text-slate-500 dark:text-slate-400";
}

export function dockerStateColor(state: string, health?: string | null): string {
  if (health === "unhealthy" || state === "dead") return "text-rose-600 dark:text-rose-300";
  if (state === "restarting" || state === "paused") return "text-amber-700 dark:text-amber-300";
  if (state === "running") return "text-emerald-700 dark:text-emerald-300";
  return "text-slate-500 dark:text-slate-400";
}
