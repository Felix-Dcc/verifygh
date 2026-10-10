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
import {
  ReferralInviteBanner,
  clearReferralInvite,
  useReferralInvite,
} from "@/components/referral-invite";
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

/** Mirrors the backend's minimum. Shown as guidance, enforced server-side. */
const MIN_PASSWORD_LENGTH = 10;

export default function RegisterPage() {
  return (
    <React.Suspense fallback={null}>
      <RegisterForm />
    </React.Suspense>
  );
}

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signUp, user, ready } = useAuth();
  const invite = useReferralInvite();
  const google = useGoogleSignIn();
  const googleError = googleProblem(params.get("google"));

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
  const [humanToken, setHumanToken] = React.useState<string | null>(null);
  const [humanError, setHumanError] = React.useState("");
  const turnstile = React.useRef<TurnstileHandle>(null);

  const onToken = React.useCallback((token: string | null) => {
    setHumanToken(token);
    if (token) setHumanError("");
  }, []);

  /** The terms come first for Google too: stop the navigation and say so. */
  function termsFirst(): boolean {
    if (acceptedTerms) return true;
    setFieldErrors({ accepted_terms: "Tick this box to accept the terms, then continue with Google." });
    document.getElementById("accepted_terms")?.focus();
    return false;
  }

  /**
   * Set synchronously, before the registration request goes out.
   *
   * Registering signs the user in, and the effect below sends a signed-in
   * visitor to the dashboard. While a registration is in flight that effect
   * stands aside, so a failed attempt keeps the form and its errors on screen;
   * a successful one is sent on by `onSubmit` itself.
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
    if (TURNSTILE_SITE_KEY && !humanToken) {
      setHumanError("Complete the security check first.");
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
        turnstile_token: humanToken ?? undefined,
      });
      clearReferralInvite();
      // Straight on to the 6-digit code: the app asks for it before anything
      // else (components/verify-email-gate.tsx), with the address shown in full
      // so a typo is caught now.
      router.replace("/dashboard");
    } catch (error) {
      // Registration failed, so this is an ordinary signed-out visitor again.
      justRegistered.current = false;
      // Cloudflare's token works once; this attempt has spent it.
      turnstile.current?.reset();
      if (error instanceof ApiError && error.code === "HUMAN_CHECK_FAILED") {
        setHumanError(error.message);
      } else if (error instanceof ApiError) {
        setFieldErrors(error.fieldErrors);
        setFormError(Object.keys(error.fieldErrors).length > 0 ? "" : errorMessage(error));
      } else {
        setFormError(errorMessage(error));
      }
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight text-ink">Create your account</h1>
      <p className="mt-1.5 text-sm text-ink-muted">
        Free to create. You only pay when you buy a verification number.
      </p>

      {googleError ? (
        <Alert tone="danger" title="Google sign-up did not finish" className="mt-6">
          {googleError}
        </Alert>
      ) : null}

      <div className="mt-6">
        <form onSubmit={onSubmit} noValidate className="space-y-5">
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

          {TURNSTILE_SITE_KEY ? (
            <div>
              <Turnstile ref={turnstile} action="register" onToken={onToken} />
              {humanError ? (
                <p role="alert" className="mt-1.5 text-sm text-danger-700">
                  {humanError}
                </p>
              ) : null}
            </div>
          ) : null}

          <Button type="submit" variant="dawn" size="lg" fullWidth loading={submitting}>
            Create account
          </Button>
        </form>
      </div>

      {google ? (
        <div className="mt-6 space-y-6">
          <OrDivider />
          <GoogleButton
            label="Sign up with Google"
            beforeLeave={termsFirst}
            href={googleStartUrl({
              intent: "signup",
              acceptedTerms,
              referralCode: invite.code || undefined,
            })}
          />
        </div>
      ) : null}

      <p className="mt-8 text-center text-sm text-ink-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-brand-700 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
