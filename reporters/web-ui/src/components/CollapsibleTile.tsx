import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, type LucideIcon } from "lucide-react";
import { cn } from "../lib/cn";

export type TileTone = "neutral" | "ok" | "warn" | "crit";

export interface TileDefinition {
  id: string;
  title: string;
  summary: string;
  icon?: LucideIcon;
  tone?: TileTone;
  content: ReactNode;
}

const toneTileStyles: Record<TileTone, string> = {
  neutral:
    "border-indigo-100/90 bg-white/90 hover:border-indigo-200 dark:border-white/10 dark:bg-[#0a1020]/80 dark:hover:border-white/20",
  ok: "border-emerald-200/90 bg-emerald-50/40 hover:border-emerald-300 dark:border-emerald-500/20 dark:bg-emerald-950/30 dark:hover:border-emerald-500/40",
  warn: "border-amber-200/90 bg-amber-50/40 hover:border-amber-300 dark:border-amber-500/20 dark:bg-amber-950/30 dark:hover:border-amber-500/40",
  crit: "border-rose-200/90 bg-rose-50/40 hover:border-rose-300 dark:border-rose-500/20 dark:bg-rose-950/30 dark:hover:border-rose-500/40",
};

const toneRingStyles: Record<TileTone, string> = {
  neutral: "ring-indigo-400/50 dark:ring-violet-400/40",
  ok: "ring-emerald-400/50",
  warn: "ring-amber-400/50",
  crit: "ring-rose-400/50",
};

const toneIconStyles: Record<TileTone, string> = {
  neutral:
    "from-indigo-100 to-violet-100 text-indigo-700 dark:from-violet-500/25 dark:to-fuchsia-500/15 dark:text-violet-200",
  ok: "from-emerald-100 to-teal-100 text-emerald-700 dark:from-emerald-500/25 dark:to-teal-500/15 dark:text-emerald-200",
  warn: "from-amber-100 to-orange-100 text-amber-800 dark:from-amber-500/25 dark:to-orange-500/15 dark:text-amber-200",
  crit: "from-rose-100 to-pink-100 text-rose-700 dark:from-rose-500/25 dark:to-pink-500/15 dark:text-rose-200",
};

function CompactTile({
  title,
  summary,
  icon: Icon,
  tone = "neutral",
  active,
  onClick,
}: {
  title: string;
  summary: string;
  icon?: LucideIcon;
  tone?: TileTone;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "group flex aspect-square w-full flex-col items-center justify-center gap-1.5 rounded-2xl border p-2.5 text-center shadow-sm transition",
        "hover:-translate-y-0.5 hover:shadow-md active:translate-y-0",
        toneTileStyles[tone],
        active && cn("ring-2 shadow-md", toneRingStyles[tone]),
      )}
    >
      {Icon && (
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br shadow-inner",
            toneIconStyles[tone],
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
      )}
      <span className="line-clamp-2 w-full text-[11px] font-bold leading-tight dash-title">
        {title}
      </span>
      <span className="line-clamp-2 w-full text-[9px] leading-tight dash-subtle">{summary}</span>
    </button>
  );
}

export function TileGrid({
  tiles,
  defaultActiveId = null,
  sectionLabel = "Details",
}: {
  tiles: TileDefinition[];
  defaultActiveId?: string | null;
  sectionLabel?: string;
}) {
  const [activeId, setActiveId] = useState<string | null>(defaultActiveId);
  const active = tiles.find((t) => t.id === activeId);

  if (tiles.length === 0) return null;

  return (
    <div className="space-y-3">
      {sectionLabel ? (
        <p className="text-[11px] font-bold uppercase tracking-[0.22em] dash-heading">
          {sectionLabel}
          <span className="ml-2 font-normal normal-case tracking-normal text-slate-500 dark:text-slate-500">
            tap a tile to expand
          </span>
        </p>
      ) : null}

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
        {tiles.map((tile) => (
          <CompactTile
            key={tile.id}
            title={tile.title}
            summary={tile.summary}
            icon={tile.icon}
            tone={tile.tone}
            active={activeId === tile.id}
            onClick={() => setActiveId(activeId === tile.id ? null : tile.id)}
          />
        ))}
      </div>

      <AnimatePresence mode="wait">
        {active && (
          <motion.div
            key={active.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.18 }}
            className="dash-panel overflow-hidden"
          >
            <div className="flex items-center justify-between border-b border-indigo-100/80 px-4 py-3 dark:border-white/10">
              <div className="flex min-w-0 items-center gap-3">
                {active.icon && (
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-100 to-violet-100 text-indigo-700 dark:from-violet-500/25 dark:to-fuchsia-500/15 dark:text-violet-200">
                    <active.icon className="h-4 w-4" />
                  </span>
                )}
                <div className="min-w-0">
                  <h4 className="truncate font-display text-sm font-bold dash-title">
                    {active.title}
                  </h4>
                  <p className="truncate text-xs dash-subtle">{active.summary}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setActiveId(null)}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-indigo-100 text-slate-500 transition hover:bg-indigo-50 dark:border-white/10 dark:hover:bg-white/10"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[min(70vh,640px)] overflow-y-auto px-4 py-4">
              {active.content}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
