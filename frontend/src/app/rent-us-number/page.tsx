import type { Metadata } from "next";
import Link from "next/link";

import { ChevronDownIcon } from "@/components/icons";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink, Card } from "@/components/ui/primitives";
import { APP_PAGES } from "@/lib/app-pages";

const TITLE = "Rent a US Number in Ghana for SMS Verification";

export const metadata: Metadata = {
  title: { absolute: `${TITLE} | VerifyGH` },
  description:
    "Keep a US phone number for 1 to 90 days and receive every SMS code on it - for one app or any app. Pay in cedis with MTN MoMo, Telecel Cash or AT Money.",
  alternates: { canonical: "/rent-us-number" },
  openGraph: { title: TITLE, url: "/rent-us-number" },
};

// shortcut: no price shown - rental prices need a signed-in request; add a public "from" price if this page is to rank on price.
const FAQS = [
  {
    q: "How is renting different from buying a number?",
    a: "A bought number is for one verification code and lasts minutes. A rented number is yours for the days you choose, so you can receive codes again - to log back in, reset a password or recover an account.",
  },
  {
    q: "How long can I rent a number for?",
    a: "1, 3, 7, 14, 30 or 90 days. It never renews by itself, and you can extend it from its page before it ends.",
  },
  {
    q: "One app or any app - which should I choose?",
    a: "One app is cheaper and right if you need the number for a single service, such as WhatsApp. Any app receives messages from every app and sender.",
  },
  {
    q: "Can I get my money back?",
    a: "If the number can't be set up, the full amount goes back to your wallet automatically. You can also cancel for a full refund while our provider allows it - usually shortly after renting, before any message arrives. Extensions can't be refunded.",
  },
  {
    q: "How do I pay?",
    a: "Top up your VerifyGH wallet in cedis with MTN MoMo, Telecel Cash or AT Money, then pay for the rental from your wallet.",
  },
];

export default function RentUsNumberPage() {
  // FAQPage structured data, so Google can show the answers in results.
  const schema = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQS.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  };

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SiteHeader />
      <main id="main" className="flex-1">
        <div className="container-page max-w-3xl space-y-10 py-10">
          <section className="app-hero dark relative overflow-hidden rounded-3xl px-6 py-8 text-white sm:px-10 sm:py-10">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-aqua">Number rentals</p>
            <h1 className="mt-4 text-balance text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
              Rent a US Number in Ghana
            </h1>
            <p className="mt-3 max-w-xl text-pretty text-white/75">
              Keep a US phone number for days, not minutes. Every SMS it receives lands in its inbox
              on VerifyGH - log in again, recover an account, or get codes from any app. Pay in cedis
              with Mobile Money.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <ButtonLink href="/rentals" variant="onBand">
                Rent a number
              </ButtonLink>
              <span className="text-sm text-white/80">1 day to 3 months · see prices for each length</span>
            </div>
          </section>

          <section aria-labelledby="how">
            <h2 id="how" className="text-heading text-ink">
              How it works
            </h2>
            <ol className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                ["Choose and pay", "Pick one app or any app and a length, then pay once from your wallet."],
                ["Use the number", "Enter it in the app. Every SMS appears in the number's inbox within seconds."],
                ["Extend or let it end", "Add more days whenever you like. It never renews or charges you by itself."],
              ].map(([title, body], index) => (
                <li key={title}>
                  <Card className="h-full p-4">
                    <p className="text-caption font-semibold text-brand-700">Step {index + 1}</p>
                    <p className="mt-1 font-semibold text-ink">{title}</p>
                    <p className="mt-1 text-sm text-ink-muted">{body}</p>
                  </Card>
                </li>
              ))}
            </ol>
          </section>

          <section aria-labelledby="uses">
            <h2 id="uses" className="text-heading text-ink">
              What people rent a number for
            </h2>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
              <li>Logging in again to an account that sends a code each time.</li>
              <li>Resetting a password or recovering an account that was set up with the number.</li>
              <li>Receiving codes from several apps on one number with an any-app rental.</li>
              <li>Keeping a WhatsApp or Telegram account verified while you set up its own security.</li>
            </ul>
          </section>

          <section aria-labelledby="faq">
            <h2 id="faq" className="text-heading text-ink">
              Questions people ask
            </h2>
            <Card className="mt-3 divide-y divide-line">
              {FAQS.map((item) => (
                <details key={item.q} className="group px-5 py-4">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-medium text-ink">
                    {item.q}
                    <ChevronDownIcon className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-open:rotate-180" />
                  </summary>
                  <p className="mt-2 text-sm text-ink-muted">{item.a}</p>
                </details>
              ))}
            </Card>
          </section>

          <section className="flex flex-col items-start gap-3 rounded-2xl border border-line p-6 sm:flex-row sm:items-center sm:justify-between">
            <p className="font-medium text-ink">Need a number for just one code?</p>
            <ButtonLink href="/services" variant="secondary">
              Buy a number instead
            </ButtonLink>
          </section>

          <nav aria-labelledby="apps">
            <h2 id="apps" className="text-sm font-semibold text-ink-muted">
              US numbers for popular apps
            </h2>
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-sm">
              {APP_PAGES.map((page) => (
                <li key={page.slug}>
                  <Link href={`/us-number/${page.slug}`} className="link">
                    {page.name}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </main>
      <SiteFooter />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }} />
    </div>
  );
}
