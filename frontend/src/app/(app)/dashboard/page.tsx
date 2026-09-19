"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { ServiceAvatar } from "@/components/brand";
import {
  ArrowRightIcon,
  BoltIcon,
  CheckCircleIcon,
  ClockIcon,
  GridIcon,
  PlusIcon,
  ReceiptIcon,
  WalletIcon,
} from "@/components/icons";
import { OrderStatusRow } from "@/components/orders/order-row";
import {
  Alert,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cedis, relativeTime, signedCedis } from "@/lib/format";
import type { OrderSummary, Paginated, Transaction, WalletSummary } from "@/lib/types";

export default function DashboardPage() {
  return (
    <React.Suspense fallback={null}>
      <Dashboard />
    </React.Suspense>
  );
}

function Dashboard() {
  const { user, refresh } = useAuth();
  const params = useSearchParams();
  const toast = useToast();

  const { data: summary, isLoading: summaryLoading } = useSWR<WalletSummary>("/wallet/summary/");
  const { data: activeOrders } = useSWR<OrderSummary[]>("/orders/active/", {
    // Active orders change on their own, so keep this fresh while the tab is open.
    refreshInterval: 15_000,
  });
  const { data: recentOrders, isLoading: ordersLoading } = useSWR<Paginated<OrderSummary>>([
    "/orders/",
    { page_size: 5 },
  ]);
  const { data: recentTransactions, isLoading: txLoading } = useSWR<Paginated<Transaction>>([
    "/transactions/",
    { page_size: 5 },
  ]);

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

  return (
    <div className="space-y-5">
      <PageHeader
        title={firstName ? `Hello, ${firstName}` : "Your dashboard"}
        description="Your wallet, your orders and everything in flight."
      />

      {params.get("welcome") === "1" ? (
        <Alert tone="brand" title="Welcome to VerifyGH">
          Add money to your wallet to buy your first verification number.
        </Alert>
      ) : null}

      {user && !user.is_email_verified ? (
        <Alert
          tone="warn"
          title="Confirm your email to start buying"
          action={
            <Button size="sm" variant="secondary" loading={resending} onClick={resendVerification}>
              Resend
            </Button>
          }
        >
          We sent a link to {user.email}. You can add money now, but purchases stay locked until
          your address is confirmed.
        </Alert>
      ) : null}

      {user?.has_accepted_current_terms === false ? (
        <Alert
          tone="warn"
          title="Our terms have been updated"
          action={
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                await api.post("/auth/terms/accept/", { accepted: true });
                await refresh();
                toast.success("Thanks", "You are all set.");
              }}
            >
              Accept
            </Button>
          }
        >
          Review and accept the current Terms and Acceptable Use Policy to keep buying.
        </Alert>
      ) : null}

      <BalanceCard summary={summary} loading={summaryLoading} />

      <QuickActions />

      <div className="grid gap-4 lg:grid-cols-3">
        <StatCard
          label="Today's spending"
          value={cedis(summary?.today_spending)}
          loading={summaryLoading}
          icon={<BoltIcon className="h-5 w-5" />}
        />
        <StatCard
          label="Successful orders"
          value={String(summary?.successful_orders ?? 0)}
          loading={summaryLoading}
          icon={<CheckCircleIcon className="h-5 w-5" />}
        />
        <StatCard
          label="Active orders"
          value={String(summary?.active_orders ?? 0)}
          loading={summaryLoading}
          icon={<ClockIcon className="h-5 w-5" />}
        />
      </div>

      {live.length > 0 ? (
        <Card>
          <CardHeader
            title="In progress"
            description="These orders are still running. Tap one to watch it live."
          />
          <ul className="mt-2 divide-y divide-line">
            {live.map((order) => (
              <li key={order.id}>
                <Link
                  href={`/orders/${order.reference}`}
                  className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-canvas sm:px-5"
                >
                  <ServiceAvatar name={order.service_name} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {order.service_name}{" "}
                      <span className="text-ink-muted">{order.country_flag}</span>
                    </p>
                    <p className="tabular truncate text-xs text-ink-muted">
                      {order.phone_number || "Assigning a number..."}
                    </p>
                  </div>
                  <StatusBadge status={order.status} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Recent orders"
            action={
              <Link
                href="/orders"
                className="text-sm font-medium text-brand-700 hover:underline"
              >
                View all
              </Link>
            }
          />
          {ordersLoading ? (
            <RowSkeletons />
          ) : (recentOrders?.results?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<ReceiptIcon />}
              title="No orders yet"
              description="Buy your first verification number and it will show up here."
              action={
                <Link href="/services">
                  <Button size="sm">Browse services</Button>
                </Link>
              }
            />
          ) : (
            <ul className="mt-2 divide-y divide-line">
              {recentOrders?.results.map((order) => (
                <OrderStatusRow key={order.id} order={order} />
              ))}
            </ul>
          )}
        </Card>

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
          {txLoading ? (
            <RowSkeletons />
          ) : (recentTransactions?.results?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<WalletIcon />}
              title="No transactions yet"
              description="Add money to your wallet to get started."
              action={
                <Link href="/wallet/deposit">
                  <Button size="sm">Add money</Button>
                </Link>
              }
            />
          ) : (
            <ul className="mt-2 divide-y divide-line">
              {recentTransactions?.results.map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-center gap-3 px-4 py-3.5 sm:px-5"
                >
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
                    <p className="truncate text-sm font-medium text-ink">{entry.description}</p>
                    <p className="text-xs text-ink-muted">{relativeTime(entry.created_at)}</p>
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
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function BalanceCard({
  summary,
  loading,
}: {
  summary: WalletSummary | undefined;
  loading: boolean;
}) {
  const wallet = summary?.wallet;

  return (
    <div className="relative overflow-hidden rounded-2xl bg-brand-700 p-5 text-white shadow-raised sm:p-6">
      <div
        className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-brand-500/30 blur-2xl"
        aria-hidden
      />
      <div className="relative flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-brand-200">Wallet balance</p>
          {loading ? (
            <Skeleton className="mt-2 h-9 w-40 bg-white/20" />
          ) : (
            <p className="tabular mt-1 text-4xl font-semibold tracking-tight">
              {cedis(wallet?.balance)}
            </p>
          )}
          <p className="mt-1.5 text-xs text-brand-200">
            {wallet?.is_frozen
              ? "This wallet is on hold. Contact support."
              : `${cedis(wallet?.total_deposited)} added in total`}
          </p>
        </div>
        <Link href="/wallet/deposit">
          <Button size="lg" variant="inverse" icon={<PlusIcon className="h-5 w-5" />}>
            Add money
          </Button>
        </Link>
      </div>
    </div>
  );
}

function QuickActions() {
  const actions = [
    { href: "/services", label: "Buy verification", icon: <GridIcon className="h-5 w-5" /> },
    { href: "/orders", label: "Orders", icon: <ReceiptIcon className="h-5 w-5" /> },
    { href: "/transactions", label: "Transactions", icon: <WalletIcon className="h-5 w-5" /> },
    { href: "/account", label: "Profile", icon: <CheckCircleIcon className="h-5 w-5" /> },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {actions.map((action) => (
        <Link
          key={action.href}
          href={action.href}
          className="card flex flex-col items-start gap-2.5 p-4 transition-shadow hover:shadow-raised"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
            {action.icon}
          </span>
          <span className="text-sm font-medium text-ink">{action.label}</span>
        </Link>
      ))}
    </div>
  );
}

function StatCard({
  label,
  value,
  loading,
  icon,
}: {
  label: string;
  value: string;
  loading: boolean;
  icon: React.ReactNode;
}) {
  return (
    <Card className="flex items-center gap-3.5 p-4">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-xs text-ink-muted">{label}</p>
        {loading ? (
          <Skeleton className="mt-1.5 h-5 w-16" />
        ) : (
          <p className="tabular text-lg font-semibold text-ink">{value}</p>
        )}
      </div>
    </Card>
  );
}

function RowSkeletons() {
  return (
    <ul className="mt-2 divide-y divide-line">
      {Array.from({ length: 4 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
          <Skeleton className="h-9 w-9 rounded-xl" />
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
