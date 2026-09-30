"use client";

import Link from "next/link";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import {
  AlertIcon,
  BellIcon,
  CheckCircleIcon,
  ChevronRightIcon,
  ClockIcon,
  FlagIcon,
  GiftIcon,
  LockIcon,
  MailIcon,
  MessageIcon,
  PhoneIcon,
  RefreshIcon,
  ShieldIcon,
  UserIcon,
  WalletIcon,
} from "@/components/icons";
import { Button, Card, EmptyState, LoadError, Skeleton, cn } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { dayGroup, formatDateTime, formatTime, moneyText } from "@/lib/format";
import type { Notification, Paginated } from "@/lib/types";

type Kind = {
  icon: React.ComponentType<{ className?: string }>;
  tone: "neutral" | "success" | "warn" | "danger" | "gold";
};

/** What each event looks like. Colour follows meaning: money in and codes are
 *  green, failures red, security amber, rewards gold, the rest grey. */
const KINDS: Record<string, Kind> = {
  ACCOUNT_CREATED: { icon: UserIcon, tone: "neutral" },
  PAYMENT_SUCCESSFUL: { icon: WalletIcon, tone: "success" },
  PAYMENT_FAILED: { icon: AlertIcon, tone: "danger" },
  PURCHASE_SUCCESSFUL: { icon: PhoneIcon, tone: "neutral" },
  NUMBER_ASSIGNED: { icon: PhoneIcon, tone: "neutral" },
  CODE_RECEIVED: { icon: MessageIcon, tone: "success" },
  ORDER_COMPLETED: { icon: CheckCircleIcon, tone: "neutral" },
  ORDER_EXPIRED: { icon: ClockIcon, tone: "neutral" },
  REFUND_ISSUED: { icon: RefreshIcon, tone: "success" },
  NUMBER_ISSUE_UPDATED: { icon: FlagIcon, tone: "neutral" },
  SECURITY_ALERT: { icon: ShieldIcon, tone: "warn" },
  ACCOUNT_SUSPENDED: { icon: LockIcon, tone: "danger" },
  ADMIN_MESSAGE: { icon: MailIcon, tone: "neutral" },
  REFERRAL_BONUS: { icon: GiftIcon, tone: "gold" },
};

const TONE_CLASSES: Record<Kind["tone"], string> = {
  neutral: "bg-sunken text-ink-soft",
  success: "bg-success-50 text-success-700",
  warn: "bg-warn-50 text-warn-700",
  danger: "bg-danger-50 text-danger-700",
  gold: "bg-gold-100 text-gold-700",
};

/** Where a notification leads, from the references the backend attached. */
function destination(notification: Notification): string | null {
  const meta = notification.metadata ?? {};
  if (typeof meta.order_reference === "string") return `/orders/${meta.order_reference}`;
  if (typeof meta.payment_reference === "string") return "/transactions";
  if (notification.event === "REFERRAL_BONUS") return "/refer";
  if (notification.event === "SECURITY_ALERT") return "/account";
  return null;
}

const GROUPS = ["Today", "Yesterday", "Earlier"] as const;

