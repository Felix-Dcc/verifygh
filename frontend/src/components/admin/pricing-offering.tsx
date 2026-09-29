"use client";

import * as React from "react";
import useSWR from "swr";

import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Field,
  Input,
  SegmentedControl,
  Select,
  Skeleton,
  Textarea,
  cn,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { cedis, formatDateTime } from "@/lib/format";
import type { PriceQuote, PricingOfferingDetail, PricingPreview } from "@/lib/types";

/* -------------------------------------------------------------------------
 * Formatting shared by the pricing screens
 * ---------------------------------------------------------------------- */

export function providerMoney(value: string | null | undefined, currency = "USD") {
  if (value === null || value === undefined) return "Not synced";
  const amount = Number.parseFloat(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
  return currency === "USD" ? `$${amount}` : `${currency} ${amount}`;
}

export function fxRate(value: string | null | undefined) {
  if (!value) return "-";
  return Number.parseFloat(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export function percent(value: string | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${Number.parseFloat(value).toFixed(2)}%`;
}

const COST_SOURCE: Record<string, string> = {
  PROVIDER_API: "Provider API",
  MANUAL: "Entered by staff",
  NOT_SYNCED: "Not synced",
};

const FX_MODE: Record<string, string> = {
  MANUAL: "manual pricing rate",
  AUTOMATIC: "market rate + adjustment",
  MARKET: "market rate",
  PREVIEW: "proposed",
};

/* -------------------------------------------------------------------------
 * The step-by-step breakdown
 * ---------------------------------------------------------------------- */

export function PriceBreakdown({ quote, title }: { quote: PriceQuote; title?: string }) {
  const applied = quote.applied;
  const fee = Number.parseFloat(quote.payment_fee);
  const buffer = Number.parseFloat(quote.risk_buffer);
  return (
    <div className="rounded-xl border border-line">
      {title ? (
        <p className="border-b border-line px-3.5 py-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
          {title}
        </p>
      ) : null}
      <dl className="divide-y divide-line text-sm">
        <Step label="Provider cost" hint={COST_SOURCE[quote.cost_source] ?? quote.cost_source}>
          {providerMoney(quote.provider_cost, quote.provider_currency)}
        </Step>
        <Step
          label="VerifyGH Pricing FX Rate"
          hint={
            quote.market_rate && quote.fx_mode !== "MARKET"
              ? `${FX_MODE[quote.fx_mode] ?? quote.fx_mode}; market ${fxRate(quote.market_rate)}`
              : FX_MODE[quote.fx_mode] ?? quote.fx_mode
          }
        >
          {fxRate(quote.exchange_rate)}
        </Step>
        <Step label="Provider cost in cedis">{cedis(quote.base_cost)}</Step>
        <Step
          label="Markup"
          hint={`${applied.markup_type === "FIXED" ? `fixed ${cedis(String(applied.markup_fixed))}` : applied.markup_type === "HYBRID" ? `${applied.markup_percent}% + ${cedis(String(applied.markup_fixed))}` : `${applied.markup_percent}%`} - ${quote.pricing_rule_name}`}
        >
          + {cedis(quote.markup)}
        </Step>
        {fee > 0 ? (
          <Step label="Collection fee" hint={`${applied.payment_fee_percent}%`}>
            + {cedis(quote.payment_fee)}
          </Step>
        ) : null}
        {buffer > 0 ? (
          <Step label="Risk buffer" hint={`${applied.risk_buffer_percent}%`}>
            + {cedis(quote.risk_buffer)}
          </Step>
        ) : null}
        <Step
          label="Calculated price"
          hint={`rounding ${String(applied.rounding).replace(/_/g, " ").toLowerCase()}, bounds ${cedis(String(applied.min_price))}-${cedis(String(applied.max_price))}`}
          strong
        >
          {cedis(quote.calculated_price)}
        </Step>
        {quote.override_price ? (
          <Step label="Manual override" hint={quote.override_reason} tone="warn">
            {cedis(quote.override_price)}
          </Step>
        ) : null}
        {quote.pending_review ? (
          <Step label="Recommended (awaiting review)" tone="info">
            {cedis(quote.recommended_price)}
          </Step>
        ) : null}
        <Step label="Customer price" strong tone="brand">
          {cedis(quote.customer_price)}
        </Step>
        <Step label="Gross profit" hint="customer price - provider cost in cedis">
          <span className={quote.is_loss ? "text-danger-700" : "text-success-700"}>
            {cedis(quote.gross_profit)}
          </span>
        </Step>
        <Step label="Markup %" hint="gross profit / provider cost">
          {percent(quote.markup_percent_effective)}
        </Step>
        <Step label="Gross margin %" hint="gross profit / customer price">
          <span className={quote.below_minimum_margin ? "text-warn-700" : undefined}>
            {percent(quote.gross_margin_percent)}
          </span>
        </Step>
      </dl>
    </div>
  );
}

function Step({
  label,
  hint,
  children,
  strong,
  tone,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  strong?: boolean;
  tone?: "warn" | "info" | "brand";
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 px-3.5 py-2",
        tone === "warn" && "bg-warn-50",
        tone === "info" && "bg-info-50",
        tone === "brand" && "bg-brand-50",
      )}
    >
      <dt className="min-w-0">
        <span className={cn("block text-ink-soft", strong && "font-medium text-ink")}>{label}</span>
        {hint ? <span className="block truncate text-xs text-ink-faint">{hint}</span> : null}
      </dt>
      <dd className={cn("tabular shrink-0 text-right text-ink", strong && "font-semibold")}>{children}</dd>
    </div>
  );
}

export function PriceWarnings({ quote, warnings = [] }: { quote?: PriceQuote | null; warnings?: string[] }) {
  const loss = warnings.includes("LOSS_MAKING") || quote?.is_loss;
  const thin = warnings.includes("BELOW_MINIMUM_MARGIN") || quote?.below_minimum_margin;
  if (!loss && !thin) return null;
  return (
    <div className="space-y-2">
      {loss ? (
        <Alert tone="danger" title="Loss-making price">
          The customer would pay less than this number costs us. It is not sold unless a finance
          administrator approves the loss.
        </Alert>
      ) : null}
      {thin ? (
        <Alert tone="warn" title="Below minimum margin">
          Gross margin is under the {quote?.minimum_margin_percent ?? ""}% minimum set in pricing
          settings.
        </Alert>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * The dialog
 * ---------------------------------------------------------------------- */

type EditMode = "markup" | "override" | "cost";

export function OfferingPricingDialog({
  offeringId,
  onClose,
  onChanged,
  canManage,
  canApproveLoss,
}: {
  offeringId: string | null;
  onClose: () => void;
  onChanged: () => void;
  canManage: boolean;
  canApproveLoss: boolean;
}) {
  const { data, mutate } = useSWR<PricingOfferingDetail>(
    offeringId ? `/admin/pricing/offerings/${offeringId}/` : null,
  );
  const [editing, setEditing] = React.useState(false);

  React.useEffect(() => setEditing(false), [offeringId]);

  if (!offeringId) return null;
  const row = data?.row;
  const quote = data?.published ?? data?.recommended ?? null;

  return (
    <Dialog
      open
      onClose={onClose}
      title={row ? `${row.service.name} | ${row.country.code} | ${row.provider.name}` : "Pricing"}
      description={row ? `${row.country.flag} ${row.country.name}` : undefined}
      size="lg"
    >
      {!data || !row ? (
        <div className="space-y-2">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <ServiceLogo name={row.service.name} src={row.service.icon_url} slug={row.service.slug} size="md" />
            <StatusBadges row={row} />
          </div>

          {row.status === "NOT_SYNCED" ? (
            <Alert tone="warn" title="Provider cost: not synced">
              We do not know what this number costs, so it is not sold.
              {data.cost_editable ? " Enter the provider's price below if you have it." : ""}
            </Alert>
          ) : null}
          {!data.published && data.recommended ? (
            <Alert tone="danger" title="Not sold at the current price">
              The published price no longer covers the provider cost, or a rule allows no price
              above cost. Review and publish, or adjust the pricing.
            </Alert>
          ) : null}

          {quote ? (
            <>
              <PriceWarnings quote={quote} />
              <PriceBreakdown quote={quote} />
            </>
          ) : null}

          {canManage && !editing ? (
            <Button onClick={() => setEditing(true)}>Edit pricing</Button>
          ) : null}
          {editing ? (
            <PricingEditor
              detail={data}
              canApproveLoss={canApproveLoss}
              onCancel={() => setEditing(false)}
              onSaved={async () => {
                setEditing(false);
                await mutate();
                onChanged();
              }}
            />
          ) : null}

          <Comparison detail={data} />
          <History detail={data} />
        </div>
      )}
    </Dialog>
  );
}

export function StatusBadges({ row }: { row: PricingOfferingDetail["row"] }) {
  const tones: Record<string, "success" | "neutral" | "warn" | "danger"> = {
    ACTIVE: "success",
    INACTIVE: "neutral",
    OUT_OF_STOCK: "warn",
    NOT_SOLD: "danger",
    NOT_SYNCED: "warn",
  };
  const labels: Record<string, string> = {
    ACTIVE: "Active",
    INACTIVE: "Inactive",
    OUT_OF_STOCK: "Out of stock",
    NOT_SOLD: "Not sold",
    NOT_SYNCED: "Cost not synced",
  };
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge tone={tones[row.status]} dot>
        {labels[row.status]}
      </Badge>
      {row.override_price ? <Badge tone="warn">Override</Badge> : null}
      {row.price_review_pending ? <Badge tone="info">Awaiting review</Badge> : null}
      {row.below_minimum_margin ? <Badge tone="warn">Below min. margin</Badge> : null}
      {row.is_loss ? <Badge tone="danger">Loss</Badge> : null}
      {row.provider.demo ? <Badge tone="neutral">Demo provider</Badge> : null}
    </span>
  );
}

function PricingEditor({
  detail,
  canApproveLoss,
  onCancel,
  onSaved,
}: {
  detail: PricingOfferingDetail;
  canApproveLoss: boolean;
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const toast = useToast();
  const row = detail.row;
  const active = detail.overrides.find((o) => o.is_active);
  const [mode, setMode] = React.useState<EditMode>("markup");
  const [markupType, setMarkupType] = React.useState(detail.rule?.markup_type ?? "PERCENTAGE");
  const [markupPercent, setMarkupPercent] = React.useState(detail.rule?.markup_percent ?? "0");
  const [markupFixed, setMarkupFixed] = React.useState(detail.rule?.markup_fixed ?? "0");
  const [scope, setScope] = React.useState<"service_country" | "service">("service_country");
  const [overridePrice, setOverridePrice] = React.useState(active?.price ?? "");
  const [allowLoss, setAllowLoss] = React.useState(false);
  const [cost, setCost] = React.useState(row.provider_cost ?? "");
  const [reason, setReason] = React.useState("");
  const [preview, setPreview] = React.useState<PricingPreview | null>(null);
  const [previewError, setPreviewError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  // Live preview: the server prices the proposal with the same engine that
  // prices orders, so what is shown here is exactly what would be charged.
  React.useEffect(() => {
    const body: Record<string, unknown> = { offering_id: row.id };
    if (mode === "markup") {
      Object.assign(body, { markup_type: markupType, markup_percent: markupPercent || "0", markup_fixed: markupFixed || "0" });
    } else if (mode === "override") {
      Object.assign(body, { override_price: overridePrice, allow_loss: allowLoss });
    } else if (cost) {
      body.provider_cost = cost;
    }
    const timer = window.setTimeout(async () => {
      try {
        setPreview(await api.post<PricingPreview>("/admin/pricing/preview/", body));
        setPreviewError("");
      } catch (caught) {
        setPreview(null);
        setPreviewError(caught instanceof ApiError ? caught.message : "Could not preview.");
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [row.id, mode, markupType, markupPercent, markupFixed, overridePrice, allowLoss, cost]);

  async function save(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    try {
      await action();
      toast.success(message);
      await onSaved();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const base = `/admin/pricing/offerings/${row.id}`;
  const blocked =
    preview?.enforce_minimum_margin && preview.warnings.includes("BELOW_MINIMUM_MARGIN") && !allowLoss;

  return (
    <div className="space-y-4 rounded-xl border border-brand-200 bg-brand-50/40 p-3.5">
      <SegmentedControl
        options={[
          { value: "markup" as EditMode, label: "Markup" },
          { value: "override" as EditMode, label: "Override price" },
          { value: "cost" as EditMode, label: "Provider cost" },
        ]}
        value={mode}
        onChange={(value) => {
          setMode(value);
          setError("");
        }}
      />

      {mode === "markup" ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Markup type" htmlFor="pe-type">
            <Select id="pe-type" value={markupType} onChange={(e) => setMarkupType(e.target.value as typeof markupType)}>
              <option value="PERCENTAGE">Percentage</option>
              <option value="FIXED">Fixed (cedis)</option>
              <option value="HYBRID">Percentage + fixed</option>
            </Select>
          </Field>
          {markupType !== "FIXED" ? (
            <Field label="Markup %" htmlFor="pe-pct">
              <Input id="pe-pct" inputMode="decimal" value={markupPercent} onChange={(e) => setMarkupPercent(e.target.value)} className="tabular" />
            </Field>
          ) : null}
          {markupType !== "PERCENTAGE" ? (
            <Field label="Fixed markup (₵)" htmlFor="pe-fixed">
              <Input id="pe-fixed" inputMode="decimal" value={markupFixed} onChange={(e) => setMarkupFixed(e.target.value)} className="tabular" />
            </Field>
          ) : null}
          <Field label="Applies to" htmlFor="pe-scope" className="sm:col-span-3">
            <Select id="pe-scope" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
              <option value="service_country">
                {row.service.name} in {row.country.name} only
              </option>
              <option value="service">{row.service.name} in every country</option>
            </Select>
          </Field>
        </div>
      ) : null}

      {mode === "override" ? (
        <div className="space-y-3">
          <Field
            label="Final customer price (₵)"
            htmlFor="pe-override"
            hint="Replaces the calculated price for this service and country. The calculated price stays visible."
          >
            <Input id="pe-override" inputMode="decimal" value={overridePrice} onChange={(e) => setOverridePrice(e.target.value)} className="tabular" />
          </Field>
          {canApproveLoss ? (
            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-danger-200 bg-danger-50 p-3">
              <input type="checkbox" checked={allowLoss} onChange={(e) => setAllowLoss(e.target.checked)} className="mt-0.5 h-5 w-5 rounded" />
              <span className="text-sm text-danger-700">
                Allow a loss-making price. Only for a deliberate promotion.
              </span>
            </label>
          ) : null}
        </div>
      ) : null}

      {mode === "cost" ? (
        detail.cost_editable ? (
          <Field
            label={`Provider cost (${row.currency})`}
            htmlFor="pe-cost"
            hint="Only for providers that do not report prices through their API."
          >
            <Input id="pe-cost" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} className="tabular" />
          </Field>
        ) : (
          <Alert tone="info" title="Reported by the provider">
            {row.provider.name} reports this cost through its API. It is refreshed on every catalogue
            sync, so it cannot be typed in - a manual value would be overwritten within hours.
          </Alert>
        )
      ) : null}

      {previewError ? <Alert tone="danger">{previewError}</Alert> : null}
      {preview ? (
        <>
          <PriceWarnings quote={preview.quote} warnings={preview.warnings} />
          <PriceBreakdown quote={preview.quote} title="Preview - not saved" />
        </>
      ) : null}
      {blocked ? (
        <Alert tone="danger" title="Minimum margin is enforced">
          This price cannot be saved while the pricing policy enforces the minimum margin.
        </Alert>
      ) : null}

      <Field label="Reason" htmlFor="pe-reason" required hint="Required. Recorded with the change in the audit log.">
        <Textarea id="pe-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Provider cost increase" />
      </Field>
      {error ? <Alert tone="danger">{error}</Alert> : null}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        {mode === "override" && active ? (
          <Button
            variant="secondary"
            disabled={busy || reason.trim().length < 5}
            onClick={() => save(() => api.delete(`${base}/override/`, { reason }), "Override removed")}
          >
            Remove override
          </Button>
        ) : null}
        <Button
          loading={busy}
          disabled={
            reason.trim().length < 5 ||
            Boolean(blocked) ||
            (mode === "override" && !overridePrice) ||
            (mode === "cost" && (!detail.cost_editable || !cost))
          }
          onClick={() =>
            save(
              () =>
                mode === "markup"
                  ? api.post(`${base}/markup/`, {
                      markup_type: markupType,
                      markup_percent: markupPercent || "0",
                      markup_fixed: markupFixed || "0",
                      scope: scope === "service" ? "service" : "service_country",
                      reason,
                    })
                  : mode === "override"
                    ? api.post(`${base}/override/`, { price: overridePrice, allow_loss: allowLoss, reason })
                    : api.post(`${base}/cost/`, { cost, currency: row.currency, reason }),
              "Pricing saved",
            )
          }
        >
          Save changes
        </Button>
      </div>
    </div>
  );
}

function Comparison({ detail }: { detail: PricingOfferingDetail }) {
  const comparison = detail.provider_comparison;
  return (
    <div>
      <p className="mb-1.5 text-sm font-semibold text-ink">Provider comparison</p>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-ink-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Provider</th>
              <th className="px-3 py-2 text-right font-medium">Cost</th>
              <th className="px-3 py-2 text-right font-medium">In cedis</th>
              <th className="px-3 py-2 font-medium">Stock</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {comparison.providers.map((p) => (
              <tr key={p.provider_key} className={p.this ? "bg-brand-50/50" : undefined}>
                <td className="px-3 py-2 text-ink">
                  {p.provider} {p.this ? <span className="text-xs text-ink-muted">(this)</span> : null}
                </td>
                <td className="tabular px-3 py-2 text-right">{providerMoney(p.cost, p.currency)}</td>
                <td className="tabular px-3 py-2 text-right">{p.ghs_cost ? cedis(p.ghs_cost) : "-"}</td>
                <td className="px-3 py-2 text-xs text-ink-muted">
                  {!p.enabled ? "disabled" : p.available ? "in stock" : "out of stock"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-xs text-ink-muted">
        Lowest available provider cost: {comparison.lowest_available_ghs_cost ? cedis(comparison.lowest_available_ghs_cost) : "-"}.{" "}
        {comparison.routing}
      </p>
    </div>
  );
}

function History({ detail }: { detail: PricingOfferingDetail }) {
  const [tab, setTab] = React.useState<"price" | "cost" | "override">("price");
  const items =
    tab === "price"
      ? detail.price_history.map((h) => ({
          at: h.at,
          text: `${h.old ? cedis(h.old) : "-"} -> ${cedis(h.new)}`,
          meta: `${h.source}${h.by ? ` - ${h.by}` : ""}${h.reason ? `: ${h.reason}` : ""}`,
        }))
      : tab === "cost"
        ? detail.cost_history.map((h) => ({
            at: h.at,
            text: `${h.old ? providerMoney(h.old, h.currency) : "-"} -> ${providerMoney(h.new, h.currency)}`,
            meta: `${COST_SOURCE[h.source] ?? h.source} (${h.sync_method.replace("_", " ").toLowerCase()})${h.by ? ` - ${h.by}` : ""}${h.reason ? `: ${h.reason}` : ""}`,
          }))
        : detail.overrides.map((o) => ({
            at: o.created_at,
            text: `${cedis(o.price)}${o.is_active ? " (active)" : ""}${o.allow_loss ? " - loss approved" : ""}`,
            meta: `${o.created_by ?? ""}: ${o.reason}${o.ended_at ? ` - ended ${formatDateTime(o.ended_at)}${o.end_reason ? `: ${o.end_reason}` : ""}` : ""}`,
          }));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-ink">History</p>
        <SegmentedControl
          options={[
            { value: "price" as const, label: "Price" },
            { value: "cost" as const, label: "Provider cost" },
            { value: "override" as const, label: "Overrides" },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-ink-muted">Nothing recorded yet.</p>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line text-sm">
          {items.map((item, index) => (
            <li key={index} className="flex items-start justify-between gap-3 px-3 py-2">
              <span className="min-w-0">
                <span className="tabular block text-ink">{item.text}</span>
                <span className="block text-xs text-ink-muted">{item.meta}</span>
              </span>
              <span className="shrink-0 text-xs text-ink-faint">{formatDateTime(item.at)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
