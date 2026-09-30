"use client";

import * as React from "react";
import useSWR from "swr";

import { MetricTile } from "@/components/admin/charts";
import { Pagination } from "@/components/admin/pagination";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { CountryFlag } from "@/components/country-flag";
import { FlagIcon, SearchIcon } from "@/components/icons";
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
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Textarea,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, formatDateTime } from "@/lib/format";
import type {
  AdminNumberIssue,
  AdminNumberIssueDetail,
  NumberIssueBreakdown,
  NumberIssueMetrics,
  Paginated,
} from "@/lib/types";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "OPEN", label: "Open" },
  { value: "IN_REVIEW", label: "In review" },
  { value: "REFUNDED", label: "Refunded" },
  { value: "REPLACED", label: "Replaced" },
  { value: "REJECTED", label: "Rejected" },
  { value: "RESOLVED", label: "Resolved" },
];

const PROVIDER_REPORT_TEXT: Record<AdminNumberIssue["provider_report"], string> = {
  NOT_SUPPORTED: "Provider has no report mechanism",
  NOT_SENT: "Not sent",
  ACCEPTED: "Accepted by provider",
  REFUSED: "Refused by provider",
};

export default function AdminNumberIssuesPage() {
  const { can } = useAuth();
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<string | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading, mutate } = useSWR<Paginated<AdminNumberIssue>>([
    "/admin/number-issues/",
    { status, search: debounced, page, page_size: 25 },
  ]);
  const { data: metrics, mutate: mutateMetrics } = useSWR<NumberIssueMetrics>(
    can("METRICS_VIEW") ? ["/admin/number-issues-metrics/", { days: 30 }] : null,
  );

  const issues = data?.results ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Number issues"
        description="Customer reports about delivered numbers - most often a service treating a number as already registered. Reports are evidence, not proof: review each one."
      />

      {metrics ? <Metrics metrics={metrics} /> : null}

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
            aria-label="Search reports"
            placeholder="Report, order or email"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-11"
          />
        </div>
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <RowSkeletons />
        ) : issues.length === 0 ? (
          <EmptyState
            icon={<FlagIcon />}
            title={debounced || status ? "No reports match" : "No reports yet"}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[64rem] text-left text-sm">
              <thead className="border-b border-line bg-sunken">
                <tr className="text-caption text-ink-muted">
                  <th scope="col" className="px-5 py-3 font-medium">Order</th>
                  <th scope="col" className="px-5 py-3 font-medium">Customer</th>
                  <th scope="col" className="px-5 py-3 font-medium">Provider</th>
                  <th scope="col" className="px-5 py-3 font-medium">Service</th>
                  <th scope="col" className="px-5 py-3 font-medium">Number</th>
                  <th scope="col" className="px-5 py-3 font-medium">Issue</th>
                  <th scope="col" className="px-5 py-3 font-medium">Status</th>
                  <th scope="col" className="px-5 py-3 font-medium">Created</th>
                  <th scope="col" className="px-5 py-3 font-medium">Resolution</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {issues.map((issue) => (
                  <tr
                    key={issue.id}
                    onClick={() => setSelected(issue.reference)}
                    className="cursor-pointer transition-colors hover:bg-sunken/60"
                  >
                    <td className="tabular whitespace-nowrap px-5 py-3.5 font-medium text-ink">
                      {issue.order_reference}
                    </td>
                    <td className="max-w-[12rem] truncate px-5 py-3.5 text-ink-soft">
                      {issue.customer_email}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-soft">
                      {issue.provider_name}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink">
                      <span className="inline-flex items-center gap-2.5">
                        <ServiceLogo name={issue.service_name} src={issue.service_icon} size="sm" />
                        {issue.service_name}
                        <span className="inline-flex items-center gap-1.5 text-caption text-ink-muted">
                          <CountryFlag code={issue.country_code} size="sm" />
                          {issue.country_code}
                        </span>
                      </span>
                    </td>
                    <td className="tabular whitespace-nowrap px-5 py-3.5 text-ink-soft">
                      {issue.number_masked || "-"}
                    </td>
                    <td className="px-5 py-3.5 text-ink">
                      <span className="flex items-center gap-1.5">
                        {issue.reason === "NUMBER_ALREADY_LINKED"
                          ? "Possible reused number"
                          : issue.reason_label}
                        {issue.needs_review ? <Badge tone="warn">Look closer</Badge> : null}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={issue.status} />
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                      {formatDateTime(issue.created_at)}
                    </td>
                    <td className="max-w-[14rem] truncate px-5 py-3.5 text-ink-muted">
                      {issue.resolution_note || "-"}
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
          noun="reports"
        />
      ) : null}

      <IssueDialog
        reference={selected}
        onClose={() => setSelected(null)}
        onChanged={() => {
          mutate();
          mutateMetrics();
        }}
        canManage={can("ISSUE_MANAGE")}
        canRemedy={can("ORDER_REFUND")}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Metrics({ metrics }: { metrics: NumberIssueMetrics }) {
  const rate = metrics.possible_reuse_rate_percent;
  return (
    <div className="space-y-3">
      <div className="metric-group grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          label="Reported possible reuse (30d)"
          value={metrics.possible_reuse_reports}
          sublabel={
            rate === null
              ? "No delivered orders yet"
              : `${rate}% of ${metrics.sms_received} orders that received a code`
          }
        />
        <MetricTile
          label="Open reports"
          value={metrics.open_cases}
          sublabel={`${metrics.needs_review} marked "look closer"`}
        />
        <MetricTile
          label="Refunded / replaced"
          value={`${metrics.refunded_orders} / ${metrics.replacement_orders}`}
          sublabel={`${cedis(metrics.refunded_amount)} refunded, ${metrics.rejected} not approved`}
        />
        <MetricTile
          label="Flagged numbers avoided"
          value={metrics.numbers_turned_away}
          sublabel={`${metrics.flagged_numbers} numbers flagged for a service`}
        />
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Breakdown title="By service" rows={metrics.by_service} />
        <Breakdown title="By provider" rows={metrics.by_provider} />
      </div>
      <p className="text-xs text-ink-muted">{metrics.note}</p>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: NumberIssueBreakdown[] }) {
  return (
    <Card className="p-4">
      <p className="mb-2 text-sm font-semibold text-ink">{title}</p>
      {rows.length === 0 ? (
        <p className="text-sm text-ink-muted">Nothing in this period.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-ink-muted">
              <th scope="col" className="py-1 text-left font-medium">Name</th>
              <th scope="col" className="py-1 text-right font-medium">Delivered</th>
              <th scope="col" className="py-1 text-right font-medium">Reuse reports</th>
              <th scope="col" className="py-1 text-right font-medium">Reported rate</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.slice(0, 8).map((row) => (
              <tr key={row.name}>
                <td className="py-1.5 text-ink">{row.name}</td>
                <td className="tabular py-1.5 text-right text-ink-soft">{row.delivered}</td>
                <td className="tabular py-1.5 text-right text-ink-soft">
                  {row.possible_reuse_reports}
                </td>
                <td className="tabular py-1.5 text-right text-ink-soft">
                  {row.reported_rate_percent === null ? "-" : `${row.reported_rate_percent}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

type Verb = "review" | "refund" | "replace" | "reject" | "resolve";

const VERBS: Record<Verb, { label: string; done: string; warning?: string; tone?: "danger" }> = {
  review: { label: "Start review", done: "Marked as in review" },
  refund: {
    label: "Approve refund",
    done: "Refund issued",
    warning:
      "Credits the customer's wallet with the full order price through the ledger. It cannot be reversed - only offset by an adjustment.",
  },
  replace: {
    label: "Replace number",
    done: "Replacement ordered",
    warning:
      "Gives the customer a new number for the same service at no charge. The reported number is avoided.",
  },
  reject: {
    label: "Reject claim",
    done: "Report rejected",
    warning: "The customer is told we could not confirm the problem. No money moves.",
    tone: "danger",
  },
  resolve: { label: "Mark resolved", done: "Report resolved", warning: "Closes the report with no money moving." },
};

function IssueDialog({
  reference,
  onClose,
  onChanged,
  canManage,
  canRemedy,
}: {
  reference: string | null;
  onClose: () => void;
  onChanged: () => void;
  canManage: boolean;
  canRemedy: boolean;
}) {
  const toast = useToast();
  const [verb, setVerb] = React.useState<Verb | null>(null);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const { data: issue, mutate } = useSWR<AdminNumberIssueDetail>(
    reference ? `/admin/number-issues/${reference}/` : null,
  );

  React.useEffect(() => {
    setVerb(null);
    setReason("");
    setError("");
  }, [reference]);

  if (!reference) return null;

  const open = issue ? ["OPEN", "IN_REVIEW"].includes(issue.status) : false;
  const replacementFailed =
    issue?.status === "REPLACED" &&
    ["EXPIRED", "FAILED", "CANCELLED", "REFUNDED"].includes(issue.replacement_order_status ?? "");
  const available: Verb[] = [];
  if (issue) {
    if (canManage && issue.status === "OPEN") available.push("review");
    if (canRemedy && (open || replacementFailed)) available.push("refund");
    if (canRemedy && open) available.push("replace");
    if (canManage && open) available.push("reject", "resolve");
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!verb || !issue) return;
    setBusy(true);
    setError("");
    try {
      await api.post(`/admin/number-issues/${issue.reference}/${verb}/`, { reason });
      toast.success(VERBS[verb].done);
      await mutate();
      onChanged();
      setVerb(null);
      setReason("");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={Boolean(reference)}
      onClose={onClose}
      title={issue ? `${issue.reference} - ${issue.order_reference}` : "Loading"}
      description={issue ? `${issue.service_name} - ${issue.country_code} - ${issue.customer_email}` : undefined}
      dismissible={!busy}
    >
      {!issue ? (
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : (
        <div className="space-y-4">
          {error ? (
            <Alert tone="danger" title="Could not complete that">
              {error}
            </Alert>
          ) : null}

          {verb ? (
            <form onSubmit={submit} className="space-y-4">
              {VERBS[verb].warning ? (
                <Alert tone={verb === "refund" ? "warn" : "info"} title={VERBS[verb].label}>
                  {VERBS[verb].warning}
                  {verb === "refund" ? ` Amount: ${cedis(issue.price)}.` : null}
                </Alert>
              ) : null}
              <Field label="Reason" htmlFor="issue-action-reason" required hint="At least 5 characters. Recorded in the admin log.">
                <Textarea
                  id="issue-action-reason"
                  rows={3}
                  required
                  minLength={5}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </Field>
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button variant="secondary" onClick={() => setVerb(null)} disabled={busy}>
                  Back
                </Button>
                <Button
                  type="submit"
                  variant={VERBS[verb].tone === "danger" ? "danger" : "primary"}
                  loading={busy}
                  disabled={reason.trim().length < 5}
                >
                  {VERBS[verb].label}
                </Button>
              </div>
            </form>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={issue.status} />
                <Badge tone={issue.qualifies ? "success" : "neutral"}>
                  {issue.qualifies ? "Fits the policy" : "Review individually"}
                </Badge>
                {issue.needs_review ? <Badge tone="warn">Look closer</Badge> : null}
              </div>

              <dl className="divide-y divide-line rounded-xl border border-line">
                <Row label="Issue" value={issue.reason_label} />
                <Row label="Number" value={issue.number_masked || "-"} />
                <Row label="Provider" value={issue.provider_name} />
                <Row label="Order status" value={issue.order_status} />
                <Row label="Paid" value={cedis(issue.price)} />
                <Row label="Number assigned" value={when(issue.timeline.assigned_at)} />
                <Row label="SMS received" value={when(issue.timeline.sms_received_at)} />
                <Row label="Reported" value={when(issue.timeline.reported_at)} />
                <Row label="Refund" value={issue.refund ? `${cedis(issue.refund.amount)} (${issue.refund.reference})` : issue.timeline.refund_status} />
                <Row label="Provider notified" value={PROVIDER_REPORT_TEXT[issue.provider_report]} />
                {issue.replacement_order_reference ? (
                  <Row
                    label="Replacement"
                    value={`${issue.replacement_order_reference} (${issue.replacement_order_status})`}
                  />
                ) : null}
                {issue.resolution_note ? (
                  <Row
                    label="Resolution"
                    value={`${issue.resolution_note}${issue.resolved_by_email ? ` - ${issue.resolved_by_email}` : ""}`}
                  />
                ) : null}
              </dl>

              {issue.details ? (
                <div>
                  <p className="mb-1 text-sm font-semibold text-ink">Customer&apos;s words</p>
                  <p className="rounded-lg bg-sunken px-3.5 py-2.5 text-sm text-ink-soft">{issue.details}</p>
                </div>
              ) : null}

              <div>
                <p className="mb-2 text-sm font-semibold text-ink">Policy check</p>
                <ul className="space-y-1 text-sm">
                  {issue.qualification.map((item) => (
                    <li key={item.check} className="flex items-start gap-2">
                      <span className={item.ok ? "text-success-700" : "text-danger-700"} aria-hidden>
                        {item.ok ? "✓" : "✗"}
                      </span>
                      <span className="text-ink-soft">{item.check}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {issue.risk_flags.length > 0 ? (
                <Alert tone="warn" title="Worth a closer look">
                  <ul className="list-disc space-y-0.5 pl-4">
                    {issue.risk_flags.map((flag) => (
                      <li key={flag.code}>{flag.detail}</li>
                    ))}
                  </ul>
                  <p className="mt-2">
                    These are patterns, not proof. Several reports can be bad luck with a recycled
                    number pool.
                  </p>
                </Alert>
              ) : null}

              {issue.history ? (
                <div>
                  <p className="mb-2 text-sm font-semibold text-ink">This number&apos;s history with us</p>
                  <p className="mb-2 text-xs text-ink-muted">
                    Issued {issue.history.times_issued} time(s), {issue.history.reports} report(s),{" "}
                    {issue.history.other_reports_by_other_customers} from other customers. The
                    provider does not publish a number&apos;s history, so this only covers what
                    we have seen.
                  </p>
                  <ul className="divide-y divide-line rounded-xl border border-line text-sm">
                    {issue.history.by_service.map((row) => (
                      <li key={row.service} className="flex items-center justify-between px-3.5 py-2">
                        <span className="text-ink">{row.service}</span>
                        <Badge tone={row.quality === "NO_ISSUE_REPORTED" ? "success" : "warn"}>
                          {row.quality_label}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <p className="text-xs text-ink-muted">
                Customer: {issue.customer.orders} orders, {issue.customer.orders_with_code} with a
                code, {issue.customer.reports} report(s), {issue.customer.remedies} refunded or
                replaced. Joined {formatDateTime(issue.customer.joined)}.
              </p>

              {available.length > 0 ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {available.map((option) => (
                    <Button
                      key={option}
                      variant={option === "reject" ? "danger" : option === "refund" || option === "replace" ? "primary" : "secondary"}
                      fullWidth
                      onClick={() => setVerb(option)}
                    >
                      {VERBS[option].label}
                    </Button>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

function when(value: string | null | undefined) {
  return value ? formatDateTime(value) : "-";
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
      {Array.from({ length: 6 }).map((_, index) => (
        <li key={index} className="flex items-center gap-4 px-5 py-3.5">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-6 w-24 rounded-full" />
        </li>
      ))}
    </ul>
  );
}
