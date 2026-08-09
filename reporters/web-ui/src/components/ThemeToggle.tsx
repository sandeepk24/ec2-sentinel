import { Moon, Sun } from "lucide-react";
import { cn } from "../lib/cn";
import { useThemeStore } from "../store/theme";

export function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Light mode" : "Dark mode"}
      className={cn(
        "inline-flex h-10 w-10 items-center justify-center rounded-full border transition",
        "border-indigo-200/80 bg-gradient-to-b from-white to-indigo-50 text-amber-600",
        "shadow-[0_1px_2px_rgba(15,23,42,0.06),0_4px_14px_rgba(79,70,229,0.12)]",
        "hover:border-indigo-300 hover:to-violet-50",
        "dark:border-white/10 dark:bg-white/5 dark:text-amber-300 dark:shadow-none dark:hover:bg-white/10",
      )}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4 text-indigo-700" />}
    </button>
  );
}
