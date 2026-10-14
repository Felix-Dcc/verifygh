"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { useAuth } from "@/components/auth-provider";
import { Logo, Logomark } from "@/components/brand";
import { MaintenanceStrip, PauseSiteButton } from "@/components/maintenance";
import { useReferralsEnabled } from "@/components/referral-invite";
import {
  BellIcon,
  BoltIcon,
  ChartIcon,
  ChevronRightIcon,
  CloseIcon,
  FlagIcon,
  GiftIcon,
  GridIcon,
  HelpIcon,
  HomeIcon,
  LogoutIcon,
  MenuIcon,
  PhoneIcon,
  ReceiptIcon,
  SearchIcon,
  SettingsIcon,
  ShieldIcon,
  StarIcon,
  TagIcon,
  UserIcon,
  UsersIcon,
  WalletIcon,
} from "@/components/icons";
import { ThemeSwitcher } from "@/components/theme";
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
  /** Shown only to roles holding this permission. */
  permission?: string;
};

type NavGroup = { label?: string; items: NavItem[] };

const USER_NAV: NavGroup[] = [
  {
    items: [
      { href: "/dashboard", label: "Home", icon: HomeIcon },
      { href: "/services", label: "Buy a number", icon: GridIcon },
      { href: "/rentals", label: "Rent a number", icon: PhoneIcon },
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
  { href: "/services", label: "Buy", icon: GridIcon, match: ["/services", "/rentals"] },
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
      { href: "/admin/rentals", label: "Rentals", icon: PhoneIcon },
      { href: "/admin/issues", label: "Number issues", icon: FlagIcon },
      { href: "/admin/payments", label: "Payments", icon: WalletIcon },
      { href: "/admin/manual-deposits", label: "Manual top-ups", icon: WalletIcon },
      { href: "/admin/users", label: "Users", icon: UsersIcon },
    ],
  },
  {
    label: "Catalogue & pricing",
    items: [
      { href: "/admin/catalog", label: "Catalog", icon: GridIcon },
      { href: "/admin/logos", label: "Logos", icon: StarIcon },
      { href: "/admin/pricing", label: "Pricing", icon: TagIcon },
      { href: "/admin/providers", label: "Providers", icon: ShieldIcon },
      { href: "/admin/funding", label: "Provider funding", icon: BoltIcon },
    ],
  },
  { label: "Growth", items: [{ href: "/admin/referrals", label: "Referrals", icon: GiftIcon }] },
  {
    label: "Platform",
    items: [
      { href: "/admin/team", label: "Team", icon: UserIcon, permission: "USER_ROLE_CHANGE" },
      { href: "/admin/system", label: "System", icon: SettingsIcon },
    ],
  },
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

function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    SUPER_ADMIN: "Super admin",
    ADMIN: "Admin",
    SUPPORT: "Support",
    USER: "Customer",
  };
  return labels[role] ?? role;
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
  const referrals = useReferralsEnabled();
  const { can } = useAuth();
  const groups = React.useMemo(
    () =>
      variant === "admin"
        ? ADMIN_NAV.map((group) => ({
            ...group,
            items: group.items.filter((item) => !item.permission || can(item.permission)),
          }))
        : // Referrals appear only while the programme is running.
          USER_NAV.map((group) => ({
            ...group,
            items: group.items.filter((item) => referrals || item.href !== "/refer"),
          })),
    [variant, referrals, can],
  );

  return (
    <div className={cn("min-h-dvh", variant === "admin" ? "admin-portal" : "bg-canvas")}>
      <Sidebar groups={groups} variant={variant} />
      <div className="lg:pl-60">
        <TopBar variant={variant} />
        {variant === "admin" ? <MaintenanceStrip canManage={can("MAINTENANCE_MANAGE")} /> : null}
        <main id="main" className="px-4 pb-safe-nav pt-5 sm:px-6 lg:px-10 lg:pb-12 lg:pt-8">
          <div className={cn("mx-auto w-full", variant === "admin" ? "max-w-7xl" : "max-w-6xl")}>
            <AdminPortal.Provider value={variant === "admin"}>{children}</AdminPortal.Provider>
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
  const { isStaff, user } = useAuth();
  const pathname = usePathname();
  const admin = variant === "admin";
  const { data: unread } = useSWR<{ count: number }>(
    variant === "user" ? "/notifications/unread/" : null,
    { refreshInterval: 60_000 },
  );

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-40 hidden w-60 flex-col lg:flex",
        admin ? "admin-sidebar text-white" : "border-r border-line bg-surface",
      )}
    >
      <div className="flex h-14 shrink-0 items-center gap-2 px-5">
        <Link href={admin ? "/admin" : "/dashboard"} className="rounded-md">
          <Logo className="[&_svg]:h-7 [&_svg]:w-7" tone={admin ? "light" : "brand"} />
        </Link>
        {admin ? (
          <span className="rounded-md bg-white/10 px-1.5 py-px text-2xs font-semibold uppercase tracking-wide text-white/80 ring-1 ring-inset ring-white/15">
            Admin
          </span>
        ) : null}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4 pt-2" aria-label="Main">
        {groups.map((group, index) => (
          <div key={group.label ?? index} className={cn(index > 0 && "mt-5")}>
            {group.label ? (
              <p
                className={cn(
                  "mb-1 px-2.5 text-2xs font-medium uppercase tracking-wider",
                  admin ? "text-white/40" : "text-ink-faint",
                )}
              >
                {group.label}
              </p>
            ) : null}
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.href}>
                  <SidebarLink
                    item={item}
                    dark={admin}
                    badge={item.href === "/account/notifications" ? unread?.count : undefined}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className={cn("border-t px-3 py-3", admin ? "border-white/10" : "border-line")}>
        {admin && user ? (
          <div className="mb-2 flex items-center gap-3 rounded-lg bg-white/5 px-2.5 py-2 ring-1 ring-inset ring-white/10">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-aqua to-leaf text-caption font-semibold text-navy">
              {initials(user.full_name, user.email)}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-white">{user.full_name || user.email}</span>
              <span className="block truncate text-2xs text-white/55">{roleLabel(user.role)}</span>
            </span>
          </div>
        ) : null}
        {variant === "user" ? (
          <Link
            href="/help"
            aria-current={pathname === "/help" ? "page" : undefined}
            className={cn(
              "flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors hover:bg-sunken hover:text-ink",
              pathname === "/help" ? "bg-sunken text-ink" : "text-ink-soft",
            )}
          >
            <HelpIcon className={cn("h-5 w-5", pathname === "/help" ? "text-brand-600" : "text-ink-faint")} />
            Help &amp; FAQ
          </Link>
        ) : null}
        {isStaff ? (
          <Link
            href={admin ? "/dashboard" : "/admin"}
            className={cn(
              "flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors",
              admin ? "text-white/70 hover:bg-white/10 hover:text-white" : "text-ink-soft hover:bg-sunken hover:text-ink",
            )}
          >
            <ShieldIcon className={cn("h-5 w-5", admin ? "text-white/45" : "text-ink-faint")} />
            {variant === "admin" ? "Customer view" : "Admin console"}
          </Link>
        ) : null}
      </div>
    </aside>
  );
}

