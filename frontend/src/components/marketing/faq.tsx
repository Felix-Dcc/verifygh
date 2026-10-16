"use client";

import Link from "next/link";
import * as React from "react";

import { ChevronDownIcon, ChevronRightIcon, FlagIcon, MailIcon, RefreshIcon, WalletIcon } from "@/components/icons";
import { cn } from "@/components/ui/primitives";

import { Device, Halo, HomeIndicator, Reveal, StatusBar, usePrefersReducedMotion } from "./device";

const FAQ_ITEMS: { question: string; answer: React.ReactNode }[] = [
  {
    question: "What is VerifyGH?",
    answer: (
      <>
        VerifyGH gives you a US phone number to receive a verification code, paid for in cedis. You
        top up a wallet with Mobile Money, and we buy the number from our authorised upstream
        provider on your behalf - so you never need a foreign card or crypto.
      </>
    ),
  },
  {
    question: "How does SMS verification work?",
    answer: (
      <>
        Choose the service you are signing up to and pay its price from your wallet. A US number
        is assigned to your order: enter it in the app and ask for a code. The SMS lands on your
        order the moment it arrives, ready to copy.
      </>
    ),
  },
  {
    question: "How quickly will I receive my code?",
    answer: (
      <>
        As soon as the app sends it - the code appears on your order the moment it reaches the
        number, without refreshing. How quickly an app sends depends on the app. If nothing
        arrives before the number expires, the full price goes back to your wallet.
      </>
    ),
  },
  {
    question: "How do I fund my wallet?",
    answer: (
      <>
        With Mobile Money. Enter an amount and your number, approve the prompt on your phone, and
        your wallet is credited once the network confirms the payment. You then spend that balance
        on numbers.
      </>
    ),
  },
  {
    question: "Can I pay with Mobile Money?",
    answer: (
      <>
        Yes - MTN Mobile Money, Telecel Cash and AT Money. We fill in your network from your
        number, and you can change it if you have moved networks. The live list is always on the
        Add funds screen.
      </>
    ),
  },
  {
    question: "Do you support Visa and Mastercard?",
    answer: (
      <>
        Not at the moment. Top-ups are by Mobile Money only, so we never ask for card details. You
        do not need crypto or dollars either - every price is in cedis.
      </>
    ),
  },
  {
    question: "How long does a verification number last?",
    answer: (
      <>
        It depends on the service, and the exact window is shown on your order with a live
        countdown - typically around 20 minutes. Use the number promptly once it is assigned.
      </>
    ),
  },
  {
    question: "Can I rent a number?",
    answer: (
      <>
        Not for the long term: each number is bought for a verification. When a service allows the
        same number to receive another code, your order offers it again - as a new order with its
        own price - for as long as that window is open.
      </>
    ),
  },
  {
    question: "Is my personal phone number protected?",
    answer: (
      <>
        Yes. You give the app our US number, not yours. Your own number is only used for your
        Mobile Money top-ups, where it goes to the payment provider so it can send you the prompt.
        We never see or store your MoMo PIN.
      </>
    ),
  },
  {
    question: "What happens if I don't receive an SMS?",
    answer: (
      <>
        If the number expires without a code arriving, the order is closed automatically and the
        full amount is returned to your VerifyGH wallet. You do not need to contact anyone - it
        happens on its own.
      </>
    ),
  },
  {
    question: "Can I get a refund?",
    answer: (
      <>
        Refunds are automatic when we could not deliver: the provider had no number, the number
        expired without a code, or you cancelled before a code arrived. Once a code has been
        delivered, the service has been provided and the order is not automatically refunded. Every
        refund appears in your transaction history with a reference.
      </>
    ),
  },
  {
    question: "Can I use VerifyGH outside Ghana?",
    answer: (
      <>
        The website works wherever you are, but wallets are topped up with Ghanaian Mobile Money
        (MTN, Telecel Cash or AT Money) and every price is in cedis.
      </>
    ),
  },
  {
    question: "Do you provide an API?",
    answer: <>Not yet. VerifyGH is used through this website, on your phone or your computer.</>,
  },
  {
    question: "What can I not use VerifyGH for?",
    answer: (
      <>
        Anything our{" "}
        <Link href="/acceptable-use" className="font-medium text-brand-700 underline">
          Acceptable Use Policy
        </Link>{" "}
        prohibits: fraud, impersonation, spam, evading bans or platform security, circumventing
        identity or KYC checks, or breaching the terms of the service you are verifying with.
        Accounts doing any of that are suspended.
      </>
    ),
  },
];

