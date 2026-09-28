"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { useAuth } from "@/components/auth-provider";
import { ServiceAvatar } from "@/components/brand";
import { AvailabilityLabel } from "@/components/marketplace/availability";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Button, Skeleton, cn } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { cedis } from "@/lib/format";
import type { MarketServiceDetail, Order, Quote } from "@/lib/types";

/**
 * The purchase screen: pick a country, see the price and your balance, get a
 * number.
 *
 * Nothing on it is decided here. The country options and their prices come
 * from the marketplace endpoint; the price shown before confirming comes from
 * the quote endpoint; and the order endpoint prices, checks stock and checks
 * the balance again on its own. This dialog can display a price, never set one.
 */
export function BuyDialog({
  open,
  onClose,
  serviceSlug,
  initialCountry,
}: {
  open: boolean;
  onClose: () => void;
  serviceSlug: string | null;
  initialCountry: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const { user } = useAuth();

  const { data: detail } = useSWR<MarketServiceDetail>(
    open && serviceSlug ? `/marketplace/${serviceSlug}/` : null,
  );

  const [country, setCountry] = React.useState(initialCountry);
  const [quote, setQuote] = React.useState<Quote | null>(null);
  const [quoteError, setQuoteError] = React.useState("");
  const [loadingQuote, setLoadingQuote] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [blocker, setBlocker] = React.useState<{ code: string; message: string } | null>(null);

  // One key per opening: a double tap on "Get number" buys one number, while
  // reopening the dialog is a genuinely new purchase.
  const idempotencyKey = React.useRef(newIdempotencyKey());

  React.useEffect(() => {
    if (open) {
      idempotencyKey.current = newIdempotencyKey();
      setCountry(initialCountry);
      setBlocker(null);
    }
  }, [open, initialCountry]);

  const option = detail?.countries.find((entry) => entry.code === country);
  const purchasable = Boolean(option?.offered && option.availability !== "UNAVAILABLE");

  React.useEffect(() => {
    if (!open || !serviceSlug || !user || !purchasable) {
      setQuote(null);
      return;
    }
    setQuote(null);
    setQuoteError("");
    setLoadingQuote(true);
    let cancelled = false;
    (async () => {
      try {
        const result = await api.get<Quote>("/orders/quote/", { service: serviceSlug, country });
        if (!cancelled) setQuote(result);
      } catch (error) {
        if (!cancelled) {
          setQuoteError(
            error instanceof ApiError ? error.message : "We could not price this right now.",
          );
        }
      } finally {
        if (!cancelled) setLoadingQuote(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, serviceSlug, country, user, purchasable]);

  async function confirm() {
    if (!serviceSlug) return;
    setSubmitting(true);
    setBlocker(null);
    try {
      const order = await api.post<Order>(
        "/orders/",
        { service: serviceSlug, country },
        { idempotencyKey: idempotencyKey.current },
      );
      await globalMutate((key) => {
        const path = Array.isArray(key) ? String(key[0]) : String(key);
        return (
          path.startsWith("/wallet") || path.startsWith("/orders") || path.startsWith("/transactions")
        );
      });
      toast.success("Number on its way", `${detail?.name ?? "Order"} - ${order.reference}`);
      onClose();
      router.push(`/orders/${order.reference}`);
    } catch (error) {
      setBlocker(
        error instanceof ApiError
          ? { code: error.code, message: error.message }
          : { code: "UNKNOWN", message: "Something went wrong. Please try again." },
      );
      setSubmitting(false);
    }
  }

  if (!serviceSlug) return null;

  const insufficient =
    blocker?.code === "INSUFFICIENT_FUNDS" || quote?.sufficient_balance === false;
  const price = quote?.price ?? option?.price;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={detail ? detail.name : "Loading"}
      dismissible={!submitting}
      footer={
        !user ? (
          <Link
            href={`/login?next=${encodeURIComponent(`/services?service=${serviceSlug}`)}`}
            className="block"
          >
            <Button fullWidth>Sign in to get a number</Button>
          </Link>
        ) : (
          <DialogFooter
            insufficient={insufficient}
            submitting={submitting}
            disabled={!purchasable || loadingQuote || !quote || Boolean(quoteError)}
            onCancel={onClose}
            onConfirm={confirm}
            blockerCode={blocker?.code}
          />
        )
      }
    >
      {!detail ? (
        <div className="space-y-3">
          <Skeleton className="h-12 w-full rounded-xl" />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <ServiceAvatar name={detail.name} accentColor={detail.accent_color} size="lg" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">Verification number</p>
              <p className="text-sm text-ink-muted">One-time SMS, delivered to this screen</p>
            </div>
          </div>

          {detail.maintenance_note ? (
            <Alert tone="warn" title="Temporarily unavailable">
              {detail.maintenance_note}
            </Alert>
          ) : null}

          <fieldset>
            <legend className="mb-2 text-sm font-medium text-ink">Country</legend>
            <div className="grid grid-cols-2 gap-2" role="radiogroup">
              {detail.countries.map((entry) => {
                const selected = entry.code === country;
                const unavailable = !entry.offered || entry.availability === "UNAVAILABLE";
                return (
                  <button
                    key={entry.code}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => setCountry(entry.code)}
                    className={cn(
                      "flex min-h-[4.25rem] flex-col items-start justify-center rounded-xl border px-3.5 py-2.5 text-left transition-colors",
                      selected
                        ? "border-brand-600 bg-brand-50 ring-1 ring-brand-600"
                        : "border-line hover:border-line-strong hover:bg-canvas",
                    )}
                  >
                    <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
                      <span aria-hidden>{entry.flag_emoji}</span>
                      {entry.name}
                    </span>
                    <span className="mt-0.5 text-xs text-ink-muted">
                      {unavailable
                        ? entry.offered
                          ? "Unavailable right now"
                          : "Not offered"
                        : cedis(entry.price)}
                    </span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          <dl className="space-y-2.5 rounded-xl border border-line bg-canvas p-3.5 text-sm">
            <Row label="Availability">
              {option ? (
                <AvailabilityLabel
                  availability={option.offered ? option.availability : "UNAVAILABLE"}
                  count={option.available_count ?? null}
                />
              ) : (
                <Skeleton className="h-4 w-20" />
              )}
            </Row>
            <Row label="Price">
              {loadingQuote ? (
                <Skeleton className="h-4 w-16" />
              ) : (
                <span className="tabular text-base font-semibold text-ink">
                  {purchasable && price ? cedis(price) : "-"}
                </span>
              )}
            </Row>
            {user ? (
              <Row label="Wallet balance">
                {loadingQuote ? (
                  <Skeleton className="h-4 w-16" />
                ) : (
                  <span className={cn("tabular", insufficient ? "text-warn-700" : "text-ink-soft")}>
                    {quote ? cedis(quote.wallet_balance) : "-"}
                  </span>
                )}
              </Row>
            ) : null}
          </dl>

          {quoteError ? (
            <Alert tone="danger" title="Could not price this">
              {quoteError}
            </Alert>
          ) : null}

          {insufficient ? (
            <Alert tone="warn" title="Your balance is insufficient.">
              Add money to your wallet with Mobile Money, then come back.
            </Alert>
          ) : blocker ? (
            <BlockerNotice code={blocker.code} message={blocker.message} email={user?.email} />
          ) : null}

          <p className="text-xs leading-relaxed text-ink-muted">
            The price is fixed when you tap Get number. If no code arrives before the number
            expires, it is refunded to your wallet automatically. Numbers come from our
            provider&apos;s shared pool and may have been used before - if a service treats one as
            already registered, report it from your order screen.
          </p>
        </div>
      )}
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
            Add money
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
      <Button variant="secondary" fullWidth className="sm:w-auto" onClick={onCancel} disabled={submitting}>
        Cancel
      </Button>
      <Button fullWidth className="sm:w-auto" onClick={onConfirm} loading={submitting} disabled={disabled}>
        {submitting ? "Getting number" : "Get number"}
      </Button>
    </div>
  );
}

function BlockerNotice({ code, message, email }: { code: string; message: string; email?: string }) {
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
    NO_AVAILABILITY: <>Try the other country, or check back shortly. Nothing was charged.</>,
    PROVIDER_UNAVAILABLE: <>Nothing was charged. Please try again in a moment.</>,
    PLATFORM_AT_CAPACITY: <>Nothing was charged. Please try again in a few minutes.</>,
    PRICE_UNAVAILABLE: <>Nothing was charged. Please try again later.</>,
    UNSUPPORTED_COUNTRY: <>Choose the United States or Canada.</>,
    ACCOUNT_SUSPENDED: <>Contact support to resolve this.</>,
  };
  const soft = ["NO_AVAILABILITY", "PROVIDER_UNAVAILABLE", "PLATFORM_AT_CAPACITY"].includes(code);

  return (
    <Alert tone={soft ? "warn" : "danger"} title={message}>
      {guidance[code] ?? "Please try again in a moment."}
    </Alert>
  );
}
