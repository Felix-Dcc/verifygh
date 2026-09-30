"use client";

import Link from "next/link";
import useSWR from "swr";

import { ServiceLogo } from "@/components/service-logo";
import { ArrowRightIcon } from "@/components/icons";
import { ButtonLink, Skeleton } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { Service } from "@/lib/types";

/**
 * Live availability on the landing page.
 *
 * Nothing here is hardcoded - it is the same catalogue and the same
 * server-computed prices the marketplace uses. If the catalogue is empty, the
 * section says so rather than showing a fictional price list.
 */
export function FeaturedServices() {
  const { data, isLoading, error } = useSWR<{ results: Service[] }>("/services/featured/");
  const services = data?.results ?? [];

  return (
    <section className="container-page py-16 sm:py-20" aria-labelledby="services-heading">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-xl">
          <h2
            id="services-heading"
            className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl"
          >
            Services and today&apos;s prices
          </h2>
          <p className="mt-3 text-base text-ink-muted">
            Live from our provider&apos;s stock. The price is what leaves your wallet.
          </p>
        </div>
        <ButtonLink href="/services" variant="secondary" icon={<ArrowRightIcon className="h-4 w-4" />}>
          All services
        </ButtonLink>
      </div>

      {isLoading ? (
        <div className="metric-group mt-8 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4" aria-busy>
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="flex items-center gap-3 bg-surface p-4">
              <Skeleton className="h-9 w-9 rounded-lg" />
              <Skeleton className="h-3.5 flex-1" />
              <Skeleton className="h-3.5 w-16" />
            </div>
          ))}
        </div>
      ) : error || services.length === 0 ? (
        <div className="card mt-8 p-6 text-center">
          <p className="text-sm font-medium text-ink">The catalogue is not available right now.</p>
          <p className="mt-1 text-sm text-ink-muted">
            Services and prices appear here as soon as our provider connection is live.
          </p>
        </div>
      ) : (
        <ul className="metric-group mt-8 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
          {services.map((service) => (
            <li key={service.slug} className="bg-surface">
              <Link
                href={`/services?service=${service.slug}`}
                className="flex min-h-16 items-center gap-3 px-4 py-3 transition-colors hover:bg-sunken/60"
              >
                <ServiceLogo name={service.name} src={service.icon_url} slug={service.slug} size="sm" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink" title={service.name}>
                  {service.name}
                </span>
                {service.available ? (
                  <span className="tabular text-sm font-medium text-ink">
                    {cedis(service.from_price)}
                  </span>
                ) : (
                  <span className="text-caption text-ink-muted">Out of stock</span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
