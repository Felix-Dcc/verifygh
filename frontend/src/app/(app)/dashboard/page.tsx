"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { CountryFlag } from "@/components/country-flag";
import { ChevronRightIcon } from "@/components/icons";
import { PhoneMessageArt, StatementArt } from "@/components/illustrations";
import { OrderStatusRow } from "@/components/orders/order-row";
import { ServiceLogo } from "@/components/service-logo";
import { TransactionRow } from "@/components/wallet/transaction-row";
import {
  Alert,
  Amount,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  LoadError,
  Section,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cedis, groupInternational } from "@/lib/format";
import type {
  MarketHome,
  OrderSummary,
  Paginated,
  Transaction,
  WalletSummary,
} from "@/lib/types";

/**
 * Home: where the money is, what is running, and the quickest way to the next
 * number. Everything here is the customer's own data or the marketplace's real
 * popularity - nothing is filled in to make the page look busy.
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
  const recentTransactions = useSWR<Paginated<Transaction>>(["/transactions/", { page_size: 4 }]);
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
  // Orders already shown under "In progress" are not repeated below it.
  const liveIds = new Set(live.map((order) => order.id));
  const finished = (recentOrders.data?.results ?? []).filter((order) => !liveIds.has(order.id)).slice(0, 5);

  return (
    <div className="space-y-8">
      <PageHeader
        title={firstName ? `${greeting()}, ${firstName}` : greeting()}
        description={TODAY.format(new Date())}
      />

      {params.get("welcome") === "1" || user?.is_email_verified === false ||
      user?.has_accepted_current_terms === false ? (
        <div className="-mt-3 space-y-3">
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

      <BalancePanel
        summary={summary.data}
        loading={summary.isLoading}
        failed={Boolean(summary.error) && !summary.data}
        onRetry={() => summary.mutate()}
      />

      {live.length > 0 ? (
        <Section
          title="In progress"
          description="Open orders - waiting for a code, or with one to use. Open an order to see it live."
        >
          <Card className="overflow-hidden">
            <ul className="divide-y divide-line">
              {live.map((order) => (
                <li key={order.id}>
                  <Link
                    href={`/orders/${order.reference}`}
                    className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-sunken/60 sm:px-5"
                  >
                    <ServiceLogo name={order.service_name} src={order.service_icon} slug={order.service_slug} />
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-2 text-sm font-medium text-ink">
                        <span className="truncate">{order.service_name}</span>
                        <CountryFlag code={order.country_code} size="sm" />
                      </p>
                      <p className="tabular truncate text-caption text-ink-muted">
                        {order.phone_number
                          ? groupInternational(order.phone_number, order.country_dial_code)
                          : "Getting a number…"}
                      </p>
                    </div>
                    <StatusBadge status={order.status} />
                    <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint" />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </Section>
      ) : null}

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
          <Card className="overflow-hidden">
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

        <div className="space-y-8 lg:col-span-2">
          <PopularServices
            market={market.data}
            failed={Boolean(market.error) && !market.data}
            onRetry={() => market.mutate()}
          />

          <Section
            title="Wallet activity"
            action={
              <Link href="/transactions" className="link text-sm">
                All transactions
              </Link>
            }
          >
            <Card className="overflow-hidden">
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
    </div>
  );
}

/* ------------------------------------------------------------------ */

function BalancePanel({
  summary,
  loading,
  failed,
  onRetry,
}: {
  summary: WalletSummary | undefined;
  loading: boolean;
  failed: boolean;
  onRetry: () => unknown;
}) {
  const wallet = summary?.wallet;
  const promo = Number.parseFloat(wallet?.promo_balance ?? "0");

  return (
    <Card className="grid grid-cols-1 gap-6 p-5 sm:p-6 md:grid-cols-3">
      <div className="md:col-span-2">
        <p className="text-sm text-ink-muted">Available balance</p>
        <div className="mt-1.5 min-h-10">
          {loading ? (
            <Skeleton className="h-10 w-48" />
          ) : failed ? (
            <LoadError compact what="your balance" onRetry={onRetry} className="pt-2" />
          ) : (
            <Amount value={cedis(wallet?.balance)} />
          )}
        </div>
        {wallet?.is_frozen ? (
          <p className="mt-1.5 text-caption font-medium text-danger-700">
            This wallet is on hold. Contact support before buying or adding funds.
          </p>
        ) : promo > 0 ? (
          <p className="mt-1.5 text-caption text-ink-muted">
            Plus {cedis(wallet?.promo_balance)} promotional credit, used first.
          </p>
        ) : null}
        <div className="mt-5 flex flex-wrap gap-2">
          <ButtonLink href="/wallet/deposit">Add funds</ButtonLink>
          <ButtonLink href="/services" variant="secondary">
            Buy a number
          </ButtonLink>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-4 border-t border-line pt-5 md:grid-cols-1 md:content-center md:border-l md:border-t-0 md:pl-6 md:pt-0">
        <div>
          <dt className="text-caption text-ink-muted">Spent today</dt>
          <dd className="tabular mt-0.5 text-heading text-ink">
            {loading ? <Skeleton className="h-5 w-20" /> : cedis(summary?.today_spending)}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-ink-muted">Completed orders</dt>
          <dd className="tabular mt-0.5 text-heading text-ink">
            {loading ? <Skeleton className="h-5 w-12" /> : (summary?.successful_orders ?? "—")}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

function PopularServices({
  market,
  failed,
  onRetry,
}: {
  market: MarketHome | undefined;
  failed: boolean;
  onRetry: () => unknown;
}) {
  const country = market?.country ?? "US";
  const rows = (market?.popular ?? []).slice(0, 5);
  return (
    <Section
      title="Popular services"
      action={
        <Link href="/services" className="link text-sm">
          All services
        </Link>
      }
    >
      <Card className="overflow-hidden">
        {failed ? (
          <LoadError what="the services" onRetry={onRetry} />
        ) : !market ? (
          <RowSkeletons rows={4} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nothing popular yet"
            description="The most-bought services will show here. Browse everything on sale meanwhile."
            action={
              <ButtonLink href="/services" size="sm" variant="secondary">
                Browse services
              </ButtonLink>
            }
          />
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((row) => (
              <li key={row.slug}>
                <Link
                  href={`/services?service=${encodeURIComponent(row.slug)}&country=${country}`}
                  className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-sunken/60 sm:px-5"
                >
                  <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{row.name}</span>
                  <span className="tabular text-sm text-ink-soft">
                    {row.price && !row.temporarily_unavailable ? cedis(row.price) : "Unavailable"}
                  </span>
                  <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </Section>
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
      <div className="space-y-2">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-4 w-40" />
      </div>
      <Card className="space-y-4 p-6">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-11 w-60" />
      </Card>
      <Card className="overflow-hidden">
        <RowSkeletons />
      </Card>
    </div>
  );
}
