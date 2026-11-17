import type { Metadata } from "next";

/**
 * Sets the browser tab title; the page itself is a client component.
 * Absolute, because a nested layout's plain title stops the root template
 * from reaching the pages below it.
 */
// noindex: every ?next= variant was crawled as a duplicate, and a sign-in form has no place in search.
export const metadata: Metadata = {
  title: { absolute: "VerifyGH — Sign in" },
  robots: { index: false, follow: true },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
