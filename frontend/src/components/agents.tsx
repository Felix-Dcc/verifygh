"use client";

import useSWR from "swr";

import { Badge } from "@/components/ui/primitives";
import { cedis, formatDate, formatDateTime } from "@/lib/format";

/** Commission and payout rows, shared by Admin > Agents and the agent's own page. */

export type Commission = {
  id: string;
  kind: "ORDER" | "RENTAL" | "EXTENSION";
  reference: string;
  customer: string;
  base_amount: string;
  percent: string;
  amount: string;
  status: "EARNED" | "REVERSED";
  created_at: string;
};

export type Payout = { id: string; amount: string; reference: string; note: string; created_at: string };

const KIND = { ORDER: "Verification", RENTAL: "Rental", EXTENSION: "Rental extension" };

export function CommissionTable({ rows }: { rows: Commission[] }) {
  if (!rows.length) return <p className="text-sm text-ink-muted">No commission earned yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="text-left text-caption text-ink-muted">
            <th className="py-2 pr-3 font-medium">Date</th>
            <th className="py-2 pr-3 font-medium">Sale</th>
            <th className="py-2 pr-3 font-medium">Customer</th>
            <th className="py-2 pr-3 font-medium">Paid</th>
            <th className="py-2 font-medium">Commission</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="py-2 pr-3">{formatDate(row.created_at)}</td>
              <td className="py-2 pr-3">
                {KIND[row.kind]}
                <span className="block text-caption text-ink-muted">{row.reference}</span>
              </td>
              <td className="py-2 pr-3">{row.customer}</td>
              <td className="tabular py-2 pr-3">{cedis(row.base_amount)}</td>
              <td className="tabular py-2">
                {row.status === "REVERSED" ? (
                  <Badge tone="neutral">Refunded, not earned</Badge>
                ) : (
                  <>
                    {cedis(row.amount)}
                    <span className="text-caption text-ink-muted"> ({Number.parseFloat(row.percent)}%)</span>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PayoutTable({ rows }: { rows: Payout[] }) {
  if (!rows.length) return <p className="text-sm text-ink-muted">No payouts yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm">
        <thead>
          <tr className="text-left text-caption text-ink-muted">
            <th className="py-2 pr-3 font-medium">Paid on</th>
            <th className="py-2 pr-3 font-medium">Amount</th>
            <th className="py-2 font-medium">Transaction ID</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="py-2 pr-3">{formatDateTime(row.created_at)}</td>
              <td className="tabular py-2 pr-3">{cedis(row.amount)}</td>
              <td className="py-2">{row.reference}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Whether the signed-in user is a registered agent, for showing the Agent link. */
export function useIsAgent(): boolean {
  const { data } = useSWR<{ is_agent: boolean }>("/referrals/agent/", {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return data?.is_agent === true;
}
