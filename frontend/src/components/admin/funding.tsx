"use client";

import * as React from "react";
import useSWR, { mutate } from "swr";

import { MetricTile } from "@/components/admin/charts";
import { providerMoney } from "@/components/admin/pricing-offering";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Select,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, formatDate, formatDateTime, relativeTime } from "@/lib/format";

/* -------------------------------------------------------------------------
 * Shapes returned by /admin/funding/
 * ---------------------------------------------------------------------- */

export type FundingStatus = "HEALTHY" | "LOW" | "CRITICAL" | "UNKNOWN";

export type FundingAccount = {
  provider: string;
  adapter_key: string;
  mode: "PREPAID" | "CREDIT";
  currency: string;
  balance: string | null;
  frozen: string | null;
  credit_limit: string;
  spendable: string | null;
  critical_balance: string;
  minimum_balance: string;
  target_balance: string;
  status: FundingStatus;
  recommended_top_up: string | null;
  last_synced_at: string | null;
  last_sync_attempt_at: string | null;
  last_sync_error: string;
  consecutive_sync_failures: number;
  stale: boolean;
  delivered_30d: number;
  spent_30d: string | null;
  average_cost: string | null;
  estimated_purchases_left: number | null;
  daily_burn: string | null;
  days_of_cover: number | null;
  last_completed_purchase_at: string | null;
  days_since: number | null;
  deletion_on: string | null;
  supports_account_funding: boolean;
  funding_instructions: string;
  guard_enabled: boolean;
};

type Earnings = { revenue: string; provider_cost: string; gross_profit: string };

export type CashFlow = {
  currency: "GHS";
  customer_funds: {
    wallet_cash: string;
    wallet_promotional: string;
    orders_in_progress: string;
    note: string;
  };
  provider_balance_ghs: string;
  provider_balance_unconverted: string[];
  provider_balance_unread: string[];
  reserve_top_up_needed_ghs: string;
  estimated_cost_to_serve_wallets_ghs: string | null;
  estimated_shortfall_ghs: string | null;
  earnings_30d: Earnings;
  earnings_all_time: Earnings;
  top_ups_paid_ghs: { last_30d: string; all_time: string };
  wallet_is_not_profit: string;
};

export type FundingAlert = {
  id: string;
  provider: string;
  kind: string;
  kind_label: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  message: string;
  created_at: string;
  /** Null while the alert still needs attention. */
  resolved_at: string | null;
  resolution: "" | "CLEARED" | "SUPERSEDED" | "DISMISSED" | "INFO";
  resolution_label: string;
};

export type FundingOverview = {
  accounts: FundingAccount[];
  cash_flow: CashFlow;
  /** Alerts that still need attention, newest first. */
  open_alerts: FundingAlert[];
  /** Everything else from the last 14 days. */
  alerts: FundingAlert[];
  top_up_methods: { value: string; label: string }[];
  can_manage: boolean;
};

type TopUp = {
  id: string;
  amount: string;
  currency: string;
  method_label: string;
  external_reference: string;
  paid_ghs: string | null;
  note: string;
  balance_before: string | null;
  confirmed_at: string | null;
  confirmed_balance: string | null;
  recorded_by: string;
  created_at: string;
};

/** Every top-up ever recorded for one account, not only the rows listed. */
type TopUpTotals = {
  count: number;
  /** Summed per currency, never added across currencies. */
  by_currency: { currency: string; amount: string; count: number }[];
  /** Cedis paid, over the top-ups whose cedi amount was entered. */
  paid_ghs: string;
  without_paid_ghs: number;
};

export const FUNDING_KEY = "/admin/funding/";

const topUpsKey = (adapterKey: string) => `/admin/funding/${adapterKey}/top-ups/`;

const STATUS: Record<FundingStatus, { label: string; tone: "success" | "warn" | "danger" | "neutral" }> = {
  HEALTHY: { label: "Healthy", tone: "success" },
  LOW: { label: "Below minimum", tone: "warn" },
  CRITICAL: { label: "Critical", tone: "danger" },
  UNKNOWN: { label: "Unknown", tone: "neutral" },
};

