"use client";

import Link from "next/link";
import * as React from "react";

import { errorMessage } from "@/components/auth-provider";
import { Alert, Button, Card, Field, Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [sent, setSent] = React.useState(false);
  const [error, setError] = React.useState("");

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await api.post("/auth/password/reset/", { email: email.trim() });
      setSent(true);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Check your email</h1>
        <p className="mt-1.5 text-sm text-ink-muted">
          If an account exists for <span className="font-medium text-ink">{email}</span>, a reset
          link is on its way. The link expires in 2 hours and can only be used once.
        </p>
        <Card className="mt-6 p-5">
          <p className="text-sm text-ink-muted">
            Nothing arrived? Check your spam folder, then try again in a few minutes. For your
            security we do not confirm whether an email address is registered.
          </p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <Button variant="secondary" fullWidth onClick={() => setSent(false)}>
              Try another email
            </Button>
            <Link href="/login" className="w-full">
              <Button fullWidth>Back to sign in</Button>
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Reset your password</h1>
        <p className="mt-1.5 text-sm text-ink-muted">
          Enter the email on your account and we will send you a reset link.
        </p>
      </div>

      <Card className="p-5 sm:p-6">
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          {error ? (
            <Alert tone="danger" title="Could not send the link">
              {error}
            </Alert>
          ) : null}

          <Field label="Email address" htmlFor="email" required>
            <Input
              id="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </Field>

          <Button type="submit" size="lg" fullWidth loading={submitting}>
            Send reset link
          </Button>
        </form>
      </Card>

      <p className="mt-5 text-center text-sm text-ink-muted">
        Remembered it?{" "}
        <Link href="/login" className="font-medium text-brand-700 hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
