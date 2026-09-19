"use client";

import Link from "next/link";
import * as React from "react";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { ArrowRightIcon, PlusIcon, WalletIcon } from "@/components/icons";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SegmentedControl,
  Skeleton,
} from "@/components/ui/primitives";
import { cedis, formatDateTime, relativeTime, signedCedis } from "@/lib/format";
import type { LedgerEntryType, Paginated, Transaction } from "@/lib/types";

type Filter = "" | LedgerEntryType;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "", label: "All" },
  { value: "DEPOSIT", label: "Deposits" },
  { value: "PURCHASE", label: "Purchases" },
  { value: "REFUND", label: "Refunds" },
  { value: "ADJUSTMENT", label: "Adjustments" },
];

const TYPE_TONES: Record<string, "success" | "neutral" | "brand" | "warn"> = {
  DEPOSIT: "success",
  PURCHASE: "neutral",
  REFUND: "brand",
  ADJUSTMENT: "warn",
  WITHDRAWAL: "neutral",
  REVERSAL: "warn",
};

export default function TransactionsPage() {
  const [filter, setFilter] = React.useState<Filter>("");
  const [page, setPage] = React.useState(1);

  const { data, isLoading } = useSWR<Paginated<Transaction>>([
    "/transactions/",
    { entry_type: filter, page, page_size: 25 },
  ]);

  const entries = data?.results ?? [];
  const pagination = data?.pagination;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Transactions"
        description="Every movement of money on your account, with a reference for each one."
        action={
          <Link href="/wallet/deposit">
            <Button icon={<PlusIcon className="h-5 w-5" />}>Add money</Button>
          </Link>
        }
      />

      <SegmentedControl
        options={FILTERS}
        value={filter}
        onChange={(value) => {
          setFilter(value);
          setPage(1);
        }}
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <TableSkeleton />
        ) : entries.length === 0 ? (
          <EmptyState
            icon={<WalletIcon />}
            title={filter ? "Nothing of that type yet" : "No transactions yet"}
            description="Deposits, purchases, refunds and adjustments all show up here."
            action={
              <Link href="/wallet/deposit">
                <Button>Add money</Button>
              </Link>
            }
          />
        ) : (
          <>
            <ul className="divide-y divide-line md:hidden">
              {entries.map((entry) => (
                <li key={entry.id} className="flex items-start gap-3 px-4 py-3.5">
                  <span
                    className={
                      entry.direction === "CREDIT"
                        ? "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-success-50 text-success-700"
                        : "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-line/60 text-ink-soft"
                    }
                  >
                    {entry.direction === "CREDIT" ? (
                      <PlusIcon className="h-4 w-4" />
                    ) : (
                      <ArrowRightIcon className="h-4 w-4" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink">{entry.description}</p>
                    <p className="tabular mt-0.5 text-xs text-ink-muted">{entry.reference}</p>
                    <p className="mt-1 flex items-center gap-2 text-xs text-ink-faint">
                      <Badge tone={TYPE_TONES[entry.entry_type] ?? "neutral"}>
                        {entry.entry_type.charAt(0) + entry.entry_type.slice(1).toLowerCase()}
                      </Badge>
                      {relativeTime(entry.created_at)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p
                      className={
                        entry.direction === "CREDIT"
                          ? "tabular text-sm font-semibold text-success-700"
                          : "tabular text-sm font-semibold text-ink"
                      }
                    >
                      {signedCedis(entry.amount, entry.direction)}
                    </p>
                    <p className="tabular mt-0.5 text-xs text-ink-faint">
                      {cedis(entry.balance_after)}
                    </p>
                  </div>
                </li>
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
                      Type
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Description
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Reference
                    </th>
                    <th scope="col" className="px-5 py-3 text-right font-medium">
                      Amount
                    </th>
                    <th scope="col" className="px-5 py-3 text-right font-medium">
                      Balance
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {entries.map((entry) => (
                    <tr key={entry.id} className="transition-colors hover:bg-canvas">
                      <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                        {formatDateTime(entry.created_at)}
                      </td>
                      <td className="px-5 py-3.5">
                        <Badge tone={TYPE_TONES[entry.entry_type] ?? "neutral"}>
                          {entry.entry_type.charAt(0) + entry.entry_type.slice(1).toLowerCase()}
                        </Badge>
                      </td>
                      <td className="max-w-xs truncate px-5 py-3.5 text-ink">
                        {entry.related_order_id ? (
                          <span>{entry.description}</span>
                        ) : (
                          entry.description
                        )}
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3.5 text-ink-muted">
                        {entry.reference}
                      </td>
                      <td
                        className={
                          entry.direction === "CREDIT"
                            ? "tabular whitespace-nowrap px-5 py-3.5 text-right font-semibold text-success-700"
                            : "tabular whitespace-nowrap px-5 py-3.5 text-right font-semibold text-ink"
                        }
                      >
                        {signedCedis(entry.amount, entry.direction)}
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3.5 text-right text-ink-muted">
                        {cedis(entry.balance_after)}
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
            <span className="hidden sm:inline"> - {pagination.count} transactions</span>
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

function TableSkeleton() {
  return (
    <ul className="divide-y divide-line">
      {Array.from({ length: 8 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
          <Skeleton className="h-9 w-9 rounded-xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-48" />
            <Skeleton className="h-3 w-28" />
          </div>
          <Skeleton className="h-4 w-20" />
        </li>
      ))}
    </ul>
  );
}
