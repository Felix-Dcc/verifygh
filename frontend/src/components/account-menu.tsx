"use client";

import Link from "next/link";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import {
  GiftIcon,
  LogoutIcon,
  ReceiptIcon,
  UserIcon,
  WalletIcon,
} from "@/components/icons";
import { cn } from "@/components/ui/primitives";

const LINKS = [
  { href: "/dashboard", label: "Dashboard", icon: UserIcon },
  { href: "/wallet", label: "Wallet", icon: WalletIcon },
  { href: "/orders", label: "Orders", icon: ReceiptIcon },
  { href: "/refer", label: "Refer & earn", icon: GiftIcon },
];

/** `Kwame Mensah` -> `KM`, `felix@gmail.com` -> `F`. */
function initials(name: string, email: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (email[0] ?? "?").toUpperCase();
}

/**
 * The signed-in account menu for the public site header.
 *
 * It exists because signing out was only reachable from inside the app shell
 * and the account page. A customer who landed on the marketing homepage while
 * signed in had no way out at all - the header offered "Go to dashboard" and
 * nothing else.
 */
export function AccountMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = React.useState(false);
  const wrapper = React.useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape. Without both, a menu opened by
  // accident on a phone is genuinely hard to dismiss.
  React.useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent | TouchEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div className="relative" ref={wrapper}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-lg border border-line-strong bg-surface py-1.5 pl-1.5 pr-2.5 text-sm font-medium text-ink transition-colors hover:bg-sunken/60"
      >
        <span
          aria-hidden
          className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-600 text-xs font-semibold text-white"
        >
          {initials(user.full_name, user.email)}
        </span>
        <span className="max-w-[9rem] truncate">
          {user.full_name || user.email}
        </span>
        <svg
          viewBox="0 0 20 20"
          aria-hidden
          className={cn("h-4 w-4 text-ink-faint transition-transform", open && "rotate-180")}
        >
          <path
            d="M6 8l4 4 4-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-64 overflow-hidden rounded-xl border border-line bg-surface shadow-raised animate-fade-in"
        >
          <div className="border-b border-line px-4 py-3">
            <p className="truncate text-sm font-semibold text-ink">
              {user.full_name || "Your account"}
            </p>
            <p className="truncate text-xs text-ink-muted">{user.email}</p>
          </div>

          <div className="py-1">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                role="menuitem"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2.5 px-4 py-2.5 text-sm text-ink-soft transition-colors hover:bg-sunken/60 hover:text-ink"
              >
                <link.icon className="h-4 w-4 text-ink-faint" />
                {link.label}
              </Link>
            ))}
          </div>

          <div className="border-t border-line py-1">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                void signOut();
              }}
              className="flex w-full items-center gap-2.5 px-4 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:bg-sunken/60 hover:text-ink"
            >
              <LogoutIcon className="h-4 w-4 text-ink-faint" />
              Log out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
