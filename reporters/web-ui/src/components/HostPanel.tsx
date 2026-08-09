import { motion } from "framer-motion";
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
import { DiagnosisPanel } from "./DiagnosisPanel";
import { GaugeCard } from "./GaugeCard";

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
    <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-indigo-100 ring-1 ring-indigo-200/60 dark:bg-white/5 dark:ring-white/10">
      <div
        className={`h-full rounded-full bg-gradient-to-r ${styles.bar} shadow-lg ${styles.glow} transition-all duration-700 ease-out`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
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
      ? "bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-500/20 dark:text-rose-100 dark:ring-rose-400/40"
      : verdict === "warning"
        ? "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-500/20 dark:text-amber-100 dark:ring-amber-400/40"
        : "bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-200 dark:ring-emerald-400/40";

  const visibleDisks = r.disks.filter(
    (d) => d.mount === "/" || d.mount.startsWith("/boot") || d.used_percent > 0,
  );

  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-5"
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-indigo-100/80 pb-4 dark:border-white/10">
        <h2 className="font-display text-xl font-bold dash-gradient-text">
          {h.hostname || "unknown"}
        </h2>
        <span
          className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider ring-1 ${badgeClass}`}
        >
          {verdict === "ok" ? "All clear" : verdict}
        </span>
        {isLive && (
          <span className="flex items-center gap-1.5 text-sm font-semibold text-emerald-700 dark:text-emerald-300">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            live
          </span>
        )}
        {!isLive && host.filename && (
          <span className="text-sm dash-subtle">{host.filename}</span>
        )}
        <span className="text-sm dash-subtle">
          {h.instance_id} · {h.instance_type} · {h.region}
        </span>
      </div>

      <DiagnosisPanel report={r} />

      <div className="grid gap-4 md:grid-cols-3">
        <GaugeCard
          label="CPU"
          value={`${r.cpu.usage_percent}%`}
          sub={`Load ${r.cpu.load_avg[0]?.toFixed(2) ?? "—"} · ${r.cpu.cores} cores · user ${r.cpu.user_percent ?? 0}% / iowait ${r.cpu.iowait_percent ?? 0}% / steal ${r.cpu.steal_percent}%`}
          pct={r.cpu.usage_percent}
          warn={t.cpu_warn ?? 80}
          crit={t.cpu_crit ?? 95}
          accent="hover:shadow-cyan-500/10"
          delay={0.05}
        />
        <GaugeCard
          label="Memory"
          value={`${r.memory.used_percent}%`}
          sub={`${fmtBytes(r.memory.available_bytes ?? r.memory.total_bytes - r.memory.used_bytes)} available · apps ~${fmtBytes(r.memory.app_bytes)} · swap ${r.memory.swap_used_percent}%`}
          pct={r.memory.used_percent}
          warn={t.memory_warn ?? 80}
          crit={t.memory_crit ?? 95}
          accent="hover:shadow-violet-500/10"
          delay={0.1}
        />
        <GaugeCard
          label="Uptime"
          value={fmtUptime(h.uptime_seconds)}
          sub={`Scanned ${fmtTime(r.timestamp)}`}
          accent="hover:shadow-fuchsia-500/10"
          delay={0.15}
        />
      </div>

      {visibleDisks.length > 0 && (
        <div className="dash-panel overflow-hidden">
          <div className="dash-panel-header">
            <h3 className="dash-heading">
              Disk
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider dash-subtle">
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
                      className="dash-row-hover"
                    >
                      <td className="px-5 py-3 font-mono font-semibold text-teal-800 dark:text-cyan-200/90">
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
                      <td className="px-5 py-3 dash-muted">
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
            <div className="dash-stat-card border-cyan-200/80 bg-gradient-to-br from-cyan-50 to-white dark:border-cyan-500/25 dark:from-cyan-950/50 dark:to-[#0a1020]">
              <p className="dash-heading text-cyan-700 dark:text-cyan-300/70">
                Docker
              </p>
              <p className="mt-2 font-mono text-lg font-bold text-cyan-900 dark:text-cyan-200">
                v{r.docker.server_version}
              </p>
            </div>
            <div className="dash-stat-card border-emerald-200/80 bg-gradient-to-br from-emerald-50 to-white dark:border-emerald-500/25 dark:from-emerald-950/50 dark:to-[#0a1020]">
              <p className="dash-heading text-emerald-700 dark:text-emerald-300/70">
                Containers
              </p>
              <p className="mt-2 font-mono text-2xl font-bold dash-title">
                {r.docker.running_count}
                <span className="ml-1 text-base font-normal dash-subtle">
                  / {r.docker.running_count + r.docker.stopped_count} running
                </span>
              </p>
              {r.docker.stopped_count > 0 && (
                <p className="mt-1 text-sm font-medium text-amber-800 dark:text-amber-300">
                  {r.docker.stopped_count} stopped
                </p>
              )}
            </div>
            <div className="dash-stat-card border-violet-200/80 bg-gradient-to-br from-violet-50 to-white dark:border-violet-500/25 dark:from-violet-950/50 dark:to-[#0a1020]">
              <p className="dash-heading text-violet-700 dark:text-violet-300/70">
                Images
              </p>
              <p className="mt-2 font-mono text-2xl font-bold dash-title">
                {r.docker.image_count}
              </p>
            </div>
            <div className="dash-stat-card border-fuchsia-200/80 bg-gradient-to-br from-fuchsia-50 to-white dark:border-fuchsia-500/25 dark:from-fuchsia-950/50 dark:to-[#0a1020]">
              <p className="dash-heading text-fuchsia-700 dark:text-fuchsia-300/70">
                Reclaimable
              </p>
              <p className="mt-2 font-mono text-lg font-bold text-fuchsia-900 dark:text-fuchsia-200">
                {r.docker.disk.images_reclaimable}
              </p>
              <p className="mt-1 text-xs dash-subtle">
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
    </motion.section>
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
    <div className="dash-panel overflow-hidden">
      <div className="dash-panel-header">
        <h3 className="dash-heading">
          {title}
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider dash-subtle">
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
                  className="px-5 py-6 text-center dash-subtle"
                >
                  None configured
                </td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr
                  key={i}
                  className="dash-row-hover"
                >
                  {row.map((cell, j) => {
                    const extra = rowClass?.(i);
                    const cls =
                      j === statusCol
                        ? (extra?.stateCol || statusColor(cell)) + " font-semibold"
                        : j === warnCol && cell !== "0"
                          ? "text-amber-700 font-semibold dark:text-amber-300"
                          : j === 0
                            ? "font-semibold text-slate-800 dark:text-slate-200"
                            : "dash-muted";
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
    <div className="dash-panel p-5">
      <h3 className="mb-4 dash-heading">
        Active alerts
      </h3>
      <ul className="space-y-3">
        {alerts.map((a, i) => (
          <li
            key={i}
            className={`rounded-xl border-l-4 px-4 py-3 ${
              a.severity === "critical"
                ? "border-rose-500 bg-gradient-to-r from-rose-50 to-white dark:from-rose-950/40 dark:to-[#0a1020]"
                : "border-amber-500 bg-gradient-to-r from-amber-50 to-white dark:from-amber-950/40 dark:to-[#0a1020]"
            }`}
          >
            <p className="font-semibold dash-title">{a.title}</p>
            <p className="mt-1 whitespace-pre-line text-sm text-slate-700 dark:text-slate-300">
              {a.message}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
