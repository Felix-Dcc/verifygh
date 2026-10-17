"use client";

import { TwoFactorSettings } from "@/components/account/two-factor";
import { AppShell } from "@/components/app-shell";
import { useRequireAuth } from "@/components/auth-provider";
import { Card, CardHeader, Spinner } from "@/components/ui/primitives";

/**
 * The admin console is gated twice: this guard keeps a customer from ever
 * seeing the chrome, and every admin endpoint independently enforces the role
 * matrix server-side. The client check is convenience, not security.
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, ready } = useRequireAuth({ staffOnly: true });

  if (!ready || !user || user.role === "USER") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas">
        <Spinner className="h-7 w-7 text-brand-600" />
        <span className="sr-only">Checking your access</span>
      </div>
    );
  }

  if (user.two_factor_required && !user.is_two_factor_enabled) {
    // Every admin endpoint refuses these accounts (TWO_FACTOR_SETUP_REQUIRED);
    // show the way in rather than a console full of errors.
    return (
      <AppShell variant="admin">
        <div className="mx-auto max-w-2xl">
          <Card>
            <CardHeader
              title="Set up two-factor sign-in to continue"
              description="The admin console needs a code from your phone as well as your password."
            />
            <TwoFactorSettings />
          </Card>
        </div>
      </AppShell>
    );
  }

  return <AppShell variant="admin">{children}</AppShell>;
}
