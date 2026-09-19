import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";

import { Providers } from "./providers";
import "./globals.css";

const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME ?? "VerifyGH";

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

export const metadata: Metadata = {
  title: {
    default: `${BRAND} - Verification made simple.`,
    template: `%s | ${BRAND}`,
  },
  description:
    "Access supported phone verification services and pay conveniently with Ghana Mobile Money. No card, no crypto.",
  applicationName: BRAND,
  keywords: ["Mobile Money", "Ghana", "MTN MoMo", "Telecel Cash", "verification", "GHS"],
  robots: { index: true, follow: true },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Never lock zoom: pinch-to-zoom is an accessibility feature.
  maximumScale: 5,
  themeColor: "#0B6446",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Reading the request headers is what ties rendering to the request. Next
  // picks the nonce up from the CSP header and stamps it on its own scripts.
  headers().get("x-nonce");

  return (
    <html lang="en-GH">
      <body className="min-h-dvh">
        {/* First stop for keyboard users, before the whole navigation. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-brand-600 focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
