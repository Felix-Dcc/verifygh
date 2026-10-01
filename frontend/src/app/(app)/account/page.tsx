"use client";

import Link from "next/link";
import * as React from "react";

import { AppHero } from "@/components/app-hero";
import { errorMessage, useAuth } from "@/components/auth-provider";
import {
  BellIcon,
  CheckCircleIcon,
  CheckIcon,
  ChevronRightIcon,
  LockIcon,
  LogoutIcon,
  MonitorIcon,
  ShieldIcon,
  UserIcon,
} from "@/components/icons";
import { ThemeSwitcher } from "@/components/theme";
import { ConfirmDialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  Field,
  Input,
  PasswordInput,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDate, localPhone } from "@/lib/format";
import type { User } from "@/lib/types";

const SECTIONS = [
  { id: "profile", label: "Profile" },
  { id: "security", label: "Security" },
  { id: "appearance", label: "Appearance" },
  { id: "notifications", label: "Notifications and policies" },
  { id: "sign-out", label: "Sign out" },
];

/**
 * The account: who you are and how set up the account is (on the navy
 * panel), then your details, security and preferences as cards - with a
 * menu beside them from lg. Every check on the panel is the account's real
 * state.
 */
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

  const [accepting, setAccepting] = React.useState(false);
  // The same one-tap acceptance Home offers when the terms change.
  async function acceptTerms() {
    setAccepting(true);
    try {
      await api.post("/auth/terms/accept/", { accepted: true });
      await refresh();
      toast.success("Terms accepted", "You can keep buying.");
    } catch (error) {
      toast.error("Could not accept the terms", errorMessage(error));
    } finally {
      setAccepting(false);
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
    <div className="mx-auto max-w-5xl space-y-8">
      <AppHero
        eyebrow="Your account"
        title={
          <span className="flex items-center gap-4">
            <Avatar user={user} />
            <span className="min-w-0 truncate">{user.full_name || "Your account"}</span>
          </span>
        }
        aside={
          <Checklist
            user={user}
            resending={resending}
            onResend={resendVerification}
            accepting={accepting}
            onAccept={acceptTerms}
          />
        }
      >
        <p className="mt-3 truncate text-sm text-white/70">{user.email}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <HeroBadge tone={user.is_email_verified ? "good" : "warn"}>
            {user.is_email_verified ? "Email confirmed" : "Email not confirmed"}
          </HeroBadge>
          {user.role !== "USER" ? <HeroBadge>{user.role}</HeroBadge> : null}
          <HeroBadge>Joined {formatDate(user.created_at)}</HeroBadge>
        </div>
      </AppHero>

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

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <nav aria-label="Settings" className="hidden lg:block">
          <ul className="sticky top-20 space-y-0.5">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="flex h-9 items-center rounded-lg px-3 text-sm font-medium text-ink-soft transition-colors hover:bg-sunken hover:text-ink"
                >
                  {section.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-6">
          <SettingsCard
            id="profile"
            icon={<UserIcon className="h-4 w-4" />}
            title="Profile"
            description="Used on receipts and by support."
          >
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
          </SettingsCard>

          <SettingsCard
            id="security"
            icon={<LockIcon className="h-4 w-4" />}
            title="Security"
            description={
              user?.has_password === false
                ? "You sign in with Google."
                : "Changing your password signs out every other session."
            }
          >
            {user?.has_password === false ? (
              // No current password to give: the reset link sets the first one,
              // and Google keeps working alongside it.
              <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                <p className="text-sm text-ink-muted">
                  This account has no password yet. Set one if you also want to sign in with your
                  email address - we will email you a link.
                </p>
                <ButtonLink
                  href="/forgot-password"
                  variant="secondary"
                  className="shrink-0"
                  icon={<LockIcon className="h-4 w-4" />}
                >
                  Set a password
                </ButtonLink>
              </div>
            ) : (
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
            )}
          </SettingsCard>

          <SettingsCard
            id="appearance"
            icon={<MonitorIcon className="h-4 w-4" />}
            title="Appearance"
            description="Light, dark, or match your device. Saved on this device."
          >
            <div className="p-5 sm:p-6">
              <ThemeSwitcher />
            </div>
          </SettingsCard>

          <SettingsCard id="notifications" icon={<BellIcon className="h-4 w-4" />} title="Notifications and policies">
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
          </SettingsCard>

          <SettingsCard
            id="sign-out"
            icon={<LogoutIcon className="h-4 w-4" />}
            title="Sign out"
            description="Your wallet and orders stay exactly as they are."
          >
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
          </SettingsCard>
        </div>
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

/* ------------------------------------------------------------------ */

function Avatar({ user }: { user: User }) {
  const parts = (user.full_name || "").trim().split(/\s+/).filter(Boolean);
  const letters =
    parts.length >= 2 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? user.email).slice(0, 2);
  return (
    <span
      aria-hidden
      className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#0B63B6] to-[#137A4E] p-[2px] shadow-[0_10px_24px_-10px_rgba(8,120,209,0.8)] sm:h-16 sm:w-16"
    >
      <span className="flex h-full w-full items-center justify-center rounded-full bg-navy text-lg font-bold uppercase tracking-wide text-white sm:text-xl">
        {letters}
      </span>
    </span>
  );
}

function HeroBadge({ tone = "plain", children }: { tone?: "plain" | "good" | "warn"; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-caption font-medium",
        tone === "good" && "border-leaf/40 bg-leaf/15 text-leaf-light",
        tone === "warn" && "border-[#FFB86B]/40 bg-[#FFB86B]/10 text-[#FFCB8F]",
        tone === "plain" && "border-white/15 bg-white/[0.06] text-white/80",
      )}
    >
      {tone !== "plain" ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

/**
 * How set up the account is: three real checks and a ring that fills as they
 * are done - email confirmed, current terms accepted, a Mobile Money number
 * saved (it fills in Add funds).
 */
function Checklist({
  user,
  resending,
  onResend,
  accepting,
  onAccept,
}: {
  user: User;
  resending: boolean;
  onResend: () => void;
  accepting: boolean;
  onAccept: () => void;
}) {
  const items = [
    {
      label: "Email confirmed",
      done: user.is_email_verified,
      todo: (
        <button type="button" onClick={onResend} disabled={resending} className="font-semibold text-aqua underline-offset-2 hover:underline disabled:opacity-60">
          {resending ? "Sending…" : "Resend link"}
        </button>
      ),
    },
    {
      label: "Current terms accepted",
      done: user.has_accepted_current_terms,
      todo: (
        <button type="button" onClick={onAccept} disabled={accepting} className="font-semibold text-aqua underline-offset-2 hover:underline disabled:opacity-60">
          {accepting ? "Accepting…" : "Accept"}
        </button>
      ),
    },
    {
      label: "Mobile Money number saved",
      done: Boolean(user.phone),
      todo: (
        <a href="#profile" className="font-semibold text-aqua underline-offset-2 hover:underline">
          Add it
        </a>
      ),
    },
  ];
  const done = items.filter((item) => item.done).length;
  const circumference = 2 * Math.PI * 22;

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4 backdrop-blur sm:p-5">
      <div className="flex items-center gap-4">
        <svg viewBox="0 0 52 52" className="h-14 w-14 shrink-0 -rotate-90" aria-hidden>
          <defs>
            <linearGradient id="setup-ring" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#28C7F7" />
              <stop offset="1" stopColor="#65D99A" />
            </linearGradient>
          </defs>
          <circle cx="26" cy="26" r="22" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="5" />
          <circle
            cx="26"
            cy="26"
            r="22"
            fill="none"
            stroke="url(#setup-ring)"
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - done / items.length)}
            className="transition-[stroke-dashoffset] duration-700 ease-out"
          />
        </svg>
        <div>
          <p className="text-sm font-semibold text-white">
            {done === items.length ? "Your account is set up" : `${done} of ${items.length} done`}
          </p>
          <p className="text-caption text-white/60">
            {done === items.length ? "Everything is in place to buy numbers." : "Finish these to buy without interruptions."}
          </p>
        </div>
      </div>
      <ul className="mt-4 space-y-2">
        {items.map((item) => (
          <li key={item.label} className="flex items-center gap-2.5 text-sm">
            <span
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                item.done ? "bg-leaf text-navy" : "border border-white/30",
              )}
            >
              {item.done ? <CheckIcon className="h-3 w-3" /> : null}
            </span>
            <span className={cn("min-w-0 flex-1", item.done ? "text-white/85" : "text-white")}>{item.label}</span>
            {item.done ? null : <span className="text-caption">{item.todo}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A group of settings as a card: an icon, what it is, then the controls. */
function SettingsCard({
  id,
  icon,
  title,
  description,
  children,
}: {
  id: string;
  icon: React.ReactNode;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24">
      <Card className="overflow-hidden rounded-2xl">
        <div className="flex items-start gap-3 border-b border-line px-5 py-4 sm:px-6">
          <span
            aria-hidden
            className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-[#0B63B6] to-[#137A4E] text-white"
          >
            {icon}
          </span>
          <div>
            <h2 id={`${id}-title`} className="text-heading text-ink">
              {title}
            </h2>
            {description ? <p className="mt-0.5 text-sm text-ink-muted">{description}</p> : null}
          </div>
        </div>
        {children}
      </Card>
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
        className="group flex min-h-14 items-center gap-3 px-5 py-3 transition-colors hover:bg-sunken/60 sm:px-6"
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
        <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </Link>
    </li>
  );
}
