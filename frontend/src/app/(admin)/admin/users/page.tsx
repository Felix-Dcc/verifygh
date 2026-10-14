"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import {
  AdminToolbar,
  KpiCard,
  KpiRow,
  ListCard,
  SearchBox,
  TableSkeleton,
  openRow,
} from "@/components/admin/ui";
import { ROLE_INFO, RoleBadge, RoleChangeForm } from "@/components/admin/team";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { AlertIcon, BoltIcon, UserIcon, UsersIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  LoadError,
  SegmentedControl,
  Select,
  Skeleton,
  Textarea,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { cedis, formatDate, localPhone, relativeTime } from "@/lib/format";
import type { AdminOverview, AdminUser, Paginated, Transaction } from "@/lib/types";

type Filter = "all" | "flagged" | "suspended" | "verified" | "unverified";

export default function AdminUsersPage() {
  const { can } = useAuth();
  const [search, setSearch] = React.useState("");
  // Opened from an abuse signal: start on that account.
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) setSearch(q.slice(0, 120));
  }, []);
  const [debounced, setDebounced] = React.useState("");
  const [filter, setFilter] = React.useState<Filter>("all");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<AdminUser | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, isLoading, isValidating, error, mutate } = useSWR<Paginated<AdminUser>>(
    [
      "/admin/users/",
      {
        search: debounced,
        flagged: filter === "flagged" ? "true" : "",
        suspended: filter === "suspended" ? "true" : "",
        verified: filter === "verified" ? "true" : filter === "unverified" ? "false" : "",
        page,
        page_size: 25,
      },
    ],
    { keepPreviousData: true },
  );
  const { data: overview } = useSWR<AdminOverview>("/admin/overview/", { refreshInterval: 60_000 });
  // Accounts still waiting on their email code - a count only.
  const { data: unverified } = useSWR<Paginated<AdminUser>>(
    ["/admin/users/", { verified: "false", page_size: 1 }],
    { refreshInterval: 60_000 },
  );

  const users = data?.results ?? [];
  const show = (value: Filter) => {
    setFilter((current) => (current === value ? "all" : value));
    setPage(1);
  };
  const FILTER_TITLES: Record<Filter, string> = {
    all: "All users",
    flagged: "Flagged users",
    suspended: "Suspended users",
    verified: "Verified users",
    unverified: "Unverified users",
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Users"
        description="Search accounts, review abuse signals, and act with a recorded reason."
      />

      <KpiRow>
        <KpiCard
          icon={<UsersIcon />}
          label="Customers"
          value={overview?.users.total}
          hint={overview ? `${overview.users.new_today} joined today` : undefined}
          onClick={() => show("all")}
          active={filter === "all"}
        />
        <KpiCard
          icon={<BoltIcon />}
          tone="info"
          label="Active in 30 days"
          value={overview?.users.active_30d}
          hint="Signed in this month"
        />
        <KpiCard
          icon={<UserIcon />}
          tone="warn"
          label="Email not verified"
          value={unverified?.pagination?.count}
          hint="Cannot buy or top up yet"
          onClick={() => show("unverified")}
          active={filter === "unverified"}
        />
        <KpiCard
          icon={<AlertIcon />}
          tone="danger"
          label="Suspended"
          value={overview?.users.suspended}
          hint="Signed out and blocked"
          onClick={() => show("suspended")}
          active={filter === "suspended"}
        />
      </KpiRow>

      <AdminToolbar>
        <SegmentedControl
          options={[
            { value: "all" as Filter, label: "All" },
            { value: "flagged" as Filter, label: "Flagged" },
            { value: "suspended" as Filter, label: "Suspended" },
            { value: "verified" as Filter, label: "Verified" },
            { value: "unverified" as Filter, label: "Unverified" },
          ]}
          value={filter}
          onChange={(value) => {
            setFilter(value);
            setPage(1);
          }}
        />
        <SearchBox
          label="Search users"
          placeholder="Email, name or phone"
          value={search}
          onChange={setSearch}
          className="lg:ml-auto"
        />
      </AdminToolbar>

      <ListCard
        title={FILTER_TITLES[filter]}
        count={data?.pagination?.count}
        noun="accounts"
        refreshing={isValidating}
        onRefresh={() => mutate()}
      >
        {isLoading ? (
          <TableSkeleton />
        ) : error && !data ? (
          <LoadError what="the users" onRetry={() => mutate()} />
        ) : users.length === 0 ? (
          <EmptyState
            icon={<UsersIcon />}
            title={debounced ? "No users match that search" : "No users to show"}
            description={debounced ? "Try a different email, name or phone number." : undefined}
            action={
              debounced || filter !== "all" ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setFilter("all");
                    setPage(1);
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <ul className="divide-y divide-line md:hidden">
              {users.map((user) => (
                <li key={user.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(user)}
                    className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-sunken/60"
                  >
                    <Avatar user={user} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">
                        {user.full_name || user.email}
                      </span>
                      <span className="block truncate text-caption text-ink-muted">{user.email}</span>
                    </span>
                    <span className="shrink-0 text-right">
                      <span className="tabular block text-sm font-semibold text-ink">
                        {cedis(user.balance)}
                      </span>
                      <UserFlags user={user} />
                    </span>
                  </button>
                </li>
              ))}
            </ul>

            <div className="hidden md:block">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line bg-sunken">
                  <tr className="text-caption text-ink-muted">
                    <th scope="col" className="px-5 py-3 font-medium">User</th>
                    <th scope="col" className="px-5 py-3 font-medium">Phone</th>
                    <th scope="col" className="px-5 py-3 text-right font-medium">Balance</th>
                    <th scope="col" className="px-5 py-3 text-right font-medium">Orders</th>
                    <th scope="col" className="px-5 py-3 font-medium">Status</th>
                    <th scope="col" className="px-5 py-3 font-medium">Joined</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {users.map((user) => (
                    <tr key={user.id} {...openRow(() => setSelected(user), `Open ${user.email}`)}>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <Avatar user={user} />
                          <div className="min-w-0">
                            <p className="truncate font-medium text-ink">
                              {user.full_name || "-"}
                            </p>
                            <p className="truncate text-caption text-ink-muted">{user.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3.5 text-ink-soft">
                        {user.phone ? localPhone(user.phone) : "-"}
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3.5 text-right font-medium text-ink">
                        {cedis(user.balance)}
                      </td>
                      <td className="tabular px-5 py-3.5 text-right text-ink-soft">
                        {user.order_count}
                      </td>
                      <td className="px-5 py-3.5">
                        <UserFlags user={user} />
                      </td>
                      <td className="whitespace-nowrap px-5 py-3.5 text-ink-muted">
                        {formatDate(user.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </ListCard>

      {data?.pagination && data.pagination.pages > 1 ? (
        <Pagination
          page={data.pagination.page}
          pages={data.pagination.pages}
          count={data.pagination.count}
          hasNext={data.pagination.has_next}
          hasPrevious={data.pagination.has_previous}
          onChange={setPage}
        />
      ) : null}

      <UserDetailDialog
        user={selected}
        onClose={() => setSelected(null)}
        onChanged={() => mutate()}
        canSuspend={can("USER_SUSPEND")}
        canChangeEmail={can("USER_EMAIL_CHANGE")}
        canAdjust={can("WALLET_ADJUST")}
        canViewWallet={can("WALLET_VIEW")}
        canChangeRole={can("USER_ROLE_CHANGE")}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Avatar({ user }: { user: AdminUser }) {
  return (
    <span
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-caption font-semibold",
        user.is_suspended ? "bg-danger-50 text-danger-700" : "bg-brand-100 text-brand-700",
      )}
    >
      {(user.full_name || user.email).slice(0, 1).toUpperCase()}
    </span>
  );
}

function UserFlags({ user }: { user: AdminUser }) {
  return (
    <span className="flex flex-wrap items-center justify-end gap-1">
      {user.is_suspended ? <Badge tone="danger">Suspended</Badge> : null}
      {user.open_flags > 0 ? <Badge tone="warn">{user.open_flags} flags</Badge> : null}
      {!user.is_email_verified ? <Badge tone="neutral">Unverified</Badge> : null}
      {user.invite_pending ? <Badge tone="warn">Invite pending</Badge> : null}
      {user.role !== "USER" ? <RoleBadge role={user.role} /> : null}
      {user.is_suspended || user.open_flags || !user.is_email_verified || user.role !== "USER" ? null : (
        <Badge tone="success" dot>
          Active
        </Badge>
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ */

function UserDetailDialog({
  user,
  onClose,
  onChanged,
  canSuspend,
  canChangeEmail,
  canAdjust,
  canViewWallet,
  canChangeRole,
}: {
  user: AdminUser | null;
  onClose: () => void;
  onChanged: () => void;
  canSuspend: boolean;
  canChangeEmail: boolean;
  canAdjust: boolean;
  canViewWallet: boolean;
  canChangeRole: boolean;
}) {
  const toast = useToast();
  const { user: me } = useAuth();
  const [tab, setTab] = React.useState<"details" | "suspend" | "adjust" | "email" | "email-confirm" | "role">(
    "details",
  );
  const [reason, setReason] = React.useState("");
  const [newEmail, setNewEmail] = React.useState("");
  const [confirmEmail, setConfirmEmail] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [amount, setAmount] = React.useState("");
  const [direction, setDirection] = React.useState<"CREDIT" | "DEBIT">("CREDIT");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const { data: transactions } = useSWR<Transaction[]>(
    user && canViewWallet ? `/admin/users/${user.id}/transactions/` : null,
  );

  React.useEffect(() => {
    setTab("details");
    setReason("");
    setAmount("");
    setError("");
    setNewEmail("");
    setConfirmEmail("");
    setFieldErrors({});
  }, [user?.id]);

  // One key per distinct adjustment: a double-click or a retry after a network
  // error resends the same key and cannot move the money twice. Editing the
  // form makes it a different adjustment, so it gets a new key.
  const adjustmentKey = React.useRef(newIdempotencyKey());
  React.useEffect(() => {
    adjustmentKey.current = newIdempotencyKey();
  }, [user?.id, amount, direction, reason]);

  if (!user) return null;

  async function run(action: () => Promise<unknown>, successMessage: string) {
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await action();
      toast.success(successMessage);
      onChanged();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
      const fields = caught instanceof ApiError ? caught.fieldErrors : {};
      setFieldErrors(fields);
      if (tab === "email-confirm" && Object.keys(fields).length) setTab("email");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={Boolean(user)}
      onClose={onClose}
      title={user.full_name || user.email}
      description={user.email}
      dismissible={!busy}
    >
      <div className="space-y-4">
        {error ? (
          <Alert tone="danger" title="Could not complete that">
            {error}
          </Alert>
        ) : null}

        {tab === "details" ? (
          <>
            <dl className="divide-y divide-line rounded-xl border border-line">
              <Detail label="Balance" value={cedis(user.balance)} />
              <Detail label="Orders" value={String(user.order_count)} />
              <Detail label="Phone" value={user.phone ? localPhone(user.phone) : "Not set"} />
              <Detail label="Role" value={ROLE_INFO[user.role]?.label ?? user.role} />
              <div className="flex items-center justify-between gap-4 px-3.5 py-2.5">
                <dt className="text-sm text-ink-muted">Email</dt>
                <dd className="flex min-w-0 items-center gap-2 text-sm text-ink">
                  <span className="truncate">{user.email}</span>
                  {user.is_email_verified ? (
                    <Badge tone="success">Verified</Badge>
                  ) : (
                    <Badge tone="warn">Not verified</Badge>
                  )}
                </dd>
              </div>
              <Detail label="Risk score" value={String(user.risk_score)} />
              <Detail label="Open flags" value={String(user.open_flags)} />
              <Detail
                label="Last sign-in"
                value={user.last_login ? relativeTime(user.last_login) : "Never"}
              />
              <Detail label="Joined" value={formatDate(user.created_at)} />
            </dl>

            {user.is_suspended ? (
              <Alert tone="danger" title="This account is suspended">
                {user.suspension_reason}
              </Alert>
            ) : null}

            {canViewWallet && transactions && transactions.length > 0 ? (
              <div>
                <p className="mb-2 text-sm font-semibold text-ink">Recent transactions</p>
                <ul className="divide-y divide-line rounded-xl border border-line">
                  {transactions.slice(0, 5).map((entry) => (
                    <li key={entry.id} className="flex items-center gap-3 px-3.5 py-2.5 text-sm">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-ink">{entry.description}</span>
                        <span className="tabular block text-caption text-ink-muted">
                          {entry.reference}
                        </span>
                      </span>
                      <span
                        className={cn(
                          "tabular shrink-0 font-medium",
                          entry.direction === "CREDIT" ? "text-success-700" : "text-ink",
                        )}
                      >
                        {entry.direction === "CREDIT" ? "+" : "−"}
                        {cedis(entry.amount)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="flex flex-col gap-2 sm:flex-row">
              {canSuspend ? (
                <Button
                  variant={user.is_suspended ? "secondary" : "danger"}
                  fullWidth
                  onClick={() => setTab("suspend")}
                >
                  {user.is_suspended ? "Unsuspend account" : "Suspend account"}
                </Button>
              ) : null}
              {canAdjust ? (
                <Button variant="secondary" fullWidth onClick={() => setTab("adjust")}>
                  Adjust balance
                </Button>
              ) : null}
              {canChangeEmail && !user.is_email_verified ? (
                <Button variant="secondary" fullWidth onClick={() => setTab("email")}>
                  Change email
                </Button>
              ) : null}
              {/* Staff, or former staff being re-added. Customers are never
                  promoted - new staff are invited. */}
              {canChangeRole && (user.role !== "USER" || user.former_staff) && user.id !== me?.id ? (
                <Button variant="secondary" fullWidth onClick={() => setTab("role")}>
                  {user.role === "USER" ? "Re-add to team" : "Change role"}
                </Button>
              ) : null}
            </div>

            {canChangeEmail && user.is_email_verified ? (
              <p className="text-caption text-ink-muted">{EMAIL_LOCKED}</p>
            ) : null}

            {!canSuspend && !canAdjust && !canChangeEmail ? (
              <p className="text-caption text-ink-muted">
                Your role can view this account but not change it.
              </p>
            ) : null}
          </>
        ) : null}

        {tab === "suspend" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              run(
                () =>
                  api.post(
                    `/admin/users/${user.id}/${user.is_suspended ? "unsuspend" : "suspend"}/`,
                    { reason },
                  ),
                user.is_suspended ? "Account unsuspended" : "Account suspended",
              );
            }}
            className="space-y-4"
          >
            <Alert tone={user.is_suspended ? "info" : "warn"} title="This is recorded">
              {user.is_suspended
                ? "The user will be able to sign in and buy again."
                : "The user will be signed out and blocked from buying. They are told their account is suspended."}{" "}
              Your name, the time and this reason are written to the audit log permanently.
            </Alert>

            <Field label="Reason" htmlFor="reason" required hint="At least 5 characters.">
              <Textarea
                id="reason"
                rows={3}
                required
                minLength={5}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. Chargeback fraud reported by the payment provider on 14 Sept"
              />
            </Field>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="secondary" onClick={() => setTab("details")} disabled={busy}>
                Back
              </Button>
              <Button
                type="submit"
                variant={user.is_suspended ? "primary" : "danger"}
                loading={busy}
                disabled={reason.trim().length < 5}
              >
                {user.is_suspended ? "Unsuspend" : "Suspend"}
              </Button>
            </div>
          </form>
        ) : null}

        {tab === "email" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const problems = emailProblems(user.email, newEmail, confirmEmail);
              setFieldErrors(problems);
              setError("");
              if (Object.keys(problems).length === 0) setTab("email-confirm");
            }}
            className="space-y-4"
            noValidate
          >
            <Alert tone="warn" title="Unverified emails only">
              {EMAIL_WARNING}
            </Alert>

            <Field label="Current email" htmlFor="current-email">
              <Input id="current-email" value={user.email} readOnly disabled />
            </Field>
            <Field label="New email" htmlFor="new-email" required error={fieldErrors.new_email}>
              <Input
                id="new-email"
                type="email"
                inputMode="email"
                autoComplete="off"
                autoCapitalize="none"
                value={newEmail}
                onChange={(event) => setNewEmail(event.target.value)}
                placeholder="name@example.com"
              />
            </Field>
            <Field
              label="Confirm new email"
              htmlFor="confirm-email"
              required
              error={fieldErrors.confirm_email}
            >
              <Input
                id="confirm-email"
                type="email"
                inputMode="email"
                autoComplete="off"
                autoCapitalize="none"
                value={confirmEmail}
                onChange={(event) => setConfirmEmail(event.target.value)}
              />
            </Field>
            <Field
              label="Reason"
              htmlFor="email-reason"
              required
              hint="At least 5 characters. Recorded in the audit log."
              error={fieldErrors.reason}
            >
              <Textarea
                id="email-reason"
                rows={2}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. User wrote to support: typo in their email at signup"
              />
            </Field>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="secondary" onClick={() => setTab("details")} disabled={busy}>
                Back
              </Button>
              <Button type="submit" disabled={reason.trim().length < 5}>
                Review change
              </Button>
            </div>
          </form>
        ) : null}

        {tab === "email-confirm" ? (
          <div className="space-y-4">
            <Alert tone="warn" title="Change this email?">
              {EMAIL_WARNING} Any links already sent to the old address stop working, and the
              user is signed out and signs in again with the new email.
            </Alert>
            <dl className="divide-y divide-line rounded-xl border border-line">
              <Detail label="From" value={user.email} />
              <Detail label="To" value={normaliseEmail(newEmail)} />
            </dl>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="secondary" onClick={() => setTab("email")} disabled={busy}>
                Back
              </Button>
              <Button
                loading={busy}
                onClick={() =>
                  run(
                    () =>
                      api.post(`/admin/users/${user.id}/change-email/`, {
                        new_email: newEmail,
                        confirm_email: confirmEmail,
                        reason,
                      }),
                    "Email updated successfully. A new verification email has been sent to the new address.",
                  )
                }
              >
                Change email
              </Button>
            </div>
          </div>
        ) : null}

        {tab === "role" ? (
          <RoleChangeForm
            user={user}
            onCancel={() => setTab("details")}
            onDone={() => {
              onChanged();
              onClose();
            }}
          />
        ) : null}

        {tab === "adjust" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              run(
                () =>
                  api.post(
                    `/admin/users/${user.id}/wallet-adjustment/`,
                    { amount, direction, reason },
                    { idempotencyKey: adjustmentKey.current },
                  ),
                "Balance adjusted",
              );
            }}
            className="space-y-4"
          >
            <Alert tone="warn" title="This moves real money">
              An adjustment writes an immutable ledger entry against this wallet. It cannot be
              edited or deleted afterwards - only offset by another adjustment.
            </Alert>

            <Field label="Direction" htmlFor="direction" required>
              <Select
                id="direction"
                value={direction}
                onChange={(event) => setDirection(event.target.value as "CREDIT" | "DEBIT")}
              >
                <option value="CREDIT">Credit - add to their balance</option>
                <option value="DEBIT">Debit - take from their balance</option>
              </Select>
            </Field>

            <Field
              label="Amount"
              htmlFor="amount"
              required
              hint={`Current balance: ${cedis(user.balance)}`}
            >
              <Input
                id="amount"
                inputMode="decimal"
                required
                prefix="GH₵"
                value={amount}
                onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ""))}
                className="tabular"
                placeholder="0.00"
              />
            </Field>

            <Field label="Reason" htmlFor="adjust-reason" required hint="At least 5 characters.">
              <Textarea
                id="adjust-reason"
                rows={3}
                required
                minLength={5}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. Goodwill credit for the provider outage on 14 Sept, ticket #482"
              />
            </Field>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="secondary" onClick={() => setTab("details")} disabled={busy}>
                Back
              </Button>
              <Button
                type="submit"
                loading={busy}
                disabled={reason.trim().length < 5 || !amount || Number.parseFloat(amount) <= 0}
              >
                {direction === "CREDIT" ? "Credit" : "Debit"} {cedis(amount || "0")}
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </Dialog>
  );
}

const EMAIL_WARNING =
  "Only change this email if the user entered an incorrect email during registration. " +
  "The new email will remain unverified until the user verifies it.";

const EMAIL_LOCKED =
  "This email has already been verified. Email changes are restricted to unverified accounts.";

function normaliseEmail(value: string): string {
  return value.trim().toLowerCase();
}

/** The same checks the server makes, so mistakes show before the confirm step. */
function emailProblems(current: string, next: string, confirm: string): Record<string, string> {
  const problems: Record<string, string> = {};
  const value = normaliseEmail(next);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) problems.new_email = "Enter a valid email address.";
  else if (value === normaliseEmail(current)) problems.new_email = "This is already their email.";
  if (!problems.new_email && normaliseEmail(confirm) !== value) {
    problems.confirm_email = "The two emails do not match.";
  }
  return problems;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 px-3.5 py-2.5">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="tabular text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

function RowSkeletons() {
  return (
    <ul className="divide-y divide-line">
      {Array.from({ length: 8 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
          <Skeleton className="h-9 w-9 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-28" />
          </div>
          <Skeleton className="h-4 w-16" />
        </li>
      ))}
    </ul>
  );
}
