"use client";

import useSWR from "swr";

import { PROVIDERS_KEY, ProviderCard, type ProvidersOverview } from "@/components/admin/providers";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { Alert, Skeleton } from "@/components/ui/primitives";

/**
 * Admin > Providers: every number supplier, whether it may sell, and how it is
 * doing - measured from our own calls and orders, never estimated.
 * See docs/PROVIDERS.md.
 */
export default function AdminProvidersPage() {
  const { can } = useAuth();
  const canView = can("PRICING_VIEW");
  const { data, error, mutate } = useSWR<ProvidersOverview>(canView ? PROVIDERS_KEY : null, {
    refreshInterval: 60_000,
  });

  if (!canView) {
    return (
      <div className="space-y-4">
        <PageHeader title="Providers" />
        <Alert tone="info" title="Providers are restricted">
          Your role cannot see provider costs and balances.
        </Alert>
      </div>
    );
  }

  const selling = data?.providers.filter((provider) => provider.selling) ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Providers"
        description="Where our numbers come from, whether each supplier has authorised us to resell, and how each one is performing."
      />

      {data && selling.length === 0 ? (
        <Alert tone="danger" title="No provider is selling right now">
          Customers see no services. A provider sells only when it is switched on, its credentials are set and
          its written authorisation to resell has been recorded here.
        </Alert>
      ) : null}
      {error ? <Alert tone="danger">Could not load providers.</Alert> : null}
      {!data && !error ? <Skeleton className="h-64" /> : null}

      {data?.providers.map((provider) => (
        <ProviderCard
          key={provider.adapter_key}
          provider={provider}
          canManage={data.can_manage}
          onChanged={() => mutate()}
        />
      ))}
    </div>
  );
}
