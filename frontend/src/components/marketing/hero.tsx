"use client";

import * as React from "react";
import useSWR from "swr";

import { useAuth } from "@/components/auth-provider";
import { Logomark } from "@/components/brand";
import { CheckCircleIcon, CopyIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, LiveDot } from "@/components/ui/primitives";
import type { MarketHome, MarketPage, MarketRow } from "@/lib/types";

import { Device, HomeIndicator, StatusBar, useInView, usePrefersReducedMotion } from "./device";
import { PhoneOrbit, Stars } from "./orbit";
import { pickerKey } from "./service-picker";

/**
 * The homepage hero, at night: what VerifyGH is in one line ("Don't give out
 * your number. Use ours."), and at its centre a phone receiving a
 * verification code on one of our numbers, with the services on sale today
 * revolving around it. The navy ramps down through blue, cyan and green into
 * the page (atmosphere-night in globals.css).
 *
 * Live: the service count and every logo. Invented, and only these: the
 * example number (from the 555 range kept for fiction) and its code.
 */

const EXAMPLE_NUMBER = "+1 (512) 555-0147";
const EXAMPLE_CODE = "842917";
const REPLAY_MS = 8000;

export function Hero() {
  const { user } = useAuth();
  const { data: home } = useSWR<MarketHome>("/marketplace/home/");
  const country = home?.country ?? "";
  // The same first page the service picker opens with: one request serves both.
  const { data: page } = useSWR<MarketPage>(country ? pickerKey(country) : null);

  // Popular first, then the rest of what is on sale, each logo once.
  const seen = new Set<string>();
  const logos = [...(home?.popular ?? []), ...(page?.results ?? [])]
    .filter((row) => row.icon_url && !row.temporarily_unavailable && row.availability !== "UNAVAILABLE")
    .filter((row) => (seen.has(row.slug) ? false : (seen.add(row.slug), true)))
    .slice(0, 12);
  const whatsapp = [...(home?.popular ?? []), ...(page?.results ?? [])].find((row) => row.slug === "whatsapp");

  return (
    <section className="atmosphere-night relative overflow-x-clip text-white">
      <Stars />
      {/* From lg the text sits high and the phone runs on below it into the
          ramp - white text has to stay on the navy. */}
      <div className="container-page relative grid grid-cols-1 items-center gap-2 pb-24 pt-10 sm:pt-14 lg:grid-cols-2 lg:items-start lg:gap-8 lg:pb-40 lg:pt-14">
        <div className="text-center lg:pt-8 lg:text-left">
          <p className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.06] px-3.5 py-1.5 text-caption font-medium text-white/85 backdrop-blur">
            <span className="relative flex h-2 w-2">
              <span className="absolute inset-0 animate-pulse-ring rounded-full bg-leaf-light/60" />
              <span className="relative h-2 w-2 rounded-full bg-leaf-light" />
            </span>
            {home?.total ? `Codes from ${home.total} services, paid in cedis` : "SMS codes, paid in cedis"}
          </p>

          <h1 className="mt-6 text-balance text-[2.6rem] font-extrabold leading-[1.05] tracking-[-0.035em] text-white sm:text-6xl lg:text-[3.6rem] xl:text-[4rem]">
            Don&apos;t give out your number. <span className="text-dawn">Use ours.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-lg text-pretty text-lg leading-relaxed text-white/75 lg:mx-0">
            Receive SMS verification codes on a US number, without exposing your personal phone
            number. Pay in cedis with Mobile Money.
          </p>

          <div className="mt-8 flex flex-col items-stretch gap-3 sm:flex-row sm:justify-center lg:justify-start">
            <ButtonLink
              href={user ? "/services" : "/register"}
              size="lg"
              variant="dawn"
              className="group sm:w-auto"
            >
              {user ? "Buy a number" : "Get started free"}
              <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
                →
              </span>
            </ButtonLink>
            <ButtonLink href={user ? "/dashboard" : "/login"} size="lg" variant="onBandOutline" className="sm:w-auto">
              {user ? "Go to dashboard" : "Sign in"}
            </ButtonLink>
          </div>

          <a
            href="#how-it-works"
            className="group mt-5 inline-flex min-h-11 items-center gap-2.5 rounded-full text-sm font-medium text-white/80 transition-colors hover:text-white"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-full border border-white/20 bg-white/5 transition-colors group-hover:border-aqua/60">
              <svg viewBox="0 0 12 12" className="ml-0.5 h-2.5 w-2.5" fill="currentColor" aria-hidden>
                <path d="M2 1.2v9.6L10.4 6z" />
              </svg>
            </span>
            See how it works
          </a>
        </div>

        <PhoneOrbit logos={logos}>
          <Device>
            <VerificationScreen whatsapp={whatsapp} />
          </Device>
        </PhoneOrbit>
      </div>
    </section>
  );
}

