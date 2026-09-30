"use client";

import * as React from "react";

import { GridIcon, HomeIcon, LockIcon, ReceiptIcon, UserIcon, WalletIcon } from "@/components/icons";
import { cn } from "@/components/ui/primitives";

/*
 * The homepage's one device and its motion. Every phone on the page is this
 * component showing a real VerifyGH screen, so they all look like the same
 * product photographed the same way.
 */

/**
 * A current large "Pro"-class phone, drawn in CSS: a brushed-titanium frame,
 * a thin even black bezel, the island cut-out, side keys (action, volume,
 * power and the camera key), a faint glass reflection and a soft floor
 * shadow. Proportions follow a 6.9" device (77.6 x 163 mm). The hardware
 * keeps its own colours in both themes; the screen follows the site's.
 */
export function Device({ children, className }: { children: React.ReactNode; className?: string }) {
  const metal = "bg-gradient-to-b from-[#d8d3cb] via-[#9e9890] to-[#6b665f]";
  return (
    <div className={cn("relative shrink-0", className ?? "w-[15rem] sm:w-64 lg:w-[17rem]")}>
      {/* Floor shadow, tinted green so it settles into pale surfaces rather than greying them */}
      <span className="absolute -bottom-5 left-1/2 h-10 w-4/5 -translate-x-1/2 rounded-[50%] bg-band-deep/35 blur-2xl" />

      {/* Side keys: action, volume up, volume down; power, camera key */}
      <span className={cn("absolute -left-[2px] top-[15%] h-[3.5%] w-[3px] rounded-l-[2px]", metal)} />
      <span className={cn("absolute -left-[2px] top-[22%] h-[7%] w-[3px] rounded-l-[2px]", metal)} />
      <span className={cn("absolute -left-[2px] top-[31%] h-[7%] w-[3px] rounded-l-[2px]", metal)} />
      <span className={cn("absolute -right-[2px] top-[24%] h-[10.5%] w-[3px] rounded-r-[2px]", metal)} />
      <span className="absolute -right-[1.5px] top-[52%] h-[6%] w-[2.5px] rounded-r-[2px] bg-gradient-to-b from-[#4b4843] to-[#2c2a27]" />

      {/* Frame */}
      <div
        className={cn(
          "relative aspect-[776/1630] rounded-[2.75rem] p-[3px]",
          "bg-gradient-to-br from-[#ebe7e0] via-[#a19b92] to-[#5e5a54]",
          "shadow-[inset_0_1px_1px_rgba(255,255,255,0.7),0_45px_90px_-30px_rgba(0,0,0,0.55),0_25px_45px_-25px_rgba(0,0,0,0.45)]",
        )}
      >
        {/* Bezel */}
        <div className="h-full rounded-[2.55rem] bg-black p-[5px] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]">
          {/* Screen */}
          <div className="relative flex h-full flex-col overflow-hidden rounded-[2.25rem] bg-canvas">
            {children}
            {/* Island */}
            <span className="absolute left-1/2 top-[9px] z-30 flex h-[22px] w-[28%] -translate-x-1/2 items-center justify-end rounded-full bg-black pr-2">
              <span className="h-[7px] w-[7px] rounded-full bg-[#1a1d2b] ring-1 ring-[#2b3040]" />
            </span>
            {/* Glass reflection */}
            <span className="pointer-events-none absolute inset-0 z-30 bg-gradient-to-br from-white/[0.08] via-transparent to-transparent" />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Time on the left, signal, wifi and battery on the right, the island between. */
export function StatusBar() {
  return (
    <div className="grid h-10 shrink-0 grid-cols-[1fr_28%_1fr] items-center pt-1.5 text-ink">
      <span className="tabular text-center text-[0.8125rem] font-semibold">9:41</span>
      <span />
      <span className="flex items-center justify-center gap-[3px]">
        <svg viewBox="0 0 18 12" className="h-[9px] w-[13px]" fill="currentColor">
          <rect x="0" y="8" width="3" height="4" rx="0.8" />
          <rect x="5" y="5.5" width="3" height="6.5" rx="0.8" />
          <rect x="10" y="3" width="3" height="9" rx="0.8" />
          <rect x="15" y="0" width="3" height="12" rx="0.8" />
        </svg>
        <svg viewBox="0 0 16 12" className="h-[9px] w-[12px]" fill="currentColor">
          <path d="M8 2.2c2.3 0 4.4.9 6 2.4l1.2-1.3A10.4 10.4 0 0 0 8 .4 10.4 10.4 0 0 0 .8 3.3L2 4.6a8.6 8.6 0 0 1 6-2.4Zm0 3.6c1.3 0 2.5.5 3.4 1.3l1.3-1.3A6.6 6.6 0 0 0 8 4a6.6 6.6 0 0 0-4.7 1.8l1.3 1.3c.9-.8 2.1-1.3 3.4-1.3Zm0 3.6c.4 0 .8.2 1.1.4L8 11.2 6.9 9.8c.3-.2.7-.4 1.1-.4Z" />
        </svg>
        <span className="relative ml-0.5 flex h-[10px] w-[20px] items-center rounded-[3px] border border-ink/40 p-[1.5px]">
          <span className="h-full w-[78%] rounded-[1.5px] bg-ink" />
          <span className="absolute -right-[3px] h-1 w-[1.5px] rounded-r-sm bg-ink/40" />
        </span>
      </span>
    </div>
  );
}

export function HomeIndicator() {
  return <span className="mx-auto mb-1.5 mt-1 block h-1 w-[36%] shrink-0 rounded-full bg-ink/80" />;
}

/** VerifyGH is a website: in the phone it sits under the browser's address bar. */
export function AddressBar({ marker }: { marker?: React.ReactNode }) {
  return (
    <div className="relative mx-3 mb-1 flex h-7 shrink-0 items-center justify-center gap-1 rounded-full bg-sunken text-2xs text-ink-soft">
      <LockIcon className="h-2.5 w-2.5" />
      getverifygh.com
      {marker}
    </div>
  );
}

/** The app's own bottom bar on phones, with one tab lit. */
export function BottomNav({ active }: { active: "home" | "buy" | "orders" | "wallet" | "account" }) {
  const tabs = [
    { key: "home", label: "Home", Icon: HomeIcon },
    { key: "buy", label: "Buy", Icon: GridIcon },
    { key: "orders", label: "Orders", Icon: ReceiptIcon },
    { key: "wallet", label: "Wallet", Icon: WalletIcon },
    { key: "account", label: "Account", Icon: UserIcon },
  ] as const;
  return (
    <div className="grid shrink-0 grid-cols-5 border-t border-line bg-surface px-1 pt-1.5">
      {tabs.map(({ key, label, Icon }) => (
        <span
          key={key}
          className={cn(
            "flex flex-col items-center gap-0.5 text-[0.5625rem] font-medium",
            key === active ? "text-brand-700" : "text-ink-muted",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </span>
      ))}
    </div>
  );
}

/** A soft pale-green light behind a device, so it sits in the page's atmosphere. */
export function Halo({ className }: { className?: string }) {
  return <span aria-hidden className={cn("halo", className)} />;
}

/* ------------------------------------------------------------------------ */
/* Motion                                                                   */
/* ------------------------------------------------------------------------ */

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = React.useState(false);
  React.useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** Whether the element is (mostly) on screen right now. */
export function useInView<T extends Element>() {
  const ref = React.useRef<T>(null);
  const [inView, setInView] = React.useState(false);
  React.useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), {
      rootMargin: "-15% 0px -15% 0px",
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, inView] as const;
}

/**
 * Steps through `count` states while `running` (on screen). Choosing a state
 * yourself stops the automatic stepping - the reader has taken over. Under
 * reduced motion nothing steps on its own.
 */
export function useStory(count: number, running: boolean, interval: number) {
  const reduced = usePrefersReducedMotion();
  const [index, setIndex] = React.useState(0);
  const [held, setHeld] = React.useState(false);
  const playing = running && !held && !reduced && count > 1;

  React.useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setIndex((current) => (current + 1) % count), interval);
    return () => window.clearInterval(timer);
  }, [playing, count, interval]);

  const choose = React.useCallback((next: number) => {
    setHeld(true);
    setIndex(next);
  }, []);

  return { index, choose, playing, reduced };
}

