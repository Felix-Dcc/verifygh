"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { CheckCircleIcon, ClockIcon, PhoneIcon } from "@/components/icons";
import {
  Alert,
  Button,
  Card,
  Field,
  Input,
  Select,
  Skeleton,
  Spinner,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, localPhone } from "@/lib/format";
import type { PaymentOptions, Payment as PaymentType, Wallet } from "@/lib/types";

/** How long we keep asking the provider before telling the user to check later. */
const POLL_TIMEOUT_MS = 3 * 60 * 1000;

export default function DepositPage() {
  const { data: options } = useSWR<PaymentOptions>("/payments/options/");
  const [payment, setPayment] = React.useState<PaymentType | null>(null);

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Add money"
        description="Top up your VerifyGH wallet with Mobile Money. Your balance updates as soon as the network confirms the payment."
        back={{ href: "/wallet", label: "Wallet" }}
      />

      {payment ? (
        <AwaitingApproval payment={payment} onStartOver={() => setPayment(null)} />
      ) : (
        <DepositForm options={options} onStarted={setPayment} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function DepositForm({
  options,
  onStarted,
}: {
  options: PaymentOptions | undefined;
  onStarted: (payment: PaymentType) => void;
}) {
  const { user } = useAuth();
  const { data: wallet } = useSWR<Wallet>("/wallet/");

  const [amount, setAmount] = React.useState("");
  const [phone, setPhone] = React.useState(user?.phone ? localPhone(user.phone) : "");
  const [network, setNetwork] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  // Detect the network from the prefix so the user does not have to pick.
  const detected = React.useMemo(() => {
    const digits = phone.replace(/\D/g, "");
    const local = digits.startsWith("233") ? `0${digits.slice(3)}` : digits;
    const prefix = local.slice(0, 3);
    return options?.networks.find((item) => item.prefixes.includes(prefix)) ?? null;
  }, [phone, options]);

  React.useEffect(() => {
    if (detected) setNetwork(detected.value);
  }, [detected]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setFormError("");
    setFieldErrors({});
    setSubmitting(true);

    try {
      const payment = await api.post<PaymentType>("/payments/deposit/", {
        amount,
        phone,
        ...(network ? { network } : {}),
      });
      onStarted(payment);
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldErrors(error.fieldErrors);
        setFormError(Object.keys(error.fieldErrors).length > 0 ? "" : error.message);
      } else {
        setFormError("Something went wrong. Please try again.");
      }
      setSubmitting(false);
    }
  }

  if (!options) {
    return (
      <Card className="space-y-4 p-5">
        <Skeleton className="h-12 w-full rounded-xl" />
        <Skeleton className="h-12 w-full rounded-xl" />
        <Skeleton className="h-12 w-full rounded-xl" />
      </Card>
    );
  }

  return (
    <Card className="p-5 sm:p-6">
      <form onSubmit={onSubmit} noValidate className="space-y-5">
        {formError ? (
          <Alert tone="danger" title="Could not start the payment">
            {formError}
          </Alert>
        ) : null}

        <div>
          <Field
            label="Amount"
            htmlFor="amount"
            error={fieldErrors.amount}
            hint={`Between ${cedis(options.min_deposit)} and ${cedis(options.max_deposit)} per payment.`}
            required
          >
            <Input
              id="amount"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              required
              prefix="&#8373;"
              value={amount}
              onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ""))}
              invalid={Boolean(fieldErrors.amount)}
              placeholder="0.00"
              className="tabular text-lg font-semibold"
            />
          </Field>

          <div className="mt-2.5 grid grid-cols-5 gap-2">
            {options.quick_amounts.map((quick) => {
              const active = amount === quick;
              return (
                <button
                  key={quick}
                  type="button"
                  onClick={() => setAmount(quick)}
                  className={cn(
                    "tabular rounded-lg py-2.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-brand-600 text-white"
                      : "bg-line/40 text-ink-soft hover:bg-line/70",
                  )}
                >
                  {cedis(quick).replace(".00", "")}
                </button>
              );
            })}
          </div>
        </div>

        <Field
          label="Mobile Money number"
          htmlFor="phone"
          error={fieldErrors.phone}
          hint={
            detected ? (
              <span className="text-brand-700">
                Detected: {detected.label}. The prompt goes to this number.
              </span>
            ) : (
              "Any format works - 024 123 4567 or +233 24 123 4567."
            )
          }
          required
        >
          <Input
            id="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel-national"
            required
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            invalid={Boolean(fieldErrors.phone)}
            placeholder="024 123 4567"
            className="tabular"
          />
        </Field>

        {!detected ? (
          <Field
            label="Mobile Money network"
            htmlFor="network"
            error={fieldErrors.network}
            hint="We could not tell from the number, so please choose."
            required
          >
            <Select
              id="network"
              value={network}
              onChange={(event) => setNetwork(event.target.value)}
              invalid={Boolean(fieldErrors.network)}
              required
            >
              <option value="">Select your network</option>
              {options.networks.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}

        <div className="rounded-xl bg-canvas p-3.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-ink-muted">Current balance</span>
            <span className="tabular font-medium text-ink">{cedis(wallet?.balance)}</span>
          </div>
          {amount ? (
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-ink-muted">Balance after</span>
              <span className="tabular font-semibold text-ink">
                {cedis(
                  (
                    Number.parseFloat(wallet?.balance ?? "0") +
                    (Number.parseFloat(amount) || 0)
                  ).toFixed(2),
                )}
              </span>
            </div>
          ) : null}
        </div>

        <Button
          type="submit"
          size="lg"
          fullWidth
          loading={submitting}
          icon={<PhoneIcon className="h-5 w-5" />}
        >
          Send payment prompt
        </Button>

        <p className="text-center text-xs leading-relaxed text-ink-muted">
          You will be asked to approve the payment on your phone. VerifyGH never sees or stores
          your Mobile Money PIN.
        </p>
      </form>
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function AwaitingApproval({
  payment,
  onStartOver,
}: {
  payment: PaymentType;
  onStartOver: () => void;
}) {
  const router = useRouter();
  const toast = useToast();
  const startedAt = React.useRef(Date.now());
  const [timedOut, setTimedOut] = React.useState(false);
  const [checking, setChecking] = React.useState(false);

  const terminal = ["SUCCESS", "FAILED", "CANCELLED", "EXPIRED"];

  // Poll our own API. The wallet is only credited by a verified provider
  // callback - this screen reflects that, it never decides it.
  const { data: current, mutate } = useSWR<PaymentType>(
    timedOut ? null : `/payments/${payment.reference}/`,
    {
      refreshInterval: (latest) =>
        latest && terminal.includes(latest.status) ? 0 : 4000,
      fallbackData: payment,
    },
  );

  const status = current?.status ?? payment.status;

  React.useEffect(() => {
    if (terminal.includes(status)) return;
    const timer = window.setInterval(() => {
      if (Date.now() - startedAt.current > POLL_TIMEOUT_MS) setTimedOut(true);
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  React.useEffect(() => {
    if (status !== "SUCCESS") return;
    globalMutate((key) => {
      const path = Array.isArray(key) ? String(key[0]) : String(key);
      return path.startsWith("/wallet") || path.startsWith("/transactions");
    });
    toast.success("Payment received", `${cedis(payment.amount)} added to your wallet.`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  async function checkNow() {
    setChecking(true);
    try {
      // Asks the provider directly - the safety net for a dropped callback.
      await api.post(`/payments/${payment.reference}/refresh/`, {});
      await mutate();
      setTimedOut(false);
      startedAt.current = Date.now();
    } catch {
      toast.error("Could not check", "Try again in a moment.");
    } finally {
      setChecking(false);
    }
  }

  if (status === "SUCCESS") {
    return (
      <Card className="p-6 text-center sm:p-8">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-success-50 text-success-700">
          <CheckCircleIcon className="h-7 w-7" />
        </div>
        <h2 className="mt-4 text-xl font-semibold text-ink">Payment received</h2>
        <p className="mt-1.5 text-sm text-ink-muted">
          <span className="tabular font-medium text-ink">{cedis(payment.amount)}</span> has been
          added to your wallet.
        </p>
        <p className="tabular mt-3 text-xs text-ink-faint">Reference {payment.reference}</p>

        <div className="mt-6 flex flex-col gap-2 sm:flex-row">
          <Button fullWidth onClick={() => router.push("/services")}>
            Buy verification
          </Button>
          <Button variant="secondary" fullWidth onClick={() => router.push("/wallet")}>
            Back to wallet
          </Button>
        </div>
      </Card>
    );
  }

  if (["FAILED", "CANCELLED", "EXPIRED"].includes(status)) {
    return (
      <Card className="p-6 text-center sm:p-8">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-danger-50 text-danger-700">
          <ClockIcon className="h-7 w-7" />
        </div>
        <h2 className="mt-4 text-xl font-semibold text-ink">
          {status === "EXPIRED" ? "The prompt expired" : "Payment did not go through"}
        </h2>
        <p className="mt-1.5 text-sm text-ink-muted">
          {current?.failure_reason ||
            "No money has left your Mobile Money account. You can try again."}
        </p>
        <p className="tabular mt-3 text-xs text-ink-faint">Reference {payment.reference}</p>

        <div className="mt-6 flex flex-col gap-2 sm:flex-row">
          <Button fullWidth onClick={onStartOver}>
            Try again
          </Button>
          <Button variant="secondary" fullWidth onClick={() => router.push("/wallet")}>
            Back to wallet
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-6 sm:p-8">
      <div className="flex flex-col items-center text-center">
        <div className="relative flex h-16 w-16 items-center justify-center">
          <span className="absolute h-16 w-16 animate-pulse-ring rounded-full bg-brand-300" aria-hidden />
          <span className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
            <PhoneIcon className="h-7 w-7" />
          </span>
        </div>

        <h2 className="mt-5 text-xl font-semibold text-ink">Approve on your phone</h2>
        <p className="mt-2 max-w-sm text-sm text-ink-muted">
          We sent a prompt for{" "}
          <span className="tabular font-semibold text-ink">{cedis(payment.amount)}</span> to{" "}
          <span className="tabular font-medium text-ink">{payment.phone_display}</span> on{" "}
          {payment.network_label}. Enter your PIN on your handset to approve it.
        </p>

        {payment.instructions ? (
          <p className="mt-4 max-w-sm rounded-xl bg-canvas px-4 py-3 text-sm text-ink-soft">
            {payment.instructions}
          </p>
        ) : null}

        {!timedOut ? (
          <div className="mt-6 flex items-center gap-2 text-sm text-ink-muted">
            <Spinner className="h-4 w-4" />
            Waiting for confirmation...
          </div>
        ) : (
          <Alert tone="warn" className="mt-6 max-w-sm text-left" title="Still waiting">
            We have not had confirmation yet. If you approved the prompt, check again - your
            balance will update as soon as the network confirms it.
          </Alert>
        )}

        <p className="tabular mt-4 text-xs text-ink-faint">Reference {payment.reference}</p>

        <div className="mt-6 flex w-full flex-col gap-2 sm:flex-row">
          <Button variant="secondary" fullWidth loading={checking} onClick={checkNow}>
            Check again
          </Button>
          <Button variant="ghost" fullWidth onClick={() => router.push("/wallet")}>
            I will check later
          </Button>
        </div>

        <p className="mt-4 text-xs text-ink-faint">
          You can safely leave this page. The payment completes on its own.
        </p>
      </div>
    </Card>
  );
}
