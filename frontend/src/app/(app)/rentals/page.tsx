"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { AppHero, HeroStat } from "@/components/app-hero";
import { CheckCircleIcon, ClockIcon, GlobeIcon, MessageIcon, PhoneIcon, SearchIcon } from "@/components/icons";
import { RentalLogo, RentalRow } from "@/components/rentals/rental-ui";
import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  DescriptionList,
  EmptyState,
  Input,
  LoadError,
  Skeleton,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { cedis } from "@/lib/format";
import type { Paginated, Rental, RentalCatalog, RentalOptions, RentalSummary, Wallet } from "@/lib/types";

export default function RentalsPage() {
  // useSearchParams needs a boundary, or the page cannot be prerendered.
  return (
    <React.Suspense fallback={<Skeleton className="h-64 w-full rounded-3xl" />}>
      <Rentals />
    </React.Suspense>
  );
}

/**
 * Rent a number: a US number kept for days rather than minutes, for one app or
 * for any app, with every SMS it receives in an inbox here. Above the form,
 * the numbers the customer already rents.
 */
function Rentals() {
  const params = useSearchParams();
  const [showEnded, setShowEnded] = React.useState(false);

  const open = useSWR<Paginated<RentalSummary>>(["/rentals/", { filter: "active", page_size: 50 }]);
  const ended = useSWR<Paginated<RentalSummary>>(
    showEnded ? ["/rentals/", { filter: "ended", page_size: 50 }] : null,
  );
  const active = open.data?.results ?? [];
  const messages = active.reduce((sum, rental) => sum + rental.message_count, 0);

  const stat = (value: number) =>
    open.isLoading ? <Skeleton className="mt-1 h-6 w-10" /> : open.error && !open.data ? "—" : value;

  return (
    <div className="space-y-6">
      <AppHero
        eyebrow="Number rentals"
        title="Rent a number"
        description="Keep a US number for days, not minutes. Every SMS it receives lands in its inbox here - log in again, recover an account, or receive codes from any app."
        aside={
          <div className="grid grid-cols-3 gap-2 sm:gap-2.5">
            <HeroStat label="Active" value={stat(active.filter((r) => r.status === "ACTIVE").length)} />
            <HeroStat label="Setting up" value={stat(active.filter((r) => r.status === "PENDING").length)} />
            <HeroStat label="Messages" value={stat(messages)} />
          </div>
        }
      />

      {open.error && !open.data ? (
        <Card>
          <LoadError what="your rentals" onRetry={() => open.mutate()} />
        </Card>
      ) : active.length > 0 ? (
        <Card className="overflow-hidden">
          <CardHeader title="Your rented numbers" />
          <div className="divide-y divide-line border-t border-line">
            {active.map((rental) => (
              <RentalRow key={rental.id} rental={rental} />
            ))}
          </div>
        </Card>
      ) : null}

      <RentForm initialService={params.get("service")} />

      <div>
        <button
          type="button"
          onClick={() => setShowEnded((value) => !value)}
          className="text-sm font-semibold text-brand-700 hover:underline"
          aria-expanded={showEnded}
        >
          {showEnded ? "Hide ended rentals" : "Show ended rentals"}
        </button>
        {showEnded ? (
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
              <div className="divide-y divide-line">
                {ended.data.results.map((rental) => (
                  <RentalRow key={rental.id} rental={rental} />
                ))}
              </div>
            )}
          </Card>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

type Mode = "app" | "all";

function RentForm({ initialService }: { initialService: string | null }) {
  const router = useRouter();
  const toast = useToast();
  const [mode, setMode] = React.useState<Mode>(initialService === "all" ? "all" : "app");
  const [service, setService] = React.useState<string | null>(
    initialService && initialService !== "all" ? initialService : null,
  );
  const [query, setQuery] = React.useState("");
  const [days, setDays] = React.useState<number | null>(null);
  const [confirming, setConfirming] = React.useState(false);

  const catalog = useSWR<RentalCatalog>("/rentals/services/");
  const target = mode === "all" ? "all" : service;
  const options = useSWR<RentalOptions>(target ? ["/rentals/options/", { service: target }] : null);
  const { data: wallet } = useSWR<Wallet>("/wallet/");

  // A new app or mode: choose the length again (its price may differ).
  React.useEffect(() => setDays(null), [target]);

  const chosen = catalog.data?.services.find((entry) => entry.slug === service);
  const duration = options.data?.durations.find((entry) => entry.days === days && entry.available);

  const matches = React.useMemo(() => {
    const all = catalog.data?.services ?? [];
    const needle = query.trim().toLowerCase();
    const found = needle ? all.filter((entry) => entry.name.toLowerCase().includes(needle)) : all;
    return found.slice(0, needle ? 30 : 18);
  }, [catalog.data, query]);

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

  return (
    <Card className="overflow-hidden">
      <CardHeader title="Rent a new number" />
      <div className="space-y-6 border-t border-line p-4 sm:p-6">
        {/* 1. What the number is for */}
        <section>
          <StepTitle step={1} title="What is the number for?" />
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <ModeCard
              active={mode === "app"}
              onClick={() => setMode("app")}
              icon={<MessageIcon className="h-5 w-5" />}
              title="One app"
              body="Receives messages from the app you choose, such as WhatsApp or Telegram."
            />
            <ModeCard
              active={mode === "all"}
              onClick={() => setMode("all")}
              icon={<GlobeIcon className="h-5 w-5" />}
              title="Any app"
              body="One number that receives messages from every app and sender."
            />
          </div>

          {mode === "app" ? (
            <div className="mt-4">
              {chosen ? (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-brand-200 bg-brand-50/50 px-3 py-2.5">
                  <span className="flex min-w-0 items-center gap-3">
                    <ServiceLogo name={chosen.name} src={chosen.icon_url} slug={chosen.slug} size="sm" />
                    <span className="truncate text-sm font-semibold text-ink">{chosen.name}</span>
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => setService(null)}>
                    Change
                  </Button>
                </div>
              ) : (
                <>
                  <div className="relative">
                    <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
                    <Input
                      type="search"
                      aria-label="Search apps"
                      placeholder="Search apps - WhatsApp, Telegram, Google…"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      className="pl-11"
                    />
                  </div>
                  {!catalog.data ? (
                    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {Array.from({ length: 6 }).map((_, index) => (
                        <Skeleton key={index} className="h-12 rounded-xl" />
                      ))}
                    </div>
                  ) : matches.length === 0 ? (
                    <p className="mt-3 text-sm text-ink-muted">
                      No app matches “{query}”. Try another name, or rent an <button type="button" className="font-semibold text-brand-700 underline" onClick={() => setMode("all")}>any-app number</button>.
                    </p>
                  ) : (
                    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {matches.map((entry) => (
                        <button
                          key={entry.slug}
                          type="button"
                          onClick={() => setService(entry.slug)}
                          className="flex min-h-12 items-center gap-2.5 rounded-xl border border-line bg-surface px-3 py-2 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40"
                        >
                          <ServiceLogo name={entry.name} src={entry.icon_url} slug={entry.slug} size="xs" />
                          <span className="truncate text-sm font-medium text-ink">{entry.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ) : null}
        </section>

        {/* 2. How long */}
        {target ? (
          <section>
            <StepTitle step={2} title="For how long?" />
            {options.error && !options.data ? (
              <Alert tone="warn" className="mt-3" title="Prices unavailable">
                {options.error instanceof ApiError ? options.error.message : "We could not price this right now."}{" "}
                <button type="button" className="font-semibold underline" onClick={() => options.mutate()}>
                  Try again
                </button>
              </Alert>
            ) : !options.data ? (
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {Array.from({ length: 6 }).map((_, index) => (
                  <Skeleton key={index} className="h-16 rounded-xl" />
                ))}
              </div>
            ) : options.data.durations.every((entry) => !entry.available) ? (
              <p className="mt-3 text-sm text-ink-muted">
                {options.data.service_name} numbers can&apos;t be rented right now. Try another app, or an
                any-app number.
              </p>
            ) : (
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Rental length">
                {options.data.durations.map((entry) => {
                  const selected = entry.days === days;
                  return (
                    <button
                      key={entry.days}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={!entry.available}
                      onClick={() => setDays(entry.days)}
                      className={cn(
                        "flex min-h-16 flex-col items-start justify-center rounded-xl border px-3.5 py-2.5 text-left transition-colors",
                        selected
                          ? "border-brand-500 bg-brand-50 ring-2 ring-brand-500/30"
                          : "border-line bg-surface hover:border-brand-300",
                        !entry.available && "cursor-not-allowed opacity-50 hover:border-line",
                      )}
                    >
                      <span className="text-sm font-semibold text-ink">{entry.label}</span>
                      <span className="tabular text-caption text-ink-muted">
                        {entry.available && entry.price ? cedis(entry.price) : (entry.note ?? "Not offered")}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        ) : null}

        {/* 3. Pay */}
        {duration && duration.price ? (
          <section className="flex flex-col gap-3 rounded-2xl bg-sunken/60 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <RentalLogo
                rental={{
                  all_services: mode === "all",
                  service_name: options.data?.service_name ?? "",
                  service_icon: chosen?.icon_url ?? "",
                  service_slug: chosen?.slug ?? "all",
                }}
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-ink">
                  {options.data?.service_name} number, {duration.label}
                </p>
                <p className="tabular text-caption text-ink-muted">
                  {cedis(duration.price)}
                  {wallet ? ` · balance ${cedis(wallet.spendable)}` : ""}
                </p>
              </div>
            </div>
            <Button onClick={() => setConfirming(true)} className="w-full shrink-0 sm:w-auto">
              Rent for {cedis(duration.price)}
            </Button>
          </section>
        ) : null}
      </div>

      {duration && duration.price && target ? (
        <ConfirmRental
          open={confirming}
          onClose={() => setConfirming(false)}
          target={target}
          name={options.data?.service_name ?? ""}
          days={duration.days}
          label={duration.label}
          price={duration.price}
          wallet={wallet}
          onPriceChanged={() => options.mutate()}
          onRented={(rental) => {
            toast.success("Number on its way", `${rental.service_name} - ${rental.reference}`);
            router.push(`/rentals/${rental.reference}`);
          }}
        />
      ) : null}
    </Card>
  );
}

function StepTitle({ step, title }: { step: number; title: string }) {
  return (
    <h3 className="flex items-center gap-2.5 text-sm font-semibold text-ink">
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink text-2xs font-bold text-canvas">
        {step}
      </span>
      {title}
    </h3>
  );
}

function ModeCard({
  active,
  onClick,
  icon,
  title,
  body,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex items-start gap-3 rounded-xl border p-3.5 text-left transition-colors",
        active ? "border-brand-500 bg-brand-50 ring-2 ring-brand-500/30" : "border-line bg-surface hover:border-brand-300",
      )}
    >
      <span
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          active ? "bg-brand-600 text-white" : "bg-sunken text-ink-soft",
        )}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          {title}
          {active ? <CheckCircleIcon className="h-4 w-4 text-brand-600" /> : null}
        </span>
        <span className="mt-0.5 block text-caption text-ink-muted">{body}</span>
      </span>
    </button>
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
      title="Rent this number?"
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
        <DescriptionList
          items={[
            { label: "Number for", value: name },
            { label: "Length", value: label },
            { label: "Price", value: <span className="tabular">{cedis(price)}</span>, emphasis: true },
            ...(wallet
              ? [
                  { label: "Your balance", value: <span className="tabular">{cedis(wallet.spendable)}</span> },
                  {
                    label: "After paying",
                    value: <span className={cn("tabular", short && "text-danger-700")}>{cedis(after ?? 0)}</span>,
                  },
                ]
              : []),
          ]}
        />
        {blocker ? (
          <Alert tone={blocker.code === "PRICE_CHANGED" ? "warn" : "danger"} title={blocker.code === "PRICE_CHANGED" ? "The price changed" : "Not rented"}>
            {blocker.message}
            {blocker.code === "PRICE_CHANGED" ? " Close this and choose the length again to see the new price." : null}
          </Alert>
        ) : null}
        <ul className="space-y-2 text-caption text-ink-muted">
          <li className="flex gap-2">
            <CheckCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
            A US mobile number, yours for {label}. Every SMS it receives shows up on its page.
          </li>
          <li className="flex gap-2">
            <CheckCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
            Not set up? You get the full amount back automatically.
          </li>
          <li className="flex gap-2">
            <ClockIcon className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            You can cancel for a full refund only while our provider allows it - usually shortly after
            renting, before messages arrive. It never renews by itself; you can extend it, but extensions
            can&apos;t be refunded.
          </li>
        </ul>
        <p className="text-caption text-ink-faint">
          By renting you agree to our <Link href="/terms" className="underline">Terms</Link> and Acceptable
          Use Policy.
        </p>
      </div>
    </Dialog>
  );
}
