"use client";

import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { ArrowRightIcon, CheckIcon, LockIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome, MarketRow } from "@/lib/types";

import { Reveal } from "./device";

/**
 * Price transparency, shown rather than tabled: one service's price large, as
 * a receipt that proves the price is what leaves the wallet, with the cedi
 * sign set huge behind it and today's other prices around it.
 *
 * Every price is live from the public catalogue - the same numbers the
 * marketplace charges. The provider's own cost is not public, so it is not
 * shown; what goes into a price is described, not quantified.
 */

const PARTS = [
  { label: "Provider cost", note: "What our provider charges us for the number, in US dollars." },
  { label: "Exchange rate", note: "Converted to cedis at our published rate, fixed when you buy." },
  { label: "Our margin", note: "How VerifyGH pays for itself." },
  {
    label: "Collection and failure costs",
    note: "Mobile Money collection and the cost of orders that fail, where they apply.",
  },
];

/** Where the other prices sit around the receipt from lg up (percent of the stage). */
const TAG_SLOTS = [
  { left: "2%", top: "10%", delay: 0 },
  { left: "8%", top: "44%", delay: 1.4 },
  { left: "0%", top: "76%", delay: 0.7 },
  { right: "2%", top: "14%", delay: 2.0 },
  { right: "7%", top: "48%", delay: 0.3 },
  { right: "0%", top: "80%", delay: 1.1 },
];

