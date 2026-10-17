import * as React from "react";

import { cn } from "@/components/ui/primitives";

/**
 * The navy panel at the top of an app page - the homepage's night, carried
 * into the product: the page's title and the few facts and actions that
 * matter most, in white on navy, with the dawn line along the bottom edge.
 * The rest of the page stays light.
 *
 * Headings inside set `text-white` themselves (the base styles colour h1-h3
 * with text-ink). Buttons on it use the `onBand` / `onBandOutline` / `dawn`
 * variants; secondary text is white at /70, small print no lower than /60.
 */
export function AppHero({
  eyebrow,
  title,
  description,
  actions,
  aside,
  children,
  className,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** The right-hand side from lg (stats, a visual); below the text on phones. */
  aside?: React.ReactNode;
  /** Anything else under the title, full width (a search box, a balance). */
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        // `dark`: anything token-coloured inside (a skeleton, an error) takes
        // the dark theme's colours, which read on navy.
        "app-hero dark relative overflow-hidden rounded-3xl px-5 py-6 text-white shadow-[0_30px_60px_-35px_rgba(5,11,24,0.8)] ring-1 ring-white/5 sm:px-8 sm:py-8",
        className,
      )}
    >
      <div className={cn("relative grid grid-cols-1 gap-6", aside ? "lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] lg:items-center lg:gap-10" : "")}>
        <div className="min-w-0">
          {eyebrow ? <p className="text-caption font-medium text-white/60">{eyebrow}</p> : null}
          <h1 className={cn("text-balance text-2xl font-extrabold tracking-[-0.03em] text-white sm:text-3xl", eyebrow && "mt-1")}>
            {title}
          </h1>
          {description ? (
            <p className="mt-2 max-w-xl text-pretty text-sm leading-relaxed text-white/70 sm:text-base">{description}</p>
          ) : null}
          {children}
          {actions ? <div className="mt-6 flex flex-wrap gap-2.5">{actions}</div> : null}
        </div>
        {aside ? <div className="min-w-0">{aside}</div> : null}
      </div>
      {/* The dawn line */}
      <span
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-[3px] bg-linear-to-r from-azure via-aqua to-leaf opacity-80"
      />
    </section>
  );
}

/** A figure on the navy panel: a quiet label over a white number. */
export function HeroStat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col rounded-2xl border border-white/10 bg-white/6 p-3 backdrop-blur-sm sm:p-4", className)}>
      {/* A size down on phones, where three tiles share a row. */}
      <p className="text-2xs text-white/60 sm:text-caption">{label}</p>
      {/* A div, not a p: the value may be a loading skeleton (a block). mt-auto
          keeps values level across a row when one label wraps. */}
      <div className="tabular mt-auto pt-1 text-lg font-bold tracking-tight text-white sm:text-xl">{value}</div>
      {hint ? <p className="mt-0.5 text-2xs text-white/60">{hint}</p> : null}
    </div>
  );
}

/** A big cedi amount on navy: "GH₵" small and quiet, the figure large. */
export function HeroAmount({ value }: { value: string }) {
  const match = value.match(/^(−?)(GH₵)\s?(.*)$/);
  if (!match) return <span className="tabular text-4xl font-extrabold tracking-tight text-white sm:text-5xl">{value}</span>;
  const [, sign, currency, figure] = match;
  return (
    <span className="tabular inline-flex items-baseline gap-2 text-white">
      <span className="text-xl font-semibold text-white/60 sm:text-2xl">
        {sign}
        {currency}
      </span>
      <span className="text-4xl font-extrabold tracking-[-0.03em] sm:text-5xl">{figure}</span>
    </span>
  );
}
