import {
  fmtBytes,
  fmtTime,
  fmtUptime,
  dockerStateColor,
  levelForPercent,
  levelStyles,
  statusColor,
} from "../utils";
import type { Alert, HostPayload } from "../types";

interface Props {
  host: HostPayload;
  thresholds: Record<string, number>;
  isLive?: boolean;
}

function ProgressBar({
  pct,
  warn,
  crit,
}: {
  pct: number;
  warn: number;
  crit: number;
}) {
  const level = levelForPercent(pct, warn, crit);
  const styles = levelStyles[level];
  return (
    <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-white/5 ring-1 ring-white/10">
      <div
        className={`h-full rounded-full bg-gradient-to-r ${styles.bar} shadow-lg ${styles.glow} transition-all duration-700 ease-out`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  pct,
  warn,
  crit,
  accent,
}: {
  label: string;
  value: string;
  sub: string;
  pct?: number;
  warn?: number;
  crit?: number;
  accent: string;
}) {
  return (
    <div
      className={`group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04] p-5 backdrop-blur-xl transition hover:border-white/20 hover:bg-white/[0.06] ${accent}`}
    >
      <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-gradient-to-br from-white/10 to-transparent blur-2xl" />
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-200/60">
        {label}
      </p>
      <p className="mt-2 font-mono text-4xl font-bold tracking-tight text-white">
        {value}
      </p>
      {pct != null && warn != null && crit != null && (
        <ProgressBar pct={pct} warn={warn} crit={crit} />
      )}
      <p className="mt-3 text-sm text-slate-400">{sub}</p>
    </div>
  );
}

export function HostPanel({ host, thresholds, isLive }: Props) {
  const r = host.report;
  const h = r.host;
  const t = thresholds;
  const verdict = host.verdict?.status ?? "ok";

  const badgeClass =
    verdict === "critical"
      ? "bg-rose-500/20 text-rose-100 ring-rose-400/40"
      : verdict === "warning"
        ? "bg-amber-500/20 text-amber-100 ring-amber-400/40"
        : "bg-emerald-500/20 text-emerald-200 ring-emerald-400/40";

  const visibleDisks = r.disks.filter(
    (d) => d.mount === "/" || d.mount.startsWith("/boot") || d.used_percent > 0,
  );

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 border-b border-white/10 pb-4">
        <h2 className="bg-gradient-to-r from-cyan-300 via-violet-300 to-fuchsia-300 bg-clip-text text-xl font-bold text-transparent">
          {h.hostname || "unknown"}
        </h2>
        <span
          className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ring-1 ${badgeClass}`}
        >
          {verdict === "ok" ? "All clear" : verdict}
        </span>
        {isLive && (
          <span className="flex items-center gap-1.5 text-sm text-emerald-300">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            live
          </span>
        )}
        {!isLive && host.filename && (
          <span className="text-sm text-slate-500">{host.filename}</span>
        )}
        <span className="text-sm text-slate-500">
          {h.instance_id} · {h.instance_type} · {h.region}
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          label="CPU"
          value={`${r.cpu.usage_percent}%`}
          sub={`Load ${r.cpu.load_avg[0]?.toFixed(2) ?? "—"} · ${r.cpu.cores} cores · steal ${r.cpu.steal_percent}%`}
          pct={r.cpu.usage_percent}
          warn={t.cpu_warn ?? 80}
          crit={t.cpu_crit ?? 95}
          accent="hover:shadow-cyan-500/10"
        />
        <MetricCard
          label="Memory"
          value={`${r.memory.used_percent}%`}
          sub={`${fmtBytes(r.memory.used_bytes)} / ${fmtBytes(r.memory.total_bytes)} · OOM ${r.memory.oom_kills}`}
          pct={r.memory.used_percent}
          warn={t.memory_warn ?? 80}
          crit={t.memory_crit ?? 95}
          accent="hover:shadow-violet-500/10"
        />
        <MetricCard
          label="Uptime"
          value={fmtUptime(h.uptime_seconds)}
          sub={`Scanned ${fmtTime(r.timestamp)}`}
          accent="hover:shadow-fuchsia-500/10"
        />
      </div>

      {visibleDisks.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-xl">
          <div className="border-b border-white/10 px-5 py-3">
            <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-200/60">
              Disk
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-5 py-3 font-semibold">Mount</th>
                  <th className="px-5 py-3 font-semibold">Used</th>
                  <th className="px-5 py-3 font-semibold min-w-[180px]">Usage</th>
                  <th className="px-5 py-3 font-semibold">Free</th>
                </tr>
              </thead>
              <tbody>
                {visibleDisks.map((d) => {
                  const level = levelForPercent(
                    d.used_percent,
                    t.disk_warn ?? 75,
                    t.disk_crit ?? 90,
                  );
                  return (
                    <tr
                      key={d.mount}
                      className="border-t border-white/5 hover:bg-white/[0.02]"
                    >
                      <td className="px-5 py-3 font-mono text-cyan-200/90">
                        {d.mount}
                      </td>
                      <td
                        className={`px-5 py-3 font-mono font-semibold ${levelStyles[level].text}`}
                      >
                        {d.used_percent}%
                      </td>
                      <td className="px-5 py-3">
                        <ProgressBar
                          pct={d.used_percent}
                          warn={t.disk_warn ?? 75}
                          crit={t.disk_crit ?? 90}
                        />
                      </td>
                      <td className="px-5 py-3 text-slate-400">
                        {fmtBytes(d.total_bytes - d.used_bytes)}
                        {d.days_until_full != null && (
                          <span className="ml-2 text-amber-300/80">
                            ~{Math.round(d.days_until_full)}d left
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <DataTable
          title="Processes"
          headers={["Name", "Status", "PID", "CPU", "Mem"]}
          rows={(r.processes ?? []).map((p) => [
            p.name,
            p.status,
            String(p.pid ?? "—"),
            p.cpu_percent != null ? `${p.cpu_percent}%` : "—",
            p.memory_mb != null ? `${p.memory_mb} MB` : "—",
          ])}
          statusCol={1}
        />
        <DataTable
          title="Ports"
          headers={["Port", "Service", "Status", "Latency"]}
          rows={(r.ports ?? []).map((p) => [
            String(p.port),
            p.service,
            p.status,
            p.response_ms != null ? `${p.response_ms} ms` : "—",
          ])}
          statusCol={2}
        />
      </div>

      {r.docker?.available && (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/5 p-4 backdrop-blur-xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300/70">
                Docker
              </p>
              <p className="mt-2 font-mono text-lg font-bold text-cyan-200">
                v{r.docker.server_version}
              </p>
            </div>
            <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-4 backdrop-blur-xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300/70">
                Containers
              </p>
              <p className="mt-2 font-mono text-2xl font-bold text-white">
                {r.docker.running_count}
                <span className="ml-1 text-base font-normal text-slate-500">
                  / {r.docker.running_count + r.docker.stopped_count} running
                </span>
              </p>
              {r.docker.stopped_count > 0 && (
                <p className="mt-1 text-sm text-amber-300">
                  {r.docker.stopped_count} stopped
                </p>
              )}
            </div>
            <div className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-4 backdrop-blur-xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-300/70">
                Images
              </p>
              <p className="mt-2 font-mono text-2xl font-bold text-white">
                {r.docker.image_count}
              </p>
            </div>
            <div className="rounded-2xl border border-fuchsia-500/20 bg-fuchsia-500/5 p-4 backdrop-blur-xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-fuchsia-300/70">
                Reclaimable
              </p>
              <p className="mt-2 font-mono text-lg font-bold text-fuchsia-200">
                {r.docker.disk.images_reclaimable}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                images {r.docker.disk.images_size}
              </p>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <DataTable
              title="Containers"
              headers={["Name", "Image", "State", "Status"]}
              rows={(r.docker.containers ?? []).map((c) => [
                c.name,
                c.image.length > 28 ? c.image.slice(0, 28) + "…" : c.image,
                c.state,
                c.status.length > 40 ? c.status.slice(0, 40) + "…" : c.status,
              ])}
              rowClass={(rowIdx) => {
                const c = r.docker!.containers[rowIdx];
                return { stateCol: dockerStateColor(c.state, c.health) };
              }}
              statusCol={2}
            />
            <DataTable
              title="Images"
              headers={["Repository", "Tag", "Size", "Age"]}
              rows={(r.docker.images ?? []).map((img) => [
                img.repository,
                img.tag,
                img.size,
                img.created_since || "—",
              ])}
            />
          </div>
        </div>
      )}

      {r.log_matches?.length > 0 && (
        <DataTable
          title="Log patterns"
          headers={["Pattern", "Hits", "File"]}
          rows={r.log_matches.map((m) => [
            m.pattern,
            String(m.count),
            m.file,
          ])}
          statusCol={1}
          warnCol={1}
        />
      )}

      {host.alerts && host.alerts.length > 0 && (
        <AlertList alerts={host.alerts} />
      )}
    </section>
  );
}

function DataTable({
  title,
  headers,
  rows,
  statusCol,
  warnCol,
  rowClass,
}: {
  title: string;
  headers: string[];
  rows: string[][];
  statusCol?: number;
  warnCol?: number;
  rowClass?: (rowIdx: number) => { stateCol?: string };
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-xl">
      <div className="border-b border-white/10 px-5 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-200/60">
          {title}
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
              {headers.map((h) => (
                <th key={h} className="px-5 py-3 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={headers.length}
                  className="px-5 py-6 text-center text-slate-500"
                >
                  None configured
                </td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-t border-white/5 hover:bg-white/[0.02]"
                >
                  {row.map((cell, j) => {
                    const extra = rowClass?.(i);
                    const cls =
                      j === statusCol
                        ? (extra?.stateCol || statusColor(cell)) + " font-semibold"
                        : j === warnCol && cell !== "0"
                          ? "text-amber-300 font-semibold"
                          : j === 0
                            ? "font-medium text-slate-200"
                            : "text-slate-400";
                    return (
                      <td key={j} className={`px-5 py-3 ${cls}`}>
                        {cell}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AlertList({ alerts }: { alerts: Alert[] }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-xl">
      <h3 className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-violet-200/60">
        Active alerts
      </h3>
      <ul className="space-y-3">
        {alerts.map((a, i) => (
          <li
            key={i}
            className={`rounded-xl border-l-4 px-4 py-3 ${
              a.severity === "critical"
                ? "border-rose-500 bg-rose-500/10"
                : "border-amber-400 bg-amber-500/10"
            }`}
          >
            <p className="font-semibold text-white">{a.title}</p>
            <p className="mt-1 whitespace-pre-line text-sm text-slate-300">
              {a.message}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
