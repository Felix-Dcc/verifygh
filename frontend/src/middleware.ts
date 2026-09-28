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

/**
 * The site's own address. Unset in development, which turns the redirect off.
 */
const SITE_ORIGIN = process.env.NEXT_PUBLIC_SITE_ORIGIN ?? "";

/**
 * Railway's generated hostname for this service, which predates the real
 * domain and is still linked from old messages and bookmarks.
 *
 * Signing in cannot work there. The session cookies belong to the site's own
 * domain and are SameSite=Lax, so a browser on *.up.railway.app neither keeps
 * nor sends them: the password is accepted, and the very next request finds no
 * session and sends the customer back to the sign-in page. From their side it
 * is indistinguishable from a wrong password. Send them to the real domain
 * before they get that far.
 *
 * Matched by suffix, not by "anything that is not the canonical host": the
 * apex domain is served directly and works, and Railway's health check arrives
 * on a hostname of its own that must get a 200, not a redirect.
 */
function legacyHostRedirect(request: NextRequest): NextResponse | null {
  if (!SITE_ORIGIN) return null;
  const host = (request.headers.get("host") ?? "").split(":")[0].toLowerCase();
  if (!host.endsWith(".up.railway.app")) return null;

  const target = new URL(request.nextUrl.pathname + request.nextUrl.search, SITE_ORIGIN);
  // 308 keeps the method, and browsers remember it.
  return NextResponse.redirect(target, 308);
}

export function middleware(request: NextRequest) {
  const redirect = legacyHostRedirect(request);
  if (redirect) return redirect;

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
