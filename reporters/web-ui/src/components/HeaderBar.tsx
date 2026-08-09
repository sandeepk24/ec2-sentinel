import { motion } from "framer-motion";
import { Activity, RefreshCw, Shield } from "lucide-react";
import { cn } from "../lib/cn";
import { fmtTime, verdictStyles } from "../utils";
import type { HostInfo, Verdict } from "../types";

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
      className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"
    >
      <div>
        <div className="mb-2 flex items-center gap-3">
          <div className="relative flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-lg shadow-violet-500/40">
            <Shield className="h-5 w-5 text-white" />
            <span className="absolute -bottom-0.5 -right-0.5 flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-400 ring-2 ring-[#070b14]" />
            </span>
          </div>
          <div>
            <h1 className="font-display text-2xl font-extrabold tracking-tight sm:text-3xl">
              <span className="bg-gradient-to-r from-cyan-300 via-violet-300 to-fuchsia-300 bg-clip-text text-transparent">
                EC2 Sentinel
              </span>
            </h1>
            <p className="text-sm text-slate-400">
              Live diagnostics · Why is this slow?
            </p>
          </div>
        </div>
        {host && (
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-400">
            <Activity className="inline h-3.5 w-3.5 text-cyan-400" />
            <span className="font-mono text-cyan-300/90">{host.hostname}</span>
            <span className="text-slate-600">·</span>
            <span className="font-mono">{host.instance_id}</span>
            <span className="text-slate-600">·</span>
            <span>
              {host.instance_type} · {host.region}
            </span>
            {scannedAt && (
              <>
                <span className="text-slate-600">·</span>
                <span>scanned {fmtTime(scannedAt)}</span>
              </>
            )}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "rounded-full px-4 py-1.5 text-sm font-bold uppercase tracking-wider ring-1",
            vStyle.badge,
          )}
        >
          {vStyle.label}
        </span>

        <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-400">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          Live · next in {countdown}s / {intervalSeconds}s
          {lastUpdated && (
            <span className="hidden text-slate-600 sm:inline">
              · updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className={cn(
            "inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2",
            "text-sm font-medium text-white transition hover:bg-white/10",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          Refresh
        </button>
      </div>
    </motion.header>
  );
}