/** The questions people bring up first, as they would put it - each opens its answer below. */
const ASKED = [
  { question: "Can I pay with Mobile Money?", label: "Can I pay with MoMo?" },
  { question: "What happens if I don't receive an SMS?", label: "What if no code arrives?" },
  { question: "Is my personal phone number protected?", label: "Is my number private?" },
  { question: "How long does a verification number last?", label: "How long does a number last?" },
];

const SUPPORT_EMAIL = "support@getverifygh.com";

/**
 * On the homepage: "Questions? We've got answers." beside a phone showing the
 * real Help screen, with the questions people ask first floating around it -
 * tap one and its answer opens. Embedded (the Help page): the plain list.
 */
export function Faq({ embedded = false }: { embedded?: boolean }) {
  const [openIndex, setOpenIndex] = React.useState<number | null>(0);
  const reduced = usePrefersReducedMotion();

  const ask = (question: string) => {
    const index = FAQ_ITEMS.findIndex((item) => item.question === question);
    if (index < 0) return;
    setOpenIndex(index);
    window.requestAnimationFrame(() => {
      const button = document.getElementById(`faq-q-${index}`);
      button?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
      button?.focus({ preventScroll: true });
    });
  };

  if (embedded) {
    return (
      <section id="faq" className="scroll-mt-20">
        <h2 className="text-heading text-ink">Questions people ask</h2>
        <FaqList openIndex={openIndex} onToggle={setOpenIndex} embedded />
      </section>
    );
  }

  return (
    <section id="faq" className="scroll-mt-20 overflow-x-clip" aria-labelledby="faq-heading">
      <div className="container-page grid grid-cols-1 gap-10 py-16 sm:py-24 lg:grid-cols-12 lg:gap-14">
        <Reveal className="lg:col-span-5">
          <h2 id="faq-heading" className="section-title">
            Questions people ask
          </h2>
          <p className="section-lead">
            Everything you need to know before your first verification. Tap a question to jump to
            its answer.
          </p>

          {/* Phones: the questions as a row of bubbles */}
          <div className="mt-6 flex flex-wrap gap-2 lg:hidden">
            {ASKED.map((item, index) => (
              <AskBubble key={item.label} label={item.label} tail={index % 2 ? "right" : "left"} onAsk={() => ask(item.question)} />
            ))}
          </div>

          {/* From lg: the Help screen on a phone, the questions floating around it */}
          <div className="relative mt-8 hidden h-116 lg:block">
            <Halo className="left-1/2 top-1/2 h-[110%] w-[120%] -translate-x-1/2 -translate-y-1/2" />
            <div className="absolute left-1/2 top-0 -translate-x-1/2" aria-hidden>
              <Device className="w-48">
                <HelpScreen />
              </Device>
            </div>
            {ASKED.map((item, index) => {
              const slot = BUBBLE_SLOTS[index];
              return (
                <div key={item.label} className="absolute z-10" style={slot.style}>
                  <div className="motion-safe:animate-float" style={{ animationDelay: `${slot.delay}s` }}>
                    <AskBubble label={item.label} tail={slot.tail} onAsk={() => ask(item.question)} compact />
                  </div>
                </div>
              );
            })}
          </div>

          <p className="mt-6 text-sm text-ink-muted">
            Still stuck?{" "}
            <a href={`mailto:${SUPPORT_EMAIL}`} className="link">
              Email {SUPPORT_EMAIL}
            </a>{" "}
            with your order reference.
          </p>
        </Reveal>

        <Reveal className="lg:col-span-7">
          <FaqList openIndex={openIndex} onToggle={setOpenIndex} />
        </Reveal>
      </div>
    </section>
  );
}

const BUBBLE_SLOTS: { style: React.CSSProperties; delay: number; tail: "left" | "right" }[] = [
  { style: { left: "-3%", top: "1%" }, delay: 0, tail: "right" },
  { style: { right: "-3%", top: "30%" }, delay: 1.3, tail: "left" },
  { style: { left: "-2%", top: "57%" }, delay: 0.6, tail: "right" },
  { style: { right: "-2%", top: "80%" }, delay: 1.9, tail: "left" },
];

