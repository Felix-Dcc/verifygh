"use client";

import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { CheckCircleIcon, ClockIcon, CopyIcon, MessageIcon, PhoneIcon, SearchIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome, MarketRow } from "@/lib/types";

import { BottomNav, Device, Halo, HomeIndicator, Reveal, ScreenStack, StatusBar, useInView, useStory } from "./device";

/**
 * How it works, as a mini product demo: the four steps on one side drive a
 * phone on the other - choose a service from today's catalogue, get a US
 * number, wait for the SMS, read the code as it fills in. It plays on its
 * own while on screen; choosing a step takes over.
 *
 * Live: the services, their logos and prices. Invented, and only these: the
 * number (from the 555 range kept for fiction), the countdown and the code.
 */

const STEP_MS = 4400;
const EXAMPLE_NUMBER = "+1 (512) 555-0147";
const EXAMPLE_CODE = "482196";
/** The story follows TikTok; its bundled tile stands in until the catalogue answers. Prices never do. */
const SUBJECT_ICON = "/service-icons/tiktok.svg";

const STEPS = [
  {
    title: "Choose your service",
    body: "Pick the app you are signing up to from the live catalogue. Every price is in cedis, before you buy.",
  },
  {
    title: "Get your number",
    body: "Pay from your wallet and a US number is assigned to your order. Enter it in the app and ask for the code.",
  },
  {
    title: "Wait for your code",
    body: "Keep the order open. The SMS lands on it the moment the app sends it - no refreshing, no inbox to check.",
  },
  {
    title: "Verify",
    body: "Copy the code into the app and you are in. If no code arrives before the number expires, you get the full price back.",
  },
];

