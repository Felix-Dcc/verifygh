"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import {
  AdminToolbar,
  KpiCard,
  KpiRow,
  ListCard,
  SearchBox,
  TableSkeleton,
  openRow,
} from "@/components/admin/ui";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { CountryFlag } from "@/components/country-flag";
import { AlertIcon, BoltIcon, CheckCircleIcon, ReceiptIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  LoadError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Textarea,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, formatDateTime, groupInternational } from "@/lib/format";
import type { AdminOrder, AdminOverview, Paginated } from "@/lib/types";

type TimelineEntry = {
  status: string;
  label: string;
  detail: string;
  is_system: boolean;
  actor: string | null;
  created_at: string;
};

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "WAITING_FOR_CODE", label: "Waiting" },
  { value: "CODE_RECEIVED", label: "Code received" },
  { value: "COMPLETED", label: "Completed" },
  { value: "FAILED", label: "Failed" },
  { value: "REFUNDED", label: "Refunded" },
];

export default function AdminOrdersPage() {
  const { can } = useAuth();
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  // Opened from a staff alert: start on that reference.
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) setSearch(q.slice(0, 80));
  }, []);
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<AdminOrder | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading, isValidating, error, mutate } = useSWR<Paginated<AdminOrder>>(
    ["/admin/orders/", { status, search: debounced, page, page_size: 25 }],
    { keepPreviousData: true },
  );
  const { data: overview } = useSWR<AdminOverview>("/admin/overview/", { refreshInterval: 60_000 });

  const orders = data?.results ?? [];
  const filter = (value: string) => {
    setStatus((current) => (current === value ? "" : value));
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Orders"
        description="Investigate any order, see its provider reference and timeline, and refund where it is warranted."
      />

      <KpiRow>
        <KpiCard
          icon={<ReceiptIcon />}
          label="Orders today"
          value={overview?.orders.today}
          hint={overview ? `${overview.orders.total.toLocaleString()} all time` : undefined}
          onClick={() => filter("")}
          active={status === ""}
        />
        <KpiCard
          icon={<BoltIcon />}
          tone="info"
          label="Live now"
          value={overview?.orders.active}
          hint="Waiting for a number or code"
          onClick={() => filter("WAITING_FOR_CODE")}
          active={status === "WAITING_FOR_CODE"}
        />
        <KpiCard
          icon={<CheckCircleIcon />}
          label="Completed"
          value={overview?.orders.successful}
          hint={overview ? `${overview.orders.code_received} code received, not closed` : undefined}
          onClick={() => filter("COMPLETED")}
          active={status === "COMPLETED"}
        />
        <KpiCard
          icon={<AlertIcon />}
          tone="danger"
          label="Failed or expired"
          value={overview?.orders.failed}
          hint="All time"
          onClick={() => filter("FAILED")}
          active={status === "FAILED"}
        />
      </KpiRow>

      <AdminToolbar>
        <SegmentedControl
          options={STATUS_FILTERS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          className="lg:flex-1"
        />
        <SearchBox
          label="Search orders"
          placeholder="Reference, email or number"
          value={search}
          onChange={setSearch}
        />
      </AdminToolbar>

      <ListCard
        title={STATUS_FILTERS.find((item) => item.value === status)?.label === "All" ? "All orders" : `${STATUS_FILTERS.find((item) => item.value === status)?.label} orders`}
        count={data?.pagination?.count}
        noun="orders"
        refreshing={isValidating}
        onRefresh={() => mutate()}
      >
        {isLoading ? (
          <TableSkeleton />
        ) : error && !data ? (
          <LoadError what="the orders" onRetry={() => mutate()} />
        ) : orders.length === 0 ? (
          <EmptyState
            icon={<ReceiptIcon />}
            title={debounced ? "No orders match that search" : status ? "No orders with this status" : "No orders yet"}
            description={debounced || status ? "Try another filter, or clear the search." : undefined}
            action={
              debounced || status ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setStatus("");
                    setPage(1);
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-4xl text-left text-sm">
              <thead className="border-b border-line bg-sunken">
                <tr className="text-caption text-ink-muted">
                  <th scope="col" className="px-5 py-3 font-medium">Reference</th>
                  <th scope="col" className="px-5 py-3 font-medium">User</th>
                  <th scope="col" className="px-5 py-3 font-medium">Service</th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">Price</th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">Cost</th>
                  <th scope="col" className="px-5 py-3 font-medium">Status</th>
                  <th scope="col" className="px-5 py-3 font-medium">Placed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {orders.map((order) => (
                  <tr key={order.id} {...openRow(() => setSelected(order), `Open order ${order.reference}`)}>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 font-medium text-ink">
                      {order.reference}
                    </td>
                    <td className="max-w-48 truncate px-5 py-3.5 text-ink-soft">
                      {order.user_email}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink">
                      <span className="inline-flex items-center gap-2.5">
                        <ServiceLogo name={order.service_name} src={order.service_icon} size="sm" />
                        {order.service_name}
                        <span className="inline-flex items-center gap-1.5 text-caption text-ink-muted">
                          <CountryFlag code={order.country_code} size="sm" />
                          {order.country_code}
                        </span>
                      </span>
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 text-right font-medium text-ink">
                      {cedis(order.price)}
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 text-right text-ink-muted">
                      {order.provider_cost === null
                        ? "-"
                        : `$${Number.parseFloat(order.provider_cost).toFixed(2)}`}
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="flex items-center gap-1.5">
                        <StatusBadge status={order.status} />
                        {order.has_code ? <Badge tone="success">Code</Badge> : null}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                      {formatDateTime(order.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>

      {data?.pagination ? (
        <Pagination
          page={data.pagination.page}
          pages={data.pagination.pages}
          count={data.pagination.count}
          hasNext={data.pagination.has_next}
          hasPrevious={data.pagination.has_previous}
          onChange={setPage}
          noun="orders"
        />
      ) : null}

      <OrderDialog
        order={selected}
        onClose={() => setSelected(null)}
        onChanged={() => mutate()}
        canRefund={can("ORDER_REFUND")}
        canCancel={can("ORDER_CANCEL")}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function OrderDialog({
  order,
  onClose,
  onChanged,
  canRefund,
  canCancel,
}: {
  order: AdminOrder | null;
  onClose: () => void;
  onChanged: () => void;
  canRefund: boolean;
  canCancel: boolean;
}) {
  const toast = useToast();
  const [mode, setMode] = React.useState<"details" | "refund" | "cancel">("details");
  const [reason, setReason] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const { data: timeline } = useSWR<TimelineEntry[]>(
    order ? `/admin/orders/${order.reference}/timeline/` : null,
  );

  React.useEffect(() => {
    setMode("details");
    setReason("");
    setAmount(order?.price ?? "");
    setError("");
  }, [order?.reference, order?.price]);

  if (!order) return null;

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    try {
      await action();
      toast.success(message);
      onChanged();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const alreadyRefunded = order.refund_status === "COMPLETED";

  return (
    <Dialog
      open={Boolean(order)}
      onClose={onClose}
      title={order.reference}
      description={`${order.service_name} - ${order.country_code} - ${order.user_email}`}
      dismissible={!busy}
    >
      <div className="space-y-4">
        {error ? (
          <Alert tone="danger" title="Could not complete that">
            {error}
          </Alert>
        ) : null}

        {mode === "details" ? (
          <>
            <dl className="divide-y divide-line rounded-xl border border-line">
              <Row label="Status" value={order.status} />
              <Row label="Customer paid" value={cedis(order.price)} />
              <Row label="Provider" value={order.provider_name} />
              <Row label="Provider order id" value={order.provider_order_id || "-"} />
              <Row
                label="Number"
                value={
                  order.phone_number
                    ? groupInternational(order.phone_number, order.country_dial_code)
                    : "-"
                }
              />
              <Row label="Code received" value={order.has_code ? "Yes" : "No"} />
              <Row label="Refund" value={order.refund_status} />
              <Row label="Placed" value={formatDateTime(order.created_at)} />
              {order.failure_reason ? (
                <Row label="Failure" value={order.failure_reason} />
              ) : null}
            </dl>

            {/* Cost and margin come back null for staff without PRICING_VIEW. */}
            {order.provider_cost !== null ? <PricingSnapshot order={order} /> : null}

            <p className="text-caption text-ink-muted">
              The verification code itself is never shown here. Support can confirm that a message
              arrived without being able to read a customer&apos;s one-time code.
            </p>

            {timeline && timeline.length > 0 ? (
              <div>
                <p className="mb-2 text-sm font-semibold text-ink">Timeline</p>
                <ol className="divide-y divide-line rounded-xl border border-line text-sm">
                  {timeline.map((entry, index) => (
                    <li key={index} className="flex items-start justify-between gap-3 px-3.5 py-2.5">
                      <span className="min-w-0">
                        <span className="block text-ink">{entry.label}</span>
                        {entry.detail ? (
                          <span className="block text-caption text-ink-muted">{entry.detail}</span>
                        ) : null}
                        {!entry.is_system && entry.actor ? (
                          <span className="block text-caption text-ink-faint">by {entry.actor}</span>
                        ) : null}
                      </span>
                      <span className="tabular shrink-0 text-caption text-ink-faint">
                        {formatDateTime(entry.created_at)}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}

            {alreadyRefunded ? (
              <Alert tone="brand" title="Already refunded">
                This order has been refunded. A second refund is refused by the database, not just
                by this screen.
              </Alert>
            ) : null}

            <div className="flex flex-col gap-2 sm:flex-row">
              {canRefund && !alreadyRefunded ? (
                <Button variant="secondary" fullWidth onClick={() => setMode("refund")}>
                  Issue refund
                </Button>
              ) : null}
              {canCancel && !["COMPLETED", "REFUNDED", "FAILED", "EXPIRED", "CANCELLED"].includes(order.status) ? (
                <Button variant="danger" fullWidth onClick={() => setMode("cancel")}>
                  Cancel order
                </Button>
              ) : null}
            </div>
          </>
        ) : null}

        {mode === "refund" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              run(
                () => api.post(`/admin/orders/${order.reference}/refund/`, { amount, reason }),
                "Refund issued",
              );
            }}
            className="space-y-4"
          >
            <Alert tone="warn" title="This credits the customer's wallet">
              A refund writes an immutable ledger entry. It cannot exceed {cedis(order.price)}, and
              it cannot be reversed - only offset by an adjustment.
            </Alert>

            <Field label="Amount" htmlFor="refund-amount" required hint={`Order total: ${cedis(order.price)}`}>
              <Input
                id="refund-amount"
                inputMode="decimal"
                required
                prefix="GH₵"
                value={amount}
                onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ""))}
                className="tabular"
              />
            </Field>

            <Field label="Reason" htmlFor="refund-reason" required hint="At least 5 characters.">
              <Textarea
                id="refund-reason"
                rows={3}
                required
                minLength={5}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. Number was reported as already used, ticket #512"
              />
            </Field>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="secondary" onClick={() => setMode("details")} disabled={busy}>
                Back
              </Button>
              <Button type="submit" loading={busy} disabled={reason.trim().length < 5 || !amount}>
                Refund {cedis(amount || "0")}
              </Button>
            </div>
          </form>
        ) : null}

        {mode === "cancel" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              run(
                () => api.post(`/admin/orders/${order.reference}/cancel/`, { reason }),
                "Order cancelled",
              );
            }}
            className="space-y-4"
          >
            <Alert tone="warn" title="The provider decides">
              We ask the provider to release the number. If it refuses - usually because a code has
              already landed - the cancellation fails rather than leaving our records disagreeing
              with theirs.
            </Alert>

            <Field label="Reason" htmlFor="cancel-reason" required hint="At least 5 characters.">
              <Textarea
                id="cancel-reason"
                rows={3}
                required
                minLength={5}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </Field>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="secondary" onClick={() => setMode("details")} disabled={busy}>
                Back
              </Button>
              <Button type="submit" variant="danger" loading={busy} disabled={reason.trim().length < 5}>
                Cancel and refund
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </Dialog>
  );
}

/**
 * The price this order was sold at, exactly as it was calculated at purchase.
 * Later changes to FX, markup or provider cost never touch it. Orders placed
 * before the full snapshot existed show what they recorded.
 */
function PricingSnapshot({ order }: { order: AdminOrder }) {
  const snap = order.price_breakdown ?? {};
  const cost = Number.parseFloat(order.provider_cost ?? "0");
  const rate = Number.parseFloat(order.exchange_rate ?? "0");
  const ghsCost = snap.base_cost ? Number.parseFloat(snap.base_cost) : cost * rate;
  const price = Number.parseFloat(order.price);
  const profit = price - ghsCost;
  const applied = snap.applied ?? {};
  const markup =
    applied.markup_type === "FIXED"
      ? `+ ${cedis(String(applied.markup_fixed))}`
      : applied.markup_type === "HYBRID"
        ? `${applied.markup_percent}% + ${cedis(String(applied.markup_fixed))}`
        : applied.markup_percent !== undefined
          ? `${applied.markup_percent}%`
          : "-";
  return (
    <div>
      <p className="mb-2 text-sm font-semibold text-ink">Pricing snapshot at purchase</p>
      <dl className="divide-y divide-line rounded-xl border border-line">
        <Row label="Provider cost" value={`${order.provider_currency === "USD" ? "$" : `${order.provider_currency} `}${cost.toFixed(4)}`} />
        <Row label="VerifyGH Pricing FX Rate" value={`${rate.toFixed(4)}${snap.fx_mode ? ` (${String(snap.fx_mode).toLowerCase()})` : ""}`} />
        <Row label="Provider cost in cedis" value={cedis(ghsCost.toFixed(2))} />
        <Row label="Markup" value={`${markup}${snap.pricing_rule_name ? ` - ${snap.pricing_rule_name}` : ""}`} />
        {snap.calculated_price ? <Row label="Calculated price" value={cedis(snap.calculated_price)} /> : null}
        {snap.override_price ? <Row label="Manual override" value={cedis(snap.override_price)} /> : null}
        <Row label="Customer paid" value={cedis(order.price)} />
        <Row label="Gross profit" value={cedis(profit.toFixed(2))} />
        <Row label="Gross margin %" value={price > 0 ? `${((profit / price) * 100).toFixed(2)}%` : "-"} />
        <Row label="Provider transaction" value={order.provider_order_id || "-"} />
        <Row label="Priced at" value={snap.quoted_at ? formatDateTime(snap.quoted_at) : formatDateTime(order.created_at)} />
      </dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 px-3.5 py-2.5">
      <dt className="shrink-0 text-sm text-ink-muted">{label}</dt>
      <dd className="tabular break-all text-right text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}
