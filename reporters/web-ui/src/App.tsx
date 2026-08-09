import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Loader2, ServerCrash } from "lucide-react";
import { fetchHealth } from "./lib/api";
import { useHistoryStore } from "./store/history";
import { applyTheme, useThemeStore } from "./store/theme";
import { HeaderBar } from "./components/HeaderBar";
import { LiveCharts } from "./components/LiveCharts";
import { HostPanel } from "./components/HostPanel";

export default function App() {
  const pushHistory = useHistoryStore((s) => s.push);
  const theme = useThemeStore((s) => s.theme);
  const [countdown, setCountdown] = useState(30);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const query = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: (q) => (q.state.data?.refresh_seconds ?? 30) * 1000,
    refetchIntervalInBackground: true,
    retry: 2,
    staleTime: 5_000,
  });

  const intervalSeconds = query.data?.refresh_seconds ?? 30;

  // Push samples into client-side history for live charts
  useEffect(() => {
    const report = query.data?.live?.report;
    if (!report) return;
    pushHistory({
      cpu: report.cpu.usage_percent,
      memory: report.memory.used_percent,
      load: report.cpu.load_avg[0] ?? 0,
      iowait: report.cpu.iowait_percent ?? 0,
      steal: report.cpu.steal_percent ?? 0,
    });
  }, [query.dataUpdatedAt, query.data?.live?.report, pushHistory]);

  // Countdown to next poll
  useEffect(() => {
    setCountdown(intervalSeconds);
    const id = setInterval(() => {
      setCountdown((c) => (c <= 1 ? intervalSeconds : c - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [intervalSeconds, query.dataUpdatedAt]);

  const live = query.data?.live;
  const host = live?.report.host;
  const verdict = live?.verdict?.status ?? "ok";
  const lastUpdated = useMemo(
    () => (query.dataUpdatedAt ? new Date(query.dataUpdatedAt) : undefined),
    [query.dataUpdatedAt],
  );

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      {/* Light backdrop — fully hidden in dark mode */}
      <div className="pointer-events-none fixed inset-0 dark:hidden">
        <div className="absolute inset-0 bg-[linear-gradient(165deg,#f8faff_0%,#f3f0ff_38%,#eef8ff_100%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_15%_-5%,rgba(99,102,241,0.22)_0%,transparent_52%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_85%_0%,rgba(14,165,233,0.16)_0%,transparent_45%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_100%,rgba(168,85,247,0.14)_0%,transparent_50%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_100%_80%,rgba(244,114,182,0.1)_0%,transparent_40%)]" />
        <div
          className="absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(79,70,229,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(79,70,229,0.06) 1px, transparent 1px)",
            backgroundSize: "56px 56px",
          }}
        />
      </div>

      {/* Dark backdrop — restored deep-space look */}
      <div className="pointer-events-none fixed inset-0 hidden dark:block">
        <div className="absolute inset-0 bg-[#070b14]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(99,102,241,0.28)_0%,_transparent_50%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_right,_rgba(236,72,153,0.16)_0%,_transparent_45%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_rgba(34,211,238,0.12)_0%,_transparent_40%)]" />
        <div
          className="absolute inset-0 opacity-[0.035]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
            backgroundSize: "48px 48px",
          }}
        />
      </div>

      <div className="relative z-10 mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <HeaderBar
          host={host}
          scannedAt={live?.report.timestamp}
          verdict={verdict}
          refreshing={query.isFetching}
          lastUpdated={lastUpdated}
          countdown={countdown}
          intervalSeconds={intervalSeconds}
          onRefresh={() => query.refetch()}
        />

        <AnimatePresence mode="wait">
          {query.isLoading && !query.data && (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center py-32 dash-muted"
            >
              <Loader2 className="mb-4 h-10 w-10 animate-spin text-indigo-500 dark:text-violet-400" />
              <p className="font-display text-lg font-semibold text-slate-800 dark:text-slate-300">
                Collecting live health data…
              </p>
              <p className="mt-1 text-sm dash-subtle">
                Sampling CPU, memory, top consumers, and diagnosis
              </p>
            </motion.div>
          )}

          {query.isError && !query.data && (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-rose-200 bg-gradient-to-br from-rose-50 to-white px-6 py-10 text-center shadow-[0_8px_40px_rgba(244,63,94,0.1)] backdrop-blur-xl dark:border-rose-500/30 dark:from-rose-950/40 dark:to-[#0a1020] dark:shadow-none"
            >
              <ServerCrash className="mx-auto mb-3 h-10 w-10 text-rose-500 dark:text-rose-300" />
              <p className="text-lg font-semibold text-rose-700 dark:text-rose-200">
                Failed to load health data
              </p>
              <p className="mt-2 text-sm text-rose-600 dark:text-rose-300/80">
                {(query.error as Error)?.message}
              </p>
              <p className="mt-4 text-sm dash-muted">
                Run{" "}
                <code className="rounded-md bg-indigo-50 px-2 py-0.5 font-mono text-indigo-700 ring-1 ring-indigo-100 dark:bg-black/30 dark:text-cyan-300 dark:ring-0">
                  python sentinel.py --web
                </code>{" "}
                on this host.
              </p>
            </motion.div>
          )}

          {query.data && (
            <motion.div
              key="data"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="space-y-8"
            >
              {query.isError && (
                <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-gradient-to-r from-amber-50 to-orange-50/80 px-4 py-2 text-sm text-amber-950 shadow-sm dark:border-amber-500/30 dark:from-amber-950/40 dark:to-[#0a1020] dark:text-amber-100 dark:shadow-none">
                  <AlertTriangle className="h-4 w-4" />
                  Last refresh failed — showing cached data
                </div>
              )}

              <LiveCharts />

              {query.data.live && (
                <HostPanel
                  host={query.data.live}
                  thresholds={query.data.thresholds}
                  isLive
                />
              )}

              {query.data.fleet.length > 0 && (
                <div>
                  <h2 className="mb-6 font-display text-sm font-bold uppercase tracking-[0.25em] text-indigo-600/70 dark:text-violet-300/50">
                    Fleet reports ({query.data.fleet.length})
                  </h2>
                  <div className="space-y-12">
                    {query.data.fleet.map((f, i) => (
                      <HostPanel
                        key={f.filename ?? i}
                        host={f}
                        thresholds={query.data.thresholds}
                      />
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        <footer className="mt-16 border-t border-indigo-100/80 pt-6 text-center text-xs dash-subtle dark:border-white/10">
          Dynamic SPA · React + TanStack Query + Recharts · polls{" "}
          <code className="rounded bg-indigo-50 px-1.5 py-0.5 font-mono text-indigo-700 dark:bg-transparent dark:text-violet-300/70">/api/health</code> every{" "}
          {intervalSeconds}s
        </footer>
      </div>
    </div>
  );
}
