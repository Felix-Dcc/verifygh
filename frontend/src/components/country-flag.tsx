import { cn } from "@/components/ui/primitives";

/**
 * Country flags as small inline SVGs.
 *
 * Emoji flags are not flags on Windows - Chrome there draws the two regional
 * letters instead, so the marketplace read "us United States". These are drawn
 * for the countries the product actually shows (the US and Canada it sells,
 * Ghana where its customers are); anything else falls back to its code in a
 * quiet chip rather than a guessed drawing. Decorative: the country name is
 * always written next to it, so screen readers skip the flag.
 */

const FLAGS: Record<string, React.ReactNode> = {
  US: (
    <>
      <rect width="24" height="16" fill="#FFFFFF" />
      {[0, 2, 4, 6, 8, 10, 12].map((stripe) => (
        <rect key={stripe} y={(stripe * 16) / 13} width="24" height={16 / 13} fill="#B22234" />
      ))}
      <rect width="10" height={(7 * 16) / 13} fill="#3C3B6E" />
      {[2, 5, 8].flatMap((x) =>
        [2, 4.5, 7].map((y) => <circle key={`${x}-${y}`} cx={x} cy={y} r="0.55" fill="#FFFFFF" />),
      )}
    </>
  ),
  CA: (
    <>
      <rect width="24" height="16" fill="#FFFFFF" />
      <rect width="6" height="16" fill="#D52B1E" />
      <rect x="18" width="6" height="16" fill="#D52B1E" />
      <path
        fill="#D52B1E"
        d="M12 3.2l.9 1.8 1.4-.6-.5 2.8 1.6-1 .5 1.2 1.3-.3-.9 1.8.6.4-3 1.9.3 1.1-1.9-.3v1.6h-.6V12l-1.9.3.3-1.1-3-1.9.6-.4-.9-1.8 1.3.3.5-1.2 1.6 1-.5-2.8 1.4.6z"
      />
    </>
  ),
  GH: (
    <>
      <rect width="24" height="16" fill="#006B3F" />
      <rect width="24" height="10.67" fill="#FCD116" />
      <rect width="24" height="5.33" fill="#CE1126" />
      <path
        fill="#000000"
        d="M12 5.6l.62 1.9h2l-1.62 1.18.62 1.9L12 9.4l-1.62 1.18.62-1.9L9.38 7.5h2z"
      />
    </>
  ),
};

export function CountryFlag({ code, className }: { code: string | null | undefined; className?: string }) {
  const key = (code ?? "").toUpperCase();
  const flag = FLAGS[key];
  if (!flag) {
    return key ? (
      <span
        aria-hidden
        className={cn(
          "inline-flex h-4 min-w-6 items-center justify-center rounded-sm border border-line px-0.5 text-2xs font-semibold text-ink-muted",
          className,
        )}
      >
        {key}
      </span>
    ) : null;
  }
  return (
    <svg
      viewBox="0 0 24 16"
      aria-hidden
      className={cn("inline-block h-4 w-6 shrink-0 overflow-hidden rounded-sm ring-1 ring-ink/10", className)}
    >
      {flag}
    </svg>
  );
}
