import { cn } from "@/components/ui/primitives";
import type { Availability } from "@/lib/types";

const DOT: Record<Availability, string> = {
  AVAILABLE: "bg-success-500",
  LIMITED: "bg-warn-500",
  UNAVAILABLE: "bg-danger-500",
};

/**
 * Stock as the provider reported it, and no more.
 *
 * A number appears only when the server sends one - it withholds counts that
 * look like a ceiling (OnlineSim reports 9999 for almost everything) - so the
 * words here never claim stock we were not told about.
 */
export function AvailabilityLabel({
  availability,
  count,
  compact,
  className,
}: {
  availability: Availability;
  count: number | null;
  compact?: boolean;
  className?: string;
}) {
  const text =
    availability === "UNAVAILABLE"
      ? "Unavailable"
      : availability === "LIMITED"
        ? count
          ? `${count} left`
          : "Limited"
        : count
          ? compact
            ? `${count}`
            : `${count} available`
          : "Available";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs",
        availability === "UNAVAILABLE" ? "text-ink-faint" : "text-ink-soft",
        className,
      )}
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT[availability])} aria-hidden />
      {text}
    </span>
  );
}
