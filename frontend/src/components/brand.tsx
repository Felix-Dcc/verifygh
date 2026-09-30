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
      <Logomark className={cn("h-8 w-8", tone === "light" ? "text-white" : "text-primary")} />
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
