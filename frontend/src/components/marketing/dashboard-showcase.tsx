"use client";

import useSWR from "swr";

import { Logomark } from "@/components/brand";
import { CountryFlag } from "@/components/country-flag";
import {
  BellIcon,
  GiftIcon,
  GridIcon,
  HomeIcon,
  PlusIcon,
  ReceiptIcon,
  SettingsIcon,
  WalletIcon,
} from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome, MarketRow } from "@/lib/types";

import { BottomNav, Device, Halo, HomeIndicator, Reveal, StatusBar } from "./device";

/**
 * The app itself: the dashboard in a laptop from lg, on a phone below it -
 * the same screens a customer gets, with the app's own navigation, labels
 * and statuses. Live: services, logos and prices. Invented: the example
 * account's name, balance, numbers and history.
 */

const BALANCE = 127.5;
const NUMBERS = ["+1 (512) 555-0147", "+1 (646) 555-0182", "+1 (312) 555-0119", "+1 (415) 555-0163", "+1 (213) 555-0128"];

type Order = { row?: MarketRow; number: string; status: "code" | "waiting" | "refunded"; when: string };

export function DashboardShowcase() {
  const { data } = useSWR<MarketHome>("/marketplace/home/");
  const rows = (data?.popular ?? []).filter((row) => !row.temporarily_unavailable);
  const orders: Order[] = [
    { row: rows[1], number: NUMBERS[0], status: "waiting", when: "Now" },
    { row: rows[0], number: NUMBERS[1], status: "code", when: "09:42" },
    { row: rows[2], number: NUMBERS[2], status: "code", when: "09:31" },
    { row: rows[3], number: NUMBERS[3], status: "refunded", when: "Yesterday" },
    { row: rows[5], number: NUMBERS[4], status: "code", when: "Yesterday" },
  ];

  return (
    <section id="dashboard" className="atmosphere-wash scroll-mt-20 overflow-x-clip" aria-labelledby="dashboard-heading">
      <div className="container-page py-16 sm:py-24">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 id="dashboard-heading" className="section-title">
            Every order, number and cedi in one place.
          </h2>
          <p className="section-lead">
            Live orders with their codes, your balance and every transaction - on your phone or
            your laptop, the same account.
          </p>
        </Reveal>

        <Reveal>
          {/* lg: a laptop */}
          <div className="relative mx-auto mt-12 hidden max-w-5xl lg:block" aria-hidden>
            <Halo className="left-1/2 top-1/2 h-[90%] w-[110%] -translate-x-1/2 -translate-y-1/2" />
            <div className="relative rounded-t-[1.4rem] bg-[#0d0f12] p-2.5 pb-3 shadow-[0_50px_100px_-40px_rgba(5,11,24,0.6)] ring-1 ring-black/40">
              <span className="absolute left-1/2 top-1 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-[#2a2d33]" />
              <div className="overflow-hidden rounded-lg bg-canvas">
                <DesktopApp orders={orders} />
              </div>
            </div>
            {/* The base */}
            <div className="relative -mx-10 h-4 rounded-b-2xl bg-linear-to-b from-[#d9d6d0] via-[#b3aea6] to-[#8a857e] shadow-[0_20px_30px_-15px_rgba(0,0,0,0.5)]">
              <span className="absolute left-1/2 top-0 h-1.5 w-28 -translate-x-1/2 rounded-b-lg bg-[#8f8a83]" />
            </div>
          </div>

          {/* Below lg: a phone */}
          <div className="relative mx-auto mt-10 flex justify-center lg:hidden" aria-hidden>
            <Halo className="left-1/2 top-1/2 h-[110%] w-[140%] -translate-x-1/2 -translate-y-1/2" />
            <Device>
              <MobileApp orders={orders} />
            </Device>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Status({ status, compact = false }: { status: Order["status"]; compact?: boolean }) {
  const map = {
    code: { label: "Code received", tone: "bg-success-50 text-success-700" },
    waiting: { label: "Waiting for SMS", tone: "bg-info-50 text-info-700" },
    refunded: { label: "Refunded", tone: "bg-sunken text-ink-soft" },
  } as const;
  return (
    <span
      className={cn(
        "whitespace-nowrap rounded-full font-semibold",
        compact ? "px-1.5 py-px text-[0.5625rem]" : "px-2 py-0.5 text-2xs",
        map[status].tone,
      )}
    >
      {compact && status === "waiting" ? "Waiting" : map[status].label}
    </span>
  );
}

function DesktopApp({ orders }: { orders: Order[] }) {
  const nav = [
    { label: "Home", Icon: HomeIcon, active: true },
    { label: "Buy a number", Icon: GridIcon },
    { label: "Orders", Icon: ReceiptIcon },
    { label: "Wallet", Icon: WalletIcon },
  ];
  const account = [
    { label: "Refer friends", Icon: GiftIcon },
    { label: "Notifications", Icon: BellIcon },
    { label: "Settings", Icon: SettingsIcon },
  ];
  return (
    <div className="grid h-136 grid-cols-[13rem_1fr] text-left">
      {/* Sidebar */}
      <aside className="flex flex-col border-r border-line bg-surface px-3 py-4">
        <span className="flex items-center gap-2 px-2">
          <Logomark className="h-6 w-6 text-primary" />
          <span className="text-sm font-bold tracking-tight text-ink">VerifyGH</span>
        </span>
        <nav className="mt-6 space-y-0.5">
          {nav.map(({ label, Icon, active }) => (
            <span
              key={label}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-caption font-medium",
                active ? "bg-brand-50 text-brand-700" : "text-ink-soft",
              )}
            >
              <Icon className="h-4 w-4" /> {label}
            </span>
          ))}
        </nav>
        <p className="mt-5 px-2.5 text-2xs font-semibold uppercase tracking-wide text-ink-faint">Account</p>
        <nav className="mt-1.5 space-y-0.5">
          {account.map(({ label, Icon }) => (
            <span key={label} className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-caption font-medium text-ink-soft">
              <Icon className="h-4 w-4" /> {label}
            </span>
          ))}
        </nav>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center justify-end gap-3 border-b border-line bg-surface px-6 py-3">
          <span className="tabular text-caption font-semibold text-ink">{cedis(BALANCE)}</span>
          <span className="flex items-center gap-1 rounded-full bg-primary px-3 py-1.5 text-2xs font-semibold text-white">
            <PlusIcon className="h-3 w-3" /> Add funds
          </span>
          <BellIcon className="h-4 w-4 text-ink-muted" />
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-50 text-2xs font-bold text-brand-700">KA</span>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[1fr_16rem] gap-5 overflow-hidden p-6">
          <div className="min-w-0 space-y-4">
            <div>
              <p className="text-lg font-bold tracking-tight text-ink">Good morning, Kofi</p>
              <p className="text-caption text-ink-muted">One order is waiting for its code.</p>
            </div>

            <div className="rounded-2xl border border-line bg-surface">
              <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
                <p className="text-caption font-semibold text-ink">Recent orders</p>
                <p className="text-2xs font-medium text-brand-700">View all</p>
              </div>
              <div className="grid grid-cols-[1.3fr_1.4fr_0.8fr_1fr] gap-2 border-b border-line bg-sunken/60 px-4 py-2 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
                <span>Service</span>
                <span>Number</span>
                <span>Price</span>
                <span className="text-right">Status</span>
              </div>
              {orders.map((order, index) => (
                <div key={index} className="grid grid-cols-[1.3fr_1.4fr_0.8fr_1fr] items-center gap-2 border-b border-line px-4 py-2.5 last:border-b-0">
                  <span className="flex min-w-0 items-center gap-2">
                    <RowLogo row={order.row} size="xs" />
                    <span className="min-w-0">
                      <span className="block truncate text-caption font-semibold text-ink">{order.row?.name ?? "—"}</span>
                      <span className="block text-2xs text-ink-muted">{order.when}</span>
                    </span>
                  </span>
                  <span className="code truncate text-caption text-ink-soft">{order.number}</span>
                  <span className="tabular text-caption text-ink-soft">{cedis(order.row?.price)}</span>
                  <span className="text-right">
                    <Status status={order.status} />
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-2xl bg-linear-to-br from-[#0B63B6] to-[#137A4E] p-4 text-white shadow-[0_16px_30px_-14px_rgba(8,120,209,0.8)]">
              <p className="text-2xs text-white/75">Available balance</p>
              <p className="tabular mt-0.5 text-2xl font-extrabold tracking-tight">{cedis(BALANCE)}</p>
              <div className="mt-3 grid grid-cols-2 gap-1.5 text-2xs font-semibold">
                <span className="rounded-full bg-white py-1.5 text-center text-[#0B4F8F]">Add funds</span>
                <span className="rounded-full border border-white/40 py-1.5 text-center">Buy a number</span>
              </div>
            </div>
            <div className="rounded-2xl border border-line bg-surface p-4">
              <p className="text-caption font-semibold text-ink">In progress</p>
              <div className="mt-2.5 flex items-center gap-2.5">
                <RowLogo row={orders[0].row} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1 text-caption font-semibold text-ink">
                    {orders[0].row?.name ?? "—"} <CountryFlag code="US" size="sm" />
                  </span>
                  <span className="code block truncate text-2xs text-ink-muted">{orders[0].number}</span>
                </span>
              </div>
              <div className="mt-3 flex items-center gap-2 rounded-xl bg-info-50 px-3 py-2">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-info-500" />
                <span className="text-2xs font-medium text-info-700">Waiting for the SMS · 18:12 left</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MobileApp({ orders }: { orders: Order[] }) {
  return (
    <>
      <StatusBar />
      <div className="flex min-h-0 flex-1 flex-col gap-2.5 px-3.5 pt-1.5">
        <div className="flex items-center justify-between px-0.5">
          <Logomark className="h-6 w-6 text-primary" />
          <span className="tabular rounded-full border border-line-strong px-2.5 py-1 text-2xs font-semibold text-ink">
            {cedis(BALANCE)}
          </span>
        </div>
        <div className="px-0.5">
          <p className="text-base font-bold tracking-tight text-ink">Good morning, Kofi</p>
          <p className="text-[0.625rem] text-ink-muted">One order is waiting for its code.</p>
        </div>
        <div className="rounded-2xl bg-linear-to-br from-[#0B63B6] to-[#137A4E] p-3 text-white">
          <p className="text-[0.625rem] text-white/75">Available balance</p>
          <p className="tabular text-xl font-extrabold tracking-tight">{cedis(BALANCE)}</p>
          <div className="mt-2 grid grid-cols-2 gap-1.5 text-[0.625rem] font-semibold">
            <span className="rounded-full bg-white py-1 text-center text-[#0B4F8F]">Add funds</span>
            <span className="rounded-full border border-white/40 py-1 text-center">Buy a number</span>
          </div>
        </div>
        <p className="px-0.5 text-[0.625rem] font-medium text-ink-soft">Recent orders</p>
        <div className="divide-y divide-line rounded-xl border border-line bg-surface">
          {orders.slice(0, 3).map((order, index) => (
            <div key={index} className="flex items-center gap-2 px-2.5 py-2">
              <RowLogo row={order.row} size="xs" className="h-6! w-6!" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.6875rem] font-semibold text-ink">{order.row?.name ?? "—"}</span>
                <span className="code block truncate text-[0.5625rem] text-ink-muted">{order.number}</span>
              </span>
              <Status status={order.status} compact />
            </div>
          ))}
        </div>
      </div>
      <BottomNav active="home" />
      <HomeIndicator />
    </>
  );
}

/** A service's logo, or a quiet placeholder tile until the catalogue answers. */
function RowLogo({ row, size, className }: { row?: MarketRow; size: "xs" | "sm" | "md"; className?: string }) {
  if (!row) {
    const box = { xs: "h-7 w-7", sm: "h-8 w-8 sm:h-9 sm:w-9", md: "h-9 w-9" }[size];
    return <Skeleton className={cn("shrink-0 rounded-[23%]", box, className)} />;
  }
  return <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size={size} className={className} />;
}
