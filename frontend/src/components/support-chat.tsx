"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { CloseIcon, MessageIcon } from "@/components/icons";
import { useToast } from "@/components/ui/toast";
import { Button, Spinner, Textarea, cn } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";

/**
 * The support chat: a bubble on every signed-in page. A rule-based bot on the
 * server answers first; "Talk to a person" hands the thread to the admins,
 * who reply from Admin > Chats. Polls only while the panel is open.
 */

export type ChatMessage = {
  id: string;
  sender: "CUSTOMER" | "BOT" | "STAFF";
  body: string;
  created_at: string;
};

type Chat = {
  status: "BOT" | "WAITING" | "ANSWERED" | "CLOSED";
  messages: ChatMessage[];
  topics: { key: string; label: string }[];
};

const MAX_LENGTH = 1000;

export function SupportChat() {
  const [open, setOpen] = React.useState(false);
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  // The "Support replied" notification links here with ?chat=open.
  React.useEffect(() => {
    if (params.get("chat") !== "open") return;
    setOpen(true);
    router.replace(pathname, { scroll: false });
  }, [params, pathname, router]);

  return (
    <>
      {open ? <ChatPanel onClose={() => setOpen(false)} /> : null}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={open ? "Close support chat" : "Open support chat"}
        className={cn(
          "fixed right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-white shadow-lg",
          "transition-colors hover:bg-primary-hover focus-visible:shadow-focus focus-visible:outline-hidden",
          "bottom-[calc(5rem+var(--safe-bottom))] lg:bottom-6 lg:right-6",
          open && "max-sm:hidden",
        )}
      >
        {open ? <CloseIcon className="h-6 w-6" /> : <MessageIcon className="h-6 w-6" />}
      </button>
    </>
  );
}

function ChatPanel({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const { data, mutate } = useSWR<Chat>("/support/chat/", { refreshInterval: 5000 });
  const [draft, setDraft] = React.useState("");
  const [sending, setSending] = React.useState(false);

  async function send(payload: { body: string } | { topic: string }) {
    setSending(true);
    try {
      await mutate(await api.post<Chat>("/support/chat/", payload), { revalidate: false });
      if ("body" in payload) setDraft("");
    } catch (error) {
      toast.error("Message not sent", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setSending(false);
    }
  }

  const withStaff = data?.status === "WAITING" || data?.status === "ANSWERED";

  return (
    <div
      role="dialog"
      aria-label="Support chat"
      className={cn(
        "fixed z-50 flex flex-col overflow-hidden border border-line bg-surface shadow-xl",
        "inset-x-0 bottom-0 top-14 rounded-t-2xl",
        "sm:inset-auto sm:bottom-24 sm:right-6 sm:h-[34rem] sm:max-h-[calc(100dvh-8rem)] sm:w-96 sm:rounded-2xl",
      )}
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-ink">VerifyGH support</p>
          <p className="text-caption text-ink-muted">
            {withStaff ? "An admin will reply here" : "Instant answers, or ask for a person"}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close support chat">
          <CloseIcon className="h-5 w-5" />
        </Button>
      </div>

      {data ? (
        <ChatMessages
          messages={data.messages}
          mine="CUSTOMER"
          empty="Hi! Choose a topic below or type your question. Never send your password or MoMo PIN."
        />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      )}

      {data ? (
        <div className="no-scrollbar flex gap-2 overflow-x-auto border-t border-line px-3 py-2">
          {data.topics
            .filter((topic) => !(withStaff && topic.key === "human"))
            .map((topic) => (
              <button
                key={topic.key}
                type="button"
                disabled={sending}
                onClick={() => send({ topic: topic.key })}
                className="shrink-0 rounded-full bg-brand-50 px-3 py-1.5 text-caption font-medium text-brand-700 hover:bg-brand-100 disabled:opacity-50"
              >
                {topic.label}
              </button>
            ))}
        </div>
      ) : null}

      <form
        className="flex items-end gap-2 border-t border-line p-3 pb-safe sm:pb-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim()) send({ body: draft.trim() });
        }}
      >
        <Textarea
          rows={1}
          value={draft}
          maxLength={MAX_LENGTH}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Type a message"
          aria-label="Message"
          className="max-h-32 min-h-11 resize-none py-2.5"
        />
        <Button type="submit" loading={sending} disabled={!draft.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}

/** A chat transcript, newest at the bottom. Shared with the admin inbox. */
export function ChatMessages({
  messages,
  mine,
  empty,
}: {
  messages: ChatMessage[];
  mine: ChatMessage["sender"];
  empty: string;
}) {
  const end = React.useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1]?.id;
  React.useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [last]);

  return (
    <div className="flex-1 space-y-3 overflow-y-auto bg-canvas px-4 py-4" aria-live="polite">
      {messages.length === 0 ? <p className="text-sm text-ink-muted">{empty}</p> : null}
      {messages.map((message) => {
        const own = message.sender === mine;
        return (
          <div key={message.id} className={cn("flex flex-col", own ? "items-end" : "items-start")}>
            <span className="mb-0.5 text-2xs text-ink-faint">
              {message.sender === "BOT" ? "Assistant" : message.sender === "STAFF" ? "VerifyGH team" : "Customer"}
              {" · "}
              {new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
            <p
              className={cn(
                "max-w-[85%] whitespace-pre-line rounded-2xl px-3.5 py-2 text-sm",
                own ? "bg-primary text-white" : "border border-line bg-surface text-ink",
              )}
            >
              {message.body}
            </p>
          </div>
        );
      })}
      <div ref={end} />
    </div>
  );
}
