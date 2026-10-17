"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { AppHero, HeroStat } from "@/components/app-hero";
import { CountryFlag } from "@/components/country-flag";
import { ChevronRightIcon, SearchIcon } from "@/components/icons";
import { PhoneMessageArt, SearchArt } from "@/components/illustrations";
import { OrderStatusRow } from "@/components/orders/order-row";
import { ServiceLogo } from "@/components/service-logo";
import {
  Button,
  ButtonLink,
  Card,
  EmptyState,
  LoadError,
  Skeleton,
  StatusBadge,
  cn,
} from "@/components/ui/primitives";
import { cedis, dayGroup, formatDateTime, groupInternational } from "@/lib/format";
import type { OrderSummary, Paginated, WalletSummary } from "@/lib/types";

type Filter = "all" | "active" | "completed" | "failed" | "refunded";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "refunded", label: "Refunded" },
];

const isFilter = (value: string | null): value is Filter =>
  FILTERS.some((option) => option.value === value);

export default function OrdersPage() {
  // useSearchParams needs a boundary, or the page cannot be prerendered.
  return (
    <React.Suspense fallback={<ListSkeleton />}>
      <Orders />
    </React.Suspense>
  );
}

/**
 * Orders: every number bought and how it turned out, grouped by day - rows on
 * a phone, aligned columns from md. The counts on the panel are the wallet
 * summary's own; the list is the server's, filtered and searched there.
 */
