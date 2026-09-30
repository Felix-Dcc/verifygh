"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { useAuth } from "@/components/auth-provider";
import { AvailabilityLabel, TemporarilyUnavailableBadge } from "@/components/marketplace/availability";
import { CountryFlag } from "@/components/country-flag";
import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Button, DescriptionList, Skeleton, cn } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { cedis } from "@/lib/format";
import type { MarketServiceDetail, Order, Quote } from "@/lib/types";

/**
 * The purchase screen: pick a country, see the price, your balance and what is
 * left after paying, then buy - with the amount written on the button.
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

  // One key per opening: a double tap on the buy button buys one number, while
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
  const paused = Boolean(option?.temporarily_unavailable);
  const purchasable = Boolean(
    option?.offered && option.availability !== "UNAVAILABLE" && !option.temporarily_unavailable,
  );

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
  const balance = quote?.wallet_balance;
  // Display only - the order endpoint does its own sums. Whole pesewas, so
  // 35.00 - 8.50 never shows as 26.499999.
  const pesewas = (amount: string) => Math.round(Number.parseFloat(amount) * 100);
  const after = quote ? (pesewas(quote.wallet_balance) - pesewas(quote.price)) / 100 : null;
  const choosing = (detail?.countries.length ?? 0) > 1;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={detail ? `Buy a ${detail.name} number` : "Buy a number"}
      dismissible={!submitting}
      footer={
        !user ? (
          <Link
            href={`/login?next=${encodeURIComponent(`/services?service=${serviceSlug}`)}`}
            className="block"
          >
            <Button fullWidth>Sign in to buy</Button>
          </Link>
        ) : (
          <DialogFooter
            insufficient={insufficient}
            submitting={submitting}
            disabled={!purchasable || loadingQuote || !quote || Boolean(quoteError)}
            onCancel={onClose}
            onConfirm={confirm}
            blockerCode={blocker?.code}
            price={quote && purchasable ? quote.price : null}
          />
        )
      }
    >
      {!detail ? (
        <div className="space-y-3" aria-busy>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-36 w-full rounded-xl" />
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <ServiceLogo name={detail.name} src={detail.icon_url} slug={detail.slug} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-ink">{detail.name}</p>
              <p className="text-caption text-ink-muted">
                One-time number for an SMS code
                {quote?.ttl_minutes ? `, active for ${quote.ttl_minutes} minutes` : ""}
              </p>
            </div>
          </div>

          {detail.maintenance_note ? (
            <Alert tone="warn" title="Temporarily unavailable">
              {detail.maintenance_note}
            </Alert>
          ) : null}

          {choosing ? (
            <fieldset>
              <legend className="mb-2 text-label text-ink">Country</legend>
              <div className="grid grid-cols-2 gap-2" role="radiogroup">
                {detail.countries.map((entry) => {
                  const selected = entry.code === country;
                  const unavailable =
                    !entry.offered || entry.availability === "UNAVAILABLE" || entry.temporarily_unavailable;
                  return (
                    <button
                      key={entry.code}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => setCountry(entry.code)}
                      className={cn(
                        "flex min-h-14 flex-col items-start justify-center rounded-lg border px-3 py-2 text-left transition-colors",
                        selected
                          ? "border-brand-600 bg-brand-50 ring-1 ring-brand-600"
                          : "border-line hover:border-line-strong hover:bg-sunken",
                      )}
                    >
                      <span className="flex items-center gap-2 text-sm font-medium text-ink">
                        <CountryFlag code={entry.code} size="sm" />
                        {entry.name}
                      </span>
                      <span className="tabular mt-0.5 text-caption text-ink-muted">
                        {entry.temporarily_unavailable
                          ? "Temporarily unavailable"
                          : unavailable
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
          ) : null}

          <div className="rounded-lg border border-line px-4">
            <DescriptionList
              items={[
                ...(choosing
                  ? []
                  : [
                      {
                        label: "Country",
                        value: option ? (
                          <span className="inline-flex items-center gap-2">
                            <CountryFlag code={option.code} size="sm" />
                            {option.name}
                          </span>
                        ) : (
                          <Skeleton className="h-4 w-24" />
                        ),
                      },
                    ]),
                {
                  label: "Availability",
                  value:
                    option && paused ? (
                      <TemporarilyUnavailableBadge />
                    ) : option ? (
                      <AvailabilityLabel
                        availability={option.offered ? option.availability : "UNAVAILABLE"}
                        count={option.available_count ?? null}
                      />
                    ) : (
                      <Skeleton className="h-4 w-20" />
                    ),
                },
                {
                  label: "Number price",
                  emphasis: true,
                  value: loadingQuote ? (
                    <Skeleton className="h-4 w-16" />
                  ) : (
                    <span className="tabular">{purchasable && price ? cedis(price) : "-"}</span>
                  ),
                },
                ...(user && purchasable
                  ? [
                      {
                        label: "Current balance",
                        value: loadingQuote ? (
                          <Skeleton className="h-4 w-16" />
                        ) : (
                          <span className="tabular">{balance ? cedis(balance) : "-"}</span>
                        ),
                      },
                      {
                        label: "After purchase",
                        emphasis: true,
                        value: loadingQuote ? (
                          <Skeleton className="h-4 w-16" />
                        ) : after === null ? (
                          "-"
                        ) : after < 0 ? (
                          <span className="tabular text-warn-700">Short by {cedis(-after)}</span>
                        ) : (
                          <span className="tabular">{cedis(after)}</span>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </div>

          {quoteError ? (
            <Alert tone="danger" title="We couldn't price this number">
              {quoteError} Nothing was charged.
            </Alert>
          ) : null}

          {insufficient ? (
            <Alert tone="warn" title="Not enough in your wallet">
              Add funds with Mobile Money, then come back to this number.
            </Alert>
          ) : blocker ? (
            <BlockerNotice code={blocker.code} message={blocker.message} email={user?.email} />
          ) : null}

          <p className="text-caption text-ink-muted">
            You pay once, when the number is reserved. If no code arrives before it expires, the
            full amount goes back to your wallet automatically. Numbers come from a shared pool and
            may have been used before - if a service says one is already registered, report it from
            the order screen.
          </p>
        </div>
      )}
    </Dialog>
  );
}

function DialogFooter({
  insufficient,
  submitting,
  disabled,
  onCancel,
  onConfirm,
  blockerCode,
  price,
}: {
  insufficient: boolean;
  submitting: boolean;
  disabled: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  blockerCode?: string;
  /** The quoted price, written on the button so the tap is never ambiguous. */
  price: string | null;
}) {
  if (insufficient) {
    return (
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" fullWidth className="sm:w-auto" onClick={onCancel}>
          Cancel
        </Button>
        <Link href="/wallet/deposit" className="sm:w-auto">
          <Button fullWidth className="sm:w-auto">
            Add funds
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
        {submitting ? "Reserving your number" : price ? `Buy for ${cedis(price)}` : "Buy number"}
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
    NO_AVAILABILITY: <>Check back shortly. Nothing was charged.</>,
    PROVIDER_UNAVAILABLE: <>Nothing was charged. Please try again in a moment.</>,
    PLATFORM_AT_CAPACITY: <>Nothing was charged. Please try again in a few minutes.</>,
    PRICE_UNAVAILABLE: <>Nothing was charged. Please try again later.</>,
    UNSUPPORTED_COUNTRY: <>Numbers are available for the United States only.</>,
    TEMPORARILY_UNAVAILABLE: <>Nothing was charged. Please try again shortly.</>,
    ACCOUNT_SUSPENDED: <>Contact support to resolve this.</>,
  };
  const soft = [
    "NO_AVAILABILITY",
    "PROVIDER_UNAVAILABLE",
    "PLATFORM_AT_CAPACITY",
    "TEMPORARILY_UNAVAILABLE",
  ].includes(code);

  return (
    <Alert tone={soft ? "warn" : "danger"} title={message}>
      {guidance[code] ?? "Please try again in a moment."}
    </Alert>
  );
}
