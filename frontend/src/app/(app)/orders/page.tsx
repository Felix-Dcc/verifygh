"use client";

import Link from "next/link";
import * as React from "react";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { ServiceLogo } from "@/components/service-logo";
import { ReceiptIcon, SearchIcon } from "@/components/icons";
import { OrderStatusRow } from "@/components/orders/order-row";
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
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "refunded", label: "Refunded" },
];

export default function OrdersPage() {
  const [filter, setFilter] = React.useState<Filter>("all");
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

  return (
    <div className="space-y-4">
      <PageHeader
        title="Orders"
        description="Every verification number you have bought, and how each one turned out."
        action={
          <Link href="/services">
            <Button>Buy verification</Button>
          </Link>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SegmentedControl
          options={FILTERS}
          value={filter}
          onChange={(value) => {
            setFilter(value);
            setPage(1);
          }}
          className="sm:flex-1"
        />
        <div className="relative sm:w-64">
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
          <Input
            type="search"
            inputMode="search"
            aria-label="Search orders"
            placeholder="Reference or service"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-11"
          />
        </div>
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
                  : `No ${filter} orders`
            }
            description={
              debouncedSearch
                ? "Try a different reference or service name."
                : "When you buy a verification number it appears here with its full history."
            }
            action={
              debouncedSearch ? (
                <Button variant="secondary" onClick={() => setSearch("")}>
                  Clear search
                </Button>
              ) : (
                <Link href="/services">
                  <Button>Browse services</Button>
                </Link>
              )
            }
          />
        ) : (
          <>
            {/* Cards on phones, a real table from md up: the same data, laid out
                for the device rather than one squeezed into the other. */}
            <ul className="divide-y divide-line md:hidden">
              {orders.map((order) => (
                <OrderStatusRow key={order.id} order={order} />
              ))}
            </ul>

            <div className="hidden md:block">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line bg-canvas">
                  <tr className="text-xs uppercase tracking-wide text-ink-muted">
                    <th scope="col" className="px-5 py-3 font-medium">
                      Date
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Service
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Number
                    </th>
                    <th scope="col" className="px-5 py-3 text-right font-medium">
                      Amount
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Status
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Reference
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {orders.map((order) => (
                    <tr key={order.id} className="transition-colors hover:bg-canvas">
                      <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                        {formatDateTime(order.created_at)}
                      </td>
                      <td className="px-5 py-3.5">
                        <Link
                          href={`/orders/${order.reference}`}
                          className="inline-flex items-center gap-2.5 font-medium text-ink hover:underline"
                        >
                          <ServiceLogo
                            name={order.service_name}
                            src={order.service_icon}
                            slug={order.service_slug}
                            size="sm"
                          />
                          {order.service_name}
                        </Link>
                        <span className="ml-2 text-ink-muted" aria-label={order.country_name}>
                          {order.country_flag}
                        </span>
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3.5 text-ink-soft">
                        {order.phone_number
                          ? groupInternational(order.phone_number, order.country_dial_code)
                          : "-"}
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3.5 text-right font-medium text-ink">
                        {cedis(order.price)}
                      </td>
                      <td className="px-5 py-3.5">
                        <StatusBadge status={order.status} />
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3.5 text-ink-muted">
                        <Link href={`/orders/${order.reference}`} className="hover:underline">
                          {order.reference}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>

      {pagination && pagination.pages > 1 ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-ink-muted">
            Page {pagination.page} of {pagination.pages}
            <span className="hidden sm:inline"> - {pagination.count} orders</span>
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
    <ul className="divide-y divide-line">
      {Array.from({ length: 6 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
          <Skeleton className="h-11 w-11 rounded-xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-3 w-24" />
          </div>
          <Skeleton className="h-6 w-20 rounded-full" />
        </li>
      ))}
    </ul>
  );
}
