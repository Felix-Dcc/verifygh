"use client";

import Link from "next/link";
import * as React from "react";

import { MetricTile } from "@/components/admin/charts";
import { providerMoney } from "@/components/admin/pricing-offering";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Badge, Button, Card, CardHeader, Field, Input } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDateTime, relativeTime } from "@/lib/format";

/* -------------------------------------------------------------------------
 * Shapes returned by /admin/providers/
 * ---------------------------------------------------------------------- */

export type ProviderReport = {
  adapter_key: string;
  name: string;
  is_primary: boolean;
  is_enabled: boolean;
  priority: number;
  registered: boolean;
  configured: boolean;
  resale_authorized: boolean;
  authorization_reference: string;
  authorized_at: string | null;
  authorized_by: string | null;
  selling: boolean;
  capabilities: {
    balance: boolean;
    account_funding: boolean;
    webhooks: boolean;
    webhooks_active: boolean;
    issue_reports: boolean;
  };
  api: {
    since: string | null;
    calls: number;
    failures: number;
    average_ms: number | null;
    last_success_at: string | null;
    last_success_operation: string;
    last_failure_at: string | null;
    last_failure_operation: string;
    last_failure_error: string;
  };
  catalogue: {
    offerings: number;
    in_stock: number;
    listed_to_customers: number;
    countries: string[];
    last_synced_at: string | null;
    last_sync_error: string;
  };
  orders: {
    window_days: number;
    orders: number;
    numbers_assigned: number;
    purchase_success_rate: string | null;
    sms_delivered: number;
    sms_success_rate: string | null;
    refunded: number;
    in_flight: number;
  };
  funding: {
    status: string | null;
    balance: string | null;
    currency: string | null;
    last_synced_at: string | null;
    last_sync_error: string;
  };
};

export type ProvidersOverview = {
  primary: string;
  providers: ProviderReport[];
  can_manage: boolean;
};

export const PROVIDERS_KEY = "/admin/providers/";

function percent(value: string | null) {
  return value === null ? "Not measured yet" : `${value}%`;
}

function when(value: string | null) {
  return value ? `${relativeTime(value)} (${formatDateTime(value)})` : "Never";
}

/* -------------------------------------------------------------------------
 * One provider
 * ---------------------------------------------------------------------- */

export function ProviderCard({
  provider,
  canManage,
  onChanged,
}: {
  provider: ProviderReport;
  canManage: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const [dialog, setDialog] = React.useState<null | "authorize" | "withdraw" | "enable" | "disable">(
    null,
  );
  const p = provider;
  const fundingTone =
    p.funding.status === "CRITICAL" ? "danger" : p.funding.status === "LOW" ? "warn" : "neutral";

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {p.name}
            {p.is_primary ? <Badge tone="brand">Primary</Badge> : null}
            <Badge tone={p.is_enabled ? "success" : "neutral"} dot>
              {p.is_enabled ? "Enabled" : "Switched off"}
            </Badge>
            <Badge tone={p.resale_authorized ? "success" : "warn"}>
              {p.resale_authorized ? "Resale authorised" : "Resale not authorised"}
            </Badge>
            {!p.configured && p.registered ? <Badge tone="danger">Credentials missing</Badge> : null}
          </span>
        }
        description={
          p.selling
            ? "Customers can buy numbers from this provider."
            : "Customers cannot buy anything from this provider right now."
        }
      />
      <div className="space-y-4 p-4 sm:p-5">
        {!p.resale_authorized ? (
          <Alert tone="warn" title="Nothing is sold through this provider until it authorises resale">
            Its catalogue can be synced and priced, and its balance read, but no number is listed to
            customers or ordered for them. Record the authorisation only once {p.name} has agreed in
            writing that its numbers may be resold to our customers.
          </Alert>
        ) : (
          <p className="text-sm text-ink-muted">
            Authorised: {p.authorization_reference}
            {p.authorized_by ? ` - recorded by ${p.authorized_by}` : ""}
            {p.authorized_at ? ` on ${formatDateTime(p.authorized_at)}` : ""}
          </p>
        )}

        <div className="metric-group grid-cols-2 lg:grid-cols-4">
          <MetricTile
            label="Purchase success"
            value={percent(p.orders.purchase_success_rate)}
            sublabel={`${p.orders.numbers_assigned} of ${p.orders.orders} orders got a number (${p.orders.window_days} days)`}
          />
          <MetricTile
            label="SMS success"
            value={percent(p.orders.sms_success_rate)}
            sublabel={`${p.orders.sms_delivered} codes delivered; ${p.orders.in_flight} in flight`}
          />
          <MetricTile
            label="Average response"
            value={p.api.average_ms === null ? "Not measured yet" : `${p.api.average_ms} ms`}
            sublabel={
              p.api.since
                ? `${p.api.calls} calls, ${p.api.failures} failed, since ${formatDateTime(p.api.since)}`
                : "No calls recorded yet"
            }
          />
          <MetricTile
            label="Listed to customers"
            value={p.catalogue.listed_to_customers}
            sublabel={`${p.catalogue.in_stock} of ${p.catalogue.offerings} offerings in stock`}
          />
        </div>

        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <Row label="Last successful call" value={
            p.api.last_success_at
              ? `${when(p.api.last_success_at)} - ${p.api.last_success_operation}`
              : "Never"
          } />
          <Row
            label="Last failed call"
            value={
              p.api.last_failure_at
                ? `${when(p.api.last_failure_at)} - ${p.api.last_failure_operation} (${p.api.last_failure_error})`
                : "Never"
            }
            warn={Boolean(p.api.last_failure_at)}
          />
          <Row label="Catalogue synced" value={when(p.catalogue.last_synced_at)} />
          <Row
            label="Balance"
            value={
              p.capabilities.balance ? (
                <span className="inline-flex items-center gap-2">
                  {p.funding.balance !== null
                    ? providerMoney(p.funding.balance, p.funding.currency ?? "USD")
                    : "Not read yet"}
                  {p.funding.status ? <Badge tone={fundingTone}>{p.funding.status}</Badge> : null}
                  <Link href="/admin/funding" className="text-brand-700 underline">
                    Funding
                  </Link>
                </span>
              ) : (
                "This provider does not report a balance"
              )
            }
          />
          <Row label="Countries" value={p.catalogue.countries.join(", ") || "None synced"} />
          <Row
            label="Capabilities"
            value={[
              p.capabilities.balance ? "balance" : null,
              p.capabilities.webhooks
                ? p.capabilities.webhooks_active
                  ? "signed webhooks (on)"
                  : "signed webhooks (secret not set - polling only)"
                : "polling only",
              p.capabilities.issue_reports ? "number reports" : null,
              p.capabilities.account_funding ? "API funding" : "no API funding",
            ]
              .filter(Boolean)
              .join(" · ")}
          />
        </dl>
        {p.catalogue.last_sync_error ? (
          <p className="text-sm text-warn-700">Last catalogue sync: {p.catalogue.last_sync_error}</p>
        ) : null}
        {p.funding.last_sync_error ? (
          <p className="text-sm text-warn-700">Last balance read: {p.funding.last_sync_error}</p>
        ) : null}

        {canManage ? (
          <div className="flex flex-wrap gap-2">
            {p.resale_authorized ? (
              <Button variant="secondary" onClick={() => setDialog("withdraw")}>
                Withdraw authorisation
              </Button>
            ) : (
              <Button onClick={() => setDialog("authorize")}>Record written authorisation</Button>
            )}
            <Button variant="secondary" onClick={() => setDialog(p.is_enabled ? "disable" : "enable")}>
              {p.is_enabled ? "Switch off" : "Switch on"}
            </Button>
          </div>
        ) : null}
      </div>

      <ChangeDialog provider={p} mode={dialog} onClose={() => setDialog(null)} onSaved={onChanged} />
    </Card>
  );
}

