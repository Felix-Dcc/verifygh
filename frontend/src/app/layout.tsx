import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { headers } from "next/headers";

import { THEME_SCRIPT } from "@/lib/theme";

import { Providers } from "./providers";
import "./globals.css";

const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME ?? "VerifyGH";

/**
 * IBM Plex: precise, slightly technical, with clear figures for money - it reads
 * as financial infrastructure rather than as a template. next/font downloads it
 * at build time and serves it from our own origin, so there is no request to a
 * font CDN and the CSP's font-src 'self' is unchanged. Mono is for codes,
 * references and phone numbers.
 */
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-sans",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-mono",
});

/**
 * Every page renders per request, never at build time.
 *
 * The Content-Security-Policy (src/middleware.ts) allows scripts only with a
 * nonce that is fresh for each request. A page prerendered at build time has
 * its HTML frozen before any request exists, so its scripts carry no nonce and
 * the browser blocks all of them - the app loads but never hydrates. Development
 * hides this, because there every page renders on demand anyway.
 *
 * The cost is losing static optimisation, which matters little here: nearly
 * every screen is per-user and fetches its data client-side regardless.
 */
export const dynamic = "force-dynamic";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_ORIGIN || "https://www.getverifygh.com";
const DESCRIPTION = "US numbers for SMS verification codes, paid for in cedis with Mobile Money.";

/**
 * Titles read "VerifyGH — Wallet" and so on: each route's layout supplies the
 * part after the dash. The favicon, Apple icon and link-preview images are
 * Next.js file conventions in this folder (favicon.ico, icon.svg,
 * apple-icon.png, opengraph-image.png, twitter-image.png) and manifest.ts, so
 * Next emits their <link>/<meta> tags itself - none are declared twice here.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${BRAND} \u2014 SMS Verification`,
    template: `${BRAND} \u2014 %s`,
  },
  description: DESCRIPTION,
  applicationName: BRAND,
  openGraph: {
    type: "website",
    siteName: BRAND,
    title: `${BRAND} \u2014 SMS Verification`,
    description: DESCRIPTION,
    url: "/",
    locale: "en_GH",
  },
  twitter: {
    card: "summary_large_image",
    title: `${BRAND} \u2014 SMS Verification`,
    description: DESCRIPTION,
  },
  appleWebApp: { title: BRAND, capable: true, statusBarStyle: "default" },
  keywords: ["Mobile Money", "Ghana", "MTN MoMo", "Telecel Cash", "verification", "GH₵"],
  robots: { index: true, follow: true },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Never lock zoom: pinch-to-zoom is an accessibility feature.
  maximumScale: 5,
  // The page background of each theme; the theme provider updates it when a
  // visitor picks a theme that differs from their device's.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F6F8F7" },
    { media: "(prefers-color-scheme: dark)", color: "#0B100E" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Reading the request headers is what ties rendering to the request. Next
  // picks the nonce up from the CSP header and stamps it on its own scripts.
  const nonce = headers().get("x-nonce") ?? undefined;

  return (
    // The head script adds "dark" before React hydrates, so the server's
    // className legitimately differs from the client's on first render.
    <html lang="en-GH" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        {/* Browsers hide a script's nonce from the DOM once it has run, so the
            client never sees the value the server rendered - not a mismatch. */}
        <script nonce={nonce} suppressHydrationWarning dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-dvh">
        {/* First stop for keyboard users, before the whole navigation. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
