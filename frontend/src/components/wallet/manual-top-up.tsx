"use client";

import * as React from "react";
import useSWR from "swr";

import { Alert, Badge, Button, Card, Field, Input, Select, cn } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, formatDateTime } from "@/lib/format";
import type { ManualTopUpDetails, Paginated, Payment } from "@/lib/types";

/**
 * Manual Mobile Money top-up, while the payment gateway is paused.
 *
 * The customer sends money to the business wallet through *246#, then submits
 * the transaction ID and a screenshot. Staff credit it after seeing the money
 * arrive - the screenshot helps them find it, it is never the proof.
 * backend/apps/payments/manual.py.
 */

const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 5 * 1024 * 1024;

const STATUS_LABEL: Record<string, { text: string; tone: "warn" | "info" | "success" | "danger" | "neutral" }> = {
  PENDING: { text: "Waiting for your payment", tone: "warn" },
  PROCESSING: { text: "Being checked", tone: "info" },
  SUCCESS: { text: "Credited", tone: "success" },
  FAILED: { text: "Not confirmed", tone: "danger" },
  EXPIRED: { text: "Expired", tone: "neutral" },
};

export function ManualTopUp({ manual, quickAmounts }: { manual: ManualTopUpDetails; quickAmounts: string[] }) {
  const { data: history, mutate } = useSWR<Paginated<Payment>>(["/payments/", { page_size: 20 }]);
  const mine = (history?.results ?? []).filter((payment) => payment.provider === "manual");
  const waiting = mine.find((payment) => payment.status === "PENDING");
  const [active, setActive] = React.useState<Payment | null>(null);
  const current = active ?? waiting ?? null;

  return (
    <div className="space-y-4">
      <Alert tone="info" title="Top up by Mobile Money transfer">
        Card and prompt payments are paused for now. You can still top up by sending Mobile Money
        to our wallet - we check it and credit your balance, usually within 30 minutes between 8am
        and 10pm.
      </Alert>

      {current && current.status === "PENDING" ? (
        <ClaimStep
          payment={current}
          manual={manual}
          onDone={() => {
            setActive(null);
            mutate();
          }}
        />
      ) : (
        <AmountStep
          manual={manual}
          quickAmounts={quickAmounts}
          onStarted={(payment) => {
            setActive(payment);
            mutate();
          }}
        />
      )}

      {mine.length ? (
        <Card className="p-4 sm:p-5">
          <h3 className="text-sm font-semibold text-ink">Your recent top-ups</h3>
          <ul className="mt-2 divide-y divide-line">
            {mine.slice(0, 6).map((payment) => {
              const label = STATUS_LABEL[payment.status] ?? { text: payment.status, tone: "neutral" as const };
              return (
                <li key={payment.reference} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="tabular text-sm font-medium text-ink">
                      {cedis(payment.amount)} <span className="font-mono text-caption text-ink-muted">{payment.reference}</span>
                    </p>
                    <p className="text-caption text-ink-muted">{formatDateTime(payment.created_at)}</p>
                    {payment.status === "FAILED" && payment.failure_reason ? (
                      <p className="mt-1 text-caption text-danger-700">{payment.failure_reason}</p>
                    ) : null}
                  </div>
                  <Badge tone={label.tone}>{label.text}</Badge>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function AmountStep({
  manual,
  quickAmounts,
  onStarted,
}: {
  manual: ManualTopUpDetails;
  quickAmounts: string[];
  onStarted: (payment: Payment) => void;
}) {
  const [amount, setAmount] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const value = Number.parseFloat(amount || "0");
  const valid = value >= Number.parseFloat(manual.min) && value <= Number.parseFloat(manual.max);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onStarted(await api.post<Payment>("/payments/manual/", { amount }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5 sm:p-6">
      <form onSubmit={submit} className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field
          label="How much do you want to add?"
          htmlFor="manual-amount"
          required
          hint={`Between ${cedis(manual.min)} and ${cedis(manual.max)}.`}
        >
          <Input
            id="manual-amount"
            inputMode="decimal"
            prefix="GH₵"
            value={amount}
            onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ""))}
            className="tabular"
            placeholder="0.00"
          />
        </Field>
        <div className="flex flex-wrap gap-2">
          {quickAmounts
            .filter((quick) => Number.parseFloat(quick) <= Number.parseFloat(manual.max))
            .map((quick) => (
              <button
                key={quick}
                type="button"
                onClick={() => setAmount(quick)}
                className={cn(
                  "min-h-10 rounded-full border px-3.5 text-sm",
                  amount === quick ? "border-brand-500 bg-brand-50 font-medium text-brand-700" : "border-line text-ink-soft",
                )}
              >
                {cedis(quick)}
              </button>
            ))}
        </div>
        <Button type="submit" fullWidth size="lg" loading={busy} disabled={!valid}>
          Continue
        </Button>
      </form>
    </Card>
  );
}

function ClaimStep({ payment, manual, onDone }: { payment: Payment; manual: ManualTopUpDetails; onDone: () => void }) {
  const toast = useToast();
  const [phone, setPhone] = React.useState("");
  const [network, setNetwork] = React.useState("MTN");
  const [txn, setTxn] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [problem, setProblem] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const preview = React.useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);
  React.useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  function pick(event: React.ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0];
    event.target.value = "";
    setProblem("");
    if (!picked) return;
    if (!IMAGE_TYPES.includes(picked.type)) return setProblem("The screenshot must be a PNG, JPEG or WebP image.");
    if (picked.size > MAX_BYTES) return setProblem("The screenshot must be 5 MB or smaller.");
    setFile(picked);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return setProblem("Attach a screenshot of your payment confirmation.");
    setBusy(true);
    setProblem("");
    try {
      const form = new FormData();
      form.append("sender_phone", phone);
      form.append("network", network);
      form.append("transaction_id", txn);
      form.append("evidence", file);
      await api.post(`/payments/${payment.reference}/manual-claim/`, form);
      toast.success("Top-up sent for checking", "We'll credit your balance once we see the payment.");
      onDone();
    } catch (caught) {
      setProblem(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-5 p-5 sm:p-6">
      <div>
        <h2 className="text-heading text-ink">1. Send {cedis(payment.amount)}</h2>
        <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-ink-soft">
          <li>
            Dial <span className="font-mono font-semibold text-ink">{manual.ussd}</span> (ExpressPay) from the phone you
            pay with.
          </li>
          <li>Choose the option to send money to a mobile money wallet, then {manual.network}.</li>
          <li>
            Enter <span className="font-mono font-semibold text-ink">{manual.number}</span>
            {manual.account_name ? ` (${manual.account_name})` : ""} and the amount{" "}
            <span className="font-semibold text-ink">{cedis(payment.amount)}</span>.
          </li>
          <li>
            If you are asked for a reference, enter{" "}
            <span className="font-mono font-semibold text-ink">{payment.reference}</span>.
          </li>
          <li>Confirm with your PIN on your own phone. Never share your PIN with anyone, including us.</li>
        </ol>
      </div>

      <form onSubmit={submit} className="space-y-4" noValidate>
        <h2 className="text-heading text-ink">2. Tell us you&apos;ve paid</h2>
        {problem ? <Alert tone="danger">{problem}</Alert> : null}
        <Field label="Number you paid from" htmlFor="manual-phone" required>
          <Input id="manual-phone" inputMode="tel" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="024 123 4567" />
        </Field>
        <Field label="Its network" htmlFor="manual-network" required>
          <Select id="manual-network" value={network} onChange={(event) => setNetwork(event.target.value)}>
            <option value="MTN">MTN</option>
            <option value="TELECEL">Telecel</option>
            <option value="AT">AirtelTigo</option>
          </Select>
        </Field>
        <Field label="Transaction ID" htmlFor="manual-txn" required hint="From the confirmation SMS you received after paying.">
          <Input id="manual-txn" value={txn} onChange={(event) => setTxn(event.target.value)} autoCapitalize="characters" className="font-mono" />
        </Field>
        <div className="space-y-2">
          <p className="text-sm font-medium text-ink">
            Screenshot of the confirmation <span className="text-danger-700">*</span>
          </p>
          {preview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="Your payment confirmation" className="max-h-56 rounded-lg border border-line" />
          ) : null}
          <label className="inline-flex min-h-11 cursor-pointer items-center rounded-lg border border-line px-4 text-sm font-medium text-ink hover:bg-sunken">
            {file ? "Change screenshot" : "Add screenshot"}
            <input type="file" accept={IMAGE_TYPES.join(",")} className="sr-only" onChange={pick} />
          </label>
        </div>
        <Button type="submit" fullWidth size="lg" loading={busy} disabled={!phone || !txn || !file}>
          Submit for checking
        </Button>
        <p className="text-caption text-ink-muted">
          We credit your balance once the money shows on our wallet. If anything doesn&apos;t match, we&apos;ll tell you why and
          nothing is lost.
        </p>
      </form>
    </Card>
  );
}
