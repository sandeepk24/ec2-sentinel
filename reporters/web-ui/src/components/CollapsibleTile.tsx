import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, type LucideIcon } from "lucide-react";
import { cn } from "../lib/cn";

const toneStyles = {
  neutral:
    "border-indigo-100/80 hover:border-indigo-200 dark:border-white/10 dark:hover:border-white/20",
  ok: "border-emerald-200/80 hover:border-emerald-300 dark:border-emerald-500/25 dark:hover:border-emerald-500/40",
  warn: "border-amber-200/80 hover:border-amber-300 dark:border-amber-500/25 dark:hover:border-amber-500/40",
  crit: "border-rose-200/80 hover:border-rose-300 dark:border-rose-500/25 dark:hover:border-rose-500/40",
};

const badgeStyles = {
  neutral: "bg-indigo-50 text-indigo-700 ring-indigo-100 dark:bg-white/10 dark:text-violet-200 dark:ring-white/10",
  ok: "bg-emerald-50 text-emerald-800 ring-emerald-100 dark:bg-emerald-500/20 dark:text-emerald-200 dark:ring-emerald-400/30",
  warn: "bg-amber-50 text-amber-900 ring-amber-100 dark:bg-amber-500/20 dark:text-amber-100 dark:ring-amber-400/30",
  crit: "bg-rose-50 text-rose-800 ring-rose-100 dark:bg-rose-500/20 dark:text-rose-100 dark:ring-rose-400/30",
};

interface Props {
  title: string;
  subtitle?: string;
  summary?: string;
  icon?: LucideIcon;
  badge?: string;
  tone?: keyof typeof toneStyles;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function CollapsibleTile({
  title,
  subtitle,
  summary,
  icon: Icon,
  badge,
  tone = "neutral",
  defaultOpen = false,
  children,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      className={cn(
        "dash-panel overflow-hidden transition-colors",
        toneStyles[tone],
        open && "ring-1 ring-indigo-200/60 dark:ring-violet-500/20",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-indigo-50/40 dark:hover:bg-white/[0.02]"
        aria-expanded={open}
      >
        {Icon && (
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-100 to-violet-100 text-indigo-700 dark:from-violet-500/20 dark:to-fuchsia-500/10 dark:text-violet-200">
            <Icon className="h-4 w-4" />
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-display text-base font-bold dash-title">{title}</span>
            {badge && (
              <span
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1",
                  badgeStyles[tone],
                )}
              >
                {badge}
              </span>
            )}
          </span>
          {(subtitle || summary) && (
            <span className="mt-1 block text-sm dash-muted">
              {open ? subtitle : summary || subtitle}
            </span>
          )}
        </span>
        <ChevronDown
          className={cn(
            "h-5 w-5 shrink-0 text-indigo-400 transition-transform duration-200 dark:text-violet-400",
            open && "rotate-180",
          )}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="border-t border-indigo-100/80 px-5 pb-5 pt-4 dark:border-white/10">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
