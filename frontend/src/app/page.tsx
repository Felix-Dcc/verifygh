import Link from "next/link";

import { Faq } from "@/components/marketing/faq";
import { Hero } from "@/components/marketing/hero";
import { HowItWorks } from "@/components/marketing/how-it-works";
import { PaymentSection } from "@/components/marketing/payment-section";
import { PricingSection } from "@/components/marketing/pricing-section";
import { SecuritySection } from "@/components/marketing/security-section";
import { ServicePicker } from "@/components/marketing/service-picker";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink } from "@/components/ui/primitives";

/**
 * The homepage. Order: what it is and a picture of it (the green band); the
 * catalogue itself - pick a country and a service, see today's price; how it
 * works; how you pay; what a price is made of; what protects your money;
 * questions; start (the band again, closing the page).
 *
 * One continuous surface: the green never meets the page at a line. The hero
 * ramps down into it, the close ramps up out of it and down into the footer,
 * and the sections between are set apart by a faint green wash rather than
 * borders (the atmosphere-* classes in globals.css).
 */
export default function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main id="main" className="flex-1">
        <Hero />
        <ServicePicker />
        <HowItWorks />
        <PaymentSection />
        <PricingSection />
        <SecuritySection />
        <Faq />
        <FinalCta />
      </main>
      <SiteFooter seamless />
    </div>
  );
}

/* ------------------------------------------------------------------------ */

function FinalCta() {
  return (
    <section className="atmosphere-close relative overflow-hidden text-white">
      {/* The padding holds the text inside the solid green: at least
          --fade-in above and --fade-out below. */}
      <div className="container-page relative pb-40 pt-44 text-center sm:pb-52 sm:pt-64">
        <h2 className="mx-auto max-w-2xl text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Ready when your next code is
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-white/80 sm:text-lg">
          Creating an account takes a minute and costs nothing. You pay only when you buy a
          number.
        </p>
        <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
          <ButtonLink href="/register" size="lg" variant="onBand" fullWidth className="sm:w-auto">
            Create an account
          </ButtonLink>
          <ButtonLink href="/services" size="lg" variant="onBandOutline" fullWidth className="sm:w-auto">
            See services and prices
          </ButtonLink>
        </div>
        <p className="mx-auto mt-8 max-w-2xl text-caption leading-relaxed text-white/75">
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
