"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { GiftIcon, SearchIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
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
  const { data, isLoading, mutate } = useSWR<Paginated<AdminReferral>>(key);
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

      <div className="metric-group grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Registrations" value={analytics?.registrations} />
        <Stat label="Rewarded" value={analytics?.rewarded} />
        <Stat
          label="Credit issued"
          value={analytics ? cedis(analytics.promotional_credit_issued) : undefined}
        />
        <Stat
          label="Cost per acquisition"
          value={analytics ? cedis(analytics.average_acquisition_cost) : undefined}
          hint={analytics ? `${analytics.conversion_rate}% conversion` : undefined}
        />
      </div>

      {analytics && analytics.fraud_flagged > 0 ? (
        <Alert tone="warn" title={`${analytics.fraud_flagged} referrals need review`}>
          These are held, not rejected. Open one to see which check caught it.
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <SegmentedControl
          options={STATUS_FILTERS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
        />
        <div className="relative lg:ml-auto lg:w-80">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Code or email address"
            className="pl-9"
            aria-label="Search referrals"
          />
        </div>
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2, 3].map((row) => (
              <Skeleton key={row} className="h-12 w-full" />
            ))}
          </div>
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
                  <tr
                    key={referral.id}
                    onClick={() => setSelected(referral)}
                    className="cursor-pointer transition hover:bg-sunken/60"
                  >
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
      </Card>

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

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value?: number | string;
  hint?: string;
}) {
  return (
    <Card className="p-4">
      <p className="text-caption text-ink-muted">{label}</p>
      {value === undefined ? (
        <Skeleton className="mt-2 h-6 w-20" />
      ) : (
        <p className="tabular mt-1 text-title text-ink">{value}</p>
      )}
      {hint ? <p className="mt-0.5 text-caption text-ink-muted">{hint}</p> : null}
    </Card>
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
            label="Reward"
            value={referral.reward ? `${cedis(referral.reward.amount)} (${referral.reward.status})` : "None"}
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
            <p className="mt-2 text-xs text-ink-muted">
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
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink">{value}</dd>
    </div>
  );
}
