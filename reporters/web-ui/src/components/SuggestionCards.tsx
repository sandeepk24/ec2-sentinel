export interface ActionSuggestion {
  severity: "info" | "warning" | "critical";
  category: string;
  title: string;
  command: string;
  description: string;
  process_name?: string;
  pid?: number | null;
}

export function SuggestionCards({ suggestions }: { suggestions: ActionSuggestion[] }) {
  if (suggestions.length === 0) return null;

  return (
    <div className="space-y-2">
      {suggestions.map((s, i) => (
        <div
          key={i}
          className={`rounded-xl border px-4 py-3 ${
            s.severity === "critical"
              ? "border-rose-200/90 bg-rose-50/50 dark:border-rose-500/25 dark:bg-rose-950/30"
              : s.severity === "warning"
                ? "border-amber-200/90 bg-amber-50/50 dark:border-amber-500/25 dark:bg-amber-950/30"
                : "border-indigo-100/80 bg-indigo-50/30 dark:border-white/10 dark:bg-white/[0.03]"
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider dash-subtle">
              {s.category}
            </span>
            {s.pid != null && (
              <span className="font-mono text-[10px] dash-muted">pid {s.pid}</span>
            )}
          </div>
          <p className="mt-1 text-sm font-semibold dash-title">{s.title}</p>
          <p className="mt-1 text-xs dash-subtle">{s.description}</p>
          <code className="mt-2 block rounded-lg bg-black/5 px-3 py-2 font-mono text-xs dark:bg-black/30">
            {s.command}
          </code>
        </div>
      ))}
    </div>
  );
}
