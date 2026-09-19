import type { Config } from "tailwindcss";

/**
 * VerifyGH design tokens.
 *
 * The palette is deliberately restrained: a deep Ghanaian green as the single
 * brand colour, a muted gold used only as an accent, and a warm neutral scale
 * for everything else. No neon, no gradients-as-decoration - this has to read
 * as a payments company, not a temporary-number site.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F7F9F8",
        surface: "#FFFFFF",
        ink: {
          DEFAULT: "#0F1B17",
          soft: "#3D4B45",
          muted: "#6B7A73",
          faint: "#9AA6A0",
        },
        line: {
          DEFAULT: "#E3E8E5",
          strong: "#CBD4CF",
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
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI Variable Display",
          "Segoe UI",
          "Inter",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Cascadia Mono",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
      },
      borderRadius: {
        lg: "0.625rem",
        xl: "0.875rem",
        "2xl": "1.125rem",
        "3xl": "1.5rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 27, 23, 0.04), 0 1px 3px rgba(15, 27, 23, 0.06)",
        raised: "0 4px 12px rgba(15, 27, 23, 0.06), 0 1px 3px rgba(15, 27, 23, 0.04)",
        pop: "0 12px 32px rgba(15, 27, 23, 0.12), 0 2px 8px rgba(15, 27, 23, 0.06)",
        focus: "0 0 0 3px rgba(15, 122, 85, 0.18)",
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
      },
      animation: {
        "fade-in": "fade-in 180ms ease-out",
        "slide-up": "slide-up 220ms cubic-bezier(0.16, 1, 0.3, 1)",
        shimmer: "shimmer 1.6s infinite",
        "pulse-ring": "pulse-ring 1.8s cubic-bezier(0.24, 0, 0.38, 1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
