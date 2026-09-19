"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { AlertIcon, CheckCircleIcon, FlagIcon, ShieldIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  SegmentedControl,
  Skeleton,
  Textarea,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDateTime, relativeTime } from "@/lib/format";
import type {
  AdminActionEntry,
  AdminSystemHealth,
  AuditLogEntry,
  Paginated,
  SuspiciousActivity,
} from "@/lib/types";

type Tab = "health" | "flags" | "audit" | "actions";

export default function AdminSystemPage() {
  const { can } = useAuth();
  const [tab, setTab] = React.useState<Tab>("health");

  return (
    <div className="space-y-4">
      <PageHeader
        title="System"
        description="Provider health, abuse signals and the permanent record of who did what."
      />

      <SegmentedControl
        options={[
          { value: "health" as Tab, label: "Health" },
          { value: "flags" as Tab, label: "Abuse signals" },
          { value: "audit" as Tab, label: "Audit log" },
          { value: "actions" as Tab, label: "Admin actions" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "health" ? <HealthTab /> : null}
      {tab === "flags" ? <FlagsTab /> : null}
      {tab === "audit" ? <AuditTab canView={can("AUDIT_VIEW")} /> : null}
      {tab === "actions" ? <ActionsTab canView={can("AUDIT_VIEW")} /> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function HealthTab() {
  const { data, isLoading } = useSWR<AdminSystemHealth>("/admin/health/", {
    refreshInterval: 30_000,
  });

  if (isLoading || !data) {
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="h-40 p-5">
          <Skeleton className="h-full w-full" />
        </Card>
        <Card className="h-40 p-5">
          <Skeleton className="h-full w-full" />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {data.unprocessed_webhooks > 0 ? (
        <Alert tone="danger" title={`${data.unprocessed_webhooks} webhooks failed to process`}>
          These events passed signature verification but could not be applied. A customer may have
          paid without being credited. Check the application logs for
          <span className="font-mono"> webhook_processing_failed</span>.
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <ProviderCard
          title="Verification provider"
          providerKey={data.verification_provider.key}
          healthy={data.verification_provider.healthy}
          isMock={data.verification_provider.is_mock}
          mockNote="Numbers are simulated. No upstream orders are placed and no provider cost is incurred."
        />
        <ProviderCard
          title="Payment provider"
          providerKey={data.payment_provider.key}
          healthy={data.payment_provider.healthy}
          isMock={data.payment_provider.is_mock}
          mockNote="Payments are simulated end to end, including signed webhooks. No real cedis move."
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Pricing" />
          <dl className="divide-y divide-line px-4 sm:px-5">
            <Row
              label="Exchange rate"
              value={
                data.exchange_rate.configured
                  ? `1 USD = ${Number.parseFloat(data.exchange_rate.rate ?? "0").toFixed(4)} GHS`
                  : "Not configured"
              }
              tone={data.exchange_rate.configured ? "ok" : "bad"}
            />
            <Row
              label="Rate source"
              value={data.exchange_rate.source ?? "-"}
            />
            <Row
              label="Rate updated"
              value={
                data.exchange_rate.fetched_at ? relativeTime(data.exchange_rate.fetched_at) : "-"
              }
            />
            <Row
              label="Active pricing rules"
              value={String(data.pricing_rules)}
              tone={data.pricing_rules > 0 ? "ok" : "bad"}
            />
          </dl>
        </Card>

        <Card>
          <CardHeader title="Provider sync" />
          {data.providers.length === 0 ? (
            <EmptyState title="No providers registered" />
          ) : (
            <ul className="mt-2 divide-y divide-line">
              {data.providers.map((provider) => (
                <li key={provider.adapter_key} className="px-4 py-3.5 sm:px-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{provider.name}</p>
                      <p className="tabular text-xs text-ink-muted">{provider.adapter_key}</p>
                    </div>
                    {provider.is_enabled ? (
                      <Badge tone="success" dot>
                        Enabled
                      </Badge>
                    ) : (
                      <Badge tone="neutral">Disabled</Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-ink-muted">
                    Last synced{" "}
                    {provider.last_synced_at ? relativeTime(provider.last_synced_at) : "never"}
                  </p>
                  {provider.last_sync_error ? (
                    <p className="mt-1.5 rounded-lg bg-danger-50 px-2.5 py-1.5 text-xs text-danger-700">
                      {provider.last_sync_error}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function ProviderCard({
  title,
  providerKey,
  healthy,
  isMock,
  mockNote,
}: {
  title: string;
  providerKey: string;
  healthy: boolean;
  isMock: boolean;
  mockNote: string;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-ink-muted">{title}</p>
          <p className="mt-0.5 text-lg font-semibold text-ink">{providerKey}</p>
        </div>
        <span
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-xl",
            healthy ? "bg-success-50 text-success-700" : "bg-danger-50 text-danger-700",
          )}
        >
          {healthy ? <CheckCircleIcon className="h-5 w-5" /> : <AlertIcon className="h-5 w-5" />}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {healthy ? (
          <Badge tone="success" dot>
            Reachable
          </Badge>
        ) : (
          <Badge tone="danger" dot>
            Unreachable
          </Badge>
        )}
        {isMock ? <Badge tone="warn">Mock</Badge> : <Badge tone="brand">Live</Badge>}
      </div>

      {isMock ? <p className="mt-3 text-xs leading-relaxed text-ink-muted">{mockNote}</p> : null}
    </Card>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "bad";
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd
        className={cn(
          "tabular text-sm font-medium",
          tone === "bad" ? "text-danger-700" : tone === "ok" ? "text-success-700" : "text-ink",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function FlagsTab() {
  const toast = useToast();
  const [showResolved, setShowResolved] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [resolving, setResolving] = React.useState<SuspiciousActivity | null>(null);
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const { data, mutate } = useSWR<Paginated<SuspiciousActivity>>([
    "/admin/flags/",
    { resolved: showResolved ? "true" : "", page, page_size: 25 },
  ]);

  const flags = data?.results ?? [];

  async function resolve() {
    if (!resolving) return;
    setBusy(true);
    try {
      await api.post(`/admin/flags/${resolving.id}/resolve/`, { note });
      toast.success("Signal resolved");
      setResolving(null);
      setNote("");
      await mutate();
    } catch (error) {
      toast.error("Could not resolve", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Alert tone="info" title="Signals are advisory, not verdicts">
        Nothing here suspends an account on its own. A shared device can mean an internet cafe as
        easily as it can mean abuse - a person decides, and that decision is recorded.
      </Alert>

      <SegmentedControl
        options={[
          { value: "open", label: "Open" },
          { value: "resolved", label: "Resolved" },
        ]}
        value={showResolved ? "resolved" : "open"}
        onChange={(value) => {
          setShowResolved(value === "resolved");
          setPage(1);
        }}
      />

      <Card className="overflow-hidden">
        {!data ? (
          <RowSkeletons />
        ) : flags.length === 0 ? (
          <EmptyState
            icon={<ShieldIcon />}
            title={showResolved ? "Nothing resolved yet" : "No open signals"}
            description={
              showResolved ? undefined : "Nothing on the platform currently needs review."
            }
          />
        ) : (
          <ul className="divide-y divide-line">
            {flags.map((flag) => (
              <li key={flag.id} className="px-4 py-4 sm:px-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        tone={
                          flag.level === "HIGH"
                            ? "danger"
                            : flag.level === "MEDIUM"
                              ? "warn"
                              : "neutral"
                        }
                      >
                        {flag.level}
                      </Badge>
                      <span className="text-sm font-medium text-ink">
                        {flag.kind.replace(/_/g, " ").toLowerCase()}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-ink-soft">{flag.description}</p>
                    <p className="mt-1 text-xs text-ink-muted">
                      {flag.user_email || "no account"}
                      <span className="mx-1.5" aria-hidden>
                        &middot;
                      </span>
                      {formatDateTime(flag.created_at)}
                    </p>
                    {flag.resolved && flag.resolution_note ? (
                      <p className="mt-2 rounded-lg bg-canvas px-3 py-2 text-xs text-ink-soft">
                        Resolved: {flag.resolution_note}
                      </p>
                    ) : null}
                  </div>
                  {!flag.resolved ? (
                    <Button size="sm" variant="secondary" onClick={() => setResolving(flag)}>
                      Resolve
                    </Button>
                  ) : (
                    <Badge tone="success">Resolved</Badge>
                  )}
                </div>
              </li>
            ))}
          </ul>
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
          noun="signals"
        />
      ) : null}

      <Dialog
        open={Boolean(resolving)}
        onClose={() => setResolving(null)}
        title="Resolve this signal"
        description={resolving?.description}
        dismissible={!busy}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setResolving(null)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={resolve} loading={busy} disabled={note.trim().length < 3}>
              Resolve
            </Button>
          </div>
        }
      >
        <Field label="What did you find?" htmlFor="note" required hint="Recorded permanently.">
          <Textarea
            id="note"
            rows={3}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="e.g. Confirmed shared university network, no abuse found"
          />
        </Field>
      </Dialog>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function AuditTab({ canView }: { canView: boolean }) {
  const [page, setPage] = React.useState(1);
  const { data } = useSWR<Paginated<AuditLogEntry>>(
    canView ? ["/admin/audit/", { page, page_size: 50 }] : null,
  );

  if (!canView) {
    return (
      <Alert tone="info" title="The audit log is restricted">
        Your role cannot view the audit log.
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        {!data ? (
          <RowSkeletons />
        ) : data.results.length === 0 ? (
          <EmptyState icon={<FlagIcon />} title="Nothing logged yet" />
        ) : (
          <ul className="divide-y divide-line">
            {data.results.map((entry) => (
              <li key={entry.id} className="flex items-start gap-3 px-4 py-3 sm:px-5">
                <span className="tabular w-44 shrink-0 text-xs text-ink-faint">
                  {formatDateTime(entry.created_at)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink">{entry.action}</span>
                  <span className="block truncate text-xs text-ink-muted">
                    {entry.actor_email || "system"}
                    {entry.target_type ? ` - ${entry.target_type}` : ""}
                    {entry.target_id ? ` ${entry.target_id.slice(0, 12)}` : ""}
                  </span>
                </span>
                {entry.ip_address ? (
                  <span className="tabular hidden shrink-0 text-xs text-ink-faint sm:block">
                    {entry.ip_address}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
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
          noun="entries"
        />
      ) : null}
    </div>
  );
}

function ActionsTab({ canView }: { canView: boolean }) {
  const [page, setPage] = React.useState(1);
  const { data } = useSWR<Paginated<AdminActionEntry>>(
    canView ? ["/admin/admin-actions/", { page, page_size: 50 }] : null,
  );

  if (!canView) {
    return (
      <Alert tone="info" title="Admin actions are restricted">
        Your role cannot view privileged-action history.
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      <Alert tone="info" title="Every privileged action, with its reason">
        Suspensions, wallet adjustments, refunds and pricing changes are written here before they
        take effect. These rows are never updated or deleted.
      </Alert>

      <Card className="overflow-hidden">
        {!data ? (
          <RowSkeletons />
        ) : data.results.length === 0 ? (
          <EmptyState icon={<ShieldIcon />} title="No privileged actions yet" />
        ) : (
          <ul className="divide-y divide-line">
            {data.results.map((entry) => (
              <li key={entry.id} className="px-4 py-3.5 sm:px-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-ink">{entry.action}</span>
                  <span className="tabular text-xs text-ink-faint">
                    {formatDateTime(entry.created_at)}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-ink-muted">
                  {entry.admin_email}
                  {entry.target_type ? ` - ${entry.target_type} ${entry.target_id.slice(0, 12)}` : ""}
                </p>
                <p className="mt-1.5 rounded-lg bg-canvas px-3 py-2 text-sm text-ink-soft">
                  {entry.reason}
                </p>
              </li>
            ))}
          </ul>
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
          noun="actions"
        />
      ) : null}
    </div>
  );
}

function RowSkeletons() {
  return (
    <ul className="divide-y divide-line">
      {Array.from({ length: 8 }).map((_, index) => (
        <li key={index} className="flex items-center gap-4 px-5 py-3.5">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-20" />
        </li>
      ))}
    </ul>
  );
}
