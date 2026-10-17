import type { Metadata } from "next";

/**
 * Sets the browser tab title; the page itself is a client component.
 * Absolute, because a nested layout's plain title stops the root template
 * from reaching the pages below it.
 */
export const metadata: Metadata = {
  title: { absolute: "VerifyGH — Buy a number" },
  description:
    "See today's price in cedis for every service - WhatsApp, TikTok, Telegram, Google and hundreds more - and buy a US verification number with your Mobile Money wallet.",
  alternates: { canonical: "/services" },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
