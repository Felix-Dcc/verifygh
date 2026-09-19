"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";

import { ApiError, api } from "@/lib/api";
import type { User } from "@/lib/types";

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  /** True once we know for certain whether there is a session. */
  ready: boolean;
  refresh: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<User>;
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
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

const ME_KEY = "/auth/me/";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

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

  const refresh = React.useCallback(async () => {
    await mutate();
  }, [mutate]);

  const signIn = React.useCallback(
    async (email: string, password: string) => {
      const response = await api.post<{ user: User }>("/auth/login/", { email, password });
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
      // Signing out must always land, even if the request fails.
    }
    await mutate(undefined, { revalidate: false });
    // Drop every cached response so the next account never sees the last
    // account's wallet, orders or notifications.
    await globalMutate(() => true, undefined, { revalidate: false });
    router.push("/login");
  }, [mutate, router]);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      loading: isLoading,
      ready,
      refresh,
      signIn,
      signUp,
      signOut,
      isStaff: Boolean(user && user.role !== "USER"),
      can: (permission: string) => Boolean(user?.admin_permissions?.includes(permission)),
    }),
    [user, isLoading, ready, refresh, signIn, signUp, signOut],
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
