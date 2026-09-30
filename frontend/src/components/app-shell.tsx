"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { useAuth } from "@/components/auth-provider";
import { Logo, Logomark } from "@/components/brand";
import {
  BellIcon,
  BoltIcon,
  ChartIcon,
  CloseIcon,
  FlagIcon,
  GiftIcon,
  GridIcon,
  HelpIcon,
  HomeIcon,
  LogoutIcon,
  MenuIcon,
  ReceiptIcon,
  SearchIcon,
  SettingsIcon,
  ShieldIcon,
  TagIcon,
  UserIcon,
  UsersIcon,
  WalletIcon,
} from "@/components/icons";
import { ButtonLink, Skeleton, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { Wallet } from "@/lib/types";

/**
 * The application frame: sidebar, top bar and mobile navigation.
 *
 * The sidebar is deliberately quiet - navigation, not a billboard. The balance
 * lives once, in the top bar, next to the one action it invites. On phones the
 * bottom bar carries the five places a customer goes; everything else is one
 * tap into Account.
 */

type NavItem = {
  href: string;
  label: string;
  icon: (props: { className?: string }) => React.JSX.Element;
  /** Also treat these path prefixes as "this item is active". */
  match?: string[];
  /** Only the exact path is active (for a parent like /account). */
  exact?: boolean;
};

type NavGroup = { label?: string; items: NavItem[] };

const USER_NAV: NavGroup[] = [
  {
    items: [
      { href: "/dashboard", label: "Home", icon: HomeIcon },
      { href: "/services", label: "Buy a number", icon: GridIcon },
      { href: "/orders", label: "Orders", icon: ReceiptIcon },
      { href: "/wallet", label: "Wallet", icon: WalletIcon, match: ["/wallet", "/transactions"] },
    ],
  },
  {
    label: "Account",
    items: [
      { href: "/refer", label: "Refer friends", icon: GiftIcon },
      { href: "/account/notifications", label: "Notifications", icon: BellIcon },
      { href: "/account", label: "Settings", icon: SettingsIcon, exact: true },
    ],
  },
];

const USER_BOTTOM_NAV: NavItem[] = [
  { href: "/dashboard", label: "Home", icon: HomeIcon },
  { href: "/services", label: "Buy", icon: GridIcon },
  { href: "/orders", label: "Orders", icon: ReceiptIcon },
  { href: "/wallet", label: "Wallet", icon: WalletIcon, match: ["/wallet", "/transactions"] },
  { href: "/account", label: "Account", icon: UserIcon, match: ["/account", "/refer"] },
];

const ADMIN_NAV: NavGroup[] = [
  { items: [{ href: "/admin", label: "Overview", icon: ChartIcon, exact: true }] },
  {
    label: "Operations",
    items: [
      { href: "/admin/orders", label: "Orders", icon: ReceiptIcon },
      { href: "/admin/issues", label: "Number issues", icon: FlagIcon },
      { href: "/admin/payments", label: "Payments", icon: WalletIcon },
      { href: "/admin/users", label: "Users", icon: UsersIcon },
    ],
  },
  {
    label: "Catalogue & pricing",
    items: [
      { href: "/admin/catalog", label: "Catalog", icon: GridIcon },
      { href: "/admin/pricing", label: "Pricing", icon: TagIcon },
      { href: "/admin/providers", label: "Providers", icon: ShieldIcon },
      { href: "/admin/funding", label: "Provider funding", icon: BoltIcon },
    ],
  },
  { label: "Growth", items: [{ href: "/admin/referrals", label: "Referrals", icon: GiftIcon }] },
  { label: "Platform", items: [{ href: "/admin/system", label: "System", icon: SettingsIcon }] },
];

function useIsActive() {
  const pathname = usePathname();
  return React.useCallback(
    (item: NavItem) => {
      if (item.exact) return pathname === item.href;
      const targets = item.match ?? [item.href];
      return targets.some((target) => pathname === target || pathname.startsWith(`${target}/`));
    },
    [pathname],
  );
}

/** `Kwame Mensah` -> `KM`, `felix@gmail.com` -> `F`. */
function initials(name: string | undefined, email: string | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (email?.[0] ?? "?").toUpperCase();
}

export function AppShell({
  children,
  variant = "user",
}: {
  children: React.ReactNode;
  variant?: "user" | "admin";
}) {
  const groups = variant === "admin" ? ADMIN_NAV : USER_NAV;

  return (
    <div className="min-h-dvh bg-canvas">
      <Sidebar groups={groups} variant={variant} />
      <div className="lg:pl-60">
        <TopBar variant={variant} />
        <main id="main" className="px-4 pb-safe-nav pt-5 sm:px-6 lg:px-10 lg:pb-12 lg:pt-8">
          <div className={cn("mx-auto w-full", variant === "admin" ? "max-w-7xl" : "max-w-6xl")}>
            {children}
          </div>
        </main>
      </div>
      {variant === "admin" ? <AdminBottomNav groups={groups} /> : <BottomNav items={USER_BOTTOM_NAV} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Sidebar                                                            */
/* ------------------------------------------------------------------ */

function Sidebar({ groups, variant }: { groups: NavGroup[]; variant: "user" | "admin" }) {
  const { isStaff } = useAuth();
  const { data: unread } = useSWR<{ count: number }>(
    variant === "user" ? "/notifications/unread/" : null,
    { refreshInterval: 60_000 },
  );

  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col border-r border-line bg-surface lg:flex">
      <div className="flex h-14 shrink-0 items-center gap-2 px-5">
        <Link href={variant === "admin" ? "/admin" : "/dashboard"} className="rounded-md">
          <Logo className="[&_svg]:h-7 [&_svg]:w-7" />
        </Link>
        {variant === "admin" ? (
          <span className="rounded border border-line px-1.5 py-px text-2xs font-semibold uppercase tracking-wide text-ink-muted">
            Admin
          </span>
        ) : null}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4 pt-2" aria-label="Main">
        {groups.map((group, index) => (
          <div key={group.label ?? index} className={cn(index > 0 && "mt-5")}>
            {group.label ? (
              <p className="mb-1 px-2.5 text-2xs font-medium uppercase tracking-wider text-ink-faint">
                {group.label}
              </p>
            ) : null}
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.href}>
                  <SidebarLink
                    item={item}
                    badge={item.href === "/account/notifications" ? unread?.count : undefined}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-3 py-3">
        {variant === "user" ? (
          <a
            href="/#faq"
            className="flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium text-ink-soft transition-colors hover:bg-sunken hover:text-ink"
          >
            <HelpIcon className="h-5 w-5 text-ink-faint" />
            Help &amp; FAQ
          </a>
        ) : null}
        {isStaff ? (
          <Link
            href={variant === "admin" ? "/dashboard" : "/admin"}
            className="flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium text-ink-soft transition-colors hover:bg-sunken hover:text-ink"
          >
            <ShieldIcon className="h-5 w-5 text-ink-faint" />
            {variant === "admin" ? "Customer view" : "Admin console"}
          </Link>
        ) : null}
      </div>
    </aside>
  );
}

function SidebarLink({ item, badge }: { item: NavItem; badge?: number }) {
  const isActive = useIsActive();
  const active = isActive(item);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors",
        active ? "bg-sunken text-ink" : "text-ink-soft hover:bg-sunken hover:text-ink",
      )}
    >
      {active ? (
        <span aria-hidden className="absolute -left-3 bottom-2 top-2 w-0.5 rounded-r bg-brand-600" />
      ) : null}
      <Icon
        className={cn(
          "h-5 w-5 shrink-0 transition-colors",
          active ? "text-brand-600" : "text-ink-faint group-hover:text-ink-muted",
        )}
      />
      <span className="truncate">{item.label}</span>
      {badge ? (
        <span className="tabular ml-auto rounded-md bg-brand-600 px-1.5 text-2xs font-semibold leading-5 text-white">
          {badge > 99 ? "99+" : badge}
          <span className="sr-only"> unread</span>
        </span>
      ) : null}
    </Link>
  );
}

/* ------------------------------------------------------------------ */
/* Top bar                                                            */
/* ------------------------------------------------------------------ */

function TopBar({ variant }: { variant: "user" | "admin" }) {
  const { data: wallet, isLoading } = useSWR<Wallet>(variant === "user" ? "/wallet/" : null);
  const { data: unread } = useSWR<{ count: number }>(
    variant === "user" ? "/notifications/unread/" : null,
    { refreshInterval: 60_000 },
  );

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-6 lg:px-10">
        <Link href={variant === "admin" ? "/admin" : "/dashboard"} className="rounded-md lg:hidden">
          <span className="flex min-h-11 items-center gap-2">
            <Logomark className="h-7 w-7 text-brand-600" />
            {variant === "admin" ? (
              <span className="text-sm font-semibold text-ink">Admin</span>
            ) : (
              <span className="sr-only">VerifyGH home</span>
            )}
          </span>
        </Link>

        {variant === "user" ? <ServiceSearch /> : null}

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          {variant === "user" ? (
            <>
              <Link
                href="/wallet"
                className="flex min-h-11 items-center gap-2 rounded-lg px-2 transition-colors hover:bg-sunken sm:min-h-9"
                aria-label={wallet ? `Wallet balance ${cedis(wallet.balance)}` : "Wallet"}
              >
                <span className="hidden text-caption text-ink-muted xl:inline">Balance</span>
                {isLoading ? (
                  <Skeleton className="h-5 w-20" />
                ) : (
                  <span className="tabular text-sm font-semibold text-ink">{cedis(wallet?.balance)}</span>
                )}
              </Link>
              <ButtonLink href="/wallet/deposit" size="sm" className="hidden sm:inline-flex">
                Add funds
              </ButtonLink>
              <Link
                href="/account/notifications"
                aria-label={unread?.count ? `Notifications, ${unread.count} unread` : "Notifications"}
                className="relative flex h-11 w-11 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-sunken hover:text-ink sm:h-10 sm:w-10"
              >
                <BellIcon className="h-5 w-5" />
                {unread && unread.count > 0 ? (
                  <span aria-hidden className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-brand-600 ring-2 ring-surface" />
                ) : null}
              </Link>
            </>
          ) : null}
          <UserMenu variant={variant} />
        </div>
      </div>
    </header>
  );
}

/** Search from anywhere: lands on the marketplace with the query applied. */
function ServiceSearch() {
  const router = useRouter();
  const [query, setQuery] = React.useState("");
  return (
    <form
      role="search"
      className="hidden max-w-sm flex-1 md:block"
      onSubmit={(event) => {
        event.preventDefault();
        const q = query.trim();
        router.push(q ? `/services?q=${encodeURIComponent(q)}` : "/services");
      }}
    >
      <label className="relative block">
        <span className="sr-only">Search services</span>
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search services - WhatsApp, TikTok, Gmail"
          className="h-9 w-full rounded-lg border border-line bg-canvas pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint transition-colors focus:border-brand-500 focus:bg-surface focus:shadow-focus focus:outline-none"
        />
      </label>
    </form>
  );
}

/** The account menu: who is signed in, where their settings are, sign out. */
function UserMenu({ variant }: { variant: "user" | "admin" }) {
  const { user, signOut, isStaff } = useAuth();
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const pathname = usePathname();

  React.useEffect(() => setOpen(false), [pathname]);
  React.useEffect(() => {
    if (!open) return;
    function onDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const items =
    variant === "admin"
      ? [{ href: "/dashboard", label: "Customer view" }]
      : [
          { href: "/account", label: "Settings" },
          { href: "/account/notifications", label: "Notifications" },
          { href: "/refer", label: "Refer friends" },
          ...(isStaff ? [{ href: "/admin", label: "Admin console" }] : []),
        ];

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen((value) => !value)}
        className="flex h-11 items-center gap-2 rounded-lg px-1.5 transition-colors hover:bg-sunken sm:h-10"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-50 text-caption font-semibold text-brand-700">
          {initials(user?.full_name, user?.email)}
        </span>
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-full z-50 mt-1.5 w-64 animate-fade-in overflow-hidden rounded-xl border border-line bg-surface shadow-pop"
        >
          <div className="border-b border-line px-4 py-3">
            <p className="truncate text-sm font-medium text-ink">{user?.full_name || "Your account"}</p>
            <p className="truncate text-caption text-ink-muted">{user?.email}</p>
          </div>
          <div className="py-1">
            {items.map((item) => (
              <Link
                key={item.href}
                role="menuitem"
                href={item.href}
                className="flex min-h-11 items-center px-4 text-sm text-ink-soft transition-colors hover:bg-sunken hover:text-ink focus:bg-sunken focus:outline-none sm:min-h-9"
              >
                {item.label}
              </Link>
            ))}
          </div>
          <div className="border-t border-line py-1">
            <button
              type="button"
              role="menuitem"
              onClick={signOut}
              className="flex min-h-11 w-full items-center gap-2 px-4 text-left text-sm text-ink-soft transition-colors hover:bg-sunken hover:text-ink focus:bg-sunken focus:outline-none sm:min-h-9"
            >
              <LogoutIcon className="h-4 w-4 text-ink-faint" />
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Mobile navigation                                                  */
/* ------------------------------------------------------------------ */

function BottomNav({ items }: { items: NavItem[] }) {
  const isActive = useIsActive();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface lg:hidden"
      style={{ paddingBottom: "var(--safe-bottom)" }}
    >
      <ul className="mx-auto flex max-w-lg">
        {items.map((item) => (
          <li key={item.href} className="flex-1">
            <BottomLink item={item} active={isActive(item)} />
          </li>
        ))}
      </ul>
    </nav>
  );
}

function BottomLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-16 flex-col items-center justify-center gap-1 text-2xs font-medium transition-colors",
        active ? "text-brand-700" : "text-ink-muted",
      )}
    >
      <Icon className={cn("h-6 w-6", active ? "text-brand-600" : "text-ink-faint")} />
      {item.label}
    </Link>
  );
}

