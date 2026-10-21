"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { CloseIcon, HeadsetIcon, MessageIcon, PaperclipIcon } from "@/components/icons";
import { useToast } from "@/components/ui/toast";
import { Button, Spinner, Textarea, cn } from "@/components/ui/primitives";
import { API_URL, ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

/**
 * The support chat: a bubble on every signed-in page. Every message goes to
 * the admins, who reply from Admin > Chats. Polls only while the panel is open.
 */

export type ChatMessage = {
  id: string;
  sender: "CUSTOMER" | "BOT" | "STAFF";
  body: string;
  has_image: boolean;
  created_at: string;
};

type Chat = {
  status: "BOT" | "WAITING" | "ANSWERED" | "CLOSED";
  messages: ChatMessage[];
};

const MAX_LENGTH = 1000;
const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const PHOTO_TYPES = "image/png,image/jpeg,image/webp";

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
  const [photo, setPhoto] = React.useState<File | null>(null);
  const [sending, setSending] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement>(null);
  const preview = React.useMemo(() => (photo ? URL.createObjectURL(photo) : ""), [photo]);
  React.useEffect(() => () => URL.revokeObjectURL(preview), [preview]);

  function pick(file: File | undefined) {
    if (fileInput.current) fileInput.current.value = "";
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      toast.error("Photo too large", "Photos must be 5 MB or smaller.");
      return;
    }
    setPhoto(file);
  }

  async function send() {
    const body = draft.trim();
    if (!body && !photo) return;
    setSending(true);
    try {
      let payload: FormData | { body: string } = { body };
      if (photo) {
        payload = new FormData();
        payload.append("body", body);
        payload.append("image", photo);
      }
      await mutate(await api.post<Chat>("/support/chat/", payload), { revalidate: false });
      setDraft("");
      setPhoto(null);
    } catch (error) {
      toast.error("Message not sent", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setSending(false);
    }
  }

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
      <div className="flex items-center gap-3 border-b border-line px-4 py-3">
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700"
        >
          <HeadsetIcon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-sm font-semibold text-ink">
            VerifyGH support
            <span className="flex items-center gap-1 text-caption font-medium text-success-700">
              <span aria-hidden className="h-2 w-2 rounded-full bg-success-500" />
              Online
            </span>
          </p>
          <p className="text-caption text-ink-muted">Support team</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close support chat">
          <CloseIcon className="h-5 w-5" />
        </Button>
      </div>

      {data ? (
        <ChatMessages
          messages={data.messages}
          mine="CUSTOMER"
          imageUrl={(id) => `${API_URL}/support/chat/images/${id}/`}
          empty="Send us a message and our support team will reply here. Include your order reference if it's about an order. Never send your password or MoMo PIN."
        />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      )}

      {photo ? (
        <div className="flex items-center gap-3 border-t border-line px-3 py-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={preview} alt="Photo to send" className="h-12 w-12 rounded-lg border border-line object-cover" />
          <span className="min-w-0 flex-1 truncate text-caption text-ink-muted">{photo.name}</span>
          <Button variant="ghost" size="sm" onClick={() => setPhoto(null)} aria-label="Remove photo">
            <CloseIcon className="h-4 w-4" />
          </Button>
        </div>
      ) : null}

      <form
        className="flex items-end gap-2 border-t border-line p-3 pb-safe sm:pb-3"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <input
          ref={fileInput}
          type="file"
          accept={PHOTO_TYPES}
          className="hidden"
          onChange={(event) => pick(event.target.files?.[0])}
        />
        <Button
          variant="ghost"
          size="sm"
          disabled={sending}
          onClick={() => fileInput.current?.click()}
          aria-label="Attach photo"
        >
          <PaperclipIcon className="h-5 w-5" />
        </Button>
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
          placeholder="Message support..."
          aria-label="Message"
          className="max-h-32 min-h-11 resize-none py-2.5"
        />
        <Button type="submit" loading={sending} disabled={!draft.trim() && !photo}>
          Send
        </Button>
      </form>
    </div>
  );
}

const SENDER_LABEL: Record<ChatMessage["sender"], string> = {
  CUSTOMER: "Customer",
  STAFF: "VerifyGH support",
  BOT: "VerifyGH",
};

/** A chat transcript, newest at the bottom. Shared with the admin inbox. */
export function ChatMessages({
  messages,
  mine,
  imageUrl,
  empty,
}: {
  messages: ChatMessage[];
  mine: ChatMessage["sender"];
  imageUrl: (id: string) => string;
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
            <div
              className={cn(
                "max-w-[85%] space-y-2 rounded-2xl px-3.5 py-2 text-sm",
                own ? "bg-primary text-white" : "border border-line bg-surface text-ink",
              )}
            >
              {!own ? <p className="text-2xs font-semibold opacity-70">{SENDER_LABEL[message.sender]}</p> : null}
              {message.has_image ? (
                <a href={imageUrl(message.id)} target="_blank" rel="noreferrer" className="block">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={imageUrl(message.id)}
                    alt="Attached photo"
                    className="max-h-56 rounded-lg object-cover"
                  />
                </a>
              ) : null}
              {message.body ? <p className="whitespace-pre-line">{message.body}</p> : null}
              <p className={cn("text-2xs", own ? "text-right text-white/70" : "text-ink-faint")}>
                {formatDateTime(message.created_at)}
              </p>
            </div>
          </div>
        );
      })}
      <div ref={end} />
    </div>
  );
}
