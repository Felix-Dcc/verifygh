import type { Metadata } from "next";

/** "VerifyGH — Order VGH-ABC123" in the tab; the page is a client component. */
export function generateMetadata({ params }: { params: { reference: string } }): Metadata {
  return { title: { absolute: `VerifyGH — Order ${params.reference}` } };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
