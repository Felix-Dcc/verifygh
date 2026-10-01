import Link from "next/link";

import { CountryFlag } from "@/components/country-flag";
import { ChevronRightIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { StatusBadge } from "@/components/ui/primitives";
import { cedis, groupInternational, relativeTime } from "@/lib/format";
import type { OrderSummary } from "@/lib/types";

/**
 * One order in a list - Home, the phone layout of Orders, anywhere an order is
 * a row. Service and country first, then its number (or its reference, before
 * a number is assigned) and when, then what it cost and where it stands.
 */
export function OrderStatusRow({ order }: { order: OrderSummary }) {
  return (
    <li>
      <Link
        href={`/orders/${order.reference}`}
        className="group flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-sunken/60 sm:px-5"
      >
        <ServiceLogo name={order.service_name} src={order.service_icon} slug={order.service_slug} />

        <div className="min-w-0 flex-1">
          <p className="flex min-w-0 items-center gap-2 text-sm font-semibold text-ink">
            <span className="truncate">{order.service_name}</span>
            <CountryFlag code={order.country_code} size="sm" />
            <span className="sr-only">{order.country_name}</span>
          </p>
          <p className="truncate text-caption text-ink-muted">
            <span className="code">
              {order.phone_number ? groupInternational(order.phone_number, order.country_dial_code) : order.reference}
            </span>
            <span className="hidden sm:inline">
              <span className="mx-1.5" aria-hidden>
                &middot;
              </span>
              {relativeTime(order.created_at)}
            </span>
          </p>
          {/* Phones: status and time on their own line, so the name and the
              number get the full width. */}
          <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 sm:hidden">
            <StatusBadge status={order.status} />
            <span className="whitespace-nowrap text-caption text-ink-muted">{relativeTime(order.created_at)}</span>
          </span>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="tabular text-sm font-semibold text-ink">{cedis(order.price)}</span>
          <StatusBadge status={order.status} className="hidden sm:inline-flex" />
        </div>

        <ChevronRightIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5" />
      </Link>
    </li>
  );
}
