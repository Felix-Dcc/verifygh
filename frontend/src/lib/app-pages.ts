/**
 * The public "US number for <app>" pages (/us-number/<slug>): one per app
 * people buy most, written for the searches that bring them.
 *
 * Everything here must stay true of the product: prices are read live from the
 * marketplace, never written down here.
 */

export type AppPage = {
  /** Catalogue slug, also the URL segment and the buy link's ?service=. */
  slug: string;
  /** How people say it in a search. */
  name: string;
  /** What the number is for, in a phrase ("create a WhatsApp account"). */
  purpose: string;
  /** Advice specific to this app, shown before the general FAQ. */
  tips: string[];
  /** One question people ask about this app in particular. */
  faq: { q: string; a: string };
};

export const APP_PAGES: AppPage[] = [
  {
    slug: "whatsapp",
    name: "WhatsApp",
    purpose: "create a WhatsApp or WhatsApp Business account",
    tips: [
      "When WhatsApp asks how to verify, choose SMS. These numbers cannot take calls.",
      "Once you are in, add a passkey, add your email and turn on two-step verification (Settings → Account), so you can always get back in without an SMS.",
    ],
    faq: {
      q: "Can I use it for WhatsApp Business?",
      a: "Yes. WhatsApp Business verifies a number the same way as WhatsApp, with an SMS code.",
    },
  },
  {
    slug: "telegram",
    name: "Telegram",
    purpose: "create a Telegram account",
    tips: [
      "If Telegram says the code was sent to the Telegram app, or offers to call you, that number already has a Telegram account and no SMS will come. Cancel for a full refund and buy a new number.",
      "Once you are in, set a cloud password: Settings → Privacy and Security → Two-Step Verification.",
    ],
    faq: {
      q: "Why did Telegram send the code to the app instead of by SMS?",
      a: "That happens when the number is already on Telegram. Cancel the order for a full refund and try a new number.",
    },
  },
  {
    slug: "tiktok",
    name: "TikTok",
    purpose: "sign up for TikTok or verify your TikTok account",
    tips: [
      "If TikTok says there were too many attempts, wait a while before trying again. A new number straight away usually hits the same limit.",
    ],
    faq: {
      q: "Can I use it for TikTok Shop or a business account?",
      a: "Yes, as long as TikTok asks for an SMS code to verify the phone number.",
    },
  },
  {
    slug: "google",
    name: "Google and Gmail",
    purpose: "create a Gmail or Google account",
    tips: [
      "If Google says the number cannot be used for verification, cancel for a full refund and try a new number.",
      "Add a recovery email to your new Google account straight away, so you are not relying on this number later.",
    ],
    faq: {
      q: "Does it work for YouTube and Google Play?",
      a: "Yes. They use your Google account, so verifying the Google account is all they need.",
    },
  },
  {
    slug: "facebook",
    name: "Facebook",
    purpose: "create or verify a Facebook account",
    tips: [
      "If you already have a Facebook account, sign in to it rather than creating a new one. New accounts are checked more closely.",
    ],
    faq: {
      q: "Can I use it for Facebook Marketplace or a Page?",
      a: "Yes. Marketplace and Pages use your Facebook account, so verifying the account is what they need.",
    },
  },
  {
    slug: "instagram",
    name: "Instagram",
    purpose: "create or verify an Instagram account",
    tips: [
      "If you already have an Instagram account, sign in to it rather than creating a new one. New accounts are checked more closely.",
    ],
    faq: {
      q: "Can I use it for an Instagram business account?",
      a: "Yes, as long as Instagram asks for an SMS code to verify the phone number.",
    },
  },
  {
    slug: "signal",
    name: "Signal",
    purpose: "create a Signal account",
    tips: [
      "Signal may ask you to solve a captcha first. The SMS is only sent after that.",
      "Choose SMS, not a voice call. These numbers cannot take calls.",
      "Once you are in, turn on Registration Lock with a PIN (Settings → Account).",
    ],
    faq: {
      q: "Why hasn't Signal sent the code?",
      a: "Signal only sends the SMS after its captcha is solved. If no code arrives in time, the full price goes back to your wallet automatically.",
    },
  },
  {
    slug: "snapchat",
    name: "Snapchat",
    purpose: "create or verify a Snapchat account",
    tips: [
      "If Snapchat says the number is already in use, cancel for a full refund and try a new number.",
      "Once you are in, add your email and turn on two-factor authentication: Settings → Two-Factor Authentication.",
    ],
    faq: {
      q: "Can I use it for Snapchat+?",
      a: "Yes. Snapchat+ runs on your Snapchat account, so verifying the account is all it needs.",
    },
  },
  {
    slug: "discord",
    name: "Discord",
    purpose: "verify a Discord account",
    tips: [
      "Discord may ask you to solve a captcha first. The SMS is only sent after that.",
      "Once your phone is verified, turn on two-factor authentication with an authenticator app: User Settings → My Account.",
    ],
    faq: {
      q: "Why does Discord ask for a phone number?",
      a: "Some servers only let in members whose phone is verified, and Discord sometimes asks after unusual activity. A US number verifies it the same way.",
    },
  },
  {
    slug: "linkedin",
    name: "LinkedIn",
    purpose: "create or verify a LinkedIn account",
    tips: [
      "If you already have a LinkedIn account, sign in to it rather than creating a new one. New accounts are checked more closely.",
      "Add your email as the main sign-in on your account, so you are not relying on this number later.",
    ],
    faq: {
      q: "Can I use it for LinkedIn Premium or a company page?",
      a: "Yes. Both run on your LinkedIn account, so verifying the account is what they need.",
    },
  },
  {
    slug: "twitter",
    name: "X (Twitter)",
    purpose: "create or verify an X (Twitter) account",
    tips: [
      "If you already have an X account, sign in to it rather than creating a new one. New accounts are checked more closely.",
    ],
    faq: {
      q: "Does it work for Twitter as well as X?",
      a: "Yes. Twitter is now called X, and it is the same account.",
    },
  },
];

export const appPage = (slug: string) => APP_PAGES.find((page) => page.slug === slug);
