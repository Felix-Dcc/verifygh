"use client";

import * as React from "react";
import Link from "next/link";
import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { ArrowRightIcon, ChevronRightIcon, SearchIcon } from "@/components/icons";
import { AvailabilityLabel } from "@/components/marketplace/availability";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome, MarketPage } from "@/lib/types";

/** Rows shown on the homepage; the marketplace has the rest. */
export const PICKER_SIZE = 8;

/** The key the picker opens with - the hero reads the same page, so one request serves both. */
export function pickerKey(country: string, search = "") {
  return ["/marketplace/", { country, search, page: 1, page_size: PICKER_SIZE }] as const;
}

/**
 * "Pick a country, pick a service": the catalogue itself on the homepage, with
 * today's prices and stock, searchable. Choosing a service opens it in the
 * marketplace, ready to buy. Nothing here is a sample - if the catalogue is
 * not reachable the section says so.
 */
export function ServicePicker() {
  const { data: home, error: homeError } = useSWR<MarketHome>("/marketplace/home/");
  const [country, setCountry] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const active = country || home?.country || "";
  const { data: page, error, isLoading } = useSWR<MarketPage>(
    active ? pickerKey(active, query) : null,
    { keepPreviousData: true },
  );

  // Before a search, lead with what people buy most (the marketplace's own
  // popular ranking), then fill from the catalogue.
  const rows = React.useMemo(() => {
    const results = page?.results ?? [];
    if (query || !home || active !== home.country) return results;
    const seen = new Set<string>();
    return [...home.popular.filter((row) => !row.temporarily_unavailable), ...results]
      .filter((row) => (seen.has(row.slug) ? false : (seen.add(row.slug), true)))
      .slice(0, PICKER_SIZE);
  }, [page, query, home, active]);

  const countries = home?.countries ?? [];
  const activeCountry = countries.find((entry) => entry.code === active);
  const allHref = `/services?country=${encodeURIComponent(active)}${query ? `&q=${encodeURIComponent(query)}` : ""}`;
  const failed = Boolean(homeError || error);

  return (
    <section id="services" className="container-page scroll-mt-20 py-16 sm:py-24" aria-labelledby="picker-heading">
      <div className="mx-auto max-w-2xl text-center">
        <h2 id="picker-heading" className="section-title">
          What do you need a number for?
        </h2>
        <p className="section-lead">
          Today&apos;s prices and stock, straight from the catalogue. The price is exactly what
          leaves your wallet.
        </p>
      </div>

      <div className="card mx-auto mt-10 grid max-w-5xl grid-cols-1 overflow-hidden shadow-raised lg:grid-cols-5">
        {/* 1. Country */}
        <div className="border-b border-line bg-sunken/50 p-4 sm:p-6 lg:col-span-2 lg:border-b-0 lg:border-r">
          <StepLabel number={1}>Country</StepLabel>
          {failed ? (
            <p className="mt-3 text-sm text-ink-muted">Countries appear here when the catalogue is available.</p>
          ) : !home ? (
            <Skeleton className="mt-3 h-14 w-full rounded-xl" />
          ) : (
            <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1">
              {countries.map((entry) => {
                const selected = entry.code === active;
                return (
                  <li key={entry.code}>
                    <button
                      type="button"
                      onClick={() => setCountry(entry.code)}
                      aria-pressed={selected}
                      className={cn(
                        "flex min-h-14 w-full items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-colors",
                        selected
                          ? "border-brand-500 bg-surface ring-1 ring-brand-500"
                          : "border-line bg-surface hover:border-line-strong",
                      )}
                    >
                      <CountryFlag code={entry.code} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-ink">{entry.name}</span>
                        <span className="tabular block text-caption text-ink-muted">{entry.dial_code}</span>
                      </span>
                      {selected && home.country === entry.code && home.total ? (
                        <span className="tabular shrink-0 text-caption text-ink-soft">
                          {home.total} services
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="mt-4 hidden text-caption leading-relaxed text-ink-muted lg:block">
            Numbers are real mobile numbers from our provider, rented for one code. New countries
            appear here as they are added.
          </p>
        </div>

        {/* 2. Service */}
        <div className="flex min-w-0 flex-col p-4 sm:p-6 lg:col-span-3">
          <StepLabel number={2}>Service</StepLabel>
          <label className="relative mt-3 block">
            <span className="sr-only">Search services</span>
            <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
            <input
              type="search"
              inputMode="search"
              placeholder="Search WhatsApp, TikTok…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              disabled={failed}
              className="h-11 w-full rounded-full border border-line-strong bg-surface pl-10 pr-4 text-base text-ink placeholder:text-ink-faint transition-shadow focus:border-brand-500 focus:shadow-focus focus:outline-none disabled:opacity-60"
            />
          </label>

          <div className="mt-3 min-h-[22rem]" aria-live="polite" aria-busy={isLoading}>
            {failed ? (
              <div className="flex h-full flex-col items-center justify-center py-12 text-center">
                <p className="text-sm font-medium text-ink">The catalogue is not available right now.</p>
                <p className="mt-1 max-w-xs text-sm text-ink-muted">
                  Services and prices appear here as soon as our provider connection is back.
                </p>
              </div>
            ) : !page ? (
              <ul className="divide-y divide-line">
                {Array.from({ length: 6 }).map((_, index) => (
                  <li key={index} className="flex h-14 items-center gap-3">
                    <Skeleton className="h-9 w-9 rounded-lg" />
                    <Skeleton className="h-3.5 flex-1" />
                    <Skeleton className="h-3.5 w-16" />
                  </li>
                ))}
              </ul>
            ) : rows.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <p className="text-sm font-medium text-ink">
                  Nothing matches &ldquo;{query}&rdquo;{activeCountry ? ` in ${activeCountry.name}` : ""}.
                </p>
                <p className="mt-1 text-sm text-ink-muted">Try the app&apos;s usual name, or browse the full list.</p>
              </div>
            ) : (
              <ul className={cn("divide-y divide-line transition-opacity", isLoading && "opacity-60")}>
                {rows.map((row) => {
                  const off = row.availability === "UNAVAILABLE" || row.temporarily_unavailable;
                  return (
                    <li key={row.slug}>
                      <Link
                        href={`/services?service=${encodeURIComponent(row.slug)}&country=${encodeURIComponent(active)}`}
                        className="group -mx-2 flex min-h-14 items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-sunken/60"
                      >
                        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} className={off ? "opacity-50" : ""} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold text-ink">{row.name}</span>
                          <AvailabilityLabel availability={row.availability} count={row.available_count} />
                        </span>
                        <span className="tabular shrink-0 text-sm font-semibold text-ink">
                          {row.price ? cedis(row.price) : "—"}
                        </span>
                        <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {page && !failed ? (
            <div className="mt-4 flex flex-col items-stretch gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="tabular text-caption text-ink-muted">
                {page.count > rows.length
                  ? `Showing ${rows.length} of ${page.count}`
                  : `${page.count} ${page.count === 1 ? "service" : "services"}`}
              </p>
              <ButtonLink href={allHref} variant="secondary" className="group">
                {query ? "Search the marketplace" : "See all services"}
                <ArrowRightIcon className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </ButtonLink>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function StepLabel({ number, children }: { number: number; children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-sm font-semibold text-ink">
      <span className="tabular flex h-6 w-6 items-center justify-center rounded-full bg-primary text-2xs font-bold text-white">
        {number}
      </span>
      {children}
    </p>
  );
}
