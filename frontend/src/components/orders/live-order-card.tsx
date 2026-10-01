"use client";

import Link from "next/link";
import * as React from "react";

import { CountryFlag } from "@/components/country-flag";
import { CheckCircleIcon, ChevronRightIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { cn } from "@/components/ui/primitives";
import { countdown, groupInternational } from "@/lib/format";
import type { OrderSummary } from "@/lib/types";

/** The current time, ticking once a second while anything is using it. */
export function useNow(active = true) {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

const WAITING = new Set(["NUMBER_ASSIGNED", "WAITING_FOR_CODE"]);

/**
 * An order that is still running, as a card: the service, its number, and
 * where it stands - a live countdown and a bar draining towards the number's
 * expiry while it waits (both from the order's own created_at / expires_at),
 * "Code ready" once the SMS has landed.
 */
export function LiveOrderCard({ order, now }: { order: OrderSummary; now: number }) {
  const created = Date.parse(order.created_at);
  const expires = order.expires_at ? Date.parse(order.expires_at) : NaN;
  const waiting = WAITING.has(order.status);
  const remaining = Number.isFinite(expires) ? Math.max(0, Math.round((expires - now) / 1000)) : null;
  const span = Number.isFinite(expires) && Number.isFinite(created) ? Math.max(1, expires - created) : null;
  const left = remaining !== null && span ? Math.min(1, (remaining * 1000) / span) : null;
  const codeReady = order.status === "CODE_RECEIVED";
  const urgent = waiting && remaining !== null && remaining < 120;

  return (
    <Link
      href={`/orders/${order.reference}`}
      className="group relative flex flex-col gap-3 overflow-hidden rounded-2xl border border-line bg-surface p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-raised"
    >
      <div className="flex items-center gap-3">
        <ServiceLogo name={order.service_name} src={order.service_icon} slug={order.service_slug} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-sm font-semibold text-ink">
            <span className="truncate">{order.service_name}</span>
            <CountryFlag code={order.country_code} size="sm" />
            <span className="sr-only">{order.country_name}</span>
          </p>
          <p className="code truncate text-caption text-ink-muted">
            {order.phone_number ? groupInternational(order.phone_number, order.country_dial_code) : "Getting a number…"}
          </p>
        </div>
        <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </div>

      {codeReady ? (
        <p className="flex items-center gap-2 rounded-xl bg-success-50 px-3 py-2 text-caption font-semibold text-success-700">
          <CheckCircleIcon className="h-4 w-4" />
          Code ready - open the order to copy it
        </p>
      ) : waiting && remaining !== null ? (
        <div>
          <div className="flex items-center justify-between text-caption">
            <span className="flex items-center gap-2 font-medium text-info-700">
              <span className="relative flex h-2 w-2">
                <span className="absolute inset-0 animate-pulse-ring rounded-full bg-info-500" />
                <span className="relative h-2 w-2 rounded-full bg-info-500" />
              </span>
              Waiting for the SMS
            </span>
            <span className={cn("tabular font-semibold", urgent ? "text-warn-700" : "text-ink-soft")}>
              {/* Past its time: the order closes on the server's next pass (and
                  refunds itself if no code came) - say so rather than 0:00. */}
              {remaining > 0 ? `${countdown(remaining)} left` : "Closing…"}
            </span>
          </div>
          {left !== null ? (
            <span aria-hidden className="mt-2 block h-1.5 overflow-hidden rounded-full bg-sunken">
              <span
                className={cn(
                  "block h-full rounded-full transition-[width] duration-1000 ease-linear",
                  urgent ? "bg-warn-500" : "bg-gradient-to-r from-azure to-leaf",
                )}
                style={{ width: `${left * 100}%` }}
              />
            </span>
          ) : null}
        </div>
      ) : (
        <p className="flex items-center gap-2 text-caption font-medium text-ink-muted">
          <span className="h-2 w-2 animate-pulse rounded-full bg-ink-faint" />
          Getting your number…
        </p>
      )}
    </Link>
  );
}
