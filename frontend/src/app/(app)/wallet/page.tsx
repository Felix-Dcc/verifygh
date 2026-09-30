"use client";

import Link from "next/link";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { ReceiptIcon, WalletIcon } from "@/components/icons";
import {
  Alert,
  Amount,
  Button,
  Card,
  EmptyState,
  Section,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { TransactionRow } from "@/components/wallet/transaction-row";
import { cedis, formatDateTime } from "@/lib/format";
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
    <div className="space-y-8">
      <PageHeader
        title="Wallet"
        description="Your cedi balance, top-ups and everything you have spent."
      />

      {wallet?.is_frozen ? (
        <Alert tone="danger" title="This wallet is on hold">
          You can still see your history, but purchases are paused. Contact support to resolve it.
        </Alert>
      ) : null}

      <Card className="grid gap-6 p-5 sm:p-6 md:grid-cols-5">
        <div className="md:col-span-3">
          <p className="text-sm text-ink-muted">{hasPromo ? "Available to spend" : "Available balance"}</p>
          <div className="mt-1.5 min-h-10">
            {isLoading ? (
              <Skeleton className="h-10 w-48" />
            ) : (
              <Amount value={cedis(hasPromo ? wallet?.spendable : wallet?.balance)} />
            )}
          </div>
          {/* Cash and promotional credit are shown apart, always. One can be
              withdrawn and refunded as money; the other cannot. */}
          {hasPromo ? (
            <p className="mt-1.5 text-caption text-ink-muted">
              <span className="tabular">{cedis(wallet?.balance)}</span> cash and{" "}
              <span className="tabular font-medium text-gold-700">{cedis(wallet?.promo_balance)}</span>{" "}
              promotional credit, which is used first.
            </p>
          ) : null}
          <div className="mt-5 flex flex-wrap gap-2">
            <Link href="/wallet/deposit">
              <Button>Add funds</Button>
            </Link>
            <Link href="/services">
              <Button variant="secondary">Buy a number</Button>
            </Link>
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-4 border-t border-line pt-5 md:col-span-2 md:grid-cols-1 md:content-center md:border-l md:border-t-0 md:pl-6 md:pt-0">
          <div>
            <dt className="text-caption text-ink-muted">Total added</dt>
            <dd className="tabular mt-0.5 text-heading text-ink">
              {isLoading ? <Skeleton className="h-5 w-24" /> : cedis(wallet?.total_deposited)}
            </dd>
          </div>
          <div>
            <dt className="text-caption text-ink-muted">Total spent</dt>
            <dd className="tabular mt-0.5 text-heading text-ink">
              {isLoading ? <Skeleton className="h-5 w-24" /> : cedis(wallet?.total_spent)}
            </dd>
          </div>
        </dl>
      </Card>

      <div className="grid gap-8 lg:grid-cols-2">
        <Section
          title="Recent transactions"
          action={
            <Link href="/transactions" className="link text-sm">
              All transactions
            </Link>
          }
        >
          <Card className="overflow-hidden">
            {!transactions ? (
              <RowSkeletons />
            ) : transactions.results.length === 0 ? (
              <EmptyState
                icon={<WalletIcon />}
                title="No transactions yet"
                description="Your deposits, purchases and refunds all appear here."
              />
            ) : (
              <ul className="divide-y divide-line">
                {transactions.results.map((entry) => (
                  <TransactionRow key={entry.id} entry={entry} />
                ))}
              </ul>
            )}
          </Card>
        </Section>

        <Section title="Top-ups" description="Mobile Money payments into your wallet.">
          <Card className="overflow-hidden">
            {!payments ? (
              <RowSkeletons />
            ) : payments.results.length === 0 ? (
              <EmptyState
                icon={<ReceiptIcon />}
                title="No top-ups yet"
                description="Add funds from MTN MoMo, Telecel Cash or AT Money."
                action={
                  <Link href="/wallet/deposit">
                    <Button size="sm">Add funds</Button>
                  </Link>
                }
              />
            ) : (
              <ul className="divide-y divide-line">
                {payments.results.map((payment) => (
                  <li key={payment.id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink">
                        <span className="tabular font-medium">{cedis(payment.amount)}</span>
                        <span className="text-ink-muted"> from {payment.network_label}</span>
                      </p>
                      <p className="truncate text-caption text-ink-muted">
                        <span className="tabular">{payment.phone_display}</span>
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
        </Section>
      </div>
    </div>
  );
}

function RowSkeletons() {
  return (
    <ul className="divide-y divide-line" aria-busy>
      {Array.from({ length: 4 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <Skeleton className="h-9 w-9 rounded-lg" />
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
