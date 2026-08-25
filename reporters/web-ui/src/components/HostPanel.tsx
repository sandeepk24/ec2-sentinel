import { useMemo } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Coffee,
  Container,
  FileText,
  HardDrive,
  LineChart,
  Server,
} from "lucide-react";
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
import { TileGrid, type TileDefinition } from "./CollapsibleTile";
import { DiagnosisPanel } from "./DiagnosisPanel";
import { GaugeCard } from "./GaugeCard";
import { LiveChartsContent, getChartsSummary } from "./LiveCharts";
import { useHistoryStore } from "../store/history";

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
    <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-indigo-100 ring-1 ring-indigo-200/60 dark:bg-white/5 dark:ring-white/10">
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

  const processes = r.processes ?? [];
  const ports = r.ports ?? [];
  const missingProcs = processes.filter((p) => p.status === "NOT_FOUND").length;
  const badPorts = ports.filter((p) => p.status !== "OPEN" && p.status !== "SLOW").length;
  const logHits = (r.log_matches ?? []).reduce((s, m) => s + m.count, 0);
  const alerts = host.alerts ?? [];

  const worstDisk = [...visibleDisks].sort((a, b) => b.used_percent - a.used_percent)[0];
  const diskTone =
    worstDisk && worstDisk.used_percent >= (t.disk_crit ?? 90)
      ? "crit"
      : worstDisk && worstDisk.used_percent >= (t.disk_warn ?? 75)
        ? "warn"
        : "neutral";

  const serviceTone =
    missingProcs > 0 || badPorts > 0 ? (missingProcs > 0 ? "crit" : "warn") : "ok";

  const historyPoints = useHistoryStore((s) => s.points);

  const detailTiles = useMemo(() => {
    const tiles: TileDefinition[] = [];

    if (isLive) {
      tiles.push({
        id: "charts",
        title: "Charts",
        summary: getChartsSummary(historyPoints),
        icon: LineChart,
        tone: "neutral",
        content: <LiveChartsContent />,
      });
    }

    if (visibleDisks.length > 0) {
      const growing = visibleDisks.find(
        (d) => d.trend === "growing" && d.growth_gb_per_day != null,
      );
      tiles.push({
        id: "disk",
        title: "Disk",
        summary: growing
          ? `${growing.mount} ${growing.growth_gb_per_day! >= 0 ? "+" : ""}${growing.growth_gb_per_day} GB/d`
          : worstDisk
            ? `${worstDisk.mount} ${worstDisk.used_percent}%`
            : `${visibleDisks.length} mounts`,
        icon: HardDrive,
        tone: diskTone as TileDefinition["tone"],
        content: (
          <div className="space-y-4">
            <div className="overflow-x-auto rounded-xl border border-indigo-100/80 dark:border-white/10">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-indigo-50/50 text-left text-xs uppercase tracking-wider dash-subtle dark:bg-white/[0.03]">
                    <th className="px-4 py-2.5 font-semibold">Mount</th>
                    <th className="px-4 py-2.5 font-semibold">Used</th>
                    <th className="px-4 py-2.5 font-semibold min-w-[140px]">Bar</th>
                    <th className="px-4 py-2.5 font-semibold">Free</th>
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
                      <tr key={d.mount} className="dash-row-hover">
                        <td className="px-4 py-3 font-mono font-semibold text-teal-800 dark:text-cyan-200/90">
                          {d.mount}
                        </td>
                        <td
                          className={`px-4 py-3 font-mono font-semibold ${levelStyles[level].text}`}
                        >
                          {d.used_percent}%
                        </td>
                        <td className="px-4 py-3">
                          <ProgressBar
                            pct={d.used_percent}
                            warn={t.disk_warn ?? 75}
                            crit={t.disk_crit ?? 90}
                          />
                        </td>
                        <td className="px-4 py-3 dash-muted">
                          {fmtBytes(d.free_bytes ?? d.total_bytes - d.used_bytes)}
                          {d.days_until_full != null && (
                            <span className="ml-2 text-amber-700 dark:text-amber-300/80">
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

            {visibleDisks.some((d) => d.growth_gb_per_day != null || d.trend) && (
              <div className="space-y-2">
                <h4 className="text-xs font-bold uppercase tracking-wider dash-heading">
                  Growth forecast
                </h4>
                {visibleDisks.map((d) => {
                  if (d.growth_gb_per_day == null && !d.trend) return null;
                  const growing = d.trend === "growing";
                  return (
                    <div
                      key={`growth-${d.mount}`}
                      className={`rounded-xl border px-4 py-3 ${
                        growing && (d.days_until_90 ?? 999) < 14
                          ? "border-amber-200/90 bg-amber-50/50 dark:border-amber-500/25 dark:bg-amber-950/30"
                          : "border-indigo-100/80 bg-indigo-50/30 dark:border-white/10 dark:bg-white/[0.03]"
                      }`}
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <p className="font-mono text-sm font-semibold dash-title">{d.mount}</p>
                        <p className="text-xs uppercase tracking-wider dash-subtle">
                          {d.trend || "unknown"}
                          {d.growth_gb_per_day != null && (
                            <span className="ml-2 font-mono normal-case">
                              {d.growth_gb_per_day >= 0 ? "+" : ""}
                              {d.growth_gb_per_day} GB/day
                            </span>
                          )}
                        </p>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-3 text-xs dash-muted">
                        {d.days_until_80 != null && (
                          <span>
                            80% ~<span className="font-mono">{Math.round(d.days_until_80)}d</span>
                          </span>
                        )}
                        {d.days_until_90 != null && (
                          <span>
                            90% ~<span className="font-mono">{Math.round(d.days_until_90)}d</span>
                          </span>
                        )}
                        {d.days_until_95 != null && (
                          <span>
                            95% ~<span className="font-mono">{Math.round(d.days_until_95)}d</span>
                          </span>
                        )}
                        {d.predicted_full_date && (
                          <span>
                            Full ~<span className="font-mono">{d.predicted_full_date}</span>
                          </span>
                        )}
                        {d.growth_sample_count != null && d.growth_sample_count > 0 && (
                          <span className="dash-subtle">n={d.growth_sample_count}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ),
      });
    }

    if (processes.length > 0 || ports.length > 0) {
      tiles.push({
        id: "services",
        title: "Services",
        summary: `${processes.length - missingProcs}/${processes.length} proc · ${ports.length - badPorts}/${ports.length} ports`,
        icon: Server,
        tone: serviceTone as TileDefinition["tone"],
        content: (
          <div className="grid gap-4 lg:grid-cols-2">
            <DataTable
              embedded
              title="Processes"
              headers={["Name", "Status", "PID", "CPU", "Mem"]}
              rows={processes.map((p) => [
                p.name,
                p.status,
                String(p.pid ?? "—"),
                p.cpu_percent != null ? `${p.cpu_percent}%` : "—",
                p.memory_mb != null ? `${p.memory_mb} MB` : "—",
              ])}
              statusCol={1}
            />
            <DataTable
              embedded
              title="Ports"
              headers={["Port", "Service", "Status", "Latency"]}
              rows={ports.map((p) => [
                String(p.port),
                p.service,
                p.status,
                p.response_ms != null ? `${p.response_ms} ms` : "—",
              ])}
              statusCol={2}
            />
          </div>
        ),
      });
    }

    if (r.java?.enabled) {
      tiles.push({
        id: "java",
        title: "Java",
        summary:
          !r.java.available && r.java.processes.length === 0
            ? "None"
            : `${r.java.processes.length} JVM · ${r.java.installation_count} RT`,
        icon: Coffee,
        tone:
          r.java.processes.length > 0
            ? "neutral"
            : r.java.available
              ? "ok"
              : "warn",
        content:
          !r.java.available && r.java.processes.length === 0 ? (
            <p className="text-sm dash-muted">
              {r.java.error || "No Java runtime detected on this host."}
            </p>
          ) : (
            <div className="space-y-4">
              {r.java.error && (
                <p className="text-sm text-amber-800 dark:text-amber-200/90">{r.java.error}</p>
              )}
              <div className="grid gap-3 sm:grid-cols-3">
                <MiniStat label="Runtimes" value={String(r.java.installation_count)} />
                <MiniStat label="JDK" value={String(r.java.jdk_count)} />
                <MiniStat label="JVMs" value={String(r.java.processes.length)} />
              </div>
              {r.java.installations.length > 0 && (
                <DataTable
                  embedded
                  title="Installations"
                  headers={["Vendor", "Version", "Type", "Path", "javac"]}
                  rows={r.java.installations.map((j) => [
                    j.vendor,
                    j.version,
                    j.is_jdk ? "JDK" : "JRE",
                    j.path.length > 40 ? "…" + j.path.slice(-39) : j.path,
                    j.javac_version ?? "—",
                  ])}
                />
              )}
              <DataTable
                embedded
                title="Running Java (ps -ef | grep java)"
                headers={["PID", "Name", "Version", "Binary", "Command"]}
                rows={
                  r.java.processes.length > 0
                    ? r.java.processes.map((p) => [
                        String(p.pid),
                        p.name,
                        p.version ?? "—",
                        p.java_path
                          ? p.java_path.length > 28
                            ? "…" + p.java_path.slice(-27)
                            : p.java_path
                          : "—",
                        p.cmdline.length > 44 ? p.cmdline.slice(0, 44) + "…" : p.cmdline,
                      ])
                    : [["—", "—", "—", "—", "No running JVM processes"]]
                }
              />
            </div>
          ),
      });
    }

    if (r.docker?.available) {
      const docker = r.docker;
      const disk = docker.disk;
      const dangling = docker.dangling_count ?? 0;
      const cacheReclaim = disk.build_cache_reclaimable ?? "0B";
      const totalReclaim = docker.total_reclaimable ?? disk.images_reclaimable;
      const suggestions = docker.cleanup_suggestions ?? [];
      const dockerTone =
        dangling >= 5 || suggestions.some((s) => s.severity === "warning")
          ? "warn"
          : docker.stopped_count > 0
            ? "warn"
            : "ok";
      const dockerSummary =
        dangling > 0
          ? `${docker.running_count} up · ${dangling} dangling · ${totalReclaim} reclaimable`
          : `${docker.running_count} up · ${docker.stopped_count} down · ${totalReclaim} reclaimable`;

      tiles.push({
        id: "docker",
        title: "Docker",
        summary: dockerSummary,
        icon: Container,
        tone: dockerTone,
        content: (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <MiniStat label="Version" value={`v${docker.server_version}`} small />
              <MiniStat label="Running" value={String(docker.running_count)} />
              <MiniStat
                label="Dangling"
                value={String(dangling)}
                small={dangling >= 5}
              />
              <MiniStat label="Build cache" value={cacheReclaim} small />
            </div>

            <DataTable
              embedded
              title="Disk usage"
              headers={["Type", "Total", "Reclaimable"]}
              rows={[
                ["Images", disk.images_size, disk.images_reclaimable],
                ["Containers", disk.containers_size, disk.containers_reclaimable],
                ["Volumes", disk.volumes_size, disk.volumes_reclaimable],
                [
                  "Build cache",
                  disk.build_cache_size ?? "—",
                  disk.build_cache_reclaimable ?? "—",
                ],
              ]}
              warnCol={2}
            />

            {suggestions.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-xs font-bold uppercase tracking-wider dash-heading">
                  Cleanup suggestions
                </h4>
                <div className="space-y-2">
                  {suggestions.map((s, i) => (
                    <div
                      key={i}
                      className={`rounded-xl border px-4 py-3 ${
                        s.severity === "warning"
                          ? "border-amber-200/90 bg-amber-50/50 dark:border-amber-500/25 dark:bg-amber-950/30"
                          : "border-indigo-100/80 bg-indigo-50/30 dark:border-white/10 dark:bg-white/[0.03]"
                      }`}
                    >
                      <p className="text-sm font-semibold dash-title">{s.title}</p>
                      <p className="mt-1 text-xs dash-subtle">{s.description}</p>
                      <code className="mt-2 block rounded-lg bg-black/5 px-3 py-2 font-mono text-xs dark:bg-black/30">
                        {s.command}
                      </code>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="grid gap-4 lg:grid-cols-2">
              <DataTable
                embedded
                title="Containers"
                headers={["Name", "Image", "State", "Status"]}
                rows={(docker.containers ?? []).map((c) => [
                  c.name,
                  c.image.length > 24 ? c.image.slice(0, 24) + "…" : c.image,
                  c.state,
                  c.status.length > 36 ? c.status.slice(0, 36) + "…" : c.status,
                ])}
                rowClass={(rowIdx) => {
                  const c = docker.containers[rowIdx];
                  return { stateCol: dockerStateColor(c.state, c.health) };
                }}
                statusCol={2}
              />
              <DataTable
                embedded
                title={dangling > 0 ? `Dangling images (${dangling})` : "Images"}
                headers={["Repository", "Tag", "Size", "Age"]}
                rows={
                  dangling > 0
                    ? (docker.dangling_images ?? []).map((img) => [
                        img.repository,
                        img.tag,
                        img.size,
                        img.created_since || "—",
                      ])
                    : (docker.images ?? []).map((img) => [
                        img.repository,
                        img.tag,
                        img.size,
                        img.created_since || "—",
                      ])
                }
              />
            </div>
          </div>
        ),
      });
    }

    if (r.log_matches?.length > 0) {
      tiles.push({
        id: "logs",
        title: "Logs",
        summary: `${logHits} hits`,
        icon: FileText,
        tone: logHits > 0 ? "warn" : "neutral",
        content: (
          <DataTable
            embedded
            title="Matches"
            headers={["Pattern", "Hits", "File"]}
            rows={r.log_matches.map((m) => [m.pattern, String(m.count), m.file])}
            warnCol={1}
          />
        ),
      });
    }

    if (alerts.length > 0) {
      tiles.push({
        id: "alerts",
        title: "Alerts",
        summary: `${alerts.length} firing`,
        icon: AlertTriangle,
        tone: alerts.some((a) => a.severity === "critical") ? "crit" : "warn",
        content: <AlertList alerts={alerts} embedded />,
      });
    }

    return tiles;
  }, [
    isLive,
    historyPoints,
    visibleDisks,
    worstDisk,
    diskTone,
    t,
    processes,
    ports,
    missingProcs,
    badPorts,
    serviceTone,
    r.java,
    r.docker,
    r.log_matches,
    logHits,
    alerts,
  ]);

  const defaultDetailId =
    alerts.length > 0
      ? "alerts"
      : diskTone !== "neutral"
        ? "disk"
        : serviceTone !== "ok"
          ? "services"
          : null;

  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4"
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
          {h.instance_type}
          {h.cloud_provider && h.cloud_provider !== "unknown" ? ` · ${h.cloud_provider}` : ""}
          {" · "}
          {h.region}
          {h.os?.name && h.os.name !== "unknown" ? ` · ${h.os.name}` : ""}
        </span>
      </div>

      <DiagnosisPanel report={r} />

      <div className="grid gap-3 sm:grid-cols-3">
        <GaugeCard
          label="CPU"
          value={`${r.cpu.usage_percent}%`}
          sub={`Load ${r.cpu.load_avg[0]?.toFixed(2) ?? "—"} · ${r.cpu.cores} cores`}
          pct={r.cpu.usage_percent}
          warn={t.cpu_warn ?? 80}
          crit={t.cpu_crit ?? 95}
          accent="hover:shadow-cyan-500/10"
          delay={0.05}
        />
        <GaugeCard
          label="Memory"
          value={`${r.memory.used_percent}%`}
          sub={`${fmtBytes(r.memory.available_bytes ?? r.memory.total_bytes - r.memory.used_bytes)} free`}
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

      <TileGrid
        tiles={detailTiles}
        defaultActiveId={defaultDetailId}
        sectionLabel="Host details"
      />
    </motion.section>
  );
}

function MiniStat({
  label,
  value,
  small,
}: {
  label: string;
  value: string;
  small?: boolean;
}) {
  return (
    <div className="rounded-xl border border-indigo-100/80 bg-indigo-50/30 px-4 py-3 dark:border-white/10 dark:bg-white/[0.03]">
      <p className="text-[10px] font-bold uppercase tracking-wider dash-subtle">{label}</p>
      <p
        className={`mt-1 font-mono font-bold dash-title ${small ? "text-base" : "text-xl"}`}
      >
        {value}
      </p>
    </div>
  );
}

function DataTable({
  title,
  headers,
  rows,
  statusCol,
  warnCol,
  rowClass,
  embedded,
}: {
  title: string;
  headers: string[];
  rows: string[][];
  statusCol?: number;
  warnCol?: number;
  rowClass?: (rowIdx: number) => { stateCol?: string };
  embedded?: boolean;
}) {
  const table = (
    <div className="overflow-x-auto">
      {embedded && (
        <h4 className="mb-2 text-xs font-bold uppercase tracking-wider dash-heading">{title}</h4>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wider dash-subtle">
            {headers.map((h) => (
              <th key={h} className={`font-semibold ${embedded ? "px-3 py-2" : "px-5 py-3"}`}>
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
                className={`text-center dash-subtle ${embedded ? "px-3 py-4" : "px-5 py-6"}`}
              >
                None configured
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={i}
                className="dash-row-hover border-t border-indigo-50/80 dark:border-white/5"
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
                    <td key={j} className={`${embedded ? "px-3 py-2.5" : "px-5 py-3"} ${cls}`}>
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
  );

  if (embedded) return table;

  return (
    <div className="dash-panel overflow-hidden">
      <div className="dash-panel-header">
        <h3 className="dash-heading">{title}</h3>
      </div>
      {table}
    </div>
  );
}

function AlertList({ alerts, embedded }: { alerts: Alert[]; embedded?: boolean }) {
  return (
    <ul className={`space-y-3 ${embedded ? "" : "dash-panel p-5"}`}>
      {!embedded && <h3 className="mb-4 dash-heading">Active alerts</h3>}
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
  );
}
