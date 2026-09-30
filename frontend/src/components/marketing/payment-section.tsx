"use client";

import useSWR from "swr";

import { CheckCircleIcon, LockIcon } from "@/components/icons";
import { Skeleton } from "@/components/ui/primitives";
import type { PaymentOptions } from "@/lib/types";

/**
 * Paying in cedis, the way people here already pay.
 *
 * The networks come from the live payment options - the same list the Add
 * funds screen uses - so this section can only ever name a network that is
 * actually supported today. Names, not logos: the networks' marks belong to
 * them.
 */
export function PaymentSection() {
  const { data, error } = useSWR<PaymentOptions>("/payments/options/");

  return (
    <section className="border-y border-line bg-surface">
      <div className="container-page grid grid-cols-1 gap-12 py-16 sm:py-24 lg:grid-cols-2 lg:items-center">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            Fund your wallet with the Mobile Money you already use
          </h2>
          <p className="mt-4 text-base leading-relaxed text-ink-muted">
            No card and no crypto. Top up in cedis from your MoMo wallet, then pay for numbers
            straight from your balance.
          </p>

          <div className="mt-6">
            <p className="text-label text-ink-muted">Supported networks</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {data
                ? data.networks.map((network) => (
                    <li
                      key={network.value}
                      className="inline-flex h-10 items-center rounded-lg border border-line bg-canvas px-3.5 text-sm font-medium text-ink"
                    >
                      {network.label}
                    </li>
                  ))
                : error
                  ? (
                      <li className="text-sm text-ink-muted">
                        MTN, Telecel and AT Money - the live list is on the Add funds screen.
                      </li>
                    )
                  : [0, 1, 2].map((key) => (
                      <li key={key}>
                        <Skeleton className="h-10 w-32" />
                      </li>
                    ))}
            </ul>
          </div>

          <ul className="mt-6 space-y-3">
            {[
              "Type your number the way you normally write it - 024 123 4567 works.",
              "Your network is filled in from the number. Change it if you have moved networks.",
              "Approve the prompt on your phone. Your balance updates once the network confirms it.",
            ].map((line) => (
              <li key={line} className="flex gap-3 text-sm text-ink-soft">
                <CheckCircleIcon className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                {line}
              </li>
            ))}
            <li className="flex gap-3 text-sm text-ink-soft">
              <LockIcon className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
              Payments are processed by Paystack. Your PIN goes into your own phone and never passes
              through VerifyGH.
            </li>
          </ul>
        </div>

        <figure>
          <div className="card overflow-hidden shadow-raised" aria-hidden>
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
                        ? "tabular rounded-lg border border-brand-500 bg-brand-50 py-2 text-center text-sm font-medium text-brand-700 ring-1 ring-brand-500"
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
              <div className="rounded-lg bg-primary py-3 text-center text-sm font-medium text-white">
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
