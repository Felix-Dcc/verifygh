"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/app-shell";
import { errorMessage, useAuth } from "@/components/auth-provider";
import {
  BellIcon,
  CheckCircleIcon,
  ChevronRightIcon,
  LockIcon,
  LogoutIcon,
  ShieldIcon,
} from "@/components/icons";
import { ThemeSwitcher } from "@/components/theme";
import { ConfirmDialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  Field,
  Input,
  PasswordInput,
  cn,
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
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Settings" description="Your details, security and preferences." />

      {!user.is_email_verified ? (
        <Alert
          tone="warn"
          title="Confirm your email address"
          className="mb-6"
          action={
            <Button size="sm" variant="secondary" loading={resending} onClick={resendVerification}>
              Resend
            </Button>
          }
        >
          Purchases stay locked until you confirm {user.email}.
        </Alert>
      ) : null}

      <div className="divide-y divide-line">
        <SettingsSection title="Profile" description="Used on receipts and by support.">
          <div className="flex items-center gap-4 border-b border-line p-5 sm:p-6">
            <span
              aria-hidden
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-100 text-heading text-brand-700"
            >
              {(user.full_name || user.email).slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-ink">{user.full_name || "Your account"}</p>
              <p className="truncate text-caption text-ink-muted">{user.email}</p>
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

          <form onSubmit={saveProfile} className="space-y-4 p-5 sm:p-6">
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
              hint="Filled in for you when you add funds."
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

            <div className="flex justify-end">
              <Button type="submit" loading={savingProfile}>
                Save changes
              </Button>
            </div>
          </form>
        </SettingsSection>

        <SettingsSection
          title="Security"
          description="Changing your password signs out every other session."
        >
          <form onSubmit={changePassword} className="space-y-4 p-5 sm:p-6">
            <Field
              label="Current password"
              htmlFor="current_password"
              error={passwordErrors.current_password}
              required
            >
              <PasswordInput
                id="current_password"
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
              <PasswordInput
                id="new_password"
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

            <div className="flex justify-end">
              <Button type="submit" loading={savingPassword} icon={<LockIcon className="h-4 w-4" />}>
                Change password
              </Button>
            </div>
          </form>
        </SettingsSection>

        <SettingsSection
          title="Appearance"
          description="Light, dark, or match your device. Saved on this device."
        >
          <div className="p-5 sm:p-6">
            <ThemeSwitcher />
          </div>
        </SettingsSection>

        <SettingsSection title="Notifications and policies">
          <ul className="divide-y divide-line">
            <AccountLink
              href="/account/notifications"
              icon={<BellIcon className="h-4 w-4" />}
              label="Notifications"
              description="Payment, order and security alerts."
            />
            <AccountLink
              href="/acceptable-use"
              icon={<ShieldIcon className="h-4 w-4" />}
              label="Acceptable Use Policy"
              description={
                user.has_accepted_current_terms
                  ? `Accepted version ${user.accepted_terms_version}`
                  : "Action needed - please review and accept."
              }
              attention={!user.has_accepted_current_terms}
            />
            <AccountLink
              href="/terms"
              icon={<CheckCircleIcon className="h-4 w-4" />}
              label="Terms of Service"
              description="What you agree to when using VerifyGH."
            />
          </ul>
        </SettingsSection>

        <SettingsSection title="Sign out" description="Your wallet and orders stay exactly as they are.">
          <div className="p-5 sm:p-6">
            <Button
              variant="secondary"
              onClick={() => setConfirmSignOut(true)}
              icon={<LogoutIcon className="h-4 w-4" />}
              className="w-full sm:w-auto"
            >
              Sign out
            </Button>
          </div>
        </SettingsSection>
      </div>

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

/** A settings group: what it is on the left, the controls on the right. */
function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 gap-4 py-8 first:pt-0 md:grid-cols-3 md:gap-8">
      <div>
        <h2 className="text-heading text-ink">{title}</h2>
        {description ? <p className="mt-1 text-sm text-ink-muted">{description}</p> : null}
      </div>
      <Card className="overflow-hidden md:col-span-2">{children}</Card>
    </section>
  );
}

function AccountLink({
  href,
  icon,
  label,
  description,
  attention = false,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  description: string;
  attention?: boolean;
}) {
  return (
    <li>
      <Link
        href={href}
        className="flex min-h-14 items-center gap-3 px-5 py-3 transition-colors hover:bg-sunken/60 sm:px-6"
      >
        <span
          aria-hidden
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sunken text-ink-soft"
        >
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-ink">{label}</span>
          <span
            className={cn(
              "block truncate text-caption",
              attention ? "font-medium text-warn-700" : "text-ink-muted",
            )}
          >
            {description}
          </span>
        </span>
        <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint" />
      </Link>
    </li>
  );
}
