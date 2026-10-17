"use client";

import * as React from "react";
import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { ArrowLeftIcon, CheckCircleIcon, GridIcon, LockIcon, PhoneIcon, PlusIcon, WalletIcon } from "@/components/icons";
import { NetworkLogo } from "@/components/network-logo";
import { Skeleton, cn } from "@/components/ui/primitives";
import { cedis, signedCedis } from "@/lib/format";
import type { MarketHome, PaymentOptions } from "@/lib/types";

import { BottomNav, Device, Halo, HomeIndicator, Reveal, ScreenStack, StatusBar, useInView, useStory } from "./device";

/**
 * Paying in cedis, the way people here already pay - shown as a top-up
 * happening: the Add funds form, the network's own PIN prompt on the phone,
 * then "Payment received" and the balance counting up. The three lines beside
 * the phone light up with it.
 *
 * The networks, the quick amounts and which network a 024 number belongs to
 * all come from the live payment options (the same data the Add funds screen
 * uses), so nothing here can name a network that is not supported today.
 * Each is shown with its own logo (components/network-logo.tsx). Invented: the
 * example balance and phone number.
 */

const STEP_MS = 3800;
const EXAMPLE_PHONE = "024 123 4567";
const EXAMPLE_START = 25;

/** Form, prompt, money received. */
const STORY_STEPS = 3;

