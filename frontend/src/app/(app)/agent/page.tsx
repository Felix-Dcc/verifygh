"use client";

import useSWR from "swr";

import { MetricTile } from "@/components/admin/charts";
import { type Commission, CommissionTable, type Payout, PayoutTable } from "@/components/agents";
import { Alert, Button, Card, CardHeader, EmptyState, Input, Skeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { cedis } from "@/lib/format";

/**
 * The agent's own page: their link, what their customers' purchases earned,
 * and what has been paid out. Only people staff registered as agents see it.
 */

type MyAgent =
  | { is_agent: false }
  | {
      is_agent: true;
      commission_percent: string;
      is_active: boolean;
      payout_details: string;
      code: string;
      share_url: string;
      customers: number;
      sales: number;
      sales_volume: string;
      earned: string;
      paid: string;
      balance: string;
      commissions: Commission[];
      payouts: Payout[];
    };

const AGENT_KEY = "/referrals/agent/";
/** A card's body: `Card` itself carries no padding. */
const BODY = "px-4 pb-4 pt-3 sm:px-5";

export default function AgentPage() {
  const { data, error } = useSWR<MyAgent>(AGENT_KEY);
  const toast = useToast();

  if (error) return <Alert tone="danger">Could not load your agent page. Refresh to try again.</Alert>;
  if (!data) return <Skeleton className="h-48" />;

  if (!data.is_agent) {
    return (
      <div className="space-y-6">
        <h1 className="text-title text-ink">Agent</h1>
        <EmptyState
          title="You are not an agent yet"
          description="Agents earn commission when the customers they bring buy numbers. Message support if you would like to become one."
        />
      </div>
    );
  }

  const rate = Number.parseFloat(data.commission_percent);

  async function copy() {
    if (!data?.is_agent) return;
    try {
      await navigator.clipboard.writeText(data.share_url);
      toast.success("Link copied");
    } catch {
      toast.error("Could not copy. Select the link and copy it yourself.");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-title text-ink">Agent</h1>
        <p className="mt-1 text-sm text-ink-muted">
          You earn {rate}% of what your customers pay for numbers. A purchase that is refunded
          earns nothing, and promotional credit does not count.
        </p>
      </div>

      {data.is_active ? null : (
        <Alert tone="warn" title="Your agent account is paused">
          Purchases made while it is paused earn no commission. Message support to resume.
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricTile label="Owed to you" value={cedis(data.balance)} sublabel="Paid by mobile money" />
        <MetricTile label="Earned so far" value={cedis(data.earned)} sublabel={`${data.sales} purchases`} />
        <MetricTile label="Paid out" value={cedis(data.paid)} />
        <MetricTile label="Your customers" value={data.customers} sublabel="Signed up with your link" />
      </div>

      <Card>
        <CardHeader
          title="Your link"
          description="Everyone who signs up with this link, or types your code when signing up, becomes your customer for good."
        />
        <div className={BODY}>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="flex-1">
              <Input readOnly value={data.share_url} aria-label="Your agent link" onFocus={(e) => e.target.select()} />
            </div>
            <Button onClick={copy}>Copy link</Button>
          </div>
          <p className="mt-2 text-caption text-ink-muted">
            Your code: <span className="font-semibold text-ink">{data.code}</span>
            {data.payout_details ? <> · We pay you on: {data.payout_details}</> : null}
          </p>
        </div>
      </Card>

      <Card>
        <CardHeader title="Commission" description="The latest 50 purchases by your customers." />
        <div className={BODY}>
          <CommissionTable rows={data.commissions} />
        </div>
      </Card>

      <Card>
        <CardHeader title="Payouts" />
        <div className={BODY}>
          <PayoutTable rows={data.payouts} />
        </div>
      </Card>
    </div>
  );
}
