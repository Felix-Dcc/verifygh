"use client";

import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { MetricTile } from "@/components/admin/charts";
import { Pagination } from "@/components/admin/pagination";
import {
  OfferingPricingDialog,
  StatusBadges,
  fxRate,
  percent,
  providerMoney,
} from "@/components/admin/pricing-offering";
import { SearchIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Select,
  Skeleton,
  Textarea,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, formatDateTime, relativeTime } from "@/lib/format";
import type {
  Paginated,
  PricingAuditRow,
  PricingFXRow,
  PricingImpact,
  PricingPolicyData,
  PricingRow,
  PricingSummary,
  ProviderCostChangeRow,
} from "@/lib/types";

/** Refresh everything a pricing change can move. */
export async function refreshPricing() {
  await globalMutate((key) => {
    const path = Array.isArray(key) ? String(key[0]) : String(key);
    return path.startsWith("/admin/pricing") || path.startsWith("/admin/price-changes");
  });
}

/* -------------------------------------------------------------------------
 * Summary
 * ---------------------------------------------------------------------- */

export function PricingSummaryCards({ summary }: { summary?: PricingSummary }) {
  if (!summary) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-24 rounded-2xl" />
        ))}
      </div>
    );
  }
  const usd = summary.fx.find((row) => row.currency === "USD");
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          label="Total services"
          value={summary.total_services}
          sublabel={`${summary.total_offerings} service-country offerings`}
        />
        <MetricTile
          label="Active services"
          value={summary.active_offerings}
          sublabel={`${summary.not_sold} not sold, ${summary.not_synced} cost not synced`}
        />
        <MetricTile
          label="Average markup %"
          value={percent(summary.average_markup_percent)}
          sublabel="Gross profit / provider cost"
        />
        <MetricTile
          label="Average gross margin %"
          value={percent(summary.average_gross_margin_percent)}
          sublabel={`Gross profit / customer price. Minimum ${percent(summary.policy.minimum_margin_percent)}`}
          tone={
            summary.average_gross_margin_percent &&
            Number.parseFloat(summary.average_gross_margin_percent) <
              Number.parseFloat(summary.policy.minimum_margin_percent)
              ? "negative"
              : "default"
          }
        />
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge tone="brand">
          VerifyGH Pricing FX Rate (USD): {usd?.pricing_rate ? fxRate(usd.pricing_rate) : usd?.error ?? "-"}
          {usd?.mode ? ` - ${usd.mode.toLowerCase()}` : ""}
        </Badge>
        <Badge tone={summary.policy.auto_publish_prices ? "success" : "info"}>
          {summary.policy.auto_publish_prices ? "Prices publish automatically" : "Prices publish after review"}
        </Badge>
        {summary.pending_review ? <Badge tone="info">{summary.pending_review} awaiting review</Badge> : null}
        {summary.below_minimum_margin ? (
          <Badge tone="warn">{summary.below_minimum_margin} below minimum margin</Badge>
        ) : null}
        {summary.active_overrides ? <Badge tone="warn">{summary.active_overrides} overrides</Badge> : null}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * The pricing table
 * ---------------------------------------------------------------------- */

const STATUS_FILTERS = [
  ["", "All statuses"],
  ["active", "Active"],
  ["inactive", "Inactive"],
  ["out_of_stock", "Out of stock"],
  ["not_sold", "Not sold"],
  ["not_synced", "Cost not synced"],
  ["pending", "Awaiting review"],
  ["override", "Overridden"],
  ["below_minimum", "Below minimum margin"],
] as const;

