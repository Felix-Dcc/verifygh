"use client";

import Link from "next/link";
import * as React from "react";

import { AccountMenu } from "@/components/account-menu";
import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand";
import { ChevronRightIcon, CloseIcon, LogoutIcon, MenuIcon } from "@/components/icons";
import { ThemeSwitcher } from "@/components/theme";
import { ButtonLink, cn } from "@/components/ui/primitives";
import { APP_PAGES } from "@/lib/app-pages";

const LINKS = [
  { href: "/#products", label: "Products" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#pricing", label: "Pricing" },
  { href: "/#security", label: "Security" },
  { href: "/#faq", label: "FAQ" },
];

export function SiteHeader() {
  const { user, ready, signOut } = useAuth();
  const [open, setOpen] = React.useState(false);

  // Close the mobile menu on navigation so a tap never leaves it hanging open.
  React.useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("hashchange", close);
    return () => window.removeEventListener("hashchange", close);
  }, [open]);

  return (
    <header className="sticky top-0 z-50 border-b border-line/70 bg-surface/90 shadow-[0_1px_12px_-6px_rgba(5,11,24,0.18)] backdrop-blur-md">
      <div className="container-page flex h-16 items-center justify-between gap-4">
        <Link href="/" aria-label="VerifyGH home" className="flex min-h-11 items-center rounded-lg">
          <Logo />
        </Link>

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-lg px-3 py-2 text-sm font-medium text-ink-soft transition-colors hover:bg-sunken hover:text-ink"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          {!ready ? (
            <div className="h-10 w-40" aria-hidden />
          ) : user ? (
            <>
              <ButtonLink href="/dashboard" size="sm">Go to dashboard</ButtonLink>
              {/* Signing out used to be reachable only from inside the app
                  shell, so a customer who landed here while signed in had no
                  way out of their session at all. */}
              <AccountMenu />
            </>
          ) : (
            <>
              <ButtonLink href="/login" variant="ghost" size="sm">Sign in</ButtonLink>
              <ButtonLink href="/register" size="sm" variant="dawn">Get started</ButtonLink>
            </>
          )}
        </div>

        <div className="flex items-center gap-1 lg:hidden">
        {ready ? (
          <Link
            href={user ? "/dashboard" : "/login"}
            className="flex min-h-11 items-center rounded-lg px-3 text-sm font-semibold text-ink transition-colors hover:bg-sunken"
          >
            {user ? "Dashboard" : "Sign in"}
          </Link>
        ) : null}
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-menu"
          aria-label={open ? "Close menu" : "Open menu"}
          className="-mr-2 flex h-11 w-11 items-center justify-center rounded-lg text-ink-soft transition-colors hover:bg-sunken lg:hidden"
        >
          {open ? <CloseIcon /> : <MenuIcon />}
        </button>
        </div>
      </div>

      <div
        id="mobile-menu"
        hidden={!open}
        className={cn(
          "max-h-[calc(100dvh-4rem)] overflow-y-auto border-t border-line bg-surface shadow-pop lg:hidden",
          open && "animate-fade-in",
        )}
      >
        <nav className="container-page flex flex-col py-3" aria-label="Mobile">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setOpen(false)}
              className="flex items-center justify-between rounded-xl px-3 py-3.5 text-lg font-semibold tracking-tight text-ink hover:bg-sunken"
            >
              {link.label}
              <ChevronRightIcon className="h-4 w-4 text-ink-faint" />
            </Link>
          ))}
          <div className="mt-2 flex flex-col gap-2 border-t border-line pt-3 pb-4">
            {user ? (
              <>
                <ButtonLink href="/dashboard" onClick={() => setOpen(false)} fullWidth>
                  Go to dashboard
                </ButtonLink>
                <ButtonLink href="/wallet" onClick={() => setOpen(false)} variant="secondary" fullWidth>
                  Wallet
                </ButtonLink>
                <ButtonLink href="/orders" onClick={() => setOpen(false)} variant="secondary" fullWidth>
                  Orders
                </ButtonLink>
                {/* Reachable without leaving the phone layout, which is where
                    most of this traffic is. */}
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    void signOut();
                  }}
                  className="mt-1 flex items-center justify-center gap-2 rounded-lg border border-line-strong px-4 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:bg-sunken/60 hover:text-ink"
                >
                  <LogoutIcon className="h-4 w-4" />
                  Log out
                </button>
              </>
            ) : (
              <>
                <ButtonLink href="/register" onClick={() => setOpen(false)} fullWidth size="lg" variant="dawn">
                  Get started free
                </ButtonLink>
                <ButtonLink href="/login" onClick={() => setOpen(false)} variant="secondary" fullWidth>
                  Sign in
                </ButtonLink>
              </>
            )}
          </div>
        </nav>
      </div>
    </header>
  );
}

