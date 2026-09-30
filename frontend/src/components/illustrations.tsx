import { cn } from "@/components/ui/primitives";

/**
 * VerifyGH's illustration set, for empty states and help.
 *
 * One style throughout: 1.5px outlines in the neutral line colour, one soft
 * brand-tinted shape per drawing, and a single brand accent. Drawn in theme
 * colours (stroke-line-strong, fill-brand-50, ...) so they sit correctly in
 * light and dark mode, and weigh a few hundred bytes each - no image files.
 * Decorative: the text beside them carries the meaning.
 */

type ArtProps = { className?: string };

function Art({ className, children }: ArtProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 160 120"
      fill="none"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={cn("h-24 w-32", className)}
    >
      {children}
    </svg>
  );
}

/** A phone with an incoming message - orders, verification numbers. */
export function PhoneMessageArt(props: ArtProps) {
  return (
    <Art {...props}>
      <ellipse cx="80" cy="108" rx="44" ry="5" className="fill-sunken" />
      <rect x="52" y="14" width="56" height="92" rx="10" className="fill-surface stroke-line-strong" />
      <path d="M72 21h16" className="stroke-line-strong" />
      <rect x="60" y="34" width="40" height="7" rx="3.5" className="fill-sunken" />
      <rect x="60" y="46" width="28" height="7" rx="3.5" className="fill-sunken" />
      <path
        d="M84 60h40a8 8 0 0 1 8 8v12a8 8 0 0 1-8 8h-24l-9 7v-7h-7a8 8 0 0 1-8-8V68a8 8 0 0 1 8-8z"
        className="fill-brand-50 stroke-brand-500"
      />
      <path d="M92 74h6M103 74h6M114 74h6" strokeWidth="3" className="stroke-brand-500" />
    </Art>
  );
}

/** A statement sheet - transactions. */
export function StatementArt(props: ArtProps) {
  return (
    <Art {...props}>
      <ellipse cx="80" cy="108" rx="44" ry="5" className="fill-sunken" />
      <path d="M48 12h64v90l-8-5-8 5-8-5-8 5-8-5-8 5-8-5-8 5z" className="fill-surface stroke-line-strong" />
      <path d="M60 30h28M60 44h40M60 58h40M60 72h24" className="stroke-line-strong" />
      <circle cx="112" cy="76" r="17" className="fill-brand-50 stroke-brand-500" />
      <path d="M106 76h12M112 70v12" className="stroke-brand-500" />
    </Art>
  );
}

/** A wallet with a Mobile Money card - top-ups. */
export function WalletArt(props: ArtProps) {
  return (
    <Art {...props}>
      <ellipse cx="80" cy="108" rx="48" ry="5" className="fill-sunken" />
      <rect x="54" y="18" width="52" height="34" rx="6" transform="rotate(-8 80 35)" className="fill-brand-50 stroke-brand-500" />
      <path d="M62 30l20-3" transform="rotate(-8 80 35)" className="stroke-brand-500" />
      <rect x="36" y="40" width="88" height="60" rx="10" className="fill-surface stroke-line-strong" />
      <path d="M36 54h88" className="stroke-line-strong" />
      <rect x="98" y="64" width="26" height="18" rx="5" className="fill-sunken stroke-line-strong" />
      <circle cx="108" cy="73" r="2.5" className="fill-brand-500" />
    </Art>
  );
}

/** A quiet bell - notifications. */
export function BellArt(props: ArtProps) {
  return (
    <Art {...props}>
      <ellipse cx="80" cy="108" rx="40" ry="5" className="fill-sunken" />
      <path
        d="M80 20a26 26 0 0 0-26 26v18l-8 14h68l-8-14V46a26 26 0 0 0-26-26z"
        className="fill-surface stroke-line-strong"
      />
      <path d="M72 86a8 8 0 0 0 16 0" className="stroke-line-strong" />
      <circle cx="104" cy="28" r="9" className="fill-brand-50 stroke-brand-500" />
      <path d="M101 28l2.2 2.2 4-4.4" className="stroke-brand-500" />
    </Art>
  );
}

/** A magnifier over a list - nothing found. */
export function SearchArt(props: ArtProps) {
  return (
    <Art {...props}>
      <ellipse cx="80" cy="108" rx="44" ry="5" className="fill-sunken" />
      <rect x="36" y="18" width="76" height="80" rx="10" className="fill-surface stroke-line-strong" />
      <rect x="46" y="30" width="12" height="12" rx="3" className="fill-sunken" />
      <path d="M64 36h34" className="stroke-line-strong" />
      <rect x="46" y="50" width="12" height="12" rx="3" className="fill-sunken" />
      <path d="M64 56h26" className="stroke-line-strong" />
      <circle cx="108" cy="72" r="16" className="fill-brand-50 stroke-brand-500" />
      <path d="M120 84l10 10" strokeWidth="3" className="stroke-brand-500" />
    </Art>
  );
}

/** Two phones joined by an invitation - referrals. */
export function InviteArt(props: ArtProps) {
  return (
    <Art {...props}>
      <ellipse cx="80" cy="108" rx="52" ry="5" className="fill-sunken" />
      <rect x="22" y="26" width="40" height="72" rx="8" className="fill-surface stroke-line-strong" />
      <rect x="98" y="26" width="40" height="72" rx="8" className="fill-surface stroke-line-strong" />
      <path d="M64 58c10-14 22-14 32 0" strokeDasharray="3 5" className="stroke-brand-500" />
      <rect x="70" y="22" width="20" height="16" rx="3" className="fill-brand-50 stroke-brand-500" />
      <path d="M70 29h20M80 22v16" className="stroke-brand-500" />
      <path d="M32 44h20M32 54h14M108 44h20M108 54h14" className="stroke-line-strong" />
    </Art>
  );
}

/** A conversation - help and support. */
export function SupportArt(props: ArtProps) {
  return (
    <Art {...props}>
      <ellipse cx="80" cy="108" rx="48" ry="5" className="fill-sunken" />
      <path
        d="M30 22h60a10 10 0 0 1 10 10v26a10 10 0 0 1-10 10H54l-12 10V68H30a10 10 0 0 1-10-10V32a10 10 0 0 1 10-10z"
        className="fill-surface stroke-line-strong"
      />
      <path d="M34 38h40M34 50h28" className="stroke-line-strong" />
      <path
        d="M130 50H86a10 10 0 0 0-10 10v18a10 10 0 0 0 10 10h28l12 10V88h4a10 10 0 0 0 10-10V60a10 10 0 0 0-10-10z"
        className="fill-brand-50 stroke-brand-500"
      />
      <path d="M92 66l6 6 12-12" className="stroke-brand-500" />
    </Art>
  );
}