/**
 * VerifyGH on the phone the moment a code lands: the number, the SMS, the
 * code filling in digit by digit, "Code received". It replays every few
 * seconds while on screen; under reduced motion it simply shows the result.
 */
function VerificationScreen({ whatsapp }: { whatsapp?: MarketRow }) {
  const [ref, inView] = useInView<HTMLDivElement>();
  const reduced = usePrefersReducedMotion();
  const [cycle, setCycle] = React.useState(0);

  React.useEffect(() => {
    if (!inView || reduced) return;
    const timer = window.setInterval(() => setCycle((value) => value + 1), REPLAY_MS);
    return () => window.clearInterval(timer);
  }, [inView, reduced]);

  return (
    <div ref={ref} className="flex min-h-0 flex-1 flex-col">
      <StatusBar />
      <div className="flex min-h-0 flex-1 flex-col gap-2.5 px-3.5 pt-1.5">
        <div className="flex items-center justify-between px-0.5">
          <span className="flex items-center gap-1.5">
            <Logomark className="h-5 w-5 text-primary" />
            <span className="text-sm font-bold tracking-tight text-ink">VerifyGH</span>
          </span>
          <span className="flex items-center gap-1 rounded-full bg-success-50 px-2 py-0.5 text-[0.625rem] font-semibold text-success-700">
            <LiveDot className="text-success-500" />
            Active
          </span>
        </div>

        <div className="rounded-2xl border border-line bg-surface p-3">
          <div className="flex items-center gap-2.5">
            {/* The bundled tile until the catalogue answers, so the mockup never shows a blank logo. */}
            <ServiceLogo
              name="WhatsApp"
              src={whatsapp?.icon_url ?? "/service-icons/whatsapp.svg"}
              slug="whatsapp"
              size="md"
            />
            <span className="min-w-0">
              <span className="block text-sm font-semibold leading-tight text-ink">WhatsApp</span>
              <span className="block text-[0.625rem] text-ink-muted">US number · SMS</span>
            </span>
          </div>
          <p className="code mt-2.5 whitespace-nowrap text-[0.9rem] font-semibold text-ink sm:text-[1.05rem]">{EXAMPLE_NUMBER}</p>
          <p className="text-[0.625rem] text-ink-muted">Assigned just now</p>
        </div>

        <div key={cycle} className="flex flex-col gap-2.5">
          <div className="drop-in rounded-2xl border border-azure/25 bg-azure/[0.07] p-3" style={{ animationDelay: "300ms" }}>
            <p className="text-[0.5625rem] font-bold uppercase tracking-[0.12em] text-azure">SMS received · now</p>
            <p className="mt-1 text-[0.6875rem] leading-snug text-ink-soft">
              Your WhatsApp code is {EXAMPLE_CODE.slice(0, 3)}-{EXAMPLE_CODE.slice(3)}. Don&apos;t share this code
              with anyone.
            </p>
          </div>

          <div className="grid grid-cols-6 gap-1.5">
            {EXAMPLE_CODE.split("").map((digit, index) => (
              <span
                key={index}
                className="rise-in code flex h-10 items-center justify-center rounded-lg border border-line-strong bg-surface text-lg font-semibold text-ink"
                style={{ animationDelay: `${900 + index * 140}ms` }}
              >
                {digit}
              </span>
            ))}
          </div>

          <p
            className="rise-in flex items-center gap-1.5 px-0.5 text-caption font-semibold text-success-700"
            style={{ animationDelay: "1850ms" }}
          >
            <CheckCircleIcon className="h-4 w-4" />
            Code received
          </p>
        </div>

        <div className="mt-auto pb-2">
          <div className="flex h-10 items-center justify-center gap-1.5 rounded-full bg-primary text-caption font-semibold text-white">
            <CopyIcon className="h-3.5 w-3.5" />
            Copy code
          </div>
        </div>
      </div>
      <HomeIndicator />
    </div>
  );
}
