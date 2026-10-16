"use client";

import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand";
import { Alert, Button, Card, Field, Input } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";

/**
 * The 6-digit email code, asked for before anything else in the app.
 *
 * Shown to every signed-in account whose email is not verified - right after
 * "Create account", and to older unverified accounts at their next visit.
 * The code is typed, not a link to click in the right browser, which is where
 * sign-ups were being lost (9 Oct 2026). The server decides everything: it
 * sends at most one code per 45 seconds, kills a code after 5 wrong tries,
 * and only it can mark the address verified.
 */

type Status = {
  verified: boolean;
  email: string;
  code_active: boolean;
  resend_in: number;
  sent?: boolean;
};

function clock(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function VerifyEmailGate() {
  const { user, refresh, signOut } = useAuth();
  const toast = useToast();
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [resendIn, setResendIn] = React.useState(0);
  const [sending, setSending] = React.useState(false);
  const [changing, setChanging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const started = React.useRef(false);

  React.useEffect(() => {
    if (resendIn <= 0) return;
    const timer = window.setTimeout(() => setResendIn((left) => Math.max(0, left - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [resendIn]);

  // First view: send a code, unless one is already on its way (the sign-up
  // email, or one sent a moment ago). A reload therefore sends nothing new.
  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const status = await api.get<Status>("/auth/email/verify/status/");
        setResendIn(status.resend_in);
        if (!status.code_active && status.resend_in === 0) {
          const sent = await api.post<Status>("/auth/email/verify/send/", {});
          setResendIn(sent.resend_in);
        }
      } catch {
        // The resend button below still works.
      }
    })();
  }, []);

  async function submit(value: string) {
    if (value.length !== 6 || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/auth/email/verify/code/", { code: value });
      toast.success("Email verified", "Welcome to VerifyGH.");
      await refresh(); // the account is now verified, so the app opens
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
      setCode("");
      inputRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setSending(true);
    setError("");
    try {
      const result = await api.post<Status>("/auth/email/verify/send/", {});
      setResendIn(result.resend_in);
      setCode("");
      if (result.sent) toast.success("New code sent", `Check ${result.email}.`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "We couldn't send a code. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="flex h-16 items-center justify-between px-4 sm:px-6">
        <Logo />
        <button
          type="button"
          onClick={() => signOut()}
          className="min-h-11 rounded-lg px-2 text-sm font-medium text-ink-muted hover:text-ink"
        >
          Sign out
        </button>
      </header>

      <main id="main" className="flex flex-1 items-start justify-center px-4 pb-10 pt-4 sm:items-center">
        <div className="w-full max-w-104">
          <Card className="p-6 sm:p-8">
            {changing ? (
              <ChangeEmail
                current={user?.email ?? ""}
                onCancel={() => setChanging(false)}
                onChanged={(status) => {
                  setChanging(false);
                  setCode("");
                  setError("");
                  setResendIn(status.resend_in);
                  toast.success("Code sent", `We sent a new code to ${status.email}.`);
                }}
                refresh={refresh}
              />
            ) : (
              <>
                <h1 className="text-title text-ink">Enter the code we emailed you</h1>
                <p className="mt-2 text-sm text-ink-muted">
                  We sent a 6-digit code to{" "}
                  <span className="wrap-break-word font-medium text-ink">{user?.email}</span>.{" "}
                  <button
                    type="button"
                    onClick={() => setChanging(true)}
                    className="font-medium text-brand-700 hover:underline"
                  >
                    Wrong address?
                  </button>
                </p>

                <form
                  className="mt-6"
                  noValidate
                  onSubmit={(event) => {
                    event.preventDefault();
                    submit(code);
                  }}
                >
                  <label htmlFor="email-code" className="sr-only">
                    6-digit code
                  </label>
                  <input
                    ref={inputRef}
                    id="email-code"
                    name="one-time-code"
                    // Lets phones offer the code straight from the email.
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength={6}
                    autoFocus
                    value={code}
                    onChange={(event) => {
                      const next = event.target.value.replace(/\D/g, "").slice(0, 6);
                      setCode(next);
                      if (next.length === 6) submit(next);
                    }}
                    placeholder="······"
                    aria-describedby="email-code-help"
                    className="code h-14 w-full rounded-lg border border-line-strong bg-surface px-4 text-center text-title font-semibold tracking-[0.5em] text-ink transition-shadow placeholder:text-ink-faint focus:border-brand-500 focus:shadow-focus focus:outline-hidden"
                  />
                  <p id="email-code-help" className="mt-2 text-center text-caption text-ink-faint">
                    The code expires in 15 minutes.
                  </p>

                  {error ? (
                    <Alert tone="danger" className="mt-4">
                      {error}
                    </Alert>
                  ) : null}

                  <Button type="submit" size="lg" fullWidth loading={busy} disabled={code.length !== 6} className="mt-4">
                    Verify email
                  </Button>
                </form>

                <p className="mt-5 text-center text-sm text-ink-muted">
                  Didn&apos;t get it? Check Spam or Promotions.{" "}
                  {resendIn > 0 ? (
                    <span className="tabular text-ink-faint">Resend code in {clock(resendIn)}</span>
                  ) : (
                    <button
                      type="button"
                      onClick={resend}
                      disabled={sending}
                      className="font-medium text-brand-700 hover:underline disabled:opacity-60"
                    >
                      {sending ? "Sending…" : "Resend code"}
                    </button>
                  )}
                </p>
                <p className="mt-4 text-center text-caption text-ink-faint">
                  A verified email keeps your wallet and orders reachable. You need it to add funds and buy numbers.
                </p>
              </>
            )}
          </Card>
        </div>
      </main>
    </div>
  );
}

function ChangeEmail({
  current,
  onCancel,
  onChanged,
  refresh,
}: {
  current: string;
  onCancel: () => void;
  onChanged: (status: Status) => void;
  refresh: () => Promise<void>;
}) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      const status = await api.post<Status>("/auth/email/change/", {
        new_email: email.trim(),
        password,
      });
      await refresh();
      onChanged(status);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFieldErrors(caught.fieldErrors);
        setError(Object.keys(caught.fieldErrors).length ? "" : caught.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <div>
        <h1 className="text-title text-ink">Change your email</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Currently <span className="wrap-break-word font-medium text-ink">{current}</span>. We&apos;ll send a new
          code to the address you enter.
        </p>
      </div>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <Field label="Correct email address" htmlFor="new-email" error={fieldErrors.new_email}>
        <Input
          id="new-email"
          type="email"
          inputMode="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          invalid={Boolean(fieldErrors.new_email)}
          placeholder="you@gmail.com"
        />
      </Field>
      <Field label="Your password" htmlFor="change-password" error={fieldErrors.password}>
        <Input
          id="change-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          invalid={Boolean(fieldErrors.password)}
        />
      </Field>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Back
        </Button>
        <Button type="submit" loading={busy} disabled={!email.trim() || !password}>
          Send code to this address
        </Button>
      </div>
    </form>
  );
}