/** Admin on a phone: the four busiest places, and everything else in a sheet. */
function AdminBottomNav({ groups }: { groups: NavGroup[] }) {
  const isActive = useIsActive();
  const [open, setOpen] = React.useState(false);
  const pathname = usePathname();
  React.useEffect(() => setOpen(false), [pathname]);

  const all = groups.flatMap((group) => group.items);
  const primary = ["/admin", "/admin/orders", "/admin/issues", "/admin/users"]
    .map((href) => all.find((item) => item.href === href))
    .filter((item): item is NavItem => Boolean(item));
  const moreActive = !primary.some((item) => isActive(item));

  return (
    <>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface lg:hidden"
        style={{ paddingBottom: "var(--safe-bottom)" }}
      >
        <ul className="mx-auto flex max-w-lg">
          {primary.map((item) => (
            <li key={item.href} className="flex-1">
              <BottomLink item={item} active={isActive(item)} />
            </li>
          ))}
          <li className="flex-1">
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-haspopup="dialog"
              className={cn(
                "flex h-16 w-full flex-col items-center justify-center gap-1 text-2xs font-medium",
                moreActive ? "text-brand-700" : "text-ink-muted",
              )}
            >
              <MenuIcon className={cn("h-6 w-6", moreActive ? "text-brand-600" : "text-ink-faint")} />
              More
            </button>
          </li>
        </ul>
      </nav>
      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="All sections">
          <button
            type="button"
            aria-label="Close"
            className="absolute inset-0 bg-ink/30"
            onClick={() => setOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-0 max-h-[80dvh] animate-slide-up overflow-y-auto rounded-t-2xl border-t border-line bg-surface pb-safe">
            <div className="flex items-center justify-between px-4 py-3">
              <p className="text-heading">All sections</p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="flex h-10 w-10 items-center justify-center rounded-lg text-ink-muted hover:bg-sunken"
              >
                <CloseIcon className="h-5 w-5" />
              </button>
            </div>
            {groups.map((group, index) => (
              <div key={group.label ?? index} className="border-t border-line px-2 py-2">
                {group.label ? (
                  <p className="px-2 py-1 text-2xs font-medium uppercase tracking-wider text-ink-faint">
                    {group.label}
                  </p>
                ) : null}
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex h-11 items-center gap-3 rounded-lg px-2 text-sm font-medium",
                        active ? "bg-sunken text-ink" : "text-ink-soft",
                      )}
                    >
                      <Icon className={cn("h-5 w-5", active ? "text-brand-600" : "text-ink-faint")} />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Page header                                                        */
/* ------------------------------------------------------------------ */

export function PageHeader({
  title,
  description,
  action,
  back,
  icon,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  back?: { href: string; label: string };
  icon?: React.ReactNode;
}) {
  return (
    <div className="mb-6 lg:mb-8">
      {back ? (
        <Link
          href={back.href}
          className="-mt-3 mb-0.5 inline-flex min-h-11 items-center gap-1 text-sm font-medium text-ink-muted transition-colors hover:text-ink"
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
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div className="flex min-w-0 items-center gap-3">
          {icon}
          <div className="min-w-0">
            <h1 className="text-title text-ink">{title}</h1>
            {description ? <div className="mt-1 max-w-2xl text-sm text-ink-muted">{description}</div> : null}
          </div>
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
    </div>
  );
}
