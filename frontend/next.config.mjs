import path from "node:path";
import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // The repository root has its own package-lock.json (the Railway SDK), which
  // Next 16 would otherwise take for the workspace root.
  turbopack: { root: path.dirname(fileURLToPath(import.meta.url)) },
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Content-Security-Policy is set per-request in src/middleware.ts,
          // because it carries a nonce. frame-ancestors there covers framing;
          // X-Frame-Options is kept for browsers that predate CSP level 2.
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          {
            key: "Permissions-Policy",
            value:
              "accelerometer=(), autoplay=(), camera=(), display-capture=(), " +
              "encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), " +
              "magnetometer=(), microphone=(), midi=(), payment=(), usb=(), " +
              "xr-spatial-tracking=()",
          },
          // Browsers ignore HSTS over plain http, so this is inert locally.
          // No `preload`: that is a one-way commitment for the whole domain
          // and should be a deliberate decision, not a default.
          ...(process.env.NODE_ENV === "production"
            ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
            : []),
        ],
      },
      {
        // Bundled service logos and brand icons: tiny, shared by every row that
        // shows them, and only ever replaced by a new deploy.
        source: "/:dir(service-icons|icons)/:file*",
        headers: [
          { key: "Cache-Control", value: "public, max-age=604800, stale-while-revalidate=86400" },
        ],
      },
    ];
  },
};

export default nextConfig;
