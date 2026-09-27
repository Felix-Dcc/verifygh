"use client";

import { useParams } from "next/navigation";

import { VerifyEmailFlow } from "../verify-email-flow";

/**
 * `/verify-email/<token>` - the link shape verification emails use.
 *
 * A path segment rather than a query string: some mail clients and link
 * scanners rewrite or drop query parameters, and a bare path survives being
 * copied out of a plain-text email by hand.
 */
export default function VerifyEmailTokenPage() {
  const params = useParams<{ token: string | string[] }>();
  const raw = params?.token;
  const token = Array.isArray(raw) ? (raw[0] ?? "") : (raw ?? "");

  return <VerifyEmailFlow token={decodeURIComponent(token)} />;
}
