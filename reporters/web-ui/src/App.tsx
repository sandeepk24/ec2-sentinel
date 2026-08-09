import { useCallback, useEffect, useState } from "react";
import { HostPanel } from "./components/HostPanel";
import type { HealthPayload } from "./types";
import { fmtTime, verdictStyles } from "./utils";

export default function App() {
  const [data, setData] = useState<HealthPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch("/api/health");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setData(await resp.json());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = (data?.refresh_seconds ?? 30) * 1000;
    const id = setInterval(refresh, interval);
    return () => clearInterval(id);
  }, [refresh, data?.refresh_seconds]);

  const live = data?.live;
  const host = live?.report.host;
  const verdict = live?.verdict?.status ?? "ok";
  const vStyle = verdictStyles[verdict];

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Background */}
      <div className="pointer-events-none fixed inset-0 bg-[#070b14]" />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(99,102,241,0.25)_0%,_transparent_50%)]" />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_bottom_right,_rgba(236,72,153,0.15)_0%,_transparent_45%)]" />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_bottom_left,_rgba(34,211,238,0.12)_0%,_transparent_40%)]" />
      <div
        className="pointer-events-none fixed inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />

      <div className="relative z-10 mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <header className="mb-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-lg shadow-violet-500/30">
                <span className="text-lg">🛡️</span>
              </div>
              <h1 className="font-display text-3xl font-extrabold tracking-tight">
                <span className="bg-gradient-to-r from-cyan-300 via-violet-300 to-fuchsia-300 bg-clip-text text-transparent">
                  EC2 Sentinel
                </span>
                <span className="ml-2 text-lg font-medium text-slate-400">
                  Health Dashboard
                </span>
              </h1>
            </div>
            {host && (
              <p className="text-sm text-slate-400">
                <span className="font-mono text-cyan-300/90">{host.hostname}</span>
                {" · "}
                <span className="font-mono">{host.instance_id}</span>
                {" · "}
                scanned {fmtTime(live?.report.timestamp)}
              </p>
            )}
          </div>
          {live && (
            <span
              className={`self-start rounded-full px-4 py-1.5 text-sm font-bold uppercase tracking-wider ring-1 ${vStyle.badge}`}
            >
              {vStyle.label}
            </span>
          )}
        </header>

        {/* Content */}
        {loading && !data && (
          <div className="flex flex-col items-center justify-center py-32 text-slate-400">
            <div className="mb-4 h-10 w-10 animate-spin rounded-full border-2 border-violet-500/30 border-t-violet-400" />
            <p>Collecting health data…</p>
          </div>
        )}

        {error && (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-6 py-8 text-center backdrop-blur-xl">
            <p className="text-lg font-semibold text-rose-200">
              Failed to load health data
            </p>
            <p className="mt-2 text-sm text-rose-300/80">{error}</p>
            <p className="mt-4 text-sm text-slate-400">
              Run{" "}
              <code className="rounded bg-black/30 px-2 py-0.5 font-mono text-cyan-300">
                python sentinel.py --web
              </code>{" "}
              on this host.
            </p>
          </div>
        )}

        {data && !error && (
          <div className="space-y-12">
            {data.live && (
              <HostPanel
                host={data.live}
                thresholds={data.thresholds}
                isLive
              />
            )}

            {data.fleet.length > 0 && (
              <div>
                <h2 className="mb-6 text-sm font-semibold uppercase tracking-[0.25em] text-violet-300/50">
                  Fleet reports ({data.fleet.length})
                </h2>
                <div className="space-y-12">
                  {data.fleet.map((f, i) => (
                    <HostPanel
                      key={f.filename ?? i}
                      host={f}
                      thresholds={data.thresholds}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <footer className="mt-16 border-t border-white/10 pt-6 text-center text-xs text-slate-500">
          Auto-refreshes every {data?.refresh_seconds ?? 30}s · Local only ·{" "}
          <code className="text-violet-300/70">/api/health</code>
        </footer>
      </div>
    </div>
  );
}
