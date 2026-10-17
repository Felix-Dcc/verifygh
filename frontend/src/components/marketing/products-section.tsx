"use client";

import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { ArrowRightIcon, CheckCircleIcon, ClockIcon, RefreshIcon, StarIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, Skeleton, cn } from "@/components/ui/primitives";
import { cedis, signedCedis } from "@/lib/format";
import type { MarketHome, MarketRow } from "@/lib/types";

import { Reveal } from "./device";

/**
 * What VerifyGH does, product by product - only what exists today, each with
 * a picture of itself rather than an icon: numbers for SMS codes, using a
 * number again, refunds that happen on their own, and favourites one tap
 * away. (No voice, rentals or public API: they are not offered, so they are
 * not shown.)
 *
 * Live: services, logos, prices, the count. Invented: example numbers and codes.
 */
export function ProductsSection() {
  const { data } = useSWR<MarketHome>("/marketplace/home/");
  const popular = (data?.popular ?? []).filter((row) => !row.temporarily_unavailable && row.icon_url);
  const featured = popular.find((row) => row.slug === "tiktok") ?? popular[0];

  return (
    <section id="products" className="scroll-mt-20 py-16 sm:py-24" aria-labelledby="products-heading">
      <div className="container-page">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 id="products-heading" className="section-title">
            Everything you need to verify.
          </h2>
          <p className="section-lead">
            One account for every code: the numbers, a second code when you need it, refunds you
            never have to ask for, and the services you use most.
          </p>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Reveal className="sm:col-span-2">
            <Product
              title="US numbers for SMS codes"
              body={`Real US numbers for ${data?.total ? `${data.total} services` : "hundreds of services"}. Pay in cedis, receive the code on your order.`}
              action={{ href: "/services", label: "Browse services" }}
            >
              <NumbersArt rows={popular.slice(0, 3)} />
            </Product>
          </Reveal>
          <Reveal delay={80}>
            <Product
              title="Use a number again"
              body="Need another code? When the service allows it, the order offers the same number again for a new price."
            >
              <ReuseArt />
            </Product>
          </Reveal>
          <Reveal>
            <Product
              title="Refunds on their own"
              body="No code before the number expires, or you cancel first? The full price goes back to your wallet automatically."
            >
              <RefundArt row={featured} />
            </Product>
          </Reveal>
          <Reveal delay={80} className="sm:col-span-2">
            <Product
              title="Your services, one tap away"
              body="Star the apps you use most and they get their own row in the marketplace. Buy again from your last orders in one tap."
              action={{ href: "/services", label: "Open the marketplace" }}
            >
              <FavouritesArt rows={popular.slice(0, 6)} />
            </Product>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Product({
  title,
  body,
  action,
  children,
}: {
  title: string;
  body: string;
  action?: { href: string; label: string };
  children: React.ReactNode;
}) {
  return (
    <article className="group flex h-full flex-col overflow-hidden rounded-3xl border border-line bg-surface shadow-card transition-shadow hover:shadow-raised">
      <div
        aria-hidden
        className="relative flex h-52 items-center justify-center overflow-hidden bg-[radial-gradient(ellipse_at_30%_0%,rgb(var(--c-brand-50)),transparent_60%),radial-gradient(ellipse_at_90%_100%,rgba(8,120,209,0.08),transparent_60%)] px-5"
      >
        {children}
      </div>
      <div className="flex flex-1 flex-col p-6">
        <h3 className="text-lg font-bold tracking-tight text-ink">{title}</h3>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{body}</p>
        {action ? (
          <ButtonLink href={action.href} variant="ghost" size="sm" className="group/link -ml-3 mt-4 self-start">
            {action.label}
            <ArrowRightIcon className="h-4 w-4 transition-transform group-hover/link:translate-x-0.5" />
          </ButtonLink>
        ) : null}
      </div>
    </article>
  );
}

/** Three orders on three numbers, at three stages. */
function NumbersArt({ rows }: { rows: MarketRow[] }) {
  const stages = [
    { number: "+1 (512) 555-0147", status: "Code received", tone: "bg-success-50 text-success-700" },
    { number: "+1 (646) 555-0182", status: "Waiting for SMS", tone: "bg-info-50 text-info-700" },
    { number: "+1 (312) 555-0119", status: "Ready", tone: "bg-sunken text-ink-soft" },
  ];
  return (
    <div className="w-full max-w-md space-y-2">
      {stages.map((stage, index) => {
        const row = rows[index];
        return (
          <div
            key={stage.number}
            className={cn(
              "flex items-center gap-3 rounded-2xl border border-line bg-surface px-3 py-2.5 shadow-card",
              index === 1 && "translate-x-3 sm:translate-x-6",
            )}
          >
            <RowLogo row={row} size="sm" />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 text-sm font-semibold text-ink">
                {row?.name ?? "—"} <CountryFlag code="US" size="sm" />
              </span>
              <span className="code block truncate text-caption text-ink-muted">{stage.number}</span>
            </span>
            <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-2xs font-semibold", stage.tone)}>{stage.status}</span>
          </div>
        );
      })}
    </div>
  );
}

/** One number, two codes. */
function ReuseArt() {
  return (
    <div className="w-full max-w-60">
      <div className="rounded-2xl border border-line bg-surface p-3 shadow-card">
        <p className="text-2xs text-ink-muted">Same number</p>
        <p className="code text-sm font-semibold text-ink">+1 (512) 555-0147</p>
      </div>
      <div className="ml-4 mt-2 space-y-1.5 border-l-2 border-dashed border-line-strong pl-3">
        {[
          { label: "First code", code: "482196" },
          { label: "Another code", code: "739015" },
        ].map((item) => (
          <div key={item.label} className="flex items-center gap-2 rounded-xl bg-success-50 px-2.5 py-1.5">
            <CheckCircleIcon className="h-3.5 w-3.5 text-success-700" />
            <span className="text-2xs text-success-700">{item.label}</span>
            <span className="code ml-auto text-caption font-semibold tracking-wider text-success-700">{item.code}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The clock runs out, the money comes back. */
function RefundArt({ row }: { row?: MarketRow }) {
  const price = row?.price ?? null;
  return (
    <div className="flex w-full max-w-60 flex-col items-stretch gap-2">
      <div className="flex items-center gap-2.5 rounded-2xl border border-line bg-surface p-3 shadow-card">
        <span className="relative flex h-9 w-9 items-center justify-center rounded-full border-2 border-dashed border-warn-500 text-warn-700">
          <ClockIcon className="h-4 w-4" />
        </span>
        <span>
          <span className="block text-caption font-semibold text-ink">Number expired</span>
          <span className="block text-2xs text-ink-muted">No code arrived</span>
        </span>
      </div>
      <div className="flex items-center gap-2.5 rounded-2xl bg-linear-to-r from-[#0B63B6] to-[#137A4E] p-3 text-white shadow-[0_12px_24px_-12px_rgba(8,120,209,0.8)]">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15">
          <RefreshIcon className="h-4 w-4" />
        </span>
        <span>
          <span className="tabular block text-base font-bold">{price ? signedCedis(price, "CREDIT") : "Full price"}</span>
          <span className="block text-2xs text-white/80">Back in your wallet</span>
        </span>
      </div>
    </div>
  );
}

/** Starred services at the top, "Buy again" chips beneath. */
function FavouritesArt({ rows }: { rows: MarketRow[] }) {
  return (
    <div className="w-full max-w-md">
      <div className="grid grid-cols-3 gap-2">
        {rows.slice(0, 3).map((row) => (
          <div key={row.slug} className="relative rounded-2xl border border-line bg-surface p-2.5 shadow-card">
            <StarIcon filled className="absolute right-2 top-2 h-3.5 w-3.5 text-gold-500" />
            <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="sm" />
            <p className="mt-1.5 truncate text-caption font-semibold text-ink">{row.name}</p>
            <p className="tabular text-2xs text-ink-muted">{cedis(row.price)}</p>
          </div>
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {rows.slice(3, 6).map((row) => (
          <span
            key={row.slug}
            className="flex items-center gap-1.5 rounded-full border border-line bg-surface py-1 pl-1 pr-3 text-2xs font-medium text-ink-soft shadow-card"
          >
            <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="xs" className="h-5! w-5!" />
            Buy again
          </span>
        ))}
      </div>
    </div>
  );
}

/** A service's logo, or a quiet placeholder tile until the catalogue answers. */
function RowLogo({ row, size, className }: { row?: MarketRow; size: "xs" | "sm" | "md"; className?: string }) {
  if (!row) {
    const box = { xs: "h-7 w-7", sm: "h-8 w-8 sm:h-9 sm:w-9", md: "h-9 w-9" }[size];
    return <Skeleton className={cn("shrink-0 rounded-[23%]", box, className)} />;
  }
  return <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size={size} className={className} />;
}
