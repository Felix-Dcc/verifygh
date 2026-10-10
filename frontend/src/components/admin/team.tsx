"use client";

import * as React from "react";

import { Alert, Badge, Button, Field, Input, Textarea, cn } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import type { AdminUser, Role } from "@/lib/types";

/**
 * Staff roles: what each one can do, and the two forms a super admin uses -
 * invite someone new, or change a staff member's role (or remove their
 * access). Staff join only by invitation; customers are never promoted.
 *
 * The server decides everything (accounts/staff.py): only super admins may
 * act, customer accounts never become staff, nobody changes their own role,
 * the last super admin stays one, and a demotion signs the person out. These forms explain the rules; they do not enforce them.
 */

export const ROLE_INFO: Record<Role, { label: string; summary: string; tone: "neutral" | "info" | "brand" | "gold" }> = {
  USER: {
    label: "Customer",
    summary: "No staff access. Uses VerifyGH like any customer.",
    tone: "neutral",
  },
  SUPPORT: {
    label: "Support",
    summary: "Reads users, orders and payments, and handles number issues. Cannot move money or change pricing.",
    tone: "info",
  },
  ADMIN: {
    label: "Admin",
    summary: "Runs the business day to day: refunds, wallet adjustments, suspensions, catalogue and providers.",
    tone: "brand",
  },
  SUPER_ADMIN: {
    label: "Super admin",
    summary: "Everything, including pricing, exchange rates and the team itself.",
    tone: "gold",
  },
};

export const STAFF_ROLE_ORDER: Role[] = ["SUPER_ADMIN", "ADMIN", "SUPPORT"];

export function RoleBadge({ role, className }: { role: Role; className?: string }) {
  const info = ROLE_INFO[role] ?? ROLE_INFO.USER;
  return (
    <Badge tone={info.tone} className={className}>
      {info.label}
    </Badge>
  );
}

