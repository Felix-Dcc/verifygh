"use client";

import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { ServiceAvatar } from "@/components/brand";
import { RefreshIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
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
import { cedis, formatDateTime, relativeTime } from "@/lib/format";
import type {
  AdminCountry,
  AdminOffering,
  AdminService,
  ExchangeRate,
  Paginated,
  PricingRule,
} from "@/lib/types";

type Tab = "services" | "countries" | "pricing" | "rates";

export default function AdminCatalogPage() {
  const { can } = useAuth();
  const [tab, setTab] = React.useState<Tab>("services");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Catalog and pricing"
        description="What we sell, where we sell it, and how a provider cost becomes a customer price."
      />

      <SegmentedControl
        options={[
          { value: "services" as Tab, label: "Services" },
          { value: "countries" as Tab, label: "Countries" },
          { value: "pricing" as Tab, label: "Pricing rules" },
          { value: "rates" as Tab, label: "Exchange rates" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "services" ? <ServicesTab canManage={can("CATALOG_MANAGE")} /> : null}
      {tab === "countries" ? <CountriesTab canManage={can("CATALOG_MANAGE")} /> : null}
      {tab === "pricing" ? <PricingTab canManage={can("PRICING_MANAGE")} /> : null}
      {tab === "rates" ? <RatesTab canManage={can("PRICING_MANAGE")} /> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ServicesTab({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data: services, mutate } = useSWR<AdminService[]>("/admin/services/");
  const [editing, setEditing] = React.useState<AdminService | null>(null);
  const [syncing, setSyncing] = React.useState(false);

  async function sync() {
    setSyncing(true);
    try {
      const summary = await api.post<{ offerings: number; unavailable: number }>(
        "/admin/offerings/sync/",
        {},
      );
      toast.success(
        "Catalog synced",
        `${summary.offerings} offerings refreshed, ${summary.unavailable} out of stock.`,
      );
      await mutate();
      await globalMutate((key) => String(Array.isArray(key) ? key[0] : key).startsWith("/services"));
    } catch (error) {
      toast.error("Sync failed", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <>
      <Card>
        <CardHeader
          title="Services"
          description="Disabling a service hides it from the marketplace immediately. A provider sync never re-enables it."
          action={
            canManage ? (
              <Button
                size="sm"
                variant="secondary"
                loading={syncing}
                onClick={sync}
                icon={<RefreshIcon className="h-4 w-4" />}
              >
                Sync from provider
              </Button>
            ) : undefined
          }
        />
        {!services ? (
          <RowSkeletons />
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {services.map((service) => (
              <li key={service.id} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
                <ServiceAvatar name={service.name} accentColor={service.accent_color} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{service.name}</p>
                  <p className="text-xs text-ink-muted">
                    {service.available_count}/{service.offering_count} in stock
                    <span className="mx-1.5" aria-hidden>
                      &middot;
                    </span>
                    {service.category.toLowerCase()}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {service.is_maintenance ? (
                    <Badge tone="warn">Maintenance</Badge>
                  ) : service.is_enabled ? (
                    <Badge tone="success" dot>
                      Live
                    </Badge>
                  ) : (
                    <Badge tone="neutral">Disabled</Badge>
                  )}
                  {canManage ? (
                    <Button size="sm" variant="secondary" onClick={() => setEditing(service)}>
                      Edit
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <ServiceEditor
        service={editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          await mutate();
          await globalMutate((key) =>
            String(Array.isArray(key) ? key[0] : key).startsWith("/services"),
          );
        }}
      />

      <OfferingsCard />
    </>
  );
}

function ServiceEditor({
  service,
  onClose,
  onSaved,
}: {
  service: AdminService | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const toast = useToast();
  const [form, setForm] = React.useState({
    is_enabled: true,
    is_maintenance: false,
    maintenance_note: "",
    reason: "",
  });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!service) return;
    setForm({
      is_enabled: service.is_enabled,
      is_maintenance: service.is_maintenance,
      maintenance_note: service.maintenance_note,
      reason: "",
    });
    setError("");
  }, [service]);

  if (!service) return null;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.patch(`/admin/services/${service!.slug}/`, form);
      toast.success("Service updated");
      await onSaved();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onClose={onClose} title={service.name} description="Marketplace visibility" dismissible={!busy}>
      <form onSubmit={save} className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}

        <Toggle
          id="is_enabled"
          label="Available in the marketplace"
          description="Turning this off removes the service from the catalogue entirely."
          checked={form.is_enabled}
          onChange={(value) => setForm((current) => ({ ...current, is_enabled: value }))}
        />

        <Toggle
          id="is_maintenance"
          label="Maintenance mode"
          description="Stays visible with a notice, but cannot be purchased."
          checked={form.is_maintenance}
          onChange={(value) => setForm((current) => ({ ...current, is_maintenance: value }))}
        />

        {form.is_maintenance ? (
          <Field label="Maintenance note" htmlFor="maintenance_note" hint="Shown to customers.">
            <Input
              id="maintenance_note"
              value={form.maintenance_note}
              onChange={(event) =>
                setForm((current) => ({ ...current, maintenance_note: event.target.value }))
              }
              placeholder="Back shortly - upstream provider issue"
            />
          </Field>
        ) : null}

        <Field label="Reason" htmlFor="service-reason" hint="Recorded in the audit log.">
          <Textarea
            id="service-reason"
            rows={2}
            value={form.reason}
            onChange={(event) => setForm((current) => ({ ...current, reason: event.target.value }))}
            placeholder="e.g. Provider reporting high failure rate"
          />
        </Field>

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" loading={busy}>
            Save changes
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function OfferingsCard() {
  const [service, setService] = React.useState("");
  const { data } = useSWR<Paginated<AdminOffering>>([
    "/admin/offerings/",
    { service, page_size: 50 },
  ]);
  const { data: services } = useSWR<AdminService[]>("/admin/services/");

  const offerings = data?.results ?? [];

  return (
    <Card className="mt-4">
      <CardHeader
        title="Provider cost against customer price"
        description="Every (service, country) pair, priced by the live engine."
        action={
          <Select
            aria-label="Filter by service"
            value={service}
            onChange={(event) => setService(event.target.value)}
            className="h-9 w-44 text-sm"
          >
            <option value="">All services</option>
            {services?.map((item) => (
              <option key={item.slug} value={item.slug}>
                {item.name}
              </option>
            ))}
          </Select>
        }
      />
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <thead className="border-y border-line bg-canvas">
            <tr className="text-xs uppercase tracking-wide text-ink-muted">
              <th scope="col" className="px-5 py-3 font-medium">Service</th>
              <th scope="col" className="px-5 py-3 font-medium">Country</th>
              <th scope="col" className="px-5 py-3 text-right font-medium">Provider cost</th>
              <th scope="col" className="px-5 py-3 text-right font-medium">Customer price</th>
              <th scope="col" className="px-5 py-3 text-right font-medium">Margin</th>
              <th scope="col" className="px-5 py-3 font-medium">Stock</th>
              <th scope="col" className="px-5 py-3 font-medium">Synced</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {offerings.map((offering) => (
              <tr key={offering.id} className="transition-colors hover:bg-canvas">
                <td className="whitespace-nowrap px-5 py-3 font-medium text-ink">
                  {offering.service_name}
                </td>
                <td className="whitespace-nowrap px-5 py-3 text-ink-soft">
                  {offering.country_code}
                </td>
                <td className="tabular whitespace-nowrap px-5 py-3 text-right text-ink-muted">
                  ${Number.parseFloat(offering.cost_amount).toFixed(4)}
                </td>
                <td className="tabular whitespace-nowrap px-5 py-3 text-right font-medium text-ink">
                  {offering.customer_price ? cedis(offering.customer_price) : "-"}
                </td>
                <td
                  className={cn(
                    "tabular whitespace-nowrap px-5 py-3 text-right",
                    offering.margin && Number.parseFloat(offering.margin) > 0
                      ? "text-success-700"
                      : "text-danger-700",
                  )}
                >
                  {offering.margin ? cedis(offering.margin) : "-"}
                </td>
                <td className="px-5 py-3">
                  {!offering.is_enabled ? (
                    <Badge tone="neutral">Disabled</Badge>
                  ) : offering.is_available ? (
                    <Badge tone="success" dot>
                      {offering.available_count ?? "In stock"}
                    </Badge>
                  ) : (
                    <Badge tone="warn">Out of stock</Badge>
                  )}
                </td>
                <td className="whitespace-nowrap px-5 py-3 text-xs text-ink-muted">
                  {offering.last_synced_at ? relativeTime(offering.last_synced_at) : "never"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function CountriesTab({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data: countries, mutate } = useSWR<AdminCountry[]>("/admin/countries/");
  const [busy, setBusy] = React.useState<string | null>(null);

  async function toggle(country: AdminCountry) {
    setBusy(country.code);
    try {
      await api.patch(`/admin/countries/${country.code}/`, {
        is_enabled: !country.is_enabled,
        reason: `${country.is_enabled ? "Disabled" : "Enabled"} from the admin console`,
      });
      await mutate();
      await globalMutate((key) => String(Array.isArray(key) ? key[0] : key).startsWith("/services"));
      toast.success(country.is_enabled ? "Country disabled" : "Country enabled");
    } catch (error) {
      toast.error("Could not update", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Countries"
        description="Disabling a country removes every service for it from the marketplace."
      />
      {!countries ? (
        <RowSkeletons />
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {countries.map((country) => (
            <li key={country.id} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
              <span className="text-xl" aria-hidden>
                {country.flag_emoji}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink">{country.name}</p>
                <p className="tabular text-xs text-ink-muted">
                  {country.code} {country.dial_code}
                </p>
              </div>
              {country.is_enabled ? (
                <Badge tone="success" dot>
                  Enabled
                </Badge>
              ) : (
                <Badge tone="neutral">Disabled</Badge>
              )}
              {canManage ? (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={busy === country.code}
                  onClick={() => toggle(country)}
                >
                  {country.is_enabled ? "Disable" : "Enable"}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function PricingTab({ canManage }: { canManage: boolean }) {
  const { data: rules } = useSWR<PricingRule[]>("/admin/pricing-rules/");

  if (!canManage) {
    return (
      <Alert tone="info" title="Pricing is restricted">
        Only a super admin can view or change pricing rules.
      </Alert>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Pricing rules"
        description="Resolution is most-specific-first: service and country beats service, which beats the global default."
      />
      {!rules ? (
        <RowSkeletons />
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[46rem] text-left text-sm">
            <thead className="border-y border-line bg-canvas">
              <tr className="text-xs uppercase tracking-wide text-ink-muted">
                <th scope="col" className="px-5 py-3 font-medium">Rule</th>
                <th scope="col" className="px-5 py-3 font-medium">Scope</th>
                <th scope="col" className="px-5 py-3 font-medium">Markup</th>
                <th scope="col" className="px-5 py-3 font-medium">Fees</th>
                <th scope="col" className="px-5 py-3 font-medium">Rounding</th>
                <th scope="col" className="px-5 py-3 font-medium">Bounds</th>
                <th scope="col" className="px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rules.map((rule) => (
                <tr key={rule.id} className="transition-colors hover:bg-canvas">
                  <td className="px-5 py-3 font-medium text-ink">{rule.name}</td>
                  <td className="px-5 py-3 text-ink-soft">
                    {rule.service_slug || rule.country_code ? (
                      <>
                        {rule.service_slug ?? "any service"}
                        {rule.country_code ? ` / ${rule.country_code}` : ""}
                      </>
                    ) : (
                      <Badge tone="brand">Global default</Badge>
                    )}
                  </td>
                  <td className="tabular px-5 py-3 text-ink-soft">
                    {rule.markup_type === "FIXED"
                      ? cedis(rule.markup_fixed)
                      : rule.markup_type === "HYBRID"
                        ? `${rule.markup_percent}% + ${cedis(rule.markup_fixed)}`
                        : `${rule.markup_percent}%`}
                  </td>
                  <td className="tabular px-5 py-3 text-ink-muted">
                    {rule.payment_fee_percent}% fee, {rule.risk_buffer_percent}% buffer
                  </td>
                  <td className="px-5 py-3 text-ink-muted">
                    {rule.rounding.replace(/_/g, " ").toLowerCase()}
                  </td>
                  <td className="tabular px-5 py-3 text-ink-muted">
                    {cedis(rule.min_price)} - {cedis(rule.max_price)}
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-line px-4 py-3 text-xs text-ink-muted sm:px-5">
        The global default cannot be deleted. Without it nothing can be priced, and the
        marketplace would have to stop selling rather than guess a markup.
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ */

function RatesTab({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const { data: rates, mutate } = useSWR<ExchangeRate[]>("/admin/exchange-rates/");
  const [rate, setRate] = React.useState("");
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  if (!canManage) {
    return (
      <Alert tone="info" title="Exchange rates are restricted">
        Only a super admin can view or set exchange rates.
      </Alert>
    );
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.post("/admin/exchange-rates/", { rate, note, reason: note || "Manual FX update" });
      setRate("");
      setNote("");
      await mutate();
      await globalMutate((key) => String(Array.isArray(key) ? key[0] : key).startsWith("/services"));
      toast.success("Rate recorded", "Prices across the marketplace have been recalculated.");
    } catch (error) {
      toast.error("Could not save", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  const current = rates?.[0];

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardHeader title="Record a new rate" description="Rates are append-only - never edited." />
        <form onSubmit={save} className="space-y-4 p-4 pt-4 sm:p-5 sm:pt-4">
          {current ? (
            <div className="rounded-xl bg-canvas p-3.5 text-sm">
              <p className="text-ink-muted">Current rate</p>
              <p className="tabular mt-0.5 text-lg font-semibold text-ink">
                1 USD = {Number.parseFloat(current.rate).toFixed(4)} GHS
              </p>
              <p className="mt-0.5 text-xs text-ink-faint">
                {current.source} - {relativeTime(current.fetched_at)}
              </p>
            </div>
          ) : (
            <Alert tone="warn" title="No rate configured">
              Nothing can be priced until a rate exists.
            </Alert>
          )}

          <Field label="USD to GHS" htmlFor="rate" required>
            <Input
              id="rate"
              inputMode="decimal"
              required
              value={rate}
              onChange={(event) => setRate(event.target.value.replace(/[^\d.]/g, ""))}
              placeholder="12.4000"
              className="tabular"
            />
          </Field>

          <Field label="Note" htmlFor="rate-note" hint="Recorded with the rate and audited.">
            <Input
              id="rate-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="e.g. Interbank mid-rate, 17 Sept"
            />
          </Field>

          <Button type="submit" fullWidth loading={busy} disabled={!rate}>
            Record rate
          </Button>

          <p className="text-xs leading-relaxed text-ink-muted">
            Changing the rate reprices the marketplace immediately. Orders already placed keep the
            rate frozen onto them.
          </p>
        </form>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader title="Rate history" />
        {!rates ? (
          <RowSkeletons />
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {rates.map((entry, index) => (
              <li key={entry.id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                <span className="tabular text-sm font-semibold text-ink">
                  {Number.parseFloat(entry.rate).toFixed(4)}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
                  {entry.note || entry.source}
                </span>
                {index === 0 ? <Badge tone="brand">Current</Badge> : null}
                <span className="shrink-0 text-xs text-ink-faint">
                  {formatDateTime(entry.fetched_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Toggle({
  id,
  label,
  description,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-start gap-3">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-5 w-5 shrink-0 rounded border-line-strong text-brand-600 focus:ring-2 focus:ring-brand-500/50"
      />
      <span>
        <span className="block text-sm font-medium text-ink">{label}</span>
        <span className="block text-xs text-ink-muted">{description}</span>
      </span>
    </label>
  );
}

function RowSkeletons() {
  return (
    <ul className="mt-2 divide-y divide-line">
      {Array.from({ length: 6 }).map((_, index) => (
        <li key={index} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
          <Skeleton className="h-9 w-9 rounded-xl" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </li>
      ))}
    </ul>
  );
}
