"use client";

import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { CheckCircleIcon, ClockIcon, CopyIcon, PhoneIcon, SearchIcon, WalletIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome, MarketRow } from "@/lib/types";

import { BottomNav, Device, Halo, HomeIndicator, Reveal, ScreenStack, StatusBar, useInView, useStory } from "./device";

/**
 * How it works, as one order watched from start to finish. The steps on the
 * left drive the phone on the right: the marketplace, the buy sheet, the order
 * with its number, then the code arriving - the real screens, with today's
 * real service and price. It plays on its own while on screen; choosing a
 * step takes over.
 *
 * Invented, and only these: the example wallet balance, the number (from the
 * 555 range kept for fiction), the countdown and the code.
 */

const STEP_MS = 4200;
const EXAMPLE_BALANCE = 50;
const EXAMPLE_NUMBER = "+1 (512) 555-0147";
const EXAMPLE_CODE = "482913";
/** The story follows TikTok; its bundled tile stands in until the catalogue answers. Prices never do. */
const SUBJECT_ICON = "/service-icons/tiktok.svg";

const STEPS = [
  {
    title: "Choose a service",
    body: "Search for the app you are signing up to. Every service shows its price in cedis before you buy.",
  },
  {
    title: "Pay with your wallet",
    body: "The price comes out of your VerifyGH balance, which you top up with MoMo. Nothing is added at checkout.",
  },
  {
    title: "Receive your number",
    body: "A US number is assigned to your order. Enter it in the app and ask it to send the code.",
  },
  {
    title: "Get your SMS code",
    body: "The code appears on your order the moment it arrives. If none arrives before the number expires, you get the full price back.",
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
          the left column, centred as a group (the 1fr rows either side take up
          the slack) against the phone, which spans every row on the right. */}
      <div className="container-page grid grid-cols-1 gap-x-16 gap-y-8 py-16 sm:py-24 lg:grid-cols-2 lg:grid-rows-[1fr_auto_auto_1fr] lg:gap-y-6">
        <Reveal className="text-center lg:col-start-1 lg:row-start-2 lg:text-left">
          <h2 id="how-heading" className="section-title">
            How VerifyGH works
          </h2>
          <p className="section-lead mx-auto max-w-lg lg:mx-0">
            One order, from choosing a service to reading the code - the way it looks on your
            phone.
          </p>
        </Reveal>

        <Reveal className="lg:col-start-2 lg:row-span-4 lg:row-start-1 lg:self-center">
          <Journey step={story.index} featured={featured} rows={popular} loading={!data} />
        </Reveal>

        <Reveal className="mx-auto w-full max-w-xl lg:col-start-1 lg:row-start-3 lg:max-w-none">
          <ol className="relative space-y-1" aria-label="Steps">
            {/* The rail the steps hang on */}
            <span aria-hidden className="absolute bottom-6 left-[1.5rem] top-6 w-px bg-line" />
            {STEPS.map((step, index) => {
              const active = index === story.index;
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
                        "tabular relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-caption font-bold transition-colors",
                        active ? "bg-primary text-white" : "border border-line-strong bg-canvas text-ink-muted",
                      )}
                    >
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="min-w-0 flex-1 pt-1">
                      <span
                        className={cn(
                          "block text-base font-semibold transition-colors",
                          active ? "text-ink" : "text-ink-soft",
                        )}
                      >
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
                                className="story-progress block h-full origin-left rounded-full bg-brand-500"
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

function Journey({
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
  const price = featured?.price ? Number.parseFloat(featured.price) : null;
  const name = featured?.name ?? "TikTok";

  // What just happened, narrated beside the phone.
  const events = [
    {
      icon: <ServiceLogo name={name} src={featured?.icon_url ?? SUBJECT_ICON} slug={featured?.slug ?? "tiktok"} size="xs" />,
      title: `${name} selected`,
      note: "United States",
    },
    {
      icon: (
        <Bubble>
          <WalletIcon className="h-3.5 w-3.5" />
        </Bubble>
      ),
      title: price !== null ? `${cedis(price)} paid` : "Paid",
      note: "From your wallet",
    },
    {
      icon: (
        <Bubble>
          <PhoneIcon className="h-3.5 w-3.5" />
        </Bubble>
      ),
      title: "Number assigned",
      note: EXAMPLE_NUMBER,
    },
    {
      icon: (
        <Bubble tone="success">
          <CheckCircleIcon className="h-3.5 w-3.5" />
        </Bubble>
      ),
      title: "Code received",
      note: EXAMPLE_CODE,
    },
  ];

  return (
    <div className="relative mx-auto flex w-full max-w-md justify-center pb-6 pt-2" aria-hidden>
      <Halo className="left-1/2 top-1/2 h-[115%] w-[135%] -translate-x-1/2 -translate-y-1/2" />

      <Device>
        <StatusBar />
        <ScreenStack active={step}>
          <BrowseScreen rows={rows} featured={featured} loading={loading} />
          <PayScreen rows={rows} featured={featured} price={price} />
          <OrderScreen featured={featured} code={false} />
          <OrderScreen featured={featured} code />
        </ScreenStack>
      </Device>

      {/* The narration: slides in afresh at every step. */}
      <div className="absolute bottom-0 left-0 z-20 sm:-left-2">
        <div
          key={step}
          className="rise-in flex items-center gap-2.5 rounded-2xl bg-white py-2.5 pl-2.5 pr-4 text-left shadow-pop"
        >
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
        tone === "success" ? "bg-[#E6F4EC] text-[#1C7A4A]" : "bg-[#E8F3EE] text-[#0B6446]",
      )}
    >
      {children}
    </span>
  );
}

/** The marketplace on a phone, with the featured service being tapped. */
function BrowseScreen({ rows, featured, loading }: { rows: MarketRow[]; featured?: MarketRow; loading: boolean }) {
  const list = featured ? [featured, ...rows.filter((row) => row.slug !== featured.slug)].slice(0, 5) : [];
  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col px-3.5 pt-2">
        <p className="px-0.5 text-base font-semibold text-ink">Buy a number</p>
        <div className="mt-2 flex h-8 items-center gap-2 rounded-full border border-line-strong bg-surface px-3 text-2xs text-ink-faint">
          <SearchIcon className="h-3 w-3" />
          Search - WhatsApp, TikTok…
        </div>
        <p className="mt-3 px-0.5 text-2xs font-medium uppercase tracking-wide text-ink-muted">Popular</p>
        <ul className="mt-1.5 space-y-1.5">
          {loading || list.length === 0
            ? [0, 1, 2, 3].map((key) => (
                <li key={key} className="flex h-11 items-center gap-2 rounded-xl bg-surface px-2">
                  <Skeleton className="h-7 w-7 rounded-lg" />
                  <Skeleton className="h-2.5 flex-1" />
                </li>
              ))
            : list.map((row, index) => (
                <li
                  key={row.slug}
                  className={cn(
                    "relative flex h-11 items-center gap-2 rounded-xl border px-2",
                    index === 0 ? "border-brand-500 bg-brand-50" : "border-line bg-surface",
                  )}
                >
                  <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="xs" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-caption font-semibold text-ink">{row.name}</span>
                    <span className="block text-[0.625rem] text-ink-muted">
                      {row.available_count ? `${row.available_count} available` : "Available"}
                    </span>
                  </span>
                  <span className="tabular text-caption font-semibold text-ink">{cedis(row.price)}</span>
                  {index === 0 ? (
                    <span className="absolute left-[55%] top-1/2 h-8 w-8 -translate-y-1/2">
                      <span className="tap-ring absolute inset-0 rounded-full bg-brand-500/40" />
                      <span className="absolute inset-2.5 rounded-full bg-brand-500/50" />
                    </span>
                  ) : null}
                </li>
              ))}
        </ul>
      </div>
      <BottomNav active="buy" />
      <HomeIndicator />
    </>
  );
}

