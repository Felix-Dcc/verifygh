"use client";

import useSWR from "swr";

import * as React from "react";

import { PageHeader } from "@/components/app-shell";
import { CheckIcon, CopyIcon, MessageIcon, ShareIcon } from "@/components/icons";
import { InviteArt } from "@/components/illustrations";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Input,
  LoadError,
  Section,
  Skeleton,
  StatusBadge,
  buttonClasses,
} from "@/components/ui/primitives";
import { cedis, relativeTime } from "@/lib/format";
import type { MyReferral, ReferralHistoryItem } from "@/lib/types";

/** Copy to clipboard, with a fallback for browsers that refuse the API. */
function useCopy() {
  const [copied, setCopied] = React.useState("");

  const copy = React.useCallback(async (value: string, key: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const field = document.createElement("textarea");
      field.value = value;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      try {
        document.execCommand("copy");
      } finally {
        document.body.removeChild(field);
      }
    }
    setCopied(key);
    window.setTimeout(() => setCopied(""), 2000);
  }, []);

  return { copied, copy };
}

export default function ReferPage() {
  const { data, isLoading, error, mutate } = useSWR<MyReferral>("/referrals/me/");
  const {
    data: history,
    error: historyError,
    mutate: retryHistory,
  } = useSWR<{ results: ReferralHistoryItem[] }>("/referrals/history/");
  const { copied, copy } = useCopy();
  const [canShare, setCanShare] = React.useState(false);

  React.useEffect(() => {
    setCanShare(typeof navigator !== "undefined" && typeof navigator.share === "function");
  }, []);

  const bonus = data ? cedis(data.bonus_amount) : "";
  const message = data
    ? `Join me on VerifyGH and get ${bonus} in promotional credit for phone verifications. Pay with Mobile Money in cedis: ${data.share_url}`
    : "";

  async function share() {
    if (!data) return;
    try {
      await navigator.share({
        title: "Join me on VerifyGH",
        text: message,
        url: data.share_url,
      });
    } catch {
      // The person dismissed the sheet, or the browser refused. Nothing to do.
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Refer friends"
        description="Give a friend promotional credit when they join VerifyGH."
      />

      {data && !data.enabled ? (
        <Alert tone="warn" title="The referral programme is paused">
          Invitations are not being accepted right now. Nothing you have already earned is
          affected.
        </Alert>
      ) : null}

      {data && !data.enabled ? null : error && !data ? (
        <Card>
          <LoadError what="your referral code" onRetry={() => mutate()} />
        </Card>
      ) : (
        <>
          <Card className="grid grid-cols-1 overflow-hidden md:grid-cols-5">
            <div className="p-5 sm:p-6 md:col-span-3">
              <h2 className="text-heading text-ink">
                {bonus ? `Your friend gets ${bonus} to start` : "Invite a friend"}
              </h2>
              <p className="mt-1 text-sm text-ink-muted">
                The credit lands in their wallet once they confirm their email address.
              </p>

              <div className="mt-5">
                <p className="text-label text-ink-muted">Your code</p>
                {isLoading ? (
                  <Skeleton className="mt-2 h-11 w-48" />
                ) : (
                  <div className="mt-1.5 flex flex-wrap items-center gap-3">
                    <span className="code select-all text-title font-semibold tracking-widest text-ink">
                      {data?.code}
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => data && copy(data.code, "code")}
                      icon={
                        copied === "code" ? <CheckIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />
                      }
                    >
                      {copied === "code" ? "Copied" : "Copy code"}
                    </Button>
                  </div>
                )}
              </div>

              <div className="mt-5">
                <label htmlFor="share-url" className="text-label text-ink-muted">
                  Your link
                </label>
                {isLoading ? (
                  <Skeleton className="mt-2 h-11 w-full max-w-md" />
                ) : (
                  <div className="mt-1.5 flex gap-2">
                    <Input
                      id="share-url"
                      readOnly
                      value={data?.share_url ?? ""}
                      onFocus={(event) => event.target.select()}
                      className="text-sm text-ink-soft"
                    />
                    <Button
                      variant="secondary"
                      onClick={() => data && copy(data.share_url, "link")}
                      icon={
                        copied === "link" ? <CheckIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />
                      }
                      className="shrink-0"
                    >
                      {copied === "link" ? "Copied" : "Copy link"}
                    </Button>
                  </div>
                )}
              </div>

              <div className="mt-5 flex flex-wrap gap-2">
                <a
                  href={`https://wa.me/?text=${encodeURIComponent(message)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={buttonClasses({})}
                >
                  <MessageIcon className="h-4 w-4" />
                  Share on WhatsApp
                </a>
                <a
                  href={`sms:?&body=${encodeURIComponent(message)}`}
                  className={buttonClasses({ variant: "secondary" })}
                >
                  Send by SMS
                </a>
                {canShare ? (
                  <Button variant="secondary" onClick={share} icon={<ShareIcon className="h-4 w-4" />}>
                    More
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="border-t border-line bg-sunken/50 p-5 sm:p-6 md:col-span-2 md:border-l md:border-t-0">
              <h2 className="text-sm font-semibold text-ink">How it works</h2>
              <ol className="mt-3 space-y-3">
                {[
                  "Share your code or link with a friend.",
                  "They create an account and confirm their email address.",
                  `${bonus || "The bonus"} in promotional credit lands in their wallet.`,
                ].map((step, index) => (
                  <li key={step} className="flex gap-3 text-sm text-ink-soft">
                    <span
                      aria-hidden
                      className="tabular flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-caption font-semibold text-ink-soft"
                    >
                      {index + 1}
                    </span>
                    <span className="pt-0.5">{step}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-4 text-caption text-ink-muted">
                Promotional credit can be spent on any number. It cannot be withdrawn, transferred or
                converted to cash, and one bonus is given per account.
              </p>
            </div>
          </Card>

          <Card className="grid grid-cols-3 divide-x divide-line">
            <Stat label="Joined and confirmed" value={data?.stats.successful} />
            <Stat label="Waiting to confirm" value={data?.stats.pending} />
            <Stat
              label="Credit given to friends"
              value={data ? cedis(data.stats.rewards_issued) : undefined}
            />
          </Card>
        </>
      )}

      <Section title="Your invitations">
        <Card className="overflow-hidden">
          {historyError && !history ? (
            <LoadError what="your invitations" onRetry={() => retryHistory()} />
          ) : !history ? (
            <div className="space-y-2 p-4" aria-busy>
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : history.results.length === 0 ? (
            <EmptyState
              art={<InviteArt />}
              title="No invitations yet"
              description="Share your link and your friends' sign-ups will appear here."
            />
          ) : (
            <ul className="divide-y divide-line">
              {history.results.map((item, index) => (
                <li
                  key={`${item.friend}-${index}`}
                  className="flex items-center justify-between gap-3 px-4 py-3 sm:px-5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{item.friend}</p>
                    <p className="text-caption text-ink-muted">Joined {relativeTime(item.created_at)}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {item.reward_amount ? (
                      <span className="tabular text-sm font-medium text-gold-700">
                        {cedis(item.reward_amount)}
                      </span>
                    ) : null}
                    <StatusBadge status={item.status} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </Section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value?: number | string }) {
  return (
    <div className="min-w-0 p-4 sm:p-5">
      <p className="text-caption text-ink-muted">{label}</p>
      {value === undefined ? (
        <Skeleton className="mt-2 h-6 w-16" />
      ) : (
        <p className="tabular mt-1 truncate text-heading text-ink">{value}</p>
      )}
    </div>
  );
}
