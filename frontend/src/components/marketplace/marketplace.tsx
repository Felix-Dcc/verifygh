"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";

import { useAuth } from "@/components/auth-provider";
import { CountryFlag } from "@/components/country-flag";
import { SearchIcon, StarIcon } from "@/components/icons";
import { AvailabilityLabel, TemporarilyUnavailableBadge } from "@/components/marketplace/availability";
import { BuyDialog } from "@/components/marketplace/buy-dialog";
import { Alert, Button, Card, EmptyState, Skeleton, cn } from "@/components/ui/primitives";
import { ServiceLogo } from "@/components/service-logo";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis } from "@/lib/format";
import type {
  CatalogHealth,
  MarketHome,
  MarketPage,
  MarketRow,
  OrderSummary,
  Paginated,
} from "@/lib/types";

const PAGE_SIZE = 40;

/**
 * SMS Verifications: find a service, pick a country, get a number.
 *
 * Built for speed on a phone: compact rows rather than cards, pinned services
 * first, then popular ones, then everything. Search runs on the server, so it
 * stays fast however large the catalogue grows, and every price, stock figure
 * and "popular" label comes from the backend - there is no catalogue here.
 */
export function Marketplace() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { user } = useAuth();

  const [country, setCountry] = React.useState(() => (params.get("country") ?? "").toUpperCase());
  // ?q= comes from the search box in the top bar, from any page.
  const [search, setSearch] = React.useState(() => params.get("q") ?? "");
  const [query, setQuery] = React.useState(() => (params.get("q") ?? "").trim());
  const incoming = params.get("q");
  React.useEffect(() => {
    if (incoming !== null) setSearch(incoming);
  }, [incoming]);
  const [buying, setBuying] = React.useState<string | null>(params.get("service"));
  // Pins flip instantly and settle when the server answers.
  const [pinOverrides, setPinOverrides] = React.useState<Record<string, boolean>>({});

  React.useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data: health } = useSWR<CatalogHealth>("/catalog/health/");
  const { data: home, mutate: mutateHome } = useSWR<MarketHome>([
    "/marketplace/home/",
    country ? { country } : {},
  ]);
  // The server picks the default country; adopt it so the list matches.
  React.useEffect(() => {
    if (!country && home?.country) setCountry(home.country);
  }, [country, home?.country]);

  const activeCountry = country || home?.country || "";

  const list = useSWRInfinite<MarketPage>(
    (index, previous) => {
      if (!activeCountry) return null;
      if (previous && !previous.has_next) return null;
      return [
        "/marketplace/",
        { country: activeCountry, search: query, page: index + 1, page_size: PAGE_SIZE },
      ];
    },
    { revalidateFirstPage: false },
  );
  const rows = React.useMemo(
    () => (list.data ?? []).flatMap((page) => page.results),
    [list.data],
  );
  const total = list.data?.[0]?.count ?? 0;
  const hasMore = Boolean(list.data?.[list.data.length - 1]?.has_next);

  const isPinned = React.useCallback(
    (row: MarketRow) => pinOverrides[row.slug] ?? row.pinned,
    [pinOverrides],
  );

  async function togglePin(row: MarketRow) {
    if (!user) {
      router.push(`/login?next=${encodeURIComponent("/services")}`);
      return;
    }
    const next = !isPinned(row);
    setPinOverrides((current) => ({ ...current, [row.slug]: next }));
    try {
      if (next) await api.post(`/marketplace/${row.slug}/pin/`, {});
      else await api.delete(`/marketplace/${row.slug}/pin/`);
      await Promise.all([mutateHome(), list.mutate()]);
    } catch (error) {
      toast.error(
        next ? "Could not pin" : "Could not unpin",
        error instanceof ApiError ? error.message : "Please try again.",
      );
    } finally {
      setPinOverrides((current) => {
        const { [row.slug]: _settled, ...rest } = current;
        return rest;
      });
    }
  }

  function changeCountry(code: string) {
    setCountry(code);
    const next = new URLSearchParams(params.toString());
    next.set("country", code);
    router.replace(`/services?${next.toString()}`, { scroll: false });
  }

  const searching = query.length > 0;
  const countryInfo = home?.countries.find((entry) => entry.code === activeCountry);
  const pinned = (home?.pinned ?? []).filter((row) => isPinned(row));
  const popular = home?.popular ?? [];

  // "Recently used": the customer's own last orders, one entry per service.
  const { data: recent } = useSWR<Paginated<OrderSummary>>(
    user ? ["/orders/", { page_size: 20 }] : null,
  );
  const recentlyUsed = React.useMemo(() => {
    const seen = new Set<string>();
    const out: { slug: string; name: string; icon: string }[] = [];
    for (const order of recent?.results ?? []) {
      if (seen.has(order.service_slug) || order.country_code !== activeCountry) continue;
      seen.add(order.service_slug);
      out.push({ slug: order.service_slug, name: order.service_name, icon: order.service_icon });
      if (out.length === 6) break;
    }
    return out;
  }, [recent, activeCountry]);

  const rowProps = (row: MarketRow) => ({
    row,
    pinned: isPinned(row),
    onOpen: () => setBuying(row.slug),
    onPin: () => togglePin(row),
  });

  return (
    <div className="space-y-8">
      {health && !health.ready ? (
        <Alert tone="warn" title="The catalogue is not fully live yet">
          {health.exchange_rate_configured
            ? "Our provider connection is being set up. Prices and availability appear here as soon as it is."
            : "Pricing is being configured. Nothing can be bought until it is complete."}
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative block flex-1">
          <span className="sr-only">Search services</span>
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            type="search"
            inputMode="search"
            placeholder="Search - WhatsApp, TikTok, Gmail, Telegram…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-11 w-full rounded-lg border border-line-strong bg-surface pl-10 pr-3 text-base text-ink placeholder:text-ink-faint transition-shadow focus:border-brand-500 focus:shadow-focus focus:outline-none"
          />
        </label>
        <div className="flex items-center gap-3">
          <CountrySwitch
            countries={home?.countries ?? []}
            value={activeCountry}
            onChange={changeCountry}
          />
        </div>
      </div>

      {!searching && recentlyUsed.length > 0 ? (
        <section aria-labelledby="recent-heading">
          <h2 id="recent-heading" className="mb-2 text-label text-ink-muted">
            Recently used
          </h2>
          <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
            {recentlyUsed.map((service) => (
              <button
                key={service.slug}
                type="button"
                onClick={() => setBuying(service.slug)}
                className="flex h-11 shrink-0 items-center gap-2 rounded-lg border border-line bg-surface pl-2 pr-3 sm:h-10 sm:pl-1.5 text-sm font-medium text-ink transition-colors hover:border-line-strong hover:bg-sunken"
              >
                <ServiceLogo name={service.name} src={service.icon} slug={service.slug} size="xs" />
                {service.name}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {!searching && pinned.length > 0 ? (
        <ServiceList title="Favourites" count={pinned.length} countryName={countryInfo?.name}>
          {pinned.map((row) => (
            <ServiceRow key={`pin-${row.slug}`} {...rowProps(row)} />
          ))}
        </ServiceList>
      ) : null}

      {!searching && popular.length > 0 ? (
        <ServiceList title="Popular" countryName={countryInfo?.name}>
          {popular.map((row) => (
            <ServiceRow key={`pop-${row.slug}`} {...rowProps(row)} />
          ))}
        </ServiceList>
      ) : null}

      <ServiceList
        title={searching ? `Results for "${query}"` : "All services"}
        count={list.data ? total : undefined}
        countryName={countryInfo?.name}
      >
        {!list.data && !list.error ? (
          <RowSkeletons />
        ) : list.error ? (
          <EmptyState
            icon={<SearchIcon />}
            title="We couldn't load the services"
            description="Check your connection, then try again. Nothing has been charged."
            action={<Button onClick={() => list.mutate()}>Try again</Button>}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<SearchIcon />}
            title={searching ? `Nothing matches "${query}"` : "Nothing on sale here right now"}
            description={
              searching
                ? "Try another name - Gmail finds Google, X finds Twitter."
                : (home?.countries.length ?? 0) > 1
                  ? "Try the other country, or check back shortly."
                  : "Services come back as soon as numbers are available. Check back shortly."
            }
          />
        ) : (
          rows.map((row) => <ServiceRow key={row.slug} {...rowProps(row)} />)
        )}
      </ServiceList>

      {hasMore ? (
        <div className="flex justify-center">
          <Button
            variant="secondary"
            loading={list.isValidating}
            onClick={() => list.setSize(list.size + 1)}
          >
            Show more services
          </Button>
        </div>
      ) : null}

      <BuyDialog
        open={buying !== null}
        onClose={() => setBuying(null)}
        serviceSlug={buying}
        initialCountry={activeCountry || "US"}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function CountrySwitch({
  countries,
  value,
  onChange,
}: {
  countries: MarketHome["countries"];
  value: string;
  onChange: (code: string) => void;
}) {
  if (countries.length === 0) return <Skeleton className="h-11 w-44" />;
  if (countries.length === 1) {
    const [only] = countries;
    return (
      <p className="flex h-11 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-medium text-ink">
        <CountryFlag code={only.code} />
        {only.name} numbers
      </p>
    );
  }
  return (
    <div className="inline-flex rounded-lg bg-sunken p-0.5" role="radiogroup" aria-label="Country">
      {countries.map((country) => {
        const active = value === country.code;
        return (
          <button
            key={country.code}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(country.code)}
            className={cn(
              "flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors",
              active ? "bg-surface text-ink shadow-card ring-1 ring-line" : "text-ink-muted hover:text-ink",
            )}
          >
            <CountryFlag code={country.code} size="sm" />
            {country.name}
          </button>
        );
      })}
    </div>
  );
}

function ServiceList({
  title,
  count,
  countryName,
  children,
}: {
  title: string;
  count?: number;
  countryName?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-label text-ink-muted">
          {title}
          {count !== undefined ? <span className="tabular ml-1.5 text-ink-faint">{count}</span> : null}
        </h2>
        {countryName ? (
          <span className="hidden text-caption text-ink-faint sm:inline">Prices for {countryName}</span>
        ) : null}
      </div>
      <Card className="divide-y divide-line overflow-hidden">{children}</Card>
    </section>
  );
}

function ServiceRow({
  row,
  pinned,
  onOpen,
  onPin,
}: {
  row: MarketRow;
  pinned: boolean;
  onOpen: () => void;
  onPin: () => void;
}) {
  const paused = Boolean(row.temporarily_unavailable);
  const unavailable = row.availability === "UNAVAILABLE" || row.unavailable_here || paused;
  const [popping, setPopping] = React.useState(false);

  return (
    <div className="group flex items-center gap-1 pr-1.5 transition-colors hover:bg-sunken/60">
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-14 min-w-0 flex-1 items-center gap-3 py-2 pl-4 text-left sm:pl-5"
      >
        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="sm" />
        <span className="min-w-0 flex-1">
          <span className={cn("block truncate text-sm font-medium", unavailable ? "text-ink-muted" : "text-ink")}>
            {row.name}
          </span>
          <span className="mt-0.5 block sm:hidden">
            {paused ? (
              <TemporarilyUnavailableBadge />
            ) : (
              <AvailabilityLabel
                availability={row.unavailable_here ? "UNAVAILABLE" : row.availability}
                count={row.available_count}
              />
            )}
          </span>
        </span>
        <span className="hidden w-40 shrink-0 sm:block">
          {paused ? (
            <TemporarilyUnavailableBadge />
          ) : (
            <AvailabilityLabel
              availability={row.unavailable_here ? "UNAVAILABLE" : row.availability}
              count={row.available_count}
            />
          )}
        </span>
        <span
          className={cn(
            "tabular w-24 shrink-0 text-right text-sm font-semibold",
            unavailable ? "text-ink-faint" : "text-ink",
          )}
        >
          {row.price && !row.unavailable_here && !paused ? cedis(row.price) : "-"}
        </span>
      </button>
      <button
        type="button"
        onClick={() => {
          if (!pinned) setPopping(true);
          onPin();
        }}
        onAnimationEnd={() => setPopping(false)}
        aria-pressed={pinned}
        aria-label={pinned ? `Remove ${row.name} from favourites` : `Add ${row.name} to favourites`}
        className={cn(
          "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-colors",
          pinned ? "text-gold-500" : "text-ink-faint hover:text-ink-muted",
        )}
      >
        <StarIcon filled={pinned} className={cn("h-5 w-5", popping && "animate-pin-pop")} />
      </button>
    </div>
  );
}

function RowSkeletons() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="flex min-h-14 items-center gap-3 px-4 sm:px-5" aria-hidden>
          <Skeleton className="h-8 w-8 rounded-lg" />
          <Skeleton className="h-3.5 flex-1 sm:max-w-40" />
          <Skeleton className="hidden h-3 w-24 sm:block" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </>
  );
}