export function PaymentSection() {
  const { data, error } = useSWR<PaymentOptions>("/payments/options/");
  const [ref, inView] = useInView<HTMLElement>();
  const story = useStory(STORY_STEPS, inView, STEP_MS);
  // Under reduced motion, show where the story ends: the money arrived.
  const step = story.reduced ? 2 : story.index;

  const quick = data?.quick_amounts ?? [];
  const amount =
    Number.parseFloat(quick.find((value) => Number.parseFloat(value) === 20) ?? quick[1] ?? "20") || 20;
  const network = data?.networks.find((entry) => entry.prefixes.includes(EXAMPLE_PHONE.slice(0, 3)));
  const { data: home } = useSWR<MarketHome>("/marketplace/home/");
  const prices = (home?.popular ?? []).map((row) => Number.parseFloat(row.price ?? "")).filter((value) => value > 0);
  const cheapest = prices.length ? Math.min(...prices) : null;

  return (
    <section ref={ref} className="atmosphere-wash overflow-x-clip" aria-labelledby="momo-heading">
      {/* Phones read heading, phone, details. From lg the phone takes the left
          column across every row and the text is centred against it. */}
      <div className="container-page grid grid-cols-1 gap-x-16 gap-y-8 py-16 sm:py-24 lg:grid-cols-2 lg:grid-rows-[1fr_auto_auto_1fr] lg:gap-y-6">
        <Reveal className="text-center lg:col-start-2 lg:row-start-2 lg:text-left">
          <h2 id="momo-heading" className="section-title">
            Fund your wallet with the Mobile Money you already use.
          </h2>
          <p className="section-lead mx-auto max-w-lg lg:mx-0">
            No card and no crypto. Top up in cedis from your MoMo wallet, then pay for numbers
            straight from your balance.
          </p>
        </Reveal>

        <Reveal className="lg:col-start-1 lg:row-span-4 lg:row-start-1 lg:self-center">
          <div className="relative mx-auto flex w-full max-w-md justify-center pb-6 pt-2" aria-hidden>
            <Halo className="left-1/2 top-1/2 h-[115%] w-[135%] -translate-x-1/2 -translate-y-1/2" />
            <Device>
              <StatusBar />
              <ScreenStack active={step}>
                <FormScreen amount={amount} quick={data?.quick_amounts} networkValue={network?.value} />
                <ApproveScreen amount={amount} networkLabel={network?.label} />
                <ReceivedScreen amount={amount} run={step === 2} reduced={story.reduced} networkLabel={network?.label} />
              </ScreenStack>
            </Device>

            {/* The outcome, beside the phone */}
            {step === 2 ? (
              <div className="absolute bottom-0 right-0 z-20 sm:-right-2">
                <div className="rise-in flex items-center gap-2.5 rounded-2xl bg-white py-2.5 pl-2.5 pr-4 shadow-pop">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#E6F4EC] text-[#1C7A4A]">
                    <PlusIcon className="h-3.5 w-3.5" />
                  </span>
                  <span>
                    <span className="tabular block text-sm font-semibold leading-tight text-black">
                      {cedis(EXAMPLE_START + amount)}
                    </span>
                    <span className="block text-2xs text-black/60">Your new balance</span>
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        </Reveal>

        <Reveal className="mx-auto w-full max-w-xl lg:col-start-2 lg:row-start-3 lg:max-w-none">
          <div>
            <p className="text-label text-ink-muted">Supported networks</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {data
                ? data.networks.map((entry) => (
                    <li
                      key={entry.value}
                      className="flex items-center gap-2.5 rounded-2xl border border-line bg-surface py-2 pl-2 pr-4 shadow-card"
                    >
                      <NetworkLogo network={entry.value} label={entry.label} />
                      <span>
                        <span className="block text-sm font-semibold text-ink">{entry.label}</span>
                        {/* Which numbers belong to it - how people here tell networks apart */}
                        <span className="tabular block text-2xs text-ink-muted">
                          {entry.prefixes.join(" · ")}
                        </span>
                      </span>
                    </li>
                  ))
                : error
                  ? (
                      <li className="text-sm text-ink-muted">
                        MTN, Telecel and AT Money - the live list is on the Add funds screen.
                      </li>
                    )
                  : [0, 1, 2].map((key) => (
                      <li key={key}>
                        <Skeleton className="h-13 w-40 rounded-2xl" />
                      </li>
                    ))}
            </ul>
          </div>

          {/* Where the money goes - Mobile Money, your wallet, numbers - lit in
              step with the phone: the same three moments, as a flow. */}
          <MoneyFlow
            step={step}
            reduced={story.reduced}
            onChoose={story.choose}
            amount={amount}
            networks={data?.networks.map((entry) => entry.label.replace(" Mobile Money", " MoMo"))}
            cheapest={cheapest}
          />

          <ul className="mt-6 space-y-2.5 text-sm text-ink-soft">
            <li className="flex items-start gap-2.5">
              <LockIcon className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
              Your PIN goes into your network&apos;s own prompt on your phone. It never passes
              through VerifyGH.
            </li>
            <li className="flex items-start gap-2.5">
              <CheckCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
              Payments are processed by our payment partner, and your wallet is credited only after
              the partner confirms the payment.
            </li>
          </ul>
        </Reveal>

      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------ */

function ScreenTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-3.5 pt-1">
      <ArrowLeftIcon className="h-3.5 w-3.5 text-ink-muted" />
      <p className="text-base font-semibold text-ink">{children}</p>
    </div>
  );
}

/** Add funds, filled in: amount chosen, number typed, network recognised. */
function FormScreen({ amount, quick, networkValue }: { amount: number; quick?: string[]; networkValue?: string }) {
  const chips = (quick && quick.length ? quick : ["10.00", "20.00", "50.00", "100.00"]).slice(0, 4);
  return (
    <>
      <ScreenTitle>Add funds</ScreenTitle>
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3.5 pt-3">
        <div className="flex items-center justify-between rounded-xl bg-sunken px-3 py-2 text-2xs">
          <span className="text-ink-muted">Current balance</span>
          <span className="tabular font-semibold text-ink">{cedis(EXAMPLE_START)}</span>
        </div>
        <div>
          <p className="text-2xs font-medium text-ink-soft">Amount to add</p>
          <div className="mt-1 flex h-10 items-center rounded-lg border border-brand-500 bg-surface px-3 text-sm ring-1 ring-brand-500">
            <span className="text-ink-muted">GH₵</span>
            <span className="tabular ml-1.5 font-semibold text-ink">{amount.toFixed(2)}</span>
          </div>
          <div className="mt-1.5 grid grid-cols-4 gap-1">
            {chips.map((value) => {
              const on = Number.parseFloat(value) === amount;
              return (
                <span
                  key={value}
                  className={cn(
                    "tabular rounded-full border py-1 text-center text-[0.625rem]",
                    on ? "border-brand-500 bg-brand-50 font-semibold text-brand-700" : "border-line text-ink-soft",
                  )}
                >
                  {cedis(value).replace(".00", "")}
                </span>
              );
            })}
          </div>
        </div>
        <div>
          <p className="text-2xs font-medium text-ink-soft">Mobile Money number</p>
          <div className="mt-1 flex h-10 items-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-sm">
            <CountryFlag code="GH" size="sm" />
            <span className="tabular text-ink">{EXAMPLE_PHONE}</span>
            {networkValue ? (
              <span className="ml-auto rounded-md bg-sunken px-1.5 py-0.5 text-[0.625rem] font-semibold text-ink-soft">
                {networkValue}
              </span>
            ) : null}
          </div>
        </div>
        <div className="mt-auto space-y-2 pb-2">
          <div className="flex items-center justify-between px-0.5 text-2xs">
            <span className="text-ink-muted">You pay</span>
            <span className="tabular font-semibold text-ink">{cedis(amount)}</span>
          </div>
          <div className="flex h-10 items-center justify-center rounded-full bg-primary text-caption font-semibold text-white">
            Send payment prompt
          </div>
        </div>
      </div>
      <HomeIndicator />
    </>
  );
}

/** VerifyGH waiting on the approval, and the network's own prompt over it. */
function ApproveScreen({ amount, networkLabel }: { amount: number; networkLabel?: string }) {
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="flex flex-1 flex-col items-center px-5 pt-16 text-center">
        <span className="relative flex h-11 w-11 items-center justify-center">
          <span className="absolute inset-0 animate-pulse-ring rounded-full bg-brand-400/40" />
          <span className="relative h-3 w-3 rounded-full bg-brand-500" />
        </span>
        <p className="mt-4 text-sm font-semibold text-ink">Approve on your phone</p>
        <p className="mt-1.5 text-2xs leading-relaxed text-ink-muted">
          We sent a prompt for <span className="tabular font-semibold text-ink">{cedis(amount)}</span> to{" "}
          <span className="tabular">{EXAMPLE_PHONE}</span>
          {networkLabel ? ` on ${networkLabel}` : ""}. Enter your Mobile Money PIN on your handset to
          approve it.
        </p>
      </div>
      <div className="absolute inset-0 bg-scrim/35" />
      {/* The network's prompt: a plain system dialog, not VerifyGH's screen. */}
      <div className="drop-in absolute inset-x-4 bottom-[12%] z-20 overflow-hidden rounded-2xl bg-[#f2f2f4] text-center text-black shadow-pop">
        <div className="px-4 pb-3 pt-4">
          <p className="text-caption font-semibold">Mobile Money</p>
          <p className="mt-1 text-2xs leading-snug text-black/70">
            Approve payment of <span className="tabular font-semibold text-black">{cedis(amount)}</span>. Enter
            your PIN to confirm.
          </p>
          <div className="mx-auto mt-2.5 flex h-8 items-center justify-center gap-2 rounded-lg border border-black/15 bg-white">
            {[0, 1, 2, 3].map((dot) => (
              <span key={dot} className="h-1.5 w-1.5 rounded-full bg-black/70" />
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 border-t border-black/10 text-caption">
          <span className="border-r border-black/10 py-2 text-black/50">Cancel</span>
          <span className="py-2 font-semibold text-[#0a64d8]">Send</span>
        </div>
      </div>
      <HomeIndicator />
    </div>
  );
}

/** The wallet, with the money in: the app's own toast and the balance counting up. */
function ReceivedScreen({
  amount,
  run,
  reduced,
  networkLabel,
}: {
  amount: number;
  run: boolean;
  reduced: boolean;
  networkLabel?: string;
}) {
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {run ? (
        <div className="drop-in absolute inset-x-2.5 top-1 z-20 flex items-start gap-2 rounded-2xl bg-raised p-2.5 shadow-pop ring-1 ring-line">
          <CheckCircleIcon className="mt-px h-4 w-4 shrink-0 text-success-700" />
          <span className="min-w-0">
            <span className="block text-caption font-semibold text-ink">Payment received</span>
            <span className="tabular block text-2xs text-ink-muted">{cedis(amount)} added to your wallet.</span>
          </span>
        </div>
      ) : null}
      <p className="px-3.5 pt-1 text-base font-semibold text-ink">Wallet</p>
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3.5 pt-3">
        <div className="rounded-2xl border border-line bg-surface p-3.5">
          <p className="text-2xs text-ink-muted">Available balance</p>
          <p className="tabular mt-0.5 text-[1.6rem] font-bold leading-tight text-ink">
            <span className="mr-1 text-base font-semibold text-ink-muted">GH₵</span>
            <CountUp from={EXAMPLE_START} to={EXAMPLE_START + amount} run={run} instant={reduced} />
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2 border-t border-line pt-2 text-[0.625rem]">
            <span>
              <span className="block text-ink-muted">Total added</span>
              <span className="tabular block font-semibold text-ink">
                <CountUp from={EXAMPLE_START} to={EXAMPLE_START + amount} run={run} instant={reduced} prefix="GH₵ " />
              </span>
            </span>
            <span>
              <span className="block text-ink-muted">Total spent</span>
              <span className="tabular block font-semibold text-ink">{cedis(0)}</span>
            </span>
          </div>
          <div className="mt-2.5 grid grid-cols-2 gap-1.5">
            <span className="flex h-8 items-center justify-center rounded-full bg-primary text-2xs font-semibold text-white">
              Add funds
            </span>
            <span className="flex h-8 items-center justify-center rounded-full border border-line-strong text-2xs font-medium text-ink-soft">
              Buy a number
            </span>
          </div>
        </div>
        <div>
          <p className="px-0.5 text-2xs font-medium text-ink-soft">Recent transactions</p>
          <div className="mt-1.5 divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
            <Row title="Deposit" note={networkLabel ?? "Mobile Money"} amount={signedCedis(amount, "CREDIT")} fresh={run} />
            <Row title="Deposit" note="Earlier" amount={signedCedis(EXAMPLE_START, "CREDIT")} />
          </div>
        </div>
      </div>
      <BottomNav active="wallet" />
      <HomeIndicator />
    </div>
  );
}

function Row({ title, note, amount, fresh }: { title: string; note: string; amount: string; fresh?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2 px-2.5 py-2 transition-colors duration-700", fresh && "bg-success-50")}>
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-success-50 text-success-700">
        <PlusIcon className="h-3 w-3" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-caption font-medium text-ink">{title}</span>
        <span className="block truncate text-[0.625rem] text-ink-muted">{note}</span>
      </span>
      <span className="tabular text-caption font-semibold text-success-700">{amount}</span>
    </div>
  );
}

/** Counts from `from` to `to` once `run` turns on; shows `to` at once when `instant`. */
function CountUp({
  from,
  to,
  run,
  instant,
  prefix = "",
}: {
  from: number;
  to: number;
  run: boolean;
  instant: boolean;
  prefix?: string;
}) {
  const [value, setValue] = React.useState(instant ? to : from);
  React.useEffect(() => {
    if (instant) {
      setValue(to);
      return;
    }
    if (!run) {
      setValue(from);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const delay = 450; // let the toast land first
    const tick = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - start - delay) / 900));
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(from + (to - from) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [from, to, run, instant]);
  return (
    <>
      {prefix}
      {value.toLocaleString("en-GH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    </>
  );
}

/* ------------------------------------------------------------------------ */

/**
 * Mobile Money -> VerifyGH wallet -> numbers, as three nodes joined by lines
 * the money runs along. Lit with the phone: the first node while the form is
 * filled, the first line while the prompt is approved, the rest once the
 * payment lands.
 */
function MoneyFlow({
  step,
  reduced,
  onChoose,
  amount,
  networks,
  cheapest,
}: {
  step: number;
  reduced: boolean;
  onChoose: (index: number) => void;
  amount: number;
  networks?: string[];
  cheapest: number | null;
}) {
  const nodes = [
    {
      Icon: PhoneIcon,
      title: "Mobile Money",
      body: networks?.length ? networks.join(" · ") : "Your MoMo wallet",
      chip: cedis(amount),
      lit: reduced || step >= 0,
    },
    {
      Icon: WalletIcon,
      title: "Your VerifyGH wallet",
      body: "Credited once your network confirms the payment",
      chip: `${cedis(EXAMPLE_START + amount)} balance`,
      lit: reduced || step === 2,
    },
    {
      Icon: GridIcon,
      title: "Numbers for any service",
      body: cheapest !== null ? `Spend it on any service, from ${cedis(cheapest)}` : "Spend it on any service in the catalogue",
      chip: "Ready to buy",
      lit: reduced || step === 2,
    },
  ];
  // Which line carries money right now: the first while the prompt is approved, the second once it lands.
  const flowing = reduced ? -1 : step === 1 ? 0 : step === 2 ? 1 : -1;

  return (
    <ol className="mt-8" aria-label="Where the money goes">
      {nodes.map((node, index) => (
        <li key={node.title}>
          <button
            type="button"
            onClick={() => onChoose(index === 0 ? 0 : 2)}
            className={cn(
              "flex w-full items-center gap-3.5 rounded-2xl border p-3 text-left transition-all duration-500",
              node.lit
                ? "border-line bg-surface shadow-card"
                : "border-transparent bg-surface/40 opacity-70 hover:opacity-100",
            )}
          >
            <span
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-colors duration-500",
                node.lit
                  ? "bg-linear-to-br from-[#0B63B6] to-[#137A4E] text-white shadow-[0_8px_20px_-8px_rgba(8,120,209,0.7)]"
                  : "bg-sunken text-ink-muted",
              )}
            >
              <node.Icon className="h-5 w-5" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-ink">{node.title}</span>
              <span className="block text-caption leading-snug text-ink-muted">{node.body}</span>
            </span>
            <span className="tabular hidden shrink-0 rounded-full bg-sunken px-2.5 py-1 text-2xs font-semibold text-ink-soft sm:block">
              {node.chip}
            </span>
          </button>

          {index < nodes.length - 1 ? (
            <svg aria-hidden viewBox="0 0 24 36" className="ml-[1.9rem] h-9 w-6 overflow-visible">
              <defs>
                <linearGradient id={`flow-${index}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#0878D1" />
                  <stop offset="1" stopColor="#20B26B" />
                </linearGradient>
              </defs>
              <line x1="12" y1="0" x2="12" y2="36" className="stroke-line-strong" strokeWidth="2" />
              {flowing === index ? (
                <>
                  <line x1="12" y1="0" x2="12" y2="36" stroke={`url(#flow-${index})`} strokeWidth="6" opacity="0.25" />
                  <line className="flow-dash" x1="12" y1="0" x2="12" y2="36" stroke={`url(#flow-${index})`} strokeWidth="2.5" strokeLinecap="round" />
                </>
              ) : null}
            </svg>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
