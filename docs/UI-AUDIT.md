# VerifyGH UI audit

Phase 1 of the interface overhaul, 2026-09-30. Every route was inspected in the
running app at 1280px and 375px, and the component code was read. Findings are
facts about the current build, with the evidence next to each.

## What is already right (keep it)

* **A token layer exists.** `tailwind.config.ts` defines a restrained palette - one
  deep Ghanaian green, a gold accent, warm neutrals, semantic colours - plus
  shadows, radii and motion. Nothing is styled with raw hex in most places.
* **Touch and focus basics.** Every button size is at least 44px tall;
  `:focus-visible` shows a ring for keyboard users only; `prefers-reduced-motion`
  is honoured; tabular figures are used for money.
* **One icon family.** `components/icons.tsx` is a single hand-drawn set with one
  stroke weight. No Font Awesome, no emoji-as-icon.
* **Real states.** Skeleton loaders, an `EmptyState`, human error messages from the
  API's error envelope, a nonce-based CSP. Data comes from SWR; nothing is faked.
* **A sound shell.** Fixed sidebar on desktop, bottom navigation on mobile with
  safe-area insets.

## 1. Visual hierarchy

| Problem | Evidence |
|---|---|
| The same saturated dark-green block is the "hero" everywhere, so nothing stands out | Sidebar balance, dashboard balance, wallet balance and the referral panel are all `bg-brand-700` blocks with white text |
| The balance is repeated on one screen | Dashboard and wallet show it in the sidebar block *and* the page hero (and in the mobile top bar) |
| The greeting is said twice | Top bar "Good morning, Kwame" and page title "Hello, Kwame" |
| Dashboard leads with navigation, not information | Four icon tiles (Buy verification, Orders, Transactions, **Profile**) and three stat tiles come before anything in progress; on a 375px phone the first in-progress order is two screens down |
| Stat tiles for their own sake | "Today's spending GH₵0.00", "Successful orders 2", "Active orders 5" - generic dashboard furniture with an icon in a square each |

## 2. Layout: everything is a card

* `<Card>` is used 84 times. Page sections, stat tiles, quick actions, form groups,
  single sentences ("Mark as complete" explainer) all sit in bordered, shadowed,
  2xl-rounded boxes.
* Cards inside cards: order detail (number card, code card, complete card, report
  card, timeline card, details card - six boxes for one order), account (profile
  card then a details card), referral (hero block containing bordered chips).
* Result: every surface has the same weight, and the page reads as a stack of
  equal boxes - the most recognisable "template dashboard" signature.

## 3. Typography

* **No brand typeface.** The stack is `ui-sans-serif, system-ui, Segoe UI...`, so
  the product is Segoe UI on Windows, San Francisco on iOS and Roboto on Android -
  three different products.
* **No type scale.** Sizes are chosen per component: `text-2xl`, `text-3xl`,
  `text-4xl`, `text-[3.4rem]`, `text-[11px]`, `tracking-[0.2em]`, `tracking-[0.4em]`.
* Section labels use uppercase-tracked micro text in some places and sentence case in
  others.
* Verification codes are set in the body face with 0.2em tracking rather than a
  monospace face designed for digits.

## 4. Money and data formatting

| Problem | Evidence |
|---|---|
| Three currency spellings | UI: `₵146.50` (`lib/format.cedis`); server messages: `GHS 7.50`; seven literal `GHS` strings in components |
| The bare `₵` is ambiguous outside Ghana and uncommon in Ghanaian fintech UI | Ghanaian banks and MoMo apps write `GH₵` |
| Negative amounts use a hyphen | `signedCedis` returns `-₵14.50`; a true minus sign (U+2212) aligns with `+` |
| Status labels are generated mechanically | `StatusBadge` title-cases the enum: "Waiting For Code", "Code Received", "Payment Pending" |
| Country flags are emoji | On Windows, emoji flags render as letters: the marketplace shows "us United States", "ca Canada" |

## 5. Colour and contrast (WCAG 2.1 AA needs 4.5:1 for body text)

| Token | On white | On page background | Used for text |
|---|---|---|---|
| `ink-faint` #9AA6A0 | **2.52** | **2.38** | 55 times - timestamps, hints, table headers |
| `ink-muted` #6B7A73 | 4.51 | **4.27** | everywhere - secondary text on the canvas fails |
| `ink-soft`, `ink`, brand and status 700s | 5.3 - 17.7 | pass | |

## 6. Radius, borders, elevation

* Radii in use: `rounded-lg`, `xl` (91 uses), `2xl`, `3xl` (21), `full`, `[23%]` - no
  rule for which surface gets which.
* Every card has both a border and a shadow; shadows add no information at this
  density.
