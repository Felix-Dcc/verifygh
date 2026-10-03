/**
 * The single way this app talks to the backend.
 *
 * Three things it takes care of so no component has to:
 *
 * 1. **Cookies, not tokens.** Auth rides on httpOnly cookies, so every request
 *    sends `credentials: "include"` and nothing sensitive is ever held in JS.
 * 2. **CSRF.** The backend sets a readable `vgh_csrf` cookie; unsafe methods
 *    must echo it in `X-CSRF-Token`. A cross-site page cannot read our cookie,
 *    so it cannot forge that header.
 * 3. **One error shape.** The API always answers failures as
 *    `{error: {code, message, details}}`, which becomes an `ApiError` here.
 *    UI code switches on `error.code`, never on prose.
 *
 * There are no secrets in this file. There are no secrets anywhere in the
 * frontend bundle: API keys live only on the server.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const CSRF_COOKIE = "vgh_csrf";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;
  requestId?: string;

  constructor(
    message: string,
    code: string,
    status: number,
    details: Record<string, unknown> = {},
    requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }

  /** Field-level validation messages, ready to drop next to inputs. */
  get fieldErrors(): Record<string, string> {
    const fields = (this.details?.fields ?? {}) as Record<string, unknown>;
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(fields)) {
      out[key] = Array.isArray(value) ? String(value[0]) : String(value);
    }
    return out;
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.code === "AUTHENTICATION_REQUIRED";
  }
}

function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/([.$?*|{}()[\]\\/+^])/g, "\\$1")}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : "";
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  /** Extra query parameters; undefined and empty values are dropped. */
  params?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  /** Set for idempotent writes (purchases) so a retry cannot double-charge. */
  idempotencyKey?: string;
  /** Internal: prevents an infinite refresh loop. */
  _retried?: boolean;
};

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(
    path.startsWith("http") ? path : `${API_URL}${path.startsWith("/") ? path : `/${path}`}`,
  );
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function request<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };

  // FormData (a file upload) sets its own multipart boundary; everything else is JSON.
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  if (options.idempotencyKey) headers["X-Idempotency-Key"] = options.idempotencyKey;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.params), {
      method,
      headers,
      credentials: "include",
      signal: options.signal,
      body:
        options.body === undefined
          ? undefined
          : isForm
            ? (options.body as FormData)
            : JSON.stringify(options.body),
      cache: "no-store",
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new ApiError(
      "We could not reach VerifyGH. Check your connection and try again.",
      "NETWORK_ERROR",
      0,
    );
  }

  const payload = await parseBody(response);

  if (response.ok) return payload as T;

  // An expired access token is routine: refresh once, in the background, and
  // replay the original request rather than bouncing the user to sign-in.
  if (response.status === 401 && !options._retried && mayRefreshAfter(path)) {
    const refreshed = await tryRefresh();
    if (refreshed) return request<T>(path, { ...options, _retried: true });
  }

  const envelope = (payload as { error?: Record<string, unknown> })?.error;
  throw new ApiError(
    String(envelope?.message ?? "Something went wrong. Please try again."),
    String(envelope?.code ?? `HTTP_${response.status}`),
    response.status,
    (envelope?.details ?? {}) as Record<string, unknown>,
    envelope?.request_id as string | undefined,
  );
}

/**
 * Auth endpoints where a 401 is the answer itself - wrong password, no
 * session to renew, a bad reset link - not an access token that just expired.
 */
const NO_REFRESH_AUTH_PATHS = [
  "/auth/login/",
  "/auth/register/",
  "/auth/refresh/",
  "/auth/logout/",
  "/auth/password/reset/",
  "/auth/email/verify/confirm/",
  "/auth/sign-in-options/",
  "/auth/google/",
];

function mayRefreshAfter(path: string): boolean {
  if (!path.startsWith("/auth/")) return true;
  if (NO_REFRESH_AUTH_PATHS.some((prefix) => path.startsWith(prefix))) return false;
  // The session endpoints (/auth/me/ above all - every page load asks it who
  // is signed in) must renew too. Leaving them out signed everyone out the
  // moment their 20-minute access token lapsed, despite a 14-day session.
  // The CSRF cookie lives exactly as long as that session and is cleared on
  // sign-out, so without it there is nothing to renew: a signed-out visitor
  // costs no extra request.
  return Boolean(readCookie(CSRF_COOKIE));
}

let refreshInFlight: Promise<boolean> | null = null;

/** Refreshes the session. Concurrent callers share one request. */
export function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(buildUrl("/auth/refresh/"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then((response) => response.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export const api = {
  get: <T>(path: string, params?: RequestOptions["params"], signal?: AbortSignal) =>
    request<T>(path, { method: "GET", params, signal }),
  post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  delete: <T>(path: string, body?: unknown) => request<T>(path, { method: "DELETE", body }),
};

/** SWR fetcher. Accepts "/path" or ["/path", params]. */
export const fetcher = <T>(key: string | [string, Record<string, unknown>]) => {
  if (Array.isArray(key)) {
    return api.get<T>(key[0], key[1] as RequestOptions["params"]);
  }
  return api.get<T>(key);
};

/** A client-generated idempotency key, so a double-tap buys one number. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}
