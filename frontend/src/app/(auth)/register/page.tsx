"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { errorMessage, useAuth } from "@/components/auth-provider";
import { MailIcon } from "@/components/icons";
import {
  ReferralInviteBanner,
  clearReferralInvite,
  useReferralInvite,
} from "@/components/referral-invite";
import { ResendVerification } from "@/components/resend-verification";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Field,
  Input,
  PasswordInput,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";

/**
 * `felix@gmail.com` -> `f****@gmail.com`.
 *
 * Enough for someone to recognise the address they just typed, not enough to
 * be worth reading over their shoulder. The backend masks the same way.
 */
function maskEmail(address: string): string {
  const at = address.indexOf("@");
  if (at < 1) return address;
  const local = address.slice(0, at);
  const domain = address.slice(at);
  return `${local[0]}${"\u2022".repeat(Math.max(local.length - 1, 4))}${domain}`;
}

/** Mirrors the backend's minimum. Shown as guidance, enforced server-side. */
const MIN_PASSWORD_LENGTH = 10;

export default function RegisterPage() {
  const router = useRouter();
  const { signUp, user, ready } = useAuth();
  const invite = useReferralInvite();

  const [form, setForm] = React.useState({
    full_name: "",
    email: "",
    phone: "",
    password: "",
  });
  const [acceptedTerms, setAcceptedTerms] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  /** Set once registration succeeds; switches this route to the check-your-email panel. */
  const [registeredEmail, setRegisteredEmail] = React.useState("");

  /**
   * Set synchronously, before the registration request goes out.
   *
   * Registering signs the user in, and the effect below sends a signed-in
   * visitor to the dashboard. `signUp()` populates the auth cache, which
   * re-renders with `user` set *before* `setRegisteredEmail` has run - so a
   * state flag is checked too late and the user is redirected past the screen
   * telling them to go and check their inbox. A ref is written immediately and
   * closes that window.
   */
  const justRegistered = React.useRef(false);

  React.useEffect(() => {
    if (justRegistered.current) return;
    if (ready && user) router.replace("/dashboard");
  }, [ready, user, router]);

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [key]: event.target.value }));
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setFormError("");
    setFieldErrors({});

    if (!acceptedTerms) {
      setFieldErrors({ accepted_terms: "You must accept the Terms and Acceptable Use Policy." });
      return;
    }
    if (form.password.length < MIN_PASSWORD_LENGTH) {
      setFieldErrors({
        password: `Use at least ${MIN_PASSWORD_LENGTH} characters.`,
      });
      return;
    }

    setSubmitting(true);
    justRegistered.current = true;
    try {
      await signUp({
        email: form.email.trim(),
        password: form.password,
        full_name: form.full_name.trim(),
        phone: form.phone.trim(),
        accepted_terms: true,
        // Sent as-is. The backend resolves it, ignores anything it does not
        // recognise, and records the attribution itself.
        referral_code: invite.code || undefined,
      });
      clearReferralInvite();
      // Deliberately not redirected to the dashboard: the next thing they need
      // to do is open their email, and a dashboard would bury that.
      setRegisteredEmail(form.email.trim());
      setSubmitting(false);
    } catch (error) {
      // Registration failed, so this is an ordinary signed-out visitor again.
      justRegistered.current = false;
      if (error instanceof ApiError) {
        setFieldErrors(error.fieldErrors);
        setFormError(Object.keys(error.fieldErrors).length > 0 ? "" : errorMessage(error));
      } else {
        setFormError(errorMessage(error));
      }
      setSubmitting(false);
    }
  }

  if (registeredEmail) {
    return (
      <Card className="flex flex-col items-center p-8 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
          <MailIcon className="h-6 w-6" />
        </div>
        <h1 className="mt-4 text-title text-ink">Check your email</h1>
        <p className="mt-2 text-sm text-ink-muted">
          We&apos;ve sent a verification link to:
        </p>
        <p className="mt-1 break-all text-sm font-medium text-ink">
          {maskEmail(registeredEmail)}
        </p>
        <p className="mt-4 text-sm text-ink-muted">
          Please click the link in your email to verify your account. You will need a verified
          email address before you can buy a verification number.
        </p>

        <div className="mt-6 w-full">
          <ResendVerification authenticated />
        </div>

        <Link
          href="/dashboard"
          className="mt-4 text-sm font-medium text-brand-700 hover:underline"
        >
          Skip for now, go to dashboard
        </Link>
      </Card>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-title text-ink">Create your account</h1>
        <p className="mt-1.5 text-sm text-ink-muted">
          Free to create. You only pay when you buy a verification number.
        </p>
      </div>

      <Card className="p-5 sm:p-6">
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          <ReferralInviteBanner invite={invite} />

          {formError ? (
            <Alert tone="danger" title="Could not create your account">
              {formError}
            </Alert>
          ) : null}

          <Field label="Full name" htmlFor="full_name" error={fieldErrors.full_name}>
            <Input
              id="full_name"
              name="name"
              autoComplete="name"
              value={form.full_name}
              onChange={update("full_name")}
              invalid={Boolean(fieldErrors.full_name)}
              placeholder="Kwame Mensah"
            />
          </Field>

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
              value={form.email}
              onChange={update("email")}
              invalid={Boolean(fieldErrors.email)}
              placeholder="you@example.com"
            />
          </Field>

          <Field
            label="Mobile Money number"
            htmlFor="phone"
            error={fieldErrors.phone}
            hint="Optional now - you will need one to add money. Any format works."
          >
            <Input
              id="phone"
              name="tel"
              type="tel"
              inputMode="tel"
              autoComplete="tel-national"
              value={form.phone}
              onChange={update("phone")}
              invalid={Boolean(fieldErrors.phone)}
              placeholder="024 123 4567"
            />
          </Field>

          <Field
            label="Password"
            htmlFor="password"
            error={fieldErrors.password}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters. A short phrase works well.`}
            required
          >
            <PasswordInput
              id="password"
              name="new-password"
              autoComplete="new-password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              value={form.password}
              onChange={update("password")}
              invalid={Boolean(fieldErrors.password)}
              placeholder="Create a password"
            />
          </Field>

          <Checkbox
            id="accepted_terms"
            checked={acceptedTerms}
            onChange={(event) => setAcceptedTerms(event.target.checked)}
            error={fieldErrors.accepted_terms}
            label={
              <>
                I agree to the{" "}
                <Link href="/terms" target="_blank" className="font-medium text-brand-700 underline">
                  Terms of Service
                </Link>{" "}
                and the{" "}
                <Link
                  href="/acceptable-use"
                  target="_blank"
                  className="font-medium text-brand-700 underline"
                >
                  Acceptable Use Policy
                </Link>
                . I will not use VerifyGH for fraud, impersonation, spam, or to evade platform
                security or identity checks.
              </>
            }
          />

          <Button type="submit" size="lg" fullWidth loading={submitting}>
            Create account
          </Button>
        </form>
      </Card>

      <p className="mt-5 text-center text-sm text-ink-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-brand-700 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