* 38 arbitrary Tailwind values (`text-[11px]`, `rounded-[23%]`, `text-[#0b3d25]`...).

## 7. Navigation and shell

* Sidebar: the balance block is the loudest thing on every page, above navigation.
* Top bar on desktop holds only a greeting and a bell - no search, no account menu.
* Mobile bottom nav holds Home, Services, Orders, Wallet, **Refer**. Account is not
  reachable from the navigation at all on mobile (only via the dashboard "Profile"
  tile).
* Admin uses the customer shell unchanged; the admin nav has 12 items and no
  grouping.

## 8. Page-specific findings

* **Marketplace** (`/services`): the strongest page - compact rows, pins, popular,
  search. Issues: emoji flags; the "SMS / Voice Soon" toggle takes prime space for a
  feature that does not exist; availability text and price compete.
* **Buy dialog**: shows price and balance but not the balance *after* purchase.
* **Deposit**: one long form; the button says "Send payment prompt" without the
  amount; no review step before the phone prompt.
* **Verification session** (`/orders/[ref]`): the code is visually strong, but it is
  one of six equal cards; "Mark as complete" sits between the code and the problem
  report.
* **Wallet**: transactions list and top-ups are two side-by-side cards with
  different row designs for the same kind of data.
* **Orders**: a real table on desktop and a list on mobile - good. Status copy and
  the reference column need work.
* **Notifications**: a flat list with a green dot, no grouping by day, no icon for
  the kind of event.
* **Account**: a narrow column of stacked cards; security (verified email, sessions,
  password) is not surfaced as a section of its own.
* **Referral**: "Refer & Earn" hero in saturated green with a monospaced code in
  spaced capitals; stat tiles again.
* **Auth pages**: clean but generic: centred card, "Welcome back".

## 9. Mobile

* Dashboard: seven full-width cards before any activity.
* Top bar balance pill duplicates the dashboard hero.
* Tables become lists on Orders (good) but not everywhere (admin tables scroll).

## 10. Dark mode

Not supported today. Adding it is out of scope for this pass; the token work below
keeps it possible later without touching components.

## Consequences for the redesign

1. Fix the foundations first - type face and scale, contrast-safe neutrals, one
   radius rule, border-only surfaces, one money format, human status copy, flags
   that render everywhere - so every page improves at once.
2. One point of emphasis per page. The balance appears once, in type, not in a
   green slab.
3. Sections and dividers instead of cards; cards only where a group needs a
   boundary.
4. Keep every data flow and API call exactly as it is.

## Outcome (September 2026)

What each finding became. Details of the rules are in `docs/DESIGN-SYSTEM.md`.

| Finding | Resolution |
|---|---|
| No brand typeface | IBM Plex Sans and Mono, self-hosted with `next/font` |
| `ink-faint` 2.52:1, `ink-muted` 4.27:1 | Neutrals re-picked: every text token passes AA on white and on the page background |
| ₵ / GHS / GH₵ mixed | `GH₵ 1,250.00` everywhere, in the app and in backend-written notifications, errors and order events (`format_ghs`); older stored text is shown the same way (`moneyText`) |
| Emoji flags render as letters on Windows | `CountryFlag` SVGs on every screen, admin included |
| Raw statuses (`WAITING_FOR_CODE`) | `statusLabel()` - "Waiting for SMS", "Code received" |
| Everything in a card; green slabs | Sections and dividers; the wallet, dashboard and referral slabs are plain panels; admin figures sit in one `metric-group` per group |
| Buy dialog lacked the balance after purchase | Number price, current balance and after purchase; the button carries the amount |
| Deposit: one long form, no amount on the button | Three numbered steps, a review, and "Pay GH₵ 50.00" |
| Verification session: six equal cards | Number, code, reuse and actions in one panel; the code is the loudest thing on the page |
| Wallet: two row designs for one kind of data | One `TransactionRow` on the wallet, dashboard and statement |
| Notifications flat | Grouped Today / Yesterday / Earlier with an icon per kind; rows open their order |
| Account: stacked cards | Settings in labelled sections: Profile, Security, Notifications and policies, Sign out |
| Mobile: seven cards before activity; Account missing | Balance, at-a-glance, then activity; bottom nav includes Account |
| Touch targets | Every control 44px tall on phones (audited per page at 375px) |
| Layout at 360px | Breakpoint-only grids get `grid-cols-1`, so nothing forces a sideways scroll |

Still open, deliberately:

* **Dark mode** - out of scope; the tokens keep it possible.
* **Active sessions list** - the backend has no sessions endpoint, and the redesign
  does not invent one. "Change password" still signs every other session out.
* ~~Legal pages used `verifygh.example` placeholder addresses~~ - fixed: every
  contact now goes to `support@getverifygh.com` (privacy and abuse reports with a subject line).

