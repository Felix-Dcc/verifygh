import type { Metadata } from "next";
import Link from "next/link";

import { ChevronDownIcon } from "@/components/icons";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, Card } from "@/components/ui/primitives";
import { APP_PAGES } from "@/lib/app-pages";
import { cedis } from "@/lib/format";
import { live } from "@/lib/live-price";

/** Rebuilt at most hourly, so the prices follow the marketplace. */
export const revalidate = 3600;

const TITLE = "Virtual US Number for SMS Verification in Ghana";

export const metadata: Metadata = {
  title: { absolute: `${TITLE} | VerifyGH` },
  description:
    "Get a temporary US phone number to receive verification codes for WhatsApp, Telegram, TikTok and hundreds more apps. Pay in cedis with Mobile Money. Full refund if no code arrives.",
  alternates: { canonical: "/virtual-us-number" },
  openGraph: { title: TITLE, url: "/virtual-us-number" },
};

const FAQS = [
  {
    q: "Is it a real phone number?",
    a: "Yes. You get a real US mobile number that receives SMS. Apps send their verification code to it, and the code appears on your order on VerifyGH.",
  },
  {
    q: "Can I receive calls on it?",
    a: "No. The numbers receive SMS only, so when an app offers a call or an SMS, choose SMS.",
  },
  {
    q: "Why use a virtual number instead of my own?",
    a: "Your own number stays private - no marketing texts, no spam calls and no account linked to your personal line. Many apps also need a US number that you can't get in Ghana.",
  },
  {
    q: "What if the code never arrives?",
    a: "If no code arrives before the number expires, the full price goes back to your wallet automatically. You can also cancel for a refund any time before a code arrives.",
  },
  {
    q: "How do I pay from Ghana?",
    a: "Top up your VerifyGH wallet in cedis with MTN MoMo, Telecel Cash or AT Money. No card or dollar account is needed.",
  },
  {
    q: "Can I keep the number?",
    a: "A bought number is for one verification. To keep a number for days and receive every SMS it gets, rent one for 1 to 90 days.",
  },
];

export default async function VirtualUsNumberPage() {
  const prices = await Promise.all(APP_PAGES.map((page) => live(page.slug)));

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
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-aqua">
              SMS verification for Ghana
            </p>
            <h1 className="mt-4 text-balance text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
              Virtual US Number for SMS Verification in Ghana
            </h1>
            <p className="mt-3 max-w-xl text-pretty text-white/75">
              Get a temporary US phone number to receive the verification code for WhatsApp,
              Telegram, TikTok and hundreds more apps - without giving out your own number. Pay in
              cedis with Mobile Money.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <ButtonLink href="/services" variant="onBand">
                See all apps and prices
              </ButtonLink>
              <ButtonLink href="/rent-us-number" variant="onBandOutline">
                Rent a number
              </ButtonLink>
            </div>
          </section>

          <section aria-labelledby="prices">
            <h2 id="prices" className="text-heading text-ink">
              Today&apos;s prices for popular apps
            </h2>
            <Card className="mt-3 divide-y divide-line overflow-hidden">
              {APP_PAGES.map((page, index) => (
                <Link
                  key={page.slug}
                  href={`/us-number/${page.slug}`}
                  className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-sunken/60 sm:px-5"
                >
                  <ServiceLogo name={page.name} src={prices[index].icon} slug={page.slug} size="sm" />
                  <span className="flex-1 font-medium text-ink">US number for {page.name}</span>
                  <span className="tabular text-sm text-ink-muted">
                    {prices[index].price ? cedis(prices[index].price) : "See price"}
                  </span>
                </Link>
              ))}
            </Card>
          </section>

          <section aria-labelledby="how">
            <h2 id="how" className="text-heading text-ink">
              How it works
            </h2>
            <ol className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                ["Top up", "Add cedis to your wallet with MTN MoMo, Telecel Cash or AT Money."],
                ["Buy a number", "Choose the app you are signing up to and get a US number straight away."],
                ["Copy the code", "Enter the number in the app. The SMS code shows on your order, usually within 2 minutes."],
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
        </div>
      </main>
      <SiteFooter />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }} />
    </div>
  );
}