function Row({ label, value, warn }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className={warn ? "text-danger-700" : "text-ink"}>{value}</dd>
    </div>
  );
}

const COPY = {
  authorize: {
    title: "Record written authorisation",
    description:
      "Only once the provider has agreed in writing that its numbers may be resold to our customers. Customers can buy through it as soon as this is saved.",
    button: "Record authorisation",
  },
  withdraw: {
    title: "Withdraw authorisation",
    description:
      "Customers stop seeing this provider's services immediately. Orders already holding a number still finish; anything not yet ordered is refunded.",
    button: "Withdraw",
  },
  enable: {
    title: "Switch provider on",
    description: "Its catalogue is synced and its balance read again. It sells only if resale is also authorised.",
    button: "Switch on",
  },
  disable: {
    title: "Switch provider off",
    description:
      "It is no longer called at all. Orders and history made through it are kept; orders not yet sent to it are refunded.",
    button: "Switch off",
  },
} as const;

function ChangeDialog({
  provider,
  mode,
  onClose,
  onSaved,
}: {
  provider: ProviderReport;
  mode: null | keyof typeof COPY;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const toast = useToast();
  const [reference, setReference] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (mode) {
      setReference("");
      setReason("");
      setError("");
    }
  }, [mode]);

  if (!mode) return null;
  const copy = COPY[mode];

  async function save() {
    setBusy(true);
    setError("");
    try {
      if (mode === "authorize" || mode === "withdraw") {
        await api.post(`/admin/providers/${provider.adapter_key}/authorization/`, {
          authorized: mode === "authorize",
          reference,
          reason,
        });
      } else {
        await api.post(`/admin/providers/${provider.adapter_key}/status/`, {
          enabled: mode === "enable",
          reason,
        });
      }
      toast.success("Saved");
      await onSaved();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const needsReference = mode === "authorize";
  return (
    <Dialog
      open
      onClose={onClose}
      title={`${copy.title}: ${provider.name}`}
      description={copy.description}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={save}
            loading={busy}
            disabled={reason.trim().length < 5 || (needsReference && reference.trim().length < 10)}
          >
            {copy.button}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {needsReference ? (
          <Field
            label="Evidence of the authorisation"
            htmlFor="provider-reference"
            required
            hint="Who agreed, how and when - e.g. 'Email from support@provider.com, 2 Oct 2026, ticket 4471'."
          >
            <Input id="provider-reference" value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
        ) : null}
        <Field label="Reason" htmlFor="provider-reason" required>
          <Input id="provider-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}
