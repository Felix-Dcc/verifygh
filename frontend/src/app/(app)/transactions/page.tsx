"use client";

import Link from "next/link";
import * as React from "react";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { PlusIcon, WalletIcon } from "@/components/icons";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SegmentedControl,
  Skeleton,
} from "@/components/ui/primitives";
import {
  ENTRY_LABELS,
  TransactionAmount,
  TransactionIcon,
  TransactionRow,
} from "@/components/wallet/transaction-row";
import { cedis, formatDateTime } from "@/lib/format";
import type { LedgerEntryType, Paginated, Transaction } from "@/lib/types";

type Filter = "" | LedgerEntryType;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "", label: "All" },
  { value: "DEPOSIT", label: "Deposits" },
  { value: "PURCHASE", label: "Purchases" },
  { value: "REFUND", label: "Refunds" },
  { value: "ADJUSTMENT", label: "Adjustments" },
];

const TYPE_TONES: Record<string, "success" | "neutral" | "brand" | "warn" | "gold"> = {
  DEPOSIT: "success",
  PURCHASE: "neutral",
  REFUND: "brand",
  ADJUSTMENT: "warn",
  WITHDRAWAL: "neutral",
  REVERSAL: "warn",
  REFERRAL_BONUS: "gold",
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
    <div>
      <PageHeader
        title="Transactions"
        description="Every movement of money on your account, with a reference for each one."
        action={
          // The top bar carries "Add funds" from sm up; phones get it here.
          <Link href="/wallet/deposit" className="sm:hidden">
            <Button icon={<PlusIcon className="h-5 w-5" />}>Add funds</Button>
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
        className="mb-4"
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
              filter ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setFilter("");
                    setPage(1);
                  }}
                >
                  Show everything
                </Button>
              ) : (
                <Link href="/wallet/deposit">
                  <Button>Add funds</Button>
                </Link>
              )
            }
          />
        ) : (
          <>
            <ul className="divide-y divide-line md:hidden">
              {entries.map((entry) => (
                <TransactionRow key={entry.id} entry={entry} showBalance />
              ))}
            </ul>

            <table className="hidden w-full text-left text-sm md:table">
              <thead className="border-b border-line bg-sunken text-caption text-ink-muted">
                <tr>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Description
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Type
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Date
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Amount
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Balance after
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {entries.map((entry) => (
                  <tr key={entry.id} className="transition-colors hover:bg-sunken/60">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <TransactionIcon entry={entry} />
                        <div className="min-w-0">
                          <p className="flex max-w-sm items-center gap-2 text-ink">
                            <span className="truncate">{entry.description}</span>
                            {entry.funds === "PROMO" ? (
                              <Badge tone="gold" className="shrink-0">
                                Promo
                              </Badge>
                            ) : null}
                          </p>
                          <p className="code text-caption text-ink-muted">{entry.reference}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={TYPE_TONES[entry.entry_type] ?? "neutral"}>
                        {ENTRY_LABELS[entry.entry_type] ?? entry.entry_type}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-ink-muted">
                      {formatDateTime(entry.created_at)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <TransactionAmount entry={entry} />
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3 text-right text-ink-muted">
                      {cedis(entry.balance_after)}
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
            <span className="hidden sm:inline"> &middot; {pagination.count} transactions</span>
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
          <Skeleton className="h-9 w-9 rounded-lg" />
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
