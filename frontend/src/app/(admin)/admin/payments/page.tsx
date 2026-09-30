"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import { PageHeader } from "@/components/app-shell";
import { SearchIcon, WalletIcon } from "@/components/icons";
import {
  Card,
  EmptyState,
  Input,
  SegmentedControl,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { cedis, formatDateTime } from "@/lib/format";
import type { AdminPayment, Paginated } from "@/lib/types";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "SUCCESS", label: "Successful" },
  { value: "PENDING", label: "Pending" },
  { value: "PROCESSING", label: "Processing" },
  { value: "FAILED", label: "Failed" },
  { value: "EXPIRED", label: "Expired" },
];

export default function AdminPaymentsPage() {
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading } = useSWR<Paginated<AdminPayment>>([
    "/admin/payments/",
    { status, search: debounced, page, page_size: 25 },
  ]);

  const payments = data?.results ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Payments"
        description="Every Mobile Money collection, and whether it was credited."
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <SegmentedControl
          options={STATUS_FILTERS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          className="lg:flex-1"
        />
        <div className="relative lg:w-72">
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
          <Input
            type="search"
            aria-label="Search payments"
            placeholder="Reference or email"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-11"
          />
        </div>
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <RowSkeletons />
        ) : payments.length === 0 ? (
          <EmptyState
            icon={<WalletIcon />}
            title={debounced ? "No payments match that search" : "No payments yet"}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] text-left text-sm">
              <thead className="border-b border-line bg-sunken">
                <tr className="text-caption text-ink-muted">
                  <th scope="col" className="px-5 py-3 font-medium">Reference</th>
                  <th scope="col" className="px-5 py-3 font-medium">User</th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">Amount</th>
                  <th scope="col" className="px-5 py-3 font-medium">Network</th>
                  <th scope="col" className="px-5 py-3 font-medium">Status</th>
                  <th scope="col" className="px-5 py-3 font-medium">Credited</th>
                  <th scope="col" className="px-5 py-3 font-medium">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {payments.map((payment) => (
                  <tr key={payment.id} className="transition-colors hover:bg-sunken/60">
                    <td className="tabular whitespace-nowrap px-5 py-3.5 font-medium text-ink">
                      {payment.reference}
                      {payment.provider_reference ? (
                        <span className="block text-xs font-normal text-ink-faint">
                          {payment.provider}: {payment.provider_reference}
                        </span>
                      ) : null}
                    </td>
                    <td className="max-w-[12rem] truncate px-5 py-3.5 text-ink-soft">
                      {payment.user_email}
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 text-right font-medium text-ink">
                      {cedis(payment.amount)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-soft">
                      {payment.network}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={payment.status} />
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                      {payment.credited_at ? formatDateTime(payment.credited_at) : "-"}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                      {formatDateTime(payment.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data?.pagination ? (
        <Pagination
          page={data.pagination.page}
          pages={data.pagination.pages}
          count={data.pagination.count}
          hasNext={data.pagination.has_next}
          hasPrevious={data.pagination.has_previous}
          onChange={setPage}
          noun="payments"
        />
      ) : null}

      <p className="text-xs leading-relaxed text-ink-muted">
        A payment is credited only by a signature-verified provider callback, or by our own
        reconciliation call to the provider. A payment showing Successful but not Credited is
        worth investigating immediately.
      </p>
    </div>
  );
}

function RowSkeletons() {
  return (
    <ul className="divide-y divide-line">
      {Array.from({ length: 8 }).map((_, index) => (
        <li key={index} className="flex items-center gap-4 px-5 py-3.5">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-6 w-24 rounded-full" />
        </li>
      ))}
    </ul>
  );
}
