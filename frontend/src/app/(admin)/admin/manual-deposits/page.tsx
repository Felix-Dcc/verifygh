"use client";

import * as React from "react";
import useSWR from "swr";

import { KpiCard, KpiRow, ListCard } from "@/components/admin/ui";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { AlertIcon, CheckCircleIcon, ClockIcon, WalletIcon } from "@/components/icons";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, LoadError, Skeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { API_URL, ApiError, api } from "@/lib/api";
import { cedis, formatDateTime, localPhone, relativeTime } from "@/lib/format";
import type { ManualTopUpQueue, ManualTopUpRow } from "@/lib/types";

const KEY = "/admin/manual-deposits/";

/**
 * Admin > Manual top-ups: customers' MoMo transfers to the business wallet.
 *
 * Credit only what you can see on the wallet. Open the wallet's history, find
 * the transfer, then type the amount that arrived and the transaction ID shown
 * there - that ID can settle one top-up only. The screenshot helps you find the
 * transfer; it is never the proof.
 */
export default function ManualDepositsPage() {
  const { can } = useAuth();
  const canDecide = can("WALLET_ADJUST");
  const { data, error, isValidating, mutate } = useSWR<ManualTopUpQueue>(KEY, { refreshInterval: 30_000 });
  const waitingTotal = (data?.waiting ?? []).reduce((sum, row) => sum + Number.parseFloat(row.amount || "0"), 0);
  const credited = (data?.decided ?? []).filter((row) => row.status === "SUCCESS");
  const rejected = (data?.decided ?? []).filter((row) => row.status !== "SUCCESS");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Manual top-ups"
        description="Mobile Money sent to the business wallet. Credit only what you can see arrived on the wallet."
      />

      {error && !data ? <LoadError what="manual top-ups" onRetry={() => mutate()} /> : null}

      <KpiRow>
        <KpiCard
          icon={<ClockIcon />}
          tone="warn"
          label="Waiting for you"
          value={data?.waiting.length}
          hint={data ? `${cedis(waitingTotal)} claimed` : undefined}
        />
        <KpiCard
          icon={<CheckCircleIcon />}
          label="Credited recently"
          value={data ? credited.length : undefined}
          hint={data ? cedis(credited.reduce((sum, row) => sum + Number.parseFloat(row.amount || "0"), 0)) : undefined}
        />
        <KpiCard
          icon={<AlertIcon />}
          tone="danger"
          label="Rejected recently"
          value={data ? rejected.length : undefined}
          hint="Not found on the wallet"
        />
        <KpiCard
          icon={<WalletIcon />}
          tone={data?.enabled ? "brand" : "neutral"}
          label="Manual top-ups"
          value={data ? (data.enabled ? "On" : "Off") : undefined}
          hint={data?.settings.number ? `${data.settings.network} ${data.settings.number}` : "No wallet number set"}
        />
      </KpiRow>

      {!data && !error ? <Skeleton className="h-40" /> : null}

      {data ? (
        <>
          <Switch data={data} canDecide={canDecide} onChanged={() => mutate()} />
          <Alert tone="warn" title="Check the wallet, not the screenshot">
            Screenshots can be edited. Approve only after you find the transfer in the{" "}
            {data.settings.network || "wallet"} history, and type the amount that actually arrived.
          </Alert>

          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-heading text-ink">
                Waiting for you
                <span className="tabular rounded-full bg-warn-50 px-2 py-0.5 text-caption font-semibold text-warn-700">
                  {data.waiting.length}
                </span>
              </h2>
            </div>
            {data.waiting.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<CheckCircleIcon />}
                  title="All caught up"
                  description="New claims appear here, and you get a notification."
                />
              </Card>
            ) : (
              data.waiting.map((row) => (
                <ClaimCard key={row.reference} row={row} reasons={data.reject_reasons} canDecide={canDecide} onDone={() => mutate()} />
              ))
            )}
          </section>

          {data.decided.length ? (
            <ListCard
              title="Recently decided"
              count={data.decided.length}
              noun="top-ups"
              refreshing={isValidating}
              onRefresh={() => mutate()}
            >
              <div className="divide-y divide-line">
                {data.decided.map((row) => (
                  <div key={row.reference} className="flex items-start justify-between gap-3 px-4 py-3 text-sm">
                    <div className="min-w-0">
                      <p className="tabular font-medium text-ink">
                        {cedis(row.amount)} <span className="font-mono text-caption text-ink-muted">{row.reference}</span>
                      </p>
                      <p className="truncate text-caption text-ink-muted">
                        {row.user_email} · {row.completed_at ? formatDateTime(row.completed_at) : ""}
                        {row.receipt_id ? ` · wallet ID ${row.receipt_id}` : ""}
                      </p>
                      {row.failure_reason ? <p className="text-caption text-danger-700">{row.failure_reason}</p> : null}
                    </div>
                    <Badge tone={row.status === "SUCCESS" ? "success" : "danger"}>
                      {row.status === "SUCCESS" ? "Credited" : "Rejected"}
                    </Badge>
                  </div>
                ))}
              </div>
            </ListCard>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function Switch({ data, canDecide, onChanged }: { data: ManualTopUpQueue; canDecide: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);

  async function toggle() {
    setBusy(true);
    try {
      await api.post(`${KEY}settings/`, {
        enabled: !data.enabled,
        reason: data.enabled ? "Switched off from the admin" : "Switched on from the admin",
      });
      toast.success(data.enabled ? "Manual top-ups switched off" : "Manual top-ups switched on");
      onChanged();
    } catch (caught) {
      toast.error("Could not change it", caught instanceof ApiError ? caught.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-ink">
          Manual top-ups are {data.enabled ? "on" : "off"}
        </p>
        <p className="text-caption text-ink-muted">
          {data.settings.number
            ? `Customers send to ${data.settings.network} ${data.settings.number} via ${data.settings.ussd}. Shown only while top-ups by prompt are paused.`
            : "Set MANUAL_DEPOSIT_NUMBER on the API before switching on."}
        </p>
      </div>
      {canDecide ? (
        <Button variant={data.enabled ? "secondary" : "primary"} onClick={toggle} loading={busy}>
          {data.enabled ? "Switch off" : "Switch on"}
        </Button>
      ) : null}
    </Card>
  );
}

function ClaimCard({
  row,
  reasons,
  canDecide,
  onDone,
}: {
  row: ManualTopUpRow;
  reasons: string[];
  canDecide: boolean;
  onDone: () => void;
}) {
  const toast = useToast();
  const [mode, setMode] = React.useState<"" | "approve" | "reject">("");
  const [amount, setAmount] = React.useState("");
  const [receipt, setReceipt] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  async function act(path: string, body: Record<string, string>, message: string) {
    setBusy(true);
    setError("");
    try {
      await api.post(`${KEY}${row.reference}/${path}/`, body);
      toast.success(message);
      onDone();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const differs = amount && Number.parseFloat(amount) !== Number.parseFloat(row.claimed_amount);

  return (
    <Card className="space-y-3 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="tabular text-heading text-ink">{cedis(row.claimed_amount)}</p>
          <p className="text-caption text-ink-muted">
            {row.user_email} · claimed {row.claimed_at ? relativeTime(row.claimed_at) : ""}
          </p>
        </div>
        <span className="font-mono text-sm text-ink-soft">{row.reference}</span>
      </div>

      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-caption text-ink-muted">Sent from</dt>
          <dd className="tabular text-ink">
            {row.sender_phone ? localPhone(row.sender_phone) : "-"} ({row.network})
          </dd>
        </div>
        <div>
          <dt className="text-caption text-ink-muted">Their transaction ID</dt>
          <dd className="font-mono text-ink">{row.transaction_id || "-"}</dd>
        </div>
      </dl>

      {row.evidence.length ? (
        <ul className="flex flex-wrap gap-2">
          {row.evidence.map((item, index) => {
            const url = `${API_URL}/admin/manual-deposits/${row.reference}/evidence/${item.id}/`;
            return (
              <li key={item.id}>
                <a href={url} target="_blank" rel="noreferrer">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt={`Screenshot ${index + 1}`} className="h-28 w-28 rounded-lg border border-line object-cover" />
                </a>
              </li>
            );
          })}
        </ul>
      ) : null}

      {error ? <Alert tone="danger">{error}</Alert> : null}

      {canDecide && mode === "" ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button fullWidth onClick={() => setMode("approve")}>I can see it - approve</Button>
          <Button fullWidth variant="secondary" onClick={() => setMode("reject")}>Reject</Button>
        </div>
      ) : null}

      {mode === "approve" ? (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            act("approve", { amount_received: amount, receipt_id: receipt }, "Top-up credited");
          }}
        >
          <Field label="Amount that arrived on the wallet" htmlFor={`amt-${row.reference}`} required>
            <Input
              id={`amt-${row.reference}`}
              inputMode="decimal"
              prefix="GH₵"
              value={amount}
              onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ""))}
              className="tabular"
            />
          </Field>
          {differs ? (
            <p className="text-caption text-warn-700">
              Different from the {cedis(row.claimed_amount)} claimed. The customer is credited what you type.
            </p>
          ) : null}
          <Field
            label="Transaction ID on the receiving wallet"
            htmlFor={`rcpt-${row.reference}`}
            required
            hint="From your own wallet history. Each one can credit only one top-up."
          >
            <Input id={`rcpt-${row.reference}`} value={receipt} onChange={(event) => setReceipt(event.target.value)} className="font-mono" autoCapitalize="characters" />
          </Field>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setMode("")} disabled={busy}>Back</Button>
            <Button type="submit" loading={busy} disabled={!amount || !receipt}>
              Credit {cedis(amount || "0")}
            </Button>
          </div>
        </form>
      ) : null}

      {mode === "reject" ? (
        <div className="space-y-2">
          {reasons.map((reason) => (
            <Button
              key={reason}
              variant="secondary"
              fullWidth
              disabled={busy}
              onClick={() => act("reject", { reason }, "Top-up rejected")}
            >
              {reason}
            </Button>
          ))}
          <Button variant="secondary" fullWidth onClick={() => setMode("")} disabled={busy}>Back</Button>
        </div>
      ) : null}
    </Card>
  );
}
