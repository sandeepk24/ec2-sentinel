import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Loader2, ServerCrash } from "lucide-react";
import { fetchHealth } from "./lib/api";
import { useHistoryStore } from "./store/history";
import { HeaderBar } from "./components/HeaderBar";
import { LiveCharts } from "./components/LiveCharts";
import { HostPanel } from "./components/HostPanel";

export default function App() {
  const pushHistory = useHistoryStore((s) => s.push);
  const [countdown, setCountdown] = useState(30);

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
      <div className="pointer-events-none fixed inset-0 bg-[#070b14]" />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(99,102,241,0.28)_0%,_transparent_50%)]" />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_bottom_right,_rgba(236,72,153,0.16)_0%,_transparent_45%)]" />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_rgba(34,211,238,0.12)_0%,_transparent_40%)]" />
      <div
        className="pointer-events-none fixed inset-0 opacity-[0.035]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />

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
              className="flex flex-col items-center justify-center py-32 text-slate-400"
            >
              <Loader2 className="mb-4 h-10 w-10 animate-spin text-violet-400" />
              <p className="text-lg">Collecting live health data…</p>
              <p className="mt-1 text-sm text-slate-500">
                Sampling CPU, memory, top consumers, and diagnosis
              </p>
            </motion.div>
          )}

          {query.isError && !query.data && (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-6 py-10 text-center backdrop-blur-xl"
            >
              <ServerCrash className="mx-auto mb-3 h-10 w-10 text-rose-300" />
              <p className="text-lg font-semibold text-rose-200">
                Failed to load health data
              </p>
              <p className="mt-2 text-sm text-rose-300/80">
                {(query.error as Error)?.message}
              </p>
              <p className="mt-4 text-sm text-slate-400">
                Run{" "}
                <code className="rounded bg-black/30 px-2 py-0.5 font-mono text-cyan-300">
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
                <div className="flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-100">
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
                  <h2 className="mb-6 text-sm font-semibold uppercase tracking-[0.25em] text-violet-300/50">
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

        <footer className="mt-16 border-t border-white/10 pt-6 text-center text-xs text-slate-500">
          Dynamic SPA · React + TanStack Query + Recharts · polls{" "}
          <code className="text-violet-300/70">/api/health</code> every{" "}
          {intervalSeconds}s
        </footer>
      </div>
    </div>
  );
}
