"use client";

import * as React from "react";

import { useAuth } from "@/components/auth-provider";

/**
 * Where a visitor came from, so a sign-up can be credited to the TikTok
 * video, ad or partner link that sent it (backend/apps/accounts/attribution.py).
 *
 * First touch wins for 30 days: someone who taps an ad today and signs up from
 * a bookmark on Friday still counts for the ad. A later campaign link replaces
 * it, since that is the newer reason they came. Kept on this device only and
 * sent nowhere but our own sign-up - no third-party tracker sees it. It holds a
 * campaign name, the page they landed on and the linking site's host name:
 * nothing about the person.
 */

export type Attribution = {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_content?: string;
  landing?: string;
  referrer?: string;
};

const STORAGE_KEY = "vgh_src";
const KEEP_MS = 30 * 24 * 60 * 60 * 1000;
const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content"] as const;

function short(value: string | null): string {
  return (value || "").trim().slice(0, 64);
}

/** What this page view says about where the visitor came from, if anything. */
function fromThisVisit(): Attribution | null {
  const params = new URLSearchParams(window.location.search);
  const found: Attribution = {};
  for (const key of UTM_KEYS) {
    const value = short(params.get(key));
    if (value) found[key] = value;
  }

  let referrer = "";
  try {
    const host = document.referrer ? new URL(document.referrer).hostname : "";
    // Our own pages (and the apex/www pair) are not a source.
    if (host && !host.endsWith("getverifygh.com") && host !== window.location.hostname) referrer = host;
  } catch {
    // An unparseable referrer is no referrer.
  }

  const campaign = Object.keys(found).length > 0;
  if (!campaign && !referrer) return null;
  return {
    ...found,
    ...(referrer ? { referrer } : {}),
    landing: window.location.pathname.slice(0, 64),
  };
}

function remembered(): { at: number; source: Attribution } | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { at?: number; source?: Attribution };
    if (!saved.at || !saved.source || Date.now() - saved.at > KEEP_MS) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return { at: saved.at, source: saved.source };
  } catch {
    return null;
  }
}

/** The source to send with a sign-up, or undefined when there is none. */
export function rememberedAttribution(): Attribution | undefined {
  if (typeof window === "undefined") return undefined;
  return remembered()?.source;
}

/** Dropped once the account exists: it has been recorded. */
export function clearAttribution() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** Notes the source on any page a visitor lands on. Rendered once, near the root. */
export function AttributionCapture() {
  const { user } = useAuth();

  // Signed in means the sign-up (by form or by Google) has already been
  // recorded, or never will be: nothing left to keep.
  React.useEffect(() => {
    if (user) clearAttribution();
  }, [user]);

  React.useEffect(() => {
    try {
      const visit = fromThisVisit();
      if (!visit) return;
      const current = remembered();
      // A campaign link always counts; a plain referral only fills an empty slot.
      if (current && !visit.utm_source) return;
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ at: Date.now(), source: visit }));
    } catch {
      // Private mode, or storage disabled: the sign-up simply goes unattributed.
    }
  }, []);
  return null;
}
