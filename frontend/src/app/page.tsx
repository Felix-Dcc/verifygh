import {
  CheckCircleIcon,
  CopyIcon,
  LockIcon,
  ReceiptIcon,
  WalletIcon,
} from "@/components/icons";
import { Faq } from "@/components/marketing/faq";
import { FeaturedServices } from "@/components/marketing/featured-services";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink } from "@/components/ui/primitives";

export default function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main id="main" className="flex-1">
        <Hero />
        <Facts />
        <HowItWorks />
        <FeaturedServices />
        <MomoExplainer />
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
    <section className="container-page grid grid-cols-1 gap-12 py-14 sm:py-20 lg:grid-cols-2 lg:items-center lg:gap-16">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-5xl">
          A US number for your verification code, paid with Mobile Money.
        </h1>
        <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-soft">
          Pick a service, pay from your cedi wallet, and the code appears on your order screen.
          If it never arrives, the money goes back to your wallet on its own.
        </p>
        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <ButtonLink href="/register" size="lg" fullWidth className="sm:w-auto">
            Create an account
          </ButtonLink>
          <ButtonLink href="/services" size="lg" variant="secondary" fullWidth className="sm:w-auto">
            See services and prices
          </ButtonLink>
        </div>
      </div>

      <OrderPreview />
    </section>
  );
}

/**
 * What an order looks like - the same layout as the real order screen, with
 * an example number from the 555 range that is reserved for fiction.
 */
function OrderPreview() {
  return (
    <figure className="lg:pl-4">
      <div className="card overflow-hidden shadow-raised" aria-hidden>
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="flex items-center gap-3">
            <ServiceLogo name="WhatsApp" src="/service-icons/whatsapp.svg" slug="whatsapp" size="sm" />
            <div>
              <p className="text-sm font-medium text-ink">WhatsApp</p>
              <p className="code text-caption text-ink-muted">VGH-7KQ2MD</p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-md bg-success-50 px-2 py-0.5 text-caption font-medium text-success-700">
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            Code received
          </span>
        </div>
        <div className="p-5">
          <p className="text-label text-ink-muted">Your WhatsApp number</p>
          <div className="mt-2 flex items-center gap-3">
            <p className="tabular text-title font-semibold text-ink">+1 (512) 555-0147</p>
            <span className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-strong px-2.5 text-caption font-medium text-ink">
              <CopyIcon className="h-3.5 w-3.5" />
              Copy
            </span>
          </div>
        </div>
        <div className="border-t border-success-200 bg-success-50 px-5 py-4">
          <p className="text-label text-success-700">Verification code</p>
          <p className="code mt-1 text-display font-semibold tracking-widest text-success-700">482913</p>
        </div>
      </div>
      <figcaption className="mt-3 text-caption text-ink-muted">
        An order once the code has arrived. Example number.
      </figcaption>
    </figure>
  );
}