function SidebarLink({ item, badge, dark = false }: { item: NavItem; badge?: number; dark?: boolean }) {
  const isActive = useIsActive();
  const active = isActive(item);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors",
        dark
          ? active
            ? "bg-white/10 text-white ring-1 ring-inset ring-white/10"
            : "text-white/65 hover:bg-white/5 hover:text-white"
          : active
            ? "bg-sunken text-ink"
            : "text-ink-soft hover:bg-sunken hover:text-ink",
      )}
    >
      {active ? (
        <span aria-hidden className="absolute -left-3 bottom-1.5 top-1.5 w-1 rounded-r bg-gradient-to-b from-azure to-leaf" />
      ) : null}
      <Icon
        className={cn(
          "h-5 w-5 shrink-0 transition-colors",
          dark
            ? active
              ? "text-aqua"
              : "text-white/40 group-hover:text-white/70"
            : active
              ? "text-brand-600"
              : "text-ink-faint group-hover:text-ink-muted",
        )}
      />
      <span className="truncate">{item.label}</span>
      {badge ? (
        <span className="tabular ml-auto rounded-md bg-primary px-1.5 text-2xs font-semibold leading-5 text-white">
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
  const { can } = useAuth();
  const { data: wallet, error: walletError, isLoading } = useSWR<Wallet>(
    variant === "user" ? "/wallet/" : null,
  );
  const { data: unread } = useSWR<{ count: number }>(
    variant === "user" ? "/notifications/unread/" : null,
    { refreshInterval: 60_000 },
  );

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-6 lg:px-10">
        <Link href={variant === "admin" ? "/admin" : "/dashboard"} className="rounded-md lg:hidden">
          <span className="flex min-h-11 items-center gap-2">
            <Logomark className="h-7 w-7 text-primary" />
            {variant === "admin" ? (
              <span className="text-sm font-semibold text-ink">Admin</span>
            ) : (
              <span className="sr-only">VerifyGH home</span>
            )}
          </span>
        </Link>

        {variant === "user" ? <ServiceSearch /> : <AdminContext />}

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          {variant === "user" ? (
            <>
              <Link
                href="/wallet"
                className="flex min-h-11 items-center gap-2 rounded-lg px-2 transition-colors hover:bg-sunken sm:min-h-9"
                aria-label={
                  wallet ? `Wallet balance ${cedis(wallet.balance)}` : walletError ? "Wallet - balance unavailable" : "Wallet"
                }
              >
                <span className="hidden text-caption text-ink-muted xl:inline">Balance</span>
                {isLoading ? (
                  <Skeleton className="h-5 w-20" />
                ) : walletError && !wallet ? (
                  // Never a zero: a balance that did not load says so.
                  <span className="text-sm text-ink-muted">Unavailable</span>
                ) : (
                  <span className="tabular text-sm font-semibold text-ink">{cedis(wallet?.balance)}</span>
                )}
              </Link>
              {/* Secondary: every page has its own main action, and the top bar
                  should not compete with it. */}
              <ButtonLink href="/wallet/deposit" size="sm" variant="secondary" className="hidden sm:inline-flex">
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
          {variant === "admin" && can("MAINTENANCE_MANAGE") ? <PauseSiteButton /> : null}
          <UserMenu variant={variant} />
        </div>
      </div>
    </header>
  );
}

/** Where you are in the console: section, then page. */
/** The admin nav item (and its group) for a path - the deepest match wins. */
function adminItemFor(pathname: string) {
  return ADMIN_NAV.flatMap((group) => group.items.map((entry) => ({ ...entry, group: group.label })))
    .filter((entry) =>
      entry.exact ? pathname === entry.href : pathname === entry.href || pathname.startsWith(`${entry.href}/`),
    )
    .sort((a, b) => b.href.length - a.href.length)[0];
}

function AdminContext() {
  const pathname = usePathname();
  const item = adminItemFor(pathname);
  return (
    <div className="hidden min-w-0 flex-1 items-center gap-2 text-sm lg:flex">
      <span className="text-ink-faint">Admin</span>
      {item?.group ? (
        <>
          <ChevronRightIcon className="h-3.5 w-3.5 text-ink-faint" />
          <span className="text-ink-faint">{item.group}</span>
        </>
      ) : null}
      {item ? (
        <>
          <ChevronRightIcon className="h-3.5 w-3.5 text-ink-faint" />
          <span className="truncate font-medium text-ink">{item.label}</span>
        </>
      ) : null}
    </div>
  );
}

/** Search from anywhere: lands on the marketplace with the query applied. */
function ServiceSearch() {
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = React.useState("");
  // The marketplace has its own search box; two on one screen is one too many.
  if (pathname.startsWith("/services")) return <div className="flex-1" aria-hidden />;
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

  const referrals = useReferralsEnabled();
  const items =
    variant === "admin"
      ? [{ href: "/dashboard", label: "Customer view" }]
      : [
          { href: "/account", label: "Settings" },
          { href: "/account/notifications", label: "Notifications" },
          ...(referrals ? [{ href: "/refer", label: "Refer friends" }] : []),
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
          className="absolute right-0 top-full z-50 mt-1.5 w-64 animate-fade-in overflow-hidden rounded-xl border border-line bg-raised shadow-pop"
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
          <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2">
            <span className="text-sm text-ink-soft">Theme</span>
            <ThemeSwitcher compact />
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
            className="absolute inset-0 bg-scrim/40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-0 max-h-[80dvh] animate-slide-up overflow-y-auto rounded-t-2xl border-t border-line bg-raised pb-safe">
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

/** True inside the admin console: page headers there become the navy banner. */
const AdminPortal = React.createContext(false);

/**
 * Each admin section in its own colour, so a glance at the banner says where
 * you are: Operations azure, Catalogue & pricing teal, Growth gold, Platform
 * violet. Only the accents change - the navy and the type stay the same.
 */
const ADMIN_THEMES: Record<string, { tile: string; glow: string; line: string }> = {
  Operations: {
    tile: "from-[#0878D1] to-[#28C7F7]",
    glow: "rgb(8 120 209 / 0.55)",
    line: "from-[#0878D1] via-[#28C7F7] to-[#0878D1]",
  },
  "Catalogue & pricing": {
    tile: "from-[#13A3B5] to-[#20B26B]",
    glow: "rgb(32 178 107 / 0.42)",
    line: "from-[#28C7F7] via-[#20B26B] to-[#65D99A]",
  },
  Growth: {
    tile: "from-[#C79A2E] to-[#F2B64A]",
    glow: "rgb(214 160 44 / 0.42)",
    line: "from-[#C79A2E] via-[#F2B64A] to-[#C79A2E]",
  },
  Platform: {
    tile: "from-[#6E56F0] to-[#3E8BFF]",
    glow: "rgb(110 86 240 / 0.48)",
    line: "from-[#6E56F0] via-[#3E8BFF] to-[#6E56F0]",
  },
};
const DEFAULT_THEME = ADMIN_THEMES.Operations;

/** The admin page header: a navy banner in the section's colour. */
function AdminPageHero({
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
  const pathname = usePathname();
  const item = adminItemFor(pathname);
  const theme = (item?.group && ADMIN_THEMES[item.group]) || DEFAULT_THEME;
  const Icon = item?.icon;
  return (
    <section
      className={cn(
        // `dark`: buttons, inputs and badges inside take the dark theme's
        // colours, which read on navy.
        "admin-hero dark relative mb-6 overflow-hidden rounded-2xl px-5 py-5 text-white shadow-[0_24px_50px_-30px_rgba(5,11,24,0.8)] ring-1 ring-white/5 sm:px-6 sm:py-6 lg:mb-8",
      )}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-24 h-64 w-80 rounded-full blur-2xl"
        style={{ background: `radial-gradient(closest-side, ${theme.glow}, transparent)` }}
      />
      <div className="relative">
        {back ? (
          <Link
            href={back.href}
            className="-mt-1 mb-2 inline-flex min-h-9 items-center gap-1 text-sm font-medium text-white/70 transition-colors hover:text-white"
          >
            <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
              <path d="M15 6l-6 6 6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {back.label}
          </Link>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
          <div className="flex min-w-0 items-start gap-4">
            {Icon ? (
              <span
                aria-hidden
                className={cn(
                  "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-lg ring-1 ring-white/20",
                  theme.tile,
                )}
              >
                <Icon className="h-6 w-6" />
              </span>
            ) : null}
            <div className="min-w-0">
              {item?.group ? (
                <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-white/55">{item.group}</p>
              ) : null}
              <h1 className="text-balance text-2xl font-extrabold tracking-[-0.02em] text-white">{title}</h1>
              {description ? (
                <div className="mt-1 max-w-2xl text-pretty text-sm leading-relaxed text-white/70">{description}</div>
              ) : null}
            </div>
          </div>
          {action ? <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div> : null}
        </div>
      </div>
      <span aria-hidden className={cn("absolute inset-x-0 bottom-0 h-[3px] bg-gradient-to-r opacity-90", theme.line)} />
    </section>
  );
}

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
  const admin = React.useContext(AdminPortal);
  if (admin) return <AdminPageHero title={title} description={description} action={action} back={back} />;
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
