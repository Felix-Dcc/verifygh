import Link from "next/link";

import { Logo } from "@/components/brand";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="border-b border-line/70">
        <div className="container-page flex h-16 items-center">
          <Link href="/" aria-label="VerifyGH home" className="rounded-lg">
            <Logo />
          </Link>
        </div>
      </header>

      <main id="main" className="flex flex-1 items-start justify-center px-4 py-8 sm:items-center sm:py-12">
        <div className="w-full max-w-md">{children}</div>
      </main>

      <footer className="border-t border-line/70 py-5">
        <div className="container-page flex flex-wrap items-center justify-between gap-3 text-xs text-ink-faint">
          <span>&copy; {new Date().getFullYear()} VerifyGH</span>
          <span className="flex gap-4">
            <Link href="/terms" className="hover:text-ink-muted">
              Terms
            </Link>
            <Link href="/acceptable-use" className="hover:text-ink-muted">
              Acceptable Use
            </Link>
            <Link href="/privacy" className="hover:text-ink-muted">
              Privacy
            </Link>
          </span>
        </div>
      </footer>
    </div>
  );
}