export function PricingTable({
  summary,
  canManage,
  canApproveLoss,
  presetStatus = "",
}: {
  summary?: PricingSummary;
  canManage: boolean;
  canApproveLoss: boolean;
  presetStatus?: string;
}) {
  const [search, setSearch] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [filters, setFilters] = React.useState({
    provider: "",
    country: "",
    status: presetStatus,
    margin_min: "",
    margin_max: "",
    markup_min: "",
    markup_max: "",
    ordering: "service",
  });
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<string | null>(null);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const params = Object.fromEntries(
    Object.entries({ ...filters, search: query, page: String(page), page_size: "50" }).filter(
      ([, value]) => value !== "",
    ),
  );
  const { data, isLoading } = useSWR<Paginated<PricingRow>>(["/admin/pricing/offerings/", params]);
  const rows = data?.results ?? [];
  const set = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };

  return (
    <Card>
      <div className="flex flex-col gap-2 p-4 sm:p-5">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
          <Input
            type="search"
            aria-label="Search services"
            placeholder="Search services..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-11"
          />
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-8">
          <Select aria-label="Provider" value={filters.provider} onChange={(e) => set("provider", e.target.value)} className="h-9 text-sm">
            <option value="">All providers</option>
            {summary?.providers.map((p) => (
              <option key={p.key} value={p.key}>
                {p.name}
                {p.demo ? " (demo)" : ""}
              </option>
            ))}
          </Select>
          <Select aria-label="Country" value={filters.country} onChange={(e) => set("country", e.target.value)} className="h-9 text-sm">
            <option value="">All countries</option>
            <option value="US">United States</option>
            <option value="CA">Canada</option>
          </Select>
          <Select aria-label="Status" value={filters.status} onChange={(e) => set("status", e.target.value)} className="h-9 text-sm">
            {STATUS_FILTERS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
          <Input aria-label="Minimum gross margin %" placeholder="Margin % from" inputMode="decimal" value={filters.margin_min} onChange={(e) => set("margin_min", e.target.value)} className="h-9 text-sm" />
          <Input aria-label="Maximum gross margin %" placeholder="Margin % to" inputMode="decimal" value={filters.margin_max} onChange={(e) => set("margin_max", e.target.value)} className="h-9 text-sm" />
          <Input aria-label="Minimum markup %" placeholder="Markup % from" inputMode="decimal" value={filters.markup_min} onChange={(e) => set("markup_min", e.target.value)} className="h-9 text-sm" />
          <Input aria-label="Maximum markup %" placeholder="Markup % to" inputMode="decimal" value={filters.markup_max} onChange={(e) => set("markup_max", e.target.value)} className="h-9 text-sm" />
          <Select aria-label="Sort" value={filters.ordering} onChange={(e) => set("ordering", e.target.value)} className="h-9 text-sm">
            <option value="service">Sort: service</option>
            <option value="margin">Lowest margin</option>
            <option value="-margin">Highest margin</option>
            <option value="-price">Highest price</option>
            <option value="price">Lowest price</option>
            <option value="-cost">Highest cost</option>
          </Select>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2 px-5 pb-5">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState icon={<SearchIcon />} title="No prices match these filters" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[74rem] text-left text-sm">
            <thead className="border-y border-line bg-canvas">
              <tr className="text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-2.5 font-medium">Service</th>
                <th className="px-3 py-2.5 font-medium">Country</th>
                <th className="px-3 py-2.5 font-medium">Provider</th>
                <th className="px-3 py-2.5 text-right font-medium">Provider cost</th>
                <th className="px-3 py-2.5 font-medium">Currency</th>
                <th className="px-3 py-2.5 text-right font-medium">Pricing FX</th>
                <th className="px-3 py-2.5 text-right font-medium">Cost in cedis</th>
                <th className="px-3 py-2.5 text-right font-medium">Markup</th>
                <th className="px-3 py-2.5 text-right font-medium">Customer price</th>
                <th className="px-3 py-2.5 text-right font-medium">Gross profit</th>
                <th className="px-3 py-2.5 text-right font-medium">Gross margin</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((row) => (
                <tr key={row.id} onClick={() => setSelected(row.id)} className="cursor-pointer transition-colors hover:bg-canvas">
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium text-ink">
                    <span className="inline-flex items-center gap-2.5">
                      <ServiceLogo name={row.service.name} src={row.service.icon_url} slug={row.service.slug} size="sm" />
                      {row.service.name}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-soft">
                    {row.country.flag} {row.country.code}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-soft">
                    {row.provider.name}
                    {row.provider.demo ? <span className="ml-1 text-xs text-ink-faint">(demo)</span> : null}
                  </td>
                  <td className={cn("tabular whitespace-nowrap px-3 py-2.5 text-right", row.provider_cost ? "text-ink" : "text-warn-700")}>
                    {providerMoney(row.provider_cost, row.currency)}
                  </td>
                  <td className="px-3 py-2.5 text-ink-muted">{row.currency}</td>
                  <td className="tabular px-3 py-2.5 text-right text-ink-soft">{fxRate(row.fx_rate)}</td>
                  <td className="tabular whitespace-nowrap px-3 py-2.5 text-right text-ink-soft">{row.ghs_cost ? cedis(row.ghs_cost) : "-"}</td>
                  <td className="tabular whitespace-nowrap px-3 py-2.5 text-right text-ink-soft">{row.markup ?? "-"}</td>
                  <td className="tabular whitespace-nowrap px-3 py-2.5 text-right font-semibold text-ink">
                    {row.customer_price ? cedis(row.customer_price) : "-"}
                    {row.override_price ? <span className="ml-1 text-xs font-normal text-warn-700">override</span> : null}
                  </td>
                  <td className={cn("tabular whitespace-nowrap px-3 py-2.5 text-right", row.is_loss ? "text-danger-700" : "text-success-700")}>
                    {row.gross_profit ? cedis(row.gross_profit) : "-"}
                  </td>
                  <td className={cn("tabular whitespace-nowrap px-3 py-2.5 text-right", row.below_minimum_margin ? "text-warn-700" : "text-ink")}>
                    {percent(row.gross_margin_percent)}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadges row={row} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data?.pagination ? (
        <div className="px-4 py-3 sm:px-5">
          <Pagination
            page={data.pagination.page}
            pages={data.pagination.pages}
            count={data.pagination.count}
            hasNext={data.pagination.has_next}
            hasPrevious={data.pagination.has_previous}
            onChange={setPage}
            noun="prices"
          />
        </div>
      ) : null}

      <OfferingPricingDialog
        offeringId={selected}
        onClose={() => setSelected(null)}
        onChanged={refreshPricing}
        canManage={canManage}
        canApproveLoss={canApproveLoss}
      />
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Confirmation for anything that moves many prices at once
 * ---------------------------------------------------------------------- */

function ImpactConfirm({
  impact,
  title,
  open,
  onCancel,
  onConfirm,
  busy,
  error,
}: {
  impact: PricingImpact | null;
  title: string;
  open: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
  busy: boolean;
  error: string;
}) {
  const [reason, setReason] = React.useState("");
  React.useEffect(() => {
    if (open) setReason("");
  }, [open]);
  if (!impact) return null;
  return (
    <Dialog open={open} onClose={onCancel} title={title} dismissible={!busy} size="lg">
      <div className="space-y-4">
        <Alert tone="warn" title={`You are about to update ${impact.changed} of ${impact.offerings} prices.`}>
          Average change {cedis(impact.average_change)} per price.
          {impact.average_gross_margin_after ? ` Average gross margin afterwards ${percent(impact.average_gross_margin_after)}.` : ""}
          {impact.keep_their_own_rule ? ` ${impact.keep_their_own_rule} keep their own, more specific rule and do not change.` : ""}
          {impact.unsellable ? ` ${impact.unsellable} would not be sold (price below cost).` : ""}
        </Alert>
        {impact.below_minimum_margin ? (
          <Alert tone="danger" title={`${impact.below_minimum_margin} below the minimum margin`}>
            {impact.below_minimum_examples.join("; ")}
          </Alert>
        ) : null}
        {impact.examples.length ? (
          <ul className="divide-y divide-line rounded-xl border border-line text-sm">
            {impact.examples.map((example, index) => (
              <li key={index} className="flex justify-between gap-3 px-3 py-2">
                <span>
                  {example.service} {example.country}
                </span>
                <span className="tabular">
                  {cedis(example.before)} &rarr; {cedis(example.after)}{" "}
                  <span className="text-xs text-ink-muted">({percent(example.gross_margin_after)} margin)</span>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <Field label="Reason" htmlFor="impact-reason" required hint="Recorded in the audit log.">
          <Textarea id="impact-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(reason)} loading={busy} disabled={reason.trim().length < 5}>
            Confirm
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------
 * FX
 * ---------------------------------------------------------------------- */

export function FXPanel({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data, mutate } = useSWR<{ rates: PricingFXRow[] }>("/admin/pricing/fx/");
  const usd = data?.rates.find((row) => row.currency === "USD");
  const [mode, setMode] = React.useState<"MANUAL" | "AUTOMATIC">("MANUAL");
  const [manualRate, setManualRate] = React.useState("");
  const [adjustment, setAdjustment] = React.useState("0");
  const [marketRate, setMarketRate] = React.useState("");
  const [impact, setImpact] = React.useState<PricingImpact | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!usd) return;
    setMode(usd.mode === "AUTOMATIC" ? "AUTOMATIC" : "MANUAL");
    setManualRate(usd.manual_rate ?? usd.effective_rate ?? "");
    setAdjustment(usd.adjustment_percent);
  }, [usd]);

  const effective =
    mode === "MANUAL"
      ? manualRate
      : usd?.market_rate
        ? (Number.parseFloat(usd.market_rate) * (1 + Number.parseFloat(adjustment || "0") / 100)).toFixed(4)
        : "";

  async function previewChange() {
    setError("");
    try {
      setImpact(
        await api.post<PricingImpact>("/admin/pricing/fx/preview/", {
          currency: "USD",
          mode,
          manual_rate: manualRate,
          adjustment_percent: adjustment,
        }),
      );
    } catch (caught) {
      toast.error("Cannot use that rate", caught instanceof ApiError ? caught.message : "Try again.");
    }
  }

  async function apply(reason: string) {
    setBusy(true);
    setError("");
    try {
      await api.put("/admin/pricing/fx/", { currency: "USD", mode, manual_rate: manualRate, adjustment_percent: adjustment, reason });
      toast.success("Pricing FX rate updated");
      setImpact(null);
      await mutate();
      await refreshPricing();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function recordMarket() {
    try {
      await api.post("/admin/exchange-rates/", { rate: marketRate, note: "Market reference", reason: "Market reference rate entered" });
      toast.success("Market reference rate recorded");
      setMarketRate("");
      await mutate();
      await refreshPricing();
    } catch (caught) {
      toast.error("Could not record it", caught instanceof ApiError ? caught.message : "Try again.");
    }
  }

  return (
    <Card>
      <CardHeader
        title="VerifyGH Pricing FX Rate"
        description="The rate provider costs are converted to cedis at, for pricing. It can sit above the market rate to cover Mobile Money collection, conversion and settlement costs and FX movement. Internal only - never shown to customers as an exchange rate."
      />
      {!usd ? (
        <div className="p-5">
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="space-y-4 p-4 sm:p-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <Info label="Market / reference rate (USD)" value={usd.market_rate ? fxRate(usd.market_rate) : "Not recorded"} hint={usd.market_rate_at ? `${usd.market_rate_source}, ${relativeTime(usd.market_rate_at)}` : "No market feed configured"} />
            <Info label="VerifyGH Pricing FX Rate in use" value={usd.effective_rate ? fxRate(usd.effective_rate) : "Unavailable"} hint={usd.error || `${usd.mode.toLowerCase()}${usd.updated_by ? `, set by ${usd.updated_by}` : ""}`} />
            <Info
              label="Difference from market"
              value={usd.market_rate && usd.effective_rate ? percent(String(((Number.parseFloat(usd.effective_rate) / Number.parseFloat(usd.market_rate)) - 1) * 100)) : "-"}
            />
          </div>

          {canManage ? (
            <div className="space-y-3 rounded-xl border border-line p-3.5">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="FX source" htmlFor="fx-mode">
                  <Select id="fx-mode" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                    <option value="MANUAL">Manual pricing rate</option>
                    <option value="AUTOMATIC">Automatic: market rate + adjustment</option>
                  </Select>
                </Field>
                {mode === "MANUAL" ? (
                  <Field label="Pricing FX rate (GHS per USD)" htmlFor="fx-manual">
                    <Input id="fx-manual" inputMode="decimal" value={manualRate} onChange={(e) => setManualRate(e.target.value)} className="tabular" />
                  </Field>
                ) : (
                  <Field label="Pricing adjustment %" htmlFor="fx-adj" hint="Added on top of the market rate.">
                    <Input id="fx-adj" inputMode="decimal" value={adjustment} onChange={(e) => setAdjustment(e.target.value)} className="tabular" />
                  </Field>
                )}
                <Info label="Effective pricing rate" value={effective ? fxRate(effective) : "-"} />
              </div>
              {mode === "AUTOMATIC" ? (
                <p className="text-xs text-ink-muted">
                  Automatic mode stops pricing if the market rate is more than 36 hours old, rather than price
                  off a stale rate. Manual mode never goes stale.
                </p>
              ) : null}
              <Button onClick={previewChange}>Preview the effect</Button>
            </div>
          ) : null}

          {canManage ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <Field label="Record a market reference rate" htmlFor="fx-market" hint="For reference and automatic mode.">
                <Input id="fx-market" inputMode="decimal" value={marketRate} onChange={(e) => setMarketRate(e.target.value)} className="tabular sm:w-48" />
              </Field>
              <Button variant="secondary" onClick={recordMarket} disabled={!marketRate}>
                Record
              </Button>
            </div>
          ) : null}
        </div>
      )}
      <ImpactConfirm
        impact={impact}
        title="Change the VerifyGH Pricing FX Rate"
        open={impact !== null}
        onCancel={() => setImpact(null)}
        onConfirm={apply}
        busy={busy}
        error={error}
      />
    </Card>
  );
}

function Info({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl bg-canvas px-3.5 py-3">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="tabular mt-0.5 text-lg font-semibold text-ink">{value}</p>
      {hint ? <p className="text-xs text-ink-faint">{hint}</p> : null}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Bulk markup
 * ---------------------------------------------------------------------- */

export function BulkMarkupPanel({ summary }: { summary?: PricingSummary }) {
  const toast = useToast();
  const [scope, setScope] = React.useState({ provider: "", country: "", service: "" });
  const [markupType, setMarkupType] = React.useState("PERCENTAGE");
  const [markupPercent, setMarkupPercent] = React.useState("25");
  const [markupFixed, setMarkupFixed] = React.useState("0");
  const [impact, setImpact] = React.useState<PricingImpact | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const body = {
    scope: Object.fromEntries(Object.entries(scope).filter(([, v]) => v)),
    markup_type: markupType,
    markup_percent: markupPercent || "0",
    markup_fixed: markupFixed || "0",
  };

  async function preview() {
    try {
      setImpact(await api.post<PricingImpact>("/admin/pricing/bulk/", body));
    } catch (caught) {
      toast.error("Cannot preview", caught instanceof ApiError ? caught.message : "Try again.");
    }
  }

  async function apply(reason: string) {
    setBusy(true);
    setError("");
    try {
      await api.post("/admin/pricing/bulk/", { ...body, confirm: true, reason });
      toast.success("Markup applied");
      setImpact(null);
      await refreshPricing();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Bulk markup"
        description="Set one markup for a whole scope - all US services, everything from one provider, or one service everywhere. Leave a field on 'All' to include everything. Nothing changes until you confirm."
      />
      <div className="space-y-3 p-4 sm:p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Provider" htmlFor="bulk-provider">
            <Select id="bulk-provider" value={scope.provider} onChange={(e) => setScope({ ...scope, provider: e.target.value })}>
              <option value="">All providers</option>
              {summary?.providers.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Country" htmlFor="bulk-country">
            <Select id="bulk-country" value={scope.country} onChange={(e) => setScope({ ...scope, country: e.target.value })}>
              <option value="">All countries</option>
              <option value="US">United States</option>
              <option value="CA">Canada</option>
            </Select>
          </Field>
          <Field label="Service (slug)" htmlFor="bulk-service" hint="Optional, e.g. tiktok">
            <Input id="bulk-service" value={scope.service} onChange={(e) => setScope({ ...scope, service: e.target.value.trim().toLowerCase() })} />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Markup type" htmlFor="bulk-type">
            <Select id="bulk-type" value={markupType} onChange={(e) => setMarkupType(e.target.value)}>
              <option value="PERCENTAGE">Percentage</option>
              <option value="FIXED">Fixed (cedis)</option>
              <option value="HYBRID">Percentage + fixed</option>
            </Select>
          </Field>
          {markupType !== "FIXED" ? (
            <Field label="Markup %" htmlFor="bulk-pct">
              <Input id="bulk-pct" inputMode="decimal" value={markupPercent} onChange={(e) => setMarkupPercent(e.target.value)} className="tabular" />
            </Field>
          ) : null}
          {markupType !== "PERCENTAGE" ? (
            <Field label="Fixed markup (₵)" htmlFor="bulk-fixed">
              <Input id="bulk-fixed" inputMode="decimal" value={markupFixed} onChange={(e) => setMarkupFixed(e.target.value)} className="tabular" />
            </Field>
          ) : null}
        </div>
        <Button onClick={preview}>Preview</Button>
      </div>
      <ImpactConfirm
        impact={impact}
        title="Apply bulk markup"
        open={impact !== null}
        onCancel={() => setImpact(null)}
        onConfirm={apply}
        busy={busy}
        error={error}
      />
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Review and publish
 * ---------------------------------------------------------------------- */

export function ReviewPanel({ summary, canManage }: { summary?: PricingSummary; canManage: boolean }) {
  const toast = useToast();
  const { data, mutate } = useSWR<Paginated<PricingRow>>(["/admin/pricing/offerings/", { status: "pending", page_size: "200" }]);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const rows = data?.results ?? [];

  async function publish() {
    setBusy(true);
    try {
      const result = await api.post<{ published: number }>("/admin/pricing/publish/", { reason });
      toast.success(`${result.published} prices published`);
      setReason("");
      await mutate();
      await refreshPricing();
    } catch (caught) {
      toast.error("Could not publish", caught instanceof ApiError ? caught.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Awaiting review"
        description={
          summary?.policy.auto_publish_prices
            ? "Prices currently publish automatically, so nothing waits here. Turn automatic publishing off in Settings to review provider-cost and FX changes before customers see them."
            : "Provider cost, FX and markup changes land here as recommendations. Customers keep paying the published price until you publish."
        }
      />
      {rows.length === 0 ? (
        <p className="px-5 pb-5 text-sm text-ink-muted">Nothing awaiting review.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="border-y border-line bg-canvas text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Service</th>
                  <th className="px-3 py-2 text-right font-medium">Published</th>
                  <th className="px-3 py-2 text-right font-medium">Recommended</th>
                  <th className="px-3 py-2 text-right font-medium">Gross margin after</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td className="px-4 py-2 text-ink">
                      {row.service.name} <span className="text-xs text-ink-muted">{row.country.code}</span>
                    </td>
                    <td className="tabular px-3 py-2 text-right">{row.customer_price ? cedis(row.customer_price) : "not sold"}</td>
                    <td className="tabular px-3 py-2 text-right font-semibold">{row.recommended_price ? cedis(row.recommended_price) : "-"}</td>
                    <td className="tabular px-3 py-2 text-right">{percent(row.gross_margin_percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {canManage ? (
            <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-end sm:p-5">
              <Field label="Reason" htmlFor="publish-reason" required className="flex-1">
                <Input id="publish-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Reviewed OnlineSim price change" />
              </Field>
              <Button onClick={publish} loading={busy} disabled={reason.trim().length < 5}>
                Publish {rows.length} prices
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

/* -------------------------------------------------------------------------
 * Settings
 * ---------------------------------------------------------------------- */

export function PolicyPanel({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data, mutate } = useSWR<PricingPolicyData>("/admin/pricing/policy/");
  const [form, setForm] = React.useState({ minimum_margin_percent: "10", enforce_minimum_margin: false, auto_publish_prices: true });
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (data) {
      setForm({
        minimum_margin_percent: data.minimum_margin_percent,
        enforce_minimum_margin: data.enforce_minimum_margin,
        auto_publish_prices: data.auto_publish_prices,
      });
    }
  }, [data]);

  async function save() {
    setBusy(true);
    try {
      await api.put("/admin/pricing/policy/", { ...form, reason });
      toast.success("Pricing settings saved");
      setReason("");
      await mutate();
      await refreshPricing();
    } catch (caught) {
      toast.error("Could not save", caught instanceof ApiError ? caught.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Pricing settings" description="Business-wide rules the pricing engine applies to every price." />
      <div className="space-y-4 p-4 sm:p-5">
        <Field label="Minimum gross margin %" htmlFor="policy-min" hint="Prices below this are flagged.">
          <Input id="policy-min" inputMode="decimal" disabled={!canManage} value={form.minimum_margin_percent} onChange={(e) => setForm({ ...form, minimum_margin_percent: e.target.value })} className="tabular sm:w-40" />
        </Field>
        <Check
          label="Enforce minimum margin"
          description="Refuse to save any price, markup or FX change that would put a price below the minimum, instead of only warning."
          checked={form.enforce_minimum_margin}
          disabled={!canManage}
          onChange={(value) => setForm({ ...form, enforce_minimum_margin: value })}
        />
        <Check
          label="Automatically update customer prices"
          description="On: provider cost, FX and markup changes reach customers straight away. Off: they become recommendations you review and publish. Manual overrides always apply straight away."
          checked={form.auto_publish_prices}
          disabled={!canManage}
          onChange={(value) => setForm({ ...form, auto_publish_prices: value })}
        />
        <Alert tone="info" title="Always on">
          Loss prevention: a price below the provider cost in cedis is never charged unless a finance
          administrator approves that specific loss-making override.
        </Alert>
        {canManage ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <Field label="Reason" htmlFor="policy-reason" required className="flex-1">
              <Input id="policy-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button onClick={save} loading={busy} disabled={reason.trim().length < 5}>
              Save settings
            </Button>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function Check({
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className={cn("flex items-start gap-3", disabled ? "cursor-not-allowed opacity-70" : "cursor-pointer")}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 h-5 w-5 rounded border-line-strong text-brand-600" />
      <span>
        <span className="block text-sm font-medium text-ink">{label}</span>
        <span className="block text-xs text-ink-muted">{description}</span>
      </span>
    </label>
  );
}

/* -------------------------------------------------------------------------
 * History and audit
 * ---------------------------------------------------------------------- */

export function CostHistoryCard() {
  const [page, setPage] = React.useState(1);
  const { data } = useSWR<Paginated<ProviderCostChangeRow>>(["/admin/pricing/cost-history/", { page, page_size: 25 }]);
  return (
    <Card>
      <CardHeader title="Provider cost history" description="Every change to what a provider charges us, from its API or entered by staff." />
      <HistoryTable
        rows={(data?.results ?? []).map((c) => ({
          id: c.id,
          at: c.created_at,
          what: `${c.service_name} ${c.country_code} (${c.provider_key})`,
          change: `${c.old_cost ? providerMoney(c.old_cost, c.currency) : "-"} -> ${providerMoney(c.new_cost, c.currency)}`,
          who: c.changed_by_email ?? (c.source === "PROVIDER_API" ? "Provider API" : ""),
          why: `${c.sync_method.replace("_", " ").toLowerCase()}${c.reason ? `: ${c.reason}` : ""}`,
        }))}
        loading={!data}
      />
      {data?.pagination ? (
        <div className="px-4 py-3 sm:px-5">
          <Pagination page={data.pagination.page} pages={data.pagination.pages} count={data.pagination.count} hasNext={data.pagination.has_next} hasPrevious={data.pagination.has_previous} onChange={setPage} noun="changes" />
        </div>
      ) : null}
    </Card>
  );
}

const ACTION_LABELS: Record<string, string> = {
  PRICING_FX_UPDATE: "Pricing FX rate",
  PRICING_POLICY_UPDATE: "Pricing settings",
  PRICING_OVERRIDE_SET: "Price override set",
  PRICING_OVERRIDE_REMOVE: "Price override removed",
  PRICING_COST_MANUAL: "Provider cost entered",
  PRICING_MARKUP_UPDATE: "Markup",
  PRICING_PUBLISH: "Prices published",
  PRICING_RULE_CREATE: "Pricing rule created",
  PRICING_RULE_UPDATE: "Pricing rule changed",
  PRICING_RULE_DELETE: "Pricing rule removed",
  EXCHANGE_RATE_SET: "Market reference rate",
};

export function PricingAuditCard() {
  const [page, setPage] = React.useState(1);
  const { data } = useSWR<Paginated<PricingAuditRow>>(["/admin/pricing/audit/", { page, page_size: 25 }]);
  return (
    <Card>
      <CardHeader title="Pricing audit log" description="Every pricing change: who, when, what changed from and to, and why." />
      <HistoryTable
        rows={(data?.results ?? []).map((a) => ({
          id: a.id,
          at: a.created_at,
          what: `${ACTION_LABELS[a.action] ?? a.action}${a.after?.service ? ` - ${String(a.after.service)} ${String(a.after.country ?? "")}` : a.after?.scope ? ` - ${String(a.after.scope)}` : ""}`,
          change: diff(a.before, a.after),
          who: a.admin_email ?? "",
          why: a.reason,
        }))}
        loading={!data}
      />
      {data?.pagination ? (
        <div className="px-4 py-3 sm:px-5">
          <Pagination page={data.pagination.page} pages={data.pagination.pages} count={data.pagination.count} hasNext={data.pagination.has_next} hasPrevious={data.pagination.has_previous} onChange={setPage} noun="entries" />
        </div>
      ) : null}
    </Card>
  );
}

function diff(before: Record<string, unknown>, after: Record<string, unknown>) {
  const skip = new Set(["service", "country", "provider", "scope", "currency"]);
  const keys = Object.keys(after ?? {}).filter((key) => !skip.has(key));
  const parts = keys
    .filter((key) => JSON.stringify(before?.[key]) !== JSON.stringify(after[key]))
    .map((key) => `${key.replace(/_/g, " ")}: ${before && key in before ? String(before[key]) : "-"} -> ${String(after[key])}`);
  return parts.join("; ") || "-";
}

function HistoryTable({
  rows,
  loading,
}: {
  rows: { id: string; at: string; what: string; change: string; who: string; why: string }[];
  loading: boolean;
}) {
  if (loading) return <Skeleton className="m-5 h-24" />;
  if (rows.length === 0) return <p className="px-5 pb-5 text-sm text-ink-muted">Nothing recorded yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[52rem] text-left text-sm">
        <thead className="border-y border-line bg-canvas text-xs uppercase tracking-wide text-ink-muted">
          <tr>
            <th className="px-4 py-2 font-medium">When</th>
            <th className="px-3 py-2 font-medium">What</th>
            <th className="px-3 py-2 font-medium">Change</th>
            <th className="px-3 py-2 font-medium">Who / why</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="whitespace-nowrap px-4 py-2 text-xs text-ink-muted" title={formatDateTime(row.at)}>
                {relativeTime(row.at)}
              </td>
              <td className="px-3 py-2 text-ink">{row.what}</td>
              <td className="tabular max-w-[22rem] px-3 py-2 text-xs text-ink-soft">{row.change}</td>
              <td className="max-w-[18rem] px-3 py-2 text-xs text-ink-muted">
                <span className="block text-ink-soft">{row.who}</span>
                <span className="block">{row.why}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
