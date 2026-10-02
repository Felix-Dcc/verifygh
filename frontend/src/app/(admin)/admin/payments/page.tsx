"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import { PageHeader } from "@/components/app-shell";
import { SearchIcon, WalletIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Card,
  EmptyState,
  Input,
  LoadError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
} from "@/components/ui/primitives";
import { cedis, formatDateTime } from "@/lib/format";
import type { AdminPayment, AdminPaymentDetail, Paginated } from "@/lib/types";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "SUCCESS", label: "Successful" },
  { value: "PENDING", label: "Pending" },
  { value: "PROCESSING", label: "Processing" },
  { value: "FAILED", label: "Failed" },
  { value: "EXPIRED", label: "Expired" },
];

export default function AdminPaymentsPage() {
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<AdminPayment | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading, error, mutate } = useSWR<Paginated<AdminPayment>>([
    "/admin/payments/",
    { status, search: debounced, page, page_size: 25 },
  ]);

  const payments = data?.results ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Payments"
        description="Every Mobile Money collection, and whether it was credited."
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <SegmentedControl
          options={STATUS_FILTERS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          className="lg:flex-1"
        />
        <div className="relative lg:w-72">
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
          <Input
            type="search"
            aria-label="Search payments"
            placeholder="Reference or email"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-11"
          />
        </div>
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <RowSkeletons />
        ) : error && !data ? (
          <LoadError what="the payments" onRetry={() => mutate()} />
        ) : payments.length === 0 ? (
          <EmptyState
            icon={<WalletIcon />}
            title={debounced ? "No payments match that search" : "No payments yet"}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] text-left text-sm">
              <thead className="border-b border-line bg-sunken">
                <tr className="text-caption text-ink-muted">
                  <th scope="col" className="px-5 py-3 font-medium">Reference</th>
                  <th scope="col" className="px-5 py-3 font-medium">User</th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">Amount</th>
                  <th scope="col" className="px-5 py-3 font-medium">Network</th>
                  <th scope="col" className="px-5 py-3 font-medium">Status</th>
                  <th scope="col" className="px-5 py-3 font-medium">Credited</th>
                  <th scope="col" className="px-5 py-3 font-medium">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {payments.map((payment) => (
                  <tr
                    key={payment.id}
                    onClick={() => setSelected(payment)}
                    className="cursor-pointer transition-colors hover:bg-sunken/60"
                  >
                    <td className="tabular whitespace-nowrap px-5 py-3.5 font-medium text-ink">
                      {payment.reference}
                      {payment.provider_reference ? (
                        <span className="block text-caption font-normal text-ink-faint">
                          {payment.provider}: {payment.provider_reference}
                        </span>
                      ) : null}
                    </td>
                    <td className="max-w-[12rem] truncate px-5 py-3.5 text-ink-soft">
                      {payment.user_email}
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 text-right font-medium text-ink">
                      {cedis(payment.amount)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-soft">
                      {payment.network}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={payment.status} />
                      {payment.failure_reason && !payment.credited_at ? (
                        <span
                          className="mt-1 block max-w-[14rem] truncate text-caption text-ink-muted"
                          title={payment.failure_reason}
                        >
                          {payment.failure_reason}
                        </span>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                      {payment.credited_at ? formatDateTime(payment.credited_at) : "-"}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                      {formatDateTime(payment.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data?.pagination ? (
        <Pagination
          page={data.pagination.page}
          pages={data.pagination.pages}
          count={data.pagination.count}
          hasNext={data.pagination.has_next}
          hasPrevious={data.pagination.has_previous}
          onChange={setPage}
          noun="payments"
        />
      ) : null}

      <p className="text-caption leading-relaxed text-ink-muted">
        A payment is credited only by a signature-verified provider callback, or by our own
        reconciliation call to the provider. A payment showing Successful but not Credited is
        worth investigating immediately.
      </p>

      <PaymentDialog payment={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

/* ------------------------------------------------------------------ */

/** What Paystack's raw `data.status` meant for the customer at that moment. */
const PROVIDER_STEPS: Record<string, string> = {
  send_otp: "asked for a code by SMS",
  pay_offline: "waiting for approval on the phone",
  success: "paid",
  failed: "failed",
  abandoned: "abandoned",
  timeout: "timed out",
  reversed: "reversed",
  pending: "pending",
  ongoing: "in progress",
  processing: "processing",
  queued: "queued",
};

function providerStep(raw: string) {
  if (!raw) return "-";
  const meaning = PROVIDER_STEPS[raw];
  return meaning && meaning !== raw ? `${raw} - ${meaning}` : raw;
}

/** Everything support needs to answer "why did this deposit fail?". */
function PaymentDialog({
  payment,
  onClose,
}: {
  payment: AdminPayment | null;
  onClose: () => void;
}) {
  const { data: detail, error, mutate } = useSWR<AdminPaymentDetail>(
    payment ? `/admin/payments/${payment.reference}/` : null,
  );

  if (!payment) return null;
  const reason = detail?.failure_reason ?? payment.failure_reason;

  return (
    <Dialog
      open={Boolean(payment)}
      onClose={onClose}
      title={payment.reference}
      description={`${cedis(payment.amount)} - ${payment.network} - ${payment.user_email}`}
    >
      <div className="space-y-4">
        <dl className="divide-y divide-line rounded-xl border border-line">
          <Row label="Status" value={payment.status} />
          {reason ? <Row label={`Reason (${payment.provider})`} value={reason} /> : null}
          <Row label="Started" value={formatDateTime(payment.created_at)} />
          <Row
            label="Finished"
            value={payment.completed_at ? formatDateTime(payment.completed_at) : "-"}
          />
          <Row
            label="Credited"
            value={payment.credited_at ? formatDateTime(payment.credited_at) : "-"}
          />
        </dl>

        {error && !detail ? (
          <LoadError what="the payment details" onRetry={() => mutate()} />
        ) : !detail ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        ) : (
          <>
            <div>
              <p className="mb-2 text-caption font-medium text-ink-muted">With the provider</p>
              <dl className="divide-y divide-line rounded-xl border border-line">
                <Row label="First answer" value={providerStep(detail.provider_status_initial)} />
                <Row label="Last answer" value={providerStep(detail.provider_status_latest)} />
                <Row
                  label="Last checked"
                  value={
                    detail.provider_checked_at ? formatDateTime(detail.provider_checked_at) : "-"
                  }
                />
                <Row label="Codes tried" value={String(detail.otp_attempts)} />
                {detail.instructions ? (
                  <Row label="Shown to customer" value={detail.instructions} />
                ) : null}
              </dl>
            </div>

            <div>
              <p className="mb-2 text-caption font-medium text-ink-muted">Phone</p>
              <dl className="divide-y divide-line rounded-xl border border-line">
                <Row label="Number" value={detail.phone_suffix || "-"} />
                <Row label="Network" value={detail.network_label || payment.network} />
                {detail.prefix_network && detail.prefix_network !== payment.network ? (
                  <Row label="Number looks like" value={detail.prefix_network} />
                ) : null}
                {detail.network_source ? (
                  <Row label="Network chosen by" value={detail.network_source} />
                ) : null}
              </dl>
            </div>

            <div>
              <p className="mb-2 text-caption font-medium text-ink-muted">Provider callbacks</p>
              {detail.webhook_events.length === 0 ? (
                <p className="text-sm text-ink-muted">
                  None. The result came from our own check with the provider.
                </p>
              ) : (
                <dl className="divide-y divide-line rounded-xl border border-line">
                  {detail.webhook_events.map((event, index) => (
                    <Row
                      key={`${event.event_type}-${index}`}
                      label={formatDateTime(event.received_at)}
                      value={[
                        event.event_type || "event",
                        event.signature_valid ? "signed" : "BAD SIGNATURE",
                        event.processed ? "applied" : "not applied",
                        event.processing_error,
                      ]
                        .filter(Boolean)
                        .join(" - ")}
                    />
                  ))}
                </dl>
              )}
            </div>
          </>
        )}
      </div>
    </Dialog>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 px-3.5 py-2.5">
      <dt className="shrink-0 text-sm text-ink-muted">{label}</dt>
      <dd className="tabular break-words text-right text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

function RowSkeletons() {
  return (
    <ul className="divide-y divide-line">
      {Array.from({ length: 8 }).map((_, index) => (
        <li key={index} className="flex items-center gap-4 px-5 py-3.5">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-6 w-24 rounded-full" />
        </li>
      ))}
    </ul>
  );
}
