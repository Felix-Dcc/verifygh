"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { AppHero, HeroStat } from "@/components/app-hero";
import { useAuth } from "@/components/auth-provider";
import {
  AlertIcon,
  ArrowLeftIcon,
  BoltIcon,
  CheckCircleIcon,
  ClockIcon,
  LockIcon,
  PhoneIcon,
  ShieldIcon,
} from "@/components/icons";
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
  Skeleton,
  Spinner,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ManualTopUp } from "@/components/wallet/manual-top-up";
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
  const { data: wallet } = useSWR<Wallet>("/wallet/");
  const [payment, setPayment] = React.useState<PaymentType | null>(null);

  // Back from a hosted checkout (SENDI's callback_url carries our reference):
  // pick the payment up again and wait for the provider to confirm it.
  React.useEffect(() => {
    const reference = new URLSearchParams(window.location.search).get("reference");
    if (!reference || !/^[A-Za-z0-9_-]{6,64}$/.test(reference)) return;
    api
      .get<PaymentType>(`/payments/${reference}/`)
      .then(setPayment)
      .catch(() => undefined);
  }, []);

  function started(next: PaymentType) {
    if (next.checkout_url) {
      // Pay on the provider's page; it sends the customer back here.
      window.location.assign(next.checkout_url);
      return;
    }
    setPayment(next);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <AppHero
        eyebrow={
          <Link href="/wallet" className="inline-flex items-center gap-1.5 hover:text-white">
            <ArrowLeftIcon className="h-3.5 w-3.5" />
            Wallet
          </Link>
        }
        title="Add funds"
        description="Top up with Mobile Money - MTN, Telecel or AT. Your balance updates as soon as the network confirms the payment."
        aside={
          <div className="grid grid-cols-2 gap-2.5">
            <HeroStat
              label="Wallet balance"
              value={wallet ? cedis(wallet.balance) : <Skeleton className="h-6 w-20" />}
            />
            <HeroStat
              label="Top up from"
              value={options ? cedis(options.min_deposit) : <Skeleton className="h-6 w-16" />}
              hint={options ? `Up to ${cedis(options.max_deposit)} per payment` : undefined}
            />
          </div>
        }
      />

      {payment ? (
        <div className="mx-auto max-w-2xl">
          <AwaitingApproval payment={payment} onStartOver={() => setPayment(null)} />
        </div>
      ) : (
        <DepositForm
          options={options}
          wallet={wallet}
          failed={Boolean(optionsError) && !options}
          onRetry={() => retryOptions()}
          onStarted={started}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function DepositForm({
  options,
  wallet,
  failed,
  onRetry,
  onStarted,
}: {
  options: PaymentOptions | undefined;
  wallet: Wallet | undefined;
  failed: boolean;
  onRetry: () => unknown;
  onStarted: (payment: PaymentType) => void;
}) {
  const { user } = useAuth();

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
      // Leaving for a hosted checkout: keep the button busy until the page goes.
      if (payment.checkout_url) return;
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
      <Card className="mx-auto max-w-2xl">
        <LoadError what="the payment options" onRetry={onRetry} />
      </Card>
    );
  }

  if (!options) {
    return (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]" aria-busy>
        <Card className="space-y-4 p-5 sm:p-6">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-24 w-full" />
        </Card>
        <Card className="space-y-3 p-5 sm:p-6">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-12 w-full" />
        </Card>
      </div>
    );
  }

  if (!options.deposits_enabled && options.manual?.enabled) {
    // The gateway is paused but staff are taking transfers by hand.
    return (
      <div className="mx-auto max-w-2xl">
        <ManualTopUp manual={options.manual} quickAmounts={options.quick_amounts} />
      </div>
    );
  }

  if (!options.deposits_enabled) {
    // No form at all, rather than a disabled one. A form that cannot be
    // submitted invites people to keep trying and then contact support; the
    // backend would refuse this anyway, so showing it would be a lie.
    return (
      <Card className="mx-auto flex max-w-2xl flex-col items-center p-8 text-center">
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
  const chosen = options.networks.find((item) => item.value === network);
  const hosted = Boolean(options.hosted_checkout);

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]"
    >
      <Card className="overflow-hidden">
        {formError ? (
          <div className="px-5 pt-5 sm:px-6 sm:pt-6">
            <Alert tone="danger" title="We couldn't start the payment">
              {formError} Nothing was charged.
            </Alert>
          </div>
        ) : null}

        <Section number={1} title="How much?">
          <label htmlFor="amount" className="sr-only">
            Amount to add, in Ghana cedis
          </label>
          <div
            className={cn(
              "flex items-baseline gap-2 rounded-2xl border bg-sunken/60 px-4 py-3 transition-colors focus-within:border-brand-600 focus-within:ring-1 focus-within:ring-brand-600 sm:px-5 sm:py-4",
              fieldErrors.amount ? "border-danger-500" : "border-line",
            )}
          >
            <span className="text-xl font-semibold text-ink-faint sm:text-2xl">GH₵</span>
            <input
              id="amount"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              required
              value={amount}
              onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ""))}
              aria-invalid={Boolean(fieldErrors.amount) || undefined}
              aria-describedby="amount-help"
              placeholder="0.00"
              className="tabular w-full min-w-0 bg-transparent text-3xl font-extrabold tracking-tight text-ink outline-none placeholder:text-ink-faint sm:text-4xl"
            />
          </div>
          {fieldErrors.amount ? (
            <p className="mt-2 text-sm text-danger-700">{fieldErrors.amount}</p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Quick amounts">
            {options.quick_amounts.map((quick) => {
              const active = entered === pesewas(quick);
              return (
                <button
                  key={quick}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setAmount(quick)}
                  className={cn(
                    "tabular min-h-11 rounded-full border px-4 text-sm font-semibold transition-colors",
                    active
                      ? "border-brand-600 bg-brand-600 text-white"
                      : "border-line bg-surface text-ink-soft hover:border-brand-600 hover:text-brand-700",
                  )}
                >
                  {cedis(quick).replace(".00", "")}
                </button>
              );
            })}
          </div>

          <p id="amount-help" className="mt-3 text-caption text-ink-muted">
            Between {cedis(options.min_deposit)} and {cedis(options.max_deposit)} per payment.
            {options.fee_note ? ` ${options.fee_note}` : ""}
          </p>
        </Section>

        <Section number={2} title="Pay from">
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
              className="tabular text-base"
            />
          </Field>

          {/* Always shown, and only ever prefilled from the number.

              This used to appear only when the prefix was unrecognised - so an
              026 number showed "Detected: AirtelTigo" and offered no way to say
              otherwise. Ghana has number portability: that number may well be on
              Telecel now. Its owner had no way to tell us, the charge went to
              AirtelTigo Money, and the code they waited for never arrived. */}
          <fieldset className="mt-5">
            <legend className="text-sm font-medium text-ink">
              Network <span className="text-danger-700">*</span>
            </legend>
            <div role="radiogroup" aria-label="Network" className="mt-2 grid grid-cols-3 gap-2 sm:gap-3">
              {options.networks.map((item) => {
                const selected = network === item.value;
                return (
                  <button
                    key={item.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => {
                      setNetwork(item.value);
                      // Once they have chosen, stop the number field overriding it.
                      userPickedNetwork.current = true;
                    }}
                    className={cn(
                      "relative flex min-h-24 flex-col items-center justify-center gap-2 rounded-2xl border p-3 text-center transition-all",
                      selected
                        ? "border-brand-600 bg-brand-50 ring-1 ring-brand-600"
                        : "border-line bg-surface hover:border-line-strong hover:bg-sunken",
                    )}
                  >
                    {selected ? (
                      <CheckCircleIcon className="absolute right-2 top-2 h-4 w-4 text-brand-600" />
                    ) : null}
                    <NetworkLogo network={item.value} label={item.label} />
                    <span className="text-caption font-semibold leading-tight text-ink">{item.label}</span>
                  </button>
                );
              })}
            </div>
            <p className={cn("mt-2 text-caption", fieldErrors.network ? "text-danger-700" : "text-ink-muted")}>
              {fieldErrors.network ? (
                fieldErrors.network
              ) : detected && network && network !== detected.value ? (
                <span className="text-warn-700">
                  This number started on {detected.label}. That is fine if you have since moved it - we
                  will charge the network you chose.
                </span>
              ) : detected ? (
                "Picked from your number. Tap another if you have moved networks."
              ) : (
                "Choose the network your Mobile Money wallet is on."
              )}
            </p>
          </fieldset>
        </Section>
      </Card>

      <div className="lg:sticky lg:top-6">
        <Card className="overflow-hidden">
          <div className="border-b border-line bg-sunken/60 px-5 py-4 sm:px-6">
            <p className="text-caption font-medium text-ink-muted">You pay</p>
            <p className="tabular mt-0.5 text-3xl font-extrabold tracking-tight text-ink">
              {cedis(entered / 100)}
            </p>
          </div>
          <div className="space-y-5 p-5 sm:p-6">
            <DescriptionList
              items={[
                {
                  label: "From",
                  value:
                    phone.trim() && chosen ? (
                      <span className="inline-flex items-center gap-1.5">
                        <NetworkLogo network={chosen.value} label={chosen.label} size="sm" />
                        <span className="tabular">{localPhone(phone) || phone}</span>
                      </span>
                    ) : (
                      "-"
                    ),
                },
                {
                  label: "Balance now",
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
            >
              {submitting
                ? hosted
                  ? "Opening checkout"
                  : "Sending the prompt"
                : inRange
                  ? `Pay ${cedis(entered / 100)}`
                  : hosted
                    ? "Continue to payment"
                    : "Send payment prompt"}
            </Button>

            <ul className="space-y-2.5 text-caption text-ink-muted">
              <li className="flex gap-2">
                <LockIcon className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                {hosted
                  ? "You finish paying on SENDI's secure checkout page, then come back here."
                  : "A prompt appears on your phone - approve it there with your PIN."}
              </li>
              <li className="flex gap-2">
                <ShieldIcon className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                VerifyGH never sees or stores your Mobile Money PIN.
              </li>
              <li className="flex gap-2">
                <BoltIcon className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                Your balance updates as soon as the network confirms the payment.
              </li>
            </ul>
          </div>
        </Card>
      </div>
    </form>
  );
}

/** One numbered part of the deposit form. */
function Section({
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
      <h2 className="mb-4 flex items-center gap-2.5 text-heading text-ink">
        <span
          aria-hidden
          className="tabular flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-caption font-bold text-white"
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
  const checkoutUrl = status === "PENDING" ? (current?.checkout_url ?? payment.checkout_url ?? "") : "";

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
          {status === "PHONE_AUTH"
            ? "Approve on your phone"
            : checkoutUrl
              ? "Finish paying on SENDI"
              : "Confirming your payment"}
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
          ) : checkoutUrl ? (
            <>
              If you have paid{" "}
              <span className="tabular font-semibold text-ink">{cedis(payment.amount)}</span> on
              SENDI&apos;s page, your balance updates here as soon as SENDI confirms it. If not, open
              the checkout again.
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

        {checkoutUrl ? (
          <Button fullWidth className="mt-6" onClick={() => window.location.assign(checkoutUrl)}>
            Open SENDI checkout
          </Button>
        ) : null}

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
