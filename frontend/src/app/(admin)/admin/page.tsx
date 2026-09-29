"use client";

import Link from "next/link";
import * as React from "react";
import useSWR from "swr";

import { PageHeader } from "@/components/app-shell";
import { AreaChart, BarChart, MetricTile, RankedBars } from "@/components/admin/charts";
import { AlertIcon, FlagIcon } from "@/components/icons";
import {
  Alert,
  Card,
  CardHeader,
  SegmentedControl,
  Skeleton,
} from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { AdminCharts, AdminOverview, AdminSystemHealth } from "@/lib/types";

type Range = "7" | "14" | "30" | "90";

export default function AdminOverviewPage() {
  const [range, setRange] = React.useState<Range>("14");

  const { data: overview, isLoading } = useSWR<AdminOverview>("/admin/overview/", {
    refreshInterval: 60_000,
  });
  const { data: charts } = useSWR<AdminCharts>(["/admin/charts/", { days: range }]);
  const { data: health } = useSWR<AdminSystemHealth>("/admin/health/");

  const usingMocks =
    health?.verification_provider.is_mock || health?.payment_provider.is_mock;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Overview"
        description="Revenue, orders, payments and everything that needs attention."
      />

      {usingMocks ? (
        <Alert tone="warn" title="Running on mock providers">
          {health?.payment_provider.is_mock && health?.verification_provider.is_mock
            ? "Both the payment and verification providers are mocks."
            : health?.payment_provider.is_mock
              ? "The payment provider is a mock."
              : "The verification provider is a mock."}{" "}
          No real money moves and no real numbers are issued. Configure the live providers before
          launch - see <span className="font-medium">docs/PROVIDERS.md</span>.
        </Alert>
      ) : null}

      {overview && overview.flags.open > 0 ? (
        <Alert
          tone={overview.flags.high > 0 ? "danger" : "warn"}
          title={`${overview.flags.open} open abuse ${overview.flags.open === 1 ? "signal" : "signals"}`}
          action={
            <Link
              href="/admin/system"
              className="text-sm font-medium underline underline-offset-2"
            >
              Review
            </Link>
          }
        >
          {overview.flags.high > 0
            ? `${overview.flags.high} are high severity.`
            : "None are high severity."}
        </Alert>
      ) : null}

      {health && health.unprocessed_webhooks > 0 ? (
        <Alert tone="danger" title={`${health.unprocessed_webhooks} webhooks failed to process`}>
          These are signature-verified events we could not apply. Money may be sitting uncredited
          - investigate before anything else.
        </Alert>
      ) : null}

      {isLoading || !overview ? (
        <TileSkeletons />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile
              label="Revenue (all time)"
              value={cedis(overview.revenue.total)}
              sublabel={`${cedis(overview.revenue.today)} today`}
            />
            <MetricTile
              label="Gross margin"
              value={cedis(overview.revenue.gross_margin)}
              sublabel={`${overview.revenue.margin_percent}% after provider cost`}
              tone={Number.parseFloat(overview.revenue.gross_margin) >= 0 ? "positive" : "negative"}
            />
            <MetricTile
              label="Provider cost"
              value={cedis(overview.revenue.provider_cost)}
              sublabel="Converted at the order's frozen rate"
            />
            <MetricTile
              label="Refunded"
              value={cedis(overview.refunds.total)}
              sublabel={`${overview.refunds.count} refunds`}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile
              label="Total users"
              value={overview.users.total}
              sublabel={`${overview.users.new_today} new today, ${overview.users.active_30d} active in 30d`}
            />
            <MetricTile
              label="Orders"
              value={overview.orders.total}
              sublabel={`${overview.orders.successful} successful, ${overview.orders.failed} failed`}
            />
            <MetricTile
              label="Active orders"
              value={overview.orders.active}
              sublabel={`${overview.orders.code_received} awaiting completion`}
            />
            <MetricTile
              label="MoMo collected"
              value={cedis(overview.payments.momo_total)}
              sublabel={`${overview.payments.count} payments, ${overview.payments.failed} failed`}
            />
          </div>
        </>
      )}

      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">Trends</h2>
        <SegmentedControl
          options={[
            { value: "7" as Range, label: "7 days" },
            { value: "14" as Range, label: "14 days" },
            { value: "30" as Range, label: "30 days" },
            { value: "90" as Range, label: "90 days" },
          ]}
          value={range}
          onChange={setRange}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Revenue over time" description={`Last ${range} days, in cedis.`} />
          <div className="p-4 pt-2 sm:p-5 sm:pt-2">
            {charts ? (
              <AreaChart
                label="Revenue over time"
                series={charts.revenue.map((row) => ({
                  date: row.date,
                  value: Number.parseFloat(row.revenue),
                }))}
                formatValue={(value) => cedis(value)}
              />
            ) : (
              <Skeleton className="h-44 w-full" />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Orders over time"
            description={
              charts ? `${charts.failure_rate}% of orders failed or expired.` : undefined
            }
          />
          <div className="p-4 pt-2 sm:p-5 sm:pt-2">
            {charts ? (
              <BarChart
                label="Orders over time"
                series={charts.orders.map((row) => ({ date: row.date, value: row.total }))}
              />
            ) : (
              <Skeleton className="h-44 w-full" />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Most popular services" description={`Last ${range} days.`} />
          <div className="p-4 pt-2 sm:p-5 sm:pt-2">
            {charts ? (
              <RankedBars
                rows={charts.popular_services.map((row) => ({
                  label: row.name,
                  value: row.orders,
                  secondary: cedis(row.revenue),
                }))}
                formatValue={(value) => `${value} orders`}
              />
            ) : (
              <Skeleton className="h-44 w-full" />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Payment methods" description="Successful MoMo collections." />
          <div className="p-4 pt-2 sm:p-5 sm:pt-2">
            {charts ? (
              charts.payment_methods.length === 0 ? (
                <p className="py-8 text-center text-sm text-ink-muted">
                  No successful payments in this period.
                </p>
              ) : (
                <RankedBars
                  rows={charts.payment_methods.map((row) => ({
                    label: row.network,
                    value: Number.parseFloat(row.amount),
                    secondary: `${row.count} payments`,
                  }))}
                  formatValue={(value) => cedis(value)}
                />
              )
            ) : (
              <Skeleton className="h-44 w-full" />
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <QuickLink
          href="/admin/users"
          label="Users"
          value={overview?.users.total ?? "-"}
          note={`${overview?.users.suspended ?? 0} suspended`}
        />
        <QuickLink
          href="/admin/orders"
          label="Orders"
          value={overview?.orders.total ?? "-"}
          note={`${overview?.orders.active ?? 0} active`}
        />
        <QuickLink
          href="/admin/payments"
          label="Payments"
          value={overview?.payments.count ?? "-"}
          note={`${overview?.payments.failed ?? 0} failed`}
        />
        <QuickLink
          href="/admin/system"
          label="Abuse signals"
          value={overview?.flags.open ?? "-"}
          note={`${overview?.flags.high ?? 0} high severity`}
          icon={overview && overview.flags.high > 0 ? <AlertIcon className="h-4 w-4" /> : <FlagIcon className="h-4 w-4" />}
        />
      </div>
    </div>
  );
}

function QuickLink({
  href,
  label,
  value,
  note,
  icon,
}: {
  href: string;
  label: string;
  value: React.ReactNode;
  note: string;
  icon?: React.ReactNode;
}) {
  return (
    <Link href={href} className="card p-4 transition-shadow hover:shadow-raised">
      <div className="flex items-center justify-between">
        <p className="text-xs text-ink-muted">{label}</p>
        {icon ? <span className="text-ink-faint">{icon}</span> : null}
      </div>
      <p className="tabular mt-1 text-2xl font-semibold text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-ink-muted">{note}</p>
    </Link>
  );
}

function TileSkeletons() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 8 }).map((_, index) => (
        <Card key={index} className="space-y-2 p-4">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-28" />
          <Skeleton className="h-3 w-24" />
        </Card>
      ))}
    </div>
  );
}
