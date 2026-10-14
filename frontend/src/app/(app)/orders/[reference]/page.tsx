"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import { CheckCircleIcon, ClockIcon, CopyIcon, RefreshIcon } from "@/components/icons";
import { BuyDialog } from "@/components/marketplace/buy-dialog";
import { CountryFlag } from "@/components/country-flag";
import { OrderTimeline } from "@/components/orders/order-timeline";
import { ReportProblem } from "@/components/orders/report-problem";
import { ServiceLogo } from "@/components/service-logo";
import { ConfirmDialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  DescriptionList,
  LoadError,
  Skeleton,
  StatusBadge,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import {
  cedis,
  copyToClipboard,
  countdown,
  formatDateTime,
  groupInternational,
  nationalNumber,
} from "@/lib/format";
import type { Order, OrderLiveStatus } from "@/lib/types";

/** Ended without delivering a code: the moment to offer the same number again. */
const RETRYABLE_STATUSES = new Set(["FAILED", "EXPIRED", "CANCELLED", "REFUNDED"]);

const ACTIVE_STATUSES = new Set([
  "CREATED",
  "PAYMENT_PENDING",
  "PROCESSING",
  "NUMBER_ASSIGNED",
  "WAITING_FOR_CODE",
]);

export default function OrderDetailPage() {
  const params = useParams<{ reference: string }>();
  const reference = params.reference;
  const toast = useToast();

  const { data: order, error, isLoading, mutate } = useSWR<Order>(`/orders/${reference}/`);

  const isActive = order ? ACTIVE_STATUSES.has(order.status) : false;

  // Poll our own API while the order is live. The upstream provider is polled
  // on the server's own schedule - never once per browser tick.
  const { data: live } = useSWR<OrderLiveStatus>(
    isActive ? `/orders/${reference}/status/` : null,
    { refreshInterval: (latest) => (latest?.poll_interval_seconds ?? 5) * 1000 },
  );

  // When the polled status moves on, refetch the full order so the timeline,
  // the code and the actions all update together.
  const lastStatus = React.useRef<string | undefined>(undefined);
  React.useEffect(() => {
    if (!live) return;
    if (lastStatus.current && lastStatus.current !== live.status) {
      mutate();
      globalMutate((key) => {
        const path = Array.isArray(key) ? String(key[0]) : String(key);
        return path.startsWith("/wallet") || path.startsWith("/transactions");
      });
      if (live.status === "CODE_RECEIVED") {
        toast.success("Verification code received", "It is on your order screen now.");
      }
    }
    lastStatus.current = live.status;
  }, [live, mutate, toast]);

  const [cancelling, setCancelling] = React.useState(false);
  const [confirmCancel, setConfirmCancel] = React.useState(false);
  const [completing, setCompleting] = React.useState(false);
  // "Buy again": the same service and country, straight from this page.
  const [buyingAgain, setBuyingAgain] = React.useState(false);

  async function onCancel() {
    setCancelling(true);
    try {
      await api.post(`/orders/${reference}/cancel/`, {});
      await mutate();
      await globalMutate((key) => {
        const path = Array.isArray(key) ? String(key[0]) : String(key);
        return path.startsWith("/wallet") || path.startsWith("/transactions");
      });
      toast.success("Order cancelled", "Your money has been returned to your wallet.");
      setConfirmCancel(false);
    } catch (caught) {
      toast.error(
        "Could not cancel",
        caught instanceof ApiError ? caught.message : "Please try again.",
      );
    } finally {
      setCancelling(false);
    }
  }

  async function onComplete() {
    setCompleting(true);
    try {
      await api.post(`/orders/${reference}/complete/`, {});
      await mutate();
      toast.success("Order completed", "Thanks - this one is closed.");
    } catch (caught) {
      toast.error(
        "Could not complete",
        caught instanceof ApiError ? caught.message : "Please try again.",
      );
    } finally {
      setCompleting(false);
    }
  }

  if (isLoading) return <OrderSkeleton />;

  // Only a 404 means the order does not exist. Anything else - a dropped
  // connection, a server error - must not tell someone who has just paid that
  // their order is gone.
  if (error && !order && !(error instanceof ApiError && error.status === 404)) {
    return (
      <div>
        <PageHeader title="Order" back={{ href: "/orders", label: "All orders" }} />
        <Card>
          <LoadError what={`order ${reference}`} onRetry={() => mutate()} />
        </Card>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div>
        <PageHeader title="Order not found" back={{ href: "/orders", label: "All orders" }} />
        <Card className="p-6">
          <p className="text-sm text-ink-muted">
            We could not find an order with the reference{" "}
            <span className="tabular font-medium text-ink">{reference}</span>. Check the reference,
            or open it from your order history.
          </p>
          <ButtonLink href="/orders" className="mt-4">Go to orders</ButtonLink>
        </Card>
      </div>
    );
  }

  const secondsLeft = live?.seconds_remaining ?? order.seconds_remaining;
  const phone = live?.phone_number || order.phone_number;
  const code = live?.verification_code || order.verification_code;
  const status = live?.status ?? order.status;
  const retryable = RETRYABLE_STATUSES.has(status) && !order.code_received_at;
  const delivered = status === "COMPLETED" || status === "CODE_RECEIVED";

  return (
    <div className="space-y-6">
      <PageHeader
        title={order.service_name}
        icon={
          <ServiceLogo
            name={order.service_name}
            src={order.service_icon}
            slug={order.service_slug}
            size="lg"
          />
        }
        back={{ href: "/orders", label: "All orders" }}
        description={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="code text-ink-soft">{order.reference}</span>
            <span aria-hidden>&middot;</span>
            <span className="inline-flex items-center gap-1.5">
              <CountryFlag code={order.country_code} size="sm" />
              {order.country_name}
            </span>
            <span aria-hidden>&middot;</span>
            <span className="tabular">{cedis(order.price)}</span>
          </span>
        }
        action={<StatusBadge status={status} />}
      />

      <div className="space-y-3 empty:hidden">
        {status === "PROCESSING" ? (
          <Alert tone="info" title="Reserving your number">
            We are placing the order with our provider. This usually takes a few seconds.
          </Alert>
        ) : null}

        {order.refund_status === "COMPLETED" ? (
          <Alert tone="brand" title="Refunded to your wallet">
            {cedis(order.refund?.amount ?? order.price)} has been returned.{" "}
            <Link href="/transactions" className="underline">
              See the transaction
            </Link>
            .
          </Alert>
        ) : null}

        {order.replacement_for ? (
          <Alert tone="info" title="Free replacement">
            This number replaces one from order{" "}
            <Link href={`/orders/${order.replacement_for}`} className="underline">
              {order.replacement_for}
            </Link>{" "}
            that could not be used. There was no charge.
          </Alert>
        ) : null}

        {order.reuse_of ? (
          <Alert tone="info" title="Same number again">
            This order reuses the number from order{" "}
            <Link href={`/orders/${order.reuse_of}`} className="underline">
              {order.reuse_of}
            </Link>{" "}
            for another code.
          </Alert>
        ) : null}

        {order.failure_reason ? (
          <Alert tone="warn" title="What happened">
            {order.failure_reason}
          </Alert>
        ) : null}

        {retryable ? (
          <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
            <div className="flex min-w-0 items-center gap-3">
              <ServiceLogo name={order.service_name} src={order.service_icon} slug={order.service_slug} />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">Try again with a new number</p>
                <p className="text-sm text-ink-muted">
                  {order.service_name}, {order.country_name}. You see the price before you pay.
                </p>
              </div>
            </div>
            <Button
              onClick={() => setBuyingAgain(true)}
              icon={<RefreshIcon className="h-4 w-4" />}
              className="w-full shrink-0 sm:w-auto"
            >
              Buy {order.service_name} again
            </Button>
          </Card>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <Card className="overflow-hidden">
            <NumberSection
              serviceName={order.service_name}
              phone={phone}
              dialCode={order.country_dial_code}
              countryName={order.country_name}
              status={status}
              secondsLeft={secondsLeft}
            />

            <CodeSection
              code={code}
              allowed={live?.code_display_allowed ?? order.code_display_allowed}
              status={status}
              message={order.verification_message}
            />

            {order.can_reuse && order.reusable_until && order.reuse_price ? (
              <ReuseSection
                reference={order.reference}
                until={order.reusable_until}
                price={order.reuse_price}
                onClosed={() => mutate()}
              />
            ) : order.can_reactivate && order.reactivate_price ? (
              <ReactivateSection reference={order.reference} price={order.reactivate_price} />
            ) : null}

            {order.can_complete || order.can_cancel ? (
              <div className="border-t border-line px-5 py-4 sm:px-6">
                <div className="flex flex-col gap-2 sm:flex-row">
                  {order.can_complete ? (
                    <Button
                      variant="secondary"
                      loading={completing}
                      onClick={onComplete}
                      icon={<CheckCircleIcon className="h-4 w-4" />}
                      className="w-full sm:w-auto"
                    >
                      Mark as complete
                    </Button>
                  ) : null}
                  {order.can_cancel ? (
                    <Button
                      variant="secondary"
                      onClick={() => setConfirmCancel(true)}
                      disabled={cancelling}
                      className="w-full sm:w-auto"
                    >
                      Cancel and refund
                    </Button>
                  ) : null}
                </div>
                <p className="mt-2.5 text-caption text-ink-muted">
                  {order.can_complete
                    ? "Marking complete closes the order. The number stops being useful once it expires either way."
                    : "You can cancel until a code arrives, and get the full amount back. After that, the service has been delivered."}
                </p>
              </div>
            ) : null}
          </Card>

          <ReportProblem order={order} onReported={() => mutate()} />

          {delivered ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-line px-4 py-3">
              <p className="text-sm text-ink-muted">Need another {order.service_name} number?</p>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setBuyingAgain(true)}
                icon={<RefreshIcon className="h-4 w-4" />}
              >
                Buy another
              </Button>
            </div>
          ) : null}
        </div>

        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader title="Progress" />
            <div className="p-4 pt-3 sm:p-5 sm:pt-3">
              <OrderTimeline status={status} events={order.events} />
            </div>
          </Card>

          <Card>
            <CardHeader title="Order details" />
            <DescriptionList
              className="px-4 pb-1 sm:px-5"
              items={[
                { label: "Reference", value: <span className="code">{order.reference}</span> },
                {
                  label: "Amount paid",
                  value: <span className="tabular">{cedis(order.price)}</span>,
                  emphasis: true,
                },
                { label: "Placed", value: formatDateTime(order.created_at) },
                ...(order.completed_at
                  ? [{ label: "Closed", value: formatDateTime(order.completed_at) }]
                  : []),
                ...(order.refund
                  ? [
                      {
                        label: "Refund reference",
                        value: <span className="code">{order.refund.reference}</span>,
                      },
                    ]
                  : []),
              ]}
            />
          </Card>
        </div>
      </div>

      <BuyDialog
        open={buyingAgain}
        onClose={() => setBuyingAgain(false)}
        serviceSlug={order.service_slug}
        initialCountry={order.country_code}
      />

      <ConfirmDialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        onConfirm={onCancel}
        loading={cancelling}
        title="Cancel this order?"
        description={
          <>
            The number is released and {cedis(order.price)} goes back to your wallet. This cannot
            be undone - you would need to buy a new number.
          </>
        }
        confirmLabel="Cancel order"
        cancelLabel="Keep waiting"
        tone="danger"
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */

/**
 * The number, big enough to read off one screen and type on another, with the
 * time it has left. The copy button gives the national digits.
 */
function NumberSection({
  serviceName,
  phone,
  dialCode,
  countryName,
  status,
  secondsLeft,
}: {
  serviceName: string;
  phone: string;
  dialCode: string;
  countryName: string;
  status: string;
  secondsLeft: number;
}) {
  const toast = useToast();
  const [copied, setCopied] = React.useState(false);

  // Tick the countdown locally between polls so it moves every second rather
  // than jumping in five-second steps.
  const [remaining, setRemaining] = React.useState(secondsLeft);
  React.useEffect(() => setRemaining(secondsLeft), [secondsLeft]);
  React.useEffect(() => {
    if (remaining <= 0) return;
    const timer = window.setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [remaining]);

  async function copy() {
    if (!phone) return;
    // The national digits, as providers copy them: sign-up forms take the
    // country from their own picker and reject a pasted "+1".
    const ok = await copyToClipboard(nationalNumber(phone, dialCode) || phone);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Could not copy", "Select the number and copy it manually.");
    }
  }

  const running = remaining > 0 && ["NUMBER_ASSIGNED", "WAITING_FOR_CODE"].includes(status);
  const urgent = running && remaining < 120;
  const dial = dialCode.startsWith("+") ? dialCode : `+${dialCode}`;

  return (
    <div className="p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-label text-ink-muted">Your {serviceName} number</p>
        {running ? (
          <span
            role="timer"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-caption",
              urgent ? "bg-warn-50 text-warn-700" : "bg-sunken text-ink-soft",
            )}
          >
            <ClockIcon className="h-3.5 w-3.5" />
            <span>
              <span className="tabular font-semibold">{countdown(remaining)}</span>
              {urgent ? " - expires soon" : " left"}
            </span>
          </span>
        ) : null}
      </div>

      {phone ? (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-3">
            <p className="tabular select-all text-display font-semibold text-ink">
              {groupInternational(phone, dialCode)}
            </p>
            <Button
              size="sm"
              variant={copied ? "subtle" : "secondary"}
              onClick={copy}
              icon={
                copied ? <CheckCircleIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />
              }
            >
              {copied ? "Copied" : "Copy number"}
            </Button>
          </div>
          <p className="mt-2 text-caption text-ink-muted">
            On {serviceName}, choose {countryName} ({dial}) and paste the number. Copy leaves out
            the {dial}.
          </p>
        </>
      ) : (
        <Skeleton className="mt-2 h-9 w-64" />
      )}
    </div>
  );
}

/** Where the code lands - the one thing the customer is here for. */
function CodeSection({
  code,
  allowed,
  status,
  message,
}: {
  code: string;
  allowed: boolean;
  status: string;
  message: string;
}) {
  const toast = useToast();
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    const ok = await copyToClipboard(code);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Could not copy", "Select the code and copy it manually.");
    }
  }

  if (!allowed) {
    return (
      <div className="border-t border-line p-5 sm:p-6">
        <p className="text-label text-ink-muted">Verification code</p>
        <p className="mt-2 text-sm text-ink-muted">
          Our agreement with this provider does not permit relaying the message contents. The
          order status above shows when a verification message has been delivered.
        </p>
      </div>
    );
  }

  if (code) {
    return (
      <div className="border-t border-success-200 bg-success-50 p-5 sm:p-6" aria-live="polite">
        <p className="text-label text-success-700">Verification code</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-3">
          <p className="code select-all text-figure font-semibold tracking-widest text-success-700">
            {code}
          </p>
          <Button
            size="sm"
            variant="secondary"
            onClick={copy}
            icon={
              copied ? <CheckCircleIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />
            }
          >
            {copied ? "Copied" : "Copy code"}
          </Button>
        </div>
        {message ? (
          <p className="mt-3 rounded-lg border border-success-200 bg-surface px-3 py-2 text-caption text-ink-soft">
            {message}
          </p>
        ) : null}
      </div>
    );
  }

  const waiting = ["NUMBER_ASSIGNED", "WAITING_FOR_CODE", "PROCESSING"].includes(status);

  return (
    <div className="border-t border-line p-5 sm:p-6" aria-live="polite">
      <p className="text-label text-ink-muted">Verification code</p>
      {waiting ? (
        <div className="mt-3 flex items-start gap-3">
          <span className="relative mt-1.5 flex h-2.5 w-2.5 shrink-0" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-brand-400" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-500" />
          </span>
          <p className="text-sm text-ink-soft">
            Waiting for the SMS. The code appears here the moment it arrives - keep this page open,
            or come back to it from Orders.
          </p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-ink-muted">No verification code was received.</p>
      )}
    </div>
  );
}