function Orders() {
  const router = useRouter();
  const params = useSearchParams();
  // The dashboard links straight to a filter ("/orders?filter=active").
  const initial = params.get("filter");
  const [filter, setFilter] = React.useState<Filter>(isFilter(initial) ? initial : "all");
  const [search, setSearch] = React.useState("");
  const [page, setPage] = React.useState(1);

  // Debounced so typing a reference does not fire a request per keystroke.
  const [debouncedSearch, setDebouncedSearch] = React.useState("");
  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading, error, mutate } = useSWR<Paginated<OrderSummary>>([
    "/orders/",
    { filter: filter === "all" ? "" : filter, search: debouncedSearch, page, page_size: 20 },
  ]);
  const summary = useSWR<WalletSummary>("/wallet/summary/");

  const orders = React.useMemo(() => data?.results ?? [], [data]);
  const pagination = data?.pagination;
  const filterLabel = FILTERS.find((option) => option.value === filter)?.label.toLowerCase();

  // Today / Yesterday / Earlier, in the order the server sent them.
  const groups = React.useMemo(() => {
    const out: { label: string; orders: OrderSummary[] }[] = [];
    for (const order of orders) {
      const label = dayGroup(order.created_at);
      const last = out[out.length - 1];
      if (last && last.label === label) last.orders.push(order);
      else out.push({ label, orders: [order] });
    }
    return out;
  }, [orders]);

  function changeFilter(value: Filter) {
    setFilter(value);
    setPage(1);
    router.replace(value === "all" ? "/orders" : `/orders?filter=${value}`, { scroll: false });
  }

  const stat = (value: number | undefined) =>
    summary.isLoading ? <Skeleton className="mt-1 h-6 w-10" /> : summary.error && !summary.data ? "—" : (value ?? 0);

  return (
    <div className="space-y-6">
      <AppHero
        title="Orders"
        description="Every number you have bought, and how each one turned out."
        actions={
          <ButtonLink href="/services" variant="onBand">
            Buy a number
          </ButtonLink>
        }
        aside={
          <div className="grid grid-cols-3 gap-2 sm:gap-2.5">
            <HeroStat label="In progress" value={stat(summary.data?.active_orders)} />
            <HeroStat label="Completed" value={stat(summary.data?.successful_orders)} />
            <HeroStat label="All orders" value={stat(summary.data?.total_orders)} />
          </div>
        }
      />

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div
          role="group"
          aria-label="Show"
          className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 md:mx-0 md:px-0"
        >
          {FILTERS.map((option) => {
            const active = filter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => changeFilter(option.value)}
                className={cn(
                  "min-h-11 shrink-0 rounded-full px-4 text-sm font-semibold transition-colors md:min-h-9",
                  active ? "bg-ink text-canvas shadow-card" : "border border-line bg-surface text-ink-soft hover:border-line-strong hover:text-ink",
                )}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        <label className="relative block md:w-72">
          <span className="sr-only">Search orders</span>
          <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            type="search"
            inputMode="search"
            placeholder="Reference or service"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-11 w-full rounded-full border border-line-strong bg-surface pl-11 pr-4 text-base text-ink placeholder:text-ink-faint transition-shadow focus:border-brand-500 focus:shadow-focus focus:outline-hidden md:h-10 md:text-sm"
          />
        </label>
      </div>

      {isLoading ? (
        <Card className="overflow-hidden rounded-2xl">
          <ListSkeleton />
        </Card>
      ) : error && !data ? (
        <Card className="rounded-2xl">
          <LoadError what="your orders" onRetry={() => mutate()} />
        </Card>
      ) : orders.length === 0 ? (
        <Card className="rounded-2xl">
          <EmptyState
            art={debouncedSearch ? <SearchArt /> : <PhoneMessageArt />}
            title={
              debouncedSearch
                ? "No orders match that search"
                : filter === "all"
                  ? "No orders yet"
                  : `Nothing ${filterLabel}`
            }
            description={
              debouncedSearch
                ? "Try a different reference or service name."
                : filter === "all"
                  ? "When you buy a number, it appears here with everything that happened to it."
                  : "Orders show up here as soon as one matches."
            }
            action={
              debouncedSearch ? (
                <Button variant="secondary" onClick={() => setSearch("")}>
                  Clear search
                </Button>
              ) : filter !== "all" ? (
                <Button variant="secondary" onClick={() => changeFilter("all")}>
                  Show all orders
                </Button>
              ) : (
                <ButtonLink href="/services">Buy a number</ButtonLink>
              )
            }
          />
        </Card>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <section key={group.label} aria-label={group.label}>
              <h2 className="mb-2 px-1 text-caption font-semibold uppercase tracking-wider text-ink-muted">
                {group.label}
              </h2>
              <Card className="overflow-hidden rounded-2xl">
                {/* Phones: rows. From md: the same orders in aligned columns. */}
                <ul className="divide-y divide-line md:hidden">
                  {group.orders.map((order) => (
                    <OrderStatusRow key={order.id} order={order} />
                  ))}
                </ul>
                <div className="hidden md:block">
                  <div
                    aria-hidden
                    className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1.2fr)_minmax(0,1fr)_7rem_9rem_1.5rem] gap-4 border-b border-line bg-sunken/60 px-5 py-2.5 text-2xs font-semibold uppercase tracking-wider text-ink-muted"
                  >
                    <span>Service</span>
                    <span>Number</span>
                    <span>Date</span>
                    <span className="text-right">Amount</span>
                    <span>Status</span>
                    <span />
                  </div>
                  <ul className="divide-y divide-line">
                    {group.orders.map((order) => (
                      <OrderLine key={order.id} order={order} />
                    ))}
                  </ul>
                </div>
              </Card>
            </section>
          ))}
        </div>
      )}

      {pagination && pagination.pages > 1 ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-ink-muted">
            Page {pagination.page} of {pagination.pages}
            <span className="hidden sm:inline"> &middot; {pagination.count} orders</span>
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={!pagination.has_previous}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!pagination.has_next}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** One order as aligned columns (md and up): the whole line opens it. */
function OrderLine({ order }: { order: OrderSummary }) {
  return (
    <li>
      <Link
        href={`/orders/${order.reference}`}
        className="group grid grid-cols-[minmax(0,1.5fr)_minmax(0,1.2fr)_minmax(0,1fr)_7rem_9rem_1.5rem] items-center gap-4 px-5 py-3 text-sm transition-colors hover:bg-sunken/60"
      >
        <span className="flex min-w-0 items-center gap-3">
          <ServiceLogo name={order.service_name} src={order.service_icon} slug={order.service_slug} size="sm" />
          <span className="min-w-0">
            <span className="flex items-center gap-2 font-semibold text-ink">
              <span className="truncate">{order.service_name}</span>
              <CountryFlag code={order.country_code} size="sm" />
              <span className="sr-only">{order.country_name}</span>
            </span>
            <span className="code block truncate text-caption text-ink-muted">{order.reference}</span>
          </span>
        </span>
        <span className="code truncate text-ink-soft">
          {order.phone_number ? groupInternational(order.phone_number, order.country_dial_code) : "-"}
        </span>
        <span className="truncate text-ink-muted">{formatDateTime(order.created_at)}</span>
        <span className="tabular text-right font-semibold text-ink">{cedis(order.price)}</span>
        <span>
          <StatusBadge status={order.status} />
        </span>
        <ChevronRightIcon className="h-4 w-4 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </Link>
    </li>
  );
}

function ListSkeleton() {
  return (
    <ul className="divide-y divide-line" aria-busy>
      {Array.from({ length: 6 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
          <Skeleton className="h-10 w-10 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-3 w-24" />
          </div>
          <Skeleton className="h-6 w-20" />
        </li>
      ))}
    </ul>
  );
}
