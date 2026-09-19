"use client";

import { AppShell } from "@/components/app-shell";
import { useRequireAuth } from "@/components/auth-provider";
import { Spinner } from "@/components/ui/primitives";

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

  return <AppShell variant="admin">{children}</AppShell>;
}
