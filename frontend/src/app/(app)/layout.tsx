"use client";

import { AppShell } from "@/components/app-shell";
import { useRequireAuth } from "@/components/auth-provider";
import { Spinner } from "@/components/ui/primitives";
import { VerifyEmailGate } from "@/components/verify-email-gate";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, ready } = useRequireAuth();

  // Hold the shell back until we know who is signed in, so a signed-out
  // visitor never sees a flash of someone's dashboard chrome.
  if (!ready || !user) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas">
        <Spinner className="h-7 w-7 text-brand-600" />
        <span className="sr-only">Loading your account</span>
      </div>
    );
  }

  // Nothing else in the app until the email is verified: the 6-digit code
  // comes first, for new sign-ups and older unverified accounts alike. The
  // server enforces the same rule on top-ups and purchases.
  if (!user.is_email_verified) return <VerifyEmailGate />;

  return <AppShell>{children}</AppShell>;
}
