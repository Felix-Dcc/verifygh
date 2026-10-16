import clsx, { type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * The design system's own size and shadow names (src/app/globals.css @theme).
 * Without them tailwind-merge would read `text-caption` as a text colour and
 * drop `text-ink` beside it.
 */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["2xs", "caption", "label", "heading", "title", "figure", "display"],
      shadow: ["card", "focus", "pop", "raised"],
      radius: ["device"],
      animate: ["fade-in", "float", "pin-pop", "pulse-ring", "shimmer", "slide-up"],
    },
  },
});

/**
 * Class-name joiner. Later classes win over earlier ones they conflict with, so
 * a component's defaults (`h-11 text-base`) give way to what its caller passes
 * (`h-9 text-sm`). Tailwind 3 happened to emit those in an order that let the
 * caller win; Tailwind 4 sorts them the other way, so the merge makes it
 * explicit instead of an accident of CSS order.
 *
 * Deliberately in its own module with no "use client" directive: server
 * components need it too, and a plain function exported from a client module
 * becomes an unusable client reference when a server component imports it.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
