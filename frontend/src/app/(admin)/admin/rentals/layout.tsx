import type { Metadata } from "next";

/** Sets the browser tab title; the page itself is a client component. */
export const metadata: Metadata = { title: { absolute: "VerifyGH — Admin - Rentals" } };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
