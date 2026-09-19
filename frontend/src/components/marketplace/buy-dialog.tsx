"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { mutate as globalMutate } from "swr";

import { useAuth } from "@/components/auth-provider";
import { ServiceAvatar } from "@/components/brand";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Button, Skeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { cedis } from "@/lib/format";
import type { CountryOption, Order, Quote, Service } from "@/lib/types";

/**
 * The purchase confirmation.
 *
 * The price shown here comes from the server's quote endpoint, and the order
 * endpoint prices independently again - this dialog can only ever *display* a
 * price, never set one. The insufficient-balance path is a first-class state,
 * because on a prepaid wallet it is the most common outcome, not an error.
 */
export function BuyDialog({
  open,
  onClose,
  service,
  country,
}: {
  open: boolean;
  onClose: () => void;
  service: Service | null;
  country: CountryOption | null;
}) {
  const router = useRouter();
  const toast = useToast();
  const { user } = useAuth();

  const [quote, setQuote] = React.useState<Quote | null>(null);
  const [quoteError, setQuoteError] = React.useState("");
  const [loadingQuote, setLoadingQuote] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [blocker, setBlocker] = React.useState<{ code: string; message: string } | null>(null);

  // A fresh idempotency key per dialog opening: a double-tap on "Confirm" must
  // buy one number, but reopening the dialog is a genuinely new purchase.
  const idempotencyKey = React.useRef(newIdempotencyKey());

  React.useEffect(() => {
    if (!open || !service || !country) return;

    idempotencyKey.current = newIdempotencyKey();
    setQuote(null);
    setQuoteError("");
    setBlocker(null);
    setLoadingQuote(true);

    let cancelled = false;
    (async () => {
      try {
        const result = await api.get<Quote>("/orders/quote/", {
          service: service.slug,
          country: country.code,
        });
        if (!cancelled) setQuote(result);
      } catch (error) {
        if (!cancelled) {
          setQuoteError(
            error instanceof ApiError
              ? error.message
              : "We could not price this right now. Please try again.",
          );
        }
      } finally {
        if (!cancelled) setLoadingQuote(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, service, country]);

  async function confirm() {
    if (!service || !country) return;
    setSubmitting(true);
    setBlocker(null);

    try {
      const order = await api.post<Order>(
        "/orders/",
        { service: service.slug, country: country.code },
        { idempotencyKey: idempotencyKey.current },
      );
      // A purchase changes the balance and the order lists - and nothing else.
      await globalMutate((key) => {
        const path = Array.isArray(key) ? String(key[0]) : String(key);
        return (
          path.startsWith("/wallet") ||
          path.startsWith("/orders") ||
          path.startsWith("/transactions")
        );
      });
      toast.success("Order placed", `${service.name} - ${order.reference}`);
      onClose();
      router.push(`/orders/${order.reference}`);
    } catch (error) {
      if (error instanceof ApiError) {
        setBlocker({ code: error.code, message: error.message });
      } else {
        setBlocker({ code: "UNKNOWN", message: "Something went wrong. Please try again." });
      }
      setSubmitting(false);
    }
  }

  if (!service || !country) return null;

  const insufficient = blocker?.code === "INSUFFICIENT_FUNDS" || quote?.sufficient_balance === false;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Confirm your purchase"
      dismissible={!submitting}
      footer={
        <DialogFooter
          insufficient={insufficient}
          submitting={submitting}
          disabled={loadingQuote || !quote || Boolean(quoteError)}
          onCancel={onClose}
          onConfirm={confirm}
          blockerCode={blocker?.code}
        />
      }
    >
      <div className="space-y-4">
        <div className="flex items-center gap-3 rounded-xl border border-line bg-canvas p-3.5">
          <ServiceAvatar name={service.name} accentColor={service.accent_color} size="lg" />
          <div className="min-w-0">
            <p className="text-base font-semibold text-ink">{service.name}</p>
            <p className="text-sm text-ink-muted">
              <span aria-hidden>{country.flag_emoji}</span> {country.name}
              {country.supports_sms ? (
                <span className="ml-2 rounded-md bg-line/60 px-1.5 py-0.5 text-2xs font-medium text-ink-soft">
                  SMS
                </span>
              ) : null}
              {country.supports_voice ? (
                <span className="ml-1 rounded-md bg-line/60 px-1.5 py-0.5 text-2xs font-medium text-ink-soft">
                  Voice
                </span>
              ) : null}
            </p>
          </div>
        </div>

        {quoteError ? (
          <Alert tone="danger" title="Could not price this">
            {quoteError}
          </Alert>
        ) : (
          <dl className="space-y-2.5 text-sm">
            <Row label="Service price">
              {loadingQuote ? (
                <Skeleton className="h-4 w-16" />
              ) : (
                <span className="tabular font-semibold text-ink">{cedis(quote?.price)}</span>
              )}
            </Row>
            <Row label="Wallet balance">
              {loadingQuote ? (
                <Skeleton className="h-4 w-16" />
              ) : (
                <span className="tabular text-ink-soft">{cedis(quote?.wallet_balance)}</span>
              )}
            </Row>
            {quote && !loadingQuote ? (
              <Row label="Balance after">
                <span className="tabular text-ink-soft">
                  {cedis(
                    (
                      Number.parseFloat(quote.wallet_balance) - Number.parseFloat(quote.price)
                    ).toFixed(2),
                  )}
                </span>
              </Row>
            ) : null}
            <Row label="Number valid for">
              <span className="text-ink-soft">
                {quote ? `about ${quote.ttl_minutes} minutes` : "-"}
              </span>
            </Row>
          </dl>
        )}

        {insufficient ? (
          <Alert tone="warn" title="Your balance is insufficient.">
            Add money to your wallet and the purchase will go straight through.
          </Alert>
        ) : blocker ? (
          <BlockerNotice code={blocker.code} message={blocker.message} email={user?.email} />
        ) : null}

        {!insufficient && !blocker && quote ? (
          <p className="text-xs leading-relaxed text-ink-muted">
            If no verification code arrives before the number expires, the full{" "}
            {cedis(quote.price)} is returned to your wallet automatically. You are responsible for
            complying with the terms of the service you verify with.
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="flex items-center">{children}</dd>
    </div>
  );
}

function DialogFooter({
  insufficient,
  submitting,
  disabled,
  onCancel,
  onConfirm,
  blockerCode,
}: {
  insufficient: boolean;
  submitting: boolean;
  disabled: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  blockerCode?: string;
}) {
  if (insufficient) {
    return (
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" fullWidth className="sm:w-auto" onClick={onCancel}>
          Cancel
        </Button>
        <Link href="/wallet/deposit" className="sm:w-auto">
          <Button fullWidth className="sm:w-auto">
            Add Money
          </Button>
        </Link>
      </div>
    );
  }

  if (blockerCode === "EMAIL_NOT_VERIFIED") {
    return (
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" fullWidth className="sm:w-auto" onClick={onCancel}>
          Close
        </Button>
        <Link href="/account" className="sm:w-auto">
          <Button fullWidth className="sm:w-auto">
            Confirm my email
          </Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      <Button
        variant="secondary"
        fullWidth
        className="sm:w-auto"
        onClick={onCancel}
        disabled={submitting}
      >
        Cancel
      </Button>
      <Button
        fullWidth
        className="sm:w-auto"
        onClick={onConfirm}
        loading={submitting}
        disabled={disabled}
      >
        {submitting ? "Placing order" : "Confirm purchase"}
      </Button>
    </div>
  );
}

function BlockerNotice({
  code,
  message,
  email,
}: {
  code: string;
  message: string;
  email?: string;
}) {
  const guidance: Record<string, React.ReactNode> = {
    EMAIL_NOT_VERIFIED: (
      <>
        We sent a confirmation link to {email ?? "your email address"}. Confirm it and you can buy
        straight away.
      </>
    ),
    TERMS_NOT_ACCEPTED: (
      <>
        Accept the current Terms and{" "}
        <Link href="/acceptable-use" className="underline">
          Acceptable Use Policy
        </Link>{" "}
        from your dashboard to continue.
      </>
    ),
    TOO_MANY_ACTIVE_ORDERS: <>Finish or cancel one of your open orders, then try again.</>,
    DAILY_ORDER_LIMIT: <>You have hit today&apos;s order limit. It resets in 24 hours.</>,
    DAILY_SPEND_LIMIT: <>You have hit today&apos;s spending limit. It resets in 24 hours.</>,
    NO_AVAILABILITY: <>Try another country, or check back shortly.</>,
    ACCOUNT_SUSPENDED: <>Contact support to resolve this.</>,
  };

  return (
    <Alert tone={code === "NO_AVAILABILITY" ? "warn" : "danger"} title={message}>
      {guidance[code] ?? "Please try again in a moment."}
    </Alert>
  );
}
