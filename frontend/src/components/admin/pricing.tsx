"use client";

import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { Pagination } from "@/components/admin/pagination";
import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
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
  AdminCountry,
  AdminOffering,
  AdminService,
  Paginated,
  PriceChange,
  PricingRule,
} from "@/lib/types";

/* -------------------------------------------------------------------------
 * Pricing rules
 * ---------------------------------------------------------------------- */

type RuleForm = {
  name: string;
  service: string;
  country: string;
  markup_type: PricingRule["markup_type"];
  markup_percent: string;
  markup_fixed: string;
  payment_fee_percent: string;
  risk_buffer_percent: string;
  rounding: string;
  min_price: string;
  max_price: string;
  allow_below_cost: boolean;
  is_active: boolean;
  reason: string;
};

const ROUNDING = [
  ["NONE", "No rounding"],
  ["NEAREST_0_10", "Nearest 0.10"],
  ["NEAREST_0_50", "Nearest 0.50"],
  ["NEAREST_1_00", "Nearest 1.00"],
  ["CEIL_1_00", "Round up to 1.00"],
] as const;

function toForm(rule: PricingRule | null): RuleForm {
  return {
    name: rule?.name ?? "",
    service: rule?.service ?? "",
    country: rule?.country ?? "",
    markup_type: rule?.markup_type ?? "PERCENTAGE",
    markup_percent: rule?.markup_percent ?? "30.00",
    markup_fixed: rule?.markup_fixed ?? "0.00",
    payment_fee_percent: rule?.payment_fee_percent ?? "1.95",
    risk_buffer_percent: rule?.risk_buffer_percent ?? "0.00",
    rounding: rule?.rounding ?? "NEAREST_0_50",
    min_price: rule?.min_price ?? "2.00",
    max_price: rule?.max_price ?? "500.00",
    allow_below_cost: rule?.allow_below_cost ?? false,
    is_active: rule?.is_active ?? true,
    reason: "",
  };
}

