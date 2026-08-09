import { motion } from "framer-motion";
import { MessageCircle, Cpu, MemoryStick } from "lucide-react";
import type { Diagnosis, Report, TopProcess } from "../types";
import { fmtBytes } from "../utils";

function StackBar({
  segments,
}: {
  segments: Array<{ label: string; pct: number; color: string }>;
}) {
  const total = segments.reduce((s, x) => s + x.pct, 0) || 1;
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full ring-1 ring-indigo-100 dark:ring-white/10">
        {segments.map((seg) => (
          <div
            key={seg.label}
            title={`${seg.label}: ${seg.pct}%`}
            className={`${seg.color} transition-all`}
            style={{ width: `${(seg.pct / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs dash-muted">
        {segments.map((seg) => (
          <span key={seg.label} className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-2 rounded-full ${seg.color}`} />
            {seg.label} {seg.pct}%
          </span>
        ))}
      </div>
    </div>
  );
}

function ConsumerRow({
  p,
  mode,
}: {
  p: TopProcess;
  mode: "cpu" | "mem";
}) {
  const value = mode === "cpu" ? p.cpu_percent : p.memory_percent;
  const label =
    mode === "cpu" ? `${p.cpu_percent}%` : `${p.memory_mb} MB (${p.memory_percent}%)`;
  return (
    <div className="group flex items-center gap-3 py-2">
      <div className="w-16 shrink-0 text-right font-mono text-sm font-bold text-teal-700 dark:text-cyan-300">
        {label}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate font-medium dash-title">{p.name}</span>
          <span className="shrink-0 font-mono text-xs dash-subtle">pid {p.pid}</span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-indigo-100 dark:bg-white/5">
          <div
            className={`h-full rounded-full ${
              mode === "cpu"
                ? "bg-gradient-to-r from-teal-500 to-indigo-500"
                : "bg-gradient-to-r from-violet-500 to-fuchsia-500"
            }`}
            style={{ width: `${Math.min(value, 100)}%` }}
          />
        </div>
        <p className="mt-0.5 truncate font-mono text-xs dash-subtle">{p.cmdline}</p>
      </div>
    </div>
  );
}

