"use client";

import * as React from "react";
import useSWR from "swr";

import type { Attribution } from "@/components/attribution";
import { Spinner, buttonClasses, cn } from "@/components/ui/primitives";
import { API_URL } from "@/lib/api";

/** Whether this deployment offers "Continue with Google" (the API knows). */
export function useGoogleSignIn(): boolean {
  const { data } = useSWR<{ google: boolean }>("/auth/sign-in-options/", {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return Boolean(data?.google);
}

/**
 * Where the button goes: the API's start of the Google flow, which sends the
 * browser on to Google's account chooser. Nothing Google ships runs on our
 * pages - the API does the exchange (backend/apps/accounts/google.py).
 */
export function googleStartUrl({
  intent,
  next,
  acceptedTerms,
  referralCode,
  attribution,
}: {
  intent: "signin" | "signup";
  next?: string;
  acceptedTerms?: boolean;
  referralCode?: string;
  /** Sent on a sign-up only; the API records it if an account is created. */
  attribution?: Attribution;
}): string {
  const params = new URLSearchParams({ intent });
  if (next) params.set("next", next);
  if (acceptedTerms) params.set("terms", "1");
  if (referralCode) params.set("ref", referralCode);
  for (const [key, value] of Object.entries(attribution ?? {})) {
    if (value) params.set(key, value);
  }
  return `${API_URL}/auth/google/start/?${params.toString()}`;
}

/** What went wrong, from the `?google=` the API sends people back with. */
export function googleProblem(code: string | null): string | null {
  switch (code) {
    case null:
    case "":
      return null;
    case "cancelled":
      return "Google sign-in was cancelled. Choose an account to continue, or use your email.";
    case "expired":
      return "That Google sign-in took too long or was opened in another tab. Please try again.";
    case "unverified":
      return "Google has not verified that email address yet, so we cannot use it to sign you in.";
    case "suspended":
      return "This account is suspended. Contact support if you think this is a mistake.";
    case "conflict":
      return "This email address is already linked to a different Google account. Sign in with your password instead.";
    case "unavailable":
      return "Google sign-in is not available right now. Use your email and password instead.";
    case "busy":
      return "Too many attempts. Wait a minute, then try again.";
    default:
      return "We could not sign you in with Google. Please try again.";
  }
}

/** Google's "G", in its own four colours - as Google's branding guidelines ask. */
export function GoogleMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={cn("h-5 w-5", className)} aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

/**
 * "Continue with Google": a real link (middle-click and screen readers work),
 * styled as the form's second button. `beforeLeave` can stop the navigation -
 * the sign-up form uses it to insist on the terms first.
 */
export function GoogleButton({
  href,
  beforeLeave,
  label = "Continue with Google",
}: {
  href: string;
  beforeLeave?: () => boolean;
  label?: string;
}) {
  const [leaving, setLeaving] = React.useState(false);

  // Coming back with the browser's Back button restores this page from the
  // back-forward cache, spinner and all; reset it.
  React.useEffect(() => {
    const onShow = (event: PageTransitionEvent) => {
      if (event.persisted) setLeaving(false);
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  return (
    <a
      href={href}
      onClick={(event) => {
        if (beforeLeave && !beforeLeave()) {
          event.preventDefault();
          return;
        }
        // A new tab or window keeps this page as it is.
        if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) {
          setLeaving(true);
        }
      }}
      aria-busy={leaving || undefined}
      className={buttonClasses({
        variant: "secondary",
        size: "lg",
        fullWidth: true,
        className: "gap-3 font-semibold shadow-sm",
      })}
    >
      {leaving ? <Spinner className="h-5 w-5" /> : <GoogleMark />}
      {leaving ? "Opening Google…" : label}
    </a>
  );
}

/** The "or" between the email form and the Google button. */
export function OrDivider({ label = "or" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3" role="separator" aria-label={label}>
      <span className="h-px flex-1 bg-line" />
      <span className="text-caption font-medium uppercase tracking-wider text-ink-faint">{label}</span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}