/** A question in a speech bubble; the tail points toward the phone. */
function AskBubble({
  label,
  tail,
  onAsk,
  compact = false,
}: {
  label: string;
  tail: "left" | "right";
  onAsk: () => void;
  /** Beside the phone: two lines at most, so it only overlaps the device's edge. */
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onAsk}
      className={cn(
        "min-h-11 rounded-2xl bg-surface text-left font-medium text-ink shadow-raised ring-1 ring-line transition-shadow hover:ring-brand-500 focus-visible:ring-2 focus-visible:ring-brand-500",
        compact ? "max-w-38 px-3.5 py-2 text-[0.8125rem] leading-snug" : "px-4 py-2.5 text-sm",
        tail === "left" ? "rounded-bl-md" : "rounded-br-md",
      )}
    >
      {label}
    </button>
  );
}

/** The Help page on a phone: a person to email, and the problems people actually have. */
function HelpScreen() {
  const problems = [
    { Icon: RefreshIcon, title: "The code never arrived" },
    { Icon: FlagIcon, title: "The number is already used" },
    { Icon: WalletIcon, title: "I paid but my balance has not changed" },
  ];
  return (
    <>
      <StatusBar />
      <div className="flex min-h-0 flex-1 flex-col gap-2.5 px-3 pt-2">
        <div className="px-0.5">
          <p className="text-sm font-semibold text-ink">Help and support</p>
          <p className="text-[0.5625rem] text-ink-muted">Answers to common problems, and how to reach us.</p>
        </div>
        <div className="rounded-xl border border-line bg-surface p-2.5">
          <p className="text-caption font-semibold text-ink">Talk to a person</p>
          <p className="mt-0.5 text-[0.5625rem] leading-snug text-ink-muted">
            Include your order reference - it starts with VGH-.
          </p>
          <span className="mt-2 flex h-7 items-center justify-center gap-1 rounded-full bg-primary text-[0.625rem] font-semibold text-white">
            <MailIcon className="h-3 w-3" /> Email support
          </span>
        </div>
        <p className="px-0.5 text-[0.625rem] font-medium text-ink-soft">Common problems</p>
        <div className="divide-y divide-line rounded-xl border border-line bg-surface">
          {problems.map(({ Icon, title }) => (
            <div key={title} className="flex items-center gap-2 px-2.5 py-2">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-sunken text-ink-soft">
                <Icon className="h-3 w-3" />
              </span>
              <span className="min-w-0 flex-1 text-[0.625rem] font-medium leading-snug text-ink">{title}</span>
              <ChevronRightIcon className="h-3 w-3 shrink-0 text-ink-faint" />
            </div>
          ))}
        </div>
      </div>
      <HomeIndicator />
    </>
  );
}

/** The questions themselves: roomy on the homepage, the plain divided list on the Help page. */
function FaqList({
  openIndex,
  onToggle,
  embedded = false,
}: {
  openIndex: number | null;
  onToggle: (index: number | null) => void;
  embedded?: boolean;
}) {
  return (
    <dl className={embedded ? "mt-3 divide-y divide-line border-y border-line" : "space-y-1.5"}>
      {FAQ_ITEMS.map((item, index) => {
        const open = openIndex === index;
        return (
          <div
            key={item.question}
            className={cn(
              !embedded && "rounded-2xl border transition-colors duration-200",
              !embedded && (open ? "border-line bg-surface shadow-card" : "border-transparent hover:bg-sunken/60"),
            )}
          >
            <dt>
              <button
                id={`faq-q-${index}`}
                type="button"
                onClick={() => onToggle(open ? null : index)}
                aria-expanded={open}
                aria-controls={`faq-panel-${index}`}
                className={cn(
                  "flex w-full items-center justify-between gap-4 text-left",
                  embedded ? "py-4" : "min-h-12 px-4 py-3",
                )}
              >
                <span className={cn("font-medium text-ink", embedded ? "text-base" : "text-[0.9375rem]")}>
                  {item.question}
                </span>
                <span
                  className={cn(
                    "flex shrink-0 items-center justify-center",
                    !embedded && "h-7 w-7 rounded-full transition-colors",
                    !embedded && (open ? "bg-brand-50 text-brand-700" : "bg-sunken text-ink-muted"),
                  )}
                >
                  <ChevronDownIcon
                    className={cn(
                      "transition-transform duration-200",
                      embedded ? "h-5 w-5 text-ink-muted" : "h-4 w-4",
                      open && "rotate-180",
                    )}
                  />
                </span>
              </button>
            </dt>
            <dd
              id={`faq-panel-${index}`}
              hidden={!open}
              className={cn(
                "text-sm leading-relaxed text-ink-muted",
                embedded ? "pb-5 pr-8" : "px-4 pb-4 pr-12",
              )}
            >
              {item.answer}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
