"use client";

import Link from "next/link";
import * as React from "react";
import useSWR from "swr";

import {
  CHART_COLORS,
  Delta,
  Donut,
  Legend,
  MetricTile,
  RankedBars,
  StackedBars,
  StatCard,
  TrendChart,
} from "@/components/admin/charts";
import { useAuth } from "@/components/auth-provider";
import {
  AlertIcon,
  BoltIcon,
  ChartIcon,
  CheckCircleIcon,
  ReceiptIcon,
  RefreshIcon,
  UsersIcon,
  WalletIcon,
} from "@/components/icons";
import { Alert, Card, LoadError, Section, Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { AdminCharts, AdminOverview, AdminSystemHealth } from "@/lib/types";

type Range = "7" | "14" | "30" | "90";

const num = (value: string | number | null | undefined) =>
  typeof value === "number" ? value : Number.parseFloat(value ?? "0") || 0;

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

export default function AdminOverviewPage() {
  const { user } = useAuth();
  const [range, setRange] = React.useState<Range>("14");

  const {
    data: overview,
    isLoading,
    error: overviewError,
    mutate: retryOverview,
  } = useSWR<AdminOverview>("/admin/overview/", {
    refreshInterval: 60_000,
  });
  const {
    data: charts,
    error: chartsError,
    mutate: retryCharts,
  } = useSWR<AdminCharts>(["/admin/charts/", { days: range }], { keepPreviousData: true });
  const { data: health } = useSWR<AdminSystemHealth>("/admin/health/");

  const usingMocks =
    health?.verification_provider.is_mock || health?.payment_provider.is_mock;
  const firstName = (user?.full_name ?? "").trim().split(/\s+/)[0];

  return (
    <div className="space-y-6 lg:space-y-8">
      <div className="admin-hero relative overflow-hidden rounded-2xl px-5 py-6 text-white sm:px-7 sm:py-7">
        <div className="relative flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="text-caption font-medium uppercase tracking-wider text-white/60">
              {new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" }).format(
                new Date(),
              )}
            </p>
            <h1 className="mt-1 text-display text-white">
              {greeting()}
              {firstName ? `, ${firstName}` : ""}
            </h1>
            <p className="mt-1 max-w-xl text-sm text-white/70">
              Revenue, orders, deposits and everything that needs attention, at a glance.
            </p>
          </div>
          <HeroRange value={range} onChange={setRange} />
        </div>
        {overview ? (
          <dl className="relative mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-white/10 pt-5 sm:grid-cols-4">
            <HeroFigure label="Revenue today" value={cedis(overview.revenue.today)} />
            <HeroFigure label="Orders today" value={String(overview.orders.today)} />
            <HeroFigure label="Live orders" value={String(overview.orders.active)} />
            <HeroFigure label="New users today" value={String(overview.users.new_today)} />
          </dl>
        ) : (
          <div className="relative mt-6 grid grid-cols-2 gap-6 border-t border-white/10 pt-5 sm:grid-cols-4" aria-busy>
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="space-y-2">
                <div className="h-3 w-20 rounded bg-white/10" />
                <div className="h-6 w-16 rounded bg-white/15" />
              </div>
            ))}
          </div>
        )}
      </div>

      <PlatformStatus health={health} overview={overview} />

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
            <Link href="/admin/system" className="text-sm font-medium underline underline-offset-2">
              Review
            </Link>
          }
        >
          {overview.flags.high > 0 ? `${overview.flags.high} are high severity.` : "None are high severity."}
        </Alert>
      ) : null}

      {health && health.unprocessed_webhooks > 0 ? (
        <Alert tone="danger" title={`${health.unprocessed_webhooks} webhooks failed to process`}>
          These are signature-verified events we could not apply. Money may be sitting uncredited
          - investigate before anything else.
        </Alert>
      ) : null}

      <Section title={`Last ${range} days`} description={`Compared with the ${range} days before.`}>
        {chartsError && !charts ? (
          <Card>
            <LoadError what="the trends" onRetry={() => retryCharts()} />
          </Card>
        ) : !charts ? (
          <StatSkeletons />
        ) : (
          <PeriodStats charts={charts} />
        )}
      </Section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ChartCard
          className="xl:col-span-2"
          title="Revenue and profit"
          description="Earned on orders that delivered a code and on rented numbers, and what was left after provider cost."
          legend={[
            { label: "Revenue", color: CHART_COLORS.brand },
            { label: "Profit", color: CHART_COLORS.info },
            { label: "Provider cost", color: CHART_COLORS.muted, dashed: true },
          ]}
        >
          {charts ? (
            <TrendChart
              label="Revenue and profit by day"
              dates={charts.series.map((day) => day.date)}
              series={[
                {
                  key: "revenue",
                  label: "Revenue",
                  values: charts.series.map((day) => num(day.revenue)),
                  color: CHART_COLORS.brand,
                  area: true,
                },
                {
                  key: "profit",
                  label: "Profit",
                  values: charts.series.map((day) => num(day.profit)),
                  color: CHART_COLORS.info,
                },
                {
                  key: "cost",
                  label: "Provider cost",
                  values: charts.series.map((day) => num(day.cost)),
                  color: CHART_COLORS.muted,
                  dashed: true,
                },
              ]}
              formatValue={(value) => cedis(value)}
              height={260}
            />
          ) : (
            <Skeleton className="h-[260px] w-full" />
          )}
        </ChartCard>

        <ChartCard title="Order outcomes" description={`Every order placed in the last ${range} days.`}>
          {charts ? (
            <Donut
              label="Order outcomes"
              centerLabel="orders"
              centerValue={String(charts.totals.orders)}
              segments={[
                { label: "Delivered", value: charts.totals.completed, color: CHART_COLORS.brand },
                { label: "Refunded", value: charts.totals.refunded, color: CHART_COLORS.info },
                { label: "Failed or expired", value: charts.totals.failed, color: CHART_COLORS.danger },
                {
                  label: "In progress",
                  value: Math.max(
                    charts.totals.orders - charts.totals.completed - charts.totals.refunded - charts.totals.failed,
                    0,
                  ),
                  color: CHART_COLORS.warn,
                },
              ]}
            />
          ) : (
            <Skeleton className="h-44 w-full" />
          )}
        </ChartCard>

        <ChartCard
          className="xl:col-span-2"
          title="Orders by day"
          description="How each day's orders ended."
          legend={[
            { label: "Delivered", color: CHART_COLORS.brand },
            { label: "Refunded", color: CHART_COLORS.info },
            { label: "Failed", color: CHART_COLORS.danger },
            { label: "In progress", color: CHART_COLORS.warn },
          ]}
        >
          {charts ? (
            <StackedBars
              label="Orders by day"
              dates={charts.series.map((day) => day.date)}
              series={[
                { key: "completed", label: "Delivered", values: charts.series.map((d) => d.completed), color: CHART_COLORS.brand },
                { key: "refunded", label: "Refunded", values: charts.series.map((d) => d.refunded), color: CHART_COLORS.info },
                { key: "failed", label: "Failed", values: charts.series.map((d) => d.failed), color: CHART_COLORS.danger },
                { key: "active", label: "In progress", values: charts.series.map((d) => d.active), color: CHART_COLORS.warn },
              ]}
            />
          ) : (
            <Skeleton className="h-60 w-full" />
          )}
        </ChartCard>

        <ChartCard title="Deposit networks" description="Successful wallet top-ups by network.">
          {charts ? (
            charts.payment_methods.length === 0 ? (
              <p className="py-10 text-center text-sm text-ink-muted">No successful deposits in this period.</p>
            ) : (
              <Donut
                label="Deposits by network"
                centerLabel="deposited"
                centerValue={compactCedis(charts.payment_methods.reduce((sum, row) => sum + num(row.amount), 0))}
                segments={charts.payment_methods.map((row, index) => ({
                  label: networkName(row.network),
                  value: num(row.amount),
                  color: NETWORK_COLORS[(row.network ?? "").toUpperCase()] ?? SPARE_COLORS[index % SPARE_COLORS.length],
                }))}
                formatValue={(value) => cedis(value)}
              />
            )
          ) : (
            <Skeleton className="h-44 w-full" />
          )}
        </ChartCard>

        <ChartCard
          className="xl:col-span-2"
          title="Sign-ups and deposits"
          description="New accounts, how many verified their email, and money coming in."
          legend={[
            { label: "Sign-ups", color: CHART_COLORS.brand },
            { label: "Verified", color: CHART_COLORS.aqua },
            { label: "Deposits", color: CHART_COLORS.gold },
          ]}
        >
          {charts ? (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <TrendChart
                label="Sign-ups by day"
                dates={charts.series.map((day) => day.date)}
                series={[
                  {
                    key: "signups",
                    label: "Sign-ups",
                    values: charts.series.map((day) => day.signups),
                    color: CHART_COLORS.brand,
                    area: true,
                  },
                  {
                    key: "verified",
                    label: "Verified",
                    values: charts.series.map((day) => day.verified_signups),
                    color: CHART_COLORS.aqua,
                  },
                ]}
                height={200}
              />
              <TrendChart
                label="Deposits by day"
                dates={charts.series.map((day) => day.date)}
                series={[
                  {
                    key: "deposits",
                    label: "Deposits",
                    values: charts.series.map((day) => num(day.deposits)),
                    color: CHART_COLORS.gold,
                    area: true,
                  },
                ]}
                formatValue={(value) => cedis(value)}
                height={200}
              />
            </div>
          ) : (
            <Skeleton className="h-52 w-full" />
          )}
        </ChartCard>

        <ChartCard title="Top services" description={`By orders, last ${range} days.`}>
          {charts ? (
            <RankedBars
              rows={charts.popular_services.slice(0, 7).map((row) => ({
                label: row.name,
                value: row.orders,
                secondary: cedis(row.revenue),
              }))}
              formatValue={(value) => `${value} ${value === 1 ? "order" : "orders"}`}
            />
          ) : (
            <Skeleton className="h-44 w-full" />
          )}
        </ChartCard>
      </div>

      <Section title="All time" description="Since launch, straight from orders, rentals, refunds and payments.">
        {overviewError && !overview ? (
          <Card>
            <LoadError what="the overview figures" onRetry={() => retryOverview()} />
          </Card>
        ) : isLoading || !overview ? (
          <TileSkeletons />
        ) : (
          <div className="space-y-4">
            <div className="metric-group grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
              <MetricTile
                label="Revenue"
                value={cedis(overview.revenue.total)}
                sublabel={`${cedis(overview.revenue.today)} today · ${cedis(
                  num(overview.revenue.by_product.rentals.revenue) +
                    num(overview.revenue.by_product.extensions.revenue),
                )} from rentals`}
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
                sublabel="Converted at each sale's frozen rate"
              />
              <MetricTile
                label="Refunded"
                value={cedis(overview.refunds.total)}
                sublabel={`${overview.refunds.count} refunds`}
              />
            </div>
            <div className="metric-group grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
              <MetricTile
                label="Users"
                value={overview.users.total}
                sublabel={`${overview.users.active_30d} active in 30 days${
                  overview.users.suspended ? `, ${overview.users.suspended} suspended` : ""
                }`}
                href="/admin/users"
              />
              <MetricTile
                label="Orders"
                value={overview.orders.total}
                sublabel={`${overview.orders.successful} successful, ${overview.orders.failed} failed`}
                href="/admin/orders"
              />
              <MetricTile
                label="Active orders"
                value={overview.orders.active}
                sublabel={`${overview.orders.code_received} awaiting completion`}
                href="/admin/orders"
              />
              <MetricTile
                label="Deposits collected"
                value={cedis(overview.payments.momo_total)}
                sublabel={`${overview.payments.count} payments, ${overview.payments.failed} failed`}
                href="/admin/payments"
              />
            </div>
          </div>
        )}
      </Section>
    </div>
  );
}

