"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import { CheckCircleIcon, ClockIcon, CopyIcon } from "@/components/icons";
import { OrderTimeline } from "@/components/orders/order-timeline";
import { ReportProblem } from "@/components/orders/report-problem";
import { ConfirmDialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  Card,
  CardHeader,
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
} from "@/lib/format";
import type { Order, OrderLiveStatus } from "@/lib/types";

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
          <Link href="/orders" className="mt-4 inline-block">
            <Button>Go to orders</Button>
          </Link>
        </Card>
      </div>
    );
  }

  const secondsLeft = live?.seconds_remaining ?? order.seconds_remaining;
  const phone = live?.phone_number || order.phone_number;
  const code = live?.verification_code || order.verification_code;
  const status = live?.status ?? order.status;

  return (
    <div className="space-y-4">
      <PageHeader
        title={order.service_name}
        back={{ href: "/orders", label: "All orders" }}
        description={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="tabular font-medium text-ink-soft">{order.reference}</span>
            <span aria-hidden>&middot;</span>
            <span>
              <span aria-hidden>{order.country_flag}</span> {order.country_name}
            </span>
            <span aria-hidden>&middot;</span>
            <span className="tabular">{cedis(order.price)}</span>
          </span>
        }
        action={<StatusBadge status={status} />}
      />

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

      {order.failure_reason ? (
        <Alert tone="warn" title="What happened">
          {order.failure_reason}
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <PhoneCard
            phone={phone}
            dialCode={order.country_dial_code}
            status={status}
            secondsLeft={secondsLeft}
          />

          <CodeCard
            code={code}
            allowed={live?.code_display_allowed ?? order.code_display_allowed}
            status={status}
            message={order.verification_message}
          />

          {order.can_complete || order.can_cancel ? (
            <Card className="p-4 sm:p-5">
              <div className="flex flex-col gap-2 sm:flex-row">
                {order.can_complete ? (
                  <Button
                    fullWidth
                    loading={completing}
                    onClick={onComplete}
                    icon={<CheckCircleIcon className="h-5 w-5" />}
                  >
                    Mark as complete
                  </Button>
                ) : null}
                {order.can_cancel ? (
                  <Button
                    variant="secondary"
                    fullWidth
                    onClick={() => setConfirmCancel(true)}
                    disabled={cancelling}
                  >
                    Cancel and refund
                  </Button>
                ) : null}
              </div>
              <p className="mt-3 text-xs text-ink-muted">
                {order.can_complete
                  ? "Marking complete closes the order. The number stops being useful once it expires either way."
                  : "You can cancel until a verification code arrives. After that the service has been delivered."}
              </p>
            </Card>
          ) : null}

          <ReportProblem order={order} onReported={() => mutate()} />
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
            <dl className="divide-y divide-line px-4 sm:px-5">
              <Detail label="Reference" value={order.reference} mono />
              <Detail label="Service" value={order.service_name} />
              <Detail label="Country" value={`${order.country_flag} ${order.country_name}`} />
              <Detail label="Amount paid" value={cedis(order.price)} mono />
              <Detail label="Placed" value={formatDateTime(order.created_at)} />
              {order.completed_at ? (
                <Detail label="Closed" value={formatDateTime(order.completed_at)} />
              ) : null}
              {order.refund ? (
                <Detail label="Refund reference" value={order.refund.reference} mono />
              ) : null}
            </dl>
          </Card>
        </div>
      </div>

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

function PhoneCard({
  phone,
  dialCode,
  status,
  secondsLeft,
}: {
  phone: string;
  dialCode: string;
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
    const ok = await copyToClipboard(phone);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Could not copy", "Select the number and copy it manually.");
    }
  }

  const running = remaining > 0 && ["NUMBER_ASSIGNED", "WAITING_FOR_CODE"].includes(status);
  const urgent = running && remaining < 120;

  return (
    <Card className="p-4 sm:p-5">
      <p className="text-xs uppercase tracking-wide text-ink-faint">Phone number</p>

      {phone ? (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <p className="tabular select-all text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
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
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <p className="mt-2 text-sm text-ink-muted">
            Enter this number on the service you are verifying with.
          </p>
        </>
      ) : (
        <div className="mt-2 flex items-center gap-2 text-ink-muted">
          <Skeleton className="h-8 w-52" />
        </div>
      )}

      {running ? (
        <div
          className={cn(
            "mt-4 flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-sm",
            urgent ? "bg-warn-50 text-warn-700" : "bg-line/50 text-ink-soft",
          )}
        >
          <ClockIcon className="h-4 w-4" />
          <span>
            {urgent ? "Expires soon:" : "Number expires in"}{" "}
            <span className="tabular font-semibold">{countdown(remaining)}</span>
          </span>
        </div>
      ) : null}
    </Card>
  );
}

function CodeCard({
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
      <Card className="p-4 sm:p-5">
        <p className="text-xs uppercase tracking-wide text-ink-faint">Verification code</p>
        <p className="mt-2 text-sm text-ink-muted">
          Our agreement with this provider does not permit relaying the message contents. The
          order status above shows when a verification message has been delivered.
        </p>
      </Card>
    );
  }

  if (code) {
    return (
      <Card className="border-success-200 bg-success-50 p-4 sm:p-5">
        <p className="text-xs uppercase tracking-wide text-success-700">Verification code</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <p className="tabular select-all text-4xl font-semibold tracking-[0.2em] text-success-700">
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
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        {message ? (
          <p className="mt-3 rounded-lg bg-white/70 px-3 py-2 text-xs text-ink-soft">{message}</p>
        ) : null}
      </Card>
    );
  }

  const waiting = ["NUMBER_ASSIGNED", "WAITING_FOR_CODE", "PROCESSING"].includes(status);

  return (
    <Card className="p-4 sm:p-5">
      <p className="text-xs uppercase tracking-wide text-ink-faint">Verification code</p>
      {waiting ? (
        <div className="mt-3 flex items-center gap-3">
          <span className="relative flex h-2.5 w-2.5" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-brand-400" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-500" />
          </span>
          <p className="text-sm text-ink-soft">
            Waiting for the verification code. It appears here the moment it arrives - you can
            leave this page open.
          </p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-ink-muted">No verification code was received.</p>
      )}
    </Card>
  );
}

function Detail({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className={cn("text-sm text-ink", mono && "tabular font-medium")}>{value}</dd>
    </div>
  );
}

function OrderSkeleton() {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-7 w-48" />
      </div>
      <div className="grid gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <Card className="space-y-3 p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-9 w-56" />
            <Skeleton className="h-10 w-full rounded-xl" />
          </Card>
          <Card className="space-y-3 p-5">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-12 w-40" />
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
