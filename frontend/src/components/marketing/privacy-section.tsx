"use client";

import useSWR from "swr";

import { CheckCircleIcon, LockIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import type { MarketHome } from "@/lib/types";

import { Reveal } from "./device";

/**
 * The privacy promise, drawn: your own number on one side, the number the
 * app sees on the other, and between them a shield ringed with the layers
 * that actually protect an account. A navy section mid-page - the page ramps
 * up into it and back down out of it (atmosphere-night-mid).
 *
 * Every layer named is something the code does (docs/SECURITY.md). Invented:
 * the example numbers.
 */

const LAYERS = [
  "HTTPS on every page",
  "Cookies scripts can't read",
  "Argon2-hashed passwords",
  "Payments confirmed by Paystack",
  "Every cedi on a ledger",
];

/** Where the layer labels sit around the shield from lg (percent of the stage). */
const LAYER_SLOTS = [
  { left: "50%", top: "2%" },
  { left: "93%", top: "34%" },
  { left: "80%", top: "88%" },
  { left: "20%", top: "88%" },
  { left: "7%", top: "34%" },
];

export function PrivacySection() {
  const { data } = useSWR<MarketHome>("/marketplace/home/");
  const whatsapp = data?.popular.find((row) => row.slug === "whatsapp");

  return (
    <section
      id="security"
      className="atmosphere-night-mid scroll-mt-20 overflow-x-clip text-white"
      aria-labelledby="privacy-heading"
    >
      {/* The padding holds the content inside the navy: at least --fade-in
          above and --fade-out below. */}
      <div className="container-page pb-[21rem] pt-[21rem] sm:pb-[27rem] sm:pt-[27rem]">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 id="privacy-heading" className="text-balance text-3xl font-extrabold tracking-[-0.03em] text-white sm:text-5xl">
            Your number. Your account. <span className="text-dawn">Protected.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-pretty text-base leading-relaxed text-white/70 sm:text-lg">
            Your personal number stays private while VerifyGH handles the verification. The app
            you sign up to only ever sees ours.
          </p>
        </Reveal>

        <Reveal>
          <div className="mt-14 grid grid-cols-1 items-center gap-6 lg:grid-cols-[1fr_auto_1fr] lg:gap-4">
            {/* Yours */}
            <GlassCard>
              <p className="text-[0.625rem] font-bold uppercase tracking-[0.14em] text-[#ff8a8a]">Your number</p>
              <p className="code mt-2 text-xl font-semibold tracking-wide text-white">+233 24 ••• ••••</p>
              <p className="mt-2 flex items-center gap-1.5 text-caption text-white/60">
                <LockIcon className="h-3.5 w-3.5 text-leaf-light" />
                Stays with you - only used for your MoMo top-ups
              </p>
            </GlassCard>

            {/* The shield, with the layers around it */}
            <div className="relative mx-auto flex h-[19rem] w-full max-w-[26rem] items-center justify-center lg:h-[24rem] lg:w-[26rem]">
              <Connector className="left-0 hidden lg:block" />
              <Connector className="right-0 hidden lg:block" />
              {/* Phones: the same lines, running down the page */}
              <VerticalConnector className="top-0 lg:hidden" />
              <VerticalConnector className="bottom-0 lg:hidden" />
              <Shield />
              {LAYERS.map((layer, index) => (
                <span
                  key={layer}
                  className="absolute hidden -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border border-white/15 bg-white/[0.07] px-3 py-1.5 text-2xs font-medium text-white/80 backdrop-blur lg:block"
                  style={LAYER_SLOTS[index]}
                >
                  {layer}
                </span>
              ))}
            </div>

            {/* Ours, and what it gets you */}
            <GlassCard>
              <p className="text-[0.625rem] font-bold uppercase tracking-[0.14em] text-aqua">What the app sees</p>
              <p className="code mt-2 text-xl font-semibold tracking-wide text-white">+1 (512) 555-0147</p>
              <div className="mt-3 flex items-center gap-2.5 rounded-xl bg-white/[0.06] p-2">
                <ServiceLogo
                  name="WhatsApp"
                  src={whatsapp?.icon_url ?? "/service-icons/whatsapp.svg"}
                  slug="whatsapp"
                  size="xs"
                />
                <span className="min-w-0 flex-1 text-caption text-white/75">WhatsApp</span>
                <span className="flex items-center gap-1 text-caption font-semibold text-leaf-light">
                  <CheckCircleIcon className="h-3.5 w-3.5" /> Code received
                </span>
              </div>
            </GlassCard>
          </div>

          {/* Phones and tablets: the layers as a row under the shield */}
          <ul className="mx-auto mt-8 flex max-w-xl flex-wrap justify-center gap-2 lg:hidden">
            {LAYERS.map((layer) => (
              <li
                key={layer}
                className="rounded-full border border-white/15 bg-white/[0.07] px-3 py-1.5 text-2xs font-medium text-white/80"
              >
                {layer}
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </section>
  );
}

function GlassCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-sm rounded-3xl border border-white/10 bg-white/[0.05] p-5 shadow-[0_30px_60px_-30px_rgba(0,0,0,0.8)] backdrop-blur-md">
      {children}
    </div>
  );
}

/** A line from a card into the shield, with light running along it. */
function Connector({ className }: { className: string }) {
  return (
    <svg aria-hidden viewBox="0 0 80 8" className={`absolute top-1/2 h-2 w-16 -translate-y-1/2 ${className}`} preserveAspectRatio="none">
      <line x1="0" y1="4" x2="80" y2="4" stroke="rgba(255,255,255,0.15)" strokeWidth="2" />
      <line className="flow-dash" x1="0" y1="4" x2="80" y2="4" stroke="#28C7F7" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function VerticalConnector({ className }: { className: string }) {
  return (
    <svg aria-hidden viewBox="0 0 8 40" className={`absolute left-1/2 h-8 w-2 -translate-x-1/2 ${className}`} preserveAspectRatio="none">
      <line x1="4" y1="0" x2="4" y2="40" stroke="rgba(255,255,255,0.15)" strokeWidth="2" />
      <line className="flow-dash" x1="4" y1="0" x2="4" y2="40" stroke="#28C7F7" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/** The shield: breathing rings of light, a glass shield, a lock. */
function Shield() {
  return (
    <div className="relative flex h-64 w-64 items-center justify-center" aria-hidden>
      {/* Rings */}
      <span className="shield-breathe absolute inset-0 rounded-full border border-aqua/25" />
      <span className="shield-breathe absolute inset-6 rounded-full border border-leaf/30" style={{ animationDelay: "1.2s" }} />
      <span className="absolute inset-10 rounded-full bg-[radial-gradient(closest-side,rgba(8,120,209,0.55),rgba(32,178,107,0.15)_65%,transparent)] blur-md" />

      <svg viewBox="0 0 120 140" className="relative h-40 w-36 drop-shadow-[0_20px_40px_rgba(8,120,209,0.55)]">
        <defs>
          <linearGradient id="shield-fill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#0B63B6" />
            <stop offset="0.55" stopColor="#0E8BA8" />
            <stop offset="1" stopColor="#137A4E" />
          </linearGradient>
          <linearGradient id="shield-edge" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#ffffff" stopOpacity="0.6" />
            <stop offset="1" stopColor="#ffffff" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        <path
          d="M60 4 108 22v38c0 34-20 60-48 76C32 120 12 94 12 60V22z"
          fill="url(#shield-fill)"
          stroke="url(#shield-edge)"
          strokeWidth="2"
        />
        {/* Glass highlight */}
        <path d="M60 10 102 26v10C84 34 66 42 18 70V26z" fill="#ffffff" opacity="0.08" />
        {/* Lock */}
        <rect x="42" y="62" width="36" height="30" rx="6" fill="#ffffff" />
        <path d="M49 62v-8a11 11 0 0 1 22 0v8" fill="none" stroke="#ffffff" strokeWidth="5" strokeLinecap="round" />
        <circle cx="60" cy="75" r="4" fill="#0B63B6" />
        <rect x="58.2" y="76" width="3.6" height="9" rx="1.8" fill="#0B63B6" />
      </svg>
    </div>
  );
}
