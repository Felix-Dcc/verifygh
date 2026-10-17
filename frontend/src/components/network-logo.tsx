import { cn } from "@/components/ui/primitives";

/**
 * The Mobile Money networks' own logos (public/networks/), keyed by the
 * network code the API uses - MTN, TELECEL, AT.
 */
const LOGOS: Record<string, string> = {
  MTN: "/networks/mtn.png",
  TELECEL: "/networks/telecel.png",
  AT: "/networks/at.png",
};

/** The code from a label, for anything that only has "MTN Mobile Money". */
function codeFromLabel(label: string): string {
  if (label.startsWith("MTN")) return "MTN";
  if (label.startsWith("Telecel") || label.startsWith("Vodafone")) return "TELECEL";
  if (label.startsWith("AT") || label.startsWith("AirtelTigo")) return "AT";
  return "";
}

const SIZES = {
  sm: "h-6 w-6 rounded-md",
  md: "h-10 w-10 rounded-xl",
} as const;

/**
 * A network's logo, as a rounded tile. Decorative: the network's name is
 * always written beside it. A network without a logo here (one the API adds
 * later) gets its initials instead of a broken image.
 */
export function NetworkLogo({
  network,
  label = "",
  size = "md",
  className,
}: {
  network?: string;
  label?: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const code = (network || codeFromLabel(label)).toUpperCase();
  const src = LOGOS[code];
  const frame = cn("shrink-0 overflow-hidden ring-1 ring-black/5 dark:ring-white/10", SIZES[size], className);

  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- a 160px local PNG; nothing for next/image to do
      <img src={src} alt="" aria-hidden width={160} height={160} className={cn(frame, "object-cover")} />
    );
  }
  return (
    <span
      aria-hidden
      className={cn(
        frame,
        "flex items-center justify-center bg-linear-to-br from-[#0B63B6] to-[#137A4E] text-2xs font-bold text-white",
      )}
    >
      {(code || label).slice(0, 2).toUpperCase()}
    </span>
  );
}