/**
 * Fades its content up the first time it scrolls into view. Anything already
 * on screen when the page loads is left alone (no flash), and so is
 * everything under reduced motion.
 */
export function Reveal({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [state, setState] = React.useState<"idle" | "hidden" | "shown">("idle");

  React.useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (node.getBoundingClientRect().top < window.innerHeight * 0.92) return;
    setState("hidden");
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        setState("shown");
        observer.disconnect();
      },
      { rootMargin: "0px 0px -8% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      data-reveal={state}
      className={cn("reveal", className)}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  );
}

/**
 * Screens stacked in one place. The incoming screen fades in on top while the
 * outgoing one stays put until it is covered, then drops away - a clean
 * dissolve, never two half-screens blended.
 */
export function ScreenStack({ active, children }: { active: number; children: React.ReactNode[] }) {
  return (
    <div className="relative min-h-0 flex-1">
      {children.map((screen, index) => (
        <div
          key={index}
          className={cn(
            "absolute inset-0 flex flex-col bg-canvas transition-opacity ease-out motion-reduce:transition-none",
            index === active
              ? "z-10 opacity-100 duration-500"
              : "pointer-events-none z-0 opacity-0 delay-500 duration-0",
          )}
        >
          {screen}
        </div>
      ))}
    </div>
  );
}
