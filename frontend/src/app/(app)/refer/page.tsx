"use client";

import useSWR from "swr";

import * as React from "react";

import { AppHero } from "@/components/app-hero";
import {
  CheckIcon,
  CopyIcon,
  GiftIcon,
  MessageIcon,
  ShareIcon,
  UsersIcon,
  WalletIcon,
} from "@/components/icons";
import { InviteArt } from "@/components/illustrations";
import { friendOffer } from "@/components/referral-invite";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  LoadError,
  Section,
  Skeleton,
  buttonClasses,
  cn,
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

/** "GH₵ 3.00" -> "GH₵3", for headlines; keeps pesewas when there are any. */
function short(amount: string): string {
  const value = Number.parseFloat(amount);
  if (!Number.isFinite(value)) return cedis(amount);
  return `GH₵${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2)}`;
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

  const earns = data ? Number.parseFloat(data.referrer_bonus) > 0 : false;
  const deposits = data
    ? data.require_first_deposit && Number.parseFloat(data.min_first_deposit) > 0
    : false;
  const offer = data
    ? friendOffer({
        bonus: data.bonus_amount,
        referrerBonus: data.referrer_bonus,
        requireFirstDeposit: data.require_first_deposit,
        minFirstDeposit: data.min_first_deposit,
      })
    : "";
  const message = data
    ? `Join me on VerifyGH - US numbers for WhatsApp, Telegram, TikTok and more, paid with Mobile Money. Sign up with my code ${data.code} and get ${offer}: ${data.share_url}`
    : "";

  async function share() {
    if (!data) return;
    try {
      await navigator.share({ title: "Join me on VerifyGH", text: message, url: data.share_url });
    } catch {
      // The person dismissed the sheet, or the browser refused. Nothing to do.
    }
  }

  if (data && !data.enabled) {
    return (
      <div className="space-y-6">
        <h1 className="text-title text-ink">Refer friends</h1>
        <Alert tone="warn" title="The referral programme is paused">
          Invitations are not being accepted right now. Nothing you have already earned is affected.
        </Alert>
        <Invitations history={history} error={historyError} retry={() => retryHistory()} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <AppHero
        eyebrow="Refer & earn"
        title={
          data ? (
            earns ? (
              <>
                Earn <span className="text-dawn">{short(data.referrer_bonus)}</span> for every friend who
                joins
              </>
            ) : (
              <>
                Give friends <span className="text-dawn">{short(data.bonus_amount)}</span> to start
              </>
            )
          ) : (
            "Invite friends to VerifyGH"
          )
        }
        description={
          data
            ? `Your friend gets ${short(data.bonus_amount)} of credit${
                deposits ? ` after their first top-up of ${short(data.min_first_deposit)}` : ""
              }${earns ? `, and you get ${short(data.referrer_bonus)} when they complete their first number.` : "."}`
            : "Share your link. Rewards land in your wallet as promotional credit."
        }
        actions={
          data ? (
            <>
              <a
                href={`https://wa.me/?text=${encodeURIComponent(message)}`}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(buttonClasses({ variant: "onBand", size: "lg" }), "gap-2")}
              >
                <MessageIcon className="h-5 w-5 text-[#1FA855]" />
                Share on WhatsApp
              </a>
              <Button
                variant="onBandOutline"
                size="lg"
                onClick={() => copy(data.share_url, "link")}
                icon={copied === "link" ? <CheckIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />}
              >
                {copied === "link" ? "Link copied" : "Copy link"}
              </Button>
              <a
                href={`sms:?&body=${encodeURIComponent(message)}`}
                className={buttonClasses({ variant: "onBandOutline", size: "lg" })}
              >
                SMS
              </a>
              {canShare ? (
                <Button
                  variant="onBandOutline"
                  size="lg"
                  onClick={share}
                  icon={<ShareIcon className="h-4 w-4" />}
                  aria-label="More ways to share"
                >
                  More
                </Button>
              ) : null}
            </>
          ) : null
        }
        aside={
          error && !data ? (
            <div className="rounded-2xl border border-white/10 bg-white/6 p-4">
              <LoadError what="your referral code" onRetry={() => mutate()} />
            </div>
          ) : (
            <RewardCard
              data={data}
              loading={isLoading}
              copied={copied === "code"}
              onCopy={() => data && copy(data.code, "code")}
            />
          )
        }
      />

      <Section title="How it works">
        <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-4">
          {[
            {
              icon: <ShareIcon />,
              title: "Share your link",
              text: "Send it on WhatsApp, in your groups, or by SMS.",
            },
            {
              icon: <UsersIcon />,
              title: "Your friend joins",
              text: deposits && data
                ? `They sign up, confirm their email and top up ${short(data.min_first_deposit)} or more.`
                : "They sign up and confirm their email.",
            },
            {
              icon: <GiftIcon />,
              title: data ? `They get ${short(data.bonus_amount)}` : "They get credit",
              text: "Promotional credit lands in their wallet, ready for any number.",
            },
            {
              icon: <WalletIcon />,
              title: data && earns ? `You get ${short(data.referrer_bonus)}` : "Everyone wins",
              text: earns
                ? "As soon as they complete their first number."
                : "Your friends start with credit on VerifyGH.",
            },
          ].map((step, index) => (
            <li key={step.title} className="card relative flex gap-3 p-4">
              <span
                aria-hidden
                className={cn(
                  "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl [&_svg]:h-5 [&_svg]:w-5",
                  index === 3 ? "bg-gold-100 text-gold-700" : "bg-brand-50 text-brand-700",
                )}
              >
                {step.icon}
              </span>
              <div className="min-w-0">
                <p className="text-caption font-medium text-ink-faint">Step {index + 1}</p>
                <p className="text-sm font-semibold text-ink">{step.title}</p>
                <p className="mt-0.5 text-sm text-ink-muted">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Your results">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            icon={<WalletIcon />}
            label="You earned"
            value={data ? cedis(data.stats.earned) : undefined}
            highlight
          />
          <Stat icon={<UsersIcon />} label="Friends welcomed" value={data?.stats.successful} />
          <Stat icon={<GiftIcon />} label="Credit given to friends" value={data ? cedis(data.stats.rewards_issued) : undefined} />
          <Stat icon={<CheckIcon />} label="Not qualified yet" value={data?.stats.pending} />
        </div>
      </Section>

      <Invitations history={history} error={historyError} retry={() => retryHistory()} />

      <p className="text-caption text-ink-muted">
        Promotional credit can be spent on any number. It cannot be withdrawn, transferred or converted
        to cash. One welcome bonus per person, and invitations to your own other accounts do not count.
      </p>
    </div>
  );
}

/** The two rewards and the code, on the navy panel - the thing people screenshot. */
function RewardCard({
  data,
  loading,
  copied,
  onCopy,
}: {
  data: MyReferral | undefined;
  loading: boolean;
  copied: boolean;
  onCopy: () => void;
}) {
  const earns = data ? Number.parseFloat(data.referrer_bonus) > 0 : false;
  return (
    <div className="rounded-2xl border border-white/10 bg-white/6 p-4 backdrop-blur-sm sm:p-5">
      <div className={cn("grid gap-3", earns ? "grid-cols-2" : "grid-cols-1")}>
        {earns ? (
          <RewardTile label="You get" value={data ? short(data.referrer_bonus) : undefined} accent />
        ) : null}
        <RewardTile label="Friend gets" value={data ? short(data.bonus_amount) : undefined} />
      </div>

      <p className="mt-4 text-caption text-white/60">Your invitation code</p>
      {loading || !data ? (
        <Skeleton className="mt-1.5 h-14 w-full rounded-xl" />
      ) : (
        <button
          type="button"
          onClick={onCopy}
          className="group mt-1.5 flex w-full items-center justify-between gap-2 rounded-xl border-2 border-dashed border-white/25 bg-white/5 px-3 py-3 text-left transition hover:border-aqua/60 hover:bg-white/10"
          aria-label={`Copy your code ${data.code}`}
        >
          {/* Never truncated: a code that is cut off cannot be typed. */}
          <span className="code whitespace-nowrap text-lg font-bold tracking-[0.12em] text-white sm:text-xl">
            {data.code}
          </span>
          <span className="flex shrink-0 items-center gap-1.5 text-sm font-medium text-white/80 group-hover:text-white">
            {copied ? <CheckIcon className="h-4 w-4 text-leaf-light" /> : <CopyIcon className="h-4 w-4" />}
            <span className={copied ? "" : "sr-only 2xl:not-sr-only"}>{copied ? "Copied" : "Copy"}</span>
          </span>
        </button>
      )}
      <p className="mt-2 text-2xs text-white/60">Friends can type it when they sign up, or use your link.</p>
    </div>
  );
}

function RewardTile({ label, value, accent }: { label: string; value?: string; accent?: boolean }) {
  return (
    <div
      className={cn(
        "min-w-0 rounded-xl p-3 ring-1 ring-inset",
        accent ? "bg-linear-to-br from-aqua/20 to-leaf/20 ring-white/15" : "bg-white/4 ring-white/10",
      )}
    >
      <p className="flex items-center gap-1.5 whitespace-nowrap text-caption text-white/70">
        <GiftIcon className="h-3.5 w-3.5 shrink-0" />
        {label}
      </p>
      {value === undefined ? (
        <Skeleton className="mt-2 h-8 w-20" />
      ) : (
        <p
          className={cn(
            // inline-block: the dawn gradient is clipped to the text box, and a
            // block-width box spread it so thin the figure all but vanished.
            "tabular mt-1 inline-block whitespace-nowrap text-2xl font-extrabold tracking-tight sm:text-3xl",
            accent ? "text-dawn" : "text-white",
          )}
        >
          {value}
        </p>
      )}
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
  highlight,
}: {
  icon: React.ReactNode;
  label: string;
  value?: number | string;
  highlight?: boolean;
}) {
  return (
    <Card className={cn("p-4", highlight && "border-gold-300 bg-gold-100/40")}>
      <p className="flex items-center gap-2 text-caption text-ink-muted">
        <span
          aria-hidden
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-lg [&_svg]:h-4 [&_svg]:w-4",
            highlight ? "bg-gold-100 text-gold-700" : "bg-sunken text-ink-soft",
          )}
        >
          {icon}
        </span>
        {label}
      </p>
      {value === undefined ? (
        <Skeleton className="mt-2 h-7 w-16" />
      ) : (
        <p className={cn("tabular mt-2 text-title", highlight ? "text-gold-700" : "text-ink")}>{value}</p>
      )}
    </Card>
  );
}

/** Each friend's progress: joined, welcomed (topped up), first number. */
function Invitations({
  history,
  error,
  retry,
}: {
  history: { results: ReferralHistoryItem[] } | undefined;
  error: unknown;
  retry: () => void;
}) {
  return (
    <Section title="Your invitations">
      <Card className="overflow-hidden">
        {error && !history ? (
          <LoadError what="your invitations" onRetry={retry} />
        ) : !history ? (
          <div className="space-y-2 p-4" aria-busy>
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : history.results.length === 0 ? (
          <EmptyState
            art={<InviteArt />}
            title="No invitations yet"
            description="Share your link and your friends' sign-ups will appear here."
          />
        ) : (
          <ul className="divide-y divide-line">
            {history.results.map((item, index) => {
              const welcomed = item.status === "REWARDED";
              const bought = Boolean(item.earned_amount);
              const declined = item.status === "REJECTED";
              return (
                <li
                  key={`${item.friend}-${index}`}
                  className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span
                      aria-hidden
                      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-sm font-semibold uppercase text-brand-700"
                    >
                      {item.friend.charAt(0)}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{item.friend}</p>
                      <p className="text-caption text-ink-muted">Joined {relativeTime(item.created_at)}</p>
                    </div>
                  </div>

                  {declined ? (
                    <span className="self-start rounded-full bg-sunken px-2.5 py-1 text-caption font-medium text-ink-muted sm:self-auto">
                      Did not qualify
                    </span>
                  ) : (
                    <div className="flex items-center gap-3 sm:justify-end">
                      <Progress steps={[true, welcomed, bought]} />
                      {bought ? (
                        <span className="tabular rounded-full bg-success-50 px-2.5 py-1 text-caption font-semibold text-success-700">
                          +{cedis(item.earned_amount)}
                        </span>
                      ) : (
                        <span className="text-caption text-ink-muted">
                          {welcomed ? "Waiting for first number" : "Waiting for top-up"}
                        </span>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </Section>
  );
}

const STEP_LABELS = ["Joined", "Topped up", "First number"];

function Progress({ steps }: { steps: boolean[] }) {
  const reached = steps.filter(Boolean).length;
  return (
    <div className="flex items-center gap-1" aria-label={`${STEP_LABELS[reached - 1]} (${reached} of 3)`}>
      {steps.map((done, index) => (
        <React.Fragment key={STEP_LABELS[index]}>
          {index > 0 ? (
            <span aria-hidden className={cn("h-0.5 w-4 rounded-full sm:w-6", done ? "bg-brand-500" : "bg-line")} />
          ) : null}
          <span
            title={STEP_LABELS[index]}
            aria-hidden
            className={cn(
              "flex h-5 w-5 items-center justify-center rounded-full",
              done ? "bg-brand-500 text-white" : "border border-line-strong bg-surface",
            )}
          >
            {done ? <CheckIcon className="h-3 w-3" /> : null}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
}
