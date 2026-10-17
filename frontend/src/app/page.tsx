import type { Metadata } from "next";
import Link from "next/link";

import { DashboardShowcase } from "@/components/marketing/dashboard-showcase";
import { Faq } from "@/components/marketing/faq";
import { Hero } from "@/components/marketing/hero";
import { HowItWorks } from "@/components/marketing/how-it-works";
import { PaymentSection } from "@/components/marketing/payment-section";
import { PricingSection } from "@/components/marketing/pricing-section";
import { PrivacySection } from "@/components/marketing/privacy-section";
import { ProductsSection } from "@/components/marketing/products-section";
import { SecuritySection } from "@/components/marketing/security-section";
import { ServicePicker } from "@/components/marketing/service-picker";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink } from "@/components/ui/primitives";

/**
 * The homepage, as one continuous surface from night to day and back:
 *
 * - Hero (navy): "Don't give out your number. Use ours." - a phone receiving a
 *   code, services revolving around it - ramping down through blue, cyan and
 *   green into the page.
 * - How it works: a mini product demo, four steps on a phone.
 * - Built for the way you verify: the catalogue - a marquee of services and
 *   the live picker.
 * - Mobile Money: a top-up happening, and where the money goes.
 * - Pricing: one live price as a receipt, and the two ways a number is sold.
 * - Your number, protected (navy, mid-page): your number, ours, the shield.
 * - Your money and account: the wallet with its protections annotated.
 * - Everything you need to verify: the products that exist today.
 * - The dashboard: the app in a laptop, or on a phone.
 * - Questions people ask.
 * - The close (ramping up into night) and the navy footer.
 *
 * The colour never changes at a line - see the atmosphere-* classes in
 * globals.css. No testimonials: there are no verified reviews to show yet,
 * and invented ones would be fake.
 */
/**
 * One address for the homepage. getverifygh.com and www.getverifygh.com both
 * serve it, and without a canonical a search engine treats them as two copies
 * of the same page and splits their ranking between them.
 */
export const metadata: Metadata = { alternates: { canonical: "/" } };

const SITE_URL = process.env.NEXT_PUBLIC_SITE_ORIGIN || "https://www.getverifygh.com";

/**
 * Who we are, for search engines (schema.org). Only facts that are true and
 * public on this page: the name, the address, the logo, the support inbox and
 * that the service is for Ghana. No ratings - there are no verified reviews.
 */
const STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": `${SITE_URL}/#organization`,
      name: "VerifyGH",
      url: SITE_URL,
      logo: `${SITE_URL}/icons/icon-512.png`,
      email: "support@getverifygh.com",
      areaServed: { "@type": "Country", name: "Ghana" },
    },
    {
      "@type": "WebSite",
      "@id": `${SITE_URL}/#website`,
      name: "VerifyGH",
      url: SITE_URL,
      inLanguage: "en-GH",
      publisher: { "@id": `${SITE_URL}/#organization` },
    },
  ],
};

export default function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      {/* Data, not code: browsers never run an ld+json block, so the CSP has no say in it. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
      />
      <SiteHeader />
      <main id="main" className="flex-1">
        <Hero />
        <HowItWorks />
        <ServicePicker />
        <PaymentSection />
        <PricingSection />
        <PrivacySection />
        <SecuritySection />
        <ProductsSection />
        <DashboardShowcase />
        <Faq />
        <FinalCta />
      </main>
      <SiteFooter night />
    </div>
  );
}

/* ------------------------------------------------------------------------ */

function FinalCta() {
  return (
    <section className="atmosphere-night-close relative overflow-x-clip text-white">
      {/* The padding holds the text on the navy: at least --fade-in above. */}
      <div className="container-page relative pb-24 pt-84 text-center sm:pb-28 sm:pt-108">
        <h2 className="mx-auto max-w-3xl text-balance text-4xl font-extrabold tracking-[-0.035em] text-white sm:text-5xl">
          Ready to verify without giving out <span className="text-dawn">your number?</span>
        </h2>
        <p className="mx-auto mt-5 max-w-xl text-pretty text-base leading-relaxed text-white/75 sm:text-lg">
          Create your VerifyGH account for free, top up with MoMo, and get your first number in
          minutes.
        </p>
        <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
          <ButtonLink href="/register" size="lg" variant="dawn" fullWidth className="group sm:w-auto">
            Get started free
            <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
              →
            </span>
          </ButtonLink>
          <ButtonLink href="/login" size="lg" variant="onBandOutline" fullWidth className="sm:w-auto">
            Sign in
          </ButtonLink>
        </div>
        <p className="mx-auto mt-10 max-w-2xl text-caption leading-relaxed text-white/60">
          By creating an account you agree to our{" "}
          <Link href="/terms" className="underline underline-offset-2 hover:text-white">
            Terms of Service
          </Link>{" "}
          and{" "}
          <Link href="/acceptable-use" className="underline underline-offset-2 hover:text-white">
            Acceptable Use Policy
          </Link>
          . VerifyGH may not be used for fraud, impersonation, spam, or evading platform security or
          identity checks.
        </p>
      </div>
    </section>
  );
}
