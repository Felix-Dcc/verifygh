"use client";

import Link from "next/link";
import * as React from "react";

import { ChevronDownIcon } from "@/components/icons";
import { cn } from "@/components/ui/primitives";

const FAQ_ITEMS: { question: string; answer: React.ReactNode }[] = [
  {
    question: "What is VerifyGH?",
    answer: (
      <>
        VerifyGH is a Ghanaian payment and access layer for supported phone verification services.
        You top up a wallet with Mobile Money in cedis, and we handle the purchase with our
        authorised upstream provider on your behalf - so you never need a foreign card or crypto.
      </>
    ),
  },
  {
    question: "How do I pay?",
    answer: (
      <>
        With Mobile Money. Enter your number and an amount, approve the prompt on your phone, and
        your VerifyGH wallet is credited. You then spend that balance on verification numbers.
      </>
    ),
  },
  {
    question: "Can I use MTN MoMo?",
    answer: <>Yes. MTN Mobile Money is supported.</>,
  },
  {
    question: "Can I use Telecel Cash or AT Money?",
    answer: (
      <>
        Yes. Telecel Cash and AT Money are supported alongside MTN. We detect your network from
        your number, so there is nothing extra to choose. The live list of supported networks is
        always shown on the Add money screen.
      </>
    ),
  },
  {
    question: "Do I need a Visa or Mastercard?",
    answer: <>No. Mobile Money is all you need. We do not ask for card details at all.</>,
  },
  {
    question: "Do I need cryptocurrency?",
    answer: (
      <>
        No. You never touch crypto, USD or an exchange. You pay in cedis and you see prices in
        cedis. The currency conversion happens on our side.
      </>
    ),
  },
  {
    question: "How long does a verification number last?",
    answer: (
      <>
        It depends on the service, and the exact window is shown on your order screen with a live
        countdown - typically around 20 minutes. Use the number promptly once it is assigned.
      </>
    ),
  },
  {
    question: "What happens if I do not receive a code?",
    answer: (
      <>
        If the number expires without a verification code arriving, the order is closed
        automatically and the full amount is returned to your VerifyGH wallet. You do not need to
        contact anyone for this - it happens on its own.
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
    question: "Which services are supported?",
    answer: (
      <>
        Only the services our upstream provider actually offers, and only while they are in stock.
        The{" "}
        <Link href="/services" className="font-medium text-brand-700 underline">
          services page
        </Link>{" "}
        shows the live list with real prices. We do not promise a service we cannot supply.
      </>
    ),
  },
  {
    question: "Is my payment secure?",
    answer: (
      <>
        Payments are collected by a licensed Ghanaian payment provider - we never see or store your
        MoMo PIN. A payment is only credited after we verify a signed confirmation from that
        provider directly. Every movement of money is recorded in an immutable ledger tied to your
        account.
      </>
    ),
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

export function Faq() {
  const [openIndex, setOpenIndex] = React.useState<number | null>(0);

  return (
    <section id="faq" className="container-page scroll-mt-20 py-16 sm:py-20">
      <div className="mx-auto max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">FAQ</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          Questions people actually ask
        </h2>

        <dl className="mt-8 divide-y divide-line border-y border-line">
          {FAQ_ITEMS.map((item, index) => {
            const open = openIndex === index;
            return (
              <div key={item.question}>
                <dt>
                  <button
                    type="button"
                    onClick={() => setOpenIndex(open ? null : index)}
                    aria-expanded={open}
                    aria-controls={`faq-panel-${index}`}
                    className="flex w-full items-start justify-between gap-4 py-4 text-left"
                  >
                    <span className="text-base font-medium text-ink">{item.question}</span>
                    <ChevronDownIcon
                      className={cn(
                        "mt-0.5 h-5 w-5 shrink-0 text-ink-muted transition-transform duration-200",
                        open && "rotate-180",
                      )}
                    />
                  </button>
                </dt>
                <dd
                  id={`faq-panel-${index}`}
                  hidden={!open}
                  className="pb-5 pr-8 text-sm leading-relaxed text-ink-muted"
                >
                  {item.answer}
                </dd>
              </div>
            );
          })}
        </dl>
      </div>
    </section>
  );
}
