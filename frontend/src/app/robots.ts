import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_ORIGIN || "https://www.getverifygh.com";

/**
 * /robots.txt. Cloudflare's managed robots.txt adds its content-signal lines
 * in front of this; what we add is where the sitemap is, and which screens are
 * private (they only ever show a crawler the sign-in page).
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/admin",
        "/dashboard",
        "/wallet",
        "/orders",
        "/rentals",
        "/transactions",
        "/account",
        "/refer",
        "/verify-email",
        "/reset-password",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
