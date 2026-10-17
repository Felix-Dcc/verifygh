"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import type { User } from "@/lib/types";

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  /** True once we know for certain whether there is a session. */
  ready: boolean;
  refresh: () => Promise<void>;
  /**
   * `turnstileToken`: Cloudflare's one-time token, when the check is on.
   * Null when the account has two-factor on: finish with verifyTwoFactor.
   */
  signIn: (email: string, password: string, turnstileToken?: string) => Promise<User | null>;
  /** The second step of signing in: a code from the app, or a recovery code. */
  verifyTwoFactor: (code: string) => Promise<User>;
  signUp: (input: SignUpInput) => Promise<User>;
  signOut: () => Promise<void>;
  isStaff: boolean;
  can: (permission: string) => boolean;
};

export type SignUpInput = {
  email: string;
  password: string;
  full_name?: string;
  phone?: string;
  accepted_terms: boolean;
  /** From /register?ref=CODE. The backend resolves it; we only pass it on. */
  referral_code?: string;
  /** Cloudflare's one-time token, when the check is on. */
  turnstile_token?: string;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

const ME_KEY = "/auth/me/";

/**
 * Written on sign-out purely so other tabs notice.
 *
 * It holds a timestamp, never anything about the session: localStorage is
 * readable by any script on the origin, so it is the wrong place for anything
 * that matters.
 */
const SIGNED_OUT_KEY = "vgh:signed-out";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const toast = useToast();

  const { data, error, isLoading, mutate } = useSWR<{ user: User }>(
    ME_KEY,
    () => api.get<{ user: User }>(ME_KEY),
    {
      // A 401 here is not an error state - it just means "signed out".
      shouldRetryOnError: false,
      revalidateOnFocus: true,
      revalidateOnReconnect: true,
      onErrorRetry: () => undefined,
    },
  );

  const user = data?.user ?? null;
  const ready = !isLoading && (data !== undefined || error !== undefined);

  // A sign-out in another tab drops this tab's private data too. The cookies
  // are already gone - they are shared across tabs - so the only thing left to
  // clear is what this tab is still holding in memory.
  React.useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key !== SIGNED_OUT_KEY) return;
      void mutate(undefined, { revalidate: false });
      void globalMutate(() => true, undefined, { revalidate: false });
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [mutate]);

  const refresh = React.useCallback(async () => {
    await mutate();
  }, [mutate]);

  const signIn = React.useCallback(
    async (email: string, password: string, turnstileToken?: string) => {
      const response = await api.post<{ user?: User; two_factor_required?: boolean }>(
        "/auth/login/",
        {
          email,
          password,
          ...(turnstileToken ? { turnstile_token: turnstileToken } : {}),
        },
      );
      // The challenge travels in an httpOnly cookie; the code step sends it back.
      if (response.two_factor_required || !response.user) return null;
      await mutate({ user: response.user }, { revalidate: false });
      return response.user;
    },
    [mutate],
  );

  const verifyTwoFactor = React.useCallback(
    async (code: string) => {
      const response = await api.post<{ user: User }>("/auth/2fa/verify/", { code });
      await mutate({ user: response.user }, { revalidate: false });
      return response.user;
    },
    [mutate],
  );

  const signUp = React.useCallback(
    async (input: SignUpInput) => {
      const response = await api.post<{ user: User }>("/auth/register/", input);
      await mutate({ user: response.user }, { revalidate: false });
      return response.user;
    },
    [mutate],
  );

  const signOut = React.useCallback(async () => {
    try {
      await api.post("/auth/logout/", {});
    } catch {
      // Signing out must always land, even if the request fails. The server
      // blacklists the refresh token and clears the cookies; if that request
      // never arrives we still drop every local trace, and the access token
      // expires on its own.
    }
    await mutate(undefined, { revalidate: false });
    // Drop every cached response so the next account never sees the last
    // account's wallet, orders or notifications.
    await globalMutate(() => true, undefined, { revalidate: false });

    // Tell the other tabs. Without this, a second tab keeps rendering a wallet
    // and an order history from its own cache until something happens to
    // revalidate it - signed out in one window, still showing private data in
    // the next.
    try {
      window.localStorage.setItem(SIGNED_OUT_KEY, String(Date.now()));
    } catch {
      // Private browsing, or storage blocked. The other tab will find out on
      // its next request instead.
    }

    toast.info("You have been logged out", "Sign in again whenever you need to.");
    router.push("/");
  }, [mutate, router, toast]);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      loading: isLoading,
      ready,
      refresh,
      signIn,
      verifyTwoFactor,
      signUp,
      signOut,
      isStaff: Boolean(user && user.role !== "USER"),
      can: (permission: string) => Boolean(user?.admin_permissions?.includes(permission)),
    }),
    [user, isLoading, ready, refresh, signIn, verifyTwoFactor, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>.");
  return context;
}

/** Redirects to sign-in once we are sure there is no session. */
export function useRequireAuth({ staffOnly = false } = {}) {
  const { user, ready } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (!ready) return;
    if (!user) {
      const next =
        typeof window !== "undefined"
          ? `?next=${encodeURIComponent(window.location.pathname)}`
          : "";
      router.replace(`/login${next}`);
      return;
    }
    if (staffOnly && user.role === "USER") router.replace("/dashboard");
  }, [user, ready, router, staffOnly]);

  return { user, ready };
}

/** Turns an unknown thrown value into something safe to show a user. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Please try again.";
}