export function PricingRulesCard() {
  const { data: rules, mutate } = useSWR<PricingRule[]>("/admin/pricing-rules/");
  const [editing, setEditing] = React.useState<PricingRule | "new" | null>(null);

  return (
    <Card>
      <CardHeader
        title="Pricing rules"
        description="The most specific rule wins: one naming a service, a country and a provider beats one naming fewer. Every change needs a reason and is written to price history."
        action={
          <Button size="sm" onClick={() => setEditing("new")}>
            New rule
          </Button>
        }
      />
      {!rules ? (
        <div className="space-y-2 p-5">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[50rem] text-left text-sm">
            <thead className="border-y border-line bg-canvas">
              <tr className="text-xs uppercase tracking-wide text-ink-muted">
                <th scope="col" className="px-5 py-3 font-medium">Rule</th>
                <th scope="col" className="px-5 py-3 font-medium">Applies to</th>
                <th scope="col" className="px-5 py-3 font-medium">Margin</th>
                <th scope="col" className="px-5 py-3 font-medium">Fees</th>
                <th scope="col" className="px-5 py-3 font-medium">Bounds</th>
                <th scope="col" className="px-5 py-3 font-medium">Status</th>
                <th scope="col" className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rules.map((rule) => (
                <tr key={rule.id} className="transition-colors hover:bg-canvas">
                  <td className="px-5 py-3 font-medium text-ink">{rule.name}</td>
                  <td className="px-5 py-3 text-ink-soft">
                    {rule.service || rule.country || rule.provider ? (
                      [rule.service_name ?? "any service", rule.country_code, rule.provider_key]
                        .filter(Boolean)
                        .join(" / ")
                    ) : (
                      <Badge tone="brand">Global default</Badge>
                    )}
                  </td>
                  <td className="tabular px-5 py-3 text-ink-soft">
                    {rule.markup_type === "FIXED"
                      ? `+ ${cedis(rule.markup_fixed)}`
                      : rule.markup_type === "HYBRID"
                        ? `${rule.markup_percent}% + ${cedis(rule.markup_fixed)}`
                        : `${rule.markup_percent}%`}
                  </td>
                  <td className="tabular px-5 py-3 text-ink-muted">
                    {rule.payment_fee_percent}% fee, {rule.risk_buffer_percent}% buffer
                  </td>
                  <td className="tabular px-5 py-3 text-ink-muted">
                    {cedis(rule.min_price)} - {cedis(rule.max_price)}
                    {rule.allow_below_cost ? (
                      <Badge tone="danger" className="ml-2">
                        Below cost allowed
                      </Badge>
                    ) : null}
                  </td>
                  <td className="px-5 py-3">
                    {rule.is_active ? (
                      <Badge tone="success" dot>
                        Active
                      </Badge>
                    ) : (
                      <Badge tone="neutral">Inactive</Badge>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <Button size="sm" variant="secondary" onClick={() => setEditing(rule)}>
                      Edit
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <RuleEditor
        rule={editing === "new" ? null : editing}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          await mutate();
          await globalMutate((key) => {
            const path = Array.isArray(key) ? String(key[0]) : String(key);
            return path.startsWith("/admin/offerings") || path.startsWith("/admin/price-changes");
          });
        }}
      />
    </Card>
  );
}

function RuleEditor({
  rule,
  open,
  onClose,
  onSaved,
}: {
  rule: PricingRule | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const toast = useToast();
  const { data: services } = useSWR<AdminService[]>(open ? "/admin/services/" : null);
  const { data: countries } = useSWR<AdminCountry[]>(open ? "/admin/countries/" : null);
  const [form, setForm] = React.useState<RuleForm>(toForm(rule));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setForm(toForm(rule));
      setError("");
    }
  }, [open, rule]);

  const isGlobal = rule !== null && !rule.service && !rule.country && !rule.provider;
  const set = <K extends keyof RuleForm>(key: K, value: RuleForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const body = {
      ...form,
      service: form.service || null,
      country: form.country || null,
    };
    try {
      if (rule) await api.patch(`/admin/pricing-rules/${rule.id}/`, body);
      else await api.post("/admin/pricing-rules/", body);
      toast.success(rule ? "Rule updated" : "Rule created", "Prices recalculated.");
      await onSaved();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const sellable = (countries ?? []).filter((c) => ["US", "CA"].includes(c.code));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={rule ? `Edit ${rule.name}` : "New pricing rule"}
      description="Customer price = provider cost in cedis + margin + fees, rounded, kept within bounds, and never below cost."
      dismissible={!busy}
    >
      <form onSubmit={save} className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}

        <Field label="Name" htmlFor="rule-name" required>
          <Input id="rule-name" required value={form.name} onChange={(e) => set("name", e.target.value)} />
        </Field>

        {isGlobal ? (
          <p className="rounded-xl bg-canvas px-3.5 py-2.5 text-xs text-ink-muted">
            This is the global default: it prices everything no narrower rule covers.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Service" htmlFor="rule-service">
              <Select id="rule-service" value={form.service} onChange={(e) => set("service", e.target.value)}>
                <option value="">Any service</option>
                {services?.map((service) => (
                  <option key={service.id} value={service.id}>
                    {service.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Country" htmlFor="rule-country">
              <Select id="rule-country" value={form.country} onChange={(e) => set("country", e.target.value)}>
                <option value="">Any country</option>
                {sellable.map((country) => (
                  <option key={country.id} value={country.id}>
                    {country.flag_emoji} {country.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Margin type" htmlFor="rule-type">
            <Select
              id="rule-type"
              value={form.markup_type}
              onChange={(e) => set("markup_type", e.target.value as RuleForm["markup_type"])}
            >
              <option value="PERCENTAGE">Percentage</option>
              <option value="FIXED">Fixed (cedis)</option>
              <option value="HYBRID">Percentage + fixed</option>
            </Select>
          </Field>
          {form.markup_type !== "FIXED" ? (
            <Field label="Margin %" htmlFor="rule-percent">
              <Input id="rule-percent" inputMode="decimal" value={form.markup_percent}
                onChange={(e) => set("markup_percent", e.target.value)} className="tabular" />
            </Field>
          ) : null}
          {form.markup_type !== "PERCENTAGE" ? (
            <Field label="Fixed margin (₵)" htmlFor="rule-fixed">
              <Input id="rule-fixed" inputMode="decimal" value={form.markup_fixed}
                onChange={(e) => set("markup_fixed", e.target.value)} className="tabular" />
            </Field>
          ) : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Collection fee %" htmlFor="rule-fee" hint="Paystack Mobile Money fee.">
            <Input id="rule-fee" inputMode="decimal" value={form.payment_fee_percent}
              onChange={(e) => set("payment_fee_percent", e.target.value)} className="tabular" />
          </Field>
          <Field label="Risk buffer %" htmlFor="rule-risk" hint="Refunds and failures.">
            <Input id="rule-risk" inputMode="decimal" value={form.risk_buffer_percent}
              onChange={(e) => set("risk_buffer_percent", e.target.value)} className="tabular" />
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Rounding" htmlFor="rule-rounding">
            <Select id="rule-rounding" value={form.rounding} onChange={(e) => set("rounding", e.target.value)}>
              {ROUNDING.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Minimum price (₵)" htmlFor="rule-min">
            <Input id="rule-min" inputMode="decimal" value={form.min_price}
              onChange={(e) => set("min_price", e.target.value)} className="tabular" />
          </Field>
          <Field label="Maximum price (₵)" htmlFor="rule-max">
            <Input id="rule-max" inputMode="decimal" value={form.max_price}
              onChange={(e) => set("max_price", e.target.value)} className="tabular" />
          </Field>
        </div>

        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(e) => set("is_active", e.target.checked)}
            className="mt-0.5 h-5 w-5 rounded border-line-strong text-brand-600"
          />
          <span className="text-sm text-ink">Active</span>
        </label>

        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-danger-200 bg-danger-50 p-3">
          <input
            type="checkbox"
            checked={form.allow_below_cost}
            onChange={(e) => set("allow_below_cost", e.target.checked)}
            className="mt-0.5 h-5 w-5 rounded border-line-strong text-danger-600"
          />
          <span>
            <span className="block text-sm font-medium text-danger-700">Allow selling below cost</span>
            <span className="block text-xs text-danger-700">
              Only for a deliberate promotion. Every sale under this rule can lose money.
            </span>
          </span>
        </label>

        <Field label="Reason" htmlFor="rule-reason" required hint="Required. Stored with every price it changes.">
          <Textarea
            id="rule-reason"
            rows={2}
            required
            minLength={5}
            value={form.reason}
            onChange={(e) => set("reason", e.target.value)}
            placeholder="e.g. Lower TikTok Canada to match competitors"
          />
        </Field>

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" loading={busy} disabled={form.reason.trim().length < 5}>
            {rule ? "Save and reprice" : "Create and reprice"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------
 * Price history
 * ---------------------------------------------------------------------- */

const SOURCE_TONE: Record<PriceChange["source"], "brand" | "info" | "warn" | "neutral"> = {
  PRICING_RULE: "brand",
  PROVIDER_COST: "warn",
  EXCHANGE_RATE: "info",
  INITIAL: "neutral",
};

export function PriceHistoryCard() {
  const [source, setSource] = React.useState("");
  const [page, setPage] = React.useState(1);
  const { data } = useSWR<Paginated<PriceChange>>([
    "/admin/price-changes/",
    { source, page, page_size: 25 },
  ]);
  const changes = data?.results ?? [];

  return (
    <Card className="mt-4">
      <CardHeader
        title="Price history"
        description="Every change to a customer price, what caused it, and - for staff changes - who and why."
        action={
          <Select
            aria-label="Filter by cause"
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
              setPage(1);
            }}
            className="h-9 w-44 text-sm"
          >
            <option value="">All causes</option>
            <option value="PRICING_RULE">Pricing rule</option>
            <option value="PROVIDER_COST">Provider cost</option>
            <option value="EXCHANGE_RATE">Exchange rate</option>
            <option value="INITIAL">First recorded</option>
          </Select>
        }
      />
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[52rem] text-left text-sm">
          <thead className="border-y border-line bg-canvas">
            <tr className="text-xs uppercase tracking-wide text-ink-muted">
              <th scope="col" className="px-5 py-3 font-medium">When</th>
              <th scope="col" className="px-5 py-3 font-medium">Service</th>
              <th scope="col" className="px-5 py-3 text-right font-medium">Old</th>
              <th scope="col" className="px-5 py-3 text-right font-medium">New</th>
              <th scope="col" className="px-5 py-3 font-medium">Cause</th>
              <th scope="col" className="px-5 py-3 font-medium">By / reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {!data ? (
              <tr>
                <td colSpan={6} className="px-5 py-3">
                  <Skeleton className="h-4 w-full" />
                </td>
              </tr>
            ) : changes.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-6 text-center text-sm text-ink-muted">
                  No price changes recorded yet.
                </td>
              </tr>
            ) : (
              changes.map((change) => (
                <tr key={change.id}>
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs text-ink-muted" title={formatDateTime(change.created_at)}>
                    {relativeTime(change.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-5 py-2.5 text-ink">
                    {change.service_name}
                    <span className="ml-1.5 text-xs text-ink-muted">{change.country_code}</span>
                  </td>
                  <td className="tabular whitespace-nowrap px-5 py-2.5 text-right text-ink-muted">
                    {change.old_price ? cedis(change.old_price) : "-"}
                  </td>
                  <td className="tabular whitespace-nowrap px-5 py-2.5 text-right font-medium text-ink">
                    {cedis(change.new_price)}
                  </td>
                  <td className="px-5 py-2.5">
                    <Badge tone={SOURCE_TONE[change.source]}>{change.source_label}</Badge>
                  </td>
                  <td className="max-w-[18rem] px-5 py-2.5 text-xs text-ink-muted">
                    {change.changed_by_email ? (
                      <span className="block text-ink-soft">{change.changed_by_email}</span>
                    ) : null}
                    <span className="block truncate">{change.reason || "-"}</span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {data?.pagination ? (
        <div className="px-4 py-3 sm:px-5">
          <Pagination
            page={data.pagination.page}
            pages={data.pagination.pages}
            count={data.pagination.count}
            hasNext={data.pagination.has_next}
            hasPrevious={data.pagination.has_previous}
            onChange={setPage}
            noun="changes"
          />
        </div>
      ) : null}
    </Card>
  );
}
