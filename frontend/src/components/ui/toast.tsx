"use client";

import * as React from "react";

import { cn } from "./primitives";

type ToastTone = "success" | "error" | "info" | "warn";

type Toast = {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
};

type ToastContextValue = {
  toast: (input: Omit<Toast, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
};

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>.");
  return context;
}

const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const nextId = React.useRef(1);

  const dismiss = React.useCallback((id: number) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = React.useCallback(
    (input: Omit<Toast, "id">) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-2), { ...input, id }]);
      window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const value = React.useMemo<ToastContextValue>(
    () => ({
      toast,
      success: (title, description) => toast({ tone: "success", title, description }),
      error: (title, description) => toast({ tone: "error", title, description }),
      info: (title, description) => toast({ tone: "info", title, description }),
    }),
    [toast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Bottom-anchored on mobile so it sits above the thumb, not under the
          notch; top-right on desktop. */}
      <div
        aria-live="polite"
        aria-atomic="false"
        className={cn(
          "pointer-events-none fixed inset-x-0 bottom-0 z-80 flex flex-col gap-2 p-4",
          "pb-[calc(1rem+var(--safe-bottom)+4.5rem)]",
          "sm:inset-x-auto sm:right-4 sm:top-4 sm:bottom-auto sm:w-96 sm:pb-4",
        )}
      >
        {toasts.map((item) => (
          <ToastCard key={item.id} toast={item} onDismiss={() => dismiss(item.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const TONE_STYLES: Record<ToastTone, { wrap: string; icon: React.ReactNode }> = {
  success: {
    wrap: "border-success-200 bg-success-50 text-success-700",
    icon: (
      <path d="M5 10.5l3.2 3.2L15 7" stroke="currentColor" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round" />
    ),
  },
  error: {
    wrap: "border-danger-200 bg-danger-50 text-danger-700",
    icon: (
      <path d="M10 6v5m0 3h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    ),
  },
  warn: {
    wrap: "border-warn-200 bg-warn-50 text-warn-700",
    icon: (
      <path d="M10 6v5m0 3h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    ),
  },
  info: {
    wrap: "border-info-200 bg-info-50 text-info-700",
    icon: (
      <path d="M10 9v5m0-8h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    ),
  },
};

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const style = TONE_STYLES[toast.tone];
  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      className={cn(
        "pointer-events-auto flex animate-slide-up items-start gap-3 rounded-xl border p-3.5 shadow-pop",
        style.wrap,
      )}
    >
      <svg viewBox="0 0 20 20" fill="none" className="mt-0.5 h-5 w-5 shrink-0" aria-hidden>
        <circle cx="10" cy="10" r="8.5" stroke="currentColor" strokeOpacity="0.35" />
        {style.icon}
      </svg>
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold">{toast.title}</p>
        {toast.description ? <p className="mt-0.5 opacity-90">{toast.description}</p> : null}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="-m-1 rounded-lg p-1 opacity-60 transition-opacity hover:opacity-100"
      >
        <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden>
          <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}
