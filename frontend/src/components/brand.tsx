import { cn } from "@/lib/cn";

/**
 * The VerifyGH mark: a verification check inside a rounded shield, with a small
 * five-point star at the corner - a quiet nod to the black star, not a flag
 * pasted onto a logo.
 */
export function Logomark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={cn("h-8 w-8", className)}
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="9" fill="currentColor" />
      <path
        d="M9.5 16.6l4.2 4.2 8.8-9.2"
        stroke="white"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M24.2 6.4l.72 1.6 1.72.2-1.28 1.2.34 1.72-1.5-.86-1.5.86.34-1.72-1.28-1.2 1.72-.2z"
        fill="#C79A2E"
      />
    </svg>
  );
}

export function Logo({
  className,
  showWordmark = true,
  tone = "brand",
}: {
  className?: string;
  showWordmark?: boolean;
  tone?: "brand" | "light";
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Logomark className={cn("h-8 w-8", tone === "light" ? "text-white" : "text-brand-600")} />
      {showWordmark ? (
        <span
          className={cn(
            "text-lg font-semibold tracking-tight",
            tone === "light" ? "text-white" : "text-ink",
          )}
        >
          Verify<span className={tone === "light" ? "text-brand-200" : "text-brand-600"}>GH</span>
        </span>
      ) : null}
    </span>
  );
}

/**
 * A service avatar.
 *
 * Deliberately a lettermark in the service's accent colour rather than the
 * company's real logo: we are not licensed to redistribute third-party
 * trademarks, and a consistent set of tiles looks better than a grid of
 * mismatched PNGs anyway.
 */
export function ServiceAvatar({
  name,
  accentColor,
  size = "md",
  className,
}: {
  name: string;
  accentColor?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const letters = name
    .replace(/[^A-Za-z0-9 ]/g, "")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
    .slice(0, 2) || "?";

  const sizes = {
    sm: "h-8 w-8 text-xs rounded-lg",
    md: "h-11 w-11 text-sm rounded-xl",
    lg: "h-14 w-14 text-base rounded-2xl",
  } as const;

  const color = accentColor && /^#[0-9a-f]{6}$/i.test(accentColor) ? accentColor : "#0B6446";

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-semibold text-white",
        sizes[size],
        className,
      )}
      style={{ backgroundColor: color }}
      aria-hidden="true"
    >
      {letters}
    </span>
  );
}
