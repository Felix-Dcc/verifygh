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
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Page background, and the slightly deeper tone used for table heads,
        // inset panels and hover rows.
        canvas: "#F6F8F7",
        sunken: "#F0F3F1",
        surface: "#FFFFFF",
        ink: {
          DEFAULT: "#0F1B17",
          // Secondary text: 10.4:1 on white.
          soft: "#34433C",
          // Supporting text, labels, metadata: 6.2:1 on white, 5.8:1 on canvas.
          muted: "#56645D",
          // Least important text - timestamps, placeholders: 4.8:1 on white.
          faint: "#68766F",
        },
        line: {
          DEFAULT: "#E3E8E5",
          strong: "#C9D2CD",
        },
        brand: {
          50: "#EDF6F2",
          100: "#D3E9DF",
          200: "#A6D3BF",
          300: "#6FB79A",
          400: "#3D9A76",
          500: "#0F7A55",
          600: "#0B6446",
          700: "#094F37",
          800: "#073C2A",
          900: "#052A1E",
        },
        gold: {
          100: "#FBF2DC",
          300: "#E9CE87",
          500: "#C79A2E",
          700: "#8F6D1B",
        },
        danger: {
          50: "#FEF3F2",
          200: "#FECDCA",
          500: "#D92D20",
          700: "#B42318",
        },
        success: {
          50: "#ECFDF3",
          200: "#ABEFC6",
          500: "#17B26A",
          700: "#067647",
        },
        warn: {
          50: "#FFFAEB",
          200: "#FEDF89",
          500: "#F79009",
          700: "#B54708",
        },
        info: {
          50: "#EFF8FF",
          200: "#B2DDFF",
          500: "#2E90FA",
          700: "#175CD3",
        },
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
      },
      // Surfaces are separated by borders; shadow means "floating above the page".
      boxShadow: {
        card: "0 1px 0 rgba(15, 27, 23, 0.03)",
        raised: "0 4px 12px rgba(15, 27, 23, 0.07), 0 1px 3px rgba(15, 27, 23, 0.05)",
        pop: "0 16px 40px rgba(15, 27, 23, 0.14), 0 2px 8px rgba(15, 27, 23, 0.06)",
        focus: "0 0 0 3px rgba(15, 122, 85, 0.2)",
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
      },
    },
  },
  plugins: [],
};

export default config;
