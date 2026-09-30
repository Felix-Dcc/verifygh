"use client";

import Link from "next/link";
import * as React from "react";

import { AccountMenu } from "@/components/account-menu";
import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand";
import { CloseIcon, LogoutIcon, MenuIcon } from "@/components/icons";
import { ButtonLink, cn } from "@/components/ui/primitives";

const LINKS = [
  { href: "/services", label: "Services" },
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
    <header className="sticky top-0 z-50 border-b border-line/80 bg-canvas/85 backdrop-blur-md">
      <div className="container-page flex h-16 items-center justify-between gap-4">
        <Link href="/" aria-label="VerifyGH home" className="rounded-lg">
          <Logo />
        </Link>

        <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-lg px-3 py-2 text-sm font-medium text-ink-soft transition-colors hover:bg-line/50 hover:text-ink"
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
              <ButtonLink href="/register" size="sm">Get started</ButtonLink>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-menu"
          aria-label={open ? "Close menu" : "Open menu"}
          className="-mr-2 rounded-xl p-2.5 text-ink-soft transition-colors hover:bg-line/50 lg:hidden"
        >
          {open ? <CloseIcon /> : <MenuIcon />}
        </button>
      </div>

      <div
        id="mobile-menu"
        hidden={!open}
        className={cn("border-t border-line bg-surface lg:hidden", open && "animate-fade-in")}
      >
        <nav className="container-page flex flex-col py-2" aria-label="Mobile">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setOpen(false)}
              className="rounded-lg px-2 py-3 text-base font-medium text-ink-soft hover:bg-line/40"
            >
              {link.label}
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
                  className="mt-1 flex items-center justify-center gap-2 rounded-xl border border-line-strong px-4 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:bg-canvas hover:text-ink"
                >
                  <LogoutIcon className="h-4 w-4" />
                  Log out
                </button>
              </>
            ) : (
              <>
                <ButtonLink href="/register" onClick={() => setOpen(false)} fullWidth>
                  Create free account
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
    title: "Product",
    links: [
      { href: "/services", label: "Supported services" },
      { href: "/#how-it-works", label: "How it works" },
      { href: "/#pricing", label: "Pricing" },
      { href: "/register", label: "Create an account" },
    ],
  },
  {
    title: "Support",
    links: [
      { href: "/#faq", label: "FAQ" },
      { href: "/#security", label: "Security" },
      { href: "mailto:support@verifygh.example", label: "Contact support" },
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

export function SiteFooter() {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="container-page py-12">
        <div className="grid grid-cols-1 gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="lg:col-span-1">
            <Logo />
            <p className="mt-3 max-w-xs text-sm text-ink-muted">
              A Ghanaian payment and access layer for supported verification services. Pay with
              MoMo. Verify with ease.
            </p>
            <div className="accent-rule mt-5 max-w-[7rem]" />
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
          <p className="text-sm text-ink-muted">
            &copy; {new Date().getFullYear()} VerifyGH. All rights reserved.
          </p>
          <p className="mt-3 max-w-3xl text-xs leading-relaxed text-ink-faint">
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
