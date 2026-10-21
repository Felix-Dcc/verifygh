"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import { AdminToolbar, ListCard, SearchBox, TableSkeleton } from "@/components/admin/ui";
import { PageHeader } from "@/components/app-shell";
import { ArrowLeftIcon, InboxIcon } from "@/components/icons";
import { ChatMessages, type ChatMessage } from "@/components/support-chat";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  LoadError,
  SegmentedControl,
  Textarea,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { Paginated } from "@/lib/types";

type Thread = {
  id: string;
  status: "BOT" | "WAITING" | "ANSWERED" | "CLOSED";
  last_message_at: string;
  email: string;
  full_name: string;
  preview: string;
};

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "WAITING", label: "Waiting" },
  { value: "ANSWERED", label: "Answered" },
  { value: "BOT", label: "With bot" },
  { value: "CLOSED", label: "Closed" },
];

const STATUS_BADGE: Record<Thread["status"], { label: string; tone: "warn" | "success" | "neutral" }> = {
  WAITING: { label: "Waiting", tone: "warn" },
  ANSWERED: { label: "Answered", tone: "success" },
  BOT: { label: "With bot", tone: "neutral" },
  CLOSED: { label: "Closed", tone: "neutral" },
};

export default function AdminChatsPage() {
  const [status, setStatus] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<string | null>(null);

  // Opened from a staff alert: start on that thread.
  React.useEffect(() => {
    const thread = new URLSearchParams(window.location.search).get("thread");
    if (thread) setSelected(thread.slice(0, 64));
  }, []);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading, isValidating, error, mutate } = useSWR<Paginated<Thread>>(
    ["/admin/chats/", { status, search: debounced, page, page_size: 25 }],
    { keepPreviousData: true, refreshInterval: 15_000 },
  );
  const threads = data?.results ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Chats"
        description="Customer support chats. The bot answers first; chats waiting for a person are listed first."
      />

      <div className={cn(selected && "max-lg:hidden")}>
        <AdminToolbar>
          <SegmentedControl
            options={STATUS_FILTERS}
            value={status}
            onChange={(value) => {
              setStatus(value);
              setPage(1);
            }}
            className="lg:flex-1"
          />
          <SearchBox label="Search chats" placeholder="Name or email" value={search} onChange={setSearch} />
        </AdminToolbar>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className={cn("space-y-4", selected && "max-lg:hidden")}>
          <ListCard
            title="Chats"
            count={data?.pagination?.count}
            noun="chats"
            refreshing={isValidating}
            onRefresh={() => mutate()}
          >
            {isLoading ? (
              <TableSkeleton rows={5} />
            ) : error && !data ? (
              <LoadError what="the chats" onRetry={() => mutate()} />
            ) : threads.length === 0 ? (
              <EmptyState icon={<InboxIcon />} title="No chats" description="Customer chats will show here." />
            ) : (
              <ul className="divide-y divide-line">
                {threads.map((thread) => (
                  <li key={thread.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(thread.id)}
                      aria-current={selected === thread.id || undefined}
                      className={cn(
                        "flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-sunken sm:px-5",
                        selected === thread.id && "bg-sunken",
                      )}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium text-ink">
                          {thread.full_name || thread.email}
                        </span>
                        <Badge tone={STATUS_BADGE[thread.status].tone}>{STATUS_BADGE[thread.status].label}</Badge>
                      </span>
                      <span className="truncate text-caption text-ink-muted">{thread.preview}</span>
                      <span className="text-2xs text-ink-faint">{relativeTime(thread.last_message_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </ListCard>

          {data && data.pagination.pages > 1 ? (
            <Pagination
              page={data.pagination.page}
              pages={data.pagination.pages}
              count={data.pagination.count}
              hasNext={data.pagination.has_next}
              hasPrevious={data.pagination.has_previous}
              onChange={setPage}
              noun="chats"
            />
          ) : null}
        </div>

        {selected ? (
          <ThreadView id={selected} onBack={() => setSelected(null)} onChange={() => mutate()} />
        ) : (
          <Card className="hidden items-center justify-center p-10 text-sm text-ink-muted lg:flex">
            Choose a chat to read it.
          </Card>
        )}
      </div>
    </div>
  );
}

function ThreadView({ id, onBack, onChange }: { id: string; onBack: () => void; onChange: () => void }) {
  const toast = useToast();
  const { data, error, mutate } = useSWR<Thread & { messages: ChatMessage[] }>(`/admin/chats/${id}/`, {
    refreshInterval: 5000,
  });
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  async function act(path: "reply" | "close", body?: { body: string }) {
    setBusy(true);
    try {
      await mutate(await api.post<Thread & { messages: ChatMessage[] }>(`/admin/chats/${id}/${path}/`, body), {
        revalidate: false,
      });
      if (path === "reply") setDraft("");
      onChange();
    } catch (err) {
      toast.error(path === "reply" ? "Reply not sent" : "Could not close", err instanceof ApiError ? err.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex h-[calc(100dvh-12rem)] min-h-[28rem] flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <Button variant="ghost" size="sm" onClick={onBack} aria-label="Back to chats" className="lg:hidden">
          <ArrowLeftIcon className="h-5 w-5" />
        </Button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">{data?.full_name || data?.email || "Chat"}</p>
          {data?.full_name ? <p className="truncate text-caption text-ink-muted">{data.email}</p> : null}
        </div>
        {data && data.status !== "CLOSED" ? (
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => act("close")}>
            Close chat
          </Button>
        ) : null}
      </div>

      {error && !data ? (
        <LoadError what="this chat" onRetry={() => mutate()} />
      ) : data ? (
        <ChatMessages messages={data.messages} mine="STAFF" empty="No messages yet." />
      ) : (
        <TableSkeleton rows={4} />
      )}

      <form
        className="flex items-end gap-2 border-t border-line p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim()) act("reply", { body: draft.trim() });
        }}
      >
        <Textarea
          rows={2}
          value={draft}
          maxLength={2000}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Reply to the customer. Never ask for passwords, PINs or codes."
          aria-label="Reply"
          className="max-h-40 resize-none py-2.5"
        />
        <Button type="submit" loading={busy} disabled={!draft.trim()}>
          Send
        </Button>
      </form>
    </Card>
  );
}
