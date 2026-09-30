"use client";

import useSWR from "swr";

import { CountryFlag } from "@/components/country-flag";
import { ArrowRightIcon, CheckCircleIcon, ClockIcon, CopyIcon, WalletIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { ButtonLink, cn } from "@/components/ui/primitives";
import { cedis } from "@/lib/format";
import type { MarketHome, MarketPage, MarketRow } from "@/lib/types";

import { Device, StatusBar } from "./device";
import { pickerKey } from "./service-picker";

/**
 * The homepage hero: a green band that says what VerifyGH is in one line, and
 * at its centre a phone showing the moment the product exists for - an order
 * screen the instant a WhatsApp code has arrived on a US number, paid for in
 * cedis.
 *
 * Everything in the picture that looks like data is data: the logos around
 * the phone are services on sale today (the same public catalogue the
 * marketplace uses), the price on the wallet card is today's WhatsApp price,
 * and the count in the list beside it is the real number of services. The only invented
 * values are the example number (from the 555 range kept for fiction), its
 * code and the countdown.
 */
export function Hero() {
  const { data: home } = useSWR<MarketHome>("/marketplace/home/");
  const country = home?.country ?? "";
  // The same first page the service picker below opens with: one request.
  const { data: page } = useSWR<MarketPage>(country ? pickerKey(country) : null);

  // Popular first, then the rest of what is on sale, each logo once.
  const seen = new Set<string>();
  const logos = [...(home?.popular ?? []), ...(page?.results ?? [])]
    .filter((row) => row.icon_url && !row.temporarily_unavailable && row.availability !== "UNAVAILABLE")
    .filter((row) => (seen.has(row.slug) ? false : (seen.add(row.slug), true)))
    .slice(0, SLOTS.length);

  return (
    <section className="atmosphere-hero relative overflow-hidden text-white">
      <DotField />
      {/* From lg the text sits high and the phone runs on below it, down into
          the ramp - white text has to stay on the solid green. */}
      <div className="container-page relative grid grid-cols-1 items-center gap-10 pb-12 pt-12 sm:pb-16 sm:pt-16 lg:grid-cols-2 lg:items-start lg:gap-8 lg:pb-32 lg:pt-20">
        <div className="text-center lg:pt-8 lg:text-left">
          <h1 className="text-balance text-4xl font-bold tracking-tight text-white sm:text-5xl lg:text-[2.75rem] lg:leading-[1.1] xl:text-[3.25rem]">
            A US number for your verification code. <span className="lg:block">Paid with MoMo.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg leading-relaxed text-white/80 lg:mx-0">
            For anyone in Ghana signing up to WhatsApp, TikTok, Telegram and other apps that ask
            for a US phone number. Pay in cedis. If no code arrives, the money comes back.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-center lg:justify-start">
            <ButtonLink href="/services" size="lg" variant="onBand" fullWidth className="sm:w-auto">
              Get a number
            </ButtonLink>
            <ButtonLink
              href="/#how-it-works"
              size="lg"
              variant="onBandOutline"
              fullWidth
              className="group sm:w-auto"
            >
              See how it works
              <ArrowRightIcon className="h-4 w-4 rotate-90 transition-transform group-hover:translate-y-0.5" />
            </ButtonLink>
          </div>
          <ul className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm text-white/80 lg:justify-start">
            {[
              "Pay with MoMo",
              home?.total ? `${home.total} services, priced in cedis` : "Prices in cedis",
              "Refunded if no code arrives",
            ].map((item) => (
              <li key={item} className="flex items-center gap-2">
                <CheckCircleIcon className="h-4 w-4 text-white" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        <PhoneScene
          logos={logos}
          whatsapp={[...(home?.popular ?? []), ...(page?.results ?? [])].find((row) => row.slug === "whatsapp")}
        />
      </div>
    </section>
  );
}

/**
 * Where the logos sit around the phone, as percentages of the scene. They keep
 * to the margins beside the device (and clear of the wallet card, 59-72% down
 * on the right); the small ones step aside on phones.
 */
const SLOTS: { left: number; top: number; delay: number; small?: boolean }[] = [
  { left: 7, top: 8, delay: 0 },
  { left: 93, top: 6, delay: 0.6 },
  { left: 4, top: 46, delay: 1.6 },
  { left: 94, top: 38, delay: 0.3 },
  { left: 8, top: 84, delay: 2.4 },
  { left: 14, top: 26, delay: 1.2, small: true },
  { left: 86, top: 22, delay: 2.1, small: true },
  { left: 91, top: 86, delay: 1.0, small: true },
];

function PhoneScene({ logos, whatsapp }: { logos: MarketRow[]; whatsapp?: MarketRow }) {
  return (
    // A picture of the product, not content: the facts are in the text beside it.
    <div className="relative mx-auto w-full max-w-md" aria-hidden>
      <div className="relative flex justify-center pb-10 pt-4">
        {logos.map((row, index) => {
          const slot = SLOTS[index];
          return (
            <span
              key={row.slug}
              className={cn("absolute z-10 -translate-x-1/2", slot.small ? "hidden sm:block" : "")}
              style={{ left: `${slot.left}%`, top: `${slot.top}%` }}
            >
              {/* The float has its own element: its transform would otherwise
                  replace the centring one above. */}
              <span
                className="block rounded-[23%] shadow-raised motion-safe:animate-float"
                style={{ animationDelay: `${slot.delay}s` }}
              >
                <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size={slot.small ? "sm" : "md"} />
              </span>
            </span>
          );
        })}

        <Device>
          <OrderScreen whatsapp={whatsapp} />
        </Device>

        {/* Where the money came from: the wallet, topped up with MoMo. */}
        <div className="absolute -right-2 top-[61%] z-20 hidden w-48 items-center gap-3 rounded-2xl bg-white p-3 text-left shadow-pop sm:flex">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#E8F3EE] text-[#0B6446]">
            <WalletIcon className="h-[18px] w-[18px]" />
          </span>
          <span className="min-w-0">
            <span className="tabular block text-sm font-semibold text-black">
              {whatsapp?.price ? cedis(whatsapp.price) : "Paid in cedis"}
            </span>
            <span className="block text-2xs leading-snug text-black/60">
              From your wallet, topped up with MoMo
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}

/** The order screen the moment the code has arrived, laid out as the real one is. */
function OrderScreen({ whatsapp }: { whatsapp?: MarketRow }) {
  return (
    <>
      <StatusBar />

      <div className="flex min-h-0 flex-1 flex-col gap-2.5 px-3.5 pb-2 pt-3">
        {/* Header */}
        <div className="flex items-center gap-2.5 px-0.5">
          {/* The bundled tile until the catalogue answers, so the mockup never shows a blank logo. */}
          <ServiceLogo name="WhatsApp" src={whatsapp?.icon_url ?? "/service-icons/whatsapp.svg"} slug="whatsapp" size="xs" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-tight text-ink">WhatsApp</p>
            <p className="flex items-center gap-1 text-2xs text-ink-muted">
              <CountryFlag code="US" size="sm" /> United States
            </p>
          </div>
        </div>

        {/* Number */}
        <div className="rounded-xl border border-line bg-surface p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-2xs text-ink-muted">Your number</p>
            <span className="flex items-center gap-1 rounded-md bg-sunken px-1.5 py-0.5 text-2xs text-ink-soft">
              <ClockIcon className="h-3 w-3" />
              <span className="tabular font-semibold">14:52</span>
            </span>
          </div>
          <p className="code mt-1 text-[0.95rem] font-semibold text-ink">+1 (512) 555-0147</p>
        </div>

        {/* Code */}
        <div className="rounded-xl border border-success-200 bg-success-50 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-2xs font-medium text-success-700">Verification code</p>
            <span className="flex items-center gap-1 text-2xs text-success-700">
              <span className="h-1.5 w-1.5 rounded-full bg-success-500" />
              Just now
            </span>
          </div>
          <p className="code mt-0.5 text-[1.7rem] font-semibold leading-tight tracking-[0.18em] text-success-700">
            482913
          </p>
          <p className="mt-2 rounded-lg border border-success-200 bg-surface px-2.5 py-1.5 text-2xs leading-snug text-ink-soft">
            Your WhatsApp code is 482-913. Don&apos;t share this code with anyone.
          </p>
        </div>

        <div className="mt-auto space-y-2">
          <div className="flex h-10 items-center justify-center gap-1.5 rounded-full bg-primary text-caption font-medium text-white">
            <CopyIcon className="h-3.5 w-3.5" />
            Copy code
          </div>
          <div className="flex h-9 items-center justify-center rounded-full border border-line-strong text-caption font-medium text-ink-soft">
            Mark as done
          </div>
        </div>
        {/* Home indicator */}
        <span className="mx-auto mt-1.5 block h-1 w-[36%] shrink-0 rounded-full bg-ink/80" />
      </div>
    </>
  );
}

/** A faint field of dots across the band - texture, not decoration. */
function DotField() {
  return (
    <svg className="atmosphere-dots pointer-events-none absolute inset-0 h-full w-full opacity-[0.12]" aria-hidden>
      <defs>
        <pattern id="band-dots" width="22" height="22" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.3" fill="white" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#band-dots)" />
    </svg>
  );
}
