/** Display helpers. Ghanaian conventions by default: cedis, local phone
 *  formatting, Accra time. */

const GHS = new Intl.NumberFormat("en-GH", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Money is written one way everywhere: "GH₵ 1,250.00".
 *
 * GH₵ (not ₵ or GHS) because that is how Ghanaian banks and MoMo apps write
 * it; a no-break space so the symbol never wraps away from the figure; always
 * two decimals. Amounts arrive as strings and stay exact.
 */
const CEDI = "GH₵ ";
const MINUS = "−";

export function cedis(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return `${CEDI}0.00`;
  const value = typeof amount === "string" ? Number.parseFloat(amount) : amount;
  if (Number.isNaN(value)) return `${CEDI}0.00`;
  return `${value < 0 ? MINUS : ""}${CEDI}${GHS.format(Math.abs(value))}`;
}

/**
 * Signed, for ledger rows: "+GH₵ 50.00" / "−GH₵ 14.50". A true minus sign, the
 * width of the plus, so a column of signed amounts lines up - and the sign is
 * there so the direction never depends on colour alone.
 */
export function signedCedis(amount: string | number, direction?: "CREDIT" | "DEBIT"): string {
  const value = typeof amount === "string" ? Number.parseFloat(amount) : amount;
  const negative = direction === "DEBIT" || value < 0;
  return `${negative ? MINUS : "+"}${cedis(Math.abs(value))}`;
}

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

/** Provider costs (staff only): "$12.50", up to four decimals when they matter. */
export function usd(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "$0.00";
  const value = typeof amount === "string" ? Number.parseFloat(amount) : amount;
  return Number.isNaN(value) ? "$0.00" : USD.format(value);
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
 * The number without its country code - what a sign-up form wants once the
 * country has been picked from its own list. Falls back to all digits.
 */
export function nationalNumber(phone: string | null | undefined, dialCode?: string | null): string {
  const digits = (phone ?? "").replace(/\D/g, "");
  const code = (dialCode ?? "").replace(/\D/g, "");
  if (code === "1" && digits.length === 10) return digits;
  if (code && digits.startsWith(code) && digits.length > code.length) {
    return digits.slice(code.length);
  }
  return digits;
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

  // US/Canada: "+1 (512) 803-3513", the way the numbers are written there and
  // the way providers show them. Also accepts the 10 national digits alone.
  if (code === "1") {
    const national = nationalNumber(phone, dialCode);
    if (national.length === 10) {
      return `+1 (${national.slice(0, 3)}) ${national.slice(3, 6)}-${national.slice(6)}`;
    }
  }

  if (code && digits.startsWith(code)) {
    const national = digits.slice(code.length);
    const grouped = national.replace(/(\d{3})(?=\d)/g, "$1 ");
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

const DAY_KEY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Africa/Accra",
});

/**
 * "Today", "Yesterday" or "Earlier", by the calendar in Accra rather than by
 * 24-hour windows - a 23:50 notification is yesterday's at 00:10.
 */
export function dayGroup(value: string): "Today" | "Yesterday" | "Earlier" {
  const day = DAY_KEY.format(new Date(value));
  const now = Date.now();
  if (day === DAY_KEY.format(new Date(now))) return "Today";
  if (day === DAY_KEY.format(new Date(now - 86_400_000))) return "Yesterday";
  return "Earlier";
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
