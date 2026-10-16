"use client";

import Link from "next/link";
import * as React from "react";

import { ChevronRightIcon } from "@/components/icons";
import { cn } from "@/components/ui/primitives";
import { cedis, formatDate } from "@/lib/format";

/**
 * Hand-rolled SVG charts for the admin console.
 *
 * A charting library would add a few hundred kilobytes to serve a handful of
 * graphs. These are plain SVG drawn at the container's real pixel width (so
 * axis text never stretches), coloured from the theme tokens so they work in
 * light and dark, and every one carries a table for screen readers.
 */

/* ------------------------------------------------------------------ */
/* Shared                                                             */
/* ------------------------------------------------------------------ */

/** Series colours, from the theme: each reads on both surfaces. */
export const CHART_COLORS = {
  brand: "rgb(var(--c-brand-500))",
  info: "rgb(var(--c-info-500))",
  warn: "rgb(var(--c-warn-500))",
  danger: "rgb(var(--c-danger-500))",
  gold: "rgb(var(--c-gold-500))",
  muted: "rgb(var(--c-ink-faint))",
  aqua: "#28C7F7",
} as const;

const SHORT_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const LONG_DATE = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

function shortDate(value: string) {
  return SHORT_DATE.format(new Date(`${value}T00:00:00Z`));
}

function longDate(value: string) {
  return LONG_DATE.format(new Date(`${value}T00:00:00Z`));
}

/** A rounded axis maximum and four even steps under it. */
function niceScale(max: number): { max: number; ticks: number[] } {
  if (!Number.isFinite(max) || max <= 0) return { max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] };
  const rough = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? rough;
  const top = step * 4;
  return { max: top, ticks: [0, step, step * 2, step * 3, top] };
}

function compact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}m`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return Number.isInteger(value) ? String(value) : value.toFixed(value < 10 ? 2 : 0);
}

/** The width of an element, kept current. Charts draw at real pixels. */
function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = React.useRef<T>(null);
  const [width, setWidth] = React.useState(0);
  React.useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    setWidth(node.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** A smooth line through the points that never overshoots (monotone cubic). */
function smoothPath(points: { x: number; y: number }[]): string {
  if (points.length === 0) return "";
  if (points.length < 3) return points.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
  const slopes: number[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    slopes.push((points[i + 1].y - points[i].y) / (points[i + 1].x - points[i].x || 1));
  }
  const tangents = points.map((_, i) => {
    if (i === 0) return slopes[0];
    if (i === points.length - 1) return slopes[slopes.length - 1];
    const a = slopes[i - 1];
    const b = slopes[i];
    return a * b <= 0 ? 0 : (a + b) / 2;
  });
  let d = `M${points[0].x},${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i];
    const p1 = points[i + 1];
    const dx = (p1.x - p0.x) / 3;
    d += ` C${p0.x + dx},${p0.y + tangents[i] * dx} ${p1.x - dx},${p1.y - tangents[i + 1] * dx} ${p1.x},${p1.y}`;
  }
  return d;
}

export function Legend({ items, className }: { items: { label: string; color: string; dashed?: boolean }[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-ink-muted", className)}>
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          {item.dashed ? (
            <span aria-hidden className="inline-block w-3 border-t-2 border-dashed" style={{ borderColor: item.color }} />
          ) : (
            <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: item.color }} />
          )}
          {item.label}
        </li>
      ))}
    </ul>
  );
}

function Tooltip({
  x,
  width,
  title,
  rows,
}: {
  x: number;
  width: number;
  title: string;
  rows: { label: string; value: string; color: string }[];
}) {
  // Keep the box inside the chart: flip to the left of the cursor past half-way.
  const right = x > width / 2;
  return (
    <div
      className="pointer-events-none absolute top-0 z-10 min-w-36 rounded-lg border border-white/10 bg-navy/95 px-3 py-2 text-caption text-white shadow-pop backdrop-blur-sm"
      style={right ? { right: width - x + 12 } : { left: x + 12 }}
    >
      <p className="mb-1 font-medium text-white/70">{title}</p>
      {rows.map((row) => (
        <p key={row.label} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-white/80">
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: row.color }} />
            {row.label}
          </span>
          <span className="tabular font-semibold">{row.value}</span>
        </p>
      ))}
    </div>
  );
}

