import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";
import { headers } from "next/headers";

import { THEME_SCRIPT } from "@/lib/theme";

import { Providers } from "./providers";
import "./globals.css";

const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME ?? "VerifyGH";

/**
 * Inter for the interface: modern, highly legible at phone sizes, with true
 * tabular figures for money. A variable font, so every weight is one file.
 * latin-ext carries the cedi sign (U+20B5) - without it "GH₵" would fall back
 * to a system font mid-word. IBM Plex Mono stays for codes, references and
 * phone numbers. next/font serves both from our own origin, so the CSP's
 * font-src 'self' is unchanged.
 */
const sans = Inter({
  subsets: ["latin", "latin-ext"],
  display: "swap",
  // Not --font-sans: the theme defines that name (globals.css) in terms of this.
  variable: "--font-inter",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-plex-mono",
});

/**
 * Every page renders per request, never at build time.
 *
 * The Content-Security-Policy (src/proxy.ts) allows scripts only with a
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
/**
 * What a search result and a shared link say under the title. Written for the
 * searches people in Ghana actually make ("US number for WhatsApp
 * verification", "pay with MoMo"), and kept to what is always true: no prices,
 * which move with the provider and the cedi.
 */
const DESCRIPTION =
  "Receive SMS verification codes on a US number for WhatsApp, TikTok, Google and more. " +
  "Pay in cedis with MTN MoMo, Telecel Cash or AT Money. Refunded if no code arrives.";
const DEFAULT_TITLE = `${BRAND} \u2014 US Numbers for SMS Verification, Paid with MoMo`;

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
    default: DEFAULT_TITLE,
    template: `${BRAND} \u2014 %s`,
  },
  description: DESCRIPTION,
  applicationName: BRAND,
  openGraph: {
    type: "website",
    siteName: BRAND,
    title: DEFAULT_TITLE,
    description: DESCRIPTION,
    url: "/",
    locale: "en_GH",
  },
  twitter: {
    card: "summary_large_image",
    title: DEFAULT_TITLE,
    description: DESCRIPTION,
  },
  appleWebApp: { title: BRAND, capable: true, statusBarStyle: "default" },
  keywords: [
    "US number for verification",
    "SMS verification Ghana",
    "virtual number Ghana",
    "Mobile Money",
    "MTN MoMo",
    "Telecel Cash",
    "GH₵",
  ],
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

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Reading the request headers is what ties rendering to the request. Next
  // picks the nonce up from the CSP header and stamps it on its own scripts.
  const nonce = (await headers()).get("x-nonce") ?? undefined;

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