function ReuseSection({
  reference,
  until,
  price,
  onClosed,
}: {
  reference: string;
  until: string;
  price: string;
  onClosed: () => void;
}) {
  const toast = useToast();
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);
  // One key per card, so a double tap or a retry buys once.
  const [key] = React.useState(() =>
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${reference}-${Date.now()}`,
  );
  const secondsLeft = () => Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 1000));
  const [left, setLeft] = React.useState(secondsLeft);

  React.useEffect(() => {
    const timer = window.setInterval(() => {
      const value = secondsLeft();
      setLeft(value);
      if (value <= 0) {
        window.clearInterval(timer);
        onClosed();
      }
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [until]);

  if (left <= 0) return null;

  async function reuse() {
    setBusy(true);
    try {
      const next = await api.post<Order>(`/orders/${reference}/reuse/`, { idempotency_key: key });
      await globalMutate("/wallet/");
      router.push(`/orders/${next.reference}`);
    } catch (caught) {
      toast.error(
        "Could not use the number again",
        caught instanceof ApiError ? caught.message : "Please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 border-t border-line px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">Need another code on this number?</p>
        <p className="mt-0.5 text-caption text-ink-muted">
          Available for <span className="tabular">{countdown(left)}</span>. It is a new order,
          refunded automatically if no code comes.
        </p>
      </div>
      <Button variant="secondary" loading={busy} onClick={reuse} className="w-full shrink-0 sm:w-auto">
        Use again for {cedis(price)}
      </Button>
    </div>
  );
}

/** After the reuse window: the provider can still reactivate this number
 *  for another code, at half the order's price. A new order, refunded
 *  automatically if no code comes - as short as TextVerified's own button. */
function ReactivateSection({ reference, price }: { reference: string; price: string }) {
  const toast = useToast();
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);
  // One key per card, so a double tap or a retry buys once.
  const [key] = React.useState(() =>
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${reference}-reactivate-${Date.now()}`,
  );

  async function reactivate() {
    setBusy(true);
    try {
      const next = await api.post<Order>(`/orders/${reference}/reactivate/`, {
        idempotency_key: key,
      });
      await globalMutate("/wallet/");
      router.push(`/orders/${next.reference}`);
    } catch (caught) {
      toast.error(
        "Could not reactivate the number",
        caught instanceof ApiError ? caught.message : "Please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="border-t border-line px-5 py-4 sm:px-6">
      <Button loading={busy} onClick={reactivate} fullWidth>
        Reactivate ({cedis(price)})
      </Button>
    </div>
  );
}

function OrderSkeleton() {
  return (
    <div className="space-y-6" aria-busy>
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-7 w-48" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <Card className="space-y-3 p-6">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-9 w-64" />
            <Skeleton className="h-3 w-full max-w-sm" />
            <div className="border-t border-line pt-5">
              <Skeleton className="h-3 w-28" />
              <Skeleton className="mt-3 h-10 w-40" />
            </div>
          </Card>
        </div>
        <div className="lg:col-span-2">
          <Card className="space-y-4 p-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="flex gap-3">
                <Skeleton className="h-6 w-6 rounded-full" />
                <Skeleton className="h-4 flex-1" />
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
}
