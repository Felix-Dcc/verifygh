import type { Metadata } from "next";

/** "VerifyGH — Order VGH-ABC123" in the tab; the page is a client component. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ reference: string }>;
}): Promise<Metadata> {
  const { reference } = await params;
  return { title: { absolute: `VerifyGH — Order ${reference}` } };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
