"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/app-shell";
import { errorMessage, useAuth } from "@/components/auth-provider";
import { BellIcon, CheckCircleIcon, LockIcon, LogoutIcon, ShieldIcon } from "@/components/icons";
import { ConfirmDialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  Input,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDate, localPhone } from "@/lib/format";

export default function AccountPage() {
  const { user, refresh, signOut } = useAuth();
  const toast = useToast();

  const [profile, setProfile] = React.useState({ full_name: "", phone: "" });
  const [savingProfile, setSavingProfile] = React.useState(false);
  const [profileErrors, setProfileErrors] = React.useState<Record<string, string>>({});

  const [passwords, setPasswords] = React.useState({ current_password: "", new_password: "" });
  const [savingPassword, setSavingPassword] = React.useState(false);
  const [passwordErrors, setPasswordErrors] = React.useState<Record<string, string>>({});

  const [resending, setResending] = React.useState(false);
  const [confirmSignOut, setConfirmSignOut] = React.useState(false);

  React.useEffect(() => {
    if (!user) return;
    setProfile({ full_name: user.full_name, phone: localPhone(user.phone) });
  }, [user]);

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    setSavingProfile(true);
    setProfileErrors({});
    try {
      await api.patch("/auth/me/", profile);
      await refresh();
      toast.success("Profile updated");
    } catch (error) {
      if (error instanceof ApiError) setProfileErrors(error.fieldErrors);
      toast.error("Could not save", errorMessage(error));
    } finally {
      setSavingProfile(false);
    }
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    setSavingPassword(true);
    setPasswordErrors({});
    try {
      await api.post("/auth/password/change/", passwords);
      setPasswords({ current_password: "", new_password: "" });
      toast.success("Password changed", "Other sessions have been signed out.");
    } catch (error) {
      if (error instanceof ApiError) setPasswordErrors(error.fieldErrors);
      toast.error("Could not change your password", errorMessage(error));
    } finally {
      setSavingPassword(false);
    }
  }

  async function resendVerification() {
    setResending(true);
    try {
      await api.post("/auth/email/verify/send/", {});
      toast.success("Verification email sent", "Check your inbox and your spam folder.");
    } catch (error) {
      toast.error("Could not send it", errorMessage(error));
    } finally {
      setResending(false);
    }
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <PageHeader title="Account" description="Your details, security and preferences." />

      <Card className="p-5">
        <div className="flex items-center gap-4">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-brand-100 text-lg font-semibold text-brand-700">
            {(user.full_name || user.email).slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className="truncate text-base font-semibold text-ink">
              {user.full_name || "Your account"}
            </p>
            <p className="truncate text-sm text-ink-muted">{user.email}</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {user.is_email_verified ? (
                <Badge tone="success" dot>
                  Email confirmed
                </Badge>
              ) : (
                <Badge tone="warn" dot>
                  Email not confirmed
                </Badge>
              )}
              {user.role !== "USER" ? <Badge tone="brand">{user.role}</Badge> : null}
              <Badge tone="neutral">Joined {formatDate(user.created_at)}</Badge>
            </div>
          </div>
        </div>
      </Card>

      {!user.is_email_verified ? (
        <Alert
          tone="warn"
          title="Confirm your email address"
          action={
            <Button size="sm" variant="secondary" loading={resending} onClick={resendVerification}>
              Resend
            </Button>
          }
        >
          Purchases stay locked until you confirm {user.email}.
        </Alert>
      ) : null}

      <Card>
        <CardHeader title="Your details" description="Used on receipts and by support." />
        <form onSubmit={saveProfile} className="space-y-4 p-4 pt-4 sm:p-5 sm:pt-4">
          <Field label="Full name" htmlFor="full_name" error={profileErrors.full_name}>
            <Input
              id="full_name"
              autoComplete="name"
              value={profile.full_name}
              onChange={(event) =>
                setProfile((current) => ({ ...current, full_name: event.target.value }))
              }
              invalid={Boolean(profileErrors.full_name)}
            />
          </Field>

          <Field
            label="Mobile Money number"
            htmlFor="phone"
            error={profileErrors.phone}
            hint="Pre-filled when you add money."
          >
            <Input
              id="phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel-national"
              value={profile.phone}
              onChange={(event) =>
                setProfile((current) => ({ ...current, phone: event.target.value }))
              }
              invalid={Boolean(profileErrors.phone)}
              placeholder="024 123 4567"
              className="tabular"
            />
          </Field>

          <Field label="Email address" htmlFor="email" hint="Contact support to change this.">
            <Input id="email" value={user.email} disabled />
          </Field>

          <Button type="submit" loading={savingProfile}>
            Save changes
          </Button>
        </form>
      </Card>

      <Card>
        <CardHeader
          title="Password"
          description="Changing it signs out every other session."
        />
        <form onSubmit={changePassword} className="space-y-4 p-4 pt-4 sm:p-5 sm:pt-4">
          <Field
            label="Current password"
            htmlFor="current_password"
            error={passwordErrors.current_password}
            required
          >
            <Input
              id="current_password"
              type="password"
              autoComplete="current-password"
              required
              value={passwords.current_password}
              onChange={(event) =>
                setPasswords((current) => ({ ...current, current_password: event.target.value }))
              }
              invalid={Boolean(passwordErrors.current_password)}
            />
          </Field>

          <Field
            label="New password"
            htmlFor="new_password"
            error={passwordErrors.new_password}
            hint="At least 10 characters."
            required
          >
            <Input
              id="new_password"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              value={passwords.new_password}
              onChange={(event) =>
                setPasswords((current) => ({ ...current, new_password: event.target.value }))
              }
              invalid={Boolean(passwordErrors.new_password)}
            />
          </Field>

          <Button type="submit" loading={savingPassword} icon={<LockIcon className="h-4 w-4" />}>
            Change password
          </Button>
        </form>
      </Card>

      <Card>
        <CardHeader title="More" />
        <ul className="divide-y divide-line">
          <AccountLink
            href="/account/notifications"
            icon={<BellIcon className="h-5 w-5" />}
            label="Notifications"
            description="Payment, order and security alerts."
          />
          <AccountLink
            href="/acceptable-use"
            icon={<ShieldIcon className="h-5 w-5" />}
            label="Acceptable Use Policy"
            description={
              user.has_accepted_current_terms
                ? `Accepted version ${user.accepted_terms_version}`
                : "Action needed - please review and accept."
            }
          />
          <AccountLink
            href="/terms"
            icon={<CheckCircleIcon className="h-5 w-5" />}
            label="Terms of Service"
            description="What you agree to when using VerifyGH."
          />
        </ul>
      </Card>

      <Card className="p-4 sm:p-5">
        <Button
          variant="secondary"
          fullWidth
          onClick={() => setConfirmSignOut(true)}
          icon={<LogoutIcon className="h-5 w-5" />}
        >
          Sign out
        </Button>
      </Card>

      <ConfirmDialog
        open={confirmSignOut}
        onClose={() => setConfirmSignOut(false)}
        onConfirm={signOut}
        title="Sign out of VerifyGH?"
        description="Your wallet and orders stay exactly as they are."
        confirmLabel="Sign out"
      />
    </div>
  );
}

function AccountLink({
  href,
  icon,
  label,
  description,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  description: string;
}) {
  return (
    <li>
      <Link
        href={href}
        className="flex items-center gap-3.5 px-4 py-3.5 transition-colors hover:bg-canvas sm:px-5"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-ink">{label}</span>
          <span className="block truncate text-xs text-ink-muted">{description}</span>
        </span>
        <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden>
          <path d="M9.5 5.5l6.5 6.5-6.5 6.5" stroke="currentColor" strokeWidth="1.7"
            strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Link>
    </li>
  );
}
