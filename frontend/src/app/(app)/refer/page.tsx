"use client";

import useSWR from "swr";

import * as React from "react";

import { PageHeader } from "@/components/app-shell";
import { CheckIcon, CopyIcon, ShareIcon, UsersIcon } from "@/components/icons";
import {
  Alert,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Skeleton,
  StatusBadge,
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
  const { data, isLoading } = useSWR<MyReferral>("/referrals/me/");
  const { data: history } = useSWR<{ results: ReferralHistoryItem[] }>("/referrals/history/");
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
    <div className="space-y-4">
      <PageHeader
        title="Refer & Earn"
        description="Invite your friends to VerifyGH."
      />

      {data && !data.enabled ? (
        <Alert tone="warn" title="The referral programme is paused">
          Your code still works once it reopens. Nothing you have already earned is affected.
        </Alert>
      ) : null}

      <div className="relative overflow-hidden rounded-2xl bg-brand-700 p-5 text-white shadow-raised sm:p-6">
        <div
          className="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-brand-500/30 blur-2xl"
          aria-hidden
        />
        <div className="relative">
          <p className="text-sm text-brand-200">
            Your friend gets {bonus || "a bonus"} in promotional credit once they verify their
            email.
          </p>

          <div className="mt-5">
            <p className="text-xs uppercase tracking-wide text-brand-200">Referral code</p>
            {isLoading ? (
              <Skeleton className="mt-2 h-12 w-48 bg-white/20" />
            ) : (
              <div className="mt-1.5 flex flex-wrap items-center gap-3">
                <span className="tabular rounded-xl bg-white/10 px-4 py-2.5 text-2xl font-semibold tracking-[0.2em] sm:text-3xl">
                  {data?.code}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => data && copy(data.code, "code")}
                  icon={
                    copied === "code" ? (
                      <CheckIcon className="h-4 w-4" />
                    ) : (
                      <CopyIcon className="h-4 w-4" />
                    )
                  }
                >
                  {copied === "code" ? "Copied" : "Copy code"}
                </Button>
              </div>
            )}
          </div>

          <div className="mt-5">
            <p className="text-xs uppercase tracking-wide text-brand-200">Referral link</p>
            {isLoading ? (
              <Skeleton className="mt-2 h-10 w-full max-w-md bg-white/20" />
            ) : (
              <div className="mt-1.5 flex flex-wrap items-center gap-3">
                <code className="max-w-full overflow-x-auto rounded-lg bg-white/10 px-3 py-2 text-sm">
                  {data?.share_url}
                </code>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => data && copy(data.share_url, "link")}
                  icon={
                    copied === "link" ? (
                      <CheckIcon className="h-4 w-4" />
                    ) : (
                      <CopyIcon className="h-4 w-4" />
                    )
                  }
                >
                  {copied === "link" ? "Copied" : "Copy link"}
                </Button>
              </div>
            )}
          </div>

          <div className="mt-6 flex flex-wrap gap-2">
            <a
              href={`https://wa.me/?text=${encodeURIComponent(message)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-xl bg-[#25D366] px-4 py-2.5 text-sm font-semibold text-[#0b3d25] transition hover:brightness-105"
            >
              <ShareIcon className="h-4 w-4" />
              Share on WhatsApp
            </a>
            <a
              href={`sms:?&body=${encodeURIComponent(message)}`}
              className="inline-flex items-center gap-2 rounded-xl bg-white/10 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-white/20"
            >
              Send by SMS
            </a>
            {canShare ? (
              <button
                type="button"
                onClick={share}
                className="inline-flex items-center gap-2 rounded-xl bg-white/10 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-white/20"
              >
                <ShareIcon className="h-4 w-4" />
                More
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Successful referrals" value={data?.stats.successful} />
        <StatCard label="Pending" value={data?.stats.pending} />
        <StatCard
          label="Credit earned by friends"
          value={data ? cedis(data.stats.rewards_issued) : undefined}
        />
      </div>

      <Card>
        <CardHeader title="Your invitations" />
        {!history ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : history.results.length === 0 ? (
          <EmptyState
            icon={<UsersIcon />}
            title="No invitations yet"
            description="Share your link and your friends' sign-ups will appear here."
          />
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {history.results.map((item, index) => (
              <li
                key={`${item.friend}-${index}`}
                className="flex items-center justify-between gap-3 px-4 py-3.5 sm:px-5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">{item.friend}</p>
                  <p className="text-xs text-ink-muted">
                    Joined {relativeTime(item.created_at)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {item.reward_amount ? (
                    <span className="tabular text-sm font-semibold text-brand-700">
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

      <Card className="p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-ink">How it works</h2>
        <ol className="mt-2 space-y-1.5 text-sm text-ink-muted">
          <li>1. Share your code or link with a friend.</li>
          <li>2. They create an account and verify their email address.</li>
          <li>3. {bonus || "The bonus"} in promotional credit lands in their wallet.</li>
        </ol>
        <p className="mt-3 text-xs text-ink-muted">
          Promotional credit can be spent on any verification. It cannot be withdrawn,
          transferred or converted to cash, and one bonus is given per account.
        </p>
      </Card>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value?: number | string }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-ink-muted">{label}</p>
      {value === undefined ? (
        <Skeleton className="mt-2 h-7 w-16" />
      ) : (
        <p className="tabular mt-1 text-2xl font-semibold text-ink">{value}</p>
      )}
    </Card>
  );
}
