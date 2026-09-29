import type { Metadata } from "next";

/** Sets the browser tab title; the page itself is a client component. */
export const metadata: Metadata = { title: { absolute: "VerifyGH \u2014 Admin - Providers" } };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
