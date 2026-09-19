import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";
import type { OrderEvent, OrderStatus } from "@/lib/types";

/**
 * The order timeline.
 *
 * Built from the canonical set of steps so the user always sees where they are
 * *going*, not only where they have been - the difference between "waiting,
 * with two steps left" and "waiting, who knows for how long".
 */
const STEPS: { status: OrderStatus; label: string }[] = [
  { status: "CREATED", label: "Order created" },
  { status: "PROCESSING", label: "Payment confirmed" },
  { status: "NUMBER_ASSIGNED", label: "Number assigned" },
  { status: "WAITING_FOR_CODE", label: "Waiting for verification code" },
  { status: "CODE_RECEIVED", label: "Verification code received" },
  { status: "COMPLETED", label: "Completed" },
];

const TERMINAL_BAD: OrderStatus[] = ["FAILED", "EXPIRED", "CANCELLED", "REFUNDED"];

type StepState = "done" | "current" | "todo" | "failed";

export function OrderTimeline({
  status,
  events,
}: {
  status: OrderStatus;
  events: OrderEvent[];
}) {
  const failed = TERMINAL_BAD.includes(status);
  const reached = new Set(events.map((event) => event.status));
  const timestamps = new Map<string, string>();
  for (const event of events) {
    if (!timestamps.has(event.status)) timestamps.set(event.status, event.created_at);
  }

  const currentIndex = STEPS.findIndex((step) => step.status === status);

  const rows: { label: string; state: StepState; at?: string; detail?: string }[] = STEPS.map(
    (step, index) => {
      const hasHappened = reached.has(step.status);
      let state: StepState = "todo";
      if (hasHappened && index < Math.max(currentIndex, 0)) state = "done";
      else if (step.status === status) state = "current";
      else if (hasHappened) state = "done";
      else if (failed) state = "todo";
      return { label: step.label, state, at: timestamps.get(step.status) };
    },
  );

  // A failed, expired or cancelled order replaces the remaining steps with the
  // single honest outcome rather than leaving ghost steps hanging.
  if (failed) {
    const cutoff = rows.findIndex((row) => row.state === "todo");
    const kept = cutoff === -1 ? rows : rows.slice(0, cutoff);
    const failureEvent = events.find((event) => TERMINAL_BAD.includes(event.status));
    kept.push({
      label: failureEvent?.label ?? "Order closed",
      state: "failed",
      at: failureEvent?.created_at,
      detail: failureEvent?.detail,
    });
    const refund = events.find((event) => event.status === "REFUNDED");
    if (refund && failureEvent?.status !== "REFUNDED") {
      kept.push({
        label: "Refunded",
        state: "done",
        at: refund.created_at,
        detail: refund.detail,
      });
    }
    return <Timeline rows={kept} />;
  }

  return <Timeline rows={rows} />;
}

function Timeline({
  rows,
}: {
  rows: { label: string; state: StepState; at?: string; detail?: string }[];
}) {
  return (
    <ol className="relative space-y-0">
      {rows.map((row, index) => {
        const last = index === rows.length - 1;
        return (
          <li key={`${row.label}-${index}`} className="relative flex gap-3.5 pb-5 last:pb-0">
            {!last ? (
              <span
                className={cn(
                  "absolute left-[11px] top-6 h-full w-px",
                  row.state === "done" ? "bg-brand-300" : "bg-line",
                )}
                aria-hidden
              />
            ) : null}

            <Marker state={row.state} />

            <div className="min-w-0 flex-1 pt-0.5">
              <p
                className={cn(
                  "text-sm",
                  row.state === "todo"
                    ? "text-ink-faint"
                    : row.state === "failed"
                      ? "font-medium text-danger-700"
                      : row.state === "current"
                        ? "font-medium text-ink"
                        : "text-ink-soft",
                )}
              >
                {row.label}
              </p>
              {row.detail ? (
                <p className="mt-0.5 text-xs text-ink-muted">{row.detail}</p>
              ) : null}
              {row.at ? (
                <p className="tabular mt-0.5 text-xs text-ink-faint">{formatTime(row.at)}</p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Marker({ state }: { state: StepState }) {
  if (state === "done") {
    return (
      <span className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white">
        <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" aria-hidden>
          <path d="M3.5 8.5l3 3 6-6.5" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }

  if (state === "failed") {
    return (
      <span className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-danger-700 text-white">
        <svg viewBox="0 0 16 16" fill="none" className="h-3 w-3" aria-hidden>
          <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" />
        </svg>
      </span>
    );
  }

  if (state === "current") {
    return (
      <span className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center">
        <span className="absolute h-6 w-6 animate-pulse-ring rounded-full bg-brand-400" aria-hidden />
        <span className="relative h-3 w-3 rounded-full bg-brand-600" />
      </span>
    );
  }

  return (
    <span className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center">
      <span className="h-3 w-3 rounded-full border-2 border-line-strong bg-surface" />
    </span>
  );
}
