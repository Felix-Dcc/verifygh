"use client";

import * as React from "react";
import useSWR from "swr";

import { type Commission, CommissionTable, type Payout, PayoutTable } from "@/components/agents";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Select,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis } from "@/lib/format";

/**
 * Admin > Agents: people who earn a cash commission on what the customers
 * they bring in pay for numbers. Staff register them, set the rate, and record
 * each payout after sending it by mobile money - the site never sends money.
 */

type Agent = {
  id: string;
  email: string;
  full_name: string;
  commission_percent: string;
  is_active: boolean;
  payout_details: string;
  code: string;
  share_url: string;
  created_at: string;
  customers: number;
  sales: number;
  sales_volume: string;
  earned: string;
  paid: string;
  balance: string;
};

type AgentDetail = Agent & { commissions: Commission[]; payouts: Payout[] };

const KEY = "/admin/agents/";

function message(caught: unknown, fallback: string) {
  return caught instanceof ApiError ? caught.message : fallback;
}

export default function AdminAgentsPage() {
  const { can } = useAuth();
  const canManage = can("PRICING_MANAGE");
  const canPay = can("WALLET_ADJUST");
  const { data, error, mutate } = useSWR<{ default_percent: string; results: Agent[] }>(KEY);
  const [registering, setRegistering] = React.useState(false);
  const [editing, setEditing] = React.useState<Agent | null>(null);
  const [paying, setPaying] = React.useState<Agent | null>(null);
  const [viewing, setViewing] = React.useState<Agent | null>(null);

  const owed = data
    ? data.results.reduce((sum, agent) => sum + Math.max(0, Number.parseFloat(agent.balance)), 0)
    : 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Agents"
        description="People who earn commission when customers sign up with their link and buy numbers."
        action={
          canManage ? <Button onClick={() => setRegistering(true)}>Register an agent</Button> : null
        }
      />

      {error ? <Alert tone="danger">Could not load agents. Refresh to try again.</Alert> : null}
      {!data && !error ? <Skeleton className="h-40" /> : null}

      {data && !data.results.length ? (
        <EmptyState
          title="No agents yet"
          description="Register someone who already has a VerifyGH account. They get a link to share and earn on every number their customers buy."
        />
      ) : null}

      {data?.results.length ? (
        <Card className="p-4 sm:p-5">
          <p className="mb-3 text-sm text-ink-muted">
            Commission owed to all agents:{" "}
            <span className="tabular font-semibold text-ink">{cedis(owed)}</span>
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="text-left text-caption text-ink-muted">
                  <th className="py-2 pr-3 font-medium">Agent</th>
                  <th className="py-2 pr-3 font-medium">Rate</th>
                  <th className="py-2 pr-3 font-medium">Customers</th>
                  <th className="py-2 pr-3 font-medium">Sales</th>
                  <th className="py-2 pr-3 font-medium">Earned</th>
                  <th className="py-2 pr-3 font-medium">Paid</th>
                  <th className="py-2 pr-3 font-medium">Owed</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.results.map((agent) => (
                  <tr key={agent.id}>
                    <td className="py-2.5 pr-3">
                      <p className="font-medium text-ink">{agent.full_name || agent.email}</p>
                      <p className="text-caption text-ink-muted">
                        {agent.email} · code {agent.code}
                      </p>
                      {agent.is_active ? null : <Badge tone="warn">Paused</Badge>}
                    </td>
                    <td className="tabular py-2.5 pr-3">{Number.parseFloat(agent.commission_percent)}%</td>
                    <td className="tabular py-2.5 pr-3">{agent.customers}</td>
                    <td className="tabular py-2.5 pr-3">
                      {agent.sales}
                      <span className="block text-caption text-ink-muted">{cedis(agent.sales_volume)}</span>
                    </td>
                    <td className="tabular py-2.5 pr-3">{cedis(agent.earned)}</td>
                    <td className="tabular py-2.5 pr-3">{cedis(agent.paid)}</td>
                    <td className="tabular py-2.5 pr-3 font-semibold text-ink">{cedis(agent.balance)}</td>
                    <td className="py-2.5">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="secondary" onClick={() => setViewing(agent)}>
                          View
                        </Button>
                        {canManage ? (
                          <Button size="sm" variant="secondary" onClick={() => setEditing(agent)}>
                            Edit
                          </Button>
                        ) : null}
                        {canPay && Number.parseFloat(agent.balance) > 0 ? (
                          <Button size="sm" onClick={() => setPaying(agent)}>
                            Record payout
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      <RegisterDialog
        open={registering}
        onClose={() => setRegistering(false)}
        defaultPercent={data?.default_percent ?? "5.00"}
        onSaved={mutate}
      />
      {editing ? <EditDialog agent={editing} onClose={() => setEditing(null)} onSaved={mutate} /> : null}
      {paying ? <PayoutDialog agent={paying} onClose={() => setPaying(null)} onSaved={mutate} /> : null}
      {viewing ? <DetailDialog agent={viewing} onClose={() => setViewing(null)} /> : null}
    </div>
  );
}

function RegisterDialog({
  open,
  onClose,
  defaultPercent,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  defaultPercent: string;
  onSaved: () => Promise<unknown>;
}) {
  const toast = useToast();
  const blank = { email: "", commission_percent: "", payout_details: "" };
  const [form, setForm] = React.useState(blank);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.post(KEY, { ...form, commission_percent: form.commission_percent || null });
      toast.success("Agent registered");
      setForm(blank);
      await onSaved();
      onClose();
    } catch (caught) {
      setError(message(caught, "Could not register the agent."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Register an agent"
      description="They must already have a VerifyGH account. Purchases their customers make from now on earn them commission."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy} disabled={!form.email}>
            Register
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field label="Their account email" htmlFor="agent-email" required>
          <Input
            id="agent-email"
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            autoComplete="off"
          />
        </Field>
        <Field
          label="Commission (%)"
          htmlFor="agent-percent"
          hint={`Leave empty for the standard ${Number.parseFloat(defaultPercent)}%.`}
        >
          <Input
            id="agent-percent"
            inputMode="decimal"
            value={form.commission_percent}
            onChange={(e) => setForm({ ...form, commission_percent: e.target.value })}
            className="tabular"
          />
        </Field>
        <Field
          label="Where to pay them"
          htmlFor="agent-payout"
          hint="Mobile money number and the name on it."
        >
          <Input
            id="agent-payout"
            value={form.payout_details}
            onChange={(e) => setForm({ ...form, payout_details: e.target.value })}
            maxLength={120}
          />
        </Field>
      </div>
    </Dialog>
  );
}

function EditDialog({
  agent,
  onClose,
  onSaved,
}: {
  agent: Agent;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const toast = useToast();
  const [form, setForm] = React.useState({
    commission_percent: agent.commission_percent,
    payout_details: agent.payout_details,
    is_active: agent.is_active ? "yes" : "no",
  });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.patch(`${KEY}${agent.id}/`, { ...form, is_active: form.is_active === "yes" });
      toast.success("Agent updated");
      await onSaved();
      onClose();
    } catch (caught) {
      setError(message(caught, "Could not update the agent."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Edit ${agent.full_name || agent.email}`}
      description="A new rate applies to purchases from now on. What they already earned stays as it is."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field label="Commission (%)" htmlFor="edit-percent" required>
          <Input
            id="edit-percent"
            inputMode="decimal"
            value={form.commission_percent}
            onChange={(e) => setForm({ ...form, commission_percent: e.target.value })}
            className="tabular"
          />
        </Field>
        <Field label="Where to pay them" htmlFor="edit-payout">
          <Input
            id="edit-payout"
            value={form.payout_details}
            onChange={(e) => setForm({ ...form, payout_details: e.target.value })}
            maxLength={120}
          />
        </Field>
        <Field
          label="Status"
          htmlFor="edit-active"
          hint="A paused agent earns nothing on purchases made while paused."
        >
          <Select
            id="edit-active"
            value={form.is_active}
            onChange={(e) => setForm({ ...form, is_active: e.target.value })}
          >
            <option value="yes">Active</option>
            <option value="no">Paused</option>
          </Select>
        </Field>
      </div>
    </Dialog>
  );
}

function PayoutDialog({
  agent,
  onClose,
  onSaved,
}: {
  agent: Agent;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const toast = useToast();
  const [form, setForm] = React.useState({ amount: agent.balance, reference: "", note: "" });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.post(`${KEY}${agent.id}/payouts/`, form);
      toast.success("Payout recorded");
      await onSaved();
      onClose();
    } catch (caught) {
      setError(message(caught, "Could not record the payout."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Record a payout to ${agent.full_name || agent.email}`}
      description="Send the money by mobile money first, then record it here. This moves no money - it keeps the books and tells the agent."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy} disabled={!form.amount || !form.reference}>
            Record payout
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <p className="text-sm text-ink-muted">
          Owed: <span className="tabular font-semibold text-ink">{cedis(agent.balance)}</span>
          {agent.payout_details ? <> · Pay to: {agent.payout_details}</> : null}
        </p>
        <Field label="Amount sent (GH₵)" htmlFor="payout-amount" required>
          <Input
            id="payout-amount"
            inputMode="decimal"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            className="tabular"
          />
        </Field>
        <Field label="Mobile money transaction ID" htmlFor="payout-ref" required>
          <Input
            id="payout-ref"
            value={form.reference}
            onChange={(e) => setForm({ ...form, reference: e.target.value })}
            autoComplete="off"
            maxLength={80}
          />
        </Field>
        <Field label="Note" htmlFor="payout-note">
          <Input
            id="payout-note"
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
            maxLength={255}
          />
        </Field>
      </div>
    </Dialog>
  );
}

function DetailDialog({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const { data } = useSWR<AgentDetail>(`${KEY}${agent.id}/`);
  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={agent.full_name || agent.email}
      description={`Their link: ${agent.share_url}`}
    >
      {!data ? (
        <Skeleton className="h-32" />
      ) : (
        <div className="space-y-5">
          <CommissionTable rows={data.commissions} />
          <PayoutTable rows={data.payouts} />
        </div>
      )}
    </Dialog>
  );
}
