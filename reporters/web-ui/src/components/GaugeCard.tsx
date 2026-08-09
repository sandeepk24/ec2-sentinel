import { motion } from "framer-motion";
import { cn } from "../lib/cn";
import { levelForPercent, levelStyles } from "../utils";

interface Props {
  label: string;
  value: string;
  sub: string;
  pct?: number;
  warn?: number;
  crit?: number;
  accent?: string;
  delay?: number;
}

export function GaugeCard({
  label,
  value,
  sub,
  pct,
  warn = 80,
  crit = 95,
  accent = "",
  delay = 0,
}: Props) {
  const level = pct != null ? levelForPercent(pct, warn, crit) : "ok";
  const styles = levelStyles[level];
  const circumference = 2 * Math.PI * 42;
  const stroke = pct != null ? circumference * (1 - Math.min(pct, 100) / 100) : circumference;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className={cn("group dash-gauge", accent)}
    >
      <div className="absolute -right-6 -top-6 h-28 w-28 rounded-full bg-gradient-to-br from-indigo-200/40 via-violet-200/20 to-transparent blur-2xl dark:from-white/10 dark:to-transparent" />
      <p className="dash-heading">
        {label}
      </p>

      <div className="mt-3 flex items-center gap-4">
        {pct != null && (
          <div className="relative h-24 w-24 shrink-0">
            <svg viewBox="0 0 100 100" className="-rotate-90">
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke="rgba(99,102,241,0.18)"
                strokeWidth="8"
              />
              <motion.circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke="url(#gaugeGrad)"
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={circumference}
                initial={{ strokeDashoffset: circumference }}
                animate={{ strokeDashoffset: stroke }}
                transition={{ duration: 0.8, ease: "easeOut" }}
                className={cn("drop-shadow", styles.glow)}
              />
              <defs>
                <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#0d9488" />
                  <stop offset="50%" stopColor="#4f46e5" />
                  <stop offset="100%" stopColor="#9333ea" />
                </linearGradient>
              </defs>
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className={cn("font-mono text-sm font-bold", styles.text)}>
                {Math.round(pct)}%
              </span>
            </div>
          </div>
        )}
        <div className="min-w-0">
          <p className="font-mono text-3xl font-bold tracking-tight text-slate-900 dark:text-white">{value}</p>
          <p className="mt-2 text-sm leading-snug text-slate-600 dark:text-slate-400">{sub}</p>
        </div>
      </div>
    </motion.div>
  );
}
