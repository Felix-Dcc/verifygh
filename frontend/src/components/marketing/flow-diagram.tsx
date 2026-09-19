import { Logomark } from "@/components/brand";

/**
 * MoMo -> VerifyGH -> verification service.
 *
 * The one thing a first-time visitor needs to understand in three seconds:
 * their Mobile Money goes in one side, a verification number comes out the
 * other, and we sit in the middle doing the part they cannot do themselves.
 */
export function FlowDiagram() {
  return (
    <div className="rounded-3xl border border-line bg-surface p-5 shadow-raised sm:p-7">
      <div className="flex items-center gap-1.5 sm:gap-5">
        <Node
          label="Mobile Money"
          sublabel="MTN - Telecel - AT"
          tone="momo"
          icon={
            <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" aria-hidden>
              <rect x="6" y="2.5" width="12" height="19" rx="3" stroke="currentColor"
                strokeWidth="1.7" />
              <path d="M10.5 18.5h3" stroke="currentColor" strokeWidth="1.7"
                strokeLinecap="round" />
              <path d="M9.5 8.5h5M9.5 11.5h5" stroke="currentColor" strokeWidth="1.7"
                strokeLinecap="round" />
            </svg>
          }
        />

        <Connector />

        <div className="flex flex-1 flex-col items-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-600 shadow-raised sm:h-16 sm:w-16">
            <Logomark className="h-7 w-7 text-brand-600 sm:h-9 sm:w-9" />
          </div>
          <div className="text-center">
            <p className="text-2xs font-semibold leading-tight text-ink sm:text-sm">VerifyGH</p>
            <p className="text-2xs leading-tight text-ink-muted sm:text-xs">Cedis in, number out</p>
          </div>
        </div>

        <Connector />

        <Node
          label="Verification"
          sublabel="Supported services"
          tone="service"
          icon={
            <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" aria-hidden>
              <path d="M20.5 12.5c0 3.9-3.8 7-8.5 7a9.8 9.8 0 0 1-2.7-.37L4.5 20.5l1.2-3.4A6.6 6.6 0 0 1 3.5 12.5c0-3.9 3.8-7 8.5-7s8.5 3.1 8.5 7z"
                stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
              <path d="M9 12.5h6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          }
        />
      </div>

      <div className="mt-6 grid grid-cols-3 gap-2 border-t border-line pt-4 text-center">
        <Step number="1" label="Pay in cedis" />
        <Step number="2" label="We handle the rest" />
        <Step number="3" label="Get your number" />
      </div>
    </div>
  );
}

function Node({
  label,
  sublabel,
  icon,
  tone,
}: {
  label: string;
  sublabel: string;
  icon: React.ReactNode;
  tone: "momo" | "service";
}) {
  return (
    <div className="flex flex-1 flex-col items-center gap-2">
      <div
        className={
          tone === "momo"
            ? "flex h-12 w-12 items-center justify-center rounded-2xl border border-gold-300 bg-gold-100 text-gold-700 sm:h-16 sm:w-16"
            : "flex h-12 w-12 items-center justify-center rounded-2xl border border-line-strong bg-canvas text-ink-soft sm:h-16 sm:w-16"
        }
      >
        {icon}
      </div>
      <div className="text-center">
        <p className="text-2xs font-semibold leading-tight text-ink sm:text-sm">{label}</p>
        <p className="text-2xs leading-tight text-ink-muted sm:text-xs">{sublabel}</p>
      </div>
    </div>
  );
}

function Connector() {
  return (
    <div className="flex h-12 shrink-0 items-center sm:h-16" aria-hidden>
      <svg viewBox="0 0 40 8" className="h-2 w-3 text-line-strong sm:w-10" fill="none">
        <path
          d="M0 4h32"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeDasharray="3 3"
          strokeLinecap="round"
        />
        <path d="M31 1l4 3-4 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
          strokeLinejoin="round" />
      </svg>
    </div>
  );
}

function Step({ number, label }: { number: string; label: string }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-50 text-2xs font-semibold text-brand-700">
        {number}
      </span>
      <span className="text-2xs text-ink-muted sm:text-xs">{label}</span>
    </div>
  );
}
