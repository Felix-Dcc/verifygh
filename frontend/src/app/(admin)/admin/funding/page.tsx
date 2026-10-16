"use client";

import useSWR from "swr";

import {
  CashFlowCard,
  FUNDING_KEY,
  FundingAlerts,
  type FundingOverview,
  ProviderAccountCard,
} from "@/components/admin/funding";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { Alert, Skeleton } from "@/components/ui/primitives";

/**
 * Admin > Provider funding: the prepaid balance numbers are bought from.
 *
 * Our providers are prepaid with no funding API, so this page is where staff
 * see the balance coming, top it up by hand and keep the books - with customer
 * money shown apart from our own. See docs/PROVIDER-FUNDING.md.
 */
export default function AdminFundingPage() {
  const { can } = useAuth();
  const canView = can("PRICING_VIEW");
  const { data, error, mutate } = useSWR<FundingOverview>(canView ? FUNDING_KEY : null, {
    refreshInterval: 60_000,
  });

  if (!canView) {
    return (
      <div className="space-y-4">
        <PageHeader title="Provider funding" />
        <Alert tone="info" title="Provider funding is restricted">
          Your role cannot see provider balances and costs.
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Provider funding"
        description="The prepaid balance every number is bought from, when to top it up, and how customer money, provider money and profit stay apart."
      />

      <Alert tone="info" title="Our providers require provider-side funding">
        Every provider we use is prepaid: it sells a number only against credit already in our account
        there, and none has an API to add money. Software cannot remove that requirement. VerifyGH watches
        each balance, refuses purchases it cannot cover before charging anyone, and alerts you - the
        top-up itself is made by hand on the provider&apos;s website.
      </Alert>

      {error ? <Alert tone="danger">Could not load provider funding.</Alert> : null}
      {!data && !error ? <Skeleton className="h-64" /> : null}

      {data?.accounts.map((account) => (
        <ProviderAccountCard
          key={account.adapter_key}
          account={account}
          canManage={data.can_manage}
          methods={data.top_up_methods}
          onChanged={() => mutate()}
        />
      ))}
      {data ? <CashFlowCard flow={data.cash_flow} /> : null}
      {data ? (
        <FundingAlerts
          openAlerts={data.open_alerts ?? []}
          history={data.alerts}
          canManage={data.can_manage}
          onChanged={() => mutate()}
        />
      ) : null}
    </div>
  );
}