function money(value: string | null, currency: string) {
  return value === null ? "Unknown" : providerMoney(value, currency);
}

/* -------------------------------------------------------------------------
 * One provider account
 * ---------------------------------------------------------------------- */

export function ProviderAccountCard({
  account,
  canManage,
  methods,
  onChanged,
}: {
  account: FundingAccount;
  canManage: boolean;
  methods: FundingOverview["top_up_methods"];
  onChanged: () => Promise<unknown>;
}) {
  const toast = useToast();
  const [syncing, setSyncing] = React.useState(false);
  const [topUpOpen, setTopUpOpen] = React.useState(false);
  const [levelsOpen, setLevelsOpen] = React.useState(false);
  const status = STATUS[account.status];
  const c = account.currency;

  async function refresh() {
    setSyncing(true);
    try {
      await api.post(`/admin/funding/${account.adapter_key}/sync/`);
      await onChanged();
      toast.success("Balance refreshed");
    } catch (caught) {
      toast.error("Could not read the balance", caught instanceof ApiError ? caught.message : "Try again.");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {account.provider}
            <Badge tone={status.tone} dot>
              {status.label}
            </Badge>
            <Badge tone="neutral">{account.mode === "CREDIT" ? "Credit agreement" : "Prepaid"}</Badge>
          </span>
        }
        description={
          account.last_synced_at
            ? `Balance read ${relativeTime(account.last_synced_at)}`
            : "Balance not read yet"
        }
        action={
          <Button variant="secondary" size="sm" onClick={refresh} loading={syncing}>
            Refresh balance
          </Button>
        }
      />
      <div className="space-y-4 p-4 sm:p-5">
        {account.stale && account.last_sync_error ? (
          <Alert tone="warn" title="The balance could not be read">
            {account.last_sync_error} ({account.consecutive_sync_failures} failed{" "}
            {account.consecutive_sync_failures === 1 ? "read" : "reads"} in a row). The figures below
            are from the last successful read.
          </Alert>
        ) : null}
        {account.status === "CRITICAL" ? (
          <Alert tone="danger" title="Customers cannot buy numbers this balance does not cover">
            They see &ldquo;temporarily unavailable&rdquo;. Top up at least{" "}
            {money(account.recommended_top_up, c)} to get back to the target level.
          </Alert>
        ) : null}

        <div className="metric-group grid-cols-2 lg:grid-cols-4">
          <MetricTile
            label="Spendable balance"
            value={money(account.spendable, c)}
            tone={account.status === "CRITICAL" ? "negative" : "default"}
            sublabel={
              account.frozen && Number(account.frozen) > 0
                ? `${providerMoney(account.frozen, c)} frozen on open orders`
                : "Nothing frozen"
            }
          />
          <MetricTile
            label="Recommended top-up"
            value={money(account.recommended_top_up, c)}
            sublabel={`Back to the ${providerMoney(account.target_balance, c)} target`}
          />
          <MetricTile
            label="Numbers it can buy"
            value={account.estimated_purchases_left ?? "—"}
            sublabel={
              account.average_cost
                ? `At ${providerMoney(account.average_cost, c)} average cost`
                : "No purchases yet to average"
            }
          />
          <MetricTile
            label="Days of cover"
            value={account.days_of_cover ?? "—"}
            sublabel={
              account.daily_burn && Number(account.daily_burn) > 0
                ? `${providerMoney(account.daily_burn, c)} a day over the last week`
                : "No spend in the last week"
            }
          />
        </div>

        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
          <Level label="Critical at or below" value={providerMoney(account.critical_balance, c)} />
          <Level label="Minimum" value={providerMoney(account.minimum_balance, c)} />
          <Level label="Target" value={providerMoney(account.target_balance, c)} />
          <Level label="Delivered, last 30 days" value={`${account.delivered_30d} (${money(account.spent_30d, c)})`} />
          <Level
            label="Last completed purchase"
            value={account.last_completed_purchase_at ? formatDate(account.last_completed_purchase_at) : "None on record"}
          />
          <Level
            label="Deleted if idle until"
            value={account.deletion_on ? formatDate(account.deletion_on) : "—"}
            warn={account.days_since !== null && account.days_since >= 20}
          />
        </dl>

        <Alert tone="info" title="How this account is funded">
          {account.funding_instructions} Customer wallet money is never sent to {account.provider}.
          {!account.guard_enabled ? " The pre-purchase balance check is switched off." : ""}
        </Alert>

        {canManage ? (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setTopUpOpen(true)}>Record a top-up</Button>
            <Button variant="secondary" onClick={() => setLevelsOpen(true)}>
              Reserve levels
            </Button>
          </div>
        ) : null}

        <TopUpHistory adapterKey={account.adapter_key} canManage={canManage} />
      </div>

      <TopUpDialog
        open={topUpOpen}
        onClose={() => setTopUpOpen(false)}
        account={account}
        methods={methods}
        onSaved={onChanged}
      />
      <LevelsDialog
        open={levelsOpen}
        onClose={() => setLevelsOpen(false)}
        account={account}
        onSaved={onChanged}
      />
    </Card>
  );
}