export function PricingSection() {
  const { data, error } = useSWR<MarketHome>("/marketplace/home/");
  const popular = (data?.popular ?? []).filter((row) => !row.temporarily_unavailable && row.price);
  const featured = popular.find((row) => row.slug === "tiktok") ?? popular[0];
  const others = popular.filter((row) => row.slug !== featured?.slug).slice(0, TAG_SLOTS.length);
  const prices = popular.map((row) => Number.parseFloat(row.price ?? "")).filter((value) => value > 0);
  const cheapest = prices.length ? Math.min(...prices) : null;

  return (
    <section id="pricing" className="relative scroll-mt-20 overflow-x-clip py-16 sm:py-24" aria-labelledby="pricing-heading">
      <div className="container-page">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 id="pricing-heading" className="section-title">
            One price per number. No surprises.
          </h2>
          <p className="section-lead">
            You see the price in Ghana cedis before you buy, and that price is exactly what leaves
            your wallet.
          </p>
        </Reveal>

        <Reveal>
          <div className="relative mx-auto mt-10 max-w-5xl lg:mt-6 lg:h-136">
            <div className="relative flex justify-center lg:h-full lg:items-center">
              {/* The cedi sign, set huge behind the receipt - wider than it, so
                  the glyph shows either side even on a phone. */}
              <span
                aria-hidden
                className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 select-none whitespace-nowrap text-[12rem] font-bold leading-none tracking-tighter text-brand-100 sm:text-[15rem] lg:text-[20rem]"
              >
                GH₵
              </span>

              {featured ? (
                <Receipt row={featured} country={data?.country ?? "US"} />
              ) : error ? (
                <div className="card relative w-full max-w-xs p-6 text-center">
                  <p className="text-sm font-medium text-ink">Prices are not available right now.</p>
                  <p className="mt-1 text-sm text-ink-muted">They appear here as soon as the catalogue is back.</p>
                </div>
              ) : (
                <Skeleton className="relative h-80 w-full max-w-[18rem] rounded-3xl" />
              )}
            </div>

            {/* Today's other prices: floating around the receipt from lg, a tidy grid below it on phones. */}
            {others.length ? (
              <ul className="relative mx-auto mt-8 grid max-w-sm grid-cols-2 gap-2 lg:static lg:mt-0 lg:block lg:max-w-none">
                {others.map((row, index) => {
                  const slot = TAG_SLOTS[index];
                  return (
                    <li
                      key={row.slug}
                      // An unset --l or --r leaves that side auto, so each tag pins to one side.
                      className="lg:absolute lg:left-(--l) lg:right-(--r) lg:top-(--t)"
                      style={{ ["--l" as string]: slot.left, ["--r" as string]: slot.right, ["--t" as string]: slot.top }}
                    >
                      <span
                        className="flex items-center gap-2 rounded-2xl bg-surface p-2 pr-3 shadow-raised ring-1 ring-line lg:rounded-full lg:py-1.5 lg:pl-1.5 lg:pr-4 lg:motion-safe:animate-float"
                        style={{ animationDelay: `${slot.delay}s` }}
                      >
                        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="xs" />
                        <span className="min-w-0 flex-1 lg:flex lg:items-center lg:gap-2.5">
                          <span className="block truncate text-caption font-medium text-ink-soft">{row.name}</span>
                          <span className="tabular block text-sm font-semibold text-ink">{cedis(row.price)}</span>
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        </Reveal>

        {/* The two ways a number is sold - both real, both priced in cedis. */}
        <Reveal className="mx-auto mt-12 grid max-w-4xl grid-cols-1 gap-4 sm:grid-cols-2 lg:mt-6">
          <Option
            title="One number, one code"
            price={cheapest !== null ? `From ${cedis(cheapest)}` : "Priced per service"}
            note="Per number, for the popular services today"
            points={["Shown in cedis before you buy", "Refunded if no code arrives", "Nothing added at checkout"]}
            featured
          />
          <Option
            title="Another code, same number"
            price="Priced on your order"
            note="When the service allows a number to be used again"
            points={[
              "Offered on the order while its window is open",
              "A new order, with its own price in cedis",
              "Refunded too if no code comes",
            ]}
          />
        </Reveal>

        <Reveal className="mx-auto mt-12 max-w-3xl text-center">
          <p className="text-balance text-2xl font-bold tracking-tight text-ink sm:text-3xl">
            No crypto. No dollars.{" "}
            <span className="text-brand-700">Nothing added at checkout.</span>
          </p>
          <p className="mx-auto mt-4 max-w-2xl text-pretty text-base leading-relaxed text-ink-muted">
            Prices follow the provider&apos;s cost and the cedi, and are fixed onto your order when
            you buy - so a rate change mid-order cannot change what you paid.
          </p>

          <details className="group mx-auto mt-6 max-w-xl rounded-2xl border border-line bg-surface text-left open:shadow-card">
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-ink [&::-webkit-details-marker]:hidden">
              What goes into a price
              <ArrowRightIcon className="h-4 w-4 rotate-90 text-ink-muted transition-transform group-open:-rotate-90" />
            </summary>
            <dl className="divide-y divide-line border-t border-line px-4">
              {PARTS.map((part) => (
                <div key={part.label} className="grid grid-cols-1 gap-1 py-3 sm:grid-cols-3 sm:gap-4">
                  <dt className="text-sm font-medium text-ink">{part.label}</dt>
                  <dd className="text-sm text-ink-muted sm:col-span-2">{part.note}</dd>
                </div>
              ))}
            </dl>
          </details>

          <ButtonLink href="/services" variant="secondary" className="group mt-6">
            See today&apos;s prices
            <ArrowRightIcon className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </ButtonLink>
        </Reveal>
      </div>
    </section>
  );
}

/** One service's price as a receipt: the price, what is added (nothing), what you pay. */
function Receipt({ row, country }: { row: MarketRow; country: string }) {
  return (
    <div className="relative w-full max-w-[18rem] rounded-3xl bg-surface p-5 shadow-pop ring-1 ring-line">
      <div className="flex items-center gap-3">
        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="lg" />
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-ink">{row.name}</p>
          <p className="flex items-center gap-1.5 text-caption text-ink-muted">
            <CountryFlag code={country} size="sm" />
            {country === "US" ? "United States" : country}
          </p>
        </div>
      </div>

      <p className="mt-5 text-2xs font-medium uppercase tracking-wider text-ink-muted">Price</p>
      <p className="tabular mt-0.5 flex items-baseline gap-1.5 text-ink">
        <span className="text-xl font-semibold text-ink-muted">GH₵</span>
        <span className="text-5xl font-bold tracking-tight">{Number.parseFloat(row.price ?? "0").toFixed(2)}</span>
      </p>
      <p className="mt-2 flex gap-1.5">
        {["One number", "One price"].map((chip) => (
          <span key={chip} className="rounded-full bg-brand-50 px-2.5 py-0.5 text-2xs font-semibold text-brand-700">
            {chip}
          </span>
        ))}
      </p>

      {/* The tear line of a receipt */}
      <div aria-hidden className="relative -mx-5 my-4 border-t border-dashed border-line-strong">
        <span className="absolute -left-2 -top-2 h-4 w-4 rounded-full bg-canvas ring-1 ring-line" />
        <span className="absolute -right-2 -top-2 h-4 w-4 rounded-full bg-canvas ring-1 ring-line" />
      </div>

      <dl className="space-y-1.5 text-caption">
        <ReceiptLine label="Number price">{cedis(row.price)}</ReceiptLine>
        <ReceiptLine label="Added at checkout">{cedis(0)}</ReceiptLine>
        <ReceiptLine label="Taken from your wallet" strong>
          {cedis(row.price)}
        </ReceiptLine>
      </dl>
      <p className="mt-3.5 flex items-center gap-1.5 text-2xs text-ink-muted">
        <LockIcon className="h-3 w-3 text-brand-600" />
        Fixed on your order when you buy
      </p>
    </div>
  );
}

function ReceiptLine({ label, strong, children }: { label: string; strong?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className={strong ? "font-semibold text-ink" : "text-ink-muted"}>{label}</dt>
      <dd className={cn("tabular", strong ? "font-semibold text-ink" : "text-ink-soft")}>{children}</dd>
    </div>
  );
}

/** One way to buy: what it is, what it costs, what you can count on. */
function Option({
  title,
  price,
  note,
  points,
  featured = false,
}: {
  title: string;
  price: string;
  note: string;
  points: string[];
  featured?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-3xl p-6",
        featured
          ? "bg-navy text-white shadow-pop ring-1 ring-white/10"
          : "border border-line bg-surface text-ink shadow-card",
      )}
    >
      {featured ? (
        <span
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-[radial-gradient(closest-side,rgba(40,199,247,0.35),transparent)]"
        />
      ) : null}
      <p className={cn("text-sm font-semibold", featured ? "text-aqua" : "text-brand-700")}>{title}</p>
      <p className="tabular mt-2 text-3xl font-extrabold tracking-tight">{price}</p>
      <p className={cn("mt-1 text-caption", featured ? "text-white/65" : "text-ink-muted")}>{note}</p>
      <ul className="mt-5 space-y-2.5">
        {points.map((point) => (
          <li key={point} className={cn("flex items-start gap-2.5 text-sm", featured ? "text-white/85" : "text-ink-soft")}>
            <span
              className={cn(
                "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
                featured ? "bg-leaf text-navy" : "bg-brand-50 text-brand-700",
              )}
            >
              <CheckIcon className="h-2.5 w-2.5" />
            </span>
            {point}
          </li>
        ))}
      </ul>
    </div>
  );
}
