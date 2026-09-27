"use client";

import Link from "next/link";
import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { AlertIcon, CheckCircleIcon } from "@/components/icons";
import { ResendVerification } from "@/components/resend-verification";
import { Button, Card, Spinner } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";

/**
 * The verification screen, shared by both link shapes.
 *
 * New emails link to `/verify-email/<token>`. Links already sitting in inboxes
 * use `/verify-email?token=<token>`, and must keep working, so both routes
 * render this.
 *
 * The four states come from the backend's error codes, never from parsing a
 * message: `TOKEN_EXPIRED` and `INVALID_TOKEN` are the only two it reports for
 * a bad link, and anything else is treated as invalid rather than surfaced.
 * Nothing here prints an exception, a stack trace or the token itself.
 */
type State = "verifying" | "success" | "expired" | "invalid" | "missing";

export function VerifyEmailFlow({ token }: { token: string }) {
  const { refresh, user } = useAuth();
  const signedIn = Boolean(user);

  const [state, setState] = React.useState<State>(token ? "verifying" : "missing");

  /**
   * Guards against React running the effect twice in development's strict
   * mode. The token is single-use, so a second call would consume nothing and
   * report "already used" - turning a good link into a failure on screen.
   */
  const attempted = React.useRef("");

  React.useEffect(() => {
    if (!token || attempted.current === token) return;
    attempted.current = token;

    // Deliberately no "cancelled" flag. The usual reason for one - a stale
    // response overwriting a newer one - cannot arise here, because the ref
    // above means exactly one request is ever made per token. With a flag, the
    // cleanup from strict mode's first mount discards the only response there
    // will be, and the screen spins forever on an account that did verify.
    (async () => {
      try {
        await api.post("/auth/email/verify/confirm/", { token });
        setState("success");
        // Pick up is_email_verified so the purchase gate lifts immediately,
        // without the user having to sign out and back in. Only worth doing
        // when there is a session to refresh; signed out, it is a guaranteed
        // 401.
        if (signedIn) await refresh();
      } catch (error) {
        const code = error instanceof ApiError ? error.code : "";
        setState(code === "TOKEN_EXPIRED" ? "expired" : "invalid");
      }
    })();
  }, [token, refresh, signedIn]);

  if (state === "verifying") {
    return (
      <Card className="flex flex-col items-center p-10 text-center">
        <Spinner className="h-7 w-7 text-brand-600" />
        <p className="mt-4 text-sm text-ink-muted">Verifying your email...</p>
      </Card>
    );
  }

  if (state === "success") {
    return (
      <Card className="flex flex-col items-center p-8 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-success-50 text-success-700">
          <CheckCircleIcon className="h-6 w-6" />
        </div>
        <h1 className="mt-4 text-xl font-semibold text-ink">Email verified successfully.</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Your email has been verified. You can now use VerifyGH.
        </p>
        <Link href={user ? "/dashboard" : "/login"} className="mt-6 w-full">
          <Button fullWidth size="lg">
            {user ? "Continue to Dashboard" : "Sign in"}
          </Button>
        </Link>
      </Card>
    );
  }

  const heading =
    state === "expired"
      ? "This verification link has expired."
      : state === "missing"
        ? "This verification link is incomplete."
        : "This verification link is invalid or has already been used.";

  const detail =
    state === "expired"
      ? "Verification links are valid for a limited time. Send yourself a new one to finish setting up your account."
      : state === "missing"
        ? "The link is missing its verification token. Open the most recent email we sent you, or send yourself a new one."
        : "Send yourself a new verification email to finish setting up your account.";

  return (
    <Card className="flex flex-col items-center p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-warn-50 text-warn-700">
        <AlertIcon className="h-6 w-6" />
      </div>
      <h1 className="mt-4 text-xl font-semibold text-ink">{heading}</h1>
      <p className="mt-2 text-sm text-ink-muted">{detail}</p>

      <div className="mt-6 w-full">
        {user ? (
          // Signed in: the backend knows who is asking, so no address is needed.
          <ResendVerification authenticated label="Send New Verification Email" />
        ) : (
          <>
            <p className="mb-4 text-sm text-ink-muted">
              Sign in to send yourself a new verification email.
            </p>
            <Link href="/login" className="block w-full">
              <Button fullWidth size="lg">
                Sign in
              </Button>
            </Link>
          </>
        )}
      </div>
    </Card>
  );
}
