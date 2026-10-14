"use client";

import Link from "next/link";
import * as React from "react";

import { ChevronRightIcon, GlobeIcon, MessageIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Badge, LiveDot, cn } from "@/components/ui/primitives";
import { cedis, groupInternational } from "@/lib/format";
import type { RentalStatus, RentalSummary } from "@/lib/types";

const STATUS: Record<RentalStatus, { label: string; tone: "success" | "warn" | "neutral" | "brand" | "danger" }> = {
  PENDING: { label: "Setting up", tone: "warn" },
  ACTIVE: { label: "Active", tone: "success" },
  EXPIRED: { label: "Ended", tone: "neutral" },
  REFUNDED: { label: "Refunded", tone: "brand" },
  FAILED: { label: "Didn't go through", tone: "danger" },
};

export function RentalStatusBadge({ status, className }: { status: RentalStatus; className?: string }) {
  const { label, tone } = STATUS[status] ?? { label: status, tone: "neutral" as const };
  return (
    <Badge tone={tone} className={className}>
      {status === "ACTIVE" || status === "PENDING" ? (
        <LiveDot />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      )}
      {label}
    </Badge>
  );
}

/** "Any app" numbers have no single logo: a globe in the brand colours. */
export function RentalLogo({
  rental,
  size = "md",
}: {
  rental: Pick<RentalSummary, "all_services" | "service_name" | "service_icon" | "service_slug">;
  size?: "sm" | "md" | "lg";
}) {
  if (rental.all_services) {
    const box = size === "lg" ? "h-12 w-12" : size === "sm" ? "h-8 w-8" : "h-10 w-10";
    return (
      <span className={cn("flex shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700", box)}>
        <GlobeIcon className={size === "sm" ? "h-4 w-4" : "h-5 w-5"} />
      </span>
    );
  }
  return (
    <ServiceLogo name={rental.service_name} src={rental.service_icon} slug={rental.service_slug} size={size} />
  );
}

/** Time left on a rental, in the largest units that still read naturally. */
export function timeLeft(seconds: number): string {
  if (seconds <= 0) return "Ended";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h left`;
  if (hours > 0) return `${hours}h ${minutes}m left`;
  return `${Math.max(1, minutes)}m left`;
}

/** Ticks a server-given number of seconds down locally, once a minute is plenty. */
export function useSecondsLeft(seconds: number): number {
  const [left, setLeft] = React.useState(seconds);
  React.useEffect(() => setLeft(seconds), [seconds]);
  React.useEffect(() => {
    if (left <= 0) return;
    const step = left > 3_600 ? 30 : 1;
    const timer = window.setInterval(() => setLeft((value) => Math.max(0, value - step)), step * 1000);
    return () => window.clearInterval(timer);
  }, [left > 3_600, left > 0]); // eslint-disable-line react-hooks/exhaustive-deps
  return left;
}

export function RentalRow({ rental }: { rental: RentalSummary }) {
  const left = useSecondsLeft(rental.seconds_remaining);
  return (
    <Link
      href={`/rentals/${rental.reference}`}
      className="group flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-sunken/60 sm:px-5"
    >
      <RentalLogo rental={rental} />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate text-sm font-semibold text-ink">{rental.service_name}</span>
          <RentalStatusBadge status={rental.status} />
        </span>
        <span className="mt-0.5 block truncate text-caption text-ink-muted">
          {rental.phone_number ? (
            <span className="tabular">{groupInternational(rental.phone_number, "+1")}</span>
          ) : (
            "Number on its way"
          )}
          <span aria-hidden> · </span>
          {rental.status === "ACTIVE" ? timeLeft(left) : rental.duration_label}
        </span>
      </span>
      <span className="hidden shrink-0 text-right sm:block">
        <span className="tabular block text-sm font-semibold text-ink">{cedis(rental.price)}</span>
        <span className="inline-flex items-center gap-1 text-caption text-ink-muted">
          <MessageIcon className="h-3.5 w-3.5" />
          {rental.message_count}
        </span>
      </span>
      <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}
