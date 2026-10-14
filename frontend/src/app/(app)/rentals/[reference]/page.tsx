"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import { CheckCircleIcon, ClockIcon, CopyIcon, InboxIcon, PlusIcon, RefreshIcon } from "@/components/icons";
import { RentalLogo, RentalStatusBadge, timeLeft, useSecondsLeft } from "@/components/rentals/rental-ui";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  DescriptionList,
  LoadError,
  Skeleton,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import {
  cedis,
  copyToClipboard,
  formatDateTime,
  groupInternational,
  nationalNumber,
  relativeTime,
} from "@/lib/format";
import type { Rental, RentalCatalog, RentalMessage } from "@/lib/types";

/** Refresh the wallet and lists after money moved. */
function refreshMoney() {
  return globalMutate((key) => {
    const path = Array.isArray(key) ? String(key[0]) : String(key);
    return path.startsWith("/wallet") || path.startsWith("/transactions") || path === "/rentals/";
  });
}

export default function RentalDetailPage() {
  const { reference } = useParams<{ reference: string }>();
  const toast = useToast();

  // While it is live, the page asks every few seconds; the server reads the
  // provider at most every 10 seconds however often it is asked.
  const { data: rental, error, isLoading, mutate } = useSWR<Rental>(`/rentals/${reference}/`, {
    refreshInterval: (latest) =>
      latest && (latest.status === "ACTIVE" || latest.status === "PENDING")
        ? Math.max(5, latest.poll_interval_seconds || 10) * 1000
        : 0,
  });

  // Tell the customer when something new lands while they watch.
  const seen = React.useRef<number | null>(null);
  const lastStatus = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!rental) return;
    if (seen.current !== null && rental.messages.length > seen.current) {
      toast.success("New message", `On your ${rental.service_name} number.`);
    }
    if (lastStatus.current && lastStatus.current !== rental.status) refreshMoney();
    seen.current = rental.messages.length;
    lastStatus.current = rental.status;
  }, [rental, toast]);

  const [confirmCancel, setConfirmCancel] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [extending, setExtending] = React.useState(false);

  async function cancel() {
    setCancelling(true);
    try {
      await api.post(`/rentals/${reference}/cancel/`, {});
      await mutate();
      await refreshMoney();
      toast.success("Rental cancelled", "Your money is back in your wallet.");
      setConfirmCancel(false);
    } catch (caught) {
      toast.error("Could not cancel", caught instanceof ApiError ? caught.message : "Please try again.");
      await mutate();
      setConfirmCancel(false);
    } finally {
      setCancelling(false);
    }
  }

  if (isLoading) return <DetailSkeleton />;

  if (error && !rental && !(error instanceof ApiError && error.status === 404)) {
    return (
      <div>
        <PageHeader title="Rental" back={{ href: "/rentals", label: "Rentals" }} />
        <Card>
          <LoadError what={`rental ${reference}`} onRetry={() => mutate()} />
        </Card>
      </div>
    );
  }

  if (error || !rental) {
    return (
      <div>
        <PageHeader title="Rental not found" back={{ href: "/rentals", label: "Rentals" }} />
        <Card className="p-6">
          <p className="text-sm text-ink-muted">
            We could not find a rental with the reference{" "}
            <span className="tabular font-medium text-ink">{reference}</span>.
          </p>
          <ButtonLink href="/rentals" className="mt-4">
            Go to rentals
          </ButtonLink>
        </Card>
      </div>
    );
  }

  const ended = ["EXPIRED", "REFUNDED", "FAILED"].includes(rental.status);
  const extensionPending = rental.extensions.some((extension) => extension.status === "PENDING");

  return (
    <div className="space-y-6">
      <PageHeader
        title={rental.all_services ? "Any-app number" : `${rental.service_name} number`}
        icon={<RentalLogo rental={rental} size="lg" />}
        back={{ href: "/rentals", label: "Rentals" }}
        description={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="code text-ink-soft">{rental.reference}</span>
            <span aria-hidden>&middot;</span>
            <span>{rental.duration_label}</span>
            <span aria-hidden>&middot;</span>
            <span className="tabular">{cedis(rental.price)}</span>
          </span>
        }
        action={<RentalStatusBadge status={rental.status} />}
      />

      <div className="space-y-3 empty:hidden">
        {rental.status === "PENDING" ? (
          <Alert tone="info" title="Setting up your number">
            Our provider is preparing your number. This usually takes a few seconds - this page updates
            by itself. If it can&apos;t be set up, the full amount comes back to your wallet.
          </Alert>
        ) : null}
        {rental.status === "FAILED" ? (
          <Alert tone="warn" title="This rental didn't go through">
            {rental.failure_reason || "Our provider could not supply a number."}{" "}
            {cedis(rental.refunded_amount)} is back in your{" "}
            <Link href="/transactions" className="underline">
              wallet
            </Link>
            .
          </Alert>
        ) : null}
        {rental.status === "REFUNDED" ? (
          <Alert tone="brand" title="Cancelled and refunded">
            {cedis(rental.refunded_amount)} went back to your{" "}
            <Link href="/transactions" className="underline">
              wallet
            </Link>
            . The number no longer receives messages.
          </Alert>
        ) : null}
        {rental.status === "EXPIRED" ? (
          <Alert tone="neutral" title="This rental has ended">
            The number stopped receiving messages on {formatDateTime(rental.ended_at ?? rental.ends_at)}. Messages
            it received are still below.
          </Alert>
        ) : null}
        {extensionPending ? (
          <Alert tone="info" title="Confirming your extension">
            We&apos;re confirming the extra time with our provider. If it doesn&apos;t go through, the
            extension&apos;s price comes back to your wallet.
          </Alert>
        ) : null}
        {ended ? (
          <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
            <div className="flex min-w-0 items-center gap-3">
              <RentalLogo rental={rental} />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">Need a number again?</p>
                <p className="text-sm text-ink-muted">
                  Rent a new {rental.all_services ? "any-app" : rental.service_name} number. You see the price
                  before you pay.
                </p>
              </div>
            </div>
            <ButtonLink
              href={`/rentals?service=${encodeURIComponent(rental.service_slug)}`}
              icon={<RefreshIcon className="h-4 w-4" />}
              className="w-full shrink-0 sm:w-auto"
            >
              Rent again
            </ButtonLink>
          </Card>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <Card className="overflow-hidden">
            <NumberPanel rental={rental} />
            {rental.status === "ACTIVE" ? (
              <div className="flex flex-col gap-2 border-t border-line px-5 py-4 sm:flex-row sm:px-6">
                <Button
                  onClick={() => setExtending(true)}
                  icon={<PlusIcon className="h-4 w-4" />}
                  disabled={extensionPending}
                  className="w-full sm:w-auto"
                >
                  Extend
                </Button>
                {rental.can_cancel ? (
                  <Button variant="secondary" onClick={() => setConfirmCancel(true)} className="w-full sm:w-auto">
                    Cancel and refund
                  </Button>
                ) : null}
              </div>
            ) : null}
            {rental.status === "ACTIVE" ? (
              <p className="border-t border-line px-5 py-3 text-caption text-ink-muted sm:px-6">
                {rental.can_cancel
                  ? `You can cancel for a full refund${rental.refundable_until ? ` until ${formatDateTime(rental.refundable_until)}` : ""}, while our provider allows it.`
                  : rental.cancel_note || "This rental can no longer be cancelled for a refund."}
              </p>
            ) : null}
          </Card>

          <Inbox rental={rental} />
        </div>

        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader title="Rental details" />
            <DescriptionList
              className="px-4 pb-1 sm:px-5"
              items={[
                { label: "Reference", value: <span className="code">{rental.reference}</span> },
                { label: "Number for", value: rental.all_services ? "Any app" : rental.service_name },
                { label: "Amount paid", value: <span className="tabular">{cedis(rental.price)}</span>, emphasis: true },
                { label: "Rented", value: formatDateTime(rental.created_at) },
                ...(rental.ends_at
                  ? [{ label: rental.status === "ACTIVE" ? "Ends" : "Ended", value: formatDateTime(rental.ended_at ?? rental.ends_at) }]
                  : []),
                ...(Number(rental.refunded_amount) > 0
                  ? [{ label: "Refunded", value: <span className="tabular">{cedis(rental.refunded_amount)}</span> }]
                  : []),
              ]}
            />
          </Card>

          {rental.extensions.length ? (
            <Card>
              <CardHeader title="Extensions" />
              <ul className="divide-y divide-line border-t border-line">
                {rental.extensions.map((extension) => (
                  <li key={extension.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm sm:px-5">
                    <span>
                      <span className="font-medium text-ink">+{extension.days} {extension.days === 1 ? "day" : "days"}</span>
                      <span className="block text-caption text-ink-muted">{formatDateTime(extension.created_at)}</span>
                    </span>
                    <span className="text-right">
                      <span className="tabular block font-medium text-ink">{cedis(extension.price)}</span>
                      <span
                        className={cn(
                          "text-caption",
                          extension.status === "FAILED" ? "text-danger-700" : "text-ink-muted",
                        )}
                      >
                        {extension.status === "COMPLETED"
                          ? "Added"
                          : extension.status === "PENDING"
                            ? "Confirming"
                            : "Refunded"}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          <Card className="p-4 sm:p-5">
            <h3 className="text-sm font-semibold text-ink">How rentals work</h3>
            <ul className="mt-2 space-y-1.5 text-caption text-ink-muted">
              <li>Messages appear here within seconds while this page is open.</li>
              <li>The number never renews by itself. Extend it before it ends to keep it.</li>
              <li>Extensions can&apos;t be refunded once made.</li>
            </ul>
          </Card>
        </div>
      </div>

      {rental.status === "ACTIVE" ? (
        <ExtendDialog
          open={extending}
          onClose={() => setExtending(false)}
          rental={rental}
          onExtended={async () => {
            await mutate();
            await refreshMoney();
          }}
        />
      ) : null}

      <ConfirmDialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        onConfirm={cancel}
        loading={cancelling}
        title="Cancel this rental?"
        description={
          <>
            The number stops receiving messages and {cedis(rental.price)} goes back to your wallet. This
            cannot be undone.
          </>
        }
        confirmLabel="Cancel rental"
        cancelLabel="Keep it"
        tone="danger"
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function NumberPanel({ rental }: { rental: Rental }) {
  const toast = useToast();
  const [copied, setCopied] = React.useState(false);
  const left = useSecondsLeft(rental.seconds_remaining);
  const urgent = rental.status === "ACTIVE" && left > 0 && left < 86_400;

  async function copy() {
    const ok = await copyToClipboard(nationalNumber(rental.phone_number, "+1") || rental.phone_number);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Could not copy", "Select the number and copy it manually.");
    }
  }

  return (
    <div className="p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-label text-ink-muted">Your number</p>
        {rental.status === "ACTIVE" ? (
          <span
            role="timer"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-caption",
              urgent ? "bg-warn-50 text-warn-700" : "bg-sunken text-ink-soft",
            )}
          >
            <ClockIcon className="h-3.5 w-3.5" />
            <span className="tabular font-semibold">{timeLeft(left)}</span>
          </span>
        ) : null}
      </div>
      {rental.phone_number ? (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-3">
            <p
              className={cn(
                "tabular select-all text-display font-semibold",
                rental.status === "ACTIVE" ? "text-ink" : "text-ink-muted line-through decoration-1",
              )}
            >
              {groupInternational(rental.phone_number, "+1")}
            </p>
            {rental.status === "ACTIVE" ? (
              <Button
                size="sm"
                variant={copied ? "subtle" : "secondary"}
                onClick={copy}
                icon={copied ? <CheckCircleIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />}
              >
                {copied ? "Copied" : "Copy number"}
              </Button>
            ) : null}
          </div>
          {rental.status === "ACTIVE" ? (
            <p className="mt-2 text-caption text-ink-muted">
              A US number: choose United States (+1) in the app and paste it. Copy leaves out the +1.
              {rental.ends_at ? ` Receives messages until ${formatDateTime(rental.ends_at)}.` : ""}
            </p>
          ) : null}
        </>
      ) : rental.status === "PENDING" ? (
        <Skeleton className="mt-2 h-9 w-64" />
      ) : (
        <p className="mt-2 text-sm text-ink-muted">No number was assigned.</p>
      )}
    </div>
  );
}

function Inbox({ rental }: { rental: Rental }) {
  const live = rental.status === "ACTIVE";
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3.5 sm:px-5">
        <h2 className="flex items-center gap-2 text-heading text-ink">
          Inbox
          {rental.messages.length ? (
            <span className="tabular rounded-full bg-sunken px-2 py-0.5 text-caption font-medium text-ink-muted">
              {rental.messages.length}
            </span>
          ) : null}
        </h2>
        {live ? (
          <span className="inline-flex items-center gap-1.5 text-caption text-ink-muted">
            <span className="relative flex h-2 w-2" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-success-500" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-success-500" />
            </span>
            Listening
          </span>
        ) : null}
      </div>
      <div className="border-t border-line">
        {rental.messages_hidden ? (
          <p className="p-5 text-sm text-ink-muted">
            Our agreement with this provider does not permit showing message contents here.
          </p>
        ) : rental.messages.length === 0 ? (
          <div className="flex flex-col items-center px-6 py-10 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-sunken text-ink-faint">
              <InboxIcon className="h-6 w-6" />
            </span>
            <p className="mt-3 text-sm font-semibold text-ink">
              {live ? "Waiting for messages" : rental.status === "PENDING" ? "Your inbox is being set up" : "No messages"}
            </p>
            <p className="mt-1 max-w-sm text-caption text-ink-muted">
              {live
                ? "Use the number in the app - every SMS it receives shows up here within seconds. Keep this page open, or come back any time."
                : rental.status === "PENDING"
                  ? "Messages appear here once the number is ready."
                  : "This number received no messages."}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {rental.messages.map((message) => (
              <MessageRow key={message.id} message={message} />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function MessageRow({ message }: { message: RentalMessage }) {
  const toast = useToast();
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    const ok = await copyToClipboard(message.code);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Could not copy", "Select the code and copy it manually.");
    }
  }

  return (
    <li className="px-4 py-4 sm:px-5">
      <div className="flex items-center justify-between gap-3">
        <p className="truncate text-caption font-medium text-ink-soft">{message.sender || "Unknown sender"}</p>
        <time className="shrink-0 text-caption text-ink-faint" dateTime={message.received_at} title={formatDateTime(message.received_at)}>
          {relativeTime(message.received_at)}
        </time>
      </div>
      {message.body ? <p className="mt-1.5 whitespace-pre-wrap break-words text-sm text-ink">{message.body}</p> : null}
      {message.code ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <span className="code select-all rounded-lg bg-success-50 px-2.5 py-1 text-base font-semibold tracking-widest text-success-700">
            {message.code}
          </span>
          <Button
            size="sm"
            variant="ghost"
            onClick={copy}
            icon={copied ? <CheckCircleIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />}
          >
            {copied ? "Copied" : "Copy code"}
          </Button>
        </div>
      ) : null}
    </li>
  );
}

/** More days on the same number: priced live, paid from the wallet, not refundable. */
function ExtendDialog({
  open,
  onClose,
  rental,
  onExtended,
}: {
  open: boolean;
  onClose: () => void;
  rental: Rental;
  onExtended: () => Promise<void>;
}) {
  const toast = useToast();
  const { data: catalog } = useSWR<RentalCatalog>(open ? "/rentals/services/" : null);
  const [days, setDays] = React.useState<number | null>(null);
  const [price, setPrice] = React.useState<string | null>(null);
  const [quoteError, setQuoteError] = React.useState("");
  const [quoting, setQuoting] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const key = React.useRef(newIdempotencyKey());

  React.useEffect(() => {
    if (open) {
      key.current = newIdempotencyKey();
      setDays(null);
      setPrice(null);
      setQuoteError("");
    }
  }, [open]);

  React.useEffect(() => {
    if (!open || days === null) return;
    let cancelled = false;
    setPrice(null);
    setQuoteError("");
    setQuoting(true);
    api
      .get<{ price: string }>(`/rentals/${rental.reference}/extension-quote/`, { days })
      .then((result) => !cancelled && setPrice(result.price))
      .catch((caught) => !cancelled && setQuoteError(caught instanceof ApiError ? caught.message : "We could not price this right now."))
      .finally(() => !cancelled && setQuoting(false));
    return () => {
      cancelled = true;
    };
  }, [open, days, rental.reference]);

  async function extend() {
    if (days === null || !price) return;
    setBusy(true);
    try {
      const updated = await api.post<Rental>(
        `/rentals/${rental.reference}/extend/`,
        { days, expected_price: price },
        { idempotencyKey: key.current },
      );
      await onExtended();
      // Newest first: the extension this request made.
      const outcome = updated.extensions[0]?.status;
      if (outcome === "COMPLETED") {
        toast.success("Rental extended", "The new end date is on this page.");
      } else if (outcome === "FAILED") {
        toast.error("Couldn't extend", "Our provider couldn't add the time. Your money is back in your wallet.");
      } else {
        toast.info("Confirming your extension", "We'll update this page as soon as our provider confirms.");
      }
      onClose();
    } catch (caught) {
      toast.error("Could not extend", caught instanceof ApiError ? caught.message : "Please try again.");
      if (caught instanceof ApiError && caught.code === "PRICE_CHANGED") {
        setPrice(String(caught.details.price ?? ""));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="Extend this rental"
      description={`Keep ${groupInternational(rental.phone_number, "+1")} for longer.`}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Not now
          </Button>
          <Button onClick={extend} loading={busy} disabled={!price || quoting}>
            {price ? `Pay ${cedis(price)}` : "Choose a length"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Extend by">
          {(catalog?.durations ?? []).map((entry) => (
            <button
              key={entry.days}
              type="button"
              role="radio"
              aria-checked={days === entry.days}
              onClick={() => setDays(entry.days)}
              className={cn(
                "min-h-12 rounded-xl border px-3 text-sm font-semibold transition-colors",
                days === entry.days ? "border-brand-500 bg-brand-50 text-ink ring-2 ring-brand-500/30" : "border-line text-ink-soft hover:border-brand-300",
              )}
            >
              +{entry.label}
            </button>
          ))}
          {!catalog ? Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-12 rounded-xl" />) : null}
        </div>
        {quoting ? <Skeleton className="h-5 w-40" /> : null}
        {price ? (
          <p className="text-sm text-ink">
            Price: <span className="tabular font-semibold">{cedis(price)}</span>, paid from your wallet.
          </p>
        ) : null}
        {quoteError ? <Alert tone="warn">{quoteError}</Alert> : null}
        <Alert tone="warn" title="Extensions can't be refunded">
          Once added, the extra time is yours - it can&apos;t be cancelled for a refund. If our provider
          can&apos;t add it, you get the money back automatically.
        </Alert>
      </div>
    </Dialog>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy>
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-7 w-48" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <Card className="space-y-3 p-6">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-9 w-64" />
          </Card>
          <Card className="space-y-3 p-6">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-16 w-full" />
          </Card>
        </div>
        <div className="lg:col-span-2">
          <Card className="space-y-3 p-5">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
          </Card>
        </div>
      </div>
    </div>
  );
}
