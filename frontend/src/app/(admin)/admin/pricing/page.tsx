"use client";

import * as React from "react";
import useSWR from "swr";

import { PriceHistoryCard, PricingRulesCard } from "@/components/admin/pricing";
import {
  BulkMarkupPanel,
  CostHistoryCard,
  FXPanel,
  PolicyPanel,
  PricingAuditCard,
  PricingSummaryCards,
  PricingTable,
  ReviewPanel,
} from "@/components/admin/pricing-dashboard";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { Alert, SegmentedControl } from "@/components/ui/primitives";
import type { PricingSummary } from "@/lib/types";

type Tab = "prices" | "fx" | "markup" | "review" | "history" | "settings";

/**
 * Admin > Pricing: what a number costs us, what we charge, what we keep.
 *
 * Provider cost -> VerifyGH Pricing FX Rate -> cost in cedis -> markup ->
 * customer price, with every step visible and every change audited.
 */
export default function AdminPricingPage() {
  const { can } = useAuth();
  const [tab, setTab] = React.useState<Tab>("prices");
  const canView = can("PRICING_VIEW");
  const canManage = can("PRICING_MANAGE");
  const { data: summary } = useSWR<PricingSummary>(canView ? "/admin/pricing/summary/" : null);

  if (!canView) {
    return (
      <div className="space-y-4">
        <PageHeader title="Pricing Management" />
        <Alert tone="info" title="Pricing is restricted">
          Your role cannot see provider costs and margins.
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Pricing Management"
        description="What each number costs us, what we charge, and what we keep - provider cost, VerifyGH Pricing FX Rate, markup and final price, with every change recorded."
      />

      <PricingSummaryCards summary={summary} />

      <SegmentedControl
        options={[
          { value: "prices" as Tab, label: "Prices" },
          { value: "fx" as Tab, label: "FX settings" },
          { value: "markup" as Tab, label: "Markup rules" },
          { value: "review" as Tab, label: `Review${summary?.pending_review ? ` (${summary.pending_review})` : ""}` },
          { value: "history" as Tab, label: "History" },
          { value: "settings" as Tab, label: "Settings" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {!canManage ? (
        <Alert tone="info" title="View only">
          You can see pricing but not change it. Changes need the Pricing Manager permission.
        </Alert>
      ) : null}

      {tab === "prices" ? (
        <PricingTable summary={summary} canManage={canManage} canApproveLoss={can("PRICING_LOSS_OVERRIDE")} />
      ) : null}
      {tab === "fx" ? <FXPanel canManage={canManage} /> : null}
      {tab === "markup" ? (
        <div className="space-y-4">
          {canManage ? <BulkMarkupPanel summary={summary} /> : null}
          <PricingRulesCard />
        </div>
      ) : null}
      {tab === "review" ? (
        <div className="space-y-4">
          <ReviewPanel summary={summary} canManage={canManage} />
          <PricingTable
            summary={summary}
            canManage={canManage}
            canApproveLoss={can("PRICING_LOSS_OVERRIDE")}
            presetStatus="override"
          />
        </div>
      ) : null}
      {tab === "history" ? (
        <div className="space-y-4">
          <PriceHistoryCard />
          <CostHistoryCard />
          <PricingAuditCard />
        </div>
      ) : null}
      {tab === "settings" ? <PolicyPanel canManage={canManage} /> : null}
    </div>
  );
}
