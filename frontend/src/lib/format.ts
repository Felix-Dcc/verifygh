/** Display helpers. Ghanaian conventions by default: cedis, local phone
 *  formatting, Accra time. */

const GHS = new Intl.NumberFormat("en-GH", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "25" -> "₵25.00". Amounts arrive as strings and stay exact. */
export function cedis(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "₵0.00";
  const value = typeof amount === "string" ? Number.parseFloat(amount) : amount;
  if (Number.isNaN(value)) return "₵0.00";
  return `₵${GHS.format(value)}`;
}

/** Signed, for ledger rows: "+₵50.00" / "-₵14.50". */
export function signedCedis(amount: string | number, direction?: "CREDIT" | "DEBIT"): string {
  const value = typeof amount === "string" ? Number.parseFloat(amount) : amount;
  const negative = direction === "DEBIT" || value < 0;
  return `${negative ? "−" : "+"}${cedis(Math.abs(value))}`;
}

/** 0241234567 / +233241234567 -> "024 123 4567". */
export function localPhone(phone: string | null | undefined): string {
  if (!phone) return "";
  let digits = phone.replace(/\D/g, "");
  if (digits.startsWith("233")) digits = `0${digits.slice(3)}`;
  if (digits.length !== 10) return phone;
  return `${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}`;
}

/**
 * Group an international number for reading and copying.
 *
 * The dial code must be supplied: you cannot tell from the digits alone where
 * a country code ends. "+13278273360" is +1 with a 10-digit number, but a
 * naive parse reads it as +132. Without a dial code we group from the right,
 * which stays readable and never asserts a wrong country.
 */
export function groupInternational(
  phone: string | null | undefined,
  dialCode?: string | null,
): string {
  if (!phone) return "";
  const digits = phone.replace(/\D/g, "");
  if (!digits) return phone;

  const code = (dialCode ?? "").replace(/\D/g, "");

  if (code && digits.startsWith(code)) {
    const national = digits.slice(code.length);
    // NANP numbers read as 3-3-4; everything else in threes.
    const grouped =
      national.length === 10
        ? `${national.slice(0, 3)} ${national.slice(3, 6)} ${national.slice(6)}`
        : national.replace(/(\d{3})(?=\d)/g, "$1 ");
    return `+${code} ${grouped}`.trim();
  }

  // Unknown dial code: group from the right so the last digits stay aligned.
  const groups: string[] = [];
  let rest = digits;
  while (rest.length > 3) {
    groups.unshift(rest.slice(-3));
    rest = rest.slice(0, -3);
  }
  if (rest) groups.unshift(rest);
  return `+${groups.join(" ")}`;
}

const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "Africa/Accra",
});

const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Africa/Accra",
});

const TIME = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Africa/Accra",
});

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return DATE.format(new Date(value));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  return DATE_TIME.format(new Date(value));
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  return TIME.format(new Date(value));
}

/** "2 minutes ago", "just now". Keeps an order list scannable. */
export function relativeTime(value: string | null | undefined): string {
  if (!value) return "";
  const then = new Date(value).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);

  if (seconds < 45) return "just now";
  if (seconds < 90) return "1 minute ago";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} ${days === 1 ? "day" : "days"} ago`;
  return formatDate(value);
}

/** 125 -> "2:05". Used by the live order countdown. */
export function countdown(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** "Instagram" -> "IG". The lettermark used instead of a third-party logo. */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

const STATUS_TEXT: Record<string, string> = {
  CREATED: "Created",
  PAYMENT_PENDING: "Payment pending",
  PROCESSING: "Processing",
  NUMBER_ASSIGNED: "Number assigned",
  WAITING_FOR_CODE: "Waiting for code",
  CODE_RECEIVED: "Code received",
  COMPLETED: "Completed",
  EXPIRED: "Expired",
  CANCELLED: "Cancelled",
  FAILED: "Failed",
  REFUNDED: "Refunded",
  PENDING: "Pending",
  SUCCESS: "Successful",
  DEPOSIT: "Deposit",
  PURCHASE: "Purchase",
  REFUND: "Refund",
  ADJUSTMENT: "Adjustment",
  WITHDRAWAL: "Withdrawal",
  REVERSAL: "Reversal",
};

export function humanStatus(status: string): string {
  return STATUS_TEXT[status] ?? status.replace(/_/g, " ").toLowerCase();
}

/** Copy to clipboard, resolving to whether it worked. Falls back for older
 *  mobile browsers that block the async clipboard API. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
