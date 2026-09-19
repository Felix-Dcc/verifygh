"use client";

import * as React from "react";

import { cn } from "@/components/ui/primitives";
import { cedis, formatDate } from "@/lib/format";

/**
 * Hand-rolled SVG charts.
 *
 * A charting library would add a few hundred kilobytes to serve six small
 * graphs. These are plain SVG: they scale, they print, they respect the theme,
 * and they carry a table fallback for screen readers.
 */

type Series = { date: string; value: number; label?: string }[];

function niceMax(values: number[]): number {
  const max = Math.max(...values, 0);
  if (max === 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  return Math.ceil(max / magnitude) * magnitude;
}

export function AreaChart({
  series,
  height = 180,
  formatValue = (value: number) => String(value),
  label,
}: {
  series: Series;
  height?: number;
  formatValue?: (value: number) => string;
  label: string;
}) {
  const [hover, setHover] = React.useState<number | null>(null);

  if (series.length === 0) {
    return <EmptyChart label={label} height={height} />;
  }

  const width = 600;
  const padding = { top: 10, right: 4, bottom: 22, left: 4 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const max = niceMax(series.map((point) => point.value));

  const step = series.length > 1 ? innerWidth / (series.length - 1) : 0;
  const points = series.map((point, index) => ({
    x: padding.left + index * step,
    y: padding.top + innerHeight - (point.value / max) * innerHeight,
    ...point,
  }));

  const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x},${point.y}`).join(" ");
  const area = `${line} L${points[points.length - 1].x},${padding.top + innerHeight} L${points[0].x},${padding.top + innerHeight} Z`;

  const active = hover === null ? null : points[hover];

  return (
    <figure className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={label}
        preserveAspectRatio="none"
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0F7A55" stopOpacity="0.20" />
            <stop offset="100%" stopColor="#0F7A55" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {[0.25, 0.5, 0.75].map((fraction) => (
          <line
            key={fraction}
            x1={padding.left}
            x2={width - padding.right}
            y1={padding.top + innerHeight * fraction}
            y2={padding.top + innerHeight * fraction}
            stroke="#E3E8E5"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        <path d={area} fill="url(#area-fill)" />
        <path
          d={line}
          fill="none"
          stroke="#0B6446"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {points.map((point, index) => (
          <rect
            key={point.date}
            x={point.x - step / 2}
            y={0}
            width={Math.max(step, 8)}
            height={height}
            fill="transparent"
            onMouseEnter={() => setHover(index)}
          />
        ))}

        {active ? (
          <>
            <line
              x1={active.x}
              x2={active.x}
              y1={padding.top}
              y2={padding.top + innerHeight}
              stroke="#0B6446"
              strokeWidth="1"
              strokeDasharray="3 3"
              vectorEffect="non-scaling-stroke"
            />
            <circle cx={active.x} cy={active.y} r="4" fill="#0B6446" stroke="white" strokeWidth="2" />
          </>
        ) : null}
      </svg>

      {active ? (
        <div
          className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 rounded-lg bg-ink px-2.5 py-1.5 text-xs text-white shadow-pop"
          style={{ left: `${(active.x / width) * 100}%` }}
        >
          <p className="font-semibold">{formatValue(active.value)}</p>
          <p className="opacity-70">{formatDate(active.date)}</p>
        </div>
      ) : null}

      <figcaption className="mt-1 flex justify-between text-2xs text-ink-faint">
        <span>{formatDate(series[0].date)}</span>
        <span>{formatDate(series[series.length - 1].date)}</span>
      </figcaption>

      <VisuallyHiddenTable label={label} series={series} formatValue={formatValue} />
    </figure>
  );
}

export function BarChart({
  series,
  height = 180,
  label,
  formatValue = (value: number) => String(value),
}: {
  series: Series;
  height?: number;
  label: string;
  formatValue?: (value: number) => string;
}) {
  if (series.length === 0) return <EmptyChart label={label} height={height} />;

  const max = niceMax(series.map((point) => point.value));

  return (
    <figure>
      <div className="flex items-end gap-1" style={{ height }} role="img" aria-label={label}>
        {series.map((point) => (
          <div key={point.date} className="group flex flex-1 flex-col items-center justify-end">
            <span className="mb-1 text-2xs font-medium text-ink opacity-0 transition-opacity group-hover:opacity-100">
              {formatValue(point.value)}
            </span>
            <div
              className="w-full rounded-t bg-brand-500/85 transition-colors group-hover:bg-brand-600"
              style={{ height: `${Math.max((point.value / max) * 100, point.value > 0 ? 2 : 0)}%` }}
            />
          </div>
        ))}
      </div>
      <figcaption className="mt-1 flex justify-between text-2xs text-ink-faint">
        <span>{formatDate(series[0].date)}</span>
        <span>{formatDate(series[series.length - 1].date)}</span>
      </figcaption>
      <VisuallyHiddenTable label={label} series={series} formatValue={formatValue} />
    </figure>
  );
}

export function RankedBars({
  rows,
  formatValue,
}: {
  rows: { label: string; value: number; secondary?: string }[];
  formatValue?: (value: number) => string;
}) {
  if (rows.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-ink-muted">No data yet.</p>;
  }
  const max = Math.max(...rows.map((row) => row.value), 1);

  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={row.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate font-medium text-ink">{row.label}</span>
            <span className="tabular shrink-0 text-ink-muted">
              {formatValue ? formatValue(row.value) : row.value}
              {row.secondary ? (
                <span className="ml-2 text-ink-faint">{row.secondary}</span>
              ) : null}
            </span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-line/60">
            <div
              className="h-full rounded-full bg-brand-500"
              style={{ width: `${(row.value / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function EmptyChart({ label, height }: { label: string; height: number }) {
  return (
    <div
      className="flex items-center justify-center rounded-xl border border-dashed border-line text-sm text-ink-muted"
      style={{ height }}
    >
      No {label.toLowerCase()} to show yet.
    </div>
  );
}

/** Charts are pictures; this is the same data as a table for assistive tech. */
function VisuallyHiddenTable({
  label,
  series,
  formatValue,
}: {
  label: string;
  series: Series;
  formatValue: (value: number) => string;
}) {
  return (
    <table className="sr-only">
      <caption>{label}</caption>
      <thead>
        <tr>
          <th scope="col">Date</th>
          <th scope="col">Value</th>
        </tr>
      </thead>
      <tbody>
        {series.map((point) => (
          <tr key={point.date}>
            <th scope="row">{formatDate(point.date)}</th>
            <td>{formatValue(point.value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function MetricTile({
  label,
  value,
  sublabel,
  tone = "default",
  className,
}: {
  label: string;
  value: React.ReactNode;
  sublabel?: React.ReactNode;
  tone?: "default" | "positive" | "negative";
  className?: string;
}) {
  return (
    <div className={cn("card p-4", className)}>
      <p className="text-xs text-ink-muted">{label}</p>
      <p
        className={cn(
          "tabular mt-1 text-2xl font-semibold tracking-tight",
          tone === "positive" ? "text-success-700" : tone === "negative" ? "text-danger-700" : "text-ink",
        )}
      >
        {value}
      </p>
      {sublabel ? <p className="mt-1 text-xs text-ink-muted">{sublabel}</p> : null}
    </div>
  );
}

export { cedis };
