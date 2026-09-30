"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { errorMessage, useAuth } from "@/components/auth-provider";
import { Alert, Button, Card, Field, Input, PasswordInput } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  return (
    <React.Suspense fallback={null}>
      <LoginForm />
    </React.Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn, user, ready } = useAuth();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  const next = params.get("next") ?? "/dashboard";

  // Already signed in? Do not make them look at a sign-in form.
  React.useEffect(() => {
    if (ready && user) router.replace(next);
  }, [ready, user, router, next]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setFormError("");
    setFieldErrors({});

    try {
      const account = await signIn(email.trim(), password);
      router.replace(account.role === "USER" ? next : "/admin");
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldErrors(error.fieldErrors);
        setFormError(
          Object.keys(error.fieldErrors).length > 0 ? "" : errorMessage(error),
        );
      } else {
        setFormError(errorMessage(error));
      }
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-title text-ink">Welcome back</h1>
        <p className="mt-1.5 text-sm text-ink-muted">
          Sign in to your VerifyGH wallet and orders.
        </p>
      </div>

      {params.get("reset") === "1" ? (
        <Alert tone="success" className="mb-4" title="Password updated">
          Sign in with your new password.
        </Alert>
      ) : null}

      <Card className="p-5 sm:p-6">
        <form onSubmit={onSubmit} noValidate className="space-y-4">
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

          <div>
            <Field label="Password" htmlFor="password" error={fieldErrors.password} required>
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
            <div className="mt-2 text-right">
              <Link
                href="/forgot-password"
                className="text-sm font-medium text-brand-700 hover:underline"
              >
                Forgot your password?
              </Link>
            </div>
          </div>

          <Button type="submit" size="lg" fullWidth loading={submitting}>
            Sign in
          </Button>
        </form>
      </Card>

      <p className="mt-5 text-center text-sm text-ink-muted">
        New to VerifyGH?{" "}
        <Link href="/register" className="font-medium text-brand-700 hover:underline">
          Create an account
        </Link>
      </p>
    </div>
  );
}
