"use client";

import Link from "next/link";

import { AppShell, PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { ChevronRightIcon, FlagIcon, MailIcon, RefreshIcon, WalletIcon } from "@/components/icons";
import { SupportArt } from "@/components/illustrations";
import { Faq } from "@/components/marketing/faq";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink, Card } from "@/components/ui/primitives";

const SUPPORT_EMAIL = "support@getverifygh.com";

/**
 * Help: how to reach a person, the answers to the problems people actually
 * have, and the questions from the homepage - in one place, inside the app
 * when signed in (the sidebar's "Help & FAQ" used to leave the app).
 */
export default function HelpPage() {
  const { user, ready } = useAuth();

  const content = (
    <div className="space-y-8">
      <PageHeader title="Help and support" description="Answers to common problems, and how to reach us." />

      <Card className="grid grid-cols-1 items-center gap-6 p-6 sm:p-8 md:grid-cols-3">
        <div className="md:col-span-2">
          <h2 className="text-heading text-ink">Talk to a person</h2>
          <p className="mt-1.5 max-w-lg text-sm text-ink-muted">
            Email us and include your order reference (it starts with VGH-) or your payment
            reference, so we can find it straight away. Never send your password or your MoMo PIN.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <ButtonLink href={`mailto:${SUPPORT_EMAIL}`} icon={<MailIcon className="h-4 w-4" />}>
              Email support
            </ButtonLink>
            <span className="text-sm text-ink-soft">{SUPPORT_EMAIL}</span>
          </div>
        </div>
        <div className="hidden justify-center md:flex">
          <SupportArt className="h-32 w-44" />
        </div>
      </Card>

      <section aria-labelledby="problems-heading">
        <h2 id="problems-heading" className="mb-3 text-heading text-ink">
          Common problems
        </h2>
        <Card className="divide-y divide-line overflow-hidden">
          <Problem
            icon={<RefreshIcon className="h-4 w-4" />}
            title="The code never arrived"
            body="If no code arrives before the number expires, the full price goes back to your wallet on its own. You can also cancel for a refund any time before a code arrives."
            href={user ? "/orders?filter=active" : undefined}
            action="Open orders"
          />
          <Problem
            icon={<FlagIcon className="h-4 w-4" />}
            title="The service says the number is already used"
            body="Numbers can have been used before. Open the order and choose Report a problem - we review it and replace or refund the number where our policy allows."
            href={user ? "/orders" : undefined}
            action="Find the order"
          />
          <Problem
            icon={<WalletIcon className="h-4 w-4" />}
            title="I paid but my balance has not changed"
            body="A top-up is added once the network confirms it, usually within a minute. If you are still on the Add funds screen, choose Check again. Otherwise email us the amount, the time and the number you paid from."
            href={user ? "/wallet" : undefined}
            action="Open wallet"
          />
        </Card>
      </section>

      <Faq embedded />

      <p className="text-sm text-ink-muted">
        Read the{" "}
        <Link href="/terms" className="link">
          Terms of Service
        </Link>
        ,{" "}
        <Link href="/acceptable-use" className="link">
          Acceptable Use Policy
        </Link>{" "}
        and{" "}
        <Link href="/privacy" className="link">
          Privacy Policy
        </Link>
        .
      </p>
    </div>
  );

  if (!ready) return <div className="min-h-dvh bg-canvas" />;
  if (user) return <AppShell>{content}</AppShell>;
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main id="main" className="flex-1">
        <div className="container-page max-w-4xl py-8">{content}</div>
      </main>
      <SiteFooter />
    </div>
  );
}

function Problem({
  icon,
  title,
  body,
  href,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  href?: string;
  action: string;
}) {
  return (
    <div className="flex gap-4 p-5 sm:p-6">
      <span
        aria-hidden
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sunken text-ink-soft"
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <p className="mt-1 text-sm leading-relaxed text-ink-muted">{body}</p>
        {href ? (
          <Link href={href} className="link mt-2 inline-flex min-h-11 items-center gap-1 text-sm sm:min-h-0">
            {action}
            <ChevronRightIcon className="h-3.5 w-3.5" />
          </Link>
        ) : null}
      </div>
    </div>
  );
}
