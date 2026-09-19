import { NextResponse, type NextRequest } from "next/server";

/**
 * Content-Security-Policy, with a per-request nonce.
 *
 * A nonce rather than `'unsafe-inline'` for scripts: this app shows wallet
 * balances and one-time verification codes, so an injected script is the worst
 * thing that can happen to it. `'strict-dynamic'` lets Next's own bootstrap
 * script load the chunks it needs without us enumerating hashes.
 *
 * Next.js reads the nonce out of the `Content-Security-Policy` request header
 * we set below and stamps it onto the script tags it renders.
 *
 * Two deliberate relaxations, both narrow:
 *
 * - `style-src` allows `'unsafe-inline'`. Next injects inline `<style>` blocks
 *   for its CSS, and a nonce cannot be threaded through all of them. Inline
 *   style is a far smaller risk than inline script: it cannot execute.
 * - In development only, `'unsafe-eval'` and `ws:` are allowed, because
 *   hot-module replacement needs both. Neither is present in production.
 */

const isDev = process.env.NODE_ENV === "development";

/** The API origin, so `connect-src` does not have to be a wildcard. */
function apiOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL ?? "";
  try {
    return new URL(raw).origin;
  } catch {
    return "";
  }
}

function buildCsp(nonce: string): string {
  const api = apiOrigin();

  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      ...(isDev ? ["'unsafe-eval'"] : []),
    ],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'", api, ...(isDev ? ["ws:", "wss:"] : [])].filter(Boolean),
    "form-action": ["'self'"],
    // Clickjacking: this app moves money, so it is never framed.
    "frame-ancestors": ["'none'"],
    "frame-src": ["'none'"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "manifest-src": ["'self'"],
    "worker-src": ["'self'", "blob:"],
  };

  const csp = Object.entries(directives)
    .map(([key, values]) => `${key} ${values.join(" ")}`)
    .join("; ");

  return isDev ? csp : `${csp}; upgrade-insecure-requests`;
}

export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp(nonce);

  // Next reads the nonce from the request-side header to stamp its scripts.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    /*
     * Everything except static assets and prefetches. Hashing a nonce into a
     * prefetch response would make it uncacheable for no benefit, and static
     * files do not execute.
     */
    {
      source: "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