export default function NotificationsPage() {
  const [page, setPage] = React.useState(1);
  const { data, isLoading, error, mutate } = useSWR<Paginated<Notification>>([
    "/notifications/",
    { page, page_size: 25 },
  ]);

  const [marking, setMarking] = React.useState(false);
  const notifications = React.useMemo(() => data?.results ?? [], [data]);
  const unread = notifications.filter((item) => !item.is_read).length;

  const grouped = React.useMemo(() => {
    const out = new Map<(typeof GROUPS)[number], Notification[]>();
    for (const item of notifications) {
      const key = dayGroup(item.created_at);
      out.set(key, [...(out.get(key) ?? []), item]);
    }
    return GROUPS.filter((key) => out.has(key)).map((key) => ({ key, items: out.get(key)! }));
  }, [notifications]);

  async function markAllRead() {
    setMarking(true);
    try {
      await api.post("/notifications/read-all/", {});
      await mutate();
      await globalMutate("/notifications/unread/");
    } finally {
      setMarking(false);
    }
  }

  async function markRead(notification: Notification) {
    if (notification.is_read) return;
    await api.post(`/notifications/${notification.id}/read/`, {});
    await mutate();
    await globalMutate("/notifications/unread/");
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Notifications"
        description={
          unread > 0
            ? `${unread} unread. Payments, orders and security alerts.`
            : "Payments, orders and security alerts."
        }
        back={{ href: "/account", label: "Settings" }}
        action={
          unread > 0 ? (
            <Button size="sm" variant="secondary" loading={marking} onClick={markAllRead}>
              Mark all as read
            </Button>
          ) : undefined
        }
      />

      {isLoading ? (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-line" aria-busy>
            {Array.from({ length: 6 }).map((_, index) => (
              <li key={index} className="flex gap-3 px-4 py-3.5 sm:px-5">
                <Skeleton className="h-9 w-9 rounded-lg" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-44" />
                  <Skeleton className="h-3 w-full max-w-sm" />
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : error && !data ? (
        <Card>
          <LoadError what="your notifications" onRetry={() => mutate()} />
        </Card>
      ) : notifications.length === 0 ? (
        <Card>
          <EmptyState
            icon={<BellIcon />}
            title="Nothing here yet"
            description="We will let you know when a payment lands, a number is assigned, or a code arrives."
          />
        </Card>
      ) : (
        <div className="space-y-6">
          {grouped.map((group) => (
            <section key={group.key} aria-labelledby={`group-${group.key}`}>
              <h2 id={`group-${group.key}`} className="mb-2 text-label text-ink-muted">
                {group.key}
              </h2>
              <Card className="overflow-hidden">
                <ul className="divide-y divide-line">
                  {group.items.map((notification) => (
                    <NotificationRow
                      key={notification.id}
                      notification={notification}
                      showDate={group.key === "Earlier"}
                      onOpen={() => markRead(notification)}
                    />
                  ))}
                </ul>
              </Card>
            </section>
          ))}
        </div>
      )}

      {data?.pagination && data.pagination.pages > 1 ? (
        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-sm text-ink-muted">
            Page {data.pagination.page} of {data.pagination.pages}
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={!data.pagination.has_previous}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!data.pagination.has_next}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NotificationRow({
  notification,
  showDate,
  onOpen,
}: {
  notification: Notification;
  showDate: boolean;
  onOpen: () => void;
}) {
  const kind = KINDS[notification.event] ?? { icon: BellIcon, tone: "neutral" as const };
  const Icon = kind.icon;
  const href = destination(notification);
  const unread = !notification.is_read;

  const body = (
    <>
      <span
        aria-hidden
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          TONE_CLASSES[kind.tone],
        )}
      >
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-3">
          <span className={cn("text-sm", unread ? "font-semibold text-ink" : "text-ink-soft")}>
            {unread ? <span className="sr-only">Unread: </span> : null}
            {notification.title}
          </span>
          <span className="tabular shrink-0 text-caption text-ink-faint">
            {showDate ? formatDateTime(notification.created_at) : formatTime(notification.created_at)}
          </span>
        </span>
        {notification.body ? (
          <span className="mt-0.5 block text-sm text-ink-muted">{moneyText(notification.body)}</span>
        ) : null}
      </span>
      <span className="flex w-4 shrink-0 flex-col items-center gap-2 self-stretch pt-1.5">
        {unread ? <span className="h-2 w-2 rounded-full bg-brand-500" aria-hidden /> : null}
        {href ? <ChevronRightIcon className="mt-auto h-4 w-4 text-ink-faint" /> : null}
      </span>
    </>
  );

  const className = "flex w-full gap-3 px-4 py-3.5 text-left transition-colors hover:bg-sunken/60 sm:px-5";

  return (
    <li>
      {href ? (
        <Link href={href} onClick={onOpen} className={className}>
          {body}
        </Link>
      ) : (
        <button type="button" onClick={onOpen} className={className}>
          {body}
        </button>
      )}
    </li>
  );
}
