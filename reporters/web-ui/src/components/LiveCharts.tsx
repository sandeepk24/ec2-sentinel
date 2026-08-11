import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { LineChart } from "lucide-react";
import { CollapsibleTile } from "./CollapsibleTile";
import { useHistoryStore } from "../store/history";
import { cn } from "../lib/cn";

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-indigo-100 bg-white/95 px-3 py-2 text-xs shadow-[0_8px_32px_rgba(79,70,229,0.12)] backdrop-blur dark:border-white/10 dark:bg-[#0d1220]/95 dark:shadow-xl">
      <p className="mb-1 dash-subtle">
        {typeof label === "number"
          ? new Date(label).toLocaleTimeString()
          : label}
      </p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }} className="font-mono font-semibold">
          {p.name}: {p.value.toFixed(1)}%
        </p>
      ))}
    </div>
  );
}

export function LiveCharts() {
  const points = useHistoryStore((s) => s.points);
  const chartData = points.map((p) => ({
    ...p,
    time: p.t,
  }));

  return (
    <CollapsibleTile
      title="Live charts"
      subtitle="CPU and memory samples while this page is open"
      summary={
        chartData.length >= 2
          ? `Latest CPU ${chartData[chartData.length - 1]?.cpu?.toFixed(0) ?? "—"}% · Mem ${chartData[chartData.length - 1]?.memory?.toFixed(0) ?? "—"}%`
          : "Collecting samples…"
      }
      icon={LineChart}
      tone="neutral"
    >
      <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard title="CPU over time" subtitle="Live samples while this page is open">
        {chartData.length < 2 ? (
          <EmptyChart hint="Collecting samples…" />
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="cpuFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#0d9488" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#0d9488" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(79,70,229,0.08)" vertical={false} />
              <XAxis
                dataKey="time"
                tickFormatter={(v) => new Date(v).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" })}
                stroke="#6366f1"
                fontSize={11}
                tickLine={false}
                axisLine={false}
              />
              <YAxis domain={[0, 100]} stroke="#6366f1" fontSize={11} tickLine={false} axisLine={false} unit="%" />
              <Tooltip content={<ChartTooltip />} />
              <Area
                type="monotone"
                dataKey="cpu"
                name="CPU"
                stroke="#0d9488"
                fill="url(#cpuFill)"
                strokeWidth={2}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="iowait"
                name="iowait"
                stroke="#d97706"
                fill="transparent"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="Memory over time" subtitle="Used % of RAM">
        {chartData.length < 2 ? (
          <EmptyChart hint="Collecting samples…" />
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="memFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#7c3aed" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#7c3aed" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(79,70,229,0.08)" vertical={false} />
              <XAxis
                dataKey="time"
                tickFormatter={(v) => new Date(v).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" })}
                stroke="#6366f1"
                fontSize={11}
                tickLine={false}
                axisLine={false}
              />
              <YAxis domain={[0, 100]} stroke="#6366f1" fontSize={11} tickLine={false} axisLine={false} unit="%" />
              <Tooltip content={<ChartTooltip />} />
              <Area
                type="monotone"
                dataKey="memory"
                name="Memory"
                stroke="#7c3aed"
                fill="url(#memFill)"
                strokeWidth={2}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </ChartCard>
      </div>
    </CollapsibleTile>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-indigo-100/80 bg-indigo-50/20 p-4 dark:border-white/10 dark:bg-white/[0.02]">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="font-display text-sm font-bold dash-title">{title}</h3>
        <span className="text-xs font-medium dash-subtle">{subtitle}</span>
      </div>
      {children}
    </div>
  );
}

function EmptyChart({ hint }: { hint: string }) {
  return (
    <div
      className={cn(
        "flex h-[180px] items-center justify-center rounded-xl border border-dashed border-indigo-200 bg-indigo-50/30",
        "text-sm font-medium dash-subtle dark:border-white/10 dark:bg-transparent",
      )}
    >
      {hint}
    </div>
  );
}
