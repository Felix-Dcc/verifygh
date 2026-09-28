"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { useAuth } from "@/components/auth-provider";
import { ServiceAvatar } from "@/components/brand";
import { ChevronDownIcon, GridIcon, SearchIcon } from "@/components/icons";
import { BuyDialog } from "@/components/marketplace/buy-dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Select,
  Skeleton,
  Spinner,
  cn,
} from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type {
  CatalogHealth,
  CountryOption,
  MarketplaceResponse,
  Service,
  ServiceDetail,
} from "@/lib/types";

export function Marketplace() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, ready } = useAuth();

  const [search, setSearch] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [country, setCountry] = React.useState("");
  const [availableOnly, setAvailableOnly] = React.useState(false);
  const [expanded, setExpanded] = React.useState<string | null>(params.get("service"));

  const [buying, setBuying] = React.useState<{
    service: Service;
    country: CountryOption;
  } | null>(null);

  const { data, isLoading, error } = useSWR<MarketplaceResponse>([
    "/services/",
    { category, country, available: availableOnly ? "true" : "" },
  ]);
  const { data: health } = useSWR<CatalogHealth>("/catalog/health/");

  // Search filters the already-loaded page client-side: instant, and it does
  // not fire a request on every keystroke over mobile data.
  const services = React.useMemo(() => {
    const all = data?.results ?? [];
    const needle = search.trim().toLowerCase();
    if (!needle) return all;
    return all.filter(
      (service) =>
        service.name.toLowerCase().includes(needle) || service.slug.includes(needle),
    );
  }, [data, search]);

  function onBuy(service: Service, option: CountryOption) {
    if (!user) {
      router.push(`/login?next=${encodeURIComponent(`/services?service=${service.slug}`)}`);
      return;
    }
    setBuying({ service, country: option });
  }

  return (
    <div className="space-y-4">
      {health && !health.ready ? (
        <Alert tone="warn" title="The catalogue is not fully live yet">
          {health.exchange_rate_configured
            ? "Our provider connection is being set up. Prices and availability appear here as soon as it is."
            : "Pricing is being configured. Nothing can be purchased until it is complete."}
        </Alert>
      ) : null}

      <Card className="p-3 sm:p-4">
        <div className="flex flex-col gap-2.5 sm:flex-row">
          <div className="relative flex-1">
            <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
            <Input
              aria-label="Search services"
              placeholder="Search services"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="pl-11"
              type="search"
              inputMode="search"
            />
          </div>

          <div className="grid grid-cols-2 gap-2.5 sm:flex sm:w-auto">
            <Select
              aria-label="Filter by category"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className="sm:w-40"
            >
              <option value="">All categories</option>
              {data?.categories?.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>

            <Select
              aria-label="Filter by country"
              value={country}
              onChange={(event) => setCountry(event.target.value)}
              className="sm:w-40"
            >
              <option value="">All countries</option>
              {data?.countries?.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.flag_emoji} {item.name}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <label className="mt-3 flex w-fit cursor-pointer items-center gap-2.5 text-sm text-ink-soft">
          <input
            type="checkbox"
            checked={availableOnly}
            onChange={(event) => setAvailableOnly(event.target.checked)}
            className="h-4 w-4 rounded border-line-strong text-brand-600 focus:ring-brand-500/50"
          />
          Show available only
        </label>
      </Card>

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, index) => (
            <Card key={index} className="p-4">
              <div className="flex items-center gap-3">
                <Skeleton className="h-11 w-11 rounded-xl" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-3 w-20" />
                </div>
              </div>
              <Skeleton className="mt-4 h-9 w-full rounded-xl" />
            </Card>
          ))}
        </div>
      ) : error ? (
        <Card>
          <EmptyState
            icon={<GridIcon />}
            title="We could not load the catalogue"
            description="Check your connection and try again."
            action={<Button onClick={() => location.reload()}>Retry</Button>}
          />
        </Card>
      ) : services.length === 0 ? (
        <Card>
          <EmptyState
            icon={<SearchIcon />}
            title="Nothing matches those filters"
            description="Try a different service, country or category."
            action={
              <Button
                variant="secondary"
                onClick={() => {
                  setSearch("");
                  setCategory("");
                  setCountry("");
                  setAvailableOnly(false);
                }}
              >
                Clear filters
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <p className="text-sm text-ink-muted">
            {services.length} {services.length === 1 ? "service" : "services"}
            {country ? ` in ${country}` : ""}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {services.map((service) => (
              <ServiceCard
                key={service.slug}
                service={service}
                expanded={expanded === service.slug}
                onToggle={() =>
                  setExpanded(expanded === service.slug ? null : service.slug)
                }
                onBuy={onBuy}
                signedIn={Boolean(user) && ready}
              />
            ))}
          </div>
        </>
      )}

      <BuyDialog
        open={buying !== null}
        onClose={() => setBuying(null)}
        service={buying?.service ?? null}
        country={buying?.country ?? null}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ServiceCard({
  service,
  expanded,
  onToggle,
  onBuy,
  signedIn,
}: {
  service: Service;
  expanded: boolean;
  onToggle: () => void;
  onBuy: (service: Service, option: CountryOption) => void;
  signedIn: boolean;
}) {
  const panelId = `countries-${service.slug}`;

  // The list endpoint deliberately omits countries - across the full provider
  // catalogue that array is ~15,000 entries, and shipping it made the
  // marketplace a multi-megabyte download on every visit. So a card carries a
  // "from" price and a count, and fetches the countries the moment someone
  // actually opens it. SWR caches per slug, so reopening is instant.
  const { data: detail, isLoading: loadingCountries } = useSWR<ServiceDetail>(
    expanded ? `/services/${service.slug}/` : null,
  );
  const countries = detail?.countries ?? [];

  return (
    <Card className={cn("flex flex-col overflow-hidden", !service.available && "opacity-80")}>
      <div className="flex items-start gap-3 p-4">
        <ServiceAvatar name={service.name} accentColor={service.accent_color} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="truncate text-base font-semibold text-ink">{service.name}</h3>
            {service.is_maintenance ? (
              <Badge tone="warn">Maintenance</Badge>
            ) : service.available ? (
              <Badge tone="success" dot>
                Available
              </Badge>
            ) : (
              <Badge tone="neutral">Out of stock</Badge>
            )}
          </div>

          <p className="mt-0.5 text-xs text-ink-muted">
            {service.from_price ? (
              <>
                From <span className="tabular font-medium text-ink">{cedis(service.from_price)}</span>
                <span className="mx-1.5" aria-hidden>
                  &middot;
                </span>
              </>
            ) : null}
            {service.country_count}{" "}
            {service.country_count === 1 ? "country" : "countries"}
          </p>

          <div className="mt-1.5 flex flex-wrap gap-1">
            {service.supports_sms ? <Capability label="SMS" /> : null}
            {service.supports_voice ? <Capability label="Voice" /> : null}
          </div>
        </div>
      </div>

      {service.is_maintenance && service.maintenance_note ? (
        <p className="mx-4 mb-3 rounded-lg bg-warn-50 px-3 py-2 text-xs text-warn-700">
          {service.maintenance_note}
        </p>
      ) : null}

      <div className="mt-auto border-t border-line">
        <ul id={panelId} className="divide-y divide-line">
          {countries.map((option) => (
            <li key={option.code} className="flex items-center gap-3 px-4 py-3">
              <span className="text-base" aria-hidden>
                {option.flag_emoji}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{option.name}</p>
                <p className="text-xs text-ink-muted">
                  {option.available ? (
                    option.available_count && option.available_count < 20 ? (
                      <span className="text-warn-700">Only {option.available_count} left</span>
                    ) : (
                      "In stock"
                    )
                  ) : (
                    "Out of stock"
                  )}
                </p>
              </div>
              <span className="tabular shrink-0 text-sm font-semibold text-ink">
                {cedis(option.price)}
              </span>
              <Button
                size="sm"
                variant={option.available ? "subtle" : "secondary"}
                disabled={!option.available || service.is_maintenance}
                onClick={() => onBuy(service, option)}
              >
                {signedIn ? "Buy" : "Sign in"}
              </Button>
            </li>
          ))}
        </ul>

        {expanded && loadingCountries ? (
          <div className="flex items-center justify-center gap-2 py-4 text-sm text-ink-muted">
            <Spinner className="h-4 w-4 text-brand-600" />
            Loading countries...
          </div>
        ) : null}

        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={panelId}
          className="flex w-full items-center justify-center gap-1.5 border-t border-line py-2.5 text-sm font-medium text-brand-700 transition-colors hover:bg-canvas"
        >
          {expanded
            ? "Hide countries"
            : `Choose from ${service.country_count} ${
                service.country_count === 1 ? "country" : "countries"
              }`}
          <ChevronDownIcon
            className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")}
          />
        </button>
      </div>
    </Card>
  );
}

function Capability({ label }: { label: string }) {
  return (
    <span className="rounded-md bg-line/60 px-1.5 py-0.5 text-2xs font-medium text-ink-soft">
      {label}
    </span>
  );
}
