"use client";

import { useSearchParams } from "next/navigation";
import * as React from "react";

import { VerifyEmailFlow } from "./verify-email-flow";

/**
 * `/verify-email?token=...` - the shape VerifyGH used to email.
 *
 * Kept because links already sent are still inside people's inboxes and must
 * keep working until they expire. New emails use `/verify-email/<token>`.
 */
export default function VerifyEmailQueryPage() {
  return (
    <React.Suspense fallback={null}>
      <FromQuery />
    </React.Suspense>
  );
}

function FromQuery() {
  const params = useSearchParams();
  return <VerifyEmailFlow token={params.get("token") ?? ""} />;
}
