import { motion } from "framer-motion";
import { Activity, RefreshCw, Shield } from "lucide-react";
import { cn } from "../lib/cn";
import { fmtTime, verdictStyles } from "../utils";
import type { HostInfo, Verdict } from "../types";
import { ThemeToggle } from "./ThemeToggle";

interface Props {
  host?: HostInfo;
  scannedAt?: string;
  verdict?: Verdict["status"];
  refreshing: boolean;
  lastUpdated?: Date;
  countdown: number;
  onRefresh: () => void;
  intervalSeconds: number;
}

export function HeaderBar({
  host,
  scannedAt,
  verdict = "ok",
  refreshing,
  lastUpdated,
  countdown,
  onRefresh,
  intervalSeconds,
}: Props) {
  const vStyle = verdictStyles[verdict];

  return (
    <motion.header
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="dash-header-bar flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
    >
      <div>
        <div className="mb-2 flex items-center gap-4">
          <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600 shadow-lg shadow-indigo-500/30 dark:from-violet-500 dark:to-fuchsia-500 dark:shadow-violet-500/40">
            <Shield className="h-5 w-5 text-white" />
            <span className="absolute -bottom-0.5 -right-0.5 flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-400 ring-2 ring-white dark:ring-[#070b14]" />
            </span>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.28em] text-indigo-500/80 dark:text-violet-300/50">
              Infrastructure health
            </p>
            <h1 className="font-display text-2xl font-extrabold tracking-tight sm:text-[2rem]">
              <span className="dash-gradient-text">EC2 Sentinel</span>
            </h1>
            <p className="mt-0.5 text-sm font-medium text-slate-600 dark:text-slate-400">
              Executive diagnostics · Where CPU & memory go · Why it&apos;s slow
            </p>
          </div>
        </div>
        {host && (
          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-2xl border border-indigo-100/70 bg-indigo-50/40 px-3 py-2 text-sm dash-muted dark:border-transparent dark:bg-transparent dark:px-0 dark:py-0">
            <Activity className="inline h-3.5 w-3.5 text-teal-600 dark:text-cyan-400" />
            <span className="font-mono font-semibold text-teal-800 dark:text-cyan-300/90">{host.hostname}</span>
            <span className="text-indigo-200 dark:text-slate-600">·</span>
            <span className="font-mono text-slate-700 dark:text-slate-300">{host.instance_id}</span>
            <span className="text-indigo-200 dark:text-slate-600">·</span>
            <span className="font-medium">
              {host.instance_type} · {host.region}
            </span>
            {scannedAt && (
              <>
                <span className="text-indigo-200 dark:text-slate-600">·</span>
                <span>scanned {fmtTime(scannedAt)}</span>
              </>
            )}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <ThemeToggle />

        <span
          className={cn(
            "rounded-full px-4 py-1.5 text-sm font-bold uppercase tracking-wider ring-1",
            vStyle.badge,
          )}
        >
          {vStyle.label}
        </span>

        <div className="dash-chip">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60 dark:bg-emerald-400" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500 dark:bg-emerald-400" />
          </span>
          Live · next in {countdown}s / {intervalSeconds}s
          {lastUpdated && (
            <span className="hidden text-slate-400 sm:inline dark:text-slate-600">
              · updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className={cn("dash-btn", "disabled:cursor-not-allowed disabled:opacity-50")}
        >
          <RefreshCw className={cn("h-4 w-4 text-indigo-600 dark:text-white", refreshing && "animate-spin")} />
          Refresh
        </button>
      </div>
    </motion.header>
  );
}
