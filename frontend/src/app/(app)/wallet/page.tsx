"use client";

import Link from "next/link";
import useSWR from "swr";

import { AppHero, HeroAmount } from "@/components/app-hero";
import { ArrowRightIcon, PlusIcon } from "@/components/icons";
import { StatementArt, WalletArt } from "@/components/illustrations";
import {
  Alert,
  ButtonLink,
  Card,
  EmptyState,
  LoadError,
  Section,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { TransactionRow } from "@/components/wallet/transaction-row";
import { cedis, formatDateTime } from "@/lib/format";
import type { Paginated, Payment, Transaction, WalletSummary } from "@/lib/types";

/**
 * The wallet: what can be spent now (cash and promotional credit, always
 * shown apart), what has gone in and out over time drawn to scale, and the
 * two histories - every ledger movement, and the Mobile Money top-ups.
 */
export default function WalletPage() {
  const {
    data: summary,
    isLoading,
    error: summaryError,
    mutate: retrySummary,
  } = useSWR<WalletSummary>("/wallet/summary/");
  const transactions = useSWR<Paginated<Transaction>>(["/transactions/", { page_size: 6 }]);
  const payments = useSWR<Paginated<Payment>>(["/payments/", { page_size: 5 }]);

  const wallet = summary?.wallet;
  const summaryFailed = Boolean(summaryError) && !summary;
  const hasPromo = Number(wallet?.promo_balance ?? 0) > 0;

  return (
    <div className="space-y-8">
      <AppHero
        title="Wallet"
        description="Your cedi balance, your Mobile Money top-ups and everything you have spent."
        actions={
          <>
            <ButtonLink href="/wallet/deposit" variant="onBand" icon={<PlusIcon className="h-4 w-4" />}>
              Add funds
            </ButtonLink>
            <ButtonLink href="/services" variant="onBandOutline">
              Buy a number
            </ButtonLink>
          </>
        }
        aside={
          <InAndOut
            loading={isLoading}
            failed={summaryFailed}
            added={wallet?.total_deposited}
            spent={wallet?.total_spent}
          />
        }
      >
        <div className="mt-6">
          <p className="text-caption font-medium text-white/60">{hasPromo ? "Available to spend" : "Available balance"}</p>
          <div className="mt-1 min-h-12">
            {isLoading ? (
              <Skeleton className="h-12 w-56" />
            ) : summaryFailed ? (
              <LoadError compact what="your balance" onRetry={() => retrySummary()} className="pt-2" />
            ) : (
              <HeroAmount value={cedis(hasPromo ? wallet?.spendable : wallet?.balance)} />
            )}
          </div>
          {/* Cash and promotional credit are shown apart, always. One can be
              withdrawn and refunded as money; the other cannot. */}
          {hasPromo ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="rounded-full border border-white/15 bg-white/[0.06] px-3 py-1 text-caption text-white/80">
                <span className="tabular font-semibold text-white">{cedis(wallet?.balance)}</span> cash
              </span>
              <span className="rounded-full border border-[#E9C46A]/30 bg-[#E9C46A]/10 px-3 py-1 text-caption text-[#F3D98B]">
                <span className="tabular font-semibold">{cedis(wallet?.promo_balance)}</span> promotional credit,
                used first
              </span>
            </div>
          ) : null}
        </div>
      </AppHero>

      {wallet?.is_frozen ? (
        <Alert tone="danger" title="This wallet is on hold">
          You can still see your history, but purchases are paused. Contact support to resolve it.
        </Alert>
      ) : null}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2 lg:gap-6">
        <Section
          title="Recent transactions"
          action={
            <Link href="/transactions" className="link inline-flex min-h-11 items-center gap-1 text-sm sm:min-h-0">
              Full statement <ArrowRightIcon className="h-3.5 w-3.5" />
            </Link>
          }
        >
          <Card className="overflow-hidden rounded-2xl">
            {transactions.error && !transactions.data ? (
              <LoadError what="your transactions" onRetry={() => transactions.mutate()} />
            ) : !transactions.data ? (
              <RowSkeletons />
            ) : transactions.data.results.length === 0 ? (
              <EmptyState
                art={<StatementArt />}
                title="No transactions yet"
                description="Your deposits, purchases and refunds all appear here."
              />
            ) : (
              <ul className="divide-y divide-line">
                {transactions.data.results.map((entry) => (
                  <TransactionRow key={entry.id} entry={entry} />
                ))}
              </ul>
            )}
          </Card>
        </Section>

        <Section title="Top-ups" description="Mobile Money payments into your wallet.">
          <Card className="overflow-hidden rounded-2xl">
            {payments.error && !payments.data ? (
              <LoadError what="your top-ups" onRetry={() => payments.mutate()} />
            ) : !payments.data ? (
              <RowSkeletons />
            ) : payments.data.results.length === 0 ? (
              <EmptyState
                art={<WalletArt />}
                title="No top-ups yet"
                description="Add funds from MTN MoMo, Telecel Cash or AT Money."
                action={<ButtonLink href="/wallet/deposit" size="sm">Add funds</ButtonLink>}
              />
            ) : (
              <ul className="divide-y divide-line">
                {payments.data.results.map((payment) => (
                  <li key={payment.id} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
                    <NetworkMark label={payment.network_label} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink">
                        <span className="tabular font-semibold">{cedis(payment.amount)}</span>
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

/**
 * Money in and money out, drawn to scale against each other: two bars on the
 * navy panel. Just the two totals the wallet reports - no sums implied
 * between them (refunds and promotional credit live elsewhere).
 */
function InAndOut({
  loading,
  failed,
  added,
  spent,
}: {
  loading: boolean;
  failed: boolean;
  added?: string;
  spent?: string;
}) {
  const inValue = Number.parseFloat(added ?? "0") || 0;
  const outValue = Number.parseFloat(spent ?? "0") || 0;
  const max = Math.max(inValue, outValue, 1);
  const bars = [
    { label: "Total added", value: added, width: inValue / max, tone: "from-azure to-aqua" },
    { label: "Total spent", value: spent, width: outValue / max, tone: "from-aqua to-leaf" },
  ];
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4 backdrop-blur sm:p-5">
      <p className="text-caption font-medium text-white/60">Since you joined</p>
      <div className="mt-3 space-y-4">
        {bars.map((bar) => (
          <div key={bar.label}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm text-white/80">{bar.label}</span>
              {loading ? (
                <Skeleton className="h-5 w-20" />
              ) : (
                <span className="tabular text-lg font-bold tracking-tight text-white">
                  {failed ? "—" : cedis(bar.value)}
                </span>
              )}
            </div>
            <span aria-hidden className="mt-2 block h-2 overflow-hidden rounded-full bg-white/10">
              <span
                className={`block h-full rounded-full bg-gradient-to-r ${bar.tone} transition-[width] duration-700 ease-out`}
                style={{ width: loading || failed ? "0%" : `${Math.max(bar.width * 100, bar.width > 0 ? 3 : 0)}%` }}
              />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The network a top-up came from, as a small mark of its initials - named, not its logo. */
function NetworkMark({ label }: { label: string }) {
  const short = label.startsWith("MTN") ? "MTN" : label.startsWith("Telecel") ? "TC" : label.startsWith("AT") ? "AT" : label.slice(0, 2);
  return (
    <span
      aria-hidden
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#0B63B6] to-[#137A4E] text-2xs font-bold text-white shadow-[0_6px_14px_-6px_rgba(8,120,209,0.7)]"
    >
      {short}
    </span>
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