/** Each network in the colour people know it by: MTN yellow, Telecel red, AT blue. */
const NETWORK_COLORS: Record<string, string> = {
  MTN: CHART_COLORS.gold,
  TELECEL: CHART_COLORS.danger,
  VODAFONE: CHART_COLORS.danger,
  AT: CHART_COLORS.info,
  AIRTELTIGO: CHART_COLORS.info,
};
const SPARE_COLORS = [CHART_COLORS.brand, CHART_COLORS.aqua, CHART_COLORS.muted];

function networkName(network: string): string {
  const names: Record<string, string> = {
    MTN: "MTN MoMo",
    TELECEL: "Telecel Cash",
    VODAFONE: "Telecel Cash",
    AIRTELTIGO: "AT Money",
    AT: "AT Money",
    CARD: "Card",
  };
  return names[(network ?? "").toUpperCase()] ?? (network || "Other");
}

function compactCedis(value: number): string {
  if (value >= 10_000) return `GH₵${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return cedis(value).replace(/\.00$/, "");
}

function HeroRange({ value, onChange }: { value: Range; onChange: (value: Range) => void }) {
  return (
    <div role="tablist" aria-label="Period" className="flex gap-0.5 rounded-lg bg-white/10 p-0.5 backdrop-blur">
      {(["7", "14", "30", "90"] as Range[]).map((option) => (
        <button
          key={option}
          type="button"
          role="tab"
          aria-selected={option === value}
          onClick={() => onChange(option)}
          className={cn(
            "min-h-9 rounded-md px-3 text-sm font-medium transition-colors",
            option === value ? "bg-white text-navy shadow-card" : "text-white/75 hover:text-white",
          )}
        >
          {option}
          <span className="sm:hidden">d</span>
          <span className="hidden sm:inline"> days</span>
        </button>
      ))}
    </div>
  );
}

function HeroFigure({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-caption text-white/60">{label}</dt>
      <dd className="tabular mt-0.5 truncate text-title text-white">{value}</dd>
    </div>
  );
}

function ChartCard({
  title,
  description,
  legend,
  className,
  children,
}: {
  title: string;
  description?: string;
  legend?: { label: string; color: string; dashed?: boolean }[];
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className={cn("flex flex-col", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-4 pt-4 sm:px-5 sm:pt-5">
        <div className="min-w-0">
          <h2 className="text-heading text-ink">{title}</h2>
          {description ? <p className="mt-0.5 text-sm text-ink-muted">{description}</p> : null}
        </div>
        {legend ? <Legend items={legend} className="pt-1" /> : null}
      </div>
      <div className="flex-1 p-4 sm:p-5">{children}</div>
    </Card>
  );
}

/** The selected period against the one before it - every figure from /admin/charts/. */
function PeriodStats({ charts }: { charts: AdminCharts }) {
  const now = charts.totals;
  const before = charts.previous_totals;
  const days = charts.series;
  const verifiedShare = now.signups ? Math.round((now.verified_signups / now.signups) * 100) : null;
  const margin = num(now.revenue) ? Math.round((num(now.profit) / num(now.revenue)) * 100) : null;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label="Revenue"
        icon={<ChartIcon />}
        value={cedis(now.revenue)}
        delta={<Delta current={num(now.revenue)} previous={num(before.revenue)} />}
        footnote={`${now.completed} delivered ${now.completed === 1 ? "order" : "orders"}`}
        spark={days.map((day) => num(day.revenue))}
        href="/admin/orders"
      />
      <StatCard
        label="Profit"
        icon={<BoltIcon />}
        value={cedis(now.profit)}
        delta={<Delta current={num(now.profit)} previous={num(before.profit)} />}
        footnote={margin === null ? "No revenue in this period" : `${margin}% margin after provider cost`}
        spark={days.map((day) => num(day.profit))}
        sparkColor={CHART_COLORS.info}
      />
      <StatCard
        label="Orders"
        icon={<ReceiptIcon />}
        value={now.orders}
        delta={<Delta current={now.orders} previous={before.orders} />}
        footnote={`${now.completed} delivered, ${now.refunded} refunded, ${now.failed} failed`}
        spark={days.map((day) => day.orders)}
        sparkColor={CHART_COLORS.warn}
        href="/admin/orders"
      />
      <StatCard
        label="Deposits"
        icon={<WalletIcon />}
        value={cedis(now.deposits)}
        delta={<Delta current={num(now.deposits)} previous={num(before.deposits)} />}
        footnote={`${now.deposit_count} successful ${now.deposit_count === 1 ? "top-up" : "top-ups"}`}
        spark={days.map((day) => num(day.deposits))}
        sparkColor={CHART_COLORS.gold}
        href="/admin/payments"
      />
      <StatCard
        label="New users"
        icon={<UsersIcon />}
        value={now.signups}
        delta={<Delta current={now.signups} previous={before.signups} />}
        footnote={verifiedShare === null ? "No sign-ups in this period" : `${verifiedShare}% verified their email`}
        spark={days.map((day) => day.signups)}
        sparkColor={CHART_COLORS.aqua}
        href="/admin/users"
      />
      <StatCard
        label="Delivery rate"
        icon={<CheckCircleIcon />}
        value={now.success_rate === null ? "—" : `${now.success_rate}%`}
        delta={
          now.success_rate !== null && before.success_rate !== null ? (
            <Delta current={now.success_rate} previous={before.success_rate} points />
          ) : undefined
        }
        footnote="Delivered, out of orders that finished"
      />
      <StatCard
        label="Refunded orders"
        icon={<RefreshIcon />}
        value={now.refunded}
        delta={<Delta current={now.refunded} previous={before.refunded} invert />}
        footnote="No code delivered, customer refunded"
        href="/admin/orders"
      />
      <StatCard
        label="Failed or expired"
        icon={<AlertIcon />}
        value={now.failed}
        delta={<Delta current={now.failed} previous={before.failed} invert />}
        footnote="Ended without a code"
        href="/admin/orders"
      />
    </div>
  );
}

function StatSkeletons() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-busy>
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="stat-card space-y-3 p-5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-3 w-28" />
        </div>
      ))}
    </div>
  );
}

function TileSkeletons() {
  return (
    <div className="space-y-4">
      {[0, 1].map((group) => (
        <div key={group} className="metric-group grid-cols-1 sm:grid-cols-2 lg:grid-cols-4" aria-busy>
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="space-y-2 bg-surface p-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-6 w-28" />
              <Skeleton className="h-3 w-24" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * The four things an operator checks first: can we get numbers, can we take
 * money, is pricing configured, is anything suspicious open. Straight from
 * /admin/health/ and the overview - nothing inferred.
 */
function PlatformStatus({
  health,
  overview,
}: {
  health: AdminSystemHealth | undefined;
  overview: AdminOverview | undefined;
}) {
  const rate = health?.exchange_rate;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatusCell
        label="Verification provider"
        href="/admin/providers"
        state={providerState(health?.verification_provider)}
        value={health ? humanKey(health.verification_provider.key) : ""}
        note={
          health?.verification_provider.is_mock
            ? "Mock - no real numbers"
            : health?.verification_provider.healthy
              ? "Reachable"
              : "Not reachable"
        }
      />
      <StatusCell
        label="Payment provider"
        href="/admin/system"
        state={providerState(health?.payment_provider)}
        value={health ? humanKey(health.payment_provider.key) : ""}
        note={
          health?.payment_provider.is_mock
            ? "Mock - no real money"
            : health?.payment_provider.healthy
              ? "Reachable"
              : "Not reachable"
        }
      />
      <StatusCell
        label="Pricing exchange rate"
        href="/admin/pricing"
        state={!health ? "loading" : rate?.configured ? "ok" : "bad"}
        value={rate?.configured && rate.rate ? `GH₵ ${Number.parseFloat(rate.rate).toFixed(2)} per US$1` : "Not set"}
        note={rate?.configured ? `Source: ${rate.source ?? "manual"}` : "Nothing can be sold until it is set"}
      />
      <StatusCell
        label="Security signals"
        href="/admin/system"
        state={!overview ? "loading" : overview.flags.high > 0 ? "bad" : overview.flags.open > 0 ? "warn" : "ok"}
        value={overview ? (overview.flags.open === 0 ? "None open" : `${overview.flags.open} open`) : ""}
        note={overview ? `${overview.flags.high} high severity` : ""}
      />
    </div>
  );
}

/** A mock is "working" but never what production should run on: amber. */
function providerState(provider: { healthy: boolean; is_mock: boolean } | undefined) {
  if (!provider) return "loading" as const;
  if (!provider.healthy) return "bad" as const;
  return provider.is_mock ? ("warn" as const) : ("ok" as const);
}

function humanKey(key: string): string {
  const names: Record<string, string> = {
    textverified: "TextVerified",
    onlinesim: "OnlineSIM",
    paystack: "Paystack",
    sendi: "Sendi",
    moolre: "Moolre",
    mock: "Mock",
  };
  return names[key] ?? key;
}

function StatusCell({
  label,
  value,
  note,
  state,
  href,
}: {
  label: string;
  value: string;
  note: string;
  state: "ok" | "warn" | "bad" | "loading";
  href: string;
}) {
  const dot = { ok: "bg-success-500", warn: "bg-warn-500", bad: "bg-danger-500", loading: "bg-line-strong" }[state];
  const ring = { ok: "bg-success-500/25", warn: "bg-warn-500/25", bad: "bg-danger-500/25", loading: "" }[state];
  return (
    <Link href={href} className="stat-card group flex items-center gap-3 p-3.5 transition-shadow hover:shadow-raised">
      <span aria-hidden className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-sunken">
        {state !== "loading" ? <span className={cn("absolute inset-1.5 rounded-full", ring)} /> : null}
        {state === "ok" ? (
          // Healthy and live: the dot pulses.
          <span className="absolute h-2.5 w-2.5 animate-pulse-ring rounded-full bg-success-500" />
        ) : null}
        <span className={cn("relative h-2.5 w-2.5 rounded-full", dot)} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-caption text-ink-muted">{label}</span>
        {state === "loading" ? (
          <Skeleton className="mt-1 h-4 w-24" />
        ) : (
          <span className="block truncate text-sm font-semibold text-ink">
            {value}
            <span className="sr-only">
              {state === "ok" ? " (healthy)" : state === "warn" ? " (needs a look)" : " (needs attention)"}
            </span>
          </span>
        )}
        <span className="block truncate text-caption text-ink-faint">{note}</span>
      </span>
    </Link>
  );
}
