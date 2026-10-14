"use client";

import { ChevronRightIcon } from "@/components/icons";
import { cn } from "@/components/ui/primitives";

/** Previous / next through a list, with where you are and how much there is. */
export function Pagination({
  page,
  pages,
  count,
  hasNext,
  hasPrevious,
  onChange,
  noun = "results",
}: {
  page: number;
  pages: number;
  count: number;
  hasNext: boolean;
  hasPrevious: boolean;
  onChange: (updater: (value: number) => number) => void;
  noun?: string;
}) {
  if (pages <= 1) return null;

  function go(updater: (value: number) => number) {
    onChange(updater);
    // Back to the top of the list, not stranded at the bottom of a new page.
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const button =
    "inline-flex h-10 items-center gap-1 rounded-lg border border-line bg-surface px-3 text-sm font-medium text-ink-soft transition-colors hover:bg-sunken hover:text-ink disabled:pointer-events-none disabled:opacity-40";

  return (
    <nav aria-label="Pages" className="flex items-center justify-between gap-3">
      <p className="text-sm text-ink-muted">
        Page <span className="tabular font-semibold text-ink">{page}</span> of{" "}
        <span className="tabular font-semibold text-ink">{pages}</span>
        <span className="hidden sm:inline">
          {" "}
          · {count.toLocaleString()} {noun}
        </span>
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          className={button}
          disabled={!hasPrevious}
          onClick={() => go((value) => Math.max(1, value - 1))}
        >
          <ChevronRightIcon className={cn("h-4 w-4 rotate-180")} />
          <span className="hidden sm:inline">Previous</span>
        </button>
        <button type="button" className={button} disabled={!hasNext} onClick={() => go((value) => value + 1)}>
          <span className="hidden sm:inline">Next</span>
          <ChevronRightIcon className="h-4 w-4" />
        </button>
      </div>
    </nav>
  );
}