const FOOTER_SECTIONS = [
  {
    title: "US numbers for",
    links: APP_PAGES.map((page) => ({ href: `/us-number/${page.slug}`, label: page.name })),
  },
  {
    title: "Product",
    links: [
      { href: "/services", label: "SMS verification" },
      { href: "/#how-it-works", label: "How it works" },
      { href: "/#pricing", label: "Pricing" },
      { href: "/#security", label: "Security" },
    ],
  },
  {
    title: "Support",
    links: [
      { href: "/help", label: "Help centre" },
      { href: "/#faq", label: "FAQ" },
      { href: "mailto:support@getverifygh.com", label: "Contact support" },
    ],
  },
  {
    title: "Legal",
    links: [
      { href: "/terms", label: "Terms of Service" },
      { href: "/acceptable-use", label: "Acceptable Use Policy" },
      { href: "/privacy", label: "Privacy Policy" },
    ],
  },
];

/**
 * `seamless`: the page above already fades into the footer's colour, so no rule.
 * `night`: the homepage's navy footer - the close ramps into it. The subtree
 * takes the dark theme's tokens (`dark`), so text and the theme switcher read
 * on navy in either theme.
 */
export function SiteFooter({ seamless = false, night = false }: { seamless?: boolean; night?: boolean }) {
  return (
    <footer
      className={cn(
        night ? "dark bg-navy-deep text-ink" : seamless ? "bg-surface" : "border-t border-line bg-surface",
      )}
    >
      <div className="container-page py-12">
        <div className="grid grid-cols-1 gap-10 sm:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-1">
            <Logo />
            <p className="mt-3 text-base font-semibold tracking-tight text-ink">
              Verify privately. Verify simply.
            </p>
            <p className="mt-1.5 max-w-xs text-sm text-ink-muted">
              US numbers for verification codes, paid for in cedis with Mobile Money.
            </p>
          </div>

          {FOOTER_SECTIONS.map((section) => (
            <div key={section.title}>
              <h3 className="text-sm font-semibold text-ink">{section.title}</h3>
              <ul className="mt-3 space-y-2.5">
                {section.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-sm text-ink-muted transition-colors hover:text-ink"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 border-t border-line pt-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-ink-muted">
              &copy; {new Date().getFullYear()} VerifyGH. All rights reserved.
            </p>
            <ThemeSwitcher compact />
          </div>
          <p className="mt-3 max-w-3xl text-caption leading-relaxed text-ink-faint">
            VerifyGH provides access to verification services supplied by authorised third-party
            providers. We are not affiliated with, endorsed by, or acting on behalf of any of the
            services a number may be used to verify. You remain responsible for complying with the
            terms of any service you use a number with. VerifyGH may not be used for fraud,
            impersonation, spam, evading bans or security controls, or circumventing identity
            checks - see our{" "}
            <Link href="/acceptable-use" className="underline hover:text-ink-muted">
              Acceptable Use Policy
            </Link>
            .
          </p>
        </div>
      </div>
    </footer>
  );
}