export function HowItWorks() {
  const { data } = useSWR<MarketHome>("/marketplace/home/");
  const popular = (data?.popular ?? []).filter((row) => !row.temporarily_unavailable);
  const featured = popular.find((row) => row.slug === "tiktok") ?? popular[0];
  const [ref, inView] = useInView<HTMLElement>();
  const story = useStory(STEPS.length, inView, STEP_MS);

  return (
    // overflow-x-clip: the halo is wider than a phone screen. Clip, not hidden,
    // so nothing inside becomes a scroll container.
    <section ref={ref} id="how-it-works" className="scroll-mt-20 overflow-x-clip" aria-labelledby="how-heading">
      {/* Phones read heading, phone, steps. From lg the heading and steps share
          the left column, centred as a group against the phone. */}
      <div className="container-page grid grid-cols-1 gap-x-16 gap-y-8 py-16 sm:py-24 lg:grid-cols-2 lg:grid-rows-[1fr_auto_auto_1fr] lg:gap-y-6">
        <Reveal className="text-center lg:col-start-1 lg:row-start-2 lg:text-left">
          <h2 id="how-heading" className="section-title">
            How VerifyGH works
          </h2>
          <p className="section-lead mx-auto max-w-lg lg:mx-0">
            From choosing a service to reading your code, on one screen. Here it is, step by step.
          </p>
        </Reveal>

        <Reveal className="lg:col-start-2 lg:row-span-4 lg:row-start-1 lg:self-center">
          <Demo step={story.index} featured={featured} rows={popular} loading={!data} />
        </Reveal>

        <Reveal className="mx-auto w-full max-w-xl lg:col-start-1 lg:row-start-3 lg:max-w-none">
          <ol className="relative space-y-1" aria-label="Steps">
            {/* The rail the steps hang on */}
            <span aria-hidden className="absolute bottom-6 left-[1.5rem] top-6 w-px bg-line" />
            {STEPS.map((step, index) => {
              const active = index === story.index;
              const done = index < story.index;
              return (
                <li key={step.title} className="relative">
                  <button
                    type="button"
                    onClick={() => story.choose(index)}
                    aria-current={active ? "step" : undefined}
                    className={cn(
                      "group flex w-full gap-4 rounded-2xl px-2 py-3 text-left transition-colors",
                      active ? "bg-surface shadow-card" : "hover:bg-sunken/60",
                    )}
                  >
                    <span
                      className={cn(
                        "tabular relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-caption font-bold transition-colors duration-500",
                        active
                          ? "bg-gradient-to-br from-[#0B63B6] to-[#137A4E] text-white"
                          : done
                            ? "bg-brand-50 text-brand-700"
                            : "border border-line-strong bg-canvas text-ink-muted",
                      )}
                    >
                      {done ? <CheckCircleIcon className="h-4 w-4" /> : String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="min-w-0 flex-1 pt-1">
                      <span className={cn("block text-base font-semibold transition-colors", active ? "text-ink" : "text-ink-soft")}>
                        {step.title}
                      </span>
                      {/* The body opens for the active step only - the phone shows the rest. */}
                      <span
                        className={cn(
                          "grid transition-[grid-template-rows] duration-500 ease-out motion-reduce:transition-none",
                          active ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
                        )}
                      >
                        <span className="overflow-hidden">
                          <span className="block pt-1 text-sm leading-relaxed text-ink-muted">{step.body}</span>
                          {active && story.playing ? (
                            <span aria-hidden className="mt-3 block h-0.5 overflow-hidden rounded-full bg-line">
                              <span
                                key={story.index}
                                className="story-progress block h-full origin-left rounded-full bg-gradient-to-r from-azure to-leaf"
                                style={{ ["--story-interval" as string]: `${STEP_MS}ms` }}
                              />
                            </span>
                          ) : null}
                        </span>
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </Reveal>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------ */

function Demo({
  step,
  featured,
  rows,
  loading,
}: {
  step: number;
  featured?: MarketRow;
  rows: MarketRow[];
  loading: boolean;
}) {
  const name = featured?.name ?? "TikTok";
  const events = [
    {
      icon: <ServiceLogo name={name} src={featured?.icon_url ?? SUBJECT_ICON} slug={featured?.slug ?? "tiktok"} size="xs" />,
      title: `${name} selected`,
      note: featured?.price ? `${cedis(featured.price)} · United States` : "United States",
    },
    { icon: <Bubble><PhoneIcon className="h-3.5 w-3.5" /></Bubble>, title: "Number assigned", note: EXAMPLE_NUMBER },
    { icon: <Bubble><MessageIcon className="h-3.5 w-3.5" /></Bubble>, title: "SMS received", note: `From ${name}` },
    { icon: <Bubble tone="success"><CheckCircleIcon className="h-3.5 w-3.5" /></Bubble>, title: "Code received", note: EXAMPLE_CODE },
  ];

  return (
    <div className="relative mx-auto flex w-full max-w-md justify-center pb-6 pt-2" aria-hidden>
      <Halo className="left-1/2 top-1/2 h-[115%] w-[135%] -translate-x-1/2 -translate-y-1/2" />

      <Device>
        <StatusBar />
        <ScreenStack active={step}>
          <ChooseScreen rows={rows} featured={featured} loading={loading} />
          <NumberScreen featured={featured} />
          <WaitScreen featured={featured} arrived={step === 2} />
          <VerifyScreen featured={featured} run={step === 3} />
        </ScreenStack>
      </Device>

      {/* What just happened, narrated at the phone's edge */}
      <div className="absolute bottom-0 left-0 z-20 sm:-left-2">
        <div key={step} className="rise-in flex items-center gap-2.5 rounded-2xl bg-white py-2.5 pl-2.5 pr-4 text-left shadow-pop">
          {events[step].icon}
          <span className="min-w-0">
            <span className="tabular block text-sm font-semibold leading-tight text-black">{events[step].title}</span>
            <span className="tabular block text-2xs text-black/60">{events[step].note}</span>
          </span>
        </div>
      </div>
    </div>
  );
}

function Bubble({ children, tone = "brand" }: { children: React.ReactNode; tone?: "brand" | "success" }) {
  return (
    <span
      className={cn(
        "flex h-7 w-7 items-center justify-center rounded-full",
        tone === "success" ? "bg-[#E6F4EC] text-[#1C7A4A]" : "bg-[#E7F1FB] text-[#0B63B6]",
      )}
    >
      {children}
    </span>
  );
}

function ServiceHeader({ featured }: { featured?: MarketRow }) {
  const name = featured?.name ?? "TikTok";
  return (
    <div className="flex items-center gap-2.5 px-0.5">
      <ServiceLogo name={name} src={featured?.icon_url ?? SUBJECT_ICON} slug={featured?.slug ?? "tiktok"} size="xs" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold leading-tight text-ink">{name}</p>
        <p className="flex items-center gap-1 text-2xs text-ink-muted">
          <CountryFlag code="US" size="sm" /> United States
        </p>
      </div>
    </div>
  );
}

/** 01 - the catalogue as a grid of tiles, the chosen one being tapped. */
function ChooseScreen({ rows, featured, loading }: { rows: MarketRow[]; featured?: MarketRow; loading: boolean }) {
  const tiles = featured ? [featured, ...rows.filter((row) => row.slug !== featured.slug)].slice(0, 6) : [];
  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col px-3.5 pt-2">
        <p className="px-0.5 text-base font-semibold text-ink">Buy a number</p>
        <div className="mt-2 flex h-8 items-center gap-2 rounded-full border border-line-strong bg-surface px-3 text-2xs text-ink-faint">
          <SearchIcon className="h-3 w-3" />
          Search services
        </div>
        <p className="mt-3 px-0.5 text-2xs font-medium uppercase tracking-wide text-ink-muted">Popular</p>
        <div className="mt-1.5 grid grid-cols-2 gap-1.5">
          {loading || tiles.length === 0
            ? [0, 1, 2, 3, 4, 5].map((key) => <Skeleton key={key} className="h-[4.25rem] rounded-xl" />)
            : tiles.map((row, index) => (
                <div
                  key={row.slug}
                  className={cn(
                    "relative flex flex-col gap-1.5 rounded-xl border p-2",
                    index === 0 ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500" : "border-line bg-surface",
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="xs" className="!h-6 !w-6" />
                    <span className="min-w-0 truncate text-[0.6875rem] font-semibold text-ink">{row.name}</span>
                  </div>
                  <span className="tabular text-caption font-bold text-ink">{cedis(row.price)}</span>
                  {index === 0 ? (
                    <span className="absolute right-2 top-2 h-7 w-7">
                      <span className="tap-ring absolute inset-0 rounded-full bg-brand-500/40" />
                      <span className="absolute inset-2 rounded-full bg-brand-500/50" />
                    </span>
                  ) : null}
                </div>
              ))}
        </div>
      </div>
      <BottomNav active="buy" />
      <HomeIndicator />
    </>
  );
}

/** 02 - the number, large, ready to enter in the app. */
function NumberScreen({ featured }: { featured?: MarketRow }) {
  const name = featured?.name ?? "TikTok";
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3.5 pt-2">
        <ServiceHeader featured={featured} />
        <div className="rounded-2xl border border-line bg-surface p-3.5">
          <div className="flex items-center justify-between">
            <p className="text-2xs text-ink-muted">Your number</p>
            <span className="rounded-full bg-success-50 px-2 py-0.5 text-[0.5625rem] font-bold uppercase tracking-wider text-success-700">
              Ready
            </span>
          </div>
          <p className="code mt-1.5 text-[1.2rem] font-semibold leading-tight text-ink">{EXAMPLE_NUMBER}</p>
          <div className="mt-3 flex items-center justify-between">
            <span className="flex items-center gap-1 text-2xs text-ink-soft">
              <ClockIcon className="h-3 w-3" />
              <span className="tabular font-semibold">19:58</span> left
            </span>
            <span className="flex items-center gap-1 rounded-full border border-line-strong px-2.5 py-1 text-[0.625rem] font-medium text-ink-soft">
              <CopyIcon className="h-3 w-3" /> Copy
            </span>
          </div>
        </div>
        <p className="px-1 text-2xs leading-relaxed text-ink-muted">
          Enter this number in {name} and ask it to send the code.
        </p>
      </div>
      <HomeIndicator />
    </div>
  );
}

/** 03 - waiting, then the SMS landing on the order. */
function WaitScreen({ featured, arrived }: { featured?: MarketRow; arrived: boolean }) {
  const name = featured?.name ?? "TikTok";
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3.5 pt-2">
        <ServiceHeader featured={featured} />
        <div className="rounded-2xl border border-line bg-surface p-3.5">
          <p className="text-2xs text-ink-muted">Your number</p>
          <p className="code mt-1 text-[0.95rem] font-semibold text-ink">{EXAMPLE_NUMBER}</p>
        </div>
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-line-strong px-3 py-6 text-center">
          <span className="relative flex h-10 w-10 items-center justify-center">
            <span className="absolute inset-0 animate-pulse-ring rounded-full bg-azure/30" />
            <span className="relative h-2.5 w-2.5 rounded-full bg-azure" />
          </span>
          <p className="mt-3 text-caption font-semibold text-ink">Waiting for the SMS</p>
          <p className="mt-0.5 text-[0.625rem] text-ink-muted">The code appears here the moment it arrives.</p>
        </div>
      </div>
      {arrived ? (
        <div
          className="drop-in absolute inset-x-2.5 top-1 z-20 rounded-2xl bg-raised p-3 shadow-pop ring-1 ring-line"
          style={{ animationDelay: "1400ms" }}
        >
          <p className="flex items-center gap-1.5 text-[0.5625rem] font-bold uppercase tracking-[0.12em] text-azure">
            <MessageIcon className="h-3 w-3" /> SMS received · {name}
          </p>
          <p className="mt-1 text-[0.6875rem] leading-snug text-ink-soft">
            Your {name} code is {EXAMPLE_CODE}. Don&apos;t share it with anyone.
          </p>
        </div>
      ) : null}
      <HomeIndicator />
    </div>
  );
}

/** 04 - the code filling in digit by digit, then received. */
function VerifyScreen({ featured, run }: { featured?: MarketRow; run: boolean }) {
  const name = featured?.name ?? "TikTok";
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3.5 pt-2">
        <ServiceHeader featured={featured} />
        <div className="rounded-2xl border border-success-200 bg-success-50 p-3.5">
          <p className="text-2xs font-medium text-success-700">Verification code</p>
          <div key={run ? "run" : "rest"} className="mt-2 grid grid-cols-6 gap-1">
            {EXAMPLE_CODE.split("").map((digit, index) => (
              <span
                key={index}
                className="rise-in code flex h-9 items-center justify-center rounded-lg border border-success-200 bg-surface text-base font-semibold text-success-700"
                style={{ animationDelay: `${200 + index * 180}ms` }}
              >
                {digit}
              </span>
            ))}
          </div>
          <p
            key={run ? "ok" : "rest-ok"}
            className="rise-in mt-3 flex items-center gap-1.5 text-caption font-semibold text-success-700"
            style={{ animationDelay: "1400ms" }}
          >
            <CheckCircleIcon className="h-4 w-4" /> Code received
          </p>
        </div>
        <p className="px-1 text-2xs leading-relaxed text-ink-muted">Copy it into {name} to finish signing up.</p>
        <div className="mt-auto pb-2">
          <div className="flex h-10 items-center justify-center gap-1.5 rounded-full bg-primary text-caption font-semibold text-white">
            <CopyIcon className="h-3.5 w-3.5" />
            Copy code
          </div>
        </div>
      </div>
      <HomeIndicator />
    </div>
  );
}
