"use client";

import useSWR from "swr";

import { CopyIcon, SearchIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Skeleton } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome } from "@/lib/types";

/**
 * The homepage's picture of the product: the marketplace on a phone, with
 * today's real popular services and prices (the same public endpoint the
 * marketplace uses), and beside it an order that has received its code.
 *
 * Behind them, the one piece of geography that explains the product: a line
 * from the phone in your hand to a US number. No stock photography, no invented figures - the
 * only example values are the order's number (from the 555 range reserved for
 * fiction) and its code, and the card says so.
 */
export function HeroVisual() {
  const { data } = useSWR<MarketHome>("/marketplace/home/");
  const rows = (data?.popular ?? []).filter((row) => !row.temporarily_unavailable).slice(0, 5);

  return (
    <div className="relative mx-auto w-full max-w-md lg:max-w-none" aria-hidden>
      <RouteLine />

      <div className="relative flex justify-center lg:justify-start lg:pl-10">
        {/* Phone */}
        <div className="w-64 rounded-device border border-line-strong bg-surface p-2 shadow-pop">
          <div className="overflow-hidden rounded-3xl bg-canvas">
            <div className="flex items-center justify-between px-4 pb-1 pt-3 text-2xs text-ink-muted">
              <span className="tabular font-medium">9:41</span>
              <span className="h-1.5 w-12 rounded-full bg-line-strong" />
              <span className="flex items-end gap-0.5">
                <span className="h-1.5 w-0.5 rounded-sm bg-ink-muted" />
                <span className="h-2 w-0.5 rounded-sm bg-ink-muted" />
                <span className="h-2.5 w-0.5 rounded-sm bg-ink-muted" />
                <span className="h-3 w-0.5 rounded-sm bg-line-strong" />
              </span>
            </div>
            <div className="px-3 pb-3 pt-2">
              <p className="px-1 text-sm font-semibold text-ink">Buy a number</p>
              <div className="mt-2 flex h-8 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-caption text-ink-faint">
                <SearchIcon className="h-3.5 w-3.5" />
                Search services
              </div>
              <p className="mt-3 px-1 text-2xs font-medium text-ink-muted">Popular</p>
              <ul className="mt-1.5 divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
                {(rows.length ? rows : Array.from({ length: 5 }, () => null)).map((row, index) => (
                  <li key={row?.slug ?? index} className="flex h-11 items-center gap-2.5 px-2.5">
                    {row ? (
                      <>
                        <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="xs" />
                        <span className="min-w-0 flex-1 truncate text-caption font-medium text-ink">
                          {row.name}
                        </span>
                        <span className="tabular text-caption font-medium text-ink">
                          {row.price ? cedis(row.price) : "—"}
                        </span>
                      </>
                    ) : (
                      <>
                        <Skeleton className="h-7 w-7 rounded-lg" />
                        <Skeleton className="h-3 flex-1" />
                        <Skeleton className="h-3 w-12" />
                      </>
                    )}
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex h-9 items-center justify-center rounded-lg bg-primary text-caption font-medium text-white">
                Buy a number
              </div>
            </div>
          </div>
        </div>

        {/* The order, once the code has arrived. Desktop only: in the single-
            column layout it would sit on top of the phone's list. */}
        <div className="absolute -bottom-6 -right-2 hidden w-60 rounded-xl border border-line bg-raised shadow-pop lg:block">
          <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5">
            <ServiceLogo name="WhatsApp" src="/service-icons/whatsapp.svg" slug="whatsapp" size="xs" />
            <span className="flex-1 text-caption font-medium text-ink">WhatsApp</span>
            <span className="inline-flex items-center gap-1 rounded-md bg-success-50 px-1.5 py-0.5 text-2xs font-medium text-success-700">
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              Code received
            </span>
          </div>
          <div className="px-3.5 py-2.5">
            <p className="text-2xs text-ink-muted">Your number</p>
            <div className="mt-0.5 flex items-center justify-between gap-2">
              <span className="tabular text-sm font-semibold text-ink">+1 (512) 555-0147</span>
              <CopyIcon className="h-3.5 w-3.5 text-ink-faint" />
            </div>
          </div>
          <div className="rounded-b-xl border-t border-success-200 bg-success-50 px-3.5 py-2.5">
            <p className="text-2xs text-success-700">Verification code</p>
            <p className="code text-title font-semibold tracking-widest text-success-700">482913</p>
          </div>
        </div>
      </div>
    </div>
  );
}

/** From the phone in your hand to a US number: a dotted field, one route. */
function RouteLine() {
  return (
    <div className="pointer-events-none absolute -inset-6 hidden sm:block">
      <svg viewBox="0 0 520 440" preserveAspectRatio="xMidYMid slice" className="h-full w-full" fill="none">
        <defs>
          <pattern id="hero-dots" width="18" height="18" patternUnits="userSpaceOnUse">
            <circle cx="1.5" cy="1.5" r="1.2" className="fill-line-strong" />
          </pattern>
          <radialGradient id="hero-fade" cx="50%" cy="50%" r="60%">
            <stop offset="0%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <mask id="hero-mask">
            <rect width="520" height="440" fill="url(#hero-fade)" />
          </mask>
        </defs>
        <rect width="520" height="440" fill="url(#hero-dots)" mask="url(#hero-mask)" opacity="0.7" />
        <path
          d="M70 360 C 170 120, 360 60, 470 96"
          strokeWidth="1.5"
          strokeDasharray="4 6"
          className="stroke-brand-500"
          opacity="0.7"
        />
        <circle cx="470" cy="96" r="5" className="fill-brand-500" />
        <circle cx="470" cy="96" r="11" className="stroke-brand-500" opacity="0.35" />
        <text x="400" y="76" fontSize="11" fontWeight="500" className="fill-ink-muted">
          US number
        </text>
      </svg>
    </div>
  );
}
