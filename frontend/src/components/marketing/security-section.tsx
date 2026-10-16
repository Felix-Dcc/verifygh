"use client";

import { CheckCircleIcon, PlusIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { cn } from "@/components/ui/primitives";
import { cedis, signedCedis } from "@/lib/format";

import { AddressBar, BottomNav, Device, Halo, HomeIndicator, Reveal, StatusBar, useInView, useStory } from "./device";

/**
 * How money and accounts are protected, as an annotated product shot: your
 * account on a phone with six numbered markers, each on the part of the
 * screen a protection guards, and the protection written beside it. The
 * markers light up in turn while the section is on screen; pointing at a
 * note lights its marker.
 *
 * Every note is something the code does (docs/SECURITY.md) - no badges, no
 * "bank-grade", no guarantees. The account on the phone is an example.
 */

const CONTROLS = [
  {
    title: "Encrypted on every page",
    body: "Every page and API call is served over HTTPS, and browsers are told never to connect any other way. Sign-in cookies can't be read by scripts.",
  },
  {
    title: "A confirmed email before buying",
    body: "Numbers can only be bought once your email address is confirmed, so every order traces back to a real inbox.",
  },
  {
    title: "Sign-in that resists guessing",
    body: "Passwords are hashed with Argon2, and repeated failed sign-ins lock the account for a while. Changing your password signs out every other session.",
  },
  {
    title: "Limits on every wallet",
    body: "Deposit caps, a daily spending limit and order rate limits contain the damage if an account is ever compromised.",
  },
  {
    title: "Top-ups you can prove",
    body: "A deposit is credited only after we verify a signed confirmation from the payment provider. Nothing your browser says can credit a wallet.",
  },
  {
    title: "A ledger that balances",
    body: "Every cedi in or out is an entry with a running balance. Balances are re-checked on a schedule, and any difference raises an alert.",
  },
];

const EXAMPLE_BALANCE = 127.5;
const EXAMPLE_TOPUP = 50;
const EXAMPLE_PURCHASE = 11.5;

export function SecuritySection() {
  const [ref, inView] = useInView<HTMLElement>();
  const story = useStory(CONTROLS.length, inView, 3200);
  // Under reduced motion nothing is singled out: every marker and note is equal.
  const active = story.reduced ? -1 : story.index;

  const note = (index: number) => (
    <Note
      key={CONTROLS[index].title}
      index={index}
      active={active === index}
      dim={active !== -1 && active !== index}
      side={index < 3 ? "left" : "right"}
      onPoint={() => story.choose(index)}
    />
  );

  return (
    <section ref={ref} id="protection" className="atmosphere-wash scroll-mt-20 overflow-x-clip" aria-labelledby="security-heading">
      <div className="container-page py-16 sm:py-24">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 id="security-heading" className="section-title">
            Your money and account are protected.
          </h2>
          <p className="section-lead">
            Your wallet, the way you see it - and the six things guarding it, shown where they
            work. No badges, no borrowed certifications.
          </p>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 items-center gap-10 lg:grid-cols-[1fr_auto_1fr] lg:gap-10">
          <Reveal className="order-2 lg:order-1">
            <ol className="space-y-2 lg:space-y-6">{[0, 1, 2].map(note)}</ol>
          </Reveal>

          <Reveal className="order-1 lg:order-2">
            <div className="relative mx-auto flex justify-center py-4" aria-hidden>
              <Rings />
              <Halo className="left-1/2 top-1/2 h-[110%] w-[150%] -translate-x-1/2 -translate-y-1/2" />
              <Device>
                <WalletScreen active={active} />
              </Device>
            </div>
          </Reveal>

          <Reveal className="order-3">
            <ol start={4} className="space-y-2 lg:space-y-6">
              {[3, 4, 5].map(note)}
            </ol>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/** One protection, with its number and a short rule pointing at the phone. */
function Note({
  index,
  active,
  dim,
  side,
  onPoint,
}: {
  index: number;
  active: boolean;
  dim: boolean;
  side: "left" | "right";
  onPoint: () => void;
}) {
  const control = CONTROLS[index];
  return (
    <li>
      <button
        type="button"
        onClick={onPoint}
        onMouseEnter={onPoint}
        onFocus={onPoint}
        aria-current={active ? "true" : undefined}
        className={cn(
          "flex w-full items-start gap-3.5 rounded-2xl px-2 py-2.5 text-left transition-opacity duration-500",
          side === "left" && "lg:flex-row-reverse lg:text-right",
          dim ? "opacity-60 hover:opacity-100" : "opacity-100",
        )}
      >
        <span className="relative mt-0.5 flex shrink-0 items-center">
          <span
            className={cn(
              "tabular flex h-7 w-7 items-center justify-center rounded-full text-caption font-bold transition-colors duration-500",
              active ? "bg-primary text-white" : "border border-line-strong bg-surface text-ink-soft",
            )}
          >
            {index + 1}
          </span>
          {/* The rule toward the phone */}
          <span
            aria-hidden
            className={cn(
              "absolute top-1/2 hidden h-px w-6 transition-colors duration-500 lg:block",
              side === "left" ? "-right-7" : "-left-7",
              active ? "bg-brand-500" : "bg-line-strong",
            )}
          />
        </span>
        <span className="min-w-0 lg:max-w-xs">
          <span className="block text-sm font-semibold text-ink">{control.title}</span>
          <span className="mt-1 block text-sm leading-relaxed text-ink-muted">{control.body}</span>
        </span>
      </button>
    </li>
  );
}

/** A numbered marker on the phone's screen. */
function Marker({ n, active }: { n: number; active: number }) {
  const on = active === n - 1;
  return (
    <span className="absolute -right-1 top-1/2 z-10 flex h-4 w-4 -translate-y-1/2 items-center justify-center">
      {on ? <span className="absolute inset-0 animate-pulse-ring rounded-full bg-brand-500/50" /> : null}
      <span
        className={cn(
          "tabular relative flex h-4 w-4 items-center justify-center rounded-full text-[0.5625rem] font-bold transition-colors duration-500",
          on ? "bg-primary text-white" : "bg-surface text-ink-soft ring-1 ring-line-strong",
        )}
      >
        {n}
      </span>
    </span>
  );
}

/** The wallet as the app shows it: balance, activity - and the account it belongs to. */
function WalletScreen({ active }: { active: number }) {
  return (
    <>
      <StatusBar />
      <div className="relative">
        <AddressBar />
        <span className="absolute right-3 top-3.5">
          <Marker n={1} active={active} />
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-1 px-3.5 pt-1 sm:gap-1.5">
        <div className="relative flex items-center gap-2 px-0.5 pr-5">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-50 text-[0.625rem] font-bold text-brand-700">
            KA
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-caption font-semibold leading-tight text-ink">Wallet</span>
            <span className="flex items-center gap-1 truncate text-[0.5625rem] text-ink-muted">
              you@example.com
              <CheckCircleIcon className="h-2.5 w-2.5 shrink-0 text-success-700" />
            </span>
          </span>
          <Marker n={2} active={active} />
        </div>

        <div className="relative rounded-2xl bg-linear-to-br from-[#0B63B6] to-[#137A4E] p-2.5 pr-6 text-white sm:p-3 shadow-[0_12px_24px_-12px_rgba(8,120,209,0.8)]">
          <p className="text-[0.625rem] text-white/75">Available balance</p>
          <p className="tabular text-2xl font-extrabold leading-tight tracking-tight">{cedis(EXAMPLE_BALANCE)}</p>
          <p className="mt-0.5 text-[0.5625rem] text-white/70">Spending limits apply</p>
          <Marker n={4} active={active} />
        </div>

        <div className="relative flex items-center justify-between rounded-xl border border-line bg-surface px-2.5 py-1.5 pr-5">
          <span className="text-[0.625rem] text-ink-muted">Password</span>
          <span className="text-caption tracking-[0.2em] text-ink">••••••••</span>
          <Marker n={3} active={active} />
        </div>

        <p className="mt-0.5 px-0.5 text-[0.625rem] font-medium text-ink-soft">Recent activity</p>
        <div className="divide-y divide-line rounded-xl border border-line bg-surface">
          <Activity
            icon={<PlusIcon className="h-2.5 w-2.5" />}
            title="Deposit"
            note="MoMo · confirmed"
            amount={signedCedis(EXAMPLE_TOPUP, "CREDIT")}
            credit
            marker={<Marker n={5} active={active} />}
          />
          <Activity
            icon={<ServiceLogo name="TikTok" src="/service-icons/tiktok.svg" slug="tiktok" size="xs" className="h-5! w-5!" />}
            title="Purchase"
            note="TikTok · US number"
            amount={signedCedis(EXAMPLE_PURCHASE, "DEBIT")}
            marker={<Marker n={6} active={active} />}
          />
          <Activity
            icon={<PlusIcon className="h-2.5 w-2.5" />}
            title="Refund"
            note="No code arrived"
            amount={signedCedis(EXAMPLE_PURCHASE, "CREDIT")}
            credit
          />
        </div>
      </div>
      <BottomNav active="wallet" />
      <HomeIndicator />
    </>
  );
}

function Activity({
  icon,
  title,
  note,
  amount,
  credit,
  marker,
}: {
  icon: React.ReactNode;
  title: string;
  note: string;
  amount: string;
  credit?: boolean;
  marker?: React.ReactNode;
}) {
  return (
    <div className="relative flex items-center gap-2 px-2.5 py-1 pr-5 sm:py-1.5">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-full bg-success-50 text-success-700">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.6875rem] font-medium leading-tight text-ink">{title}</span>
        <span className="block truncate text-[0.5625rem] text-ink-muted">{note}</span>
      </span>
      <span className={cn("tabular text-[0.6875rem] font-semibold", credit ? "text-success-700" : "text-ink")}>
        {amount}
      </span>
      {marker}
    </div>
  );
}

/** Faint concentric rings around the phone: a perimeter, drawn quietly. */
function Rings() {
  return (
    <svg
      viewBox="0 0 600 600"
      className="pointer-events-none absolute left-1/2 top-1/2 h-[125%] w-auto -translate-x-1/2 -translate-y-1/2 text-line-strong"
      fill="none"
      stroke="currentColor"
    >
      {[120, 180, 240, 296].map((r, index) => (
        <circle key={r} cx="300" cy="300" r={r} strokeWidth="1" strokeDasharray={index % 2 ? "2 6" : undefined} opacity={0.9 - index * 0.2} />
      ))}
    </svg>
  );
}
