# VerifyGH design system

The rules the interface is built on. Tokens live in `frontend/tailwind.config.ts`,
base styles in `frontend/src/app/globals.css`, components in
`frontend/src/components/ui/`. Why each rule exists is in `docs/UI-AUDIT.md`.

## Principles

1. **One point of emphasis per screen.** The balance on the wallet, the code in a
   verification session, the price in a purchase. Everything else is quieter.
2. **Sections and dividers first, cards second.** A card is a boundary for a group
   that needs one; it is never the default container. No card inside a card.
3. **Colour means something.** Green: brand action, or success. Amber: attention.
   Red: failure or danger. Blue: in progress. Grey: everything else. Gold only for
   rewards. No gradients, no tinted section backgrounds.
4. **Real data only.** No invented statistics, activity, testimonials or scarcity.
   An empty state explains what will appear and what to do.

## Type

IBM Plex Sans for the interface, IBM Plex Mono for codes, references and phone
numbers (`.code`: slashed zero, tabular). Both are self-hosted by `next/font`.

| Token | Size / line | Use |
|---|---|---|
| `text-figure` | 36/40, 600 | The one headline number (wallet balance) |
| `text-display` | 30/36, 600 | Marketing headlines only |
| `text-title` | 22/30, 600 | Page titles (`PageHeader`) |
| `text-heading` | 17/24, 600 | Section titles (`Section`), dialog titles |
| `text-base` | 16/24 | Form inputs (iOS zooms anything smaller) |
| `text-sm` | 14/20 | Body - the default for the app |
| `text-label` | 13/20, 500 | Form labels |
| `text-caption` | 12/18 | Metadata, hints, badges |
| `text-2xs` | 11/16 | Group labels, tight table metadata |

Money uses `.tabular` everywhere so columns do not jitter.

## Colour and themes

Every colour is a token (`tailwind.config.ts`) backed by a CSS variable
(`globals.css`) that holds an "R G B" triplet, defined once for light (`:root`)
and once for dark (`.dark`). Components use the token - `bg-surface`,
`text-ink-muted`, `border-line` - and never name a theme. `dark:` variants are
not needed and should not appear.

| Token | Use |
|---|---|
| `canvas` / `surface` / `sunken` | Page, panels, table heads and hover rows |
| `raised` | Things that float: menus, dialogs, sheets |
| `scrim` | Behind a dialog, always with an opacity (`bg-scrim/50`) |
| `ink`, `ink-soft`, `ink-muted`, `ink-faint` | Text, most to least important |
| `line`, `line-strong` | Borders and dividers |
| `primary` (+ `-hover`, `-active`) | Filled primary buttons - white text on it |
| `danger-solid` | Filled destructive buttons - white text on it |
| `brand-*`, `success-*`, `warn-*`, `info-*`, `gold-*` | 50: tint backgrounds; 200: tint borders; 500: dots, rings, focus; 700: text on surfaces or tints |

Why `primary` exists apart from `brand-600/700`: in dark mode a button fill must
stay deep (white text on it) while brand *text* must turn light. One token can
not do both. Never put `text-white` on a `brand-*` fill - use `bg-primary`.

Dark is its own palette, not an inversion: deep green-grey surfaces (never pure
black), text at AA or better (`ink-muted` 7.0:1, `ink-faint` 5.1:1 on
`surface`), fills deep enough for white text (`primary` 5.0:1), and deeper,
softer shadows. Light keeps the values in docs/UI-AUDIT.md section 5.

The theme is chosen per device (Light / Dark / System - `ThemeSwitcher` in the
account menus, Settings and the site footer) and stored in localStorage.
`THEME_SCRIPT` in `lib/theme.ts` runs in `<head>` with the CSP nonce and sets
the class before the first paint, so there is no flash. On "System" the page
follows the device live and re-checks whenever the tab comes back into view.

## Shape and elevation

Radius: 8px (`rounded-lg`) for controls and badges; 10-12px (`rounded-xl`,
`rounded-2xl`) for panels; `rounded-full` only for avatars and dots. `rounded-device`
(2rem) is for phone mockups on marketing pages only. Larger
aliases are pinned to 12px. Borders separate surfaces; shadows (`shadow-raised`,
`shadow-pop`) are only for things that float - menus, dialogs, toasts.

## Money and data

* Cedis: **`GH₵ 1,250.00`** - `cedis()` in `lib/format.ts`. Never `₵`, never `GHS`
  in the interface.
* Signed ledger amounts: **`+GH₵ 50.00`** / **`−GH₵ 10.00`** (a true minus) -
  `signedCedis()`. The sign is always shown so direction never depends on colour.
* Dollars (staff screens): **`$12.50`** - `usd()`.
* Dates: `formatDate` / `formatDateTime` (Accra time), relative time for recent
  activity.
* Statuses: `StatusBadge` and `statusLabel()` - "Waiting for SMS", "Code received",
  never the raw enum.
