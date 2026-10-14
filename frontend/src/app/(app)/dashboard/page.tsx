"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { AppHero, HeroAmount, HeroStat } from "@/components/app-hero";
import { useAuth } from "@/components/auth-provider";
import { ArrowRightIcon, PlusIcon } from "@/components/icons";
import { PhoneMessageArt, StatementArt } from "@/components/illustrations";
import { LiveOrderCard, useNow } from "@/components/orders/live-order-card";
import { OrderStatusRow } from "@/components/orders/order-row";
import { ServiceLogo } from "@/components/service-logo";
import { TransactionRow } from "@/components/wallet/transaction-row";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  LoadError,
  Section,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cedis } from "@/lib/format";
import type {
  MarketHome,
  OrderSummary,
  Paginated,
  Transaction,
  WalletSummary,
} from "@/lib/types";

/**
 * Home: the money, what is running right now, and the quickest way to the
 * next number. Everything here is the customer's own data or the
 * marketplace's real popularity - nothing is filled in to make the page look
 * busy.
 */
export default function DashboardPage() {
  return (
    <React.Suspense fallback={<DashboardSkeleton />}>
      <Dashboard />
    </React.Suspense>
  );
}

const TODAY = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  timeZone: "Africa/Accra",
});

function greeting(): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "numeric", hour12: false, timeZone: "Africa/Accra" })
      .format(new Date()),
  );
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function Dashboard() {
  const { user, refresh } = useAuth();
  const params = useSearchParams();
  const toast = useToast();

  const summary = useSWR<WalletSummary>("/wallet/summary/");
  const { data: activeOrders } = useSWR<OrderSummary[]>("/orders/active/", {
    // Active orders change on their own, so keep this fresh while the tab is open.
    refreshInterval: 15_000,
  });
  const recentOrders = useSWR<Paginated<OrderSummary>>(["/orders/", { page_size: 8 }]);
  const recentTransactions = useSWR<Paginated<Transaction>>(["/transactions/", { page_size: 5 }]);
  const market = useSWR<MarketHome>("/marketplace/home/");

  const [resending, setResending] = React.useState(false);

  async function resendVerification() {
    setResending(true);
    try {
      await api.post("/auth/email/verify/send/", {});
      toast.success("Verification email sent", "Check your inbox, and your spam folder.");
    } catch {
      toast.error("Could not send it", "Try again in a few minutes.");
    } finally {
      setResending(false);
    }
  }

  const firstName = user?.full_name?.split(" ")[0];
  const live = activeOrders ?? [];
  const now = useNow(live.length > 0);
  // Orders already shown under "In progress" are not repeated below it.
  const liveIds = new Set(live.map((order) => order.id));
  const finished = (recentOrders.data?.results ?? []).filter((order) => !liveIds.has(order.id)).slice(0, 5);

  const wallet = summary.data?.wallet;
  const loading = summary.isLoading;
  const failed = Boolean(summary.error) && !summary.data;
  const promo = Number.parseFloat(wallet?.promo_balance ?? "0");
  const stat = (value: React.ReactNode) => (loading ? <Skeleton className="mt-1 h-6 w-16" /> : value);

  return (
    <div className="space-y-8">
      <AppHero
        eyebrow={TODAY.format(new Date())}
        title={firstName ? `${greeting()}, ${firstName}` : greeting()}
        actions={
          <>
            <ButtonLink href="/wallet/deposit" variant="onBand" icon={<PlusIcon className="h-4 w-4" />}>
              Add funds
            </ButtonLink>
            <ButtonLink href="/services" variant="onBandOutline">
              Buy a number
            </ButtonLink>
            <ButtonLink href="/rentals" variant="onBandOutline">
              Rent a number
            </ButtonLink>
          </>
        }
        aside={
          <div className="grid grid-cols-2 gap-2.5">
            <HeroStat label="Spent today" value={stat(failed ? "—" : cedis(summary.data?.today_spending))} />
            <HeroStat label="In progress" value={stat(failed ? "—" : summary.data?.active_orders ?? 0)} />
            <HeroStat label="Completed" value={stat(failed ? "—" : summary.data?.successful_orders ?? 0)} />
            <HeroStat label="All orders" value={stat(failed ? "—" : summary.data?.total_orders ?? 0)} />
          </div>
        }
      >
        <div className="mt-6">
          <p className="text-caption font-medium text-white/60">Available balance</p>
          <div className="mt-1 min-h-12">
            {loading ? (
              <Skeleton className="h-12 w-56" />
            ) : failed ? (
              <LoadError compact what="your balance" onRetry={() => summary.mutate()} className="pt-2" />
            ) : (
              <HeroAmount value={cedis(wallet?.balance)} />
            )}
          </div>
          {wallet?.is_frozen ? (
            <p className="mt-1.5 text-caption font-medium text-[#FFB86B]">
              This wallet is on hold. Contact support before buying or adding funds.
            </p>
          ) : promo > 0 ? (
            <p className="mt-1.5 text-caption text-white/70">
              Plus <span className="tabular font-semibold text-white">{cedis(wallet?.promo_balance)}</span>{" "}
              promotional credit, used first.
            </p>
          ) : null}
        </div>
      </AppHero>

      {params.get("welcome") === "1" || user?.is_email_verified === false ||
      user?.has_accepted_current_terms === false ? (
        <div className="-mt-2 space-y-3">
          {params.get("welcome") === "1" ? (
            <Alert tone="brand" title="Welcome to VerifyGH">
              Add funds to your wallet, then pick a service to get your first number.
            </Alert>
          ) : null}

          {user && !user.is_email_verified ? (
            <Alert
              tone="warn"
              title="Confirm your email to start buying"
              action={
                <Button size="sm" variant="secondary" loading={resending} onClick={resendVerification}>
                  Resend link
                </Button>
              }
            >
              We sent a link to {user.email}. You can add funds now; purchases unlock once the
              address is confirmed.
            </Alert>
          ) : null}

          {user?.has_accepted_current_terms === false ? (
            <Alert
              tone="warn"
              title="Our terms have changed"
              action={
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={async () => {
                    await api.post("/auth/terms/accept/", { accepted: true });
                    await refresh();
                    toast.success("Terms accepted", "You can keep buying.");
                  }}
                >
                  Accept
                </Button>
              }
            >
              Review and accept the current Terms and Acceptable Use Policy to keep buying.
            </Alert>
          ) : null}
        </div>
      ) : null}

      {live.length > 0 ? (
        <Section
          title="In progress"
          description="Live orders - waiting for a code, or with one ready to use."
          action={
            <Link href="/orders?filter=active" className="link text-sm">
              View all
            </Link>
          }
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {live.map((order) => (
              <LiveOrderCard key={order.id} order={order} now={now} />
            ))}
          </div>
        </Section>
      ) : null}

      <QuickBuy market={market.data} failed={Boolean(market.error) && !market.data} onRetry={() => market.mutate()} />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-5 lg:gap-6">
        <Section
          className="lg:col-span-3"
          title={live.length > 0 ? "Earlier orders" : "Recent orders"}
          action={
            <Link href="/orders" className="link text-sm">
              All orders
            </Link>
          }
        >
          <Card className="overflow-hidden rounded-2xl">
            {recentOrders.isLoading ? (
              <RowSkeletons />
            ) : recentOrders.error && !recentOrders.data ? (
              <LoadError what="your orders" onRetry={() => recentOrders.mutate()} />
            ) : finished.length === 0 ? (
              live.length > 0 ? (
                <p className="px-5 py-6 text-sm text-ink-muted">
                  Nothing finished yet - your orders in progress are above.
                </p>
              ) : (
                <EmptyState
                  art={<PhoneMessageArt />}
                  title="No orders yet"
                  description="Your verification numbers will appear here, with their codes."
                  action={<ButtonLink href="/services" size="sm">Buy a number</ButtonLink>}
                />
              )
            ) : (
              <ul className="divide-y divide-line">
                {finished.map((order) => (
                  <OrderStatusRow key={order.id} order={order} />
                ))}
              </ul>
            )}
          </Card>
        </Section>

        <Section
          className="lg:col-span-2"
          title="Wallet activity"
          action={
            <Link href="/transactions" className="link text-sm">
              Statement
            </Link>
          }
        >
          <Card className="overflow-hidden rounded-2xl">
            {recentTransactions.isLoading ? (
              <RowSkeletons rows={3} />
            ) : recentTransactions.error && !recentTransactions.data ? (
              <LoadError what="your transactions" onRetry={() => recentTransactions.mutate()} />
            ) : (recentTransactions.data?.results?.length ?? 0) === 0 ? (
              <EmptyState
                art={<StatementArt />}
                title="No transactions yet"
                description="Deposits, purchases and refunds will be listed here."
              />
            ) : (
              <ul className="divide-y divide-line">
                {recentTransactions.data?.results.map((entry) => (
                  <TransactionRow key={entry.id} entry={entry} />
                ))}
              </ul>
            )}
          </Card>
        </Section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

/**
 * The quickest way to a number: today's popular services as tiles with their
 * live prices - a row that scrolls sideways on a phone, a grid from lg.
 */
function QuickBuy({
  market,
  failed,
  onRetry,
}: {
  market: MarketHome | undefined;
  failed: boolean;
  onRetry: () => unknown;
}) {
  const country = market?.country ?? "US";
  const rows = (market?.popular ?? []).filter((row) => !row.temporarily_unavailable).slice(0, 6);

  return (
    <Section
      title="Get a number"
      description="Today's most-bought services, with their prices in cedis."
      action={
        <Link href="/services" className="link inline-flex min-h-11 items-center gap-1 text-sm sm:min-h-0">
          All services <ArrowRightIcon className="h-3.5 w-3.5" />
        </Link>
      }
    >
      {failed ? (
        <Card className="rounded-2xl">
          <LoadError what="the services" onRetry={onRetry} />
        </Card>
      ) : (
        <ul className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0 lg:grid lg:grid-cols-6 lg:overflow-visible">
          {!market
            ? Array.from({ length: 6 }).map((_, index) => (
                <li key={index} className="w-36 shrink-0 snap-start sm:w-40 lg:w-auto">
                  <Skeleton className="h-36 w-full rounded-2xl" />
                </li>
              ))
            : rows.map((row) => (
                <li key={row.slug} className="w-36 shrink-0 snap-start sm:w-40 lg:w-auto">
                  <QuickTile row={row} country={country} />
                </li>
              ))}
        </ul>
      )}
    </Section>
  );
}

function QuickTile({ row, country }: { row: MarketHome["popular"][number]; country: string }) {
  return (
    <Link
      href={`/services?service=${encodeURIComponent(row.slug)}&country=${country}`}
      className="group flex h-full flex-col gap-3 rounded-2xl border border-line bg-surface p-4 shadow-card transition-all hover:-translate-y-0.5 hover:border-brand-500/40 hover:shadow-raised"
    >
      <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} />
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold text-ink" title={row.name}>
          {row.name}
        </span>
        <span className="tabular mt-0.5 block text-base font-bold tracking-tight text-ink">
          {row.price ? cedis(row.price) : "—"}
        </span>
      </span>
      <span className="mt-auto inline-flex items-center gap-1 text-caption font-semibold text-brand-700">
        Buy
        <ArrowRightIcon className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}

function RowSkeletons({ rows = 4 }: { rows?: number }) {
  return (
    <ul className="divide-y divide-line" aria-hidden>
      {Array.from({ length: rows }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <Skeleton className="h-9 w-9 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-3 w-20" />
          </div>
          <Skeleton className="h-4 w-14" />
        </li>
      ))}
    </ul>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-8" aria-busy>
      <div className="app-hero h-72 rounded-3xl" />
      <Card className="overflow-hidden rounded-2xl">
        <RowSkeletons />
      </Card>
    </div>
  );
}
