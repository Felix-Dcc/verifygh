"use client";

import * as React from "react";
import useSWR from "swr";

import { api } from "@/lib/api";
import { cedis } from "@/lib/format";

/**
 * Whether the referral programme is running. Staff pause it from Admin >
 * Referrals; while it is paused the app shows no way into it. `false` until
 * known, so a paused programme never flashes into view.
 */
export function useReferralsEnabled(): boolean {
  const { data } = useSWR<{ enabled: boolean }>("/referrals/status/", {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return data?.enabled === true;
}

const STORAGE_KEY = "vgh_ref";
/** How long an invitation is remembered on this device. */
const KEEP_MS = 7 * 24 * 60 * 60 * 1000;

function cleanCode(raw: string | null | undefined): string {
  return (raw || "").replace(/\s+/g, "").toUpperCase().slice(0, 16);
}

/**
 * Remember an invitation code on this device for seven days.
 *
 * Kept in localStorage, not the tab: a link opened inside WhatsApp's own
 * browser, or a visit that only signs up later in the week, must still count.
 * Only the code is stored - it is not a tracker, and it is dropped once the
 * account is created.
 */
function rememberCode(code: string) {
  if (!code || !/^[A-Z0-9]+$/.test(code)) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ code, at: Date.now() }));
  } catch {
    // Private mode, or storage disabled: the URL alone still works.
  }
}

function rememberedCode(): string {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return "";
    const saved = JSON.parse(raw) as { code?: string; at?: number };
    if (!saved.code || !saved.at || Date.now() - saved.at > KEEP_MS) {
      window.localStorage.removeItem(STORAGE_KEY);
      return "";
    }
    return cleanCode(saved.code);
  } catch {
    return "";
  }
}

/**
 * Picks up `?ref=CODE` on any page - the homepage, a service page, sign-in -
 * not just the registration form, so a friend who lands anywhere keeps the
 * invitation. Rendered once, near the root.
 */
export function ReferralCapture() {
  React.useEffect(() => {
    try {
      const code = cleanCode(new URLSearchParams(window.location.search).get("ref"));
      if (code) rememberCode(code);
    } catch {
      // Nothing to remember.
    }
  }, []);
  return null;
}

export type InviteTerms = {
  bonus: string;
  referrerBonus: string;
  requireFirstDeposit: boolean;
  minFirstDeposit: string;
};

export type InviteState = {
  /** The code as it will be sent - from the link, or typed by the friend. */
  code: string;
  setCode: (value: string) => void;
  status: "idle" | "checking" | "valid" | "invalid";
  terms: InviteTerms | null;
};

type ValidateResponse = {
  valid: boolean;
  enabled?: boolean;
  bonus_amount: string;
  referrer_bonus?: string;
  require_first_deposit?: boolean;
  min_first_deposit?: string;
};

/**
 * The invitation code for the registration form: from `?ref=`, from a code
 * remembered on this device, or typed in the form. Validation is only for the
 * banner: whether the referral counts is decided by the backend at
 * registration, from the code we send, and an unknown one simply signs the
 * user up without a referral.
 */
export function useReferralInvite(): InviteState {
  const [code, setCodeState] = React.useState("");
  const [status, setStatus] = React.useState<InviteState["status"]>("idle");
  const [terms, setTerms] = React.useState<InviteTerms | null>(null);

  React.useEffect(() => {
    let initial = "";
    try {
      initial = cleanCode(new URLSearchParams(window.location.search).get("ref"));
      if (initial) rememberCode(initial);
    } catch {
      // Fall back to a remembered code.
    }
    setCodeState(initial || rememberedCode());
  }, []);

  React.useEffect(() => {
    if (code.length < 4) {
      setStatus("idle");
      return;
    }
    let cancelled = false;
    setStatus("checking");
    // A short pause while someone is still typing the code.
    const timer = window.setTimeout(() => {
      api
        .post<ValidateResponse>("/referrals/validate/", { code })
        .then((result) => {
          if (cancelled) return;
          if (result.enabled === false) {
            // Paused: no banner - there is nothing to claim.
            setStatus("idle");
            setTerms(null);
            return;
          }
          setTerms({
            bonus: result.bonus_amount,
            referrerBonus: result.referrer_bonus ?? "0.00",
            requireFirstDeposit: result.require_first_deposit ?? false,
            minFirstDeposit: result.min_first_deposit ?? "0.00",
          });
          setStatus(result.valid ? "valid" : "invalid");
        })
        .catch(() => {
          // The banner is a nicety. If the check fails we stay quiet and still
          // send the code - the backend decides.
          if (!cancelled) setStatus("idle");
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [code]);

  const setCode = React.useCallback((value: string) => setCodeState(cleanCode(value)), []);
  return { code, setCode, status, terms };
}

export function clearReferralInvite() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** What a friend gets, in one sentence. Shared by the banner and the refer page. */
export function friendOffer(terms: InviteTerms): string {
  return terms.requireFirstDeposit && Number.parseFloat(terms.minFirstDeposit) > 0
    ? `${cedis(terms.bonus)} in promotional credit after your first top-up of ${cedis(terms.minFirstDeposit)} or more`
    : `${cedis(terms.bonus)} in promotional credit once you verify your email`;
}

export function ReferralInviteBanner({ invite }: { invite: InviteState }) {
  if (invite.status !== "valid" || !invite.terms) return null;
  return (
    <div className="rounded-xl border border-brand/20 bg-brand/5 px-4 py-3">
      <p className="text-sm font-medium text-ink">You&rsquo;ve been invited to VerifyGH.</p>
      <p className="mt-1 text-sm text-ink-muted">
        Create your account and get{" "}
        <span className="font-semibold text-brand">{friendOffer(invite.terms)}</span>.
      </p>
    </div>
  );
}
