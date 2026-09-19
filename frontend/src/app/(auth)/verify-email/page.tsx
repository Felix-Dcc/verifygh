"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { errorMessage, useAuth } from "@/components/auth-provider";
import { AlertIcon, CheckCircleIcon } from "@/components/icons";
import { Button, Card, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";

export default function VerifyEmailPage() {
  return (
    <React.Suspense fallback={null}>
      <VerifyEmail />
    </React.Suspense>
  );
}

type State = "checking" | "verified" | "failed" | "missing";

function VerifyEmail() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const { refresh, user } = useAuth();

  const [state, setState] = React.useState<State>(token ? "checking" : "missing");
  const [message, setMessage] = React.useState("");

  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;

    (async () => {
      try {
        await api.post("/auth/email/verify/confirm/", { token });
        if (cancelled) return;
        setState("verified");
        // Pick up is_email_verified so the purchase gate lifts immediately.
        await refresh();
      } catch (error) {
        if (cancelled) return;
        setMessage(errorMessage(error));
        setState("failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, refresh]);

  if (state === "checking") {
    return (
      <Card className="flex flex-col items-center p-10 text-center">
        <Spinner className="h-7 w-7 text-brand-600" />
        <p className="mt-4 text-sm text-ink-muted">Confirming your email address...</p>
      </Card>
    );
  }

  if (state === "verified") {
    return (
      <Card className="flex flex-col items-center p-8 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-success-50 text-success-700">
          <CheckCircleIcon className="h-6 w-6" />
        </div>
        <h1 className="mt-4 text-xl font-semibold text-ink">Email confirmed</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Your account is fully set up. You can add money and start buying verification numbers.
        </p>
        <Link href={user ? "/dashboard" : "/login"} className="mt-6 w-full">
          <Button fullWidth size="lg">
            {user ? "Go to dashboard" : "Sign in"}
          </Button>
        </Link>
      </Card>
    );
  }

  return (
    <Card className="flex flex-col items-center p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-warn-50 text-warn-700">
        <AlertIcon className="h-6 w-6" />
      </div>
      <h1 className="mt-4 text-xl font-semibold text-ink">
        {state === "missing" ? "This link is incomplete" : "This link did not work"}
      </h1>
      <p className="mt-2 text-sm text-ink-muted">
        {state === "missing"
          ? "The verification link is missing its token. Open the most recent email we sent you."
          : message ||
            "The link may have expired or already been used. Sign in and send yourself a new one."}
      </p>
      <Link href={user ? "/account" : "/login"} className="mt-6 w-full">
        <Button fullWidth size="lg">
          {user ? "Send a new link" : "Sign in"}
        </Button>
      </Link>
    </Card>
  );
}
