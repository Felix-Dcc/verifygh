"use client";

import useSWR from "swr";

import { ServiceLogo } from "@/components/service-logo";
import { Skeleton } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome } from "@/lib/types";

/**
 * Four steps, each beside a small drawing of the screen where it happens -
 * the product explaining itself rather than stock illustrations. Step three
 * shows today's real popular services and prices.
 */
const STEPS = [
  {
    title: "Create your account",
    body: "An email address and a password. Confirm the email and you can buy.",
  },
  {
    title: "Add funds with MoMo",
    body: "Approve the payment prompt on your phone. Your balance updates once the network confirms it.",
  },
  {
    title: "Choose a service",
    body: "Search the catalogue. Every service shows its price in cedis before you buy.",
  },
  {
    title: "Receive your number and SMS",
    body: "Use the number on the service, and the code appears on your order. No code, full refund.",
  },
];

export function HowItWorks() {
  const { data } = useSWR<MarketHome>("/marketplace/home/");
  const popular = (data?.popular ?? []).filter((row) => !row.temporarily_unavailable).slice(0, 3);

  const art = [<AccountArt key="a" />, <MomoArt key="m" />, <ChooseArt key="c" rows={popular} loading={!data} />, <CodeArt key="n" />];

  return (
    <section id="how-it-works" className="container-page scroll-mt-20 py-16 sm:py-24">
      <div className="max-w-2xl">
        <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">How VerifyGH works</h2>
        <p className="mt-3 text-base text-ink-muted">
          From sign-up to your first code in a few minutes, paid for in cedis.
        </p>
      </div>
      <ol className="mt-12 grid grid-cols-1 gap-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
        {STEPS.map((step, index) => (
          <li key={step.title} className="flex flex-col">
            <div aria-hidden className="h-40">
              {art[index]}
            </div>
            <p className="tabular mt-5 text-sm font-semibold text-brand-700">
              {String(index + 1).padStart(2, "0")}
            </p>
            <h3 className="mt-1 text-heading text-ink">{step.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col justify-center rounded-xl border border-line bg-surface p-4 shadow-card">
      {children}
    </div>
  );
}

function AccountArt() {
  return (
    <Frame>
      <p className="text-caption font-semibold text-ink">Create your account</p>
      <div className="mt-2.5 flex h-8 items-center rounded-md border border-line-strong px-2.5 text-caption text-ink-muted">
        you@example.com
      </div>
      <div className="mt-1.5 flex h-8 items-center rounded-md border border-line-strong px-2.5 text-caption tracking-widest text-ink-muted">
        ••••••••••
      </div>
      <div className="mt-2.5 flex h-8 items-center justify-center rounded-md bg-primary text-caption font-medium text-white">
        Create account
      </div>
    </Frame>
  );
}

function MomoArt() {
  return (
    <Frame>
      <div className="flex items-center justify-between">
        <p className="text-caption font-semibold text-ink">Payment request</p>
        <span className="rounded-md bg-sunken px-1.5 py-0.5 text-2xs font-medium text-ink-soft">MoMo</span>
      </div>
      <p className="tabular mt-3 text-title font-semibold text-ink">GH₵ 50.00</p>
      <p className="text-caption text-ink-muted">to VerifyGH</p>
      <div className="mt-3 flex items-center gap-2 rounded-md bg-brand-50 px-2.5 py-1.5 text-2xs font-medium text-brand-700">
        <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
        Approve with your PIN on your phone
      </div>
    </Frame>
  );
}

function ChooseArt({ rows, loading }: { rows: MarketHome["popular"]; loading: boolean }) {
  return (
    <Frame>
      <ul className="divide-y divide-line">
        {(loading || rows.length === 0 ? [null, null, null] : rows).map((row, index) => (
          <li key={row?.slug ?? index} className="flex h-10 items-center gap-2.5">
            {row ? (
              <>
                <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="xs" />
                <span className="min-w-0 flex-1 truncate text-caption font-medium text-ink">{row.name}</span>
                <span className="tabular text-caption text-ink-soft">{row.price ? cedis(row.price) : "—"}</span>
              </>
            ) : (
              <>
                <Skeleton className="h-7 w-7 rounded-lg" />
                <Skeleton className="h-3 flex-1" />
                <Skeleton className="h-3 w-12" />
              </>
            )}
          </li>
        ))}
      </ul>
    </Frame>
  );
}

function CodeArt() {
  return (
    <Frame>
      <p className="text-2xs text-ink-muted">Your number</p>
      <p className="tabular text-sm font-semibold text-ink">+1 (512) 555-0147</p>
      <div className="mt-3 rounded-md border border-success-200 bg-success-50 px-2.5 py-2">
        <p className="text-2xs text-success-700">Verification code</p>
        <p className="code text-heading tracking-widest text-success-700">482913</p>
      </div>
    </Frame>
  );
}
