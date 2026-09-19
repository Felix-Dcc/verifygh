"use client";

import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import { BellIcon } from "@/components/icons";
import { Button, Card, EmptyState, Skeleton, cn } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { Notification, Paginated } from "@/lib/types";

export default function NotificationsPage() {
  const [page, setPage] = React.useState(1);
  const { data, isLoading, mutate } = useSWR<Paginated<Notification>>([
    "/notifications/",
    { page, page_size: 25 },
  ]);

  const [marking, setMarking] = React.useState(false);
  const notifications = data?.results ?? [];
  const unread = notifications.filter((item) => !item.is_read).length;

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
    <div className="mx-auto max-w-2xl space-y-4">
      <PageHeader
        title="Notifications"
        description="Payments, orders and security alerts."
        back={{ href: "/account", label: "Account" }}
        action={
          unread > 0 ? (
            <Button size="sm" variant="secondary" loading={marking} onClick={markAllRead}>
              Mark all read
            </Button>
          ) : undefined
        }
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <ul className="divide-y divide-line">
            {Array.from({ length: 6 }).map((_, index) => (
              <li key={index} className="space-y-2 px-4 py-4 sm:px-5">
                <Skeleton className="h-4 w-44" />
                <Skeleton className="h-3 w-full max-w-sm" />
              </li>
            ))}
          </ul>
        ) : notifications.length === 0 ? (
          <EmptyState
            icon={<BellIcon />}
            title="Nothing here yet"
            description="We will let you know when a payment lands, a number is assigned, or a code arrives."
          />
        ) : (
          <ul className="divide-y divide-line">
            {notifications.map((notification) => (
              <li key={notification.id}>
                <button
                  type="button"
                  onClick={() => markRead(notification)}
                  className={cn(
                    "flex w-full gap-3 px-4 py-4 text-left transition-colors hover:bg-canvas sm:px-5",
                    !notification.is_read && "bg-brand-50/50",
                  )}
                >
                  <span
                    className={cn(
                      "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                      notification.is_read ? "bg-transparent" : "bg-brand-500",
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-start justify-between gap-3">
                      <span
                        className={cn(
                          "text-sm",
                          notification.is_read ? "text-ink-soft" : "font-semibold text-ink",
                        )}
                      >
                        {notification.title}
                      </span>
                      <span className="shrink-0 text-xs text-ink-faint">
                        {relativeTime(notification.created_at)}
                      </span>
                    </span>
                    {notification.body ? (
                      <span className="mt-0.5 block text-sm text-ink-muted">
                        {notification.body}
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {data?.pagination && data.pagination.pages > 1 ? (
        <div className="flex items-center justify-between gap-3">
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
