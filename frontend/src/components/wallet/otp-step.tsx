"use client";

import * as React from "react";

import { LockIcon } from "@/components/icons";
import { Alert, Button, Card } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { cedis } from "@/lib/format";
import type { Payment } from "@/lib/types";

/**
 * The step where the provider has texted a code and is waiting for us to
 * submit it.
 *
 * This screen exists because of a real failure: the provider's OTP state was
 * being reported as "processing", so the customer saw "approve on your phone,
 * waiting for confirmation" while holding an SMS code with nowhere to enter
 * it. The charge then expired after 180 seconds, having taken nothing and
 * explained nothing.
 *
 * The distinction this screen must never blur: the code below is a one-time
 * password sent by the payment provider. It is NOT the customer's Mobile Money
 * PIN, which they enter only on their own handset, never here.
 */
export function OtpStep({
  payment,
  onSubmitted,
}: {
  payment: Payment;
  /** Called with the payment as the backend now sees it. */
  onSubmitted: (next: Payment) => void;
}) {
  const [code, setCode] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [attemptsLeft, setAttemptsLeft] = React.useState<number | null>(null);

  const inputRef = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => inputRef.current?.focus(), []);

  const digits = code.replace(/\D/g, "");
  const canSubmit = digits.length >= 4 && !submitting;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;

    setSubmitting(true);
    setError("");
    try {
      const next = await api.post<Payment>(`/payments/${payment.reference}/otp/`, {
        otp: digits,
      });
      onSubmitted(next);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        const remaining = err.details?.attempts_remaining;
        setAttemptsLeft(typeof remaining === "number" ? remaining : null);
      } else {
        setError("We could not submit that code. Please try again.");
      }
      setCode("");
      inputRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="p-6 sm:p-8">
      <div className="flex flex-col items-center text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          <LockIcon className="h-6 w-6" />
        </div>

        <h2 className="mt-5 text-title text-ink">Enter the code we texted you</h2>
        <p className="mt-2 max-w-sm text-sm text-ink-muted">
          To approve{" "}
          <span className="tabular font-semibold text-ink">{cedis(payment.amount)}</span>, enter
          the code sent to{" "}
          <span className="tabular font-medium text-ink">{payment.phone_display}</span>.
        </p>

        {payment.instructions ? (
          <p className="mt-4 max-w-sm rounded-lg bg-sunken px-4 py-3 text-sm text-ink-soft">
            {payment.instructions}
          </p>
        ) : null}

        <form onSubmit={onSubmit} className="mt-6 w-full max-w-xs">
          {error ? (
            <Alert tone="danger" title="That did not work" className="mb-4 text-left">
              {error}
              {attemptsLeft !== null && attemptsLeft > 0 ? (
                <>
                  {" "}
                  {attemptsLeft} {attemptsLeft === 1 ? "try" : "tries"} left.
                </>
              ) : null}
            </Alert>
          ) : null}

          <label htmlFor="otp" className="sr-only">
            One-time code
          </label>
          <input
            ref={inputRef}
            id="otp"
            name="one-time-code"
            // Lets phones offer the code straight from the SMS.
            autoComplete="one-time-code"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={8}
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
            placeholder="······"
            aria-describedby="otp-help"
            className="code h-14 w-full rounded-lg border border-line-strong bg-surface px-4 text-center text-title font-semibold tracking-widest text-ink transition-shadow placeholder:text-ink-faint focus:border-brand-500 focus:shadow-focus focus:outline-none"
          />

          <Button type="submit" size="lg" fullWidth loading={submitting} className="mt-4">
            Confirm payment
          </Button>
        </form>

        {/* The single most important sentence on this screen. */}
        <p
          id="otp-help"
          className="mt-5 max-w-sm rounded-xl bg-warn-50 px-4 py-3 text-xs leading-relaxed text-warn-700"
        >
          This is the one-time code from the payment message. It is{" "}
          <strong>not your Mobile Money PIN</strong>. VerifyGH will never ask for your PIN &mdash;
          only enter that on your own phone.
        </p>

        <p className="tabular mt-4 text-xs text-ink-faint">Reference {payment.reference}</p>
      </div>
    </Card>
  );
}
