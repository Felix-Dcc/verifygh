"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import {
  AdminToolbar,
  KpiCard,
  KpiRow,
  ListCard,
  SearchBox,
  TableSkeleton,
  openRow,
} from "@/components/admin/ui";
import { PageHeader } from "@/components/app-shell";
import { AlertIcon, BoltIcon, ClockIcon, PhoneIcon, WalletIcon } from "@/components/icons";
import { RentalLogo, RentalStatusBadge } from "@/components/rentals/rental-ui";
import { Dialog } from "@/components/ui/dialog";
import { Button, DescriptionList, EmptyState, LoadError, SegmentedControl } from "@/components/ui/primitives";
import { cedis, formatDateTime, groupInternational, usd } from "@/lib/format";
import type { AdminRental, AdminRentalSummary, Paginated } from "@/lib/types";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "ACTIVE", label: "Active" },
  { value: "PENDING", label: "Setting up" },
  { value: "EXPIRED", label: "Ended" },
  { value: "REFUNDED", label: "Refunded" },
  { value: "FAILED", label: "Failed" },
];

/** Number rentals: who rents what, for how long, and what it cost us. Read-only. */
export default function AdminRentalsPage() {
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) setSearch(q.slice(0, 80));
  }, []);
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<AdminRental | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading, isValidating, error, mutate } = useSWR<Paginated<AdminRental>>(
    ["/admin/rentals/", { status, search: debounced, page, page_size: 25 }],
    { keepPreviousData: true },
  );
  const { data: summary } = useSWR<AdminRentalSummary>("/admin/rentals/summary/", { refreshInterval: 60_000 });
  const rentals = data?.results ?? [];
  const filter = (value: string) => {
    setStatus((current) => (current === value ? "" : value));
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Rentals"
        description="Numbers customers rent for days from TextVerified: their status, provider references and cost."
      />

      <KpiRow>
        <KpiCard
          icon={<PhoneIcon />}
          label="Active"
          value={summary?.active}
          hint="Receiving messages now"
          onClick={() => filter("ACTIVE")}
          active={status === "ACTIVE"}
        />
        <KpiCard
          icon={<BoltIcon />}
          tone="warn"
          label="Setting up"
          value={summary?.pending}
          hint="Waiting for the provider"
          onClick={() => filter("PENDING")}
          active={status === "PENDING"}
        />
        <KpiCard
          icon={<WalletIcon />}
          tone="gold"
          label="Takings, 30 days"
          value={summary ? cedis(summary.takings_30d) : undefined}
          hint={summary ? `${cedis(summary.takings)} all time` : undefined}
        />
        <KpiCard
          icon={<AlertIcon />}
          tone="danger"
          label="Refunded or failed"
          value={summary?.refunded_or_failed}
          hint="All time"
          onClick={() => filter("FAILED")}
          active={status === "FAILED"}
        />
      </KpiRow>

      <AdminToolbar>
        <SegmentedControl
          options={STATUS_FILTERS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          className="lg:flex-1"
        />
        <SearchBox label="Search rentals" placeholder="Reference, email or number" value={search} onChange={setSearch} />
      </AdminToolbar>

      <ListCard
        title="Rentals"
        count={data?.pagination?.count}
        noun="rentals"
        refreshing={isValidating}
        onRefresh={() => mutate()}
      >
        {isLoading ? (
          <TableSkeleton />
        ) : error && !data ? (
          <LoadError what="the rentals" onRetry={() => mutate()} />
        ) : rentals.length === 0 ? (
          <EmptyState
            icon={<ClockIcon />}
            title={debounced || status ? "No rentals match" : "No rentals yet"}
            action={
              debounced || status ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setStatus("");
                    setPage(1);
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[56rem] text-left text-sm">
              <thead className="border-b border-line bg-sunken">
                <tr className="text-caption text-ink-muted">
                  <th scope="col" className="px-5 py-3 font-medium">Reference</th>
                  <th scope="col" className="px-5 py-3 font-medium">User</th>
                  <th scope="col" className="px-5 py-3 font-medium">Number for</th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">Price</th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">Cost</th>
                  <th scope="col" className="px-5 py-3 font-medium">Status</th>
                  <th scope="col" className="px-5 py-3 font-medium">Ends</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rentals.map((rental) => (
                  <tr key={rental.id} {...openRow(() => setSelected(rental), `Open rental ${rental.reference}`)}>
                    <td className="code whitespace-nowrap px-5 py-3.5 text-ink">{rental.reference}</td>
                    <td className="max-w-[14rem] truncate px-5 py-3.5 text-ink-soft">{rental.user_email}</td>
                    <td className="px-5 py-3.5">
                      <span className="flex items-center gap-2.5">
                        <RentalLogo rental={rental} size="sm" />
                        <span className="min-w-0">
                          <span className="block truncate font-medium text-ink">{rental.service_name}</span>
                          <span className="block text-caption text-ink-muted">{rental.duration_label}</span>
                        </span>
                      </span>
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 text-right text-ink">{cedis(rental.price)}</td>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 text-right text-ink-muted">
                      {usd(rental.provider_cost)}
                    </td>
                    <td className="px-5 py-3.5">
                      <RentalStatusBadge status={rental.status} />
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                      {rental.ends_at ? formatDateTime(rental.ended_at ?? rental.ends_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>

      {data?.pagination ? (
        <Pagination
          page={data.pagination.page}
          pages={data.pagination.pages}
          count={data.pagination.count}
          hasNext={data.pagination.has_next}
          hasPrevious={data.pagination.has_previous}
          onChange={setPage}
          noun="rentals"
        />
      ) : null}

      <Dialog open={Boolean(selected)} onClose={() => setSelected(null)} title={selected?.reference ?? "Rental"}>
        {selected ? (
          <DescriptionList
            items={[
              { label: "Customer", value: selected.user_email },
              { label: "Number for", value: `${selected.service_name} (${selected.provider_service_name})` },
              { label: "Length", value: selected.duration_label },
              { label: "Status", value: <RentalStatusBadge status={selected.status} /> },
              {
                label: "Number",
                value: selected.phone_number ? (
                  <span className="tabular">{groupInternational(selected.phone_number, "+1")}</span>
                ) : (
                  "—"
                ),
              },
              { label: "Price", value: <span className="tabular">{cedis(selected.price)}</span>, emphasis: true },
              {
                label: "Paid with",
                value: `${cedis(selected.cash_amount)} cash, ${cedis(selected.promo_amount)} promotional`,
              },
              {
                label: "Provider cost",
                value: `${usd(selected.provider_cost)} at ${Number(selected.exchange_rate).toFixed(2)} = ${cedis(
                  Number(selected.provider_cost) * Number(selected.exchange_rate),
                )}`,
              },
              ...(Number(selected.refunded_amount) > 0
                ? [{ label: "Refunded", value: <span className="tabular">{cedis(selected.refunded_amount)}</span> }]
                : []),
              { label: "Messages", value: String(selected.message_count) },
              { label: "Provider rental", value: <span className="code">{selected.provider_rental_id || "—"}</span> },
              { label: "Provider sale", value: <span className="code">{selected.provider_sale_id || "—"}</span> },
              { label: "Attempts", value: String(selected.attempts) },
              ...(selected.failure_reason ? [{ label: "Reason", value: selected.failure_reason }] : []),
              { label: "Rented", value: formatDateTime(selected.created_at) },
              ...(selected.ends_at ? [{ label: "Ends", value: formatDateTime(selected.ends_at) }] : []),
            ]}
          />
        ) : null}
      </Dialog>
    </div>
  );
}
