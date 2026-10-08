"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { AlertIcon, CheckCircleIcon, ClockIcon, PhoneIcon } from "@/components/icons";
import { NetworkLogo } from "@/components/network-logo";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  DescriptionList,
  Field,
  Input,
  LoadError,
  Select,
  Skeleton,
  Spinner,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { OtpStep } from "@/components/wallet/otp-step";
import { ApiError, api } from "@/lib/api";
import { cedis, localPhone } from "@/lib/format";
import type { PaymentOptions, Payment as PaymentType, Wallet } from "@/lib/types";

/** How long we keep asking the provider before telling the user to check later. */
const POLL_TIMEOUT_MS = 3 * 60 * 1000;

export default function DepositPage() {
  const {
    data: options,
    error: optionsError,
    mutate: retryOptions,
  } = useSWR<PaymentOptions>("/payments/options/");
  const [payment, setPayment] = React.useState<PaymentType | null>(null);

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Add funds"
        description="Top up with Mobile Money. Your balance updates as soon as the network confirms the payment."
        back={{ href: "/wallet", label: "Wallet" }}
      />

      {payment ? (
        <AwaitingApproval payment={payment} onStartOver={() => setPayment(null)} />
      ) : (
        <DepositForm
          options={options}
          failed={Boolean(optionsError) && !options}
          onRetry={() => retryOptions()}
          onStarted={setPayment}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function DepositForm({
  options,
  failed,
  onRetry,
  onStarted,
}: {
  options: PaymentOptions | undefined;
  failed: boolean;
  onRetry: () => unknown;
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

  // Prefill from the prefix, but only until the customer chooses. Without this
  // guard, editing a single digit of the number would silently snap a ported
  // number back to its original network.
  const userPickedNetwork = React.useRef(false);
  React.useEffect(() => {
    if (detected && !userPickedNetwork.current) setNetwork(detected.value);
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
        // Sent whenever set. The backend now honours it over the prefix.
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

  if (failed) {
    return (
      <Card>
        <LoadError what="the payment options" onRetry={onRetry} />
      </Card>
    );
  }

  if (!options) {
    return (
      <Card className="space-y-4 p-5 sm:p-6" aria-busy>
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
      </Card>
    );
  }

  if (!options.deposits_enabled) {
    // No form at all, rather than a disabled one. A form that cannot be
    // submitted invites people to keep trying and then contact support; the
    // backend would refuse this anyway, so showing it would be a lie.
    return (
      <Card className="flex flex-col items-center p-8 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-warn-50 text-warn-700">
          <AlertIcon className="h-5 w-5" />
        </div>
        <h2 className="mt-4 text-heading text-ink">Top-ups are paused</h2>
        <p className="mt-2 max-w-sm text-sm text-ink-muted">
          {options.deposits_disabled_reason}
        </p>
        <ButtonLink href="/wallet" variant="secondary" fullWidth size="lg" className="mt-6 w-full max-w-xs">
          Back to wallet
        </ButtonLink>
      </Card>
    );
  }

  // Display only; the backend validates and charges exactly what it is sent.
  const pesewas = (value: string | undefined) => Math.round((Number.parseFloat(value ?? "0") || 0) * 100);
  const entered = pesewas(amount);
  const inRange = entered >= pesewas(options.min_deposit) && entered <= pesewas(options.max_deposit);
  const networkLabel = options.networks.find((item) => item.value === network)?.label;

  return (
    <Card className="overflow-hidden">
      <form onSubmit={onSubmit} noValidate>
        {formError ? (
          <div className="px-5 pt-5 sm:px-6 sm:pt-6">
            <Alert tone="danger" title="We couldn't start the payment">
              {formError} Nothing was charged.
            </Alert>
          </div>
        ) : null}

        <Step number={1} title="Amount">
          <Field
            label="Amount to add"
            htmlFor="amount"
            error={fieldErrors.amount}
            hint={`Between ${cedis(options.min_deposit)} and ${cedis(options.max_deposit)} per payment.${
              options.fee_note ? ` ${options.fee_note}` : ""
            }`}
            required
          >
            <Input
              id="amount"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              required
              prefix="GH₵"
              value={amount}
              onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ""))}
              invalid={Boolean(fieldErrors.amount)}
              placeholder="0.00"
              className="tabular text-lg font-semibold"
            />
          </Field>

          <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5" role="group" aria-label="Quick amounts">
            {options.quick_amounts.map((quick) => {
              const active = entered === pesewas(quick);
              return (
                <button
                  key={quick}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setAmount(quick)}
                  className={cn(
                    "tabular min-h-11 rounded-lg border text-sm font-medium transition-colors",
                    active
                      ? "border-brand-600 bg-brand-50 text-brand-700 ring-1 ring-brand-600"
                      : "border-line text-ink-soft hover:border-line-strong hover:bg-sunken",
                  )}
                >
                  {cedis(quick).replace(".00", "")}
                </button>
              );
            })}
          </div>
        </Step>

        <Step number={2} title="Mobile Money">
          <div className="space-y-5">
            <Field
              label="Mobile Money number"
              htmlFor="phone"
              error={fieldErrors.phone}
              hint="Any format works - 024 123 4567 or +233 24 123 4567."
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

            {/* Always shown, and only ever prefilled from the number.

                This used to appear only when the prefix was unrecognised - so an
                026 number showed "Detected: AirtelTigo" and offered no way to say
                otherwise. Ghana has number portability: that number may well be on
                Telecel now. Its owner had no way to tell us, the charge went to
                AirtelTigo Money, and the code they waited for never arrived. */}
            <Field
              label="Network"
              htmlFor="network"
              error={fieldErrors.network}
              hint={
                detected && network && network !== detected.value ? (
                  <span className="text-warn-700">
                    This number started on {detected.label}. That is fine if you have since
                    moved it - we will charge the network you chose.
                  </span>
                ) : detected ? (
                  "Filled in from your number. Change it if you have moved networks."
                ) : (
                  "Choose the network your Mobile Money wallet is on."
                )
              }
              required
            >
              <div className="flex items-center gap-3">
                {/* The chosen network's logo, so a wrong pick is easy to spot. */}
                {network ? (
                  <NetworkLogo network={network} className="h-11 w-11" />
                ) : (
                  <span aria-hidden className="h-11 w-11 shrink-0 rounded-xl border border-dashed border-line-strong" />
                )}
                <Select
                  id="network"
                  value={network}
                  onChange={(event) => {
                    setNetwork(event.target.value);
                    // Once they have chosen, stop the number field overriding it.
                    userPickedNetwork.current = true;
                  }}
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
              </div>
            </Field>
          </div>
        </Step>

        <Step number={3} title="Review and pay">
          <DescriptionList
            items={[
              {
                label: "You pay",
                emphasis: true,
                value: <span className="tabular">{entered > 0 ? cedis(entered / 100) : "-"}</span>,
              },
              {
                label: "From",
                value:
                  phone.trim() && networkLabel ? (
                    <span>
                      {networkLabel} <span className="tabular">{localPhone(phone) || phone}</span>
                    </span>
                  ) : (
                    "-"
                  ),
              },
              {
                label: "Current balance",
                value: <span className="tabular">{cedis(wallet?.balance)}</span>,
              },
              {
                label: "Balance after",
                emphasis: true,
                value: (
                  <span className="tabular">
                    {entered > 0 ? cedis((pesewas(wallet?.balance) + entered) / 100) : "-"}
                  </span>
                ),
              },
            ]}
          />

          <Button
            type="submit"
            size="lg"
            fullWidth
            loading={submitting}
            icon={<PhoneIcon className="h-5 w-5" />}
            className="mt-5"
          >
            {submitting
              ? "Sending the prompt"
              : inRange
                ? `Pay ${cedis(entered / 100)}`
                : "Send payment prompt"}
          </Button>

          <p className="mt-3 text-center text-caption text-ink-muted">
            A prompt appears on your phone - approve it there with your PIN. VerifyGH never sees or
            stores your Mobile Money PIN.
          </p>
        </Step>
      </form>
    </Card>
  );
}

/** One numbered part of the deposit form. */
function Step({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-line p-5 first:border-t-0 sm:p-6" aria-label={title}>
      <h2 className="mb-4 flex items-center gap-2.5 text-sm font-semibold text-ink">
        <span
          aria-hidden
          className="tabular flex h-6 w-6 items-center justify-center rounded-full bg-sunken text-caption font-semibold text-ink-soft"
        >
          {number}
        </span>
        {title}
      </h2>
      {children}
    </section>
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

  // Poll our own API, which also asks the provider (at most every few seconds),
  // so a payment the provider has already failed says so at once instead of at
  // the next scheduled sweep. The wallet is only credited by a verified
  // callback or the provider's own answer - this screen reflects that, it
  // never decides it.
  const { data: current, mutate } = useSWR<PaymentType>(
    timedOut ? null : `/payments/${payment.reference}/`,
    (path: string) => api.post<PaymentType>(`${path}refresh/`, {}),
    {
      refreshInterval: (latest) => {
        if (!latest) return 4000;
        if (terminal.includes(latest.status)) return 0;
        // Nothing to wait for while the customer is typing a code.
        if (latest.status === "OTP_REQUIRED") return 0;
        return 4000;
      },
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
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-success-50 text-success-700">
          <CheckCircleIcon className="h-6 w-6" />
        </div>
        <h2 className="mt-4 text-title text-ink">Payment received</h2>
        <p className="mt-1.5 text-sm text-ink-muted">
          <span className="tabular font-medium text-ink">{cedis(payment.amount)}</span> has been
          added to your wallet.
        </p>
        <p className="mt-3 text-caption text-ink-faint">
          Reference <span className="code">{payment.reference}</span>
        </p>

        <div className="mt-6 flex flex-col gap-2 sm:flex-row">
          <Button fullWidth onClick={() => router.push("/services")}>
            Buy a number
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
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-danger-50 text-danger-700">
          <ClockIcon className="h-6 w-6" />
        </div>
        <h2 className="mt-4 text-title text-ink">
          {status === "EXPIRED" ? "The prompt expired" : "Payment did not go through"}
        </h2>
        <p className="mt-1.5 text-sm text-ink-muted">
          {current?.failure_reason ||
            "No money has left your Mobile Money account. You can try again."}
        </p>
        <p className="mt-3 text-caption text-ink-faint">
          Reference <span className="code">{payment.reference}</span>
        </p>

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

  if (status === "OTP_REQUIRED") {
    return (
      <OtpStep
        payment={current ?? payment}
        onSubmitted={(next) => {
          // Trust the backend's view of the payment, not the fact that the
          // request returned 200. Submitting a code is not the same as being
          // paid: the provider may still want a handset approval, and only a
          // verified callback ever credits the wallet.
          mutate(next, { revalidate: false });
          startedAt.current = Date.now();
          setTimedOut(false);
        }}
      />
    );
  }

  return (
    <Card className="p-6 sm:p-8">
      <div className="flex flex-col items-center text-center">
        <div className="relative flex h-16 w-16 items-center justify-center">
          <span className="absolute h-16 w-16 animate-pulse-ring rounded-full bg-brand-300" aria-hidden />
          <span className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
            <PhoneIcon className="h-6 w-6" />
          </span>
        </div>

        <h2 className="mt-5 text-title text-ink">
          {status === "PHONE_AUTH" ? "Approve on your phone" : "Starting your payment"}
        </h2>
        <p className="mt-2 max-w-sm text-sm text-ink-muted">
          {status === "PHONE_AUTH" ? (
            <>
              We sent a prompt for{" "}
              <span className="tabular font-semibold text-ink">{cedis(payment.amount)}</span> to{" "}
              <span className="tabular font-medium text-ink">{payment.phone_display}</span> on{" "}
              <span className="inline-flex items-center gap-1.5 whitespace-nowrap align-middle font-medium text-ink">
                <NetworkLogo network={payment.network} label={payment.network_label} size="sm" />
                {payment.network_label}
              </span>
              . Enter your Mobile Money PIN on your handset to approve it.
            </>
          ) : (
            <>
              We are setting up a payment of{" "}
              <span className="tabular font-semibold text-ink">{cedis(payment.amount)}</span>{" "}
              from{" "}
              <span className="tabular font-medium text-ink">{payment.phone_display}</span>.
              This usually takes a few seconds.
            </>
          )}
        </p>

        {payment.instructions ? (
          <p className="mt-4 max-w-sm rounded-lg bg-sunken px-4 py-3 text-sm text-ink-soft">
            {payment.instructions}
          </p>
        ) : null}

        {!timedOut ? (
          <div className="mt-6 flex items-center gap-2 text-sm text-ink-muted">
            <Spinner className="h-4 w-4" />
            Waiting for the network to confirm…
          </div>
        ) : (
          <Alert tone="warn" className="mt-6 max-w-sm text-left" title="Still waiting">
            We have not had confirmation yet. If you approved the prompt, check again - your
            balance will update as soon as the network confirms it.
          </Alert>
        )}

        <p className="mt-4 text-caption text-ink-faint">
          Reference <span className="code">{payment.reference}</span>
        </p>

        <div className="mt-6 flex w-full flex-col gap-2 sm:flex-row">
          <Button variant="secondary" fullWidth loading={checking} onClick={checkNow}>
            Check again
          </Button>
          <Button variant="ghost" fullWidth onClick={() => router.push("/wallet")}>
            I will check later
          </Button>
        </div>

        <p className="mt-4 text-caption text-ink-faint">
          You can safely leave this page. The payment completes on its own.
        </p>
      </div>
    </Card>
  );
}
