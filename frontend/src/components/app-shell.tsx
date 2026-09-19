"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { useAuth } from "@/components/auth-provider";
import { Logo, Logomark } from "@/components/brand";
import {
  BellIcon,
  ChartIcon,
  GridIcon,
  HomeIcon,
  LogoutIcon,
  PlusIcon,
  ReceiptIcon,
  SettingsIcon,
  ShieldIcon,
  UserIcon,
  UsersIcon,
  WalletIcon,
} from "@/components/icons";
import { Button, Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { Wallet } from "@/lib/types";

type NavItem = {
  href: string;
  label: string;
  icon: (props: { className?: string }) => React.JSX.Element;
  /** Also treat these path prefixes as "this tab is active". */
  match?: string[];
};

const USER_NAV: NavItem[] = [
  { href: "/dashboard", label: "Home", icon: HomeIcon },
  { href: "/services", label: "Services", icon: GridIcon },
  { href: "/orders", label: "Orders", icon: ReceiptIcon },
  { href: "/wallet", label: "Wallet", icon: WalletIcon, match: ["/wallet", "/transactions"] },
  { href: "/account", label: "Account", icon: UserIcon },
];

const ADMIN_NAV: NavItem[] = [
  { href: "/admin", label: "Overview", icon: ChartIcon },
  { href: "/admin/users", label: "Users", icon: UsersIcon },
  { href: "/admin/orders", label: "Orders", icon: ReceiptIcon },
  { href: "/admin/payments", label: "Payments", icon: WalletIcon },
  { href: "/admin/catalog", label: "Catalog", icon: GridIcon },
  { href: "/admin/system", label: "System", icon: SettingsIcon },
];

function useIsActive() {
  const pathname = usePathname();
  return React.useCallback(
    (item: NavItem) => {
      const targets = item.match ?? [item.href];
      return targets.some(
        (target) => pathname === target || pathname.startsWith(`${target}/`),
      );
    },
    [pathname],
  );
}

export function AppShell({
  children,
  variant = "user",
}: {
  children: React.ReactNode;
  variant?: "user" | "admin";
}) {
  const nav = variant === "admin" ? ADMIN_NAV : USER_NAV;

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <DesktopSidebar nav={nav} variant={variant} />
      <TopBar variant={variant} />

      <main
        id="main"
        className="flex-1 lg:pl-64"
      >
        <div className="container-page py-5 mb-safe-nav lg:mb-0 lg:py-8">{children}</div>
      </main>

      <BottomNav nav={nav} />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function DesktopSidebar({ nav, variant }: { nav: NavItem[]; variant: "user" | "admin" }) {
  const isActive = useIsActive();
  const { user, signOut, isStaff } = useAuth();

  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-line bg-surface lg:flex">
      <div className="flex h-16 shrink-0 items-center border-b border-line px-5">
        <Link href={variant === "admin" ? "/admin" : "/dashboard"} className="rounded-lg">
          <Logo />
        </Link>
        {variant === "admin" ? (
          <span className="ml-2 rounded-md bg-brand-50 px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-brand-700">
            Admin
          </span>
        ) : null}
      </div>

      {variant === "user" ? <SidebarBalance /> : null}

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-3" aria-label="Sections">
        {nav.map((item) => {
          const active = isActive(item);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "bg-brand-50 text-brand-700"
                  : "text-ink-soft hover:bg-line/40 hover:text-ink",
              )}
            >
              <Icon className="h-5 w-5" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-1 border-t border-line p-3">
        {isStaff ? (
          <Link
            href={variant === "admin" ? "/dashboard" : "/admin"}
            className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:bg-line/40 hover:text-ink"
          >
            <ShieldIcon className="h-5 w-5" />
            {variant === "admin" ? "Customer view" : "Admin console"}
          </Link>
        ) : null}

        <div className="flex items-center gap-3 rounded-xl px-3 py-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">
            {(user?.full_name || user?.email || "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-ink">
              {user?.full_name || "Your account"}
            </span>
            <span className="block truncate text-xs text-ink-muted">{user?.email}</span>
          </span>
          <button
            type="button"
            onClick={signOut}
            aria-label="Sign out"
            className="-mr-1 rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-line/50 hover:text-ink"
          >
            <LogoutIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

function SidebarBalance() {
  const { data, isLoading } = useSWR<Wallet>("/wallet/");

  return (
    <div className="border-b border-line p-3">
      <div className="rounded-xl bg-brand-700 p-4 text-white">
        <p className="text-xs text-brand-200">Wallet balance</p>
        {isLoading ? (
          <Skeleton className="mt-2 h-6 w-28 bg-white/20" />
        ) : (
          <p className="tabular mt-1 text-2xl font-semibold">{cedis(data?.balance)}</p>
        )}
        <Link href="/wallet/deposit" className="mt-3 block">
          <Button size="sm" variant="inverse" fullWidth icon={<PlusIcon className="h-4 w-4" />}>
            Add money
          </Button>
        </Link>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function TopBar({ variant }: { variant: "user" | "admin" }) {
  const { user, signOut } = useAuth();
  const { data } = useSWR<Wallet>(variant === "user" ? "/wallet/" : null);
  const { data: unread } = useSWR<{ count: number }>(
    variant === "user" ? "/notifications/unread/" : null,
    { refreshInterval: 60_000 },
  );

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-canvas/90 backdrop-blur-md lg:pl-64">
      <div className="container-page flex h-14 items-center justify-between gap-3 lg:h-16">
        <Link href={variant === "admin" ? "/admin" : "/dashboard"} className="lg:hidden">
          <span className="flex items-center gap-2">
            <Logomark className="h-7 w-7 text-brand-600" />
            {variant === "admin" ? (
              <span className="text-sm font-semibold text-ink">Admin</span>
            ) : null}
          </span>
        </Link>

        <div className="hidden lg:block">
          <p className="text-sm text-ink-muted">
            {greeting()}
            {user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}
          </p>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {variant === "user" ? (
            <>
              <Link
                href="/wallet"
                className="tabular rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm font-semibold text-ink lg:hidden"
              >
                {cedis(data?.balance)}
              </Link>
              <Link
                href="/account/notifications"
                aria-label={
                  unread?.count ? `Notifications, ${unread.count} unread` : "Notifications"
                }
                className="relative rounded-xl p-2.5 text-ink-soft transition-colors hover:bg-line/50"
              >
                <BellIcon />
                {unread && unread.count > 0 ? (
                  <span className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-500 px-1 text-2xs font-semibold text-white">
                    {unread.count > 9 ? "9+" : unread.count}
                  </span>
                ) : null}
              </Link>
            </>
          ) : (
            <button
              type="button"
              onClick={signOut}
              className="rounded-xl p-2.5 text-ink-soft transition-colors hover:bg-line/50 lg:hidden"
              aria-label="Sign out"
            >
              <LogoutIcon />
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/* ------------------------------------------------------------------ */

function BottomNav({ nav }: { nav: NavItem[] }) {
  const isActive = useIsActive();
  // Five is the most a thumb can reliably hit on a 375px screen.
  const items = nav.slice(0, 5);

  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 backdrop-blur-md lg:hidden"
      style={{ paddingBottom: "var(--safe-bottom)" }}
    >
      <ul className="flex">
        {items.map((item) => {
          const active = isActive(item);
          const Icon = item.icon;
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-[4.25rem] flex-col items-center justify-center gap-1 text-2xs font-medium transition-colors",
                  active ? "text-brand-700" : "text-ink-muted",
                )}
              >
                <span className="relative">
                  <Icon className={cn("h-6 w-6", active && "stroke-[2]")} />
                  {active ? (
                    <span className="absolute -top-2 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-brand-600" />
                  ) : null}
                </span>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/* ------------------------------------------------------------------ */

export function PageHeader({
  title,
  description,
  action,
  back,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <div className="mb-5 lg:mb-7">
      {back ? (
        <Link
          href={back.href}
          className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted transition-colors hover:text-ink"
        >
          <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
            <path
              d="M15 6l-6 6 6 6"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {back.label}
        </Link>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">{title}</h1>
          {description ? (
            <div className="mt-1 text-sm text-ink-muted">{description}</div>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </div>
  );
}
