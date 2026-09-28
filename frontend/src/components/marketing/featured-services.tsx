"use client";

import Link from "next/link";
import useSWR from "swr";

import { ServiceLogo } from "@/components/service-logo";
import { ArrowRightIcon } from "@/components/icons";
import { Badge, Button, Skeleton } from "@/components/ui/primitives";
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
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">
            Supported services
          </p>
          <h2
            id="services-heading"
            className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl"
          >
            Availability and prices, live
          </h2>
          <p className="mt-3 text-base text-ink-muted">
            We show what our provider actually has in stock right now. Prices are in cedis and
            include every fee - what you see is what leaves your wallet.
          </p>
        </div>
        <Link href="/services">
          <Button variant="secondary" icon={<ArrowRightIcon className="h-4 w-4" />}>
            View all services
          </Button>
        </Link>
      </div>

      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading ? (
          Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="card p-4">
              <div className="flex items-center gap-3">
                <Skeleton className="h-11 w-11 rounded-xl" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-24" />
                  <Skeleton className="h-3 w-16" />
                </div>
              </div>
              <Skeleton className="mt-4 h-4 w-20" />
            </div>
          ))
        ) : error || services.length === 0 ? (
          <div className="card col-span-full p-6 text-center">
            <p className="text-sm font-medium text-ink">
              The catalogue is not available right now.
            </p>
            <p className="mt-1 text-sm text-ink-muted">
              Supported services and prices appear here as soon as our provider connection is
              live.
            </p>
          </div>
        ) : (
          services.map((service) => <FeaturedCard key={service.slug} service={service} />)
        )}
      </div>
    </section>
  );
}

function FeaturedCard({ service }: { service: Service }) {
  // The featured endpoint sends a few available countries for the flags; the
  // authoritative count is country_count, which covers the rest.
  const flags = (service.countries ?? []).slice(0, 3);
  const total = service.country_count;

  return (
    <Link
      href={`/services?service=${service.slug}`}
      className="card group p-4 transition-shadow hover:shadow-raised focus-visible:shadow-raised"
    >
      <div className="flex items-center gap-3">
        <ServiceLogo name={service.name} src={service.icon_url} slug={service.slug} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">{service.name}</p>
          <p className="truncate text-xs text-ink-muted">
            {total} {total === 1 ? "country" : "countries"}
          </p>
        </div>
      </div>

      <div className="mt-4 flex items-end justify-between gap-2">
        <div>
          <p className="text-2xs uppercase tracking-wide text-ink-faint">From</p>
          <p className="tabular text-base font-semibold text-ink">
            {cedis(service.from_price)}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-sm" aria-hidden>
            {flags.map((country) => country.flag_emoji).join(" ")}
          </span>
          {service.available ? (
            <Badge tone="success" dot>
              Available
            </Badge>
          ) : (
            <Badge tone="neutral">Out of stock</Badge>
          )}
        </div>
      </div>
    </Link>
  );
}
