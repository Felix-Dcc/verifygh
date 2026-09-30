"use client";

import * as React from "react";

import { api } from "@/lib/api";

const STORAGE_KEY = "vgh_ref";

type InviteState = {
  /** The code as typed in the URL, kept exactly as the backend will see it. */
  code: string;
  status: "idle" | "checking" | "valid" | "invalid";
  bonus: string;
};

/**
 * Picks up `?ref=CODE` and keeps it for the whole registration.
 *
 * The code survives a reload or a detour to the Terms page via sessionStorage,
 * which is per-tab and cleared when the browser closes - long enough to finish
 * signing up, not a tracker. Validation is only for the banner: whether the
 * referral counts is decided by the backend at registration, from the code we
 * send, and an invalid one simply signs the user up without a referral.
 */
export function useReferralInvite(): InviteState {
  const [state, setState] = React.useState<InviteState>({
    code: "",
    status: "idle",
    bonus: "",
  });

  React.useEffect(() => {
    let code = "";
    try {
      const fromUrl = new URLSearchParams(window.location.search).get("ref") || "";
      const stored = window.sessionStorage.getItem(STORAGE_KEY) || "";
      code = (fromUrl || stored).trim().toUpperCase().slice(0, 16);
      if (fromUrl && code) window.sessionStorage.setItem(STORAGE_KEY, code);
    } catch {
      // Private mode, or storage disabled: the URL alone still works.
    }
    if (!code) return;

    let cancelled = false;
    setState({ code, status: "checking", bonus: "" });
    api
      .post<{ valid: boolean; bonus_amount: string }>("/referrals/validate/", { code })
      .then((result) => {
        if (cancelled) return;
        setState({
          code,
          status: result.valid ? "valid" : "invalid",
          bonus: result.bonus_amount,
        });
      })
      .catch(() => {
        // The banner is a nicety. If the check fails we stay quiet and still
        // send the code - the backend decides.
        if (!cancelled) setState({ code, status: "idle", bonus: "" });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}

export function clearReferralInvite() {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

export function ReferralInviteBanner({ invite }: { invite: InviteState }) {
  if (invite.status === "idle" || invite.status === "checking") return null;

  if (invite.status === "invalid") {
    // Deliberately gentle: an expired or mistyped link must not look like a
    // problem with their sign-up, because it changes nothing about it.
    return (
      <div className="rounded-xl border border-line bg-sunken px-4 py-3 text-sm text-ink-muted">
        We could not find that invitation, but you can still create your account.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-brand/20 bg-brand/5 px-4 py-3">
      <p className="text-sm font-medium text-ink">You&rsquo;ve been invited to VerifyGH.</p>
      <p className="mt-1 text-sm text-ink-muted">
        Complete your registration and receive{" "}
        <span className="font-semibold text-brand">GH₵{invite.bonus}</span> in promotional
        credit once you verify your email.
      </p>
    </div>
  );
}