/** The buy sheet over the marketplace, as the real one lays it out. */
function PayScreen({ rows, featured, price }: { rows: MarketRow[]; featured?: MarketRow; price: number | null }) {
  const balance = price !== null && price > EXAMPLE_BALANCE ? Math.ceil(price / 50) * 50 + 50 : EXAMPLE_BALANCE;
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {/* The marketplace, dimmed behind the sheet */}
      <div className="flex-1 space-y-1.5 px-3.5 pt-2 opacity-40">
        <p className="px-0.5 text-base font-semibold text-ink">Buy a number</p>
        {rows.slice(0, 3).map((row) => (
          <div key={row.slug} className="flex h-11 items-center gap-2 rounded-xl border border-line bg-surface px-2">
            <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="xs" />
            <span className="text-caption font-semibold text-ink">{row.name}</span>
          </div>
        ))}
      </div>
      <div className="absolute inset-0 bg-scrim/40" />

      <div className="absolute inset-x-0 bottom-0 rounded-t-3xl bg-raised px-3.5 pt-2.5 shadow-pop">
        <span className="mx-auto block h-1 w-8 rounded-full bg-line-strong" />
        <p className="mt-2.5 text-sm font-semibold text-ink">Buy a number</p>
        <div className="mt-2 flex items-center gap-2">
          <ServiceLogo name={featured?.name ?? "TikTok"} src={featured?.icon_url ?? SUBJECT_ICON} slug={featured?.slug ?? "tiktok"} size="xs" />
          <span className="min-w-0">
            <span className="block text-caption font-semibold text-ink">{featured?.name ?? "TikTok"}</span>
            <span className="block text-[0.625rem] text-ink-muted">One-time number for an SMS code</span>
          </span>
        </div>
        <dl className="mt-2.5 divide-y divide-line rounded-xl border border-line text-2xs">
          <Line label="Country">
            <span className="flex items-center gap-1">
              <CountryFlag code="US" size="sm" /> United States
            </span>
          </Line>
          <Line label="Number price" strong>
            {cedis(price)}
          </Line>
          <Line label="Current balance">{cedis(balance)}</Line>
          <Line label="After purchase" strong>
            {price !== null ? cedis(balance - price) : "—"}
          </Line>
        </dl>
        <div className="mt-2.5 grid grid-cols-[auto_1fr] gap-2">
          <span className="flex h-9 items-center rounded-full border border-line-strong px-3.5 text-2xs font-medium text-ink-soft">
            Cancel
          </span>
          <span className="tabular flex h-9 items-center justify-center rounded-full bg-primary text-2xs font-semibold text-white">
            Buy for {cedis(price)}
          </span>
        </div>
        <HomeIndicator />
      </div>
    </div>
  );
}

