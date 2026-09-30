"use client";

import * as React from "react";

import { MonitorIcon, MoonIcon, SunIcon } from "@/components/icons";
import { cn } from "@/components/ui/primitives";
import { THEME_STORAGE_KEY } from "@/lib/theme";

/**
 * Light, dark, or whatever the device is set to.
 *
 * The choice is kept on this device (localStorage) - it is a display
 * preference, not account data. The class on <html> is set before first paint
 * by THEME_SCRIPT in layout.tsx, so a dark-mode visitor never sees a white
 * flash; this provider only takes over once React is running.
 */
export type ThemePreference = "light" | "dark" | "system";
type Resolved = "light" | "dark";

/** The page background of each theme, for the browser's toolbar colour. */
const TOOLBAR_COLOURS: Record<Resolved, string> = { light: "#F6F8F7", dark: "#0B100E" };

type ThemeContextValue = {
  preference: ThemePreference;
  resolved: Resolved;
  setPreference: (next: ThemePreference) => void;
};

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

function systemTheme(): Resolved {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function apply(resolved: Resolved) {
  const root = document.documentElement;
  // Switch every colour at once: without this, elements with a colour
  // transition fade at different speeds and the page shimmers mid-change.
  const freeze = document.createElement("style");
  freeze.textContent = "*,*::before,*::after{transition:none!important}";
  document.head.appendChild(freeze);
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  document
    .querySelectorAll('meta[name="theme-color"]')
    .forEach((meta) => meta.setAttribute("content", TOOLBAR_COLOURS[resolved]));
  // Force a style flush, then let transitions work again.
  void window.getComputedStyle(root).opacity;
  window.setTimeout(() => freeze.remove(), 0);
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = React.useState<ThemePreference>("system");
  const [resolved, setResolved] = React.useState<Resolved>("light");

  // Pick up what the head script already applied.
  React.useEffect(() => {
    let stored: ThemePreference = "system";
    try {
      const value = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (value === "light" || value === "dark" || value === "system") stored = value;
    } catch {
      // Storage blocked: the preference lasts for this page only.
    }
    setPreferenceState(stored);
    setResolved(stored === "system" ? systemTheme() : stored);
  }, []);

  // Follow the device while on "system": on the media query's change event,
  // and again whenever the page comes back into view - a device theme usually
  // changes while the tab is in the background, and not every environment
  // delivers the change event to a hidden page.
  React.useEffect(() => {
    if (preference !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => {
      const next = media.matches ? "dark" : "light";
      if (document.documentElement.classList.contains("dark") === (next === "dark")) return;
      setResolved(next);
      apply(next);
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") sync();
    };
    media.addEventListener("change", sync);
    window.addEventListener("focus", sync);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      media.removeEventListener("change", sync);
      window.removeEventListener("focus", sync);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [preference]);

  const setPreference = React.useCallback((next: ThemePreference) => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage blocked: still switch for this page.
    }
    const nextResolved = next === "system" ? systemTheme() : next;
    setPreferenceState(next);
    setResolved(nextResolved);
    apply(nextResolved);
  }, []);

  const value = React.useMemo(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = React.useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}

const OPTIONS: { value: ThemePreference; label: string; icon: React.ReactNode }[] = [
  { value: "light", label: "Light", icon: <SunIcon className="h-4 w-4" /> },
  { value: "dark", label: "Dark", icon: <MoonIcon className="h-4 w-4" /> },
  { value: "system", label: "System", icon: <MonitorIcon className="h-4 w-4" /> },
];

/**
 * Three-way theme choice. `compact` shows icons only, for menus and the
 * footer; the full version, with labels, is for Settings.
 */
export function ThemeSwitcher({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  const { preference, setPreference } = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className={cn("inline-flex rounded-lg bg-sunken p-0.5", compact ? "" : "w-full sm:w-auto", className)}
    >
      {OPTIONS.map((option) => {
        const active = preference === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={compact ? option.label : undefined}
            title={compact ? option.label : undefined}
            onClick={() => setPreference(option.value)}
            className={cn(
              "flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors",
              compact ? "h-11 w-11 sm:h-9 sm:w-10" : "min-h-11 flex-1 px-3 sm:min-h-9 sm:flex-none",
              active
                ? "bg-raised text-ink shadow-card ring-1 ring-line"
                : "text-ink-muted hover:text-ink",
            )}
          >
            {option.icon}
            {compact ? null : option.label}
          </button>
        );
      })}
    </div>
  );
}
