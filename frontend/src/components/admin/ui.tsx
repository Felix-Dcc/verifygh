"use client";

import * as React from "react";

import { CloseIcon, RefreshIcon, SearchIcon } from "@/components/icons";
import { Card, Input, Skeleton, cn } from "@/components/ui/primitives";

/**
 * The admin console's shared page furniture, so every list page reads the same
 * way: banner, figures, one sticky bar of filters, then the list.
 */

/**
 * Filters and search in one bar. On a page it stays in reach while the list
 * scrolls; `inset` is the same bar inside a card, where it does not float.
 */
export function AdminToolbar({
  children,
  inset = false,
  className,
}: {
  children: React.ReactNode;
  inset?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "z-20 flex flex-col gap-3 rounded-2xl border border-line p-2.5 lg:flex-row lg:items-center",
        inset
          ? "bg-sunken/40"
          : // Below the top bar, above the table's own header.
            "-mx-1 bg-surface/90 shadow-[0_10px_30px_-20px_rgba(5,11,24,0.6)] backdrop-blur supports-[backdrop-filter]:bg-surface/75 lg:sticky lg:top-16",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** A search field with a clear button. */
export function SearchBox({
  value,
  onChange,
  placeholder,
  label,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
  className?: string;
}) {
  return (
    <div className={cn("relative lg:w-80", className)}>
      <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
      <Input
        type="search"
        aria-label={label}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && value) {
            event.preventDefault();
            onChange("");
          }
        }}
        className="pl-11 pr-10 [&::-webkit-search-cancel-button]:hidden"
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear search"
          className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-sunken hover:text-ink"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}

/** The card around a list: what it holds, how many, and a refresh. */
export function ListCard({
  title,
  count,
  noun,
  refreshing,
  onRefresh,
  action,
  children,
  className,
}: {
  title: string;
  count?: number;
  noun?: string;
  refreshing?: boolean;
  onRefresh?: () => void;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
          {count !== undefined ? (
            <span className="tabular shrink-0 rounded-full bg-sunken px-2 py-0.5 text-caption font-medium text-ink-muted">
              {count.toLocaleString()} {noun}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {action}
          {onRefresh ? (
            <button
              type="button"
              onClick={onRefresh}
              aria-label="Refresh"
              title="Refresh"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
            >
              <RefreshIcon className={cn("h-4 w-4", refreshing && "animate-spin")} />
            </button>
          ) : null}
        </div>
      </div>
      {children}
    </Card>
  );
}

const KPI_TONES = {
  brand: "bg-brand-50 text-brand-700",
  info: "bg-info-50 text-info-700",
  warn: "bg-warn-50 text-warn-700",
  danger: "bg-danger-50 text-danger-700",
  gold: "bg-gold-100 text-gold-700",
  neutral: "bg-sunken text-ink-soft",
} as const;

/**
 * One figure at the top of a page. Given `onClick`, it is also a shortcut to
 * the filter that shows those records - `active` while that filter is on.
 */
export function KpiCard({
  icon,
  label,
  value,
  hint,
  tone = "brand",
  onClick,
  active,
}: {
  icon: React.ReactNode;
  label: string;
  value?: React.ReactNode;
  hint?: React.ReactNode;
  tone?: keyof typeof KPI_TONES;
  onClick?: () => void;
  active?: boolean;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p className="line-clamp-2 text-caption font-medium leading-snug text-ink-muted">{label}</p>
        <span
          aria-hidden
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg [&_svg]:h-4 [&_svg]:w-4",
            KPI_TONES[tone],
          )}
        >
          {icon}
        </span>
      </div>
      {value === undefined ? (
        <Skeleton className="mt-2 h-7 w-20" />
      ) : (
        <div className="tabular mt-1.5 truncate text-[1.5rem] font-bold leading-8 tracking-tight text-ink">{value}</div>
      )}
      {hint ? <p className="mt-0.5 truncate text-caption text-ink-muted">{hint}</p> : null}
    </>
  );
  const classes = cn(
    "stat-card block w-full p-4 text-left",
    onClick && "transition-shadow hover:shadow-raised focus-visible:shadow-raised",
    active && "ring-2 ring-primary/70",
  );
  return onClick ? (
    <button type="button" onClick={onClick} aria-pressed={active} className={classes}>
      {body}
    </button>
  ) : (
    <div className={classes}>{body}</div>
  );
}

export function KpiRow({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>;
}

/**
 * A table row that opens something: by click, and by Enter or Space for
 * keyboard users - a bare onClick on a <tr> cannot be reached by keyboard.
 */
export function openRow(open: () => void, label: string) {
  return {
    onClick: open,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    },
    tabIndex: 0,
    "aria-label": label,
    className: "admin-row cursor-pointer",
  };
}

/** Skeleton rows in the shape of a table, while it loads. */
export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <ul className="divide-y divide-line" aria-busy>
      {Array.from({ length: rows }).map((_, index) => (
        <li key={index} className="flex items-center gap-4 px-5 py-3.5">
          <Skeleton className="h-9 w-9 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-24" />
          </div>
          <Skeleton className="hidden h-4 w-20 sm:block" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </li>
      ))}
    </ul>
  );
}
