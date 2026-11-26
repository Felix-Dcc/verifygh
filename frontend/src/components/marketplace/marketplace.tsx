"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";

import { AppHero, HeroStat } from "@/components/app-hero";
import { useAuth } from "@/components/auth-provider";
import { CountryFlag } from "@/components/country-flag";
import { ChevronRightIcon, ClockIcon, SearchIcon, StarIcon } from "@/components/icons";
import { PhoneMessageArt, SearchArt } from "@/components/illustrations";
import { AvailabilityLabel, TemporarilyUnavailableBadge } from "@/components/marketplace/availability";
import { BuyDialog } from "@/components/marketplace/buy-dialog";
import { Alert, Card, EmptyState, LoadError, Skeleton, Spinner, cn } from "@/components/ui/primitives";
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
 * Built for speed on a phone. Popular services (the team's picks plus what
 * people actually bought in the last 30 days) come first as tiles, then the
 * customer's own "Buy again" and favourites, then the full catalogue as
 * compact rows - a service is never shown twice in the same form. Search runs
 * on the server, and every price, stock figure and rank comes from the
 * backend.
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
  const { data: home, error: homeError, mutate: mutateHome } = useSWR<MarketHome>([
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

  // Endless list: the next page loads by itself as the end comes into view,
  // so customers just keep scrolling instead of pressing "Show more".
  const endOfList = React.useRef<HTMLDivElement>(null);
  const { isValidating, setSize } = list;
  React.useEffect(() => {
    const node = endOfList.current;
    if (!node || !hasMore || isValidating) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setSize((size) => size + 1);
      },
      // Start a screen early, so the next services are usually there in time.
      { rootMargin: "800px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, isValidating, setSize]);

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
  const pinned = (home?.pinned ?? []).filter((row) => isPinned(row));
  // The list needs a country, and the country comes from this request.
  const homeFailed = Boolean(homeError) && !home && !activeCountry;

  const countryName = home?.countries.find((entry) => entry.code === activeCountry)?.name;

  // Popular, as tiles. Favourites have their own list, so they are left out.
  const pinnedSlugs = new Set(pinned.map((row) => row.slug));
  const popularAll = (home?.popular ?? [])
    .filter((row) => !pinnedSlugs.has(row.slug) && !row.temporarily_unavailable)
    .slice(0, 8);
  // Whole rows only (four across on desktop, two on phones): a lone tile on a
  // second row looks like a mistake.
  const popular =
    popularAll.length >= 4 ? popularAll.slice(0, popularAll.length - (popularAll.length % 4)) : popularAll;

  // "Buy again": the customer's own recent services - not ones already shown
  // above as favourites or popular tiles.
  const { data: recent } = useSWR<Paginated<OrderSummary>>(
    user ? ["/orders/", { page_size: 20 }] : null,
  );
  const buyAgain = React.useMemo(() => {
    const seen = new Set<string>([...pinnedSlugs, ...popular.map((row) => row.slug)]);
    const out: { slug: string; name: string; icon: string }[] = [];
    for (const order of recent?.results ?? []) {
      if (seen.has(order.service_slug) || order.country_code !== activeCountry) continue;
      seen.add(order.service_slug);
      out.push({ slug: order.service_slug, name: order.service_name, icon: order.service_icon });
    }
    return out.slice(0, 6);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recent, home, activeCountry]);

  const rowProps = (row: MarketRow) => ({
    row,
    countryName,
    pinned: isPinned(row),
    onOpen: () => setBuying(row.slug),
    onPin: () => togglePin(row),
  });

  const prices = (home?.popular ?? [])
    .map((row) => Number.parseFloat(row.price ?? ""))
    .filter((value) => value > 0);
  const cheapest = prices.length ? Math.min(...prices) : null;

  return (
    <div className="space-y-8">
      <AppHero
        title="Buy a number"
        description="Pick the service you are signing up to. You get a number that receives its code, paid in cedis from your wallet."
        aside={
          <MarketFacts
            facts={[
              { label: "On sale", value: home ? `${home.total} services` : null },
              {
                // Short, so label and value share one line even at 320px.
                label: "Country",
                value: countryName ? (
                  <span className="flex items-center gap-2">
                    <CountryFlag code={activeCountry} size="sm" />
                    {countryName}
                  </span>
                ) : null,
              },
              { label: "Popular from", value: cheapest !== null ? cedis(cheapest) : home ? "—" : null },
            ]}
          />
        }
      >
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="relative block flex-1">
            <span className="sr-only">Search services</span>
            <SearchIcon className="pointer-events-none absolute left-4 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-white/70" />
            <input
              type="search"
              inputMode="search"
              placeholder="Search WhatsApp, TikTok…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="h-12 w-full rounded-full border border-white/15 bg-white/10 pl-11 pr-4 text-base text-white placeholder:text-white/50 backdrop-blur-sm transition-colors focus:border-aqua focus:bg-white/15 focus:outline-hidden focus:ring-2 focus:ring-aqua/40"
            />
          </label>
          {homeFailed || (home?.countries.length ?? 0) < 2 ? null : (
            <CountrySwitch countries={home?.countries ?? []} value={activeCountry} onChange={changeCountry} />
          )}
        </div>
      </AppHero>

      {health && !health.ready ? (
        <Alert tone="warn" title="The catalogue is not fully live yet">
          {health.exchange_rate_configured
            ? "Our provider connection is being set up. Prices and availability appear here as soon as it is."
            : "Pricing is being configured. Nothing can be bought until it is complete."}
        </Alert>
      ) : null}

      {user && !searching ? (
        // Rentals: the other way to get a number, for days rather than minutes.
        <Link
          href="/rentals"
          className="group flex items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 transition-colors hover:border-brand-300"
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
            <ClockIcon className="h-5 w-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-ink">Need a number for days? Rent one</span>
            <span className="block text-caption text-ink-muted">
              Keep a US number from 1 day to 3 months and receive every SMS it gets.
            </span>
          </span>
          <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
        </Link>
      ) : null}

      {!searching && popular.length > 0 ? (
        <section aria-labelledby="popular-heading">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 id="popular-heading" className="text-heading text-ink">
              Popular today
            </h2>
            <p className="text-caption text-ink-muted">What people are buying most</p>
          </div>
          <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
            {popular.map((row) => (
              <PopularTile key={row.slug} {...rowProps(row)} />
            ))}
          </ul>
        </section>
      ) : null}

      {!searching && buyAgain.length > 0 ? (
        <section aria-labelledby="again-heading">
          <h2 id="again-heading" className="mb-2 text-heading text-ink">
            Buy again
          </h2>
          <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
            {buyAgain.map((service) => (
              <button
                key={service.slug}
                type="button"
                onClick={() => setBuying(service.slug)}
                className="flex h-11 shrink-0 items-center gap-2 rounded-full border border-line bg-surface pl-1.5 pr-4 text-sm font-semibold text-ink shadow-card transition-all hover:-translate-y-0.5 hover:border-brand-500/40 sm:h-10 sm:pl-1.5"
              >
                <ServiceLogo name={service.name} src={service.icon} slug={service.slug} size="xs" />
                {service.name}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {!searching && pinned.length > 0 ? (
        <ServiceList title="Favourites" count={pinned.length}>
          {pinned.map((row) => (
            <ServiceRow key={`pin-${row.slug}`} {...rowProps(row)} />
          ))}
        </ServiceList>
      ) : null}

      <ServiceList
        title={searching ? `Results for "${query}"` : "All services"}
        count={list.data ? total : undefined}
      >
        {homeFailed ? (
          <LoadError what="the services" onRetry={() => mutateHome()} />
        ) : !list.data && !list.error ? (
          <RowSkeletons />
        ) : list.error ? (
          <LoadError what="the services" onRetry={() => list.mutate()} />
        ) : rows.length === 0 ? (
          <EmptyState
            art={searching ? <SearchArt /> : <PhoneMessageArt />}
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
        <div
          ref={endOfList}
          role="status"
          className="flex items-center justify-center gap-2 py-3 text-sm text-ink-muted"
        >
          <Spinner className="h-4 w-4" />
          Loading more services…
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
  if (countries.length < 2) return null;
  // Lives on the navy panel: glass behind, the chosen country in white.
  return (
    <div className="inline-flex rounded-full border border-white/15 bg-white/10 p-1" role="radiogroup" aria-label="Country">
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
              "flex h-10 items-center gap-2 rounded-full px-3.5 text-sm font-semibold transition-colors",
              active ? "bg-white text-navy" : "text-white/75 hover:text-white",
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
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="mb-3 text-heading text-ink">
        {title}
        {count !== undefined ? (
          <span className="tabular ml-2 text-sm font-normal text-ink-faint">{count}</span>
        ) : null}
      </h2>
      <Card className="divide-y divide-line overflow-hidden rounded-2xl">{children}</Card>
    </section>
  );
}

type ServiceItemProps = {
  row: MarketRow;
  countryName?: string;
  pinned: boolean;
  onOpen: () => void;
  onPin: () => void;
};

/** Where a service stands right now: its stock, or why it cannot be bought. */
function Stock({ row }: { row: MarketRow }) {
  return row.temporarily_unavailable ? (
    <TemporarilyUnavailableBadge />
  ) : (
    <AvailabilityLabel
      availability={row.unavailable_here ? "UNAVAILABLE" : row.availability}
      count={row.available_count}
    />
  );
}

function priceOf(row: MarketRow): string {
  return row.price && !row.unavailable_here && !row.temporarily_unavailable ? cedis(row.price) : "—";
}

/** ☆ to ★, with one short pop when a service is added. */
function FavouriteButton({ row, pinned, onPin }: Pick<ServiceItemProps, "row" | "pinned" | "onPin">) {
  const [popping, setPopping] = React.useState(false);
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        if (!pinned) setPopping(true);
        onPin();
      }}
      onAnimationEnd={() => setPopping(false)}
      aria-pressed={pinned}
      aria-label={pinned ? `Remove ${row.name} from favourites` : `Add ${row.name} to favourites`}
      className={cn(
        "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-sunken",
        pinned ? "text-gold-500" : "text-ink-faint hover:text-ink-muted",
      )}
    >
      <StarIcon filled={pinned} className={cn("h-5 w-5", popping && "animate-pin-pop")} />
    </button>
  );
}

/** One service in the catalogue: logo, name, country and stock, price, favourite. */
function ServiceRow({ row, countryName, pinned, onOpen, onPin }: ServiceItemProps) {
  const unavailable =
    row.availability === "UNAVAILABLE" || row.unavailable_here || row.temporarily_unavailable;
  return (
    <div className="flex items-center gap-1 pr-1.5 transition-colors hover:bg-sunken/60">
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-16 min-w-0 flex-1 items-center gap-3 py-2.5 pl-4 text-left sm:pl-5"
      >
        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} />
        <span className="min-w-0 flex-1">
          <span className={cn("block truncate text-sm font-medium", unavailable ? "text-ink-muted" : "text-ink")}>
            {row.name}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            {countryName ? <span className="text-caption text-ink-muted">{countryName}</span> : null}
            {countryName ? <span aria-hidden className="text-caption text-ink-faint">&middot;</span> : null}
            <Stock row={row} />
          </span>
        </span>
        <span
          className={cn(
            "tabular shrink-0 rounded-full px-3 py-1 text-right text-sm font-bold",
            unavailable ? "text-ink-faint" : "bg-sunken text-ink",
          )}
        >
          {priceOf(row)}
        </span>
      </button>
      <FavouriteButton row={row} pinned={pinned} onPin={onPin} />
    </div>
  );
}

/** A popular service as a tile: the same facts as a row, given more room. */
function PopularTile({ row, countryName, pinned, onOpen, onPin }: ServiceItemProps) {
  return (
    <li className="relative">
      <button
        type="button"
        onClick={onOpen}
        className="flex h-full w-full flex-col rounded-2xl border border-line bg-surface p-3 text-left shadow-card transition-all hover:-translate-y-0.5 hover:border-brand-500/40 hover:shadow-raised sm:p-3.5"
      >
        {/* Compact: logo (the star sits beside it), name, then price and stock.
            The country is the same for every tile and is on the panel above. */}
        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="sm" />
        <span className="mt-2 block truncate text-sm font-semibold text-ink" title={row.name}>
          {row.name}
          {countryName ? <span className="sr-only">, {countryName}</span> : null}
        </span>
        <span className="tabular mt-1 block text-base font-bold tracking-tight text-ink">{priceOf(row)}</span>
        <Stock row={row} />
      </button>
      <span className="absolute right-0.5 top-0.5">
        <FavouriteButton row={row} pinned={pinned} onPin={onPin} />
      </span>
    </li>
  );
}

function RowSkeletons() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="flex min-h-16 items-center gap-3 px-4 sm:px-5" aria-hidden>
          <Skeleton className="h-10 w-10 rounded-lg" />
          <Skeleton className="h-3.5 flex-1 sm:max-w-40" />
          <Skeleton className="hidden h-3 w-24 sm:block" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </>
  );
}

/**
 * The marketplace's facts on the navy panel. Where the space is narrow - a
 * phone, or the panel's side column from lg - they are one list, label left
 * and value right, so a long value never squeezes; between sm and lg, where
 * the panel is full width, they sit side by side as tiles.
 */
function MarketFacts({ facts }: { facts: { label: string; value: React.ReactNode | null }[] }) {
  return (
    <>
      <dl className="divide-y divide-white/10 rounded-2xl border border-white/10 bg-white/6 backdrop-blur-sm sm:hidden lg:block">
        {facts.map((fact) => (
          <div key={fact.label} className="flex items-center justify-between gap-3 px-4 py-3">
            <dt className="text-caption text-white/60">{fact.label}</dt>
            <dd className="tabular whitespace-nowrap text-right text-sm font-semibold text-white">
              {fact.value ?? <Skeleton className="h-4 w-20" />}
            </dd>
          </div>
        ))}
      </dl>
      <div className="hidden grid-cols-3 gap-2.5 sm:grid lg:hidden">
        {facts.map((fact) => (
          <HeroStat key={fact.label} label={fact.label} value={fact.value ?? <Skeleton className="mt-1 h-6 w-20" />} />
        ))}
      </div>
    </>
  );
}
