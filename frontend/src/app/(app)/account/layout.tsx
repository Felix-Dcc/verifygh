import type { Metadata } from "next";

/**
 * Sets the browser tab title; the page itself is a client component.
 * Absolute, because a nested layout's plain title stops the root template
 * from reaching the pages below it.
 */
export const metadata: Metadata = { title: { absolute: "VerifyGH — Settings" } };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
