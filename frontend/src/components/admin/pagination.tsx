"use client";

import { Button } from "@/components/ui/primitives";

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

  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-sm text-ink-muted">
        Page {page} of {pages}
        <span className="hidden sm:inline">
          {" "}
          - {count} {noun}
        </span>
      </p>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={!hasPrevious}
          onClick={() => onChange((value) => Math.max(1, value - 1))}
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={!hasNext}
          onClick={() => onChange((value) => value + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
