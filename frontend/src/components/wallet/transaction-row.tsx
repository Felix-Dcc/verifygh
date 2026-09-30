import {
  ArrowRightIcon,
  GiftIcon,
  PhoneIcon,
  PlusIcon,
  RefreshIcon,
  SettingsIcon,
} from "@/components/icons";
import { Badge, cn } from "@/components/ui/primitives";
import { cedis, relativeTime, signedCedis } from "@/lib/format";
import type { LedgerEntryType, Transaction } from "@/lib/types";

export const ENTRY_LABELS: Record<LedgerEntryType, string> = {
  DEPOSIT: "Deposit",
  PURCHASE: "Purchase",
  REFUND: "Refund",
  ADJUSTMENT: "Adjustment",
  WITHDRAWAL: "Withdrawal",
  REVERSAL: "Reversal",
  REFERRAL_BONUS: "Referral reward",
};

const ENTRY_ICONS: Record<LedgerEntryType, React.ComponentType<{ className?: string }>> = {
  DEPOSIT: PlusIcon,
  PURCHASE: PhoneIcon,
  REFUND: RefreshIcon,
  ADJUSTMENT: SettingsIcon,
  WITHDRAWAL: ArrowRightIcon,
  REVERSAL: RefreshIcon,
  REFERRAL_BONUS: GiftIcon,
};

/**
 * The ledger description without the reference the backend appends
 * ("WhatsApp verification (VGH-4EG97L)" -> "WhatsApp verification"). In a
 * list row the reference only gets truncated; the statement shows it in its
 * own column.
 */
export function entryTitle(entry: Transaction): string {
  return entry.description.replace(/\s*\(?\bVGH-[A-Z0-9-]+\)?\s*$/, "") || entry.description;
}

/** What kind of movement it was, at a glance: money in is green, the rest grey. */
export function TransactionIcon({ entry }: { entry: Transaction }) {
  const Icon = ENTRY_ICONS[entry.entry_type] ?? ArrowRightIcon;
  return (
    <span
      aria-hidden
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
        entry.direction === "CREDIT" ? "bg-success-50 text-success-700" : "bg-sunken text-ink-soft",
      )}
    >
      <Icon className="h-4 w-4" />
    </span>
  );
}

/** A signed amount; the sign carries direction, the colour only repeats it. */
export function TransactionAmount({ entry, className }: { entry: Transaction; className?: string }) {
  return (
    <span
      className={cn(
        "tabular whitespace-nowrap font-medium",
        entry.direction === "CREDIT" ? "text-success-700" : "text-ink",
        className,
      )}
    >
      {signedCedis(entry.amount, entry.direction)}
    </span>
  );
}

/**
 * One ledger entry as a list row - the wallet, the dashboard and the phone
 * layout of the transactions page all use it.
 */
export function TransactionRow({
  entry,
  showBalance = false,
}: {
  entry: Transaction;
  /** The running balance under the amount, for the full statement. */
  showBalance?: boolean;
}) {
  return (
    <li className="flex items-center gap-3 px-4 py-3 sm:px-5">
      <TransactionIcon entry={entry} />
      <div className="min-w-0 flex-1">
        <p className="flex min-w-0 items-center gap-2 text-sm text-ink">
          <span className="truncate">{entryTitle(entry)}</span>
          {entry.funds === "PROMO" ? (
            <Badge tone="gold" className="shrink-0">
              Promo
            </Badge>
          ) : null}
        </p>
        <p className="truncate text-caption text-ink-muted">
          {ENTRY_LABELS[entry.entry_type] ?? entry.entry_type}
          <span className="mx-1.5" aria-hidden>
            &middot;
          </span>
          {relativeTime(entry.created_at)}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <TransactionAmount entry={entry} className="text-sm" />
        {showBalance ? (
          <p className="tabular text-caption text-ink-faint">
            <span className="sr-only">Balance after: </span>
            {cedis(entry.balance_after)}
          </p>
        ) : null}
      </div>
    </li>
  );
}