function Facts() {
  const items = [
    { icon: <WalletIcon className="h-4 w-4" />, label: "MTN, Telecel and AT Money" },
    { icon: <LockIcon className="h-4 w-4" />, label: "We never see your MoMo PIN" },
    { icon: <ReceiptIcon className="h-4 w-4" />, label: "A reference for every cedi" },
    { icon: <CheckCircleIcon className="h-4 w-4" />, label: "Refunded if no code comes" },
  ];
  return (
    <section className="border-y border-line bg-surface">
      <ul className="container-page no-scrollbar flex gap-6 overflow-x-auto py-4 sm:justify-between">
        {items.map((item) => (
          <li key={item.label} className="flex shrink-0 items-center gap-2 text-sm text-ink-soft">
            <span className="text-ink-muted">{item.icon}</span>
            {item.label}
          </li>
        ))}
      </ul>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    {
      title: "Choose a service",
      body: "Search the catalogue. The price in cedis is on every row, before you commit to anything.",
    },
    {
      title: "Add funds with MoMo",
      body: "Approve the prompt on your phone. The balance appears once the network confirms it.",
    },
    {
      title: "Get your number",
      body: "We reserve a number from our authorised provider, usually within seconds, and charge you once.",
    },
    {
      title: "Receive the code",
      body: "It appears on your order screen. If none arrives before the number expires, you are refunded.",
    },
  ];

  return (
    <section id="how-it-works" className="container-page scroll-mt-20 py-16 sm:py-20">
      <h2 className="max-w-xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
        How it works
      </h2>
      <ol className="mt-10 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
        {steps.map((step, index) => (
          <li key={step.title} className="border-t border-line-strong pt-4">
            <p className="tabular text-sm font-semibold text-brand-700">{index + 1}</p>
            <h3 className="mt-2 text-heading text-ink">{step.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function MomoExplainer() {
  return (
    <section className="border-y border-line bg-surface">
      <div className="container-page grid grid-cols-1 gap-10 py-16 sm:py-20 lg:grid-cols-2 lg:items-center">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            Paid for with the Mobile Money you already have
          </h2>
          <p className="mt-4 text-base leading-relaxed text-ink-muted">
            Most verification services expect a US card or a crypto wallet. Almost nobody in Ghana
            has either, and almost everybody has Mobile Money.
          </p>
          <ul className="mt-6 space-y-3">
            {[
              "Type your number the way you normally write it - 024 123 4567 works.",
              "Your network is filled in from the number. Change it if you have moved networks.",
              "Approve the prompt on your phone. Your balance updates once the network confirms it.",
              "Your PIN goes into your own handset and never passes through VerifyGH.",
            ].map((line) => (
              <li key={line} className="flex gap-3 text-sm text-ink-soft">
                <CheckCircleIcon className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                {line}
              </li>
            ))}
          </ul>
        </div>

        <figure>
          <div className="card overflow-hidden" aria-hidden>
            <div className="border-b border-line px-5 py-3.5">
              <p className="text-sm font-medium text-ink">Add funds</p>
            </div>
            <div className="space-y-4 p-5">
              <div>
                <p className="text-label text-ink-soft">Amount to add</p>
                <div className="mt-1.5 flex h-11 items-center rounded-lg border border-line-strong px-3.5 text-base text-ink">
                  <span className="text-ink-muted">GH₵</span>
                  <span className="tabular ml-2 font-semibold">50.00</span>
                </div>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {["10", "20", "50", "100"].map((amount) => (
                  <span
                    key={amount}
                    className={
                      amount === "50"
                        ? "tabular rounded-lg border border-brand-600 bg-brand-50 py-2 text-center text-sm font-medium text-brand-700 ring-1 ring-brand-600"
                        : "tabular rounded-lg border border-line py-2 text-center text-sm text-ink-soft"
                    }
                  >
                    GH₵ {amount}
                  </span>
                ))}
              </div>
              <div>
                <p className="text-label text-ink-soft">Mobile Money number</p>
                <div className="mt-1.5 flex h-11 items-center rounded-lg border border-line-strong px-3.5 text-base text-ink">
                  <span className="tabular">024 123 4567</span>
                  <span className="ml-auto rounded-md bg-sunken px-2 py-0.5 text-caption font-medium text-ink-soft">
                    MTN
                  </span>
                </div>
              </div>
              <div className="rounded-lg bg-brand-600 py-3 text-center text-sm font-medium text-white">
                Pay GH₵ 50.00
              </div>
            </div>
          </div>
          <figcaption className="mt-3 text-caption text-ink-muted">
            The Add funds screen. A prompt then appears on your phone.
          </figcaption>
        </figure>
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
    <section id="pricing" className="container-page scroll-mt-20 py-16 sm:py-20">
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

        <div>
          <h3 className="text-sm font-semibold text-ink">What a price is made of</h3>
          <dl className="mt-3 divide-y divide-line border-y border-line">
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
  const controls = [
    {
      title: "Payments you can prove",
      body: "A deposit is credited only after we verify a signed confirmation from the payment provider. Nothing your browser says can credit a wallet.",
    },
    {
      title: "An append-only ledger",
      body: "Every movement of money is an entry with a running balance. Balances are re-derived from it on a schedule, and any difference raises an alert.",
    },
    {
      title: "Accounts protected properly",
      body: "Passwords are hashed with Argon2, sessions live in cookies scripts cannot read, and repeated failed sign-ins lock an account for a while.",
    },
    {
      title: "Least privilege for staff",
      body: "Adjusting a balance or issuing a refund needs an elevated role and a written reason, and every such action is kept permanently.",
    },
    {
      title: "Minimal data",
      body: "We keep what a payment and a support conversation need, and no more. Verification codes are never written to our logs.",
    },
    {
      title: "Limits that stop a takeover",
      body: "Deposit caps, daily spending limits and order rate limits protect you and the platform if an account is compromised.",
    },
  ];

  return (
    <section id="security" className="scroll-mt-20 border-y border-line bg-surface">
      <div className="container-page py-16 sm:py-20">
        <h2 className="max-w-xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          How your money is protected
        </h2>
        <dl className="mt-10 grid grid-cols-1 gap-x-12 md:grid-cols-2">
          {controls.map((control) => (
            <div key={control.title} className="border-t border-line py-5">
              <dt className="text-sm font-semibold text-ink">{control.title}</dt>
              <dd className="mt-1.5 text-sm leading-relaxed text-ink-muted">{control.body}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="container-page py-16 sm:py-20">
      <div className="flex flex-col gap-6 border-t border-line pt-10 lg:flex-row lg:items-end lg:justify-between">
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
      <p className="mt-8 max-w-3xl text-caption text-ink-faint">
        By creating an account you agree to our Terms of Service and Acceptable Use Policy.
        VerifyGH may not be used for fraud, impersonation, spam, or evading platform security or
        identity checks.
      </p>
    </section>
  );
}
