"use client";

import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { OfferingsPricingCard, PriceHistoryCard, PricingRulesCard } from "@/components/admin/pricing";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { RefreshIcon } from "@/components/icons";
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
  const [scope, setScope] = React.useState<"sold" | "missing" | "all">("sold");

  const sold = (services ?? []).filter((service) => service.marketplace_offerings > 0);
  const missing = sold.filter((service) => !service.icon_url);
  const shown =
    scope === "all" ? services ?? [] : scope === "missing" ? missing : sold;

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
        <div className="flex flex-wrap items-center gap-2 px-4 pt-3 sm:px-5">
          <SegmentedControl
            options={[
              { value: "sold" as const, label: `Sold in US/CA (${sold.length})` },
              { value: "missing" as const, label: `Missing logo (${missing.length})` },
              { value: "all" as const, label: "Whole provider catalogue" },
            ]}
            value={scope}
            onChange={setScope}
          />
        </div>
        {!services ? (
          <RowSkeletons />
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {shown.map((service) => (
              <li key={service.id} className="flex items-center gap-3 px-4 py-3.5 sm:px-5">
                <ServiceLogo name={service.name} src={service.icon_url} slug={service.slug} />
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

      <OfferingsPricingCard canManage={canManage} />
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
    is_popular: false,
    popular_rank: 100,
    aliases: "",
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
      is_popular: service.is_popular,
      popular_rank: service.popular_rank,
      aliases: service.aliases,
      reason: "",
    });
    setError("");
  }, [service]);

  if (!service) return null;

  async function uploadLogo(file: File) {
    const body = new FormData();
    body.append("file", file);
    body.append("reason", form.reason || "Service logo uploaded");
    await runLogo(() => api.post(`/admin/services/${service!.slug}/logo/`, body), "Logo uploaded");
  }

  async function runLogo(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    try {
      await action();
      toast.success(message);
      await onSaved();
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

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

        <div className="rounded-xl border border-line p-3.5">
          <p className="mb-2.5 text-sm font-medium text-ink">Logo</p>
          <div className="flex items-center gap-4">
            <ServiceLogo name={service.name} src={service.icon_url} slug={service.slug} size="xl" />
            <div className="min-w-0 flex-1 space-y-1 text-xs text-ink-muted">
              <p>
                {service.has_uploaded_logo
                  ? "Uploaded logo."
                  : service.icon_url
                    ? "Bundled logo (Simple Icons, CC0)."
                    : "No logo - customers see the generic icon."}
              </p>
              <p>SVG or PNG (at least 96 x 96), up to 200 KB. SVG is sharpest.</p>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <label className="inline-flex cursor-pointer">
              <input
                type="file"
                accept="image/svg+xml,image/png,.svg,.png"
                className="sr-only"
                disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) uploadLogo(file);
                  event.target.value = "";
                }}
              />
              <span className="inline-flex h-9 items-center rounded-xl border border-line bg-surface px-3.5 text-sm font-medium text-ink hover:bg-canvas">
                {service.has_uploaded_logo || service.icon_url ? "Replace logo" : "Upload logo"}
              </span>
            </label>
            {service.has_uploaded_logo ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  runLogo(() => api.delete(`/admin/services/${service.slug}/logo/`), "Uploaded logo removed")
                }
              >
                Remove upload
              </Button>
            ) : null}
            {!service.has_uploaded_logo && service.bundled_icon_url && !service.icon_url ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  runLogo(
                    () =>
                      api.patch(`/admin/services/${service.slug}/`, {
                        icon_url: service.bundled_icon_url,
                        reason: "Restored the bundled logo",
                      }),
                    "Bundled logo restored",
                  )
                }
              >
                Use bundled logo
              </Button>
            ) : null}
            {service.icon_url && !service.has_uploaded_logo ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  runLogo(
                    () =>
                      api.patch(`/admin/services/${service.slug}/`, {
                        icon_url: "",
                        reason: "Logo hidden from the admin console",
                      }),
                    "Logo hidden",
                  )
                }
              >
                Hide logo
              </Button>
            ) : null}
          </div>
        </div>

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

        <Toggle
          id="is_popular"
          label="Popular"
          description="Listed under Popular in the marketplace, wherever it is in stock."
          checked={form.is_popular}
          onChange={(value) => setForm((current) => ({ ...current, is_popular: value }))}
        />

        {form.is_popular ? (
          <Field label="Popular position" htmlFor="popular_rank" hint="Lower comes first.">
            <Input
              id="popular_rank"
              inputMode="numeric"
              value={String(form.popular_rank)}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  popular_rank: Number.parseInt(event.target.value || "0", 10) || 0,
                }))
              }
            />
          </Field>
        ) : null}

        <Field
          label="Search aliases"
          htmlFor="aliases"
          hint="Other names customers type, comma-separated - e.g. gmail, youtube."
        >
          <Input
            id="aliases"
            value={form.aliases}
            onChange={(event) => setForm((current) => ({ ...current, aliases: event.target.value }))}
          />
        </Field>

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
  if (!canManage) {
    return (
      <Alert tone="info" title="Pricing is restricted">
        Only a super admin can view or change pricing rules.
      </Alert>
    );
  }
  return (
    <>
      <PricingRulesCard />
      <PriceHistoryCard />
    </>
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