function RoleOptions({ roles, value, onChange }: { roles: Role[]; value: Role; onChange: (role: Role) => void }) {
  return (
    <div role="radiogroup" aria-label="Role" className="grid gap-2">
      {roles.map((role) => {
        const info = ROLE_INFO[role];
        const selected = value === role;
        return (
          <button
            key={role}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={info.label}
            onClick={() => onChange(role)}
            className={cn(
              "flex items-start gap-3 rounded-xl border px-3.5 py-3 text-left transition-colors",
              selected ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-line hover:bg-sunken/60",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                selected ? "border-brand-600" : "border-line-strong",
              )}
            >
              {selected ? <span className="h-2 w-2 rounded-full bg-brand-600" /> : null}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-ink">{info.label}</span>
              <span className="mt-0.5 block text-caption text-ink-muted">{info.summary}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** Invite a new staff member. They choose their own password from the email. */
export function InviteStaffForm({ onDone, onCancel }: { onDone: (user: AdminUser) => void; onCancel: () => void }) {
  const toast = useToast();
  const [fullName, setFullName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<Role>("ADMIN");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      const created = await api.post<AdminUser & { invite_sent: boolean }>("/admin/users/invite/", {
        email: email.trim(),
        full_name: fullName.trim(),
        role,
        reason: reason.trim(),
      });
      if (created.invite_sent) {
        toast.success("Invitation sent", `${created.email} can now choose a password and sign in.`);
      } else {
        toast.error(
          "Account created, email not sent",
          "The email provider didn't accept it. Use Resend invite on the team list.",
        );
      }
      onDone(created);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFieldErrors(caught.fieldErrors);
        setError(Object.keys(caught.fieldErrors).length ? "" : caught.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name" htmlFor="invite-name" required error={fieldErrors.full_name}>
          <Input
            id="invite-name"
            autoComplete="off"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder="Esi Boateng"
            invalid={Boolean(fieldErrors.full_name)}
          />
        </Field>
        <Field label="Email" htmlFor="invite-email" required error={fieldErrors.email}>
          <Input
            id="invite-email"
            type="email"
            inputMode="email"
            autoComplete="off"
            autoCapitalize="none"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@example.com"
            invalid={Boolean(fieldErrors.email)}
          />
        </Field>
      </div>
      <div>
        <p className="mb-2 text-label text-ink">Role</p>
        <RoleOptions roles={STAFF_ROLE_ORDER} value={role} onChange={setRole} />
        {fieldErrors.role ? <p className="mt-1.5 text-caption text-danger-700">{fieldErrors.role}</p> : null}
      </div>
      {role === "SUPER_ADMIN" ? (
        <Alert tone="warn" title="Full control">
          A super admin can change pricing, move money and add or remove other admins - including you.
        </Alert>
      ) : null}
      <Field
        label="Reason"
        htmlFor="invite-reason"
        required
        hint="At least 5 characters. Recorded in the audit log."
        error={fieldErrors.reason}
      >
        <Textarea
          id="invite-reason"
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="e.g. Joining as weekend operations lead"
        />
      </Field>
      <p className="text-caption text-ink-muted">
        We email them a one-time link, valid for 72 hours, to choose their own password. Nobody else ever sees or
        sets it.
      </p>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button
          type="submit"
          loading={busy}
          disabled={fullName.trim().length < 2 || !email.trim() || reason.trim().length < 5}
        >
          Send invitation
        </Button>
      </div>
    </form>
  );
}

/** Change a staff member's role, or remove their access. */
export function RoleChangeForm({
  user,
  onDone,
  onCancel,
}: {
  user: AdminUser;
  onDone: (user: AdminUser) => void;
  onCancel: () => void;
}) {
  const toast = useToast();
  const choices: Role[] = [...STAFF_ROLE_ORDER, "USER"];
  const [role, setRole] = React.useState<Role>(user.role);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const rank: Record<Role, number> = { USER: 0, SUPPORT: 1, ADMIN: 2, SUPER_ADMIN: 3 };
  const demotion = rank[role] < rank[user.role];
  const unchanged = role === user.role;
  // Email verification is left to the server: re-adding someone who never
  // accepted their invitation sends them a fresh one instead.
  const blocked = role !== "USER" && (user.is_suspended || !user.is_active);
  const readding = user.role === "USER";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const updated = await api.post<AdminUser>(`/admin/users/${user.id}/role/`, { role, reason: reason.trim() });
      toast.success(
        role === "USER" ? "Staff access removed" : `Now ${ROLE_INFO[role].label}`,
        `${user.email} has been told by email.`,
      );
      onDone(updated);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <div className="flex items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-2.5 text-sm">
        <span className="text-ink-muted">Current role</span>
        <RoleBadge role={user.role} />
      </div>
      <RoleOptions roles={choices} value={role} onChange={setRole} />
      {blocked ? (
        <Alert tone="warn" title="Not eligible yet">
          A suspended or inactive account can&apos;t be given a staff role.
        </Alert>
      ) : demotion ? (
        <Alert tone="warn" title="They'll be signed out">
          {role === "USER"
            ? "Their staff access ends now and every session is signed out. Their customer account and wallet stay."
            : `Their access drops to ${ROLE_INFO[role].label} and every session is signed out now.`}
        </Alert>
      ) : readding && !unchanged ? (
        <Alert tone="info" title="Re-adding former staff">
          {user.has_password === false
            ? "They never set up their account, so we'll email them a fresh invitation."
            : `They'll be told by email and can sign in to the console straight away as ${ROLE_INFO[role].label}.`}
        </Alert>
      ) : role === "SUPER_ADMIN" && !unchanged ? (
        <Alert tone="warn" title="Full control">
          A super admin can change pricing, move money and add or remove other admins - including you.
        </Alert>
      ) : null}
      <Field label="Reason" htmlFor="role-reason" required hint="At least 5 characters. Recorded in the audit log.">
        <Textarea
          id="role-reason"
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder={demotion ? "e.g. Left the company on 10 Oct" : "e.g. Joining the support rota"}
        />
      </Field>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Back
        </Button>
        <Button
          type="submit"
          variant={demotion ? "danger" : "primary"}
          loading={busy}
          disabled={unchanged || blocked || reason.trim().length < 5}
        >
          {unchanged
            ? "Choose a new role"
            : role === "USER"
              ? "Remove staff access"
              : readding
                ? `Re-add as ${ROLE_INFO[role].label}`
                : `Make ${ROLE_INFO[role].label}`}
        </Button>
      </div>
    </form>
  );
}
