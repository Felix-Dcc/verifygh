"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import {
  GoogleButton,
  OrDivider,
  googleProblem,
  googleStartUrl,
  useGoogleSignIn,
} from "@/components/auth/google-sign-in";
import { TURNSTILE_SITE_KEY, Turnstile, type TurnstileHandle } from "@/components/auth/turnstile";
import { errorMessage, useAuth } from "@/components/auth-provider";
import { Alert, Button, Field, Input, PasswordInput } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  return (
    <React.Suspense fallback={null}>
      <LoginForm />
    </React.Suspense>
  );
}

/** Only a path on this site - never somewhere a crafted link points. */
function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.includes("\\") ? raw : "/dashboard";
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn, user, ready } = useAuth();
  const google = useGoogleSignIn();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [humanToken, setHumanToken] = React.useState<string | null>(null);
  const [humanError, setHumanError] = React.useState("");
  const turnstile = React.useRef<TurnstileHandle>(null);

  const next = safeNext(params.get("next"));
  const googleError = googleProblem(params.get("google"));

  // Already signed in? Do not make them look at a sign-in form.
  React.useEffect(() => {
    if (ready && user) router.replace(user.role === "USER" ? next : "/admin");
  }, [ready, user, router, next]);

  const onToken = React.useCallback((token: string | null) => {
    setHumanToken(token);
    if (token) setHumanError("");
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setFormError("");
    setFieldErrors({});
    if (TURNSTILE_SITE_KEY && !humanToken) {
      setHumanError("Complete the security check first.");
      return;
    }

    setSubmitting(true);
    try {
      const account = await signIn(email.trim(), password, humanToken ?? undefined);
      router.replace(account.role === "USER" ? next : "/admin");
    } catch (error) {
      if (error instanceof ApiError && error.code === "HUMAN_CHECK_FAILED") {
        setHumanError(error.message);
      } else if (error instanceof ApiError) {
        setFieldErrors(error.fieldErrors);
        setFormError(Object.keys(error.fieldErrors).length > 0 ? "" : errorMessage(error));
      } else {
        setFormError(errorMessage(error));
      }
      // Cloudflare's token works once; this attempt has spent it.
      turnstile.current?.reset();
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight text-ink">Welcome back</h1>
      <p className="mt-1.5 text-sm text-ink-muted">Sign in to your VerifyGH wallet and orders.</p>

      <div className="mt-6 space-y-3 empty:hidden">
        {params.get("reset") === "1" ? (
          <Alert tone="success" title="Password updated">
            Sign in with your new password.
          </Alert>
        ) : null}
        {googleError ? (
          <Alert tone="danger" title="Google sign-in did not finish">
            {googleError}
          </Alert>
        ) : null}
      </div>

      <form onSubmit={onSubmit} noValidate className="mt-6 space-y-5">
        {formError ? (
          <Alert tone="danger" title="Could not sign in">
            {formError}
          </Alert>
        ) : null}

        <Field label="Email address" htmlFor="email" error={fieldErrors.email} required>
          <Input
            id="email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            invalid={Boolean(fieldErrors.email)}
            placeholder="you@example.com"
          />
        </Field>

        <Field
          label="Password"
          htmlFor="password"
          error={fieldErrors.password}
          required
          action={
            <Link href="/forgot-password" className="text-sm font-medium text-brand-700 hover:underline">
              Forgot password?
            </Link>
          }
        >
          <PasswordInput
            id="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            invalid={Boolean(fieldErrors.password)}
            placeholder="Your password"
          />
        </Field>

        {TURNSTILE_SITE_KEY ? (
          <div>
            <Turnstile ref={turnstile} action="login" onToken={onToken} />
            {humanError ? (
              <p role="alert" className="mt-1.5 text-sm text-danger-700">
                {humanError}
              </p>
            ) : null}
          </div>
        ) : null}

        <Button type="submit" variant="dawn" size="lg" fullWidth loading={submitting}>
          Sign in with password
        </Button>
      </form>

      {google ? (
        <div className="mt-6 space-y-6">
          <OrDivider />
          <GoogleButton href={googleStartUrl({ intent: "signin", next })} />
        </div>
      ) : null}

      <p className="mt-8 text-center text-sm text-ink-muted">
        New to VerifyGH?{" "}
        <Link href="/register" className="font-semibold text-brand-700 hover:underline">
          Create an account
        </Link>
      </p>
    </div>
  );
}
