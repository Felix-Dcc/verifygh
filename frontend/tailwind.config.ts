import type { Config } from "tailwindcss";

/**
 * VerifyGH design tokens. Every colour, size, radius and shadow in the product
 * comes from here; see docs/DESIGN-SYSTEM.md for how they are meant to be used.
 *
 * Palette: one deep Ghanaian green for brand actions and emphasis, a muted gold
 * used only for rewards, warm greens-greys for everything else, and four
 * semantic colours that always mean the same thing (success, attention,
 * danger, information). Neutral text colours are chosen for WCAG AA contrast
 * on both white and the page background - see docs/UI-AUDIT.md section 5.
 */

/** A theme colour: the variable holds "R G B" so opacity modifiers still work. */
function tone(name: string): string {
  return `rgb(var(--c-${name}) / <alpha-value>)`;
}

function scale(name: string, steps: number[]): Record<number, string> {
  return Object.fromEntries(steps.map((step) => [step, tone(`${name}-${step}`)]));
}

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  // The theme is a class on <html>, set before first paint by the script in
  // src/app/layout.tsx. Components rarely need `dark:` - the tokens switch.
  darkMode: "class",
  theme: {
    extend: {
      // Every colour is a CSS variable (src/app/globals.css) holding an "R G B"
      // triplet, set once for light and once for dark. Components never name
      // a theme: `bg-surface` is white in light mode and deep green-grey in dark.
      colors: {
        // Page background; the slightly different tone for table heads, inset
        // panels and hover rows; cards; and floating things (menus, dialogs).
        canvas: tone("canvas"),
        sunken: tone("sunken"),
        surface: tone("surface"),
        raised: tone("raised"),
        // Behind a dialog. Always used with an opacity (bg-scrim/50).
        scrim: tone("scrim"),
        ink: {
          DEFAULT: tone("ink"),
          soft: tone("ink-soft"),
          muted: tone("ink-muted"),
          faint: tone("ink-faint"),
        },
        line: {
          DEFAULT: tone("line"),
          strong: tone("line-strong"),
        },
        // Filled primary actions. Separate from brand-600/700 because in dark
        // mode a button fill must stay deep (white text on it) while brand
        // text must turn light.
        primary: {
          DEFAULT: tone("primary"),
          hover: tone("primary-hover"),
          active: tone("primary-active"),
        },
        // The green band behind the homepage hero and closing call to action:
        // white text sits on it in both themes.
        band: { DEFAULT: tone("band"), deep: tone("band-deep") },
        // The homepage's night-to-day palette (hero, the privacy section, the
        // close). Fixed in both themes: these surfaces are always dark, and
        // the blends into the page use the --c-sky-* ramp in globals.css.
        navy: { DEFAULT: "#071426", deep: "#050B18" },
        azure: "#0878D1",
        aqua: "#28C7F7",
        leaf: { DEFAULT: "#20B26B", light: "#65D99A" },
        brand: scale("brand", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        gold: scale("gold", [100, 300, 500, 700]),
        danger: { ...scale("danger", [50, 200, 500, 700]), solid: tone("danger-solid") },
        success: scale("success", [50, 200, 500, 700]),
        warn: scale("warn", [50, 200, 500, 700]),
        info: scale("info", [50, 200, 500, 700]),
      },
      fontFamily: {
        // IBM Plex, self-hosted by next/font (src/app/layout.tsx). The system
        // stack is only the fallback while it loads.
        sans: [
          "var(--font-sans)",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Cascadia Mono",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        // The type scale. Dashboard body text is 14px (text-sm); 16px (text-base)
        // is for form inputs, where iOS zooms anything smaller.
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.01em" }],
        caption: ["0.75rem", { lineHeight: "1.125rem" }],
        label: ["0.8125rem", { lineHeight: "1.25rem", fontWeight: "500" }],
        heading: ["1.0625rem", { lineHeight: "1.5rem", letterSpacing: "-0.01em", fontWeight: "600" }],
        title: ["1.375rem", { lineHeight: "1.875rem", letterSpacing: "-0.015em", fontWeight: "600" }],
        display: ["1.875rem", { lineHeight: "2.25rem", letterSpacing: "-0.02em", fontWeight: "600" }],
        // Money that is the point of the screen: the wallet balance.
        figure: ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.025em", fontWeight: "600" }],
      },
      // One rule: controls 8px, panels 10-12px, pills and avatars full.
      // The larger aliases are pinned so older classes cannot drift rounder.
      borderRadius: {
        sm: "0.25rem",
        DEFAULT: "0.375rem",
        md: "0.375rem",
        lg: "0.5rem",
        xl: "0.625rem",
        "2xl": "0.75rem",
        "3xl": "0.75rem",
        // Phone mockups on the marketing pages only - never on product UI.
        device: "2rem",
      },
      // Surfaces are separated by borders; shadow means "floating above the page".
      // Defined per theme in globals.css - dark shadows are deeper and softer.
      boxShadow: {
        card: "var(--shadow-card)",
        raised: "var(--shadow-raised)",
        pop: "var(--shadow-pop)",
        focus: "0 0 0 3px rgb(var(--c-brand-500) / 0.25)",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(0.9)", opacity: "0.7" },
          "70%": { transform: "scale(1.6)", opacity: "0" },
          "100%": { transform: "scale(1.6)", opacity: "0" },
        },
        // Service logos around the homepage phone: a slow drift, never a bounce.
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
        // The favourite star: a short, damped pop, not a bounce.
        "pin-pop": {
          "0%": { transform: "scale(1)" },
          "40%": { transform: "scale(1.22)" },
          "100%": { transform: "scale(1)" },
        },
      },
      animation: {
        "fade-in": "fade-in 160ms ease-out",
        "slide-up": "slide-up 200ms cubic-bezier(0.16, 1, 0.3, 1)",
        shimmer: "shimmer 1.6s infinite",
        "pulse-ring": "pulse-ring 1.8s cubic-bezier(0.24, 0, 0.38, 1) infinite",
        "pin-pop": "pin-pop 220ms cubic-bezier(0.16, 1, 0.3, 1)",
        float: "float 6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
