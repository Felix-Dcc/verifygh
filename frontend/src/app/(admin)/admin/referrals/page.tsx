"use client";

import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

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
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import {
  AlertIcon,
  CheckCircleIcon,
  GiftIcon,
  ReceiptIcon,
  UsersIcon,
  WalletIcon,
} from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  LoadError,
  SegmentedControl,
  Skeleton,
  StatusBadge,
  Textarea,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, formatDateTime } from "@/lib/format";
import type { AdminReferral, Paginated, ReferralAnalytics } from "@/lib/types";

const STATUS_FILTERS = [
  { value: "ALL", label: "All" },
  { value: "PENDING", label: "Pending" },
  { value: "ELIGIBLE", label: "Eligible" },
  { value: "REWARDED", label: "Rewarded" },
  { value: "REJECTED", label: "Rejected" },
  { value: "FRAUD_FLAGGED", label: "Flagged" },
];

export default function AdminReferralsPage() {
  const [status, setStatus] = React.useState("ALL");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<AdminReferral | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const key = ["/admin/referrals/", { status, search: debounced, page, page_size: 25 }] as const;
  const { data, isLoading, isValidating, error, mutate } = useSWR<Paginated<AdminReferral>>(key, {
    keepPreviousData: true,
  });
  const { data: analytics, mutate: refreshAnalytics } =
    useSWR<ReferralAnalytics>("/admin/referrals-analytics/");

  const referrals = data?.results ?? [];

  function refresh() {
    void mutate();
    void refreshAnalytics();
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Referrals"
        description="Every invitation, what it cost, and why anything was held."
      />

      <ProgrammeSwitch />

      <KpiRow>
        <KpiCard
          icon={<UsersIcon />}
          label="Sign-ups via links"
          value={analytics?.registrations}
          hint={analytics ? `${analytics.pending} not qualified yet` : undefined}
          onClick={() => {
            setStatus("ALL");
            setPage(1);
          }}
          active={status === "ALL"}
        />
        <KpiCard
          icon={<CheckCircleIcon />}
          label="Welcomed"
          value={analytics?.rewarded}
          hint={analytics ? `${analytics.conversion_rate}% of sign-ups` : undefined}
          onClick={() => {
            setStatus("REWARDED");
            setPage(1);
          }}
          active={status === "REWARDED"}
        />
        <KpiCard
          icon={<AlertIcon />}
          tone="warn"
          label="Held for review"
          value={analytics?.fraud_flagged}
          hint="Approve or reject each one"
          onClick={() => {
            setStatus("FRAUD_FLAGGED");
            setPage(1);
          }}
          active={status === "FRAUD_FLAGGED"}
        />
        <KpiCard
          icon={<GiftIcon />}
          tone="gold"
          label="Bonus cost"
          value={analytics ? cedis(analytics.total_bonus_cost) : undefined}
          hint={
            analytics
              ? `Friends ${cedis(analytics.promotional_credit_issued)}, inviters ${cedis(analytics.referrer_credit_issued)}`
              : undefined
          }
        />
      </KpiRow>

      {/* What invited people went on to do - the proof the programme pays. */}
      <KpiRow>
        <KpiCard
          icon={<WalletIcon />}
          tone="info"
          label="Topped up"
          value={analytics?.invited_topped_up}
          hint={analytics ? `${analytics.invited_topped_up_rate}% of invited` : undefined}
        />
        <KpiCard
          icon={<ReceiptIcon />}
          tone="info"
          label="Bought a number"
          value={analytics?.invited_buyers}
          hint={
            analytics
              ? `${analytics.invited_repeat_buyers} came back for more (${analytics.invited_repeat_rate}%)`
              : undefined
          }
        />
        <KpiCard
          icon={<WalletIcon />}
          label="Cash paid by invited"
          value={analytics ? cedis(analytics.invited_cash_revenue) : undefined}
          hint={analytics ? `${analytics.invited_orders} delivered numbers` : undefined}
        />
        <KpiCard
          icon={<CheckCircleIcon />}
          tone="neutral"
          label="Verified email"
          value={analytics ? `${analytics.invited_verified_rate}%` : undefined}
          hint={analytics ? `${analytics.invited_verified} of ${analytics.registrations}` : undefined}
        />
      </KpiRow>

      {analytics && analytics.fraud_flagged > 0 ? (
        <Alert tone="warn" title={`${analytics.fraud_flagged} referrals need review`}>
          These are held, not rejected. Open one to see which check caught it.
        </Alert>
      ) : null}

      <AdminToolbar>
        <SegmentedControl
          options={STATUS_FILTERS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          className="lg:flex-1"
        />
        <SearchBox label="Search referrals" placeholder="Code or email address" value={search} onChange={setSearch} />
      </AdminToolbar>

      <ListCard
        title={status === "ALL" ? "All referrals" : `${STATUS_FILTERS.find((item) => item.value === status)?.label} referrals`}
        count={data?.pagination?.count}
        noun="referrals"
        refreshing={isValidating}
        onRefresh={refresh}
      >
        {isLoading ? (
          <TableSkeleton rows={4} />
        ) : error && !data ? (
          <LoadError what="the referrals" onRetry={() => mutate()} />
        ) : referrals.length === 0 ? (
          <EmptyState
            icon={<GiftIcon />}
            title="No referrals here"
            description="Nothing matches this filter yet."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line bg-sunken text-caption text-ink-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">Code</th>
                  <th className="px-4 py-3 font-medium">Referrer</th>
                  <th className="px-4 py-3 font-medium">Invited</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Reward</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {referrals.map((referral) => (
                  <tr key={referral.id} {...openRow(() => setSelected(referral), `Open referral ${referral.code}`)}>
                    <td className="tabular px-4 py-3 font-medium text-ink">{referral.code}</td>
                    <td className="px-4 py-3 text-ink-muted">{referral.referrer_email}</td>
                    <td className="px-4 py-3 text-ink-muted">{referral.referred_email}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <StatusBadge status={referral.status} />
                        {referral.risk_flags.length > 0 ? (
                          <span className="rounded-md bg-gold-100 px-1.5 py-0.5 text-2xs font-semibold text-gold-700">
                            {referral.risk_flags.length}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="tabular px-4 py-3 text-ink-muted">
                      {referral.reward ? cedis(referral.reward.amount) : "-"}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {formatDateTime(referral.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>

      {data?.pagination ? (
        <Pagination
          page={data.pagination.page}
          pages={data.pagination.pages}
          count={data.pagination.count}
          hasNext={data.pagination.has_next}
          hasPrevious={data.pagination.has_previous}
          onChange={setPage}
          noun="referrals"
        />
      ) : null}

      <ReferralDialog
        referral={selected}
        onClose={() => setSelected(null)}
        onChanged={refresh}
      />
    </div>
  );
}

const ACTIONS = [
  { key: "approve", label: "Approve and pay", tone: "primary" as const },
  { key: "reject", label: "Reject", tone: "danger" as const },
  { key: "flag", label: "Flag for review", tone: "secondary" as const },
  { key: "reverse-reward", label: "Reverse reward", tone: "danger" as const },
];

function ReferralDialog({
  referral,
  onClose,
  onChanged,
}: {
  referral: AdminReferral | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    setReason("");
    setError("");
  }, [referral?.id]);

  if (!referral) return null;

  const canManage = can("REFERRAL_MANAGE");
  const canReverse = can("WALLET_ADJUST");

  async function run(action: string) {
    if (!referral) return;
    setBusy(true);
    setError("");
    try {
      await api.post(`/admin/referrals/${referral.id}/${action}/`, { reason });
      toast.success("Referral updated");
      onChanged();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={Boolean(referral)}
      onClose={onClose}
      title={`Referral ${referral.code}`}
      description={`${referral.referrer_email} invited ${referral.referred_email}`}
      dismissible={!busy}
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger" title="Could not complete that">{error}</Alert> : null}

        <dl className="grid grid-cols-2 gap-3 text-sm">
          <Detail label="Status" value={referral.status} />
          <Detail
            label="Friend's bonus"
            value={referral.reward ? `${cedis(referral.reward.amount)} (${referral.reward.status})` : "None"}
          />
          <Detail
            label="Inviter's reward"
            value={
              referral.referrer_reward
                ? `${cedis(referral.referrer_reward.amount)} (${referral.referrer_reward.status})`
                : "Not yet"
            }
          />
          <Detail
            label="Invited email verified"
            value={referral.referred_email_verified ? "Yes" : "Not yet"}
          />
          <Detail label="Invited suspended" value={referral.referred_suspended ? "Yes" : "No"} />
          <Detail label="Created" value={formatDateTime(referral.created_at)} />
          <Detail
            label="Rewarded"
            value={referral.rewarded_at ? formatDateTime(referral.rewarded_at) : "-"}
          />
        </dl>

        {referral.staff_note ? (
          <div className="rounded-lg bg-sunken p-3 text-sm text-ink-muted">
            <span className="font-medium text-ink">Staff note: </span>
            {referral.staff_note}
          </div>
        ) : null}

        {referral.risk_flags.length > 0 ? (
          <div>
            <p className="text-sm font-medium text-ink">Risk flags</p>
            <ul className="mt-2 space-y-2">
              {referral.risk_flags.map((flag) => (
                <li
                  key={flag.kind}
                  className="rounded-xl border border-line px-3 py-2 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-ink">{flag.kind.replaceAll("_", " ")}</span>
                    <StatusBadge status={flag.blocking ? "BLOCKING" : flag.level} />
                  </div>
                  <p className="mt-0.5 text-ink-muted">{flag.detail}</p>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-caption text-ink-muted">
              A shared IP address is never blocking on its own - homes, offices, schools and
              mobile networks all share addresses.
            </p>
          </div>
        ) : null}

        {canManage || canReverse ? (
          <>
            <Field label="Reason" htmlFor="reason" required hint="Recorded in the audit log.">
              <Textarea
                id="reason"
                rows={2}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why are you making this decision?"
              />
            </Field>

            <div className="flex flex-wrap gap-2">
              {ACTIONS.map((action) => {
                const needsWallet = action.key === "reverse-reward";
                if (needsWallet ? !canReverse : !canManage) return null;
                return (
                  <Button
                    key={action.key}
                    variant={action.tone}
                    size="sm"
                    loading={busy}
                    disabled={reason.trim().length < 5}
                    onClick={() => run(action.key)}
                  >
                    {action.label}
                  </Button>
                );
              })}
            </div>
          </>
        ) : (
          <Alert tone="info" title="Read-only">
            You can review referrals, but deciding them needs a wider role.
          </Alert>
        )}
      </div>
    </Dialog>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-caption text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink">{value}</dd>
    </div>
  );
}

type Programme = {
  is_enabled: boolean;
  signup_bonus: string;
  referrer_bonus: string;
  require_first_deposit: boolean;
  min_first_deposit: string;
  currency: string;
};

/**
 * The whole programme on or off. Paused: new sign-ups are not attributed, no
 * bonus is paid, and customers see no way into referrals - history and credit
 * already issued are untouched. Changing it is a money decision, so it needs
 * the pricing permission, and the reason goes to the audit log.
 */
function ProgrammeSwitch() {
  const toast = useToast();
  const { can } = useAuth();
  const { data, mutate } = useSWR<Programme>("/admin/referral-program/");
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  if (!data) return <Skeleton className="h-18 w-full rounded-2xl" />;

  const running = data.is_enabled;
  const canChange = can("PRICING_MANAGE");

  async function change() {
    setBusy(true);
    setError("");
    try {
      const updated = await api.patch<Programme>("/admin/referral-program/", {
        is_enabled: !running,
        reason,
      });
      await mutate(updated, { revalidate: false });
      // The customer app reads this to show or hide referrals.
      void globalMutate("/referrals/status/");
      toast.success(updated.is_enabled ? "Referral programme resumed" : "Referral programme paused");
      setOpen(false);
      setReason("");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold text-ink">
            Programme
            <StatusBadge status={running ? "ACTIVE" : "PAUSED"} />
          </p>
          <p className="mt-0.5 text-sm text-ink-muted">
            {running
              ? `Running. Invited friends get ${cedis(data.signup_bonus)} ${
                  data.require_first_deposit
                    ? `after a first top-up of ${cedis(data.min_first_deposit)} or more`
                    : "once they verify their email"
                }${
                  Number.parseFloat(data.referrer_bonus) > 0
                    ? `; the inviter gets ${cedis(data.referrer_bonus)} when that friend completes a number paid partly in cash.`
                    : "."
                }`
              : "Paused. Sign-ups are not linked to referrers, no bonus is paid, and customers do not see referrals."}
          </p>
        </div>
        {canChange ? (
          <Button
            variant={running ? "secondary" : "primary"}
            size="sm"
            className="shrink-0"
            onClick={() => setOpen(true)}
          >
            {running ? "Pause programme" : "Resume programme"}
          </Button>
        ) : null}
      </Card>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={running ? "Pause the referral programme?" : "Resume the referral programme?"}
        description={
          running
            ? "New sign-ups stop being linked to referrers and no new bonuses are paid. Credit already issued, and every referral so far, stay as they are."
            : "Invite codes start working again, and qualifying referrals earn the bonus."
        }
        dismissible={!busy}
      >
        <div className="space-y-4">
          {error ? <Alert tone="danger" title="Could not change the programme">{error}</Alert> : null}
          <Field label="Reason" htmlFor="programme-reason" required hint="Recorded in the audit log.">
            <Textarea
              id="programme-reason"
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={running ? "Why pause it?" : "Why resume it?"}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant={running ? "danger" : "primary"}
              size="sm"
              loading={busy}
              disabled={reason.trim().length < 5}
              onClick={change}
            >
              {running ? "Pause programme" : "Resume programme"}
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
