import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ChevronDownIcon } from "@/components/icons";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, Card } from "@/components/ui/primitives";
import { APP_PAGES, appPage } from "@/lib/app-pages";
import { cedis } from "@/lib/format";
import { live } from "@/lib/live-price";

/** Rebuilt at most hourly, so the price shown follows the marketplace. */
export const revalidate = 3600;
export const dynamicParams = false;

export function generateStaticParams() {
  return APP_PAGES.map((page) => ({ slug: page.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const page = appPage((await params).slug);
  if (!page) return {};
  const { price } = await live(page.slug);
  const title = `US Number for ${page.name} Verification in Ghana`;
  return {
    title: { absolute: `${title} | VerifyGH` },
    description:
      `Get a US phone number to ${page.purpose} from Ghana` +
      (price ? `, from ${cedis(price)}` : "") +
      ". Pay with MTN MoMo, Telecel Cash or AT Money. Full refund if no code arrives.",
    alternates: { canonical: `/us-number/${page.slug}` },
    openGraph: { title, url: `/us-number/${page.slug}` },
  };
}

const FAQS = (name: string) => [
  {
    q: `Will ${name} accept a VerifyGH number?`,
    a: `Our numbers are real US mobile numbers that receive SMS. ${name} accepts most of them; if it refuses one, cancel the order for a full refund and try a new number.`,
  },
  {
    q: "What happens if the code never arrives?",
    a: "If no code arrives before the number expires, the full price goes back to your wallet automatically. You can also cancel for a refund any time before a code arrives.",
  },
  {
    q: "How do I pay?",
    a: "Top up your VerifyGH wallet in cedis with MTN MoMo, Telecel Cash or AT Money, then buy the number from your wallet.",
  },
  {
    q: "Can I use the same number again later?",
    a: "A bought number is for one verification. If you need to receive codes on the same number for days, rent a number instead.",
  },
];

export default async function AppNumberPage({ params }: { params: Promise<{ slug: string }> }) {
  const page = appPage((await params).slug);
  if (!page) notFound();
  const { price, icon } = await live(page.slug);
  const faqs = [page.faq, ...FAQS(page.name)];
  const buy = `/services?service=${page.slug}`;

  // FAQPage structured data, so Google can show the answers in results.
  const schema = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((item) => ({
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
            <div className="flex items-center gap-3">
              <ServiceLogo name={page.name} src={icon} slug={page.slug} size="lg" />
              <p className="text-caption font-semibold uppercase tracking-[0.18em] text-aqua">
                SMS verification for Ghana
              </p>
            </div>
            <h1 className="mt-4 text-balance text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
              US Number for {page.name} Verification in Ghana
            </h1>
            <p className="mt-3 max-w-xl text-pretty text-white/75">
              Get a US phone number to {page.purpose}, without giving out your own number. Pay in
              cedis with Mobile Money, and get your money back automatically if no code arrives.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <ButtonLink href={buy} variant="onBand">
                Buy {page.name} number
              </ButtonLink>
              {price ? (
                <span className="text-sm text-white/80">
                  From <span className="tabular font-semibold text-white">{cedis(price)}</span> today
                </span>
              ) : null}
            </div>
          </section>

          <section aria-labelledby="how">
            <h2 id="how" className="text-heading text-ink">
              How it works
            </h2>
            <ol className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                ["Top up", "Add cedis to your wallet with MTN MoMo, Telecel Cash or AT Money."],
                ["Buy the number", `Choose ${page.name} and get a US number straight away.`],
                ["Copy the code", `Enter the number in ${page.name}. The SMS code shows on your order, usually within 2 minutes.`],
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

          <section aria-labelledby="tips">
            <h2 id="tips" className="text-heading text-ink">
              Tips for {page.name}
            </h2>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
              {page.tips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="faq">
            <h2 id="faq" className="text-heading text-ink">
              Questions people ask
            </h2>
            <Card className="mt-3 divide-y divide-line">
              {faqs.map((item) => (
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
            <div>
              <p className="font-medium text-ink">Ready to verify {page.name}?</p>
              <p className="mt-1 text-sm text-ink-muted">
                Need the same number for days? <Link href="/rent-us-number" className="link">Rent a number</Link>.
              </p>
            </div>
            <ButtonLink href={buy}>Buy {page.name} number</ButtonLink>
          </section>

          <nav aria-labelledby="others">
            <h2 id="others" className="text-sm font-semibold text-ink-muted">
              US numbers for other apps
            </h2>
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-sm">
              {APP_PAGES.filter((other) => other.slug !== page.slug).map((other) => (
                <li key={other.slug}>
                  <Link href={`/us-number/${other.slug}`} className="link">
                    {other.name}
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
