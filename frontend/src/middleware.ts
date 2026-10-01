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
 *
 * Cloudflare Turnstile, once a site key is configured: its `api.js` loads with
 * our nonce (which `'strict-dynamic'` honours), and its challenge runs in an
 * iframe from https://challenges.cloudflare.com - the one origin allowed in
 * `frame-src`, as Cloudflare's CSP guidance specifies. Without a site key
 * nothing is relaxed.
 */

const isDev = process.env.NODE_ENV === "development";

const TURNSTILE_ORIGIN = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY
  ? "https://challenges.cloudflare.com"
  : "";

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
      // Ignored by CSP3 browsers under 'strict-dynamic'; lets older ones load it.
      ...(TURNSTILE_ORIGIN ? [TURNSTILE_ORIGIN] : []),
      ...(isDev ? ["'unsafe-eval'"] : []),
    ],
    "style-src": ["'self'", "'unsafe-inline'"],
    // The API origin serves logos staff upload (/api/v1/service-logos/...).
    "img-src": ["'self'", "data:", "blob:", api].filter(Boolean),
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'", api, ...(isDev ? ["ws:", "wss:"] : [])].filter(Boolean),
    "form-action": ["'self'"],
    // Clickjacking: this app moves money, so it is never framed.
    "frame-ancestors": ["'none'"],
    "frame-src": TURNSTILE_ORIGIN ? [TURNSTILE_ORIGIN] : ["'none'"],
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

/**
 * Only traffic that came through Cloudflare reaches the site (docs/CLOUDFLARE.md).
 *
 * A Cloudflare Transform Rule sets `X-VerifyGH-Origin` to a secret on every
 * request it forwards, overwriting anything a visitor sent. Without it, a
 * request reached Railway directly - around Cloudflare's WAF and bot checks.
 *
 * CLOUDFLARE_MODE: off (nothing checked), report (logged, not refused) or
 * enforce (403). Server-side variables only: the secret never reaches a
 * browser bundle. Railway's health check is always let through.
 */
const CLOUDFLARE_MODE = (process.env.CLOUDFLARE_MODE ?? "off").trim().toLowerCase();
const CLOUDFLARE_ORIGIN_SECRET = process.env.CLOUDFLARE_ORIGIN_SECRET ?? "";
const ORIGIN_HEADER = "x-verifygh-origin";

function sameSecret(given: string, secret: string): boolean {
  // Constant time in the length of the secret.
  let diff = given.length ^ secret.length;
  for (let i = 0; i < secret.length; i++) {
    diff |= (given.charCodeAt(i) || 0) ^ secret.charCodeAt(i);
  }
  return diff === 0;
}

function originCheck(request: NextRequest): NextResponse | null {
  if (CLOUDFLARE_MODE === "off") return null;
  const host = (request.headers.get("host") ?? "").split(":")[0].toLowerCase();
  if (host === "healthcheck.railway.app") return null;
  const given = request.headers.get(ORIGIN_HEADER) ?? "";
  if (CLOUDFLARE_ORIGIN_SECRET && sameSecret(given, CLOUDFLARE_ORIGIN_SECRET)) return null;

  console.warn(
    JSON.stringify({
      event: "request_not_via_cloudflare",
      mode: CLOUDFLARE_MODE,
      host: host.slice(0, 80),
      path: request.nextUrl.pathname.slice(0, 120),
    }),
  );
  if (CLOUDFLARE_MODE !== "enforce") return null;
  return new NextResponse("Forbidden", { status: 403 });
}

export function middleware(request: NextRequest) {
  const redirect = legacyHostRedirect(request);
  if (redirect) return redirect;

  const refused = originCheck(request);
  if (refused) return refused;

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp(nonce);

  // Next reads the nonce from the request-side header to stamp its scripts.
  const requestHeaders = new Headers(request.headers);
  // The origin secret has done its job; the app never needs to see it.
  requestHeaders.delete(ORIGIN_HEADER);
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
      source:
        "/((?!_next/static|_next/image|favicon.ico|icon.svg|apple-icon.png|manifest.webmanifest|opengraph-image|twitter-image|icons/|service-icons/|networks/|robots.txt|sitemap.xml).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