/** Charts are pictures; this is the same data as a table for assistive tech. */
function ScreenReaderTable({
  label,
  dates,
  columns,
}: {
  label: string;
  dates: string[];
  columns: { label: string; values: number[]; format: (value: number) => string }[];
}) {
  return (
    <table className="sr-only">
      <caption>{label}</caption>
      <thead>
        <tr>
          <th scope="col">Date</th>
          {columns.map((column) => (
            <th key={column.label} scope="col">
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {dates.map((date, index) => (
          <tr key={date}>
            <th scope="row">{formatDate(date)}</th>
            {columns.map((column) => (
              <td key={column.label}>{column.format(column.values[index] ?? 0)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
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

/** Which dates get an x-axis label: about one per 90px, always the last. */
function tickIndexes(count: number, width: number): Set<number> {
  const room = Math.max(2, Math.floor(width / 90));
  const every = Math.max(1, Math.ceil(count / room));
  const picked = new Set<number>();
  for (let i = count - 1; i >= 0; i -= every) picked.add(i);
  return picked;
}

/* ------------------------------------------------------------------ */
/* Trend: one or more lines over days                                 */
/* ------------------------------------------------------------------ */

export type TrendSeries = {
  key: string;
  label: string;
  values: number[];
  color: string;
  /** Fill under the line (use on the headline series only). */
  area?: boolean;
  dashed?: boolean;
};

export function TrendChart({
  dates,
  series,
  label,
  height = 240,
  formatValue = (value: number) => compact(value),
  formatAxis = compact,
}: {
  dates: string[];
  series: TrendSeries[];
  label: string;
  height?: number;
  formatValue?: (value: number) => string;
  formatAxis?: (value: number) => string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = React.useState<number | null>(null);
  const gradientId = React.useId().replace(/:/g, "");

  const empty = dates.length === 0 || series.every((s) => s.values.every((v) => v === 0));
  const { max, ticks } = niceScale(Math.max(...series.flatMap((s) => s.values), 0));
  const min = Math.min(0, ...series.flatMap((s) => s.values));

  const axisWidth = 44;
  const pad = { top: 12, right: 8, bottom: 26, left: axisWidth };
  const innerW = Math.max(width - pad.left - pad.right, 1);
  const innerH = height - pad.top - pad.bottom;
  const span = max - min || 1;
  const x = (i: number) => pad.left + (dates.length > 1 ? (i / (dates.length - 1)) * innerW : innerW / 2);
  const y = (v: number) => pad.top + innerH - ((v - min) / span) * innerH;
  const ticksShown = tickIndexes(dates.length, innerW);

  function onMove(event: React.PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / box.width;
    setHover(Math.min(dates.length - 1, Math.max(0, Math.round(ratio * (dates.length - 1)))));
  }

  return (
    <figure className="relative" ref={ref}>
      {empty ? (
        <EmptyChart label={label} height={height} />
      ) : width > 0 ? (
        <svg width={width} height={height} role="img" aria-label={label} className="block overflow-visible">
          <defs>
            {series
              .filter((s) => s.area)
              .map((s) => (
                <linearGradient key={s.key} id={`${gradientId}-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity="0.28" />
                  <stop offset="100%" stopColor={s.color} stopOpacity="0" />
                </linearGradient>
              ))}
          </defs>

          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y(tick)}
                y2={y(tick)}
                className={tick === 0 ? "stroke-line-strong" : "stroke-line"}
                strokeDasharray={tick === 0 ? undefined : "3 4"}
              />
              <text x={pad.left - 8} y={y(tick)} dy="0.32em" textAnchor="end" className="fill-ink-faint text-[10px]">
                {formatAxis(tick)}
              </text>
            </g>
          ))}

          {dates.map((date, i) =>
            ticksShown.has(i) ? (
              <text key={date} x={x(i)} y={height - 6} textAnchor="middle" className="fill-ink-faint text-[10px]">
                {shortDate(date)}
              </text>
            ) : null,
          )}

          {series.map((s) => {
            const points = s.values.map((v, i) => ({ x: x(i), y: y(v) }));
            const line = smoothPath(points);
            return (
              <g key={s.key}>
                {s.area ? (
                  <path
                    d={`${line} L${points[points.length - 1].x},${y(0)} L${points[0].x},${y(0)} Z`}
                    fill={`url(#${gradientId}-${s.key})`}
                  />
                ) : null}
                <path
                  d={line}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={s.area ? 2.25 : 1.75}
                  strokeDasharray={s.dashed ? "5 4" : undefined}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </g>
            );
          })}

          {hover !== null ? (
            <g>
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={pad.top}
                y2={pad.top + innerH}
                className="stroke-ink-faint"
                strokeDasharray="3 3"
              />
              {series.map((s) => (
                <circle
                  key={s.key}
                  cx={x(hover)}
                  cy={y(s.values[hover] ?? 0)}
                  r={4}
                  fill={s.color}
                  className="stroke-surface"
                  strokeWidth={2}
                />
              ))}
            </g>
          ) : null}

          <rect
            x={pad.left}
            y={0}
            width={innerW}
            height={height}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          />
        </svg>
      ) : (
        <div style={{ height }} />
      )}

      {hover !== null && !empty ? (
        <Tooltip
          x={x(hover)}
          width={width}
          title={longDate(dates[hover])}
          rows={series.map((s) => ({ label: s.label, value: formatValue(s.values[hover] ?? 0), color: s.color }))}
        />
      ) : null}

      <ScreenReaderTable
        label={label}
        dates={dates}
        columns={series.map((s) => ({ label: s.label, values: s.values, format: formatValue }))}
      />
    </figure>
  );
}

/* ------------------------------------------------------------------ */
/* Stacked bars: outcomes per day                                     */
/* ------------------------------------------------------------------ */

export function StackedBars({
  dates,
  series,
  label,
  height = 240,
  formatValue = (value: number) => String(value),
}: {
  dates: string[];
  series: { key: string; label: string; values: number[]; color: string }[];
  label: string;
  height?: number;
  formatValue?: (value: number) => string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = React.useState<number | null>(null);

  const totals = dates.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0));
  const empty = totals.every((t) => t === 0);
  const { max, ticks } = niceScale(Math.max(...totals, 0));

  const pad = { top: 12, right: 8, bottom: 26, left: 36 };
  const innerW = Math.max(width - pad.left - pad.right, 1);
  const innerH = height - pad.top - pad.bottom;
  const slot = innerW / Math.max(dates.length, 1);
  const barW = Math.max(Math.min(slot * 0.62, 28), 2);
  const y = (v: number) => pad.top + innerH - (v / max) * innerH;
  const ticksShown = tickIndexes(dates.length, innerW);

  return (
    <figure className="relative" ref={ref}>
      {empty ? (
        <EmptyChart label={label} height={height} />
      ) : width > 0 ? (
        <svg width={width} height={height} role="img" aria-label={label} className="block">
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y(tick)}
                y2={y(tick)}
                className={tick === 0 ? "stroke-line-strong" : "stroke-line"}
                strokeDasharray={tick === 0 ? undefined : "3 4"}
              />
              <text x={pad.left - 8} y={y(tick)} dy="0.32em" textAnchor="end" className="fill-ink-faint text-[10px]">
                {compact(tick)}
              </text>
            </g>
          ))}
          {dates.map((date, i) => {
            const cx = pad.left + slot * i + slot / 2;
            let base = 0;
            const visible = series.filter((s) => (s.values[i] ?? 0) > 0);
            return (
              <g key={date} opacity={hover === null || hover === i ? 1 : 0.45}>
                {visible.map((s, index) => {
                  const value = s.values[i] ?? 0;
                  const top = y(base + value);
                  const h = y(base) - top;
                  base += value;
                  const isTop = index === visible.length - 1;
                  return (
                    <rect
                      key={s.key}
                      x={cx - barW / 2}
                      y={top}
                      width={barW}
                      height={Math.max(h - (isTop ? 0 : 1), 0.5)}
                      rx={isTop ? Math.min(4, barW / 3) : 0}
                      fill={s.color}
                    />
                  );
                })}
                {ticksShown.has(i) ? (
                  <text x={cx} y={height - 6} textAnchor="middle" className="fill-ink-faint text-[10px]">
                    {shortDate(date)}
                  </text>
                ) : null}
                <rect
                  x={pad.left + slot * i}
                  y={0}
                  width={slot}
                  height={height}
                  fill="transparent"
                  onPointerEnter={() => setHover(i)}
                  onPointerLeave={() => setHover(null)}
                />
              </g>
            );
          })}
        </svg>
      ) : (
        <div style={{ height }} />
      )}

      {hover !== null && !empty ? (
        <Tooltip
          x={pad.left + slot * hover + slot / 2}
          width={width}
          title={`${longDate(dates[hover])} · ${formatValue(totals[hover])} total`}
          rows={series.map((s) => ({ label: s.label, value: formatValue(s.values[hover] ?? 0), color: s.color }))}
        />
      ) : null}

      <ScreenReaderTable
        label={label}
        dates={dates}
        columns={series.map((s) => ({ label: s.label, values: s.values, format: formatValue }))}
      />
    </figure>
  );
}

/* ------------------------------------------------------------------ */
/* Donut: shares of a whole                                           */
/* ------------------------------------------------------------------ */

export function Donut({
  segments,
  label,
  centerLabel,
  centerValue,
  size = 168,
  formatValue = (value: number) => String(value),
}: {
  segments: { label: string; value: number; color: string }[];
  label: string;
  centerLabel: string;
  centerValue: string;
  size?: number;
  formatValue?: (value: number) => string;
}) {
  const [hover, setHover] = React.useState<number | null>(null);
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const stroke = 18;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const gap = segments.filter((s) => s.value > 0).length > 1 ? 3 : 0;

  let offset = 0;
  const arcs = segments.map((segment) => {
    const length = total ? (segment.value / total) * circumference : 0;
    const arc = { ...segment, length: Math.max(length - gap, 0), offset };
    offset += length;
    return arc;
  });
  const focused = hover === null ? null : segments[hover];

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke} className="stroke-sunken" />
          {total
            ? arcs.map((arc, index) =>
                arc.length > 0 ? (
                  <circle
                    key={arc.label}
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke={arc.color}
                    strokeWidth={hover === index ? stroke + 4 : stroke}
                    strokeDasharray={`${arc.length} ${circumference - arc.length}`}
                    strokeDashoffset={-arc.offset}
                    strokeLinecap="butt"
                    className="transition-[stroke-width] duration-150"
                    opacity={hover === null || hover === index ? 1 : 0.4}
                    onPointerEnter={() => setHover(index)}
                    onPointerLeave={() => setHover(null)}
                  />
                ) : null,
              )
            : null}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="tabular text-title text-ink">
            {focused ? (total ? `${Math.round((focused.value / total) * 100)}%` : "0%") : centerValue}
          </span>
          <span className="max-w-26 truncate text-caption text-ink-muted">{focused ? focused.label : centerLabel}</span>
        </div>
      </div>
      <ul className="w-full min-w-0 space-y-2">
        {segments.map((segment, index) => (
          <li
            key={segment.label}
            className={cn(
              "flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm transition-colors",
              hover === index && "bg-sunken",
            )}
            onPointerEnter={() => setHover(index)}
            onPointerLeave={() => setHover(null)}
          >
            <span className="flex min-w-0 items-center gap-2">
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: segment.color }} />
              <span className="truncate text-ink-soft">{segment.label}</span>
            </span>
            <span className="tabular shrink-0 font-medium text-ink">
              {formatValue(segment.value)}
              <span className="ml-1.5 text-caption font-normal text-ink-faint">
                {total ? `${Math.round((segment.value / total) * 100)}%` : "0%"}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Sparkline and stat cards                                           */
/* ------------------------------------------------------------------ */

export function Sparkline({
  values,
  color = CHART_COLORS.brand,
  height = 36,
  className,
}: {
  values: number[];
  color?: string;
  height?: number;
  className?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const id = React.useId().replace(/:/g, "");
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const points = values.map((v, i) => ({
    x: values.length > 1 ? (i / (values.length - 1)) * width : width / 2,
    y: 2 + (height - 4) - ((v - min) / span) * (height - 4),
  }));
  const line = smoothPath(points);
  return (
    <div ref={ref} className={cn("w-full", className)} style={{ height }} aria-hidden>
      {width > 0 && values.length > 1 ? (
        <svg width={width} height={height} className="block overflow-visible">
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.25" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${id})`} />
          <path d={line} fill="none" stroke={color} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : null}
    </div>
  );
}

/** Percentage change against the previous period, or null when it has no meaning. */
export function percentChange(current: number, previous: number): number | null {
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null;
  if (previous === 0) return current === 0 ? 0 : null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

export function Delta({
  current,
  previous,
  invert = false,
  unit = "%",
  points = false,
}: {
  current: number;
  previous: number;
  /** Up is bad (failures, refunds). */
  invert?: boolean;
  unit?: string;
  /** Show the difference in points (for rates) rather than a percentage change. */
  points?: boolean;
}) {
  const change = points ? current - previous : percentChange(current, previous);
  if (change === null) {
    return (
      <span className="inline-flex items-center rounded-md bg-info-50 px-1.5 py-0.5 text-2xs font-semibold text-info-700">
        New
      </span>
    );
  }
  const flat = Math.abs(change) < 0.05;
  const good = invert ? change < 0 : change > 0;
  const tone = flat ? "bg-sunken text-ink-muted" : good ? "bg-success-50 text-success-700" : "bg-danger-50 text-danger-700";
  return (
    <span className={cn("tabular inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-2xs font-semibold", tone)}>
      {flat ? null : (
        <svg viewBox="0 0 12 12" className={cn("h-2.5 w-2.5", change < 0 && "rotate-180")} aria-hidden>
          <path d="M6 2.5 10 8H2z" fill="currentColor" />
        </svg>
      )}
      {flat ? "0" : Math.abs(change).toFixed(Math.abs(change) >= 100 ? 0 : 1)}
      {points ? " pts" : unit}
      <span className="sr-only">{flat ? " no change" : change > 0 ? " up" : " down"} on the previous period</span>
    </span>
  );
}

export function StatCard({
  label,
  value,
  icon,
  delta,
  spark,
  sparkColor,
  footnote,
  href,
  className,
}: {
  label: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  delta?: React.ReactNode;
  spark?: number[];
  sparkColor?: string;
  footnote?: React.ReactNode;
  href?: string;
  className?: string;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p className="flex min-w-0 items-center gap-2 text-caption font-medium text-ink-muted">
          {icon ? (
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700 [&_svg]:h-4 [&_svg]:w-4">
              {icon}
            </span>
          ) : null}
          <span className="truncate">{label}</span>
        </p>
        {href ? <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" /> : null}
      </div>
      <div className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <p className="tabular truncate text-[1.625rem] font-semibold leading-8 tracking-tight text-ink">{value}</p>
        {delta}
      </div>
      {footnote ? <p className="mt-1 truncate text-caption text-ink-muted">{footnote}</p> : null}
      {spark ? <Sparkline values={spark} color={sparkColor} className="mt-3" /> : null}
    </>
  );
  const classes = cn("stat-card group block p-4 sm:p-5", className);
  return href ? (
    <Link href={href} className={cn(classes, "transition-shadow hover:shadow-raised")}>
      {body}
    </Link>
  ) : (
    <div className={classes}>{body}</div>
  );
}

/* ------------------------------------------------------------------ */
/* The earlier, simpler charts - still used on other admin screens     */
/* ------------------------------------------------------------------ */

type Series = { date: string; value: number; label?: string }[];

export function AreaChart({
  series,
  height = 200,
  formatValue = (value: number) => String(value),
  label,
}: {
  series: Series;
  height?: number;
  formatValue?: (value: number) => string;
  label: string;
}) {
  return (
    <TrendChart
      dates={series.map((point) => point.date)}
      series={[{ key: "value", label, values: series.map((point) => point.value), color: CHART_COLORS.brand, area: true }]}
      label={label}
      height={height}
      formatValue={formatValue}
    />
  );
}

export function BarChart({
  series,
  height = 200,
  label,
  formatValue = (value: number) => String(value),
}: {
  series: Series;
  height?: number;
  label: string;
  formatValue?: (value: number) => string;
}) {
  return (
    <StackedBars
      dates={series.map((point) => point.date)}
      series={[{ key: "value", label, values: series.map((point) => point.value), color: CHART_COLORS.brand }]}
      label={label}
      height={height}
      formatValue={formatValue}
    />
  );
}

export function RankedBars({
  rows,
  formatValue,
  color = CHART_COLORS.brand,
}: {
  rows: { label: string; value: number; secondary?: string }[];
  formatValue?: (value: number) => string;
  color?: string;
}) {
  if (rows.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-ink-muted">No data yet.</p>;
  }
  const max = Math.max(...rows.map((row) => row.value), 1);

  return (
    <ol className="space-y-3.5">
      {rows.map((row, index) => (
        <li key={row.label} className="flex items-center gap-3">
          <span
            className={cn(
              "tabular flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-2xs font-semibold",
              index < 3 ? "bg-brand-50 text-brand-700" : "bg-sunken text-ink-muted",
            )}
          >
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate font-medium text-ink">{row.label}</span>
              <span className="tabular shrink-0 text-ink-muted">
                {formatValue ? formatValue(row.value) : row.value}
                {row.secondary ? <span className="ml-2 text-ink-faint">{row.secondary}</span> : null}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full rounded-full transition-[width] duration-500 ease-out"
                style={{ width: `${(row.value / max) * 100}%`, background: color, opacity: 1 - index * 0.06 }}
              />
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function MetricTile({
  label,
  value,
  sublabel,
  tone = "default",
  href,
  className,
}: {
  label: string;
  value: React.ReactNode;
  sublabel?: React.ReactNode;
  tone?: "default" | "positive" | "negative";
  /** Where the figure is broken down, when there is such a screen. */
  href?: string;
  className?: string;
}) {
  const body = (
    <>
      <p className="flex items-center justify-between gap-2 text-caption font-medium text-ink-muted">
        {label}
        {href ? (
          <ChevronRightIcon className="h-3.5 w-3.5 text-ink-faint transition-transform group-hover:translate-x-0.5" />
        ) : null}
      </p>
      <p
        className={cn(
          "tabular mt-1.5 truncate text-title tracking-tight",
          tone === "positive" ? "text-success-700" : tone === "negative" ? "text-danger-700" : "text-ink",
        )}
      >
        {value}
      </p>
      {sublabel ? <p className="mt-0.5 text-caption text-ink-muted">{sublabel}</p> : null}
    </>
  );
  return href ? (
    <Link href={href} className={cn("card group block p-4 transition-colors hover:bg-sunken/60", className)}>
      {body}
    </Link>
  ) : (
    <div className={cn("card p-4", className)}>{body}</div>
  );
}

export { cedis };
