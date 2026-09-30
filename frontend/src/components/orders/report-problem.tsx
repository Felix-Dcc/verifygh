"use client";

import * as React from "react";

import { AlertIcon, CheckCircleIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  Field,
  StatusBadge,
  Textarea,
  cn,
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { IssueReason, Order, OrderIssue } from "@/lib/types";

const REASONS: { value: IssueReason; label: string; hint: string }[] = [
  {
    value: "NUMBER_ALREADY_LINKED",
    label: "Number already linked to an account",
    hint: "The service asked you to sign in instead of letting you sign up.",
  },
  {
    value: "SMS_NOT_RECEIVED",
    label: "Didn't receive SMS",
    hint: "The message you were expecting never showed up.",
  },
  {
    value: "OTP_DID_NOT_WORK",
    label: "OTP didn't work",
    hint: "The service rejected the code.",
  },
  {
    value: "SERVICE_REJECTED_NUMBER",
    label: "Service rejected the number",
    hint: "The service would not accept this number at all.",
  },
  { value: "OTHER", label: "Other", hint: "Something else went wrong." },
];

/**
 * "Report a problem", shown once a code has arrived.
 *
 * Deliberately never asks for anything belonging to the other service: no
 * passwords, no codes, no PINs. The customer deals with TikTok (or whoever)
 * directly; all we need to know is what happened.
 */
export function ReportProblem({ order, onReported }: { order: Order; onReported: () => void }) {
  const [open, setOpen] = React.useState(false);

  if (!order.issue && !order.can_report) return null;

  return (
    <>
      {order.issue ? (
        <IssueStatusCard issue={order.issue} />
      ) : (
        <Card className="p-4 sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium text-ink">Number not working as expected?</p>
              <p className="mt-0.5 text-caption text-ink-muted">
                {order.report_window_ends_at
                  ? `You can report a problem until ${formatDateTime(order.report_window_ends_at)}.`
                  : "Tell us what happened and we'll review it."}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setOpen(true)}
              icon={<AlertIcon className="h-4 w-4" />}
            >
              Report a problem
            </Button>
          </div>
        </Card>
      )}
      {/* Mounted outside the card: filing the report refreshes the order, which
          swaps the card for the status view, and the confirmation must survive that. */}
      <ReportDialog
        open={open}
        onClose={() => setOpen(false)}
        order={order}
        onReported={onReported}
      />
    </>
  );
}

function ReportDialog({
  open,
  onClose,
  order,
  onReported,
}: {
  open: boolean;
  onClose: () => void;
  order: Order;
  onReported: () => void;
}) {
  const [reason, setReason] = React.useState<IssueReason | null>(null);
  const [details, setDetails] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [filed, setFiled] = React.useState<OrderIssue | null>(null);

  React.useEffect(() => {
    if (open) {
      setReason(null);
      setDetails("");
      setError("");
      setFiled(null);
    }
  }, [open]);

  async function submit() {
    if (!reason) return;
    setBusy(true);
    setError("");
    try {
      const issue = await api.post<OrderIssue>(`/orders/${order.reference}/report/`, {
        reason,
        details: details.trim(),
        confirmed_existing_account: reason === "NUMBER_ALREADY_LINKED",
      });
      setFiled(issue);
      onReported();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={filed ? "Report received" : "Report a problem"}
      description={filed ? undefined : `${order.service_name} - ${order.reference}`}
      dismissible={!busy}
    >
      {filed ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-xl bg-success-50 p-4 text-success-700">
            <CheckCircleIcon className="mt-0.5 h-5 w-5 shrink-0" />
            <div className="space-y-1 text-sm">
              <p className="font-medium">Thanks for reporting this.</p>
              <p>We&apos;ve flagged this number for review.</p>
              <p>
                If the number is confirmed unusable for the requested service, your order will be
                handled according to our replacement/refund policy.
              </p>
            </div>
          </div>
          <p className="text-caption text-ink-muted">Report reference: {filed.reference}</p>
          <div className="flex justify-end">
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {error ? (
            <Alert tone="danger" title="Could not send the report">
              {error}
            </Alert>
          ) : null}

          <fieldset>
            <legend className="mb-2 text-sm font-medium text-ink">What went wrong?</legend>
            <div className="space-y-2">
              {REASONS.map((option) => (
                <label
                  key={option.value}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 transition-colors",
                    reason === option.value
                      ? "border-brand-500 bg-brand-50"
                      : "border-line hover:bg-sunken/60",
                  )}
                >
                  <input
                    type="radio"
                    name="issue-reason"
                    value={option.value}
                    checked={reason === option.value}
                    onChange={() => setReason(option.value)}
                    className="mt-1 accent-brand-600"
                  />
                  <span>
                    <span className="block text-sm font-medium text-ink">{option.label}</span>
                    <span className="block text-caption text-ink-muted">{option.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {reason === "NUMBER_ALREADY_LINKED" ? (
            <div className="space-y-3 rounded-lg border border-line bg-sunken p-4">
              <p className="text-sm text-ink">
                Did {order.service_name} ask you for an existing password instead of allowing you
                to create an account?
              </p>
              <p className="text-caption text-ink-muted">
                Don&apos;t try to guess or reset that password - the account isn&apos;t yours. We
                never need your password for {order.service_name} or any other service.
              </p>
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button variant="secondary" onClick={() => setReason(null)} disabled={busy}>
                  No
                </Button>
                <Button onClick={submit} loading={busy}>
                  Yes, report this number
                </Button>
              </div>
            </div>
          ) : reason ? (
            <>
              <Field
                label="Anything else we should know?"
                htmlFor="issue-details"
                hint="Optional. Never include passwords, PINs or verification codes."
              >
                <Textarea
                  id="issue-details"
                  rows={3}
                  maxLength={500}
                  value={details}
                  onChange={(event) => setDetails(event.target.value)}
                />
              </Field>
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <Button variant="secondary" onClick={onClose} disabled={busy}>
                  Cancel
                </Button>
                <Button onClick={submit} loading={busy}>
                  Send report
                </Button>
              </div>
            </>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

function IssueStatusCard({ issue }: { issue: OrderIssue }) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink">Problem reported</p>
          <p className="mt-0.5 text-caption text-ink-muted">
            {issue.reason_label} &middot; {formatDateTime(issue.created_at)}
          </p>
        </div>
        <StatusBadge status={issue.status} />
      </div>
      <p className="mt-3 text-sm text-ink-soft">{issue.message}</p>
      {issue.replacement_order_reference ? (
        <ButtonLink href={`/orders/${issue.replacement_order_reference}`} size="sm" className="mt-3">
          Open replacement order
        </ButtonLink>
      ) : null}
    </Card>
  );
}