* Countries: `CountryFlag` (SVG; emoji flags render as letters on Windows) next to
  the country name.

## Components

| Component | Where |
|---|---|
| `AppShell`, `PageHeader` | `components/app-shell.tsx` |
| `Button`, `Input`, `Select`, `Textarea`, `Checkbox`, `Field` | `ui/primitives.tsx` |
| `ButtonLink` (a link styled as a button), `PasswordInput` (show/hide) | `ui/primitives.tsx` |
| `Card`, `CardHeader`, `Section`, `DescriptionList`, `Amount` | `ui/primitives.tsx` |
| `Badge`, `StatusBadge`, `Alert`, `EmptyState`, `LoadError`, `Skeleton`, `SegmentedControl` | `ui/primitives.tsx` |
| `Dialog`, `ConfirmDialog` | `ui/dialog.tsx` |
| `Toast` | `ui/toast.tsx` |
| `TransactionRow`, `TransactionIcon`, `TransactionAmount` | `components/wallet/transaction-row.tsx` |
| `MetricTile` (+ the `.metric-group` class) | `components/admin/charts.tsx`, `globals.css` |
| `ServiceLogo` | `components/service-logo.tsx` |
| `CountryFlag` | `components/country-flag.tsx` |
| `ThemeProvider`, `ThemeSwitcher`, `useTheme` | `components/theme.tsx` |
| Illustrations (`PhoneMessageArt`, `StatementArt`, `WalletArt`, `BellArt`, `SearchArt`, `InviteArt`, `SupportArt`) | `components/illustrations.tsx` |
| Icons (one hand-drawn set, 1.7 stroke) | `components/icons.tsx` |

## Rules that are easy to break

* **A request that failed says so.** Every data section handles its error with
  `LoadError` ("We couldn't load your orders." + Try again) - never an empty
  state, never an endless skeleton. A missing amount renders as "—"
  (`cedis()` does this), never "GH₵ 0.00": a zero balance is a statement about
  the customer's money.
* **One primary button per screen.** The top bar's "Add funds" is secondary;
  closing an order is secondary; the page's main action is the only solid green.
* **Nothing twice.** A list that shows a row does not sit above another list
  showing the same row (favourites vs. quick picks, in-progress vs. recent
  orders); a panel does not repeat what its header already says.
* **No template furniture on marketing pages:** no eyebrow labels over headings,
  no grids of icon-tile cards, no gradient washes or blurred blobs, no stat
  trios. Headings say something specific; illustrations are the real screens.

* **An action that goes somewhere is a `ButtonLink`**, never `<Link><Button>`: a
  button inside a link is two tab stops and invalid HTML.
* **44px touch targets on phones.** Buttons, tabs, menu items and chips are 44px
  tall below `sm`; the small button size tightens to 40px only from `sm` up.
* **A grid that only sets columns from a breakpoint up also sets `grid-cols-1`.**
  Without it the single mobile column sizes to its widest child and the page
  scrolls sideways at 360px.
* **`cn` is plain `clsx`**, not tailwind-merge: when two classes conflict, the
  one later in the stylesheet wins, not the one later in the string. Override
  with a responsive variant or remove the conflicting class.
* **Service logos are decorative** (`alt=""`): the name is always written beside
  them.
* **Form controls go inside `Field`**, which links them to their hint or error
  (`aria-describedby`).
* **Gold is for rewards only** - promotional credit, referral bonuses (`Badge
  tone="gold"`).

## Imagery

No stock photography and no raster images. Two kinds of picture, both drawn
in code with theme tokens so they work in light and dark and weigh bytes, not
megabytes:

* **The product itself.** The homepage hero, the "How it works" steps and the
  payment section show real screens as mockups - with live data where the
  screen shows data (today's popular services and prices from
  `/marketplace/home/`, the supported networks from `/payments/options/`). The
  only invented values are an example order's number, from the 555 range
  reserved for fiction, and its code, and the mockup says so.
* **Illustrations** (`components/illustrations.tsx`), for empty states and
  help: 1.5px outlines in `line-strong`, one soft `brand-50` shape, one
  `brand-500` accent. Customer empty states use them (`EmptyState art=`); the
  admin console keeps compact icons.

Service logos sit in one container everywhere (`ServiceLogo`): the squircle,
a hairline outline, never stretched. Payment networks are named, not shown as
logos - their marks are not ours to use.

## Motion

Fast and functional: 150-200ms, ease-out. Menus fade in; sheets slide up; the
favourite star does one short damped pop. Nothing loops except live status dots.
`prefers-reduced-motion` switches all of it off.

## Copy

Plain and specific. Buttons say what happens: "Pay GH₵ 50.00", "Get this number",
"Add funds" - not "Continue" or "Submit". Errors say what went wrong and whether
money moved: "We couldn't reserve a number. Your balance was not charged."
