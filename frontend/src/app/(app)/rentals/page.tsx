"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { AppHero } from "@/components/app-hero";
import {
  CheckCircleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  GlobeIcon,
  InboxIcon,
  MessageIcon,
  PhoneIcon,
  SearchIcon,
  ShieldIcon,
  StarIcon,
} from "@/components/icons";
import { RentalLogo, RentalStatusBadge, timeLeft, useSecondsLeft } from "@/components/rentals/rental-ui";
import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  LoadError,
  Skeleton,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { cedis, groupInternational } from "@/lib/format";
import type {
  Paginated,
  Rental,
  RentalCatalog,
  RentalDuration,
  RentalOptions,
  RentalSummary,
  Wallet,
} from "@/lib/types";

export default function RentalsPage() {
  // useSearchParams needs a boundary, or the page cannot be prerendered.
  return (
    <React.Suspense fallback={<Skeleton className="h-64 w-full rounded-3xl" />}>
      <Rentals />
    </React.Suspense>
  );
}

/** Logo URLs by service slug, from the rental catalogue (shared, fetched once). */
function useIcons(): Record<string, string> {
  const { data } = useSWR<RentalCatalog>("/rentals/services/");
  return React.useMemo(
    () => Object.fromEntries((data?.services ?? []).map((entry) => [entry.slug, entry.icon_url])),
    [data],
  );
}

/** The length chosen for you when an app is picked: a month is what most people want. */
const DEFAULT_DAYS = 30;

