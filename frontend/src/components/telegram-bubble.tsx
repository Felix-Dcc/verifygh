"use client";

import { usePathname } from "next/navigation";

import { TelegramIcon } from "@/components/icons";
import { cn } from "@/components/ui/primitives";

/**
 * Support lives on Telegram: the bubble opens a chat with the support account.
 * Hidden on a single order or rental, where it would cover the page's own actions.
 */

const USERNAME = (process.env.NEXT_PUBLIC_TELEGRAM_USERNAME || "Getverifygh").replace(/^@/, "").trim();
// A generic draft only: nothing about the customer goes in the URL.
const DRAFT = "Hi VerifyGH, I need help with ";

export function TelegramBubble() {
  const pathname = usePathname();
  if (/^\/(orders|rentals)\/[^/]+/.test(pathname)) return null;

  return (
    <a
      href={`https://t.me/${USERNAME}?text=${encodeURIComponent(DRAFT)}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Chat with support on Telegram (opens Telegram)"
      title="Chat with support on Telegram"
      className={cn(
        "fixed right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-[#229ED9] text-white shadow-lg",
        "transition-opacity hover:opacity-90 focus-visible:shadow-focus focus-visible:outline-hidden",
        "bottom-[calc(5rem+var(--safe-bottom))] lg:bottom-6 lg:right-6",
      )}
    >
      <TelegramIcon className="h-6 w-6" />
    </a>
  );
}
