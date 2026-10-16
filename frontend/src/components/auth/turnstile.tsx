"use client";

import * as React from "react";

import { useTheme } from "@/components/theme";
import { cn } from "@/components/ui/primitives";

/**
 * Cloudflare Turnstile's site key. Public by design (it is in every page that
 * shows the widget); the secret half lives only on the API. Unset - locally,
 * and until the widget is created - and there is no check to show.
 */
export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

type TurnstileApi = {
  render: (container: HTMLElement, options: Record<string, unknown>) => string | undefined;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

/** The flexible widget is never narrower than this; below it, the compact one. */
const FLEXIBLE_MIN_WIDTH = 300;

let loading: Promise<TurnstileApi> | null = null;

/**
 * Loads api.js once. Added by our own (nonce-trusted) code, which the CSP's
 * 'strict-dynamic' extends trust to; the challenge itself runs in Cloudflare's
 * iframe, the one origin `frame-src` allows (src/proxy.ts).
 */
function loadTurnstile(): Promise<TurnstileApi> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!loading) {
    loading = new Promise<TurnstileApi>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = SCRIPT_SRC;
      script.async = true;
      script.onload = () =>
        window.turnstile ? resolve(window.turnstile) : reject(new Error("Turnstile did not start"));
      script.onerror = () => {
        loading = null;
        script.remove();
        reject(new Error("Turnstile did not load"));
      };
      document.head.appendChild(script);
    });
  }
  return loading;
}

export type TurnstileHandle = {
  /** A token works once: fetch a fresh one after every attempt. */
  reset: () => void;
};

/**
 * Cloudflare's human check, as the box with its "Success!" tick and the
 * Cloudflare mark. Reports a token when solved and `null` when the token
 * expires, errors or is reset - the form sends whatever it last heard.
 */
export const Turnstile = React.forwardRef<
  TurnstileHandle,
  { action: string; onToken: (token: string | null) => void; className?: string }
>(function Turnstile({ action, onToken, className }, ref) {
  const container = React.useRef<HTMLDivElement>(null);
  const widget = React.useRef<{ id: string; theme: string } | null>(null);
  const report = React.useRef(onToken);
  report.current = onToken;
  const [failed, setFailed] = React.useState(false);
  // Re-run when the site's theme changes, so the widget matches it.
  const { resolved } = useTheme();

  React.useImperativeHandle(ref, () => ({
    reset() {
      report.current(null);
      if (widget.current && window.turnstile) window.turnstile.reset(widget.current.id);
    },
  }));

  React.useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return;
    // The class on <html> is the truth; the provider's state can lag a render.
    const theme = document.documentElement.classList.contains("dark") ? "dark" : "light";
    if (widget.current?.theme === theme) return;

    let cancelled = false;
    loadTurnstile()
      .then((turnstile) => {
        const element = container.current;
        if (cancelled || !element) return;
        if (widget.current) {
          turnstile.remove(widget.current.id);
          widget.current = null;
          report.current(null);
        }
        const id = turnstile.render(element, {
          sitekey: TURNSTILE_SITE_KEY,
          action,
          theme,
          size: element.clientWidth >= FLEXIBLE_MIN_WIDTH ? "flexible" : "compact",
          callback: (token: string) => report.current(token),
          "expired-callback": () => report.current(null),
          "timeout-callback": () => report.current(null),
          "error-callback": () => {
            report.current(null);
            // Cloudflare shows its own error and retries; returning true tells
            // it we have handled the callback, so nothing is thrown.
            return true;
          },
        });
        if (id) widget.current = { id, theme };
        setFailed(false);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [action, resolved]);

  // Remove the widget when the form goes away.
  React.useEffect(
    () => () => {
      if (widget.current && window.turnstile) window.turnstile.remove(widget.current.id);
      widget.current = null;
    },
    [],
  );

  if (!TURNSTILE_SITE_KEY) return null;

  return (
    <div className={className}>
      {/* 65px is the widget's own height: the form does not jump when it lands. */}
      <div ref={container} className={cn("min-h-[65px] w-full", failed && "hidden")} />
      {failed ? (
        <p role="alert" className="rounded-lg border border-line bg-sunken px-3 py-2.5 text-sm text-ink-muted">
          The security check could not load. Check your connection, then reload the page.
        </p>
      ) : null}
    </div>
  );
});
