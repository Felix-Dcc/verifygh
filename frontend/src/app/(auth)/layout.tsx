import Link from "next/link";

import { Logo } from "@/components/brand";
import { ArrowLeftIcon, CheckIcon } from "@/components/icons";

/** What the product does, as the homepage says it - nothing invented. */
const POINTS = [
  "Pay in cedis with MTN MoMo, Telecel Cash or AT Money",
  "Every price shown in cedis before you buy",
  "Refunded automatically if no code arrives",
];

/**
 * Sign in, sign up, and the password and email pages around them.
 *
 * From lg the page splits: the homepage's night on the left, saying what
 * VerifyGH is, and the form on the right. On a phone it is the form alone,
 * with nothing to scroll past to reach it.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh bg-canvas">
      <aside className="app-hero dark relative hidden w-[44%] max-w-160 shrink-0 flex-col overflow-hidden p-10 text-white lg:flex xl:p-14">
        <Link href="/" aria-label="VerifyGH home" className="flex min-h-11 w-fit items-center rounded-lg">
          <Logo />
        </Link>

        <div className="my-auto max-w-md py-12">
          <p className="text-caption font-semibold uppercase tracking-[0.18em] text-aqua">
            SMS verification for Ghana
          </p>
          <h2 className="mt-4 text-balance text-4xl font-extrabold leading-[1.08] tracking-[-0.03em] xl:text-5xl">
            Don&apos;t give out your number. <span className="text-dawn">Use ours.</span>
          </h2>
          <p className="mt-5 text-pretty text-base leading-relaxed text-white/70">
            Receive verification codes on a US number, without exposing your personal phone
            number.
          </p>
          <ul className="mt-8 space-y-3.5">
            {POINTS.map((point) => (
              <li key={point} className="flex items-start gap-3 text-sm text-white/85">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-azure to-leaf">
                  <CheckIcon className="h-3 w-3 text-white" />
                </span>
                {point}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-caption text-white/50">&copy; {new Date().getFullYear()} VerifyGH</p>
        {/* The dawn line every navy panel ends on. */}
        <span aria-hidden className="absolute inset-x-0 bottom-0 h-px bg-linear-to-r from-azure via-aqua to-leaf" />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="container-page flex h-16 items-center justify-between lg:h-20 lg:px-10">
          <Link href="/" aria-label="VerifyGH home" className="flex min-h-11 items-center rounded-lg lg:invisible">
            <Logo />
          </Link>
          <Link
            href="/"
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg text-sm font-medium text-ink-muted transition-colors hover:text-ink"
          >
            <ArrowLeftIcon className="h-4 w-4" />
            Home
          </Link>
        </header>

        <main id="main" className="flex flex-1 items-start justify-center px-4 pb-10 pt-4 sm:items-center sm:py-10">
          <div className="w-full max-w-104">{children}</div>
        </main>

        <footer className="container-page border-t border-line/70 py-5 lg:px-10">
          <div className="flex flex-wrap items-center justify-between gap-3 text-caption text-ink-faint">
            <span className="lg:hidden">&copy; {new Date().getFullYear()} VerifyGH</span>
            <span className="flex gap-4 lg:ml-auto">
              <Link href="/terms" className="inline-flex min-h-11 items-center hover:text-ink-muted sm:min-h-0">
                Terms
              </Link>
              <Link href="/acceptable-use" className="inline-flex min-h-11 items-center hover:text-ink-muted sm:min-h-0">
                Acceptable Use
              </Link>
              <Link href="/privacy" className="inline-flex min-h-11 items-center hover:text-ink-muted sm:min-h-0">
                Privacy
              </Link>
            </span>
          </div>
        </footer>
      </div>
    </div>
  );
}
