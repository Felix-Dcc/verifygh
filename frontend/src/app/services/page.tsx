"use client";

import * as React from "react";

import { AppShell, PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { Marketplace } from "@/components/marketplace/marketplace";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";

/**
 * The marketplace is public: a first-time visitor should be able to see real
 * services and real prices before being asked to create anything. Signed in,
 * the same page renders inside the app shell so navigation does not jump.
 */
export default function ServicesPage() {
  return (
    <React.Suspense fallback={<div className="min-h-dvh bg-canvas" />}>
      <ServicesRoute />
    </React.Suspense>
  );
}

function ServicesRoute() {
  const { user, ready } = useAuth();

  const content = (
    <>
      <PageHeader
        title="Buy a number"
        description="Pick a service to get a number that receives its verification code. Prices are in cedis and paid from your wallet."
      />
      <Marketplace />
    </>
  );

  if (!ready) {
    // Neutral shell until we know which chrome to render - flipping layout
    // after hydration is worse than a brief blank.
    return <div className="min-h-dvh bg-canvas" />;
  }

  if (user) return <AppShell>{content}</AppShell>;

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main id="main" className="flex-1">
        <div className="container-page py-8">{content}</div>
      </main>
      <SiteFooter />
    </div>
  );
}