export function DiagnosisPanel({ report }: { report: Report }) {
  const d: Diagnosis | undefined = report.diagnosis;
  const cpu = report.cpu;
  const mem = report.memory;
  const top = report.top;

  if (!d) return null;

  const healthStyle =
    d.health === "critical"
      ? "dash-hero-crit dark:from-rose-600/40 dark:to-rose-900/20"
      : d.health === "degraded"
        ? "dash-hero-warn dark:from-amber-600/30 dark:to-amber-900/20"
        : "dash-hero-ok dark:from-emerald-600/30 dark:to-emerald-900/20";

  const badge =
    d.health === "critical"
      ? "bg-rose-100 text-rose-800 ring-rose-200 dark:bg-rose-500/25 dark:text-rose-100 dark:ring-rose-400/50"
      : d.health === "degraded"
        ? "bg-amber-100 text-amber-900 ring-amber-200 dark:bg-amber-500/25 dark:text-amber-100 dark:ring-amber-400/50"
        : "bg-emerald-100 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/25 dark:text-emerald-100 dark:ring-emerald-400/50";

  const findings = d.findings.filter((f) => f.severity !== "ok");

  return (
    <div className="space-y-5">
      {/* Hero diagnosis */}
      <motion.div
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        className={`relative overflow-hidden rounded-3xl border bg-gradient-to-br p-6 backdrop-blur-xl ${healthStyle}`}
      >
        <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-indigo-200/30 blur-3xl dark:bg-white/5" />
        <div className="relative">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.25em] text-indigo-600/70 dark:text-white/50">
              Executive summary
            </span>
            <span
              className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ring-1 ${badge}`}
            >
              {d.health}
            </span>
          </div>
          <h3 className="font-display text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl dark:text-white">
            {d.headline}
          </h3>
          <p className="mt-3 max-w-3xl text-lg font-medium leading-relaxed text-slate-700 dark:text-slate-200">
            {d.summary}
          </p>
        </div>
      </motion.div>

      {/* Talk track */}
      {d.talk_track.length > 0 && (
        <div className="dash-callout">
          <h3 className="mb-3 flex items-center gap-2 dash-heading text-violet-700 dark:text-violet-300/80">
            <MessageCircle className="h-3.5 w-3.5" />
            Say this on the call
          </h3>
          <ol className="space-y-3">
            {d.talk_track.map((line, i) => (
              <li key={i} className="flex gap-3 text-sm font-medium leading-relaxed text-slate-700 dark:text-slate-200">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 font-mono text-xs font-bold text-indigo-700 dark:bg-violet-500/30 dark:text-violet-200">
                  {i + 1}
                </span>
                <span>{line}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Where CPU / Memory goes */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="dash-panel p-5">
          <h3 className="mb-1 flex items-center gap-2 dash-heading text-cyan-700 dark:text-cyan-300/70">
            <Cpu className="h-3.5 w-3.5" />
            Where is the CPU going?
          </h3>
          <p className="mb-4 text-sm dash-muted">{d.cpu_story}</p>
          <StackBar
            segments={[
              { label: "user", pct: cpu.user_percent ?? 0, color: "bg-cyan-400" },
              { label: "system", pct: cpu.system_percent ?? 0, color: "bg-violet-400" },
              { label: "iowait", pct: cpu.iowait_percent ?? 0, color: "bg-amber-400" },
              { label: "steal", pct: cpu.steal_percent ?? 0, color: "bg-rose-400" },
              { label: "idle", pct: cpu.idle_percent ?? 0, color: "bg-slate-600" },
            ]}
          />
          <div className="mt-4 border-t border-slate-200 pt-3 dark:border-white/5">
            {(top?.by_cpu ?? []).slice(0, 6).map((p) => (
              <ConsumerRow key={`cpu-${p.pid}`} p={p} mode="cpu" />
            ))}
            {!top?.by_cpu?.length && (
              <p className="text-sm dash-subtle">No significant CPU consumers sampled.</p>
            )}
          </div>
        </div>

        <div className="dash-panel p-5">
          <h3 className="mb-1 flex items-center gap-2 dash-heading text-fuchsia-700 dark:text-fuchsia-300/70">
            <MemoryStick className="h-3.5 w-3.5" />
            Where is the memory going?
          </h3>
          <p className="mb-4 text-sm dash-muted">{d.memory_story}</p>
          <StackBar
            segments={[
              {
                label: "apps",
                pct: mem.total_bytes
                  ? Math.round(((mem.app_bytes ?? 0) / mem.total_bytes) * 100)
                  : 0,
                color: "bg-fuchsia-400",
              },
              {
                label: "cache",
                pct: mem.total_bytes
                  ? Math.round(((mem.cached_bytes ?? 0) / mem.total_bytes) * 100)
                  : 0,
                color: "bg-sky-400",
              },
              {
                label: "buffers",
                pct: mem.total_bytes
                  ? Math.round(((mem.buffers_bytes ?? 0) / mem.total_bytes) * 100)
                  : 0,
                color: "bg-teal-400",
              },
              {
                label: "free",
                pct: mem.total_bytes
                  ? Math.round(((mem.free_bytes ?? 0) / mem.total_bytes) * 100)
                  : 0,
                color: "bg-slate-600",
              },
            ]}
          />
          <p className="mt-2 text-xs dash-subtle">
            Available (reclaimable): {fmtBytes(mem.available_bytes)} · Swap used:{" "}
            {mem.swap_used_percent}%
          </p>
          <div className="mt-4 border-t border-slate-200 pt-3 dark:border-white/5">
            {(top?.by_memory ?? []).slice(0, 6).map((p) => (
              <ConsumerRow key={`mem-${p.pid}`} p={p} mode="mem" />
            ))}
            {!top?.by_memory?.length && (
              <p className="text-sm dash-subtle">No memory consumers sampled.</p>
            )}
          </div>
        </div>
      </div>

      {/* Findings detail */}
      {findings.length > 0 && (
        <div className="space-y-3">
          <h3 className="dash-heading">
            Findings & next steps
          </h3>
          {findings.map((f, i) => (
            <div
              key={i}
              className={`rounded-2xl border-l-4 px-5 py-4 ${
                f.severity === "critical"
                  ? "border-rose-500 bg-gradient-to-r from-rose-50 to-white dark:from-rose-500/10 dark:to-transparent"
                  : f.severity === "warning"
                    ? "border-amber-500 bg-gradient-to-r from-amber-50 to-white dark:from-amber-500/10 dark:to-transparent"
                    : "border-slate-300 bg-slate-50 dark:border-slate-500 dark:bg-white/[0.03]"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider dash-muted">
                  {f.category}
                </span>
                <span className="text-xs uppercase dash-subtle">{f.severity}</span>
              </div>
              <p className="mt-1 text-lg font-semibold dash-title">{f.title}</p>
              <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">{f.what}</p>
              <p className="mt-1 text-sm dash-muted">{f.why_it_matters}</p>
              <p className="mt-3 rounded-lg bg-indigo-50 px-3 py-2 text-sm text-indigo-950 ring-1 ring-indigo-100 dark:bg-black/20 dark:text-cyan-100 dark:ring-0">
                <span className="font-semibold text-indigo-700 dark:text-cyan-300">Say: </span>
                {f.say_this}
              </p>
              <p className="mt-2 text-sm text-amber-800 dark:text-amber-200/90">
                <span className="font-semibold">Next: </span>
                {f.next_step}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
