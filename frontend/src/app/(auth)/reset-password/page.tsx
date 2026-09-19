"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { errorMessage } from "@/components/auth-provider";
import { Alert, Button, Card, Field, Input } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";

const MIN_PASSWORD_LENGTH = 10;

export default function ResetPasswordPage() {
  return (
    <React.Suspense fallback={null}>
      <ResetPasswordForm />
    </React.Suspense>
  );
}

function ResetPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setFieldErrors({});

    if (password !== confirm) {
      setFieldErrors({ confirm: "The two passwords do not match." });
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setFieldErrors({ new_password: `Use at least ${MIN_PASSWORD_LENGTH} characters.` });
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/password/reset/confirm/", { token, new_password: password });
      router.replace("/login?reset=1");
    } catch (caught) {
      if (caught instanceof ApiError) setFieldErrors(caught.fieldErrors);
      setError(errorMessage(caught));
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <Card className="p-6">
        <h1 className="text-xl font-semibold text-ink">This link is not valid</h1>
        <p className="mt-2 text-sm text-ink-muted">
          The reset link is missing its token. Request a new one and use the most recent email.
        </p>
        <Link href="/forgot-password" className="mt-5 block">
          <Button fullWidth>Request a new link</Button>
        </Link>
      </Card>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Choose a new password</h1>
        <p className="mt-1.5 text-sm text-ink-muted">
          Once you save it, you will be signed out everywhere else.
        </p>
      </div>

      <Card className="p-5 sm:p-6">
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          {error ? (
            <Alert tone="danger" title="Could not reset your password">
              {error}
            </Alert>
          ) : null}

          <Field
            label="New password"
            htmlFor="new_password"
            error={fieldErrors.new_password}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
            required
          >
            <Input
              id="new_password"
              type="password"
              autoComplete="new-password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              invalid={Boolean(fieldErrors.new_password)}
            />
          </Field>

          <Field label="Confirm new password" htmlFor="confirm" error={fieldErrors.confirm} required>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              invalid={Boolean(fieldErrors.confirm)}
            />
          </Field>

          <Button type="submit" size="lg" fullWidth loading={submitting}>
            Save new password
          </Button>
        </form>
      </Card>
    </div>
  );
}
