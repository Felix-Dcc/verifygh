"use client";

import { usePathname } from "next/navigation";
import * as React from "react";
import { createPortal } from "react-dom";
import useSWR, { mutate as globalMutate } from "swr";

import { AlertIcon, ShieldIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import { Button, cn } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import type { AdminMaintenance, MaintenanceMode, SiteStatus } from "@/lib/types";

/**
 * Site-wide maintenance: the "Pause site" button in the admin, the red strip
 * staff see while it is on, and the notice customers see.
 *
 * Pausing stops new orders (and, at the second level, new top-ups) before any
 * money moves. Nothing already under way stops - see
 * backend/apps/common/maintenance.py. Nothing reopens by itself either.
 */

const STATUS_KEY = "/status/";
const ADMIN_KEY = "/admin/maintenance/";

/** Every open tab notices within half a minute, and at once when refocused. */
export function useSiteStatus() {
  return useSWR<SiteStatus>(STATUS_KEY, { refreshInterval: 30_000 });
}

function refreshEverywhere() {
  return Promise.all([globalMutate(STATUS_KEY), globalMutate(ADMIN_KEY),
    globalMutate("/orders/eligibility/"), globalMutate("/payments/options/")]);
}

function clock(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* ------------------------------------------------------------------ */
/* Customers                                                          */
/* ------------------------------------------------------------------ */

/** The notice on every customer and public page while the site is paused. */
export function MaintenanceBanner() {
  const pathname = usePathname();
  const { data } = useSiteStatus();
  // Staff get their own strip, with the button to reopen.
  if (!data || data.mode === "OFF" || pathname.startsWith("/admin")) return null;
  return (
    <div role="status" className="border-b border-warn-200 bg-warn-50 px-4 py-2.5 text-warn-700 sm:px-6">
      <p className="mx-auto flex max-w-6xl items-start gap-2 text-sm">
        <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <span>
          {data.message}
          {data.expected_back_at ? ` Expected back around ${clock(data.expected_back_at)}.` : ""}
        </span>
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Staff                                                              */
/* ------------------------------------------------------------------ */

const LEVELS: { mode: Exclude<MaintenanceMode, "OFF">; title: string; detail: string }[] = [
  {
    mode: "BUYING_PAUSED",
    title: "Pause buying",
    detail: "No new orders. Top-ups stay open.",
  },
  {
    mode: "DEPOSITS_PAUSED",
    title: "Pause top-ups",
    detail: "No new deposits. Customers keep buying with their balance.",
  },
  {
    mode: "ALL_PAUSED",
    title: "Pause buying and top-ups",
    detail: "No new orders and no new deposits.",
  },
];

const PAUSED_LABEL: Record<MaintenanceMode, string> = {
  OFF: "Site is live",
  BUYING_PAUSED: "Buying paused",
  DEPOSITS_PAUSED: "Top-ups paused",
  ALL_PAUSED: "Buying and top-ups paused",
};

const BACK_IN: { label: string; minutes: number | null }[] = [
  { label: "Not sure", minutes: null },
  { label: "30 min", minutes: 30 },
  { label: "1 hour", minutes: 60 },
  { label: "2 hours", minutes: 120 },
  { label: "4 hours", minutes: 240 },
];

/** The red strip on every admin page while the site is paused. */
export function MaintenanceStrip({ canManage }: { canManage: boolean }) {
  const { data } = useSiteStatus();
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);
  if (!data || data.mode === "OFF") return null;

  async function reopen() {
    setBusy(true);
    try {
      // Reopening is the safe direction: one tap, no questions.
      await api.post(ADMIN_KEY, { mode: "OFF", reason: "Reopened from the admin" });
      await refreshEverywhere();
      toast.success("Site is live again");
    } catch (error) {
      toast.error("Could not reopen", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="status" className="border-b border-danger-200 bg-danger-50 px-4 py-2 text-danger-700 sm:px-6 lg:px-10">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          {PAUSED_LABEL[data.mode]}
          {data.since ? ` since ${clock(data.since)}` : ""}
          {data.expected_back_at ? ` · customers told ${clock(data.expected_back_at)}` : ""}
        </p>
        {canManage ? (
          <Button size="sm" variant="secondary" onClick={reopen} loading={busy}>
            Turn off
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** "Pause site" in the admin top bar: one tap opens the sheet, one tap pauses. */
export function PauseSiteButton() {
  const { data } = useSiteStatus();
  const [open, setOpen] = React.useState(false);
  const paused = Boolean(data && data.mode !== "OFF");

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "flex min-h-11 items-center gap-1.5 rounded-lg px-2.5 text-sm font-semibold transition-colors sm:min-h-9",
          paused
            ? "bg-danger-50 text-danger-700 hover:bg-danger-50/80"
            : "text-danger-700 hover:bg-danger-50",
        )}
        aria-label={paused ? "Site paused - change or reopen" : "Pause site"}
      >
        <ShieldIcon className="h-5 w-5" aria-hidden />
        {paused ? (
          <span>Paused</span>
        ) : (
          <span>
            Pause<span className="hidden sm:inline"> site</span>
          </span>
        )}
      </button>
      {/* Rendered at the page, not in the top bar: the bar's backdrop blur would
          otherwise become the sheet's frame and push it off the screen. */}
      {open ? createPortal(<PauseSheet onClose={() => setOpen(false)} />, document.body) : null}
    </>
  );
}

function PauseSheet({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const { data } = useSWR<AdminMaintenance>(ADMIN_KEY);
  const paused = Boolean(data && data.mode !== "OFF");
  const [mode, setMode] = React.useState<Exclude<MaintenanceMode, "OFF">>("BUYING_PAUSED");
  const [reason, setReason] = React.useState<string>("");
  const [backIn, setBackIn] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState<"" | "pause" | "reopen">("");

  const presets = data?.preset_reasons ?? [];
  const chosenReason = reason || presets[0] || "";

  React.useEffect(() => {
    if (data && data.mode !== "OFF") setMode(data.mode);
  }, [data]);

  async function send(next: MaintenanceMode) {
    setBusy(next === "OFF" ? "reopen" : "pause");
    try {
      await api.post(ADMIN_KEY, next === "OFF"
        ? { mode: "OFF", reason: "Reopened from the admin" }
        : { mode: next, reason: chosenReason, expected_back_minutes: backIn });
      await refreshEverywhere();
      toast.success(next === "OFF" ? "Site is live again"
        : PAUSED_LABEL[next]);
      onClose();
    } catch (error) {
      toast.error("Could not change it", error instanceof ApiError ? error.message : "Try again.");
    } finally {
      setBusy("");
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      title={paused ? "The site is paused" : "Pause VerifyGH?"}
      description={
        paused
          ? "Customers see the maintenance notice until you reopen."
          : "Customers are stopped before paying. Orders and payments already under way still finish."
      }
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={Boolean(busy)}>
            Cancel
          </Button>
          {paused ? (
            <Button variant="secondary" onClick={() => send("OFF")} loading={busy === "reopen"}
              disabled={Boolean(busy)}>
              Reopen site
            </Button>
          ) : null}
          <Button variant="danger" onClick={() => send(mode)} loading={busy === "pause"}
            disabled={Boolean(busy) || !chosenReason}>
            {paused ? "Update pause" : "Pause now"}
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        <fieldset>
          <legend className="text-sm font-medium text-ink">What to pause</legend>
          <div className="mt-2 grid gap-2">
            {LEVELS.map((level) => (
              <label
                key={level.mode}
                className={cn(
                  "flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors",
                  mode === level.mode ? "border-danger-500 bg-danger-50" : "border-line hover:bg-sunken",
                )}
              >
                <input type="radio" name="pause-level" className="mt-1" checked={mode === level.mode}
                  onChange={() => setMode(level.mode)} />
                <span>
                  <span className="block text-sm font-semibold text-ink">{level.title}</span>
                  <span className="block text-caption text-ink-muted">{level.detail}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-sm font-medium text-ink">Why</legend>
          <p className="text-caption text-ink-muted">Recorded in the audit log. Not shown to customers.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {presets.map((preset) => (
              <Chip key={preset} selected={chosenReason === preset} onClick={() => setReason(preset)}>
                {preset}
              </Chip>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-sm font-medium text-ink">Tell customers you expect to be back in</legend>
          <p className="text-caption text-ink-muted">Shown only. The site never reopens by itself.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {BACK_IN.map((option) => (
              <Chip key={option.label} selected={backIn === option.minutes}
                onClick={() => setBackIn(option.minutes)}>
                {option.label}
              </Chip>
            ))}
          </div>
        </fieldset>

        {data ? (
          <div className="rounded-xl bg-sunken px-3 py-2.5">
            <p className="text-caption font-medium text-ink-muted">Customers will see</p>
            <p className="mt-1 text-sm text-ink-soft">{data.notices[mode]}</p>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

function Chip({ selected, onClick, children }: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "min-h-10 rounded-full border px-3.5 text-sm transition-colors",
        selected ? "border-danger-500 bg-danger-50 font-medium text-danger-700" : "border-line text-ink-soft hover:bg-sunken",
      )}
    >
      {children}
    </button>
  );
}
