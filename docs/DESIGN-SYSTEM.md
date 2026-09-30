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

## Colour

Neutrals are chosen for WCAG AA on both white and the page background:
`ink` 17.7:1, `ink-soft` 10.4:1, `ink-muted` 6.2:1, `ink-faint` 4.8:1 (least
important text only). Surfaces: `canvas` (page), `surface` (white panels),
`sunken` (table heads, hover rows, active nav). Borders: `line`, `line-strong`.

## Shape and elevation

Radius: 8px (`rounded-lg`) for controls and badges; 10-12px (`rounded-xl`,
`rounded-2xl`) for panels; `rounded-full` only for avatars and dots. Larger
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
| `Badge`, `StatusBadge`, `Alert`, `EmptyState`, `Skeleton`, `SegmentedControl` | `ui/primitives.tsx` |
| `Dialog`, `ConfirmDialog` | `ui/dialog.tsx` |
| `Toast` | `ui/toast.tsx` |
| `TransactionRow`, `TransactionIcon`, `TransactionAmount` | `components/wallet/transaction-row.tsx` |
| `MetricTile` (+ the `.metric-group` class) | `components/admin/charts.tsx`, `globals.css` |
| `ServiceLogo` | `components/service-logo.tsx` |
| `CountryFlag` | `components/country-flag.tsx` |
| Icons (one hand-drawn set, 1.7 stroke) | `components/icons.tsx` |

## Rules that are easy to break

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

## Motion

Fast and functional: 150-200ms, ease-out. Menus fade in; sheets slide up; the
favourite star does one short damped pop. Nothing loops except live status dots.
`prefers-reduced-motion` switches all of it off.

## Copy

Plain and specific. Buttons say what happens: "Pay GH₵ 50.00", "Get this number",
"Add funds" - not "Continue" or "Submit". Errors say what went wrong and whether
money moved: "We couldn't reserve a number. Your balance was not charged."
