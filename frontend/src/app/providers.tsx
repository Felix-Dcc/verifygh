"use client";

import * as React from "react";
import { SWRConfig } from "swr";

import { AuthProvider } from "@/components/auth-provider";
import { ThemeProvider } from "@/components/theme";
import { ToastProvider } from "@/components/ui/toast";
import { fetcher } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        fetcher,
        // Wallet balances and order states change under the user's feet, so
        // revalidate on focus - but never hammer the API on a flaky connection.
        revalidateOnFocus: true,
        revalidateOnReconnect: true,
        shouldRetryOnError: false,
        dedupingInterval: 2000,
        errorRetryCount: 2,
      }}
    >
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>{children}</AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </SWRConfig>
  );
}