function Line({ label, strong, children }: { label: string; strong?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between px-2.5 py-1.5">
      <dt className="text-ink-muted">{label}</dt>
      <dd className={cn("tabular", strong ? "font-semibold text-ink" : "text-ink-soft")}>{children}</dd>
    </div>
  );
}

/** The order: waiting for the SMS, then the code - with the app's own toast when it lands. */
function OrderScreen({ featured, code }: { featured?: MarketRow; code: boolean }) {
  const name = featured?.name ?? "TikTok";
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {code ? (
        <div className="drop-in absolute inset-x-2.5 top-1 z-20 flex items-start gap-2 rounded-2xl bg-raised p-2.5 shadow-pop ring-1 ring-line">
          <CheckCircleIcon className="mt-px h-4 w-4 shrink-0 text-success-700" />
          <span className="min-w-0">
            <span className="block text-caption font-semibold text-ink">Verification code received</span>
            <span className="block text-2xs text-ink-muted">It is on your order screen now.</span>
          </span>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col gap-2.5 px-3.5 pt-2">
        <div className="flex items-center gap-2.5 px-0.5">
          <ServiceLogo name={name} src={featured?.icon_url ?? SUBJECT_ICON} slug={featured?.slug ?? "tiktok"} size="xs" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-tight text-ink">{name}</p>
            <p className="flex items-center gap-1 text-2xs text-ink-muted">
              <CountryFlag code="US" size="sm" /> United States
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-line bg-surface p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-2xs text-ink-muted">Your number</p>
            <span className="flex items-center gap-1 rounded-md bg-sunken px-1.5 py-0.5 text-2xs text-ink-soft">
              <ClockIcon className="h-3 w-3" />
              <span className="tabular font-semibold">{code ? "18:41" : "19:58"}</span>
            </span>
          </div>
          <p className="code mt-1 text-[0.95rem] font-semibold text-ink">{EXAMPLE_NUMBER}</p>
        </div>

        {code ? (
          <div className="rounded-xl border border-success-200 bg-success-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-2xs font-medium text-success-700">Verification code</p>
              <span className="rounded-full bg-surface px-2 py-0.5 text-[0.625rem] font-medium text-success-700">
                Code received
              </span>
            </div>
            <p className="code mt-0.5 text-[1.7rem] font-semibold leading-tight tracking-[0.18em] text-success-700">
              {EXAMPLE_CODE}
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-line bg-surface p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-2xs text-ink-muted">Verification code</p>
              <span className="rounded-full bg-info-50 px-2 py-0.5 text-[0.625rem] font-medium text-info-700">
                Waiting for SMS
              </span>
            </div>
            <div className="mt-2 flex items-start gap-2">
              <span className="relative mt-1 flex h-2 w-2 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-brand-400" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-500" />
              </span>
              <p className="text-2xs leading-snug text-ink-soft">
                Waiting for the SMS. The code appears here the moment it arrives.
              </p>
            </div>
          </div>
        )}

        <div className="mt-auto pb-2">
          <div
            className={cn(
              "flex h-9 items-center justify-center gap-1.5 rounded-full text-caption font-medium",
              code ? "bg-primary text-white" : "border border-line-strong text-ink-soft",
            )}
          >
            <CopyIcon className="h-3.5 w-3.5" />
            {code ? "Copy code" : "Copy number"}
          </div>
        </div>
      </div>
      <HomeIndicator />
    </div>
  );
}
