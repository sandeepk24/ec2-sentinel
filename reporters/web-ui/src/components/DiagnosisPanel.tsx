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
      <div className="flex h-3 overflow-hidden rounded-full ring-1 ring-white/10">
        {segments.map((seg) => (
          <div
            key={seg.label}
            title={`${seg.label}: ${seg.pct}%`}
            className={`${seg.color} transition-all`}
            style={{ width: `${(seg.pct / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-400">
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
      <div className="w-16 shrink-0 text-right font-mono text-sm font-bold text-cyan-300">
        {label}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate font-medium text-white">{p.name}</span>
          <span className="shrink-0 font-mono text-xs text-slate-500">pid {p.pid}</span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/5">
          <div
            className={`h-full rounded-full ${
              mode === "cpu"
                ? "bg-gradient-to-r from-cyan-400 to-violet-400"
                : "bg-gradient-to-r from-fuchsia-400 to-amber-400"
            }`}
            style={{ width: `${Math.min(value, 100)}%` }}
          />
        </div>
        <p className="mt-0.5 truncate font-mono text-xs text-slate-500">{p.cmdline}</p>
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
      ? "from-rose-600/40 to-rose-900/20 border-rose-500/40"
      : d.health === "degraded"
        ? "from-amber-600/30 to-amber-900/20 border-amber-500/40"
        : "from-emerald-600/30 to-emerald-900/20 border-emerald-500/40";

  const badge =
    d.health === "critical"
      ? "bg-rose-500/25 text-rose-100 ring-rose-400/50"
      : d.health === "degraded"
        ? "bg-amber-500/25 text-amber-100 ring-amber-400/50"
        : "bg-emerald-500/25 text-emerald-100 ring-emerald-400/50";

  const findings = d.findings.filter((f) => f.severity !== "ok");

  return (
    <div className="space-y-5">
      {/* Hero diagnosis */}
      <div
        className={`relative overflow-hidden rounded-3xl border bg-gradient-to-br p-6 backdrop-blur-xl ${healthStyle}`}
      >
        <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/5 blur-3xl" />
        <div className="relative">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <span className="text-xs font-bold uppercase tracking-[0.25em] text-white/50">
              Why is this slow?
            </span>
            <span
              className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ring-1 ${badge}`}
            >
              {d.health}
            </span>
          </div>
          <h3 className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
            {d.headline}
          </h3>
          <p className="mt-3 max-w-3xl text-lg leading-relaxed text-slate-200">
            {d.summary}
          </p>
        </div>
      </div>

      {/* Talk track */}
      {d.talk_track.length > 0 && (
        <div className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-5">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-violet-300/80">
            Say this on the call
          </h3>
          <ol className="space-y-3">
            {d.talk_track.map((line, i) => (
              <li key={i} className="flex gap-3 text-sm leading-relaxed text-slate-200">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-violet-500/30 font-mono text-xs font-bold text-violet-200">
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
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300/70">
            Where is the CPU going?
          </h3>
          <p className="mb-4 text-sm text-slate-400">{d.cpu_story}</p>
          <StackBar
            segments={[
              { label: "user", pct: cpu.user_percent ?? 0, color: "bg-cyan-400" },
              { label: "system", pct: cpu.system_percent ?? 0, color: "bg-violet-400" },
              { label: "iowait", pct: cpu.iowait_percent ?? 0, color: "bg-amber-400" },
              { label: "steal", pct: cpu.steal_percent ?? 0, color: "bg-rose-400" },
              { label: "idle", pct: cpu.idle_percent ?? 0, color: "bg-slate-600" },
            ]}
          />
          <div className="mt-4 border-t border-white/5 pt-3">
            {(top?.by_cpu ?? []).slice(0, 6).map((p) => (
              <ConsumerRow key={`cpu-${p.pid}`} p={p} mode="cpu" />
            ))}
            {!top?.by_cpu?.length && (
              <p className="text-sm text-slate-500">No significant CPU consumers sampled.</p>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-fuchsia-300/70">
            Where is the memory going?
          </h3>
          <p className="mb-4 text-sm text-slate-400">{d.memory_story}</p>
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
          <p className="mt-2 text-xs text-slate-500">
            Available (reclaimable): {fmtBytes(mem.available_bytes)} · Swap used:{" "}
            {mem.swap_used_percent}%
          </p>
          <div className="mt-4 border-t border-white/5 pt-3">
            {(top?.by_memory ?? []).slice(0, 6).map((p) => (
              <ConsumerRow key={`mem-${p.pid}`} p={p} mode="mem" />
            ))}
            {!top?.by_memory?.length && (
              <p className="text-sm text-slate-500">No memory consumers sampled.</p>
            )}
          </div>
        </div>
      </div>

      {/* Findings detail */}
      {findings.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-200/60">
            Findings & next steps
          </h3>
          {findings.map((f, i) => (
            <div
              key={i}
              className={`rounded-2xl border-l-4 px-5 py-4 ${
                f.severity === "critical"
                  ? "border-rose-500 bg-rose-500/10"
                  : f.severity === "warning"
                    ? "border-amber-400 bg-amber-500/10"
                    : "border-slate-500 bg-white/[0.03]"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  {f.category}
                </span>
                <span className="text-xs uppercase text-slate-500">{f.severity}</span>
              </div>
              <p className="mt-1 text-lg font-semibold text-white">{f.title}</p>
              <p className="mt-2 text-sm text-slate-300">{f.what}</p>
              <p className="mt-1 text-sm text-slate-400">{f.why_it_matters}</p>
              <p className="mt-3 rounded-lg bg-black/20 px-3 py-2 text-sm text-cyan-100">
                <span className="font-semibold text-cyan-300">Say: </span>
                {f.say_this}
              </p>
              <p className="mt-2 text-sm text-amber-200/90">
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
