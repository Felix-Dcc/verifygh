import {
  CheckCircleIcon,
  ClockIcon,
  GlobeIcon,
  LockIcon,
  MailIcon,
  ReceiptIcon,
  ShieldIcon,
} from "@/components/icons";
import { Faq } from "@/components/marketing/faq";
import { FeaturedServices } from "@/components/marketing/featured-services";
import { HeroVisual } from "@/components/marketing/hero-visual";
import { HowItWorks } from "@/components/marketing/how-it-works";
import { PaymentSection } from "@/components/marketing/payment-section";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink } from "@/components/ui/primitives";

/**
 * The homepage. Order: what it is and a picture of it; what people buy and
 * what it costs today; how it works; how you pay; what a price is made of;
 * what protects your money; questions; start.
 */
export default function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main id="main" className="flex-1">
        <Hero />
        <FeaturedServices />
        <HowItWorks />
        <PaymentSection />
        <Pricing />
        <Security />
        <Faq />
        <FinalCta />
      </main>
      <SiteFooter />
    </div>
  );
}

/* ------------------------------------------------------------------------ */

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-line">
      <div className="container-page grid grid-cols-1 items-center gap-14 py-14 sm:py-20 lg:grid-cols-2 lg:gap-10 lg:py-24">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-5xl">
            Get a US number for your verification code. Pay with MoMo.
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-soft">
            For anyone in Ghana signing up to an app that asks for a US phone number - WhatsApp,
            TikTok, Telegram and more. Pay in cedis from your Mobile Money wallet. If no code
            arrives, the money comes back.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <ButtonLink href="/register" size="lg" fullWidth className="sm:w-auto">
              Create an account
            </ButtonLink>
            <ButtonLink href="/services" size="lg" variant="secondary" fullWidth className="sm:w-auto">
              See services and prices
            </ButtonLink>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-soft">
            {["Pay with MoMo", "Prices in cedis", "Refunded if no code arrives"].map((item) => (
              <li key={item} className="flex items-center gap-2">
                <CheckCircleIcon className="h-4 w-4 text-brand-600" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        <HeroVisual />
      </div>
    </section>
  );
}

function Pricing() {
  const parts = [
    { label: "Provider cost", note: "What our provider charges us for the number, in US dollars." },
    { label: "Exchange rate", note: "Converted to cedis at our published rate, fixed when you buy." },
    { label: "Our margin", note: "How VerifyGH pays for itself." },
    {
      label: "Collection and failure costs",
      note: "Mobile Money collection and the cost of orders that fail, where they apply.",
    },
  ];
  return (
    <section id="pricing" className="container-page scroll-mt-20 py-16 sm:py-24">
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-2 lg:items-start">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            One price per number, in cedis
          </h2>
          <p className="mt-4 text-base leading-relaxed text-ink-muted">
            No subscription and no sign-up fee. The price on a service is the amount taken from your
            wallet - nothing is added at checkout.
          </p>
          <p className="mt-4 text-base leading-relaxed text-ink-muted">
            Prices follow the provider&apos;s cost and the cedi, and are fixed onto your order when
            you buy, so a rate change mid-order cannot change what you paid.
          </p>
          <ButtonLink href="/services" variant="secondary" className="mt-6">
            See current prices
          </ButtonLink>
        </div>

        <div className="card p-5 sm:p-6">
          <h3 className="text-sm font-semibold text-ink">What a price is made of</h3>
          <dl className="mt-3 divide-y divide-line">
            {parts.map((part) => (
              <div key={part.label} className="grid grid-cols-1 gap-1 py-3 sm:grid-cols-3 sm:gap-4">
                <dt className="text-sm font-medium text-ink">{part.label}</dt>
                <dd className="text-sm text-ink-muted sm:col-span-2">{part.note}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}

function Security() {
  // Every line here is something the code does - see SECURITY.md.
  const controls = [
    {
      icon: ShieldIcon,
      title: "Payments you can prove",
      body: "A deposit is credited only after we verify a signed confirmation from the payment provider. Nothing your browser says can credit a wallet.",
    },
    {
      icon: ReceiptIcon,
      title: "A ledger that balances",
      body: "Every movement of money is an entry with a running balance. Balances are re-derived from it on a schedule, and any difference raises an alert.",
    },
    {
      icon: LockIcon,
      title: "Protected sign-in",
      body: "Passwords are hashed with Argon2, sessions live in cookies scripts cannot read, and repeated failed sign-ins lock an account for a while.",
    },
    {
      icon: MailIcon,
      title: "A confirmed email before buying",
      body: "Numbers can only be bought once the account's email address is confirmed, so every order traces back to a real inbox.",
    },
    {
      icon: GlobeIcon,
      title: "Encrypted connections",
      body: "Every page and API call is served over HTTPS, and browsers are told never to connect any other way.",
    },
    {
      icon: ClockIcon,
      title: "Limits that stop a takeover",
      body: "Deposit caps, daily spending limits and order rate limits protect you and the platform if an account is compromised.",
    },
  ];

  return (
    <section id="security" className="scroll-mt-20 border-y border-line bg-surface">
      <div className="container-page py-16 sm:py-24">
        <div className="max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            How your money and account are protected
          </h2>
          <p className="mt-3 text-base text-ink-muted">
            What we actually do - no badges, no borrowed certifications.
          </p>
        </div>
        <dl className="mt-12 grid grid-cols-1 gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
          {controls.map((control) => (
            <div key={control.title}>
              <dt className="flex items-center gap-2.5 text-sm font-semibold text-ink">
                <control.icon className="h-5 w-5 text-brand-600" />
                {control.title}
              </dt>
              <dd className="mt-2 text-sm leading-relaxed text-ink-muted">{control.body}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="container-page py-16 sm:py-24">
      <div className="flex flex-col gap-6 rounded-xl border border-line bg-surface p-6 sm:p-10 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-xl">
          <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            Ready when your next code is
          </h2>
          <p className="mt-3 text-base leading-relaxed text-ink-muted">
            Creating an account takes a minute and costs nothing. You pay only when you buy a
            number.
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <ButtonLink href="/register" size="lg" fullWidth className="sm:w-auto">
            Create an account
          </ButtonLink>
          <ButtonLink href="/services" size="lg" variant="secondary" fullWidth className="sm:w-auto">
            See services and prices
          </ButtonLink>
        </div>
      </div>
      <p className="mt-6 max-w-3xl text-caption text-ink-faint">
        By creating an account you agree to our Terms of Service and Acceptable Use Policy.
        VerifyGH may not be used for fraud, impersonation, spam, or evading platform security or
        identity checks.
      </p>
    </section>
  );
}
