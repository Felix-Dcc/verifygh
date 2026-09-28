"use client";

import * as React from "react";

import { cn } from "@/lib/cn";

export { cn };

/* -------------------------------------------------------------------------
 * Button
 * ---------------------------------------------------------------------- */

type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "danger"
  | "subtle"
  // For use on a brand-coloured surface, where the usual variants vanish.
  | "inverse"
  | "ghostInverse";
type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800 disabled:bg-brand-600/50",
  secondary:
    "bg-surface text-ink border border-line-strong hover:bg-canvas active:bg-line/40 disabled:opacity-50",
  ghost: "bg-transparent text-ink-soft hover:bg-line/40 active:bg-line/60 disabled:opacity-50",
  danger:
    "bg-danger-700 text-white hover:bg-danger-500 active:bg-danger-700 disabled:bg-danger-700/50",
  subtle:
    "bg-brand-50 text-brand-700 hover:bg-brand-100 active:bg-brand-200 disabled:opacity-50",
  inverse:
    "bg-white text-brand-700 hover:bg-brand-50 active:bg-brand-100 disabled:opacity-60",
  ghostInverse:
    "bg-transparent text-white hover:bg-white/10 active:bg-white/20 disabled:opacity-50",
};

const SIZES: Record<ButtonSize, string> = {
  // 44px minimum touch target on every size: this is a phone-first product.
  sm: "h-10 px-3 text-sm gap-1.5",
  md: "h-11 px-4 text-sm gap-2",
  lg: "h-12 px-5 text-base gap-2",
};

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  fullWidth?: boolean;
  icon?: React.ReactNode;
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "primary", size = "md", loading, fullWidth, icon, children,
    disabled, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex select-none items-center justify-center rounded-xl font-medium",
        "transition-colors duration-150 disabled:cursor-not-allowed",
        VARIANTS[variant],
        SIZES[size],
        fullWidth && "w-full",
        className,
      )}
      {...props}
    >
      {loading ? <Spinner className="h-4 w-4" /> : icon}
      {children}
    </button>
  );
});

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("animate-spin", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path
        d="M22 12a10 10 0 0 0-10-10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* -------------------------------------------------------------------------
 * Card
 * ---------------------------------------------------------------------- */

export function Card({
  className,
  children,
  as: Tag = "div",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { as?: React.ElementType }) {
  return (
    <Tag className={cn("card", className)} {...props}>
      {children}
    </Tag>
  );
}

export function CardHeader({
  title,
  description,
  action,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-4 pt-4 sm:px-5", className)}>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {description ? (
          <p className="mt-0.5 text-sm text-ink-muted">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Form fields
 * ---------------------------------------------------------------------- */

export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  hint?: React.ReactNode;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-ink-soft">
        {label}
        {required ? <span className="ml-0.5 text-danger-500">*</span> : null}
      </label>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} role="alert" className="text-sm text-danger-700">
          {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-hint`} className="text-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
  prefix?: React.ReactNode;
};

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, invalid, prefix, ...props },
  ref,
) {
  const base = cn(
    "h-12 w-full bg-transparent text-base text-ink placeholder:text-ink-faint",
    // 16px text: anything smaller makes iOS Safari zoom the page on focus.
    "focus:outline-none disabled:text-ink-muted",
    className,
  );

  const shell = cn(
    "flex items-center rounded-xl border bg-surface transition-shadow",
    "focus-within:shadow-focus",
    invalid
      ? "border-danger-500"
      : "border-line-strong focus-within:border-brand-500",
  );

  return (
    <div className={shell}>
      {prefix ? (
        <span className="select-none pl-3.5 text-base text-ink-muted">{prefix}</span>
      ) : null}
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(base, prefix ? "px-2" : "px-3.5")}
        {...props}
      />
    </div>
  );
});


export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }
>(function Select({ className, invalid, children, ...props }, ref) {
  return (
    <select
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        "h-12 w-full appearance-none rounded-xl border bg-surface px-3.5 pr-10 text-base text-ink",
        "bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 20 20%22 fill=%22none%22 stroke=%22%236B7A73%22 stroke-width=%221.6%22><path d=%22M6 8l4 4 4-4%22/></svg>')] bg-[length:20px_20px] bg-[right_0.75rem_center] bg-no-repeat",
        "transition-shadow focus:shadow-focus focus:outline-none",
        invalid ? "border-danger-500" : "border-line-strong focus:border-brand-500",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
});

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }
>(function Textarea({ className, invalid, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        "w-full rounded-xl border bg-surface p-3.5 text-base text-ink placeholder:text-ink-faint",
        "transition-shadow focus:shadow-focus focus:outline-none",
        invalid ? "border-danger-500" : "border-line-strong focus:border-brand-500",
        className,
      )}
      {...props}
    />
  );
});

export function Checkbox({
  id,
  label,
  error,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { id: string; label: React.ReactNode; error?: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-start gap-3">
        <input
          id={id}
          type="checkbox"
          className={cn(
            "mt-0.5 h-5 w-5 shrink-0 rounded border-line-strong text-brand-600",
            "focus:ring-2 focus:ring-brand-500/50 focus:ring-offset-0",
            error && "border-danger-500",
          )}
          {...props}
        />
        <label htmlFor={id} className="text-sm leading-relaxed text-ink-soft">
          {label}
        </label>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Badges
 * ---------------------------------------------------------------------- */

type Tone = "neutral" | "brand" | "success" | "warn" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-line/60 text-ink-soft",
  brand: "bg-brand-50 text-brand-700",
  success: "bg-success-50 text-success-700",
  warn: "bg-warn-50 text-warn-700",
  danger: "bg-danger-50 text-danger-700",
  info: "bg-info-50 text-info-700",
};

export function Badge({
  tone = "neutral",
  className,
  children,
  dot,
}: {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden /> : null}
      {children}
    </span>
  );
}

/** Maps every order / payment / transaction status onto a consistent colour,
 *  so "green means good" holds everywhere in the product. */
const STATUS_TONES: Record<string, Tone> = {
  COMPLETED: "success",
  SUCCESS: "success",
  CODE_RECEIVED: "success",
  NUMBER_ASSIGNED: "info",
  WAITING_FOR_CODE: "info",
  PROCESSING: "info",
  PENDING: "warn",
  PAYMENT_PENDING: "warn",
  CREATED: "neutral",
  EXPIRED: "neutral",
  CANCELLED: "neutral",
  FAILED: "danger",
  REFUNDED: "brand",
  // Number-issue cases
  OPEN: "warn",
  IN_REVIEW: "info",
  REPLACED: "success",
  REJECTED: "neutral",
  RESOLVED: "neutral",
  DEPOSIT: "success",
  PURCHASE: "neutral",
  REFUND: "brand",
  ADJUSTMENT: "warn",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = STATUS_TONES[status] ?? "neutral";
  const live = status === "WAITING_FOR_CODE" || status === "PROCESSING";
  const label = status
    .split("_")
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(" ");
  return (
    <Badge tone={tone} className={className}>
      {live ? (
        <span className="relative flex h-1.5 w-1.5" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-current" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      )}
      {label}
    </Badge>
  );
}

/* -------------------------------------------------------------------------
 * Feedback
 * ---------------------------------------------------------------------- */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: Tone;
  title?: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  const border: Record<Tone, string> = {
    neutral: "border-line",
    brand: "border-brand-200",
    success: "border-success-200",
    warn: "border-warn-200",
    danger: "border-danger-200",
    info: "border-info-200",
  };
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn("rounded-xl border p-4", TONES[tone], border[tone], className)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm">
          {title ? <p className="font-semibold">{title}</p> : null}
          {children ? <div className={cn(title && "mt-1", "opacity-90")}>{children}</div> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center px-6 py-14 text-center", className)}>
      {icon ? (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
          {icon}
        </div>
      ) : null}
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description ? (
        <p className="mt-1.5 max-w-sm text-sm text-ink-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Segmented control (used for the order history filters)
 * ---------------------------------------------------------------------- */

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn(
        "no-scrollbar flex gap-1 overflow-x-auto rounded-xl bg-line/40 p-1",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-lg px-3.5 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-surface text-ink shadow-card"
                : "text-ink-muted hover:text-ink-soft",
            )}
          >
            {option.label}
            {option.count !== undefined ? (
              <span className={cn("ml-1.5", active ? "text-ink-muted" : "text-ink-faint")}>
                {option.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
