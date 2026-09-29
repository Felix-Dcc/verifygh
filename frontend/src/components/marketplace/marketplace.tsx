"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";

import { useAuth } from "@/components/auth-provider";
import { PinIcon, SearchIcon } from "@/components/icons";
import { AvailabilityLabel, TemporarilyUnavailableBadge } from "@/components/marketplace/availability";
import { BuyDialog } from "@/components/marketplace/buy-dialog";
import { Alert, Button, Card, EmptyState, Input, Skeleton, cn } from "@/components/ui/primitives";
import { ServiceLogo } from "@/components/service-logo";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis } from "@/lib/format";
import type { CatalogHealth, MarketHome, MarketPage, MarketRow } from "@/lib/types";

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
  const [search, setSearch] = React.useState("");
  const [query, setQuery] = React.useState("");
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
  const countryLabel = countryInfo ? `${countryInfo.flag_emoji} ${countryInfo.name}` : "";
  const pinned = (home?.pinned ?? []).filter((row) => isPinned(row));
  const popular = home?.popular ?? [];

  return (
    <div className="space-y-4">
      {health && !health.ready ? (
        <Alert tone="warn" title="The catalogue is not fully live yet">
          {health.exchange_rate_configured
            ? "Our provider connection is being set up. Prices and availability appear here as soon as it is."
            : "Pricing is being configured. Nothing can be purchased until it is complete."}
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <ChannelTabs voiceAvailable={Boolean(home?.voice_available)} />
        <CountrySwitch
          countries={home?.countries ?? []}
          value={activeCountry}
          onChange={changeCountry}
        />
      </div>

      <div className="relative">
        <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
        <Input
          type="search"
          inputMode="search"
          aria-label="Search services"
          placeholder="Search services..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-12 pl-11 text-base"
        />
      </div>

      {!searching && pinned.length > 0 ? (
        <Section title="Pinned" count={pinned.length}>
          {pinned.map((row) => (
            <ServiceRow
              key={`pin-${row.slug}`}
              row={row}
              pinned={isPinned(row)}
              countryLabel={countryLabel}
              onOpen={() => setBuying(row.slug)}
              onPin={() => togglePin(row)}
            />
          ))}
        </Section>
      ) : null}

      {!searching && popular.length > 0 ? (
        <Section title="Popular" count={popular.length}>
          {popular.map((row) => (
            <ServiceRow
              key={`pop-${row.slug}`}
              row={row}
              pinned={isPinned(row)}
              countryLabel={countryLabel}
              onOpen={() => setBuying(row.slug)}
              onPin={() => togglePin(row)}
            />
          ))}
        </Section>
      ) : null}

      <Section
        title={searching ? "Results" : "All services"}
        count={list.data ? total : undefined}
      >
        {!list.data && !list.error ? (
          <RowSkeletons />
        ) : list.error ? (
          <EmptyState
            icon={<SearchIcon />}
            title="We could not load the services"
            description="Check your connection and try again."
            action={<Button onClick={() => list.mutate()}>Retry</Button>}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<SearchIcon />}
            title={searching ? `Nothing matches "${query}"` : "Nothing available here right now"}
            description={
              searching
                ? "Try another name - for example Gmail, X or WhatsApp."
                : (home?.countries.length ?? 0) > 1
                  ? "Try the other country, or check back shortly."
                  : "Please check back shortly."
            }
          />
        ) : (
          rows.map((row) => (
            <ServiceRow
              key={row.slug}
              row={row}
              pinned={isPinned(row)}
              countryLabel={countryLabel}
              onOpen={() => setBuying(row.slug)}
              onPin={() => togglePin(row)}
            />
          ))
        )}
      </Section>

      {hasMore ? (
        <div className="flex justify-center">
          <Button
            variant="secondary"
            loading={list.isValidating}
            onClick={() => list.setSize(list.size + 1)}
          >
            Load more
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

function ChannelTabs({ voiceAvailable }: { voiceAvailable: boolean }) {
  return (
    <div className="inline-flex w-fit rounded-xl border border-line bg-surface p-1" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected
        className="rounded-lg bg-brand-600 px-4 py-1.5 text-sm font-medium text-white"
      >
        SMS
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={false}
        disabled
        title={voiceAvailable ? "Voice verification is coming soon" : "Coming soon"}
        className="flex cursor-not-allowed items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium text-ink-faint"
      >
        Voice
        <span className="rounded-md bg-line/70 px-1.5 py-0.5 text-2xs font-medium text-ink-muted">
          Soon
        </span>
      </button>
    </div>
  );
}

function CountrySwitch({
  countries,
  value,
  onChange,
}: {
  countries: MarketHome["countries"];
  value: string;
  onChange: (code: string) => void;
}) {
  if (countries.length === 0) return <Skeleton className="h-10 w-64 rounded-xl" />;
  if (countries.length === 1) {
    // Nothing to switch between: just say where the numbers are from.
    const [only] = countries;
    return (
      <p className="inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-3.5 py-2 text-sm font-medium text-ink">
        <span aria-hidden>{only.flag_emoji}</span>
        {only.name} numbers
      </p>
    );
  }
  return (
    <div
      className="grid w-full grid-cols-2 rounded-xl border border-line bg-surface p-1 sm:w-auto"
      role="radiogroup"
      aria-label="Country"
    >
      {countries.map((country) => (
        <button
          key={country.code}
          type="button"
          role="radio"
          aria-checked={value === country.code}
          onClick={() => onChange(country.code)}
          className={cn(
            "flex items-center justify-center gap-2 rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors",
            value === country.code ? "bg-ink text-white" : "text-ink-soft hover:bg-canvas",
          )}
        >
          <span aria-hidden>{country.flag_emoji}</span>
          {country.name}
        </button>
      ))}
    </div>
  );
}

function Section({
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
      <div className="mb-1.5 flex items-baseline justify-between px-1">
        <h2 className="text-2xs font-semibold uppercase tracking-[0.08em] text-ink-muted">
          {title}
        </h2>
        {count !== undefined ? <span className="text-2xs text-ink-faint">{count}</span> : null}
      </div>
      <Card className="divide-y divide-line overflow-hidden">{children}</Card>
    </section>
  );
}

function ServiceRow({
  row,
  pinned,
  countryLabel,
  onOpen,
  onPin,
}: {
  row: MarketRow;
  pinned: boolean;
  countryLabel: string;
  onOpen: () => void;
  onPin: () => void;
}) {
  const paused = Boolean(row.temporarily_unavailable);
  const unavailable = row.availability === "UNAVAILABLE" || row.unavailable_here || paused;
  return (
    <div className="group flex items-center gap-1 pr-1.5 transition-colors hover:bg-canvas">
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-[3.5rem] min-w-0 flex-1 items-center gap-3 py-2 pl-3.5 text-left sm:pl-4"
      >
        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="sm" />
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              "block truncate text-sm font-medium",
              unavailable ? "text-ink-muted" : "text-ink",
            )}
          >
            {row.name}
          </span>
          {paused ? (
            <TemporarilyUnavailableBadge className="mt-0.5 sm:hidden" />
          ) : (
            <AvailabilityLabel
              availability={row.unavailable_here ? "UNAVAILABLE" : row.availability}
              count={row.available_count}
              className="sm:hidden"
            />
          )}
        </span>
        <span className="hidden w-36 shrink-0 truncate text-xs text-ink-muted lg:block">
          {countryLabel}
        </span>
        {paused ? (
          <span className="hidden w-32 shrink-0 sm:inline-flex">
            <TemporarilyUnavailableBadge />
          </span>
        ) : (
          <AvailabilityLabel
            availability={row.unavailable_here ? "UNAVAILABLE" : row.availability}
            count={row.available_count}
            className="hidden w-32 shrink-0 sm:inline-flex"
          />
        )}
        <span
          className={cn(
            "tabular w-20 shrink-0 text-right text-sm font-semibold",
            unavailable ? "text-ink-faint" : "text-ink",
          )}
        >
          {row.price && !row.unavailable_here && !paused ? cedis(row.price) : "-"}
        </span>
      </button>
      <button
        type="button"
        onClick={onPin}
        aria-pressed={pinned}
        aria-label={pinned ? `Unpin ${row.name}` : `Pin ${row.name}`}
        className={cn(
          "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-[color,transform] duration-150 active:scale-90",
          pinned ? "text-brand-600" : "text-ink-faint hover:text-ink-soft",
        )}
      >
        <PinIcon filled={pinned} className="h-[1.1rem] w-[1.1rem]" />
      </button>
    </div>
  );
}

function RowSkeletons() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="flex min-h-[3.5rem] items-center gap-3 px-4">
          <Skeleton className="h-8 w-8 rounded-lg" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-14" />
        </div>
      ))}
    </>
  );
}
