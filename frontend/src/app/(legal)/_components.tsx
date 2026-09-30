export function LegalHeader({
  title,
  updated,
  summary,
}: {
  title: string;
  updated: string;
  summary: string;
}) {
  return (
    <header className="border-b border-line pb-6">
      <h1 className="text-display text-ink">{title}</h1>
      <p className="mt-2 text-sm text-ink-muted">Last updated {updated}</p>
      <p className="mt-4 rounded-lg bg-sunken p-4 text-sm leading-relaxed text-ink-soft">
        <span className="font-semibold text-ink">In short: </span>
        {summary}
      </p>
      {/* These documents are a working draft. Ghanaian counsel should review
          them against the Data Protection Act (2012) and your aggregator's
          merchant terms before you take real payments. */}
      <p className="mt-3 text-xs text-ink-faint">
        This document is a template prepared for VerifyGH and has not yet been reviewed by legal
        counsel. Have it reviewed before relying on it commercially.
      </p>
    </header>
  );
}
