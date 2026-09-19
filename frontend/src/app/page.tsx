import Link from "next/link";

import {
  BoltIcon,
  CheckCircleIcon,
  ClockIcon,
  LockIcon,
  PhoneIcon,
  ReceiptIcon,
  ShieldIcon,
  WalletIcon,
} from "@/components/icons";
import { Faq } from "@/components/marketing/faq";
import { FeaturedServices } from "@/components/marketing/featured-services";
import { FlowDiagram } from "@/components/marketing/flow-diagram";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { Button } from "@/components/ui/primitives";

export default function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main id="main" className="flex-1">
        <Hero />
        <TrustStrip />
        <HowItWorks />
        <FeaturedServices />
        <MomoExplainer />
        <WhyVerifyGH />
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
    <section className="relative overflow-hidden">
      {/* A single soft wash behind the hero - restraint over gradient soup. */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[480px] bg-[radial-gradient(ellipse_at_top,_rgba(15,122,85,0.10),_transparent_60%)]"
        aria-hidden
      />
      <div className="container-page relative grid gap-12 py-14 sm:py-20 lg:grid-cols-2 lg:items-center lg:gap-16">
        <div>
          <span className="inline-flex items-center gap-2 rounded-full border border-brand-100 bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-500" aria-hidden />
            Built in Ghana, for Ghana
          </span>

          <h1 className="mt-5 text-4xl font-semibold leading-[1.1] tracking-tight text-ink sm:text-5xl lg:text-[3.4rem]">
            Verification made simple.
          </h1>

          <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-soft">
            Access supported verification services and pay conveniently with Ghana Mobile Money.
            No foreign card. No cryptocurrency. Just cedis.
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/register" className="sm:w-auto">
              <Button size="lg" fullWidth className="sm:w-auto">
                Get Started
              </Button>
            </Link>
            <Link href="/services" className="sm:w-auto">
              <Button size="lg" variant="secondary" fullWidth className="sm:w-auto">
                View Services
              </Button>
            </Link>
          </div>

          <dl className="mt-10 grid max-w-md grid-cols-3 gap-4 border-t border-line pt-6">
            <HeroStat label="Pay with" value="MoMo" />
            <HeroStat label="Priced in" value="Cedis" />
            <HeroStat label="Cards needed" value="None" />
          </dl>
        </div>

        <div className="lg:pl-4">
          <FlowDiagram />
        </div>
      </div>
    </section>
  );
}

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-1 text-lg font-semibold text-ink">{value}</dd>
    </div>
  );
}

