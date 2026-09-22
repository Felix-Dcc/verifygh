"use client";

import Link from "next/link";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { ArrowRightIcon, PlusIcon, ReceiptIcon, WalletIcon } from "@/components/icons";
import {
  Alert,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { cedis, formatDateTime, relativeTime, signedCedis } from "@/lib/format";
import type { Paginated, Payment, Transaction, WalletSummary } from "@/lib/types";

export default function WalletPage() {
  const { data: summary, isLoading } = useSWR<WalletSummary>("/wallet/summary/");
  const { data: transactions } = useSWR<Paginated<Transaction>>([
    "/transactions/",
    { page_size: 6 },
  ]);
  const { data: payments } = useSWR<Paginated<Payment>>(["/payments/", { page_size: 5 }]);

  const wallet = summary?.wallet;
  const hasPromo = Number(wallet?.promo_balance ?? 0) > 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Wallet"
        description="Your cedi balance, top-ups and everything you have spent."
        action={
          <Link href="/wallet/deposit">
            <Button icon={<PlusIcon className="h-5 w-5" />}>Add money</Button>
          </Link>
        }
      />

      {wallet?.is_frozen ? (
        <Alert tone="danger" title="This wallet is on hold">
          You can still see your history, but purchases are paused. Contact support to resolve it.
        </Alert>
      ) : null}

      <div className="relative overflow-hidden rounded-2xl bg-brand-700 p-5 text-white shadow-raised sm:p-6">
        <div
          className="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-brand-500/30 blur-2xl"
          aria-hidden
        />
        <div className="relative">
          <p className="text-sm text-brand-200">
            {hasPromo ? "Available to spend" : "Available balance"}
          </p>
          {isLoading ? (
            <Skeleton className="mt-2 h-10 w-44 bg-white/20" />
          ) : (
            <p className="tabular mt-1 text-4xl font-semibold tracking-tight sm:text-5xl">
              {cedis(hasPromo ? wallet?.spendable : wallet?.balance)}
            </p>
          )}

          {/* Cash and promotional credit are shown apart, always. One can be
              withdrawn and refunded as money; the other cannot. */}
          {hasPromo ? (
            <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <div className="flex items-baseline gap-2">
                <dt className="text-brand-200">Cash</dt>
                <dd className="tabular font-semibold">{cedis(wallet?.balance)}</dd>
              </div>
              <div className="flex items-baseline gap-2">
                <dt className="text-brand-200">Promotional credit</dt>
                <dd className="tabular font-semibold">{cedis(wallet?.promo_balance)}</dd>
              </div>
            </dl>
          ) : null}

          <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-white/15 pt-4 sm:max-w-sm">
            <div>
              <dt className="text-xs text-brand-200">Total added</dt>
              <dd className="tabular mt-0.5 text-base font-semibold">
                {cedis(wallet?.total_deposited)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-brand-200">Total spent</dt>
              <dd className="tabular mt-0.5 text-base font-semibold">
                {cedis(wallet?.total_spent)}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Recent transactions"
            action={
              <Link
                href="/transactions"
                className="text-sm font-medium text-brand-700 hover:underline"
              >
                View all
              </Link>
            }
          />
          {!transactions ? (
            <RowSkeletons />
          ) : transactions.results.length === 0 ? (
            <EmptyState
              icon={<WalletIcon />}
              title="No transactions yet"
              description="Your deposits, purchases and refunds all appear here."
              action={
                <Link href="/wallet/deposit">
                  <Button size="sm">Add money</Button>
                </Link>
              }
            />
          ) : (
            <ul className="mt-2 divide-y divide-line">
              {transactions.results.map((entry) => (
                <li key={entry.id} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
                  <span
                    className={
                      entry.direction === "CREDIT"
                        ? "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-success-50 text-success-700"
                        : "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-line/60 text-ink-soft"
                    }
                  >
                    {entry.direction === "CREDIT" ? (
                      <PlusIcon className="h-4 w-4" />
                    ) : (
                      <ArrowRightIcon className="h-4 w-4" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {entry.description}
                      {entry.funds === "PROMO" ? (
                        <span className="ml-2 rounded-md bg-gold-100 px-1.5 py-0.5 text-[11px] font-semibold text-gold-700">
                          Promo
                        </span>
                      ) : null}
                    </p>
                    <p className="tabular text-xs text-ink-muted">
                      {entry.reference}
                      <span className="mx-1.5" aria-hidden>
                        &middot;
                      </span>
                      {relativeTime(entry.created_at)}
                    </p>
                  </div>
                  <span
                    className={
                      entry.direction === "CREDIT"
                        ? "tabular shrink-0 text-sm font-semibold text-success-700"
                        : "tabular shrink-0 text-sm font-semibold text-ink"
                    }
                  >
                    {signedCedis(entry.amount, entry.direction)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="Recent top-ups" description="Mobile Money payments to VerifyGH." />
          {!payments ? (
            <RowSkeletons />
          ) : payments.results.length === 0 ? (
            <EmptyState
              icon={<ReceiptIcon />}
              title="No top-ups yet"
              description="Add money from MTN, Telecel or AT Money."
              action={
                <Link href="/wallet/deposit">
                  <Button size="sm">Add money</Button>
                </Link>
              }
            />
          ) : (
            <ul className="mt-2 divide-y divide-line">
              {payments.results.map((payment) => (
                <li key={payment.id} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink">
                      <span className="tabular">{cedis(payment.amount)}</span>
                      <span className="ml-2 text-ink-muted">{payment.network_label}</span>
                    </p>
                    <p className="tabular text-xs text-ink-muted">
                      {payment.phone_display}
                      <span className="mx-1.5" aria-hidden>
                        &middot;
                      </span>
                      {formatDateTime(payment.created_at)}
                    </p>
                  </div>
                  <StatusBadge status={payment.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function RowSkeletons() {
  return (
    <ul className="mt-2 divide-y divide-line">
      {Array.from({ length: 4 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
          <Skeleton className="h-9 w-9 rounded-xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-36" />
            <Skeleton className="h-3 w-24" />
          </div>
          <Skeleton className="h-4 w-16" />
        </li>
      ))}
    </ul>
  );
}
