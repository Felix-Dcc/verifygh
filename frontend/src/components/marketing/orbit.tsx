"use client";

import * as React from "react";

import { ServiceLogo } from "@/components/service-logo";
import type { MarketRow } from "@/lib/types";

import { usePrefersReducedMotion } from "./device";

/*
 * Services revolving around the hero phone. Two tilted rings turn in opposite
 * directions; each logo is placed every frame from its angle - behind the
 * phone (smaller, dimmer, a touch of blur) on the far side of its ring, in
 * front of it (larger, sharp) on the near side - so the logos genuinely go
 * round the device rather than sitting in a grid.
 *
 * It only animates while on screen, and under reduced motion the logos hold
 * their starting places. The logos are services on sale today.
 */

type Ring = { cy: number; rx: number; ry: number; speed: number; size: number };

/** Ring geometry as fractions of the scene: centre height, radii (of width), turns per minute. */
const RINGS: Ring[] = [
  // Its near side crosses the phone's header, never the number or the code.
  { cy: 0.15, rx: 0.45, ry: 0.1, speed: 1.2, size: 1 },
  // Its near side crosses the bottom bezel.
  { cy: 0.82, rx: 0.43, ry: 0.09, speed: -0.9, size: 0.9 },
];

export function PhoneOrbit({ logos, children }: { logos: MarketRow[]; children: React.ReactNode }) {
  const sceneRef = React.useRef<HTMLDivElement>(null);
  const itemRefs = React.useRef<(HTMLSpanElement | null)[]>([]);
  const reduced = usePrefersReducedMotion();

  // First ring takes a little over half the logos, the second the rest.
  const split = Math.ceil(logos.length * 0.58);

  React.useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || logos.length === 0) return;

    const place = (seconds: number) => {
      const width = scene.clientWidth;
      const height = scene.clientHeight;
      logos.forEach((_, index) => {
        const el = itemRefs.current[index];
        if (!el) return;
        const inFirst = index < split;
        const ring = RINGS[inFirst ? 0 : 1];
        const count = inFirst ? split : logos.length - split;
        const slot = inFirst ? index : index - split;
        const angle =
          (slot / count) * Math.PI * 2 + (inFirst ? 0 : 0.6) + (seconds * ring.speed * Math.PI * 2) / 60;
        const x = width / 2 + Math.cos(angle) * ring.rx * width;
        const y = height * ring.cy + Math.sin(angle) * ring.ry * width;
        const near = (Math.sin(angle) + 1) / 2; // 0 far side, 1 near side
        const scale = (0.68 + near * 0.42) * ring.size;
        el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -50%) scale(${scale.toFixed(3)})`;
        el.style.zIndex = near > 0.5 ? "30" : "5";
        el.style.opacity = (0.4 + near * 0.6).toFixed(3);
        el.style.filter = near < 0.3 ? `blur(${((0.3 - near) * 5).toFixed(2)}px)` : "none";
      });
    };

    let frame = 0;
    let visible = false;
    const start = performance.now();
    const tick = (now: number) => {
      place((now - start) / 1000);
      frame = requestAnimationFrame(tick);
    };
    const run = () => {
      cancelAnimationFrame(frame);
      if (visible && !reduced) frame = requestAnimationFrame(tick);
    };

    place(0);
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      run();
    });
    observer.observe(scene);
    const resize = new ResizeObserver(() => {
      if (reduced || !visible) place(0);
    });
    resize.observe(scene);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      resize.disconnect();
    };
  }, [logos, split, reduced]);

  return (
    <div ref={sceneRef} className="relative mx-auto flex w-full max-w-120 justify-center py-10" aria-hidden>
      {/* The blue light the phone stands in */}
      <span className="pointer-events-none absolute left-1/2 top-1/2 h-[80%] w-[90%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(8,120,209,0.45),rgba(40,199,247,0.12)_60%,transparent)] blur-2xl" />

      {logos.map((row, index) => (
        <span
          key={row.slug}
          ref={(el) => {
            itemRefs.current[index] = el;
          }}
          className="absolute left-0 top-0 will-change-transform"
          style={{ opacity: 0 }}
        >
          <span className="block rounded-[23%] shadow-[0_10px_30px_-8px_rgba(0,0,0,0.6)] ring-1 ring-white/10">
            <ServiceLogo name={row.name} src={row.icon_url} slug={row.slug} size="lg" className="h-9! w-9! sm:h-12! sm:w-12!" />
          </span>
        </span>
      ))}

      <div className="relative z-20">{children}</div>
    </div>
  );
}

/** Faint stars across the night, twinkling out of step. Positions are fixed so the server and client agree. */
const STARS = [
  [6, 12, 1.5], [14, 38, 1], [22, 8, 2], [31, 24, 1], [44, 6, 1.5], [52, 30, 1], [63, 14, 2],
  [71, 34, 1], [79, 9, 1.5], [88, 22, 1], [94, 40, 2], [9, 52, 1], [18, 66, 1.5], [37, 48, 1],
  [58, 56, 1.5], [76, 50, 1], [86, 62, 1.5], [4, 30, 1], [48, 18, 1], [67, 44, 1],
];

export function Stars() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[70%] overflow-hidden">
      {STARS.map(([left, top, size], index) => (
        <span
          key={index}
          className="twinkle absolute rounded-full bg-white"
          style={{
            left: `${left}%`,
            top: `${top}%`,
            width: size * 2,
            height: size * 2,
            animationDelay: `${(index * 0.37) % 4}s`,
          }}
        />
      ))}
      {/* A couple of out-of-focus lights */}
      <span className="absolute left-[8%] top-[18%] h-24 w-24 rounded-full bg-aqua/10 blur-2xl" />
      <span className="absolute right-[10%] top-[8%] h-32 w-32 rounded-full bg-azure/15 blur-3xl" />
    </div>
  );
}