function TrustStrip() {
  const items = [
    { icon: <WalletIcon className="h-4 w-4" />, label: "MTN, Telecel and AT Money" },
    { icon: <LockIcon className="h-4 w-4" />, label: "We never see your MoMo PIN" },
    { icon: <ReceiptIcon className="h-4 w-4" />, label: "Every transaction receipted" },
    { icon: <CheckCircleIcon className="h-4 w-4" />, label: "Automatic refunds on failure" },
  ];
  return (
    <section className="border-y border-line bg-surface">
      <div className="container-page">
        <ul className="no-scrollbar flex gap-6 overflow-x-auto py-4 sm:justify-between">
          {items.map((item) => (
            <li
              key={item.label}
              className="flex shrink-0 items-center gap-2 text-sm text-ink-muted"
            >
              <span className="text-brand-600">{item.icon}</span>
              {item.label}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    {
      title: "Choose a service",
      body: "Browse the live catalogue, pick a service and a country. The price in cedis is shown before you commit to anything.",
      icon: <PhoneIcon className="h-5 w-5" />,
    },
    {
      title: "Pay with MoMo",
      body: "Top up your wallet from MTN, Telecel or AT Money. Approve the prompt on your phone and the balance appears.",
      icon: <WalletIcon className="h-5 w-5" />,
    },
    {
      title: "Receive your number",
      body: "We place the order with our authorised provider and assign you a number, usually within seconds.",
      icon: <BoltIcon className="h-5 w-5" />,
    },
    {
      title: "Receive the code",
      body: "When the verification message arrives, it appears on your order screen - where our provider agreement permits it.",
      icon: <CheckCircleIcon className="h-5 w-5" />,
    },
  ];

  return (
    <section id="how-it-works" className="container-page scroll-mt-20 py-16 sm:py-20">
      <div className="max-w-xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">
          How it works
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          Four steps, and none of them involve a bank
        </h2>
      </div>

      <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((step, index) => (
          <li key={step.title} className="card relative p-5">
            <span className="absolute right-4 top-4 text-3xl font-semibold text-line">
              {index + 1}
            </span>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              {step.icon}
            </div>
            <h3 className="mt-4 text-base font-semibold text-ink">{step.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function MomoExplainer() {
  return (
    <section className="border-y border-line bg-surface">
      <div className="container-page grid gap-10 py-16 sm:py-20 lg:grid-cols-2 lg:items-center">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">
            Pay with Mobile Money
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            The payment method you already use
          </h2>
          <p className="mt-4 text-base leading-relaxed text-ink-muted">
            Most verification platforms assume you hold a US card or a crypto wallet. Almost nobody
            in Ghana does, and almost everybody has Mobile Money. So that is what we built around.
          </p>

          <ul className="mt-6 space-y-3">
            {[
              "Enter your number the way you normally write it - 024 123 4567 works.",
              "We detect your network from the prefix, so there is nothing to select.",
              "Approve the prompt on your phone. Your balance updates once the network confirms it.",
              "Your PIN is entered on your own handset and never passes through VerifyGH.",
            ].map((line) => (
              <li key={line} className="flex gap-3 text-sm text-ink-soft">
                <CheckCircleIcon className="mt-0.5 h-5 w-5 shrink-0 text-brand-500" />
                {line}
              </li>
            ))}
          </ul>
        </div>

        <div className="card overflow-hidden">
          <div className="border-b border-line px-5 py-4">
            <p className="text-sm font-semibold text-ink">Add money</p>
            <p className="text-xs text-ink-muted">Mobile Money - Ghana</p>
          </div>
          <div className="space-y-4 p-5">
            <div>
              <p className="text-xs font-medium text-ink-soft">Mobile Money number</p>
              <div className="mt-1.5 flex h-12 items-center rounded-xl border border-line-strong px-3.5 text-base text-ink">
                024 123 4567
                <span className="ml-auto rounded-full bg-gold-100 px-2.5 py-1 text-xs font-medium text-gold-700">
                  MTN
                </span>
              </div>
            </div>
            <div>
              <p className="text-xs font-medium text-ink-soft">Amount</p>
              <div className="mt-1.5 flex h-12 items-center rounded-xl border border-line-strong px-3.5 text-base text-ink">
                <span className="text-ink-muted">&#8373;</span>
                <span className="ml-1 tabular font-medium">50.00</span>
              </div>
            </div>
            <div className="flex gap-2">
              {["10", "20", "50", "100"].map((amount) => (
                <span
                  key={amount}
                  className={
                    amount === "50"
                      ? "flex-1 rounded-lg bg-brand-50 py-2 text-center text-sm font-medium text-brand-700"
                      : "flex-1 rounded-lg bg-line/40 py-2 text-center text-sm text-ink-muted"
                  }
                >
                  &#8373;{amount}
                </span>
              ))}
            </div>
            <div className="rounded-xl bg-brand-600 py-3 text-center text-sm font-medium text-white">
              Send payment prompt
            </div>
            <p className="text-center text-xs text-ink-faint">
              You will be asked to approve on your phone.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function WhyVerifyGH() {
  const reasons = [
    {
      title: "Built for cedis, not converted to them",
      body: "Prices are quoted, charged and refunded in GHS. You never do the exchange-rate maths, and the rate is locked onto your order at the moment you buy.",
      icon: <WalletIcon className="h-5 w-5" />,
    },
    {
      title: "Automatic refunds",
      body: "If the provider cannot supply a number, or none arrives before your order expires, the money is back in your wallet without you asking.",
      icon: <ReceiptIcon className="h-5 w-5" />,
    },
    {
      title: "A live order screen",
      body: "Watch the order move from payment to number assigned to code received, with a countdown. No refreshing and hoping.",
      icon: <ClockIcon className="h-5 w-5" />,
    },
    {
      title: "Honest availability",
      body: "We show what our provider actually has. Out of stock says out of stock, rather than taking your money and failing later.",
      icon: <CheckCircleIcon className="h-5 w-5" />,
    },
    {
      title: "Records you can check",
      body: "Every deposit, purchase and refund has a reference, a timestamp and a running balance. Support can trace any cedi.",
      icon: <ShieldIcon className="h-5 w-5" />,
    },
    {
      title: "Works on the phone you own",
      body: "Designed for a 5-inch screen on mobile data first, and the desktop layout came second. Not a desktop site squeezed down.",
      icon: <PhoneIcon className="h-5 w-5" />,
    },
  ];

  return (
    <section className="container-page py-16 sm:py-20">
      <div className="max-w-xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">
          Why VerifyGH
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          The details that decide whether you trust us
        </h2>
      </div>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {reasons.map((reason) => (
          <div key={reason.title} className="card p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              {reason.icon}
            </div>
            <h3 className="mt-4 text-base font-semibold text-ink">{reason.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">{reason.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Pricing() {
  return (
    <section id="pricing" className="border-y border-line bg-surface">
      <div className="container-page grid gap-10 py-16 sm:py-20 lg:grid-cols-2 lg:items-start">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">Pricing</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            One price. No surprises at checkout.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-ink-muted">
            There is no subscription and no sign-up fee. You pay per verification number, and the
            price you see on the card is the amount deducted from your wallet - the exchange rate,
            our margin and the Mobile Money collection fee are already inside it.
          </p>
          <p className="mt-4 text-base leading-relaxed text-ink-muted">
            Prices move with the provider&apos;s cost and the cedi. They are recalculated
            continuously and frozen onto your order the moment you buy, so a rate change mid-order
            can never change what you were charged.
          </p>
          <Link href="/services" className="mt-6 inline-block">
            <Button variant="secondary">See live prices</Button>
          </Link>
        </div>

        <div className="card p-5 sm:p-6">
          <p className="text-sm font-semibold text-ink">What makes up a price</p>
          <ul className="mt-4 space-y-3 text-sm">
            <PriceRow label="Provider cost" note="What our upstream provider charges us, in USD" />
            <PriceRow label="Converted to cedis" note="At the current USD/GHS rate" />
            <PriceRow label="Platform margin" note="How VerifyGH stays running" />
            <PriceRow label="Mobile Money fee" note="The collection fee we absorb for you" />
            <PriceRow label="Failure buffer" note="Funds the automatic refunds" />
          </ul>
          <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
            <span className="text-sm font-semibold text-ink">The price you see</span>
            <span className="rounded-lg bg-brand-50 px-3 py-1.5 text-sm font-semibold text-brand-700">
              In cedis, all in
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function PriceRow({ label, note }: { label: string; note: string }) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-300" aria-hidden />
      <span>
        <span className="font-medium text-ink">{label}</span>
        <span className="block text-ink-muted">{note}</span>
      </span>
    </li>
  );
}

function Security() {
  const controls = [
    {
      title: "Payments you can prove",
      body: "A deposit is only credited after we verify a cryptographically signed confirmation from the payment provider. Nothing your browser says can credit your wallet.",
    },
    {
      title: "An immutable ledger",
      body: "Every movement of money is an append-only entry with a running balance. Balances are re-derived from that ledger on a schedule and any discrepancy is alerted on.",
    },
    {
      title: "Accounts protected properly",
      body: "Passwords are hashed with Argon2, sessions ride in cookies JavaScript cannot read, and repeated failed sign-ins lock an account temporarily.",
    },
    {
      title: "Least privilege internally",
      body: "Our own staff roles are separated. Adjusting a balance or issuing a refund requires elevated permission and a written reason, and every such action is permanently logged.",
    },
    {
      title: "Your data stays minimal",
      body: "We collect what a payment and a support conversation require - no more. Verification codes are never written to our logs.",
    },
    {
      title: "Clear limits",
      body: "Deposit caps, daily spending limits and order velocity limits protect both you and the platform from an account being taken over.",
    },
  ];

  return (
    <section id="security" className="container-page scroll-mt-20 py-16 sm:py-20">
      <div className="max-w-xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">Security</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          Treated like the money platform it is
        </h2>
      </div>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {controls.map((control) => (
          <div key={control.title} className="card p-5">
            <ShieldIcon className="h-5 w-5 text-brand-600" />
            <h3 className="mt-3 text-base font-semibold text-ink">{control.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">{control.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="container-page pb-20">
      <div className="relative overflow-hidden rounded-3xl bg-brand-700 px-6 py-12 sm:px-12 sm:py-16">
        <div
          className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-brand-500/30 blur-2xl"
          aria-hidden
        />
        <div className="relative max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
            Pay with MoMo. Verify with ease.
          </h2>
          <p className="mt-3 text-base leading-relaxed text-brand-100">
            Create an account in under a minute. There is nothing to pay until you buy your first
            verification number.
          </p>
          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <Link href="/register">
              <Button size="lg" variant="inverse" fullWidth className="sm:w-auto">
                Create free account
              </Button>
            </Link>
            <Link href="/services">
              <Button size="lg" variant="ghostInverse" fullWidth className="sm:w-auto">
                Browse services
              </Button>
            </Link>
          </div>
          <p className="mt-6 text-xs leading-relaxed text-brand-200">
            By creating an account you agree to our Terms of Service and Acceptable Use Policy.
            VerifyGH may not be used for fraud, impersonation, spam, or evading platform security
            or identity checks.
          </p>
        </div>
      </div>
    </section>
  );
}