function Rentals() {
  const params = useSearchParams();
  const open = useSWR<Paginated<RentalSummary>>(["/rentals/", { filter: "active", page_size: 50 }]);
  const active = open.data?.results ?? [];

  return (
    <div className="space-y-8">
      <AppHero
        eyebrow={
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-2xs font-semibold uppercase tracking-wider text-aqua ring-1 ring-white/15">
            <ClockIcon className="h-3.5 w-3.5" />
            Number rentals
          </span>
        }
        title="Keep a number for days, not minutes"
        description="Rent a US number for 1 to 90 days. Log in again, recover an account, or get codes from every app - each SMS lands in your inbox here within seconds."
        aside={<InboxPreview />}
      >
        <ul className="mt-5 flex flex-wrap gap-2">
          {[
            { icon: <InboxIcon className="h-4 w-4" />, text: "Every SMS in one inbox" },
            { icon: <ClockIcon className="h-4 w-4" />, text: "1 day to 3 months" },
            { icon: <ShieldIcon className="h-4 w-4" />, text: "Refund if it isn't set up" },
          ].map((item) => (
            <li
              key={item.text}
              className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.07] px-3 py-1.5 text-caption font-medium text-white/85 ring-1 ring-white/10"
            >
              <span className="text-aqua">{item.icon}</span>
              {item.text}
            </li>
          ))}
        </ul>
      </AppHero>

      {open.error && !open.data ? (
        <Card>
          <LoadError what="your rentals" onRetry={() => open.mutate()} />
        </Card>
      ) : active.length > 0 ? (
        <section aria-labelledby="your-numbers">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 id="your-numbers" className="text-heading text-ink">
              Your rented numbers
            </h2>
            <p className="text-caption text-ink-muted">
              {active.length} {active.length === 1 ? "number" : "numbers"}
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {active.map((rental) => (
              <ActiveRentalCard key={rental.id} rental={rental} />
            ))}
          </div>
        </section>
      ) : null}

      <RentBuilder initialService={params.get("service")} />

      <HowItWorks />

      <EndedRentals />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Hero art                                                            */
/* ------------------------------------------------------------------ */

/** What a rental looks like once it is yours. Illustrative, and labelled so. */
function InboxPreview() {
  const icons = useIcons();
  const messages = [
    { app: "WhatsApp", slug: "whatsapp", text: "Your WhatsApp code: 482-913", ago: "now" },
    { app: "Telegram", slug: "telegram", text: "Login code: 70361. Do not give it to anyone.", ago: "2h" },
    { app: "Google", slug: "google", text: "G-551204 is your Google verification code.", ago: "1d" },
  ];
  return (
    // Phones go straight to the form: the example is for wider screens.
    <div className="relative mx-auto hidden w-full max-w-sm md:block" aria-label="Example of a rented number's inbox">
      <div className="absolute -inset-6 rounded-[2rem] bg-linear-to-br from-azure/25 via-aqua/10 to-leaf/20 blur-2xl" aria-hidden />
      <div className="relative rounded-3xl border border-white/10 bg-white/6 p-4 backdrop-blur-md">
        <div className="flex items-center justify-between gap-3">
          <span className="text-2xs font-semibold uppercase tracking-wider text-white/50">Example inbox</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-leaf/15 px-2 py-0.5 text-2xs font-semibold text-leaf">
            <span className="relative flex h-1.5 w-1.5" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-current" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
            </span>
            29 days left
          </span>
        </div>
        <p className="tabular mt-2 text-xl font-bold tracking-tight text-white">+1 (555) 014-2289</p>
        <ul className="mt-3 space-y-2">
          {messages.map((message, index) => (
            <li
              key={message.slug}
              className="rise-in flex items-start gap-2.5 rounded-2xl bg-white/8 p-2.5 ring-1 ring-white/10"
              style={{ animationDelay: `${200 + index * 180}ms` }}
            >
              <ServiceLogo name={message.app} src={icons[message.slug]} slug={message.slug} size="xs" />
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="text-caption font-semibold text-white">{message.app}</span>
                  <span className="text-2xs text-white/45">{message.ago}</span>
                </span>
                <span className="block truncate text-caption text-white/65">{message.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Your numbers                                                        */
/* ------------------------------------------------------------------ */

function ActiveRentalCard({ rental }: { rental: RentalSummary }) {
  const left = useSecondsLeft(rental.seconds_remaining);
  const total = rental.days * 86_400;
  const share = rental.status === "ACTIVE" && total > 0 ? Math.min(100, Math.max(2, (left / total) * 100)) : 0;
  const urgent = rental.status === "ACTIVE" && left < 86_400;

  return (
    <Link
      href={`/rentals/${rental.reference}`}
      className="group flex flex-col rounded-2xl border border-line bg-surface p-4 shadow-card transition-all hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-raised"
    >
      <div className="flex items-start gap-3">
        <RentalLogo rental={rental} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">
            {rental.all_services ? "Any app" : rental.service_name}
          </p>
          <p className="tabular truncate text-caption text-ink-muted">
            {rental.phone_number ? groupInternational(rental.phone_number, "+1") : "Number on its way…"}
          </p>
        </div>
        <RentalStatusBadge status={rental.status} />
      </div>

      {rental.status === "ACTIVE" ? (
        <div className="mt-4">
          <div className="h-1.5 overflow-hidden rounded-full bg-sunken">
            <div
              className={cn("h-full rounded-full transition-[width] duration-700", urgent ? "bg-warn-500" : "bg-brand-500")}
              style={{ width: `${share}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-caption">
            <span className={cn("tabular font-medium", urgent ? "text-warn-700" : "text-ink-soft")}>{timeLeft(left)}</span>
            <span className="inline-flex items-center gap-1 text-ink-muted">
              <MessageIcon className="h-3.5 w-3.5" />
              {rental.message_count} {rental.message_count === 1 ? "message" : "messages"}
            </span>
          </div>
        </div>
      ) : (
        <p className="mt-4 text-caption text-ink-muted">Setting up - this usually takes a few seconds.</p>
      )}

      <span className="mt-3 inline-flex items-center gap-1 text-caption font-semibold text-brand-700">
        Open inbox
        <ChevronRightIcon className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}

/* ------------------------------------------------------------------ */
/* Renting                                                             */
/* ------------------------------------------------------------------ */

type Mode = "app" | "all";

function perDay(duration: RentalDuration): number | null {
  if (!duration.available || !duration.price) return null;
  return Number.parseFloat(duration.price) / duration.days;
}

function RentBuilder({ initialService }: { initialService: string | null }) {
  const router = useRouter();
  const toast = useToast();
  const [mode, setMode] = React.useState<Mode>(initialService === "all" ? "all" : "app");
  const [service, setService] = React.useState<string | null>(
    initialService && initialService !== "all" ? initialService : null,
  );
  const [query, setQuery] = React.useState("");
  const [showAll, setShowAll] = React.useState(false);
  const [days, setDays] = React.useState<number | null>(null);
  const [confirming, setConfirming] = React.useState(false);

  const catalog = useSWR<RentalCatalog>("/rentals/services/");
  const target = mode === "all" ? "all" : service;
  const options = useSWR<RentalOptions>(target ? ["/rentals/options/", { service: target }] : null);
  const { data: wallet } = useSWR<Wallet>("/wallet/");
  const icons = useIcons();

  // A new app: start on a month if it is sold, else the first length that is.
  const durations = options.data?.durations;
  React.useEffect(() => {
    if (!durations) {
      setDays(null);
      return;
    }
    const preferred = durations.find((entry) => entry.days === DEFAULT_DAYS && entry.available);
    setDays((preferred ?? durations.find((entry) => entry.available))?.days ?? null);
  }, [durations]);

  const services = React.useMemo(() => catalog.data?.services ?? [], [catalog.data]);
  const chosen = services.find((entry) => entry.slug === service);
  const duration = durations?.find((entry) => entry.days === days && entry.available);
  const bestValue = React.useMemo(() => {
    const priced = (durations ?? []).filter((entry) => perDay(entry) !== null);
    if (priced.length < 2) return null;
    return priced.reduce((best, entry) => ((perDay(entry) ?? 0) < (perDay(best) ?? 0) ? entry : best)).days;
  }, [durations]);

  const matches = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return services.slice(0, showAll ? 60 : 12);
    return services.filter((entry) => entry.name.toLowerCase().includes(needle)).slice(0, 30);
  }, [services, query, showAll]);

  if (catalog.error && !catalog.data) {
    const unavailable = catalog.error instanceof ApiError && catalog.error.code === "RENTALS_UNAVAILABLE";
    return (
      <Card>
        {unavailable ? (
          <EmptyState icon={<PhoneIcon />} title="Rentals are paused" description={catalog.error.message} />
        ) : (
          <LoadError what="rental options" onRetry={() => catalog.mutate()} />
        )}
      </Card>
    );
  }

  const name = mode === "all" ? "Any app" : (chosen?.name ?? options.data?.service_name ?? "");
  const ready = Boolean(target && duration?.price);

  return (
    <section aria-labelledby="rent-heading">
      <h2 id="rent-heading" className="mb-3 text-heading text-ink">
        Rent a new number
      </h2>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
        <Card className="overflow-hidden">
          {/* 1 · What for */}
          <div className="p-4 sm:p-6">
            <StepTitle step={1} title="What will you use it for?" done={Boolean(target)} />
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <ModeCard
                active={mode === "app"}
                onClick={() => setMode("app")}
                art={
                  <span className="flex -space-x-2">
                    {["whatsapp", "telegram", "google"].map((slug) => (
                      <span key={slug} className="rounded-lg ring-2 ring-surface">
                        <ServiceLogo name={slug} src={icons[slug]} slug={slug} size="xs" />
                      </span>
                    ))}
                  </span>
                }
                title="One app"
                body="A number for a single app, such as WhatsApp or Telegram."
                note="Cheapest"
              />
              <ModeCard
                active={mode === "all"}
                onClick={() => setMode("all")}
                art={
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-linear-to-br from-azure to-leaf text-white">
                    <GlobeIcon className="h-4 w-4" />
                  </span>
                }
                title="Any app"
                body="One number that receives messages from every app and sender."
                note="Most flexible"
              />
            </div>

            {mode === "app" ? (
              <div className="mt-5">
                {chosen ? (
                  <div className="flex items-center justify-between gap-3 rounded-2xl border border-brand-200 bg-brand-50/60 p-3">
                    <span className="flex min-w-0 items-center gap-3">
                      <ServiceLogo name={chosen.name} src={chosen.icon_url} slug={chosen.slug} size="md" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-ink">{chosen.name}</span>
                        <span className="block text-caption text-ink-muted">Receives {chosen.name} messages</span>
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setService(null);
                        setQuery("");
                      }}
                    >
                      Change
                    </Button>
                  </div>
                ) : (
                  <>
                    <div className="relative">
                      <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
                      <input
                        type="search"
                        aria-label="Search apps"
                        placeholder={`Search ${services.length ? services.length.toLocaleString() : ""} apps…`}
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        className="h-12 w-full rounded-2xl border border-line bg-sunken/50 pl-12 pr-4 text-base text-ink placeholder:text-ink-faint transition-colors focus:border-brand-400 focus:bg-surface focus:outline-hidden focus:ring-2 focus:ring-brand-500/25"
                      />
                    </div>
                    {!catalog.data ? (
                      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {Array.from({ length: 6 }).map((_, index) => (
                          <Skeleton key={index} className="h-14 rounded-xl" />
                        ))}
                      </div>
                    ) : matches.length === 0 ? (
                      <div className="mt-4 rounded-2xl border border-dashed border-line p-5 text-center">
                        <p className="text-sm font-medium text-ink">No app called “{query}”</p>
                        <p className="mt-1 text-caption text-ink-muted">
                          Try another spelling, or rent an{" "}
                          <button type="button" className="font-semibold text-brand-700 underline" onClick={() => setMode("all")}>
                            any-app number
                          </button>{" "}
                          that works everywhere.
                        </p>
                      </div>
                    ) : (
                      <>
                        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                          {matches.map((entry) => (
                            <button
                              key={entry.slug}
                              type="button"
                              onClick={() => setService(entry.slug)}
                              className="flex min-h-14 items-center gap-2.5 rounded-xl border border-line bg-surface px-3 py-2 text-left transition-all hover:-translate-y-px hover:border-brand-300 hover:shadow-card"
                            >
                              <ServiceLogo name={entry.name} src={entry.icon_url} slug={entry.slug} size="sm" />
                              <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{entry.name}</span>
                              {entry.is_popular && !query ? (
                                <StarIcon className="h-3.5 w-3.5 shrink-0 text-gold-500" aria-label="Popular" />
                              ) : null}
                            </button>
                          ))}
                        </div>
                        {!query && services.length > matches.length ? (
                          <button
                            type="button"
                            onClick={() => setShowAll((value) => !value)}
                            className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline"
                          >
                            {showAll ? "Show fewer" : "Show more apps"}
                            <ChevronDownIcon className={cn("h-4 w-4 transition-transform", showAll && "rotate-180")} />
                          </button>
                        ) : null}
                      </>
                    )}
                  </>
                )}
              </div>
            ) : null}
          </div>

          {/* 2 · How long */}
          <div className={cn("border-t border-line p-4 sm:p-6", !target && "opacity-60")}>
            <StepTitle step={2} title="For how long?" done={Boolean(duration)} />
            {!target ? (
              <p className="mt-3 text-sm text-ink-muted">Choose an app first to see the prices.</p>
            ) : options.error && !options.data ? (
              <Alert tone="warn" className="mt-4" title="Prices unavailable">
                {options.error instanceof ApiError ? options.error.message : "We could not price this right now."}{" "}
                <button type="button" className="font-semibold underline" onClick={() => options.mutate()}>
                  Try again
                </button>
              </Alert>
            ) : !durations ? (
              <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                {Array.from({ length: 6 }).map((_, index) => (
                  <Skeleton key={index} className="h-24 rounded-2xl" />
                ))}
              </div>
            ) : durations.every((entry) => !entry.available) ? (
              <p className="mt-3 text-sm text-ink-muted">
                {options.data?.service_name} numbers can&apos;t be rented right now. Try another app, or an any-app number.
              </p>
            ) : (
              <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3" role="radiogroup" aria-label="Rental length">
                {durations.map((entry) => {
                  const selected = entry.days === days;
                  const daily = perDay(entry);
                  const tag = entry.days === DEFAULT_DAYS ? "Popular" : entry.days === bestValue ? "Best value" : null;
                  return (
                    <button
                      key={entry.days}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={!entry.available}
                      onClick={() => setDays(entry.days)}
                      className={cn(
                        "relative flex min-h-24 flex-col justify-between rounded-2xl border p-3.5 text-left transition-all",
                        selected
                          ? "border-brand-500 bg-brand-50 shadow-raised ring-2 ring-brand-500/30"
                          : "border-line bg-surface hover:-translate-y-px hover:border-brand-300 hover:shadow-card",
                        !entry.available && "cursor-not-allowed opacity-45 hover:translate-y-0 hover:border-line hover:shadow-none",
                      )}
                    >
                      {tag && entry.available ? (
                        <span
                          className={cn(
                            "absolute -top-2 right-3 rounded-full px-2 py-0.5 text-2xs font-bold uppercase tracking-wide",
                            tag === "Popular" ? "bg-brand-600 text-white" : "bg-gold-100 text-gold-700",
                          )}
                        >
                          {tag}
                        </span>
                      ) : null}
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-ink">{entry.label}</span>
                        {selected ? <CheckCircleIcon className="h-4 w-4 text-brand-600" /> : null}
                      </span>
                      <span>
                        <span className="tabular block text-lg font-bold tracking-tight text-ink">
                          {entry.available && entry.price ? cedis(entry.price) : "—"}
                        </span>
                        <span className="tabular block text-2xs text-ink-muted">
                          {daily !== null ? `${cedis(daily)} a day` : (entry.note ?? "Not offered")}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Card>

        {/* Summary: sticky beside the builder from lg */}
        <div className="hidden lg:sticky lg:top-24 lg:block">
          <Summary
            name={name}
            mode={mode}
            chosen={chosen}
            duration={ready ? duration : undefined}
            wallet={wallet}
            onRent={() => setConfirming(true)}
          />
        </div>
      </div>

      {/* Phones: the price and the button stay in reach above the tab bar */}
      {ready && duration?.price ? (
        <>
          <div className="h-20 lg:hidden" aria-hidden />
          <div
            className="fixed inset-x-0 z-30 border-t border-line bg-surface/95 px-4 py-3 shadow-pop backdrop-blur-sm lg:hidden"
            style={{ bottom: "calc(4rem + var(--safe-bottom, 0px))" }}
          >
            <div className="mx-auto flex max-w-lg items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-caption text-ink-muted">
                  {name} · {duration.label}
                </p>
                <p className="tabular text-lg font-bold leading-tight text-ink">{cedis(duration.price)}</p>
              </div>
              <Button onClick={() => setConfirming(true)} className="shrink-0">
                Rent now
              </Button>
            </div>
          </div>
        </>
      ) : null}

      {ready && duration?.price && target ? (
        <ConfirmRental
          open={confirming}
          onClose={() => setConfirming(false)}
          target={target}
          name={name}
          mode={mode}
          chosen={chosen}
          days={duration.days}
          label={duration.label}
          price={duration.price}
          wallet={wallet}
          onPriceChanged={() => options.mutate()}
          onRented={(rental) => {
            toast.success("Number on its way", `${name} - ${rental.reference}`);
            router.push(`/rentals/${rental.reference}`);
          }}
        />
      ) : null}
    </section>
  );
}

function StepTitle({ step, title, done }: { step: number; title: string; done?: boolean }) {
  return (
    <h3 className="flex items-center gap-2.5 text-base font-semibold text-ink">
      <span
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-full text-caption font-bold transition-colors",
          done ? "bg-brand-600 text-white" : "bg-ink text-canvas",
        )}
      >
        {done ? <CheckCircleIcon className="h-4 w-4" /> : step}
      </span>
      {title}
    </h3>
  );
}

function ModeCard({
  active,
  onClick,
  art,
  title,
  body,
  note,
}: {
  active: boolean;
  onClick: () => void;
  art: React.ReactNode;
  title: string;
  body: string;
  note: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex flex-col gap-3 rounded-2xl border p-4 text-left transition-all",
        active
          ? "border-brand-500 bg-brand-50 shadow-raised ring-2 ring-brand-500/30"
          : "border-line bg-surface hover:-translate-y-px hover:border-brand-300 hover:shadow-card",
      )}
    >
      <span className="flex items-center justify-between gap-2">
        {art}
        <span
          className={cn(
            "flex h-5 w-5 items-center justify-center rounded-full border-2 transition-colors",
            active ? "border-brand-600 bg-brand-600" : "border-line-strong",
          )}
          aria-hidden
        >
          {active ? <span className="h-1.5 w-1.5 rounded-full bg-white" /> : null}
        </span>
      </span>
      <span>
        <span className="flex items-center gap-2">
          <span className="text-sm font-semibold text-ink">{title}</span>
          <span className="rounded-full bg-sunken px-2 py-0.5 text-2xs font-medium text-ink-muted">{note}</span>
        </span>
        <span className="mt-1 block text-caption leading-relaxed text-ink-muted">{body}</span>
      </span>
    </button>
  );
}

type ServiceChoice = RentalCatalog["services"][number] | undefined;

function Summary({
  name,
  mode,
  chosen,
  duration,
  wallet,
  onRent,
}: {
  name: string;
  mode: Mode;
  chosen: ServiceChoice;
  duration?: RentalDuration;
  wallet?: Wallet;
  onRent: () => void;
}) {
  const pesewas = (amount: string) => Math.round(Number.parseFloat(amount) * 100);
  const after = wallet && duration?.price ? (pesewas(wallet.spendable) - pesewas(duration.price)) / 100 : null;
  const short = after !== null && after < 0;
  const daily = duration ? perDay(duration) : null;

  return (
    <Card className="overflow-hidden">
      <div className="bg-linear-to-br from-brand-50 via-surface to-surface p-5">
        <p className="text-caption font-medium text-ink-muted">Your rental</p>
        {name ? (
          <div className="mt-3 flex items-center gap-3">
            <RentalLogo
              rental={{
                all_services: mode === "all",
                service_name: name,
                service_icon: chosen?.icon_url ?? "",
                service_slug: chosen?.slug ?? "all",
              }}
            />
            <div className="min-w-0">
              <p className="truncate font-semibold text-ink">{mode === "all" ? "Any-app number" : `${name} number`}</p>
              <p className="text-caption text-ink-muted">{duration ? duration.label : "Choose a length"}</p>
            </div>
          </div>
        ) : (
          <p className="mt-3 text-sm text-ink-muted">Choose an app and a length to see your price.</p>
        )}
        {duration?.price ? (
          <div className="mt-5">
            <p className="tabular text-3xl font-extrabold tracking-tight text-ink">{cedis(duration.price)}</p>
            {daily !== null ? <p className="tabular text-caption text-ink-muted">{cedis(daily)} a day · paid once</p> : null}
          </div>
        ) : null}
      </div>

      <div className="space-y-4 border-t border-line p-5">
        {wallet && duration?.price ? (
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <dt className="text-ink-muted">Your balance</dt>
              <dd className="tabular text-ink">{cedis(wallet.spendable)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-muted">After paying</dt>
              <dd className={cn("tabular font-semibold", short ? "text-danger-700" : "text-ink")}>{cedis(after ?? 0)}</dd>
            </div>
          </dl>
        ) : null}
        {short ? (
          <ButtonLink href="/wallet/deposit" fullWidth>
            Top up to rent
          </ButtonLink>
        ) : (
          <Button onClick={onRent} disabled={!duration?.price} fullWidth size="lg">
            {duration?.price ? `Rent for ${cedis(duration.price)}` : "Rent a number"}
          </Button>
        )}
        <ul className="space-y-2 text-caption text-ink-muted">
          <li className="flex gap-2">
            <CheckCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
            Full refund if the number can&apos;t be set up
          </li>
          <li className="flex gap-2">
            <CheckCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
            Never renews by itself - extend whenever you like
          </li>
          <li className="flex gap-2">
            <CheckCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
            Cancel for a refund while our provider allows
          </li>
        </ul>
      </div>
    </Card>
  );
}

/**
 * The last look before paying. The price sent back is the one shown, so the
 * server refuses (and charges nothing) if the provider's price moved meanwhile.
 */
function ConfirmRental({
  open,
  onClose,
  target,
  name,
  mode,
  chosen,
  days,
  label,
  price,
  wallet,
  onPriceChanged,
  onRented,
}: {
  open: boolean;
  onClose: () => void;
  target: string;
  name: string;
  mode: Mode;
  chosen: ServiceChoice;
  days: number;
  label: string;
  price: string;
  wallet?: Wallet;
  onPriceChanged: () => void;
  onRented: (rental: Rental) => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [blocker, setBlocker] = React.useState<{ code: string; message: string } | null>(null);
  // One key per opening: a double tap rents one number.
  const key = React.useRef(newIdempotencyKey());

  React.useEffect(() => {
    if (open) {
      key.current = newIdempotencyKey();
      setBlocker(null);
    }
  }, [open]);

  const pesewas = (amount: string) => Math.round(Number.parseFloat(amount) * 100);
  const after = wallet ? (pesewas(wallet.spendable) - pesewas(price)) / 100 : null;
  const short = after !== null && after < 0;

  async function pay() {
    setBusy(true);
    setBlocker(null);
    try {
      const rental = await api.post<Rental>(
        "/rentals/",
        { service: target, days, expected_price: price },
        { idempotencyKey: key.current },
      );
      await globalMutate((swrKey) => {
        const path = Array.isArray(swrKey) ? String(swrKey[0]) : String(swrKey);
        return path.startsWith("/wallet") || path.startsWith("/rentals") || path.startsWith("/transactions");
      });
      onClose();
      onRented(rental);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "PRICE_CHANGED") onPriceChanged();
      setBlocker(
        caught instanceof ApiError
          ? { code: caught.code, message: caught.message }
          : { code: "UNKNOWN", message: "Something went wrong. Please try again." },
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="Confirm your rental"
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Not now
          </Button>
          {short || blocker?.code === "INSUFFICIENT_FUNDS" ? (
            <ButtonLink href="/wallet/deposit">Top up wallet</ButtonLink>
          ) : (
            <Button onClick={pay} loading={busy} disabled={blocker?.code === "PRICE_CHANGED"}>
              Pay {cedis(price)}
            </Button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex items-center gap-3 rounded-2xl bg-sunken/60 p-3.5">
          <RentalLogo
            rental={{
              all_services: mode === "all",
              service_name: name,
              service_icon: chosen?.icon_url ?? "",
              service_slug: chosen?.slug ?? "all",
            }}
          />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-ink">{mode === "all" ? "Any-app number" : `${name} number`}</p>
            <p className="text-caption text-ink-muted">US mobile number · {label}</p>
          </div>
          <p className="tabular text-lg font-bold text-ink">{cedis(price)}</p>
        </div>

        {wallet ? (
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <dt className="text-ink-muted">Your balance</dt>
              <dd className="tabular text-ink">{cedis(wallet.spendable)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-muted">After paying</dt>
              <dd className={cn("tabular font-semibold", short ? "text-danger-700" : "text-ink")}>{cedis(after ?? 0)}</dd>
            </div>
          </dl>
        ) : null}

        {blocker ? (
          <Alert
            tone={blocker.code === "PRICE_CHANGED" ? "warn" : "danger"}
            title={blocker.code === "PRICE_CHANGED" ? "The price changed" : "Not rented"}
          >
            {blocker.message}
            {blocker.code === "PRICE_CHANGED" ? " Close this and check the new price." : null}
          </Alert>
        ) : null}

        <div className="rounded-2xl border border-line p-3.5 text-caption text-ink-muted">
          <p className="flex gap-2">
            <ClockIcon className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              You can cancel for a full refund only while our provider allows it - usually shortly after renting,
              before any message arrives. Extensions can&apos;t be refunded.
            </span>
          </p>
        </div>
        <p className="text-caption text-ink-faint">
          By renting you agree to our{" "}
          <Link href="/terms" className="underline">
            Terms
          </Link>{" "}
          and{" "}
          <Link href="/acceptable-use" className="underline">
            Acceptable Use Policy
          </Link>
          .
        </p>
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/* How it works, questions, history                                    */
/* ------------------------------------------------------------------ */

function HowItWorks() {
  const steps = [
    { icon: <PhoneIcon className="h-5 w-5" />, title: "Choose and pay", body: "Pick an app (or any app) and a length. Paid once from your wallet." },
    { icon: <MessageIcon className="h-5 w-5" />, title: "Use the number", body: "Enter it in the app. Every SMS appears in its inbox here within seconds." },
    { icon: <ClockIcon className="h-5 w-5" />, title: "Extend or let it end", body: "Add more days any time. It never renews or charges you by itself." },
  ];
  const faqs = [
    {
      q: "How is this different from buying a number?",
      a: "A bought number is for one code and lasts about 20 minutes. A rented number is yours for days, so you can receive codes again - to log back in, reset a password or recover an account.",
    },
    {
      q: "Can I get my money back?",
      a: "If the number can't be set up, the full amount returns to your wallet automatically. After that you can cancel for a full refund while our provider allows it - usually shortly after renting and before any message arrives. Extensions can't be refunded.",
    },
    {
      q: "One app or any app - which should I pick?",
      a: "One app is cheaper and right if you need the number for a single service. Any app receives messages from every sender, which helps when you sign up to several services with the same number.",
    },
    {
      q: "What happens when the rental ends?",
      a: "The number stops receiving messages and may later be given to someone else. We remind you a day before so you can extend it. Messages it received stay on its page.",
    },
  ];
  return (
    <section aria-labelledby="how-heading" className="grid gap-5 lg:grid-cols-2">
      <Card className="p-5 sm:p-6">
        <h2 id="how-heading" className="text-heading text-ink">
          How renting works
        </h2>
        <ol className="mt-4 space-y-4">
          {steps.map((step, index) => (
            <li key={step.title} className="flex gap-3.5">
              <span className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                {step.icon}
                <span className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-ink text-2xs font-bold text-canvas">
                  {index + 1}
                </span>
              </span>
              <span>
                <span className="block text-sm font-semibold text-ink">{step.title}</span>
                <span className="block text-caption leading-relaxed text-ink-muted">{step.body}</span>
              </span>
            </li>
          ))}
        </ol>
      </Card>
      <Card className="p-5 sm:p-6">
        <h2 className="text-heading text-ink">Questions</h2>
        <div className="mt-2 divide-y divide-line">
          {faqs.map((faq) => (
            <details key={faq.q} className="group py-3">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-ink">
                {faq.q}
                <ChevronDownIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-open:rotate-180" />
              </summary>
              <p className="mt-2 text-caption leading-relaxed text-ink-muted">{faq.a}</p>
            </details>
          ))}
        </div>
      </Card>
    </section>
  );
}

function EndedRentals() {
  const [show, setShow] = React.useState(false);
  const ended = useSWR<Paginated<RentalSummary>>(show ? ["/rentals/", { filter: "ended", page_size: 50 }] : null);
  return (
    <section>
      <button
        type="button"
        onClick={() => setShow((value) => !value)}
        className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline"
        aria-expanded={show}
      >
        {show ? "Hide ended rentals" : "Show ended rentals"}
        <ChevronDownIcon className={cn("h-4 w-4 transition-transform", show && "rotate-180")} />
      </button>
      {show ? (
        <Card className="mt-3 overflow-hidden">
          {ended.error && !ended.data ? (
            <LoadError what="your ended rentals" onRetry={() => ended.mutate()} />
          ) : !ended.data ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : ended.data.results.length === 0 ? (
            <EmptyState icon={<ClockIcon />} title="No ended rentals" description="Rentals you cancel or that run their course appear here." />
          ) : (
            <ul className="divide-y divide-line">
              {ended.data.results.map((rental) => (
                <li key={rental.id}>
                  <Link
                    href={`/rentals/${rental.reference}`}
                    className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-sunken/60 sm:px-5"
                  >
                    <RentalLogo rental={rental} size="sm" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">
                        {rental.all_services ? "Any app" : rental.service_name} · {rental.duration_label}
                      </span>
                      <span className="tabular block truncate text-caption text-ink-muted">
                        {rental.phone_number ? groupInternational(rental.phone_number, "+1") : "No number"} · {cedis(rental.price)}
                      </span>
                    </span>
                    <RentalStatusBadge status={rental.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
    </section>
  );
}
