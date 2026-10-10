"use client";

import * as React from "react";
import useSWR from "swr";

import { StatCard } from "@/components/admin/charts";
import { InviteStaffForm, ROLE_INFO, RoleBadge, RoleChangeForm, STAFF_ROLE_ORDER } from "@/components/admin/team";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { ClockIcon, MailIcon, PlusIcon, ShieldIcon, StarIcon, UsersIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Badge, Button, Card, EmptyState, LoadError, Skeleton, cn } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDate, relativeTime } from "@/lib/format";
import type { AdminUser, Paginated } from "@/lib/types";

/**
 * The staff team, for super admins: who has access, at what level, and the
 * one way in - an invitation. Customer accounts are never turned into staff;
 * the only exception is former staff, who can be re-added from here.
 */
export default function AdminTeamPage() {
  const { can, user: me } = useAuth();
  const toast = useToast();
  const allowed = can("USER_ROLE_CHANGE");
  const { data, error, isLoading, mutate } = useSWR<Paginated<AdminUser>>(
    allowed ? ["/admin/users/", { staff: "true", page_size: 100 }] : null,
  );
  const { data: former, mutate: mutateFormer } = useSWR<Paginated<AdminUser>>(
    allowed ? ["/admin/users/", { former_staff: "true", page_size: 100 }] : null,
  );
  const [dialog, setDialog] = React.useState<
    { kind: "invite" } | { kind: "role"; user: AdminUser } | null
  >(null);
  const [resending, setResending] = React.useState<string | null>(null);

  if (!allowed) {
    return (
      <div className="space-y-6">
        <PageHeader title="Team" />
        <Card>
          <EmptyState
            icon={<ShieldIcon />}
            title="Super admins only"
            description="Only a super admin can see and change who has access to the console."
          />
        </Card>
      </div>
    );
  }

  const members = (data?.results ?? []).slice().sort(
    (a, b) => STAFF_ROLE_ORDER.indexOf(a.role) - STAFF_ROLE_ORDER.indexOf(b.role) || a.email.localeCompare(b.email),
  );
  const count = (role: string) => members.filter((member) => member.role === role).length;
  const pending = members.filter((member) => member.invite_pending).length;

  async function resend(member: AdminUser) {
    setResending(member.id);
    try {
      await api.post(`/admin/users/${member.id}/resend-invite/`, {});
      toast.success("Invitation sent again", `A fresh link went to ${member.email}. Earlier links stop working.`);
    } catch (caught) {
      toast.error("Could not resend", caught instanceof ApiError ? caught.message : "Please try again.");
    } finally {
      setResending(null);
    }
  }

  function done() {
    setDialog(null);
    mutate();
    mutateFormer();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Team"
        description="Who can open the admin console, and what each person can do. Every change is audited and emailed to the person."
        action={
          <Button onClick={() => setDialog({ kind: "invite" })}>
            <PlusIcon className="h-4 w-4" />
            Invite admin
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Super admins" icon={<StarIcon />} value={data ? count("SUPER_ADMIN") : "–"} footnote="Full control" />
        <StatCard label="Admins" icon={<ShieldIcon />} value={data ? count("ADMIN") : "–"} footnote="Day-to-day operations" />
        <StatCard label="Support" icon={<UsersIcon />} value={data ? count("SUPPORT") : "–"} footnote="Read and resolve" />
        <StatCard label="Pending invites" icon={<MailIcon />} value={data ? pending : "–"} footnote="Not signed in yet" />
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3.5 sm:px-5">
          <h2 className="text-heading text-ink">Members</h2>
          {data ? <span className="text-caption text-ink-muted">{members.length} with access</span> : null}
        </div>
        {isLoading ? (
          <ul className="divide-y divide-line">
            {Array.from({ length: 4 }).map((_, index) => (
              <li key={index} className="flex items-center gap-3 px-5 py-4">
                <Skeleton className="h-10 w-10 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-3 w-56" />
                </div>
              </li>
            ))}
          </ul>
        ) : error && !data ? (
          <LoadError what="the team" onRetry={() => mutate()} />
        ) : members.length === 0 ? (
          <EmptyState icon={<UsersIcon />} title="No staff yet" description="Invite your first admin." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-left text-sm">
              <thead className="border-b border-line bg-sunken">
                <tr className="text-caption text-ink-muted">
                  <th scope="col" className="px-5 py-3 font-medium">Member</th>
                  <th scope="col" className="px-5 py-3 font-medium">Role</th>
                  <th scope="col" className="px-5 py-3 font-medium">Status</th>
                  <th scope="col" className="px-5 py-3 font-medium">Last sign-in</th>
                  <th scope="col" className="px-5 py-3 font-medium">Added</th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {members.map((member) => {
                  const isMe = member.id === me?.id;
                  return (
                    <tr key={member.id}>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <span
                            className={cn(
                              "flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-caption font-semibold",
                              member.role === "SUPER_ADMIN"
                                ? "bg-gold-100 text-gold-700"
                                : member.role === "ADMIN"
                                  ? "bg-brand-100 text-brand-700"
                                  : "bg-info-50 text-info-700",
                            )}
                          >
                            {(member.full_name || member.email).slice(0, 1).toUpperCase()}
                          </span>
                          <div className="min-w-0">
                            <p className="truncate font-medium text-ink">
                              {member.full_name || "-"}
                              {isMe ? <span className="ml-2 text-caption font-normal text-ink-faint">(you)</span> : null}
                            </p>
                            <p className="truncate text-caption text-ink-muted">{member.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-3.5">
                        <RoleBadge role={member.role} />
                      </td>
                      <td className="px-5 py-3.5">
                        {member.is_suspended ? (
                          <Badge tone="danger">Suspended</Badge>
                        ) : member.invite_pending ? (
                          <Badge tone="warn">
                            <ClockIcon className="h-3 w-3" />
                            Invite pending
                          </Badge>
                        ) : (
                          <Badge tone="success" dot>
                            Active
                          </Badge>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                        {member.last_login ? relativeTime(member.last_login) : "Never"}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">{formatDate(member.created_at)}</td>
                      <td className="whitespace-nowrap px-5 py-3.5 text-right">
                        <div className="flex justify-end gap-2">
                          {member.invite_pending ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              loading={resending === member.id}
                              onClick={() => resend(member)}
                            >
                              Resend invite
                            </Button>
                          ) : null}
                          {isMe ? null : (
                            <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "role", user: member })}>
                              Change role
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {former && former.results.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="border-b border-line px-4 py-3.5 sm:px-5">
            <h2 className="text-heading text-ink">Former staff</h2>
            <p className="mt-0.5 text-sm text-ink-muted">
              Their staff access was removed. They can be re-added - no other customer account can.
            </p>
          </div>
          <ul className="divide-y divide-line">
            {former.results.map((person) => (
              <li key={person.id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sunken text-caption font-semibold text-ink-muted">
                  {(person.full_name || person.email).slice(0, 1).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{person.full_name || "-"}</span>
                  <span className="block truncate text-caption text-ink-muted">{person.email}</span>
                </span>
                {person.is_suspended ? <Badge tone="danger">Suspended</Badge> : null}
                <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "role", user: person })}>
                  Re-add
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card className="p-4 sm:p-5">
        <h2 className="text-heading text-ink">What each role can do</h2>
        <ul className="mt-4 grid gap-3 md:grid-cols-3">
          {STAFF_ROLE_ORDER.map((role) => (
            <li key={role} className="rounded-xl border border-line p-4">
              <RoleBadge role={role} />
              <p className="mt-2 text-sm text-ink-soft">{ROLE_INFO[role].summary}</p>
            </li>
          ))}
        </ul>
        <Alert tone="info" className="mt-4" title="Safety rules">
          New staff join only by invitation - customer accounts can&apos;t be given staff access, except former
          staff, who can be re-added. Nobody can change
          their own role, the last super admin can&apos;t be removed, and removing access signs the person out
          everywhere at once.
        </Alert>
      </Card>

      <Dialog
        open={dialog?.kind === "invite"}
        onClose={() => setDialog(null)}
        title="Invite to the team"
        description="They get an email to choose their own password, then sign in to the console."
      >
        {dialog?.kind === "invite" ? <InviteStaffForm onDone={done} onCancel={() => setDialog(null)} /> : null}
      </Dialog>

      <Dialog
        open={dialog?.kind === "role"}
        onClose={() => setDialog(null)}
        title={dialog?.kind === "role" ? `Role for ${dialog.user.full_name || dialog.user.email}` : "Change role"}
        description={dialog?.kind === "role" ? dialog.user.email : undefined}
      >
        {dialog?.kind === "role" ? (
          <RoleChangeForm user={dialog.user} onDone={done} onCancel={() => setDialog(null)} />
        ) : null}
      </Dialog>
    </div>
  );
}
