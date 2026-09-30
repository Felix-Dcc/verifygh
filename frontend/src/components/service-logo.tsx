"use client";

import * as React from "react";

import { cn } from "@/lib/cn";

/**
 * A service's logo - the one component every screen uses, so a service looks
 * the same in the marketplace, the purchase screen, an order and the admin.
 *
 * `src` is whatever the backend says (`Service.icon_url`): a bundled tile from
 * /service-icons/ (generated from Simple Icons, CC0 - see SOURCES.json there)
 * or a logo staff uploaded. The frontend holds no catalogue of logos itself.
 *
 * The bundled tiles carry their own brand-coloured background, so they read on
 * any surface. Anything missing or failing to load becomes the same neutral
 * tile - never a broken image - and development builds say which service
 * needs a logo.
 */

const SIZES = {
  // Chips ("Recently used").
  xs: "h-7 w-7",
  // Marketplace rows: 32px on phones, 36px from the small breakpoint up.
  sm: "h-8 w-8 sm:h-9 sm:w-9",
  md: "h-9 w-9",
  lg: "h-12 w-12",
  xl: "h-16 w-16",
} as const;

const PIXELS = { xs: 28, sm: 36, md: 36, lg: 48, xl: 64 } as const;

const warned = new Set<string>();

export function ServiceLogo({
  name,
  src,
  slug,
  size = "md",
  className,
}: {
  name: string;
  src?: string | null;
  slug?: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [src]);

  const missing = !src || failed;

  React.useEffect(() => {
    if (!missing || process.env.NODE_ENV === "production") return;
    const key = slug || name;
    if (warned.has(key)) return;
    warned.add(key);
    console.warn(`Missing service logo: ${key}`);
  }, [missing, slug, name]);

  if (missing) {
    return (
      <span
        role="img"
        aria-label={`${name} (no logo)`}
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-[23%] border border-line bg-canvas text-ink-faint",
          SIZES[size],
          className,
        )}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
          strokeLinecap="round" strokeLinejoin="round" className="h-1/2 w-1/2" aria-hidden="true">
          <rect x="6" y="2.5" width="12" height="19" rx="2.5" />
          <path d="M10.5 18.5h3" />
        </svg>
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex shrink-0 overflow-hidden rounded-[23%] bg-line/50",
        SIZES[size],
        className,
      )}
    >
      {/* A plain <img>: the files are tiny SVGs (or small validated PNGs),
          already cached, and need no resizing pipeline. */}
      {/* Decorative: the service name is always written beside the logo, so
          alt text would only make screen readers say it twice. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt=""
        width={PIXELS[size]}
        height={PIXELS[size]}
        loading="lazy"
        decoding="async"
        draggable={false}
        onError={() => setFailed(true)}
        className="h-full w-full object-contain"
      />
    </span>
  );
}