function Level({ label, value, warn }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <div>
      <dt className="text-caption text-ink-muted">{label}</dt>
      <dd className={warn ? "tabular font-medium text-danger-700" : "tabular font-medium text-ink"}>{value}</dd>
    </div>
  );
}

function TopUpHistory({ adapterKey, canManage }: { adapterKey: string; canManage: boolean }) {
  const toast = useToast();
  const { data, mutate } = useSWR<{ results: TopUp[]; totals: TopUpTotals }>(topUpsKey(adapterKey));
  const [confirming, setConfirming] = React.useState<TopUp | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function markArrived() {
    if (!confirming) return;
    setBusy(true);
    try {
      await api.post(`/admin/funding/${adapterKey}/top-ups/${confirming.id}/confirm/`, {
        reason: "Seen in the provider balance",
      });
      toast.success("Top-up marked as arrived");
      setConfirming(null);
      void mutate();
    } catch (caught) {
      toast.error("Could not update the top-up", caught instanceof ApiError ? caught.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Skeleton className="h-16" />;
  if (!data.results.length) {
    return <p className="text-sm text-ink-muted">No top-ups recorded yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="text-left text-caption text-ink-muted">
            <th className="py-2 pr-3 font-medium">Recorded</th>
            <th className="py-2 pr-3 font-medium">Amount</th>
            <th className="py-2 pr-3 font-medium">Paid</th>
            <th className="py-2 pr-3 font-medium">Method</th>
            <th className="py-2 pr-3 font-medium">Reference</th>
            <th className="py-2 font-medium">In balance</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {data.results.map((row) => (
            <tr key={row.id}>
              <td className="py-2 pr-3">
                {formatDateTime(row.created_at)}
                <span className="block text-caption text-ink-muted">{row.recorded_by}</span>
              </td>
              <td className="tabular py-2 pr-3">{providerMoney(row.amount, row.currency)}</td>
              <td className="tabular py-2 pr-3">{row.paid_ghs ? cedis(row.paid_ghs) : "—"}</td>
              <td className="py-2 pr-3">{row.method_label}</td>
              <td className="py-2 pr-3">{row.external_reference || "—"}</td>
              <td className="py-2">
                {row.confirmed_at ? (
                  <Badge tone="success">Arrived</Badge>
                ) : (
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge tone="warn">Not seen yet</Badge>
                    {canManage ? (
                      <button type="button" className="link text-caption" onClick={() => setConfirming(row)}>
                        Mark as arrived
                      </button>
                    ) : null}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        {data.totals ? (
          <tfoot>
            <tr className="border-t-2 border-line font-semibold text-ink">
              <td className="py-2.5 pr-3">
                Total
                <span className="block text-caption font-normal text-ink-muted">
                  {data.totals.count} {data.totals.count === 1 ? "top-up" : "top-ups"}
                  {data.totals.count > data.results.length
                    ? `, latest ${data.results.length} listed`
                    : ""}
                </span>
              </td>
              <td className="tabular py-2.5 pr-3">
                {data.totals.by_currency.map((row) => (
                  <span key={row.currency} className="block">
                    {providerMoney(row.amount, row.currency)}
                  </span>
                ))}
              </td>
              <td className="tabular py-2.5 pr-3">
                {cedis(data.totals.paid_ghs)}
                {data.totals.without_paid_ghs ? (
                  <span className="block text-caption font-normal text-ink-muted">
                    {data.totals.without_paid_ghs} without a cedi amount
                  </span>
                ) : null}
              </td>
              <td colSpan={3} />
            </tr>
          </tfoot>
        ) : null}
      </table>
      <ConfirmDialog
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        onConfirm={markArrived}
        loading={busy}
        title="Mark this top-up as arrived?"
        description={
          confirming
            ? `Only if you can see the ${providerMoney(confirming.amount, confirming.currency)} in the provider's own balance. This is recorded in the audit log.`
            : undefined
        }
        confirmLabel="Mark as arrived"
      />
    </div>
  );
}

function TopUpDialog({
  open,
  onClose,
  account,
  methods,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  account: FundingAccount;
  methods: FundingOverview["top_up_methods"];
  onSaved: () => Promise<unknown>;
}) {
  const toast = useToast();
  const blank = { amount: "", method: "", external_reference: "", paid_ghs: "", note: "" };
  const [form, setForm] = React.useState(blank);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.post(`/admin/funding/${account.adapter_key}/top-ups/`, {
        ...form,
        currency: account.currency,
      });
      toast.success("Top-up recorded");
      setForm(blank);
      // The history and its total live under their own key; refresh them too,
      // so the new row and the new total show at once.
      await Promise.all([onSaved(), mutate(topUpsKey(account.adapter_key))]);
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not record the top-up.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Record a ${account.provider} top-up`}
      description={`Pay ${account.provider} on its website first, then record it here. This moves no money - it keeps the books and checks the payment arrived.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy} disabled={!form.amount || !form.method}>
            Record top-up
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={`Amount credited (${account.currency})`} htmlFor="topup-amount" required>
            <Input
              id="topup-amount"
              inputMode="decimal"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              className="tabular"
            />
          </Field>
          <Field label="Paid with" htmlFor="topup-method" required>
            <Select id="topup-method" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
              <option value="">Choose…</option>
              {methods.map((method) => (
                <option key={method.value} value={method.value}>
                  {method.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Cedis paid (operating funds)" htmlFor="topup-ghs" hint="What it cost VerifyGH, for the books.">
            <Input
              id="topup-ghs"
              inputMode="decimal"
              value={form.paid_ghs}
              onChange={(e) => setForm({ ...form, paid_ghs: e.target.value })}
              className="tabular"
            />
          </Field>
          <Field label="Payment reference" htmlFor="topup-ref" hint="Invoice or transaction ID. Never a card number.">
            <Input
              id="topup-ref"
              value={form.external_reference}
              onChange={(e) => setForm({ ...form, external_reference: e.target.value })}
              autoComplete="off"
            />
          </Field>
        </div>
        <Field label="Note" htmlFor="topup-note">
          <Input id="topup-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </Field>
      </div>
    </Dialog>
  );
}

function LevelsDialog({
  open,
  onClose,
  account,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  account: FundingAccount;
  onSaved: () => Promise<unknown>;
}) {
  const toast = useToast();
  const initial = React.useMemo(
    () => ({
      critical_balance: Number(account.critical_balance).toString(),
      minimum_balance: Number(account.minimum_balance).toString(),
      target_balance: Number(account.target_balance).toString(),
      reason: "",
    }),
    [account.critical_balance, account.minimum_balance, account.target_balance],
  );
  const [form, setForm] = React.useState(initial);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setForm(initial);
      setError("");
    }
  }, [open, initial]);

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.patch(`/admin/funding/${account.adapter_key}/`, form);
      toast.success("Reserve levels saved");
      await onSaved();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const field = (key: "critical_balance" | "minimum_balance" | "target_balance", label: string, hint: string) => (
    <Field label={`${label} (${account.currency})`} htmlFor={`level-${key}`} hint={hint}>
      <Input
        id={`level-${key}`}
        inputMode="decimal"
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="tabular"
      />
    </Field>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Reserve levels"
      description={`When to warn about the ${account.provider} balance, and what to top it back up to. Keep the target modest: ${account.provider} deletes an account and its balance after 30 days without a completed purchase.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy} disabled={form.reason.trim().length < 5}>
            Save levels
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {field("critical_balance", "Critical", "Alert urgently, every few hours.")}
          {field("minimum_balance", "Minimum", "Alert once when it drops below.")}
          {field("target_balance", "Target", "What a top-up should restore.")}
        </div>
        <Field label="Reason" htmlFor="level-reason" required>
          <Input id="level-reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        </Field>
      </div>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------
 * Cash flow
 * ---------------------------------------------------------------------- */

export function CashFlowCard({ flow }: { flow: CashFlow }) {
  const liabilities =
    Number(flow.customer_funds.wallet_cash) +
    Number(flow.customer_funds.wallet_promotional) +
    Number(flow.customer_funds.orders_in_progress);
  const profit30 = Number(flow.earnings_30d.gross_profit);
  return (
    <Card>
      <CardHeader
        title="Cash flow"
        description="Customer money, our money at providers, and what we actually earned - kept apart."
      />
      <div className="space-y-5 p-4 sm:p-5">
        <Alert tone="warn" title="Customer wallet balance ≠ VerifyGH profit">
          {flow.wallet_is_not_profit}
        </Alert>

        <section className="space-y-2">
          <h3 className="text-label text-ink">Owed to customers</h3>
          <div className="metric-group grid-cols-2 lg:grid-cols-4">
            <MetricTile label="Wallet cash" value={cedis(flow.customer_funds.wallet_cash)} sublabel="Deposits not yet spent" />
            <MetricTile label="Promotional credit" value={cedis(flow.customer_funds.wallet_promotional)} sublabel="Spendable, not withdrawable" />
            <MetricTile label="In progress" value={cedis(flow.customer_funds.orders_in_progress)} sublabel="Orders and rentals charged, refundable until delivered" />
            <MetricTile label="Total liability" value={cedis(liabilities)} sublabel={flow.customer_funds.note} />
          </div>
        </section>

        <section className="space-y-2">
          <h3 className="text-label text-ink">Our money at providers</h3>
          <div className="metric-group grid-cols-2 lg:grid-cols-4">
            <MetricTile label="Provider balance" value={cedis(flow.provider_balance_ghs)} sublabel="At the VerifyGH Pricing FX Rate" />
            <MetricTile
              label="Reserve top-up needed"
              value={cedis(flow.reserve_top_up_needed_ghs)}
              tone={Number(flow.reserve_top_up_needed_ghs) > 0 ? "negative" : "default"}
              sublabel="To bring every account to target"
            />
            <MetricTile
              label="Cost to serve all wallets"
              value={flow.estimated_cost_to_serve_wallets_ghs ? cedis(flow.estimated_cost_to_serve_wallets_ghs) : "—"}
              sublabel="Estimate, if every balance were spent today"
            />
            <MetricTile
              label="Funding shortfall"
              value={flow.estimated_shortfall_ghs ? cedis(flow.estimated_shortfall_ghs) : "—"}
              tone={Number(flow.estimated_shortfall_ghs ?? 0) > 0 ? "negative" : "default"}
              sublabel="Provider funds still needed for that"
            />
          </div>
          {flow.provider_balance_unread.length ? (
            <p className="text-caption text-ink-muted">
              Balance not read yet: {flow.provider_balance_unread.join(", ")} - the shortfall cannot be worked out
              until it is.
            </p>
          ) : null}
          {flow.provider_balance_unconverted.length ? (
            <p className="text-caption text-ink-muted">
              Not converted (no pricing rate): {flow.provider_balance_unconverted.join(", ")}.
            </p>
          ) : null}
        </section>

        <section className="space-y-2">
          <h3 className="text-label text-ink">What we earned (delivered orders and rentals)</h3>
          <div className="metric-group grid-cols-2 lg:grid-cols-4">
            <MetricTile label="Revenue, 30 days" value={cedis(flow.earnings_30d.revenue)} />
            <MetricTile label="Provider cost, 30 days" value={cedis(flow.earnings_30d.provider_cost)} />
            <MetricTile
              label="Gross profit, 30 days"
              value={cedis(flow.earnings_30d.gross_profit)}
              tone={profit30 > 0 ? "positive" : profit30 < 0 ? "negative" : "default"}
              sublabel={`All time: ${cedis(flow.earnings_all_time.gross_profit)}`}
            />
            <MetricTile
              label="Top-ups paid, 30 days"
              value={cedis(flow.top_ups_paid_ghs.last_30d)}
              sublabel={`All time: ${cedis(flow.top_ups_paid_ghs.all_time)} - a prepayment, not a cost`}
            />
          </div>
        </section>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Alerts
 * ---------------------------------------------------------------------- */

function alertTone(alert: FundingAlert) {
  return alert.severity === "CRITICAL" ? "danger" : alert.severity === "WARNING" ? "warn" : "info";
}

/**
 * Open alerts first, each with a way to dismiss it; the last 14 days of
 * resolved ones folded away underneath. An alert closes on its own when what
 * it reported is over (the balance recovered, it could be read again, a newer
 * alert replaced it), so the list holds only what still needs a person.
 */
export function FundingAlerts({
  openAlerts,
  history,
  canManage,
  onChanged,
}: {
  openAlerts: FundingAlert[];
  history: FundingAlert[];
  canManage: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [dismissing, setDismissing] = React.useState<FundingAlert | null>(null);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function dismiss() {
    if (!dismissing) return;
    setBusy(true);
    try {
      await api.post(`/admin/funding/alerts/${dismissing.id}/dismiss/`, { reason });
      toast.success("Alert dismissed");
      setDismissing(null);
      setReason("");
      onChanged();
    } catch (caught) {
      toast.error("Could not dismiss the alert", caught instanceof ApiError ? caught.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Alerts"
        description="What needs attention at your providers right now. Alerts close themselves once the problem is over."
      />
      <div className="space-y-4 p-4 sm:p-5">
        {openAlerts.length === 0 ? (
          <EmptyState title="Nothing needs attention" description="Every provider alert has been resolved." />
        ) : (
          <ul className="divide-y divide-line">
            {openAlerts.map((alert) => (
              <li key={alert.id} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={alertTone(alert)}>{alert.kind_label}</Badge>
                    <span className="text-caption text-ink-muted">
                      {alert.provider} · {formatDateTime(alert.created_at)}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-ink-soft">{alert.message}</p>
                </div>
                {canManage ? (
                  <Button variant="secondary" size="sm" onClick={() => setDismissing(alert)} className="shrink-0">
                    Dismiss
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {history.length ? (
          <details className="group rounded-xl border border-line">
            <summary className="cursor-pointer select-none px-3.5 py-2.5 text-sm font-medium text-ink-soft">
              Resolved in the last 14 days ({history.length})
            </summary>
            <ul className="divide-y divide-line border-t border-line">
              {history.map((alert) => (
                <li key={alert.id} className="px-3.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-ink">{alert.kind_label}</span>
                    <span className="text-caption text-ink-muted">
                      {alert.provider} · {formatDateTime(alert.created_at)}
                      {alert.resolution && alert.resolution !== "INFO" ? ` · ${alert.resolution_label.toLowerCase()}` : ""}
                    </span>
                  </div>
                  <p className="mt-0.5 text-caption text-ink-muted">{alert.message}</p>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      <Dialog
        open={dismissing !== null}
        onClose={() => setDismissing(null)}
        title="Dismiss this alert?"
        description="It leaves the list and its notifications are marked read. Use this when you have dealt with it; the reason goes in the audit log."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDismissing(null)}>
              Cancel
            </Button>
            <Button onClick={dismiss} loading={busy} disabled={reason.trim().length < 5}>
              Dismiss alert
            </Button>
          </>
        }
      >
        <Field label="Reason" htmlFor="alert-dismiss-reason" required hint="At least 5 characters.">
          <Input id="alert-dismiss-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </Dialog>
    </Card>
  );
}
