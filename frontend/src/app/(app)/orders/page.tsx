"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { CountryFlag } from "@/components/country-flag";
import { ChevronRightIcon, ReceiptIcon, SearchIcon } from "@/components/icons";
import { OrderStatusRow } from "@/components/orders/order-row";
import { ServiceLogo } from "@/components/service-logo";
import {
  Button,
  Card,
  EmptyState,
  Input,
  SegmentedControl,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { cedis, formatDateTime, groupInternational } from "@/lib/format";
import type { OrderSummary, Paginated } from "@/lib/types";

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
    <React.Suspense fallback={null}>
      <Orders />
    </React.Suspense>
  );
}

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

  const { data, isLoading } = useSWR<Paginated<OrderSummary>>([
    "/orders/",
    { filter: filter === "all" ? "" : filter, search: debouncedSearch, page, page_size: 20 },
  ]);

  const orders = data?.results ?? [];
  const pagination = data?.pagination;
  const filterLabel = FILTERS.find((option) => option.value === filter)?.label.toLowerCase();

  function changeFilter(value: Filter) {
    setFilter(value);
    setPage(1);
    router.replace(value === "all" ? "/orders" : `/orders?filter=${value}`, { scroll: false });
  }

  return (
    <div>
      <PageHeader
        title="Orders"
        description="Every number you have bought, and how each one turned out."
        action={
          <Link href="/services">
            <Button>Buy a number</Button>
          </Link>
        }
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SegmentedControl options={FILTERS} value={filter} onChange={changeFilter} />
        <label className="relative block sm:w-64">
          <span className="sr-only">Search orders</span>
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <Input
            type="search"
            inputMode="search"
            placeholder="Reference or service"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-10"
          />
        </label>
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <ListSkeleton />
        ) : orders.length === 0 ? (
          <EmptyState
            icon={<ReceiptIcon />}
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
                <Link href="/services">
                  <Button>Buy a number</Button>
                </Link>
              )
            }
          />
        ) : (
          <>
            {/* Rows on phones, a real table from md up: the same data, laid out
                for the device rather than one squeezed into the other. */}
            <ul className="divide-y divide-line md:hidden">
              {orders.map((order) => (
                <OrderStatusRow key={order.id} order={order} />
              ))}
            </ul>

            <table className="hidden w-full text-left text-sm md:table">
              <thead className="border-b border-line bg-sunken text-caption text-ink-muted">
                <tr>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Service
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Number
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Date
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Amount
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Status
                  </th>
                  <th scope="col" className="w-10 px-3 py-2.5">
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {orders.map((order) => (
                  <tr
                    key={order.id}
                    // The whole row opens the order; the link in the first cell
                    // is the keyboard and screen-reader route to the same place.
                    onClick={() => router.push(`/orders/${order.reference}`)}
                    className="cursor-pointer transition-colors hover:bg-sunken/60"
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <ServiceLogo
                          name={order.service_name}
                          src={order.service_icon}
                          slug={order.service_slug}
                          size="sm"
                        />
                        <div className="min-w-0">
                          <p className="flex items-center gap-2">
                            <Link
                              href={`/orders/${order.reference}`}
                              onClick={(event) => event.stopPropagation()}
                              className="font-medium text-ink hover:underline"
                            >
                              {order.service_name}
                            </Link>
                            <CountryFlag code={order.country_code} size="sm" />
                            <span className="sr-only">{order.country_name}</span>
                          </p>
                          <p className="code text-caption text-ink-muted">{order.reference}</p>
                        </div>
                      </div>
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3 text-ink-soft">
                      {order.phone_number
                        ? groupInternational(order.phone_number, order.country_dial_code)
                        : "-"}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-ink-muted">
                      {formatDateTime(order.created_at)}
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3 text-right font-medium text-ink">
                      {cedis(order.price)}
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge status={order.status} />
                    </td>
                    <td className="px-3 py-3">
                      <ChevronRightIcon className="h-4 w-4 text-ink-faint" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      {pagination && pagination.pages > 1 ? (
        <div className="mt-4 flex items-center justify-between gap-3">
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
