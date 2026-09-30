"use client";

import Link from "next/link";
import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { ArrowRightIcon } from "@/components/icons";
import { AvailabilityLabel } from "@/components/marketplace/availability";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, Skeleton } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome } from "@/lib/types";

/**
 * Popular services on the homepage: the same ranking and prices as the
 * marketplace (services the team features, then what people actually bought
 * in the last 30 days), live. If the catalogue is not reachable the section
 * says so rather than showing a made-up price list.
 */
export function FeaturedServices() {
  const { data, isLoading, error } = useSWR<MarketHome>("/marketplace/home/");
  const rows = (data?.popular ?? []).filter((row) => !row.temporarily_unavailable).slice(0, 8);
  const country = data?.countries.find((entry) => entry.code === data.country);

  return (
    <section className="container-page py-16 sm:py-24" aria-labelledby="services-heading">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-xl">
          <h2
            id="services-heading"
            className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl"
          >
            Popular services
          </h2>
          <p className="mt-3 text-base text-ink-muted">
            Today&apos;s prices and stock. The price is exactly what leaves your wallet.
          </p>
        </div>
        <ButtonLink href="/services" variant="secondary" icon={<ArrowRightIcon className="h-4 w-4" />}>
          All services
        </ButtonLink>
      </div>

      {isLoading ? (
        <ul className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-busy>
          {Array.from({ length: 8 }).map((_, index) => (
            <li key={index} className="card flex items-center gap-3 p-4">
              <Skeleton className="h-10 w-10 rounded-lg" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
            </li>
          ))}
        </ul>
      ) : error || rows.length === 0 ? (
        <div className="card mt-8 p-6 text-center">
          <p className="text-sm font-medium text-ink">The catalogue is not available right now.</p>
          <p className="mt-1 text-sm text-ink-muted">
            Services and prices appear here as soon as our provider connection is live.
          </p>
        </div>
      ) : (
        <ul className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {rows.map((row) => (
            <li key={row.slug}>
              <Link
                href={`/services?service=${encodeURIComponent(row.slug)}&country=${data?.country ?? ""}`}
                className="card group flex h-full flex-col gap-4 p-4 transition-colors hover:border-line-strong hover:bg-sunken/40"
              >
                <div className="flex items-center gap-3">
                  <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink" title={row.name}>
                      {row.name}
                    </p>
                    {country ? (
                      <p className="flex items-center gap-1.5 text-caption text-ink-muted">
                        <CountryFlag code={country.code} size="sm" />
                        {country.name}
                      </p>
                    ) : null}
                  </div>
                </div>
                <div className="mt-auto flex items-end justify-between gap-2">
                  <div>
                    <p className="tabular text-heading text-ink">{row.price ? cedis(row.price) : "—"}</p>
                    <AvailabilityLabel availability={row.availability} count={row.available_count} />
                  </div>
                  <ArrowRightIcon className="h-4 w-4 text-ink-faint transition-transform group-hover:translate-x-0.5" />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
