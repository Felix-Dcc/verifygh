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

Inter for the interface - a variable font, loaded with `latin-ext` so the cedi
sign (₵) is Inter too, not a fallback glyph mid-word - and IBM Plex Mono for
codes, references and phone numbers (`.code`: slashed zero, tabular). Both are
self-hosted by `next/font`. Homepage headlines are extra-bold with tight
tracking (-0.035em).

| Token | Size / line | Use |
|---|---|---|
| `text-figure` | 36/40, 600 | The one headline number (wallet balance) |
| Hero headline | 36-52, 700 | The homepage `<h1>` on the band only |
| `.section-title` | 30-36, 700 | Marketing section headings (with `.section-lead` under them) |
| `text-display` | 30/36, 600 | Other marketing headlines |
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
| `navy`, `navy-deep`, `azure`, `aqua`, `leaf`, `leaf-light` | The homepage's night palette (hero, the privacy section, the close, the footer). Fixed in both themes. White text only on navy (`/75` for body, `/60` minimum for small print). "Use ours." and similar single phrases take `.text-dawn` (aqua into leaf) |
| `dawn-1` ... `dawn-12` | The ramp from navy into the page: one smooth curve through deep blue, azure, aqua and mint, computed in OKLab (Catmull-Rom through those colours, eased with smoothstep so it leaves the navy and arrives at the page gently) and sampled into twelve evenly spaced steps. Evenly spaced samples of a smooth curve mean no stop changes the slope enough to be seen as a line, and OKLab keeps blue-into-green clean instead of grey. Deep all the way down in the dark theme. Only the `atmosphere-night*` classes use them; regenerate them rather than hand-editing one |
| `band`, `band-deep` | The previous green band; kept for `onBand` buttons, which also sit on navy |
| `wash` | The palest green: a section set slightly apart without a border |
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

Radius: buttons are pills (`rounded-full`, set once in `buttonClasses`), and
so are chips and the homepage search; 8px (`rounded-lg`) for inputs, selects
and badges; 10-12px (`rounded-xl`, `rounded-2xl`) for panels; `rounded-full`
also for avatars, step numbers and dots. `rounded-device` (2rem) is for phone
mockups on marketing pages only. Larger
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
| `Device` (the one phone), `StatusBar`, `AddressBar`, `BottomNav`, `Halo`, `ScreenStack`, `Reveal`, `useStory`, `useInView` | `components/marketing/device.tsx` |
| Homepage sections: `Hero` + `PhoneOrbit`/`Stars` (`orbit.tsx`), `HowItWorks`, `ServicePicker`, `PaymentSection`, `PricingSection`, `PrivacySection`, `SecuritySection`, `ProductsSection`, `DashboardShowcase`, `Faq` | `components/marketing/` |
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
  no grids of icon-tile cards, no blurred blobs, glows or multi-colour
  gradients, no stat trios. Headings say something specific; illustrations
  are the real screens.
* **The homepage never changes colour at a line.** It is one surface from
  night to day and back (`atmosphere-*` in `globals.css`): the hero's navy
  ramps down through blue, teal and green into the page (`atmosphere-night`);
  the privacy section ramps up into navy and back down (`atmosphere-night-mid`);
  the close ramps up into navy (`atmosphere-night-close`) and the footer stays
  navy (`SiteFooter night`); lighter sections are set apart by a `wash`, never
  a border. Nothing is laid over a ramp - glows and light stay inside the navy
  - so the blends stay clean. White text only ever sits on the navy - pad the
  content by at least each fade (`--fade`, `--fade-in`, `--fade-out`).
* **Headings on navy set `text-white` themselves.** The base styles colour
  every `h1`-`h3` with `text-ink`, so an inherited white is overridden and the
  heading turns dark in light mode.
* **The main homepage action is `dawn`** (blue into green, white text at 5:1
  or better on both ends); inside the app, `primary` green stays the one
  solid action.
* **No testimonials until there are real ones.** Invented reviews - even
  "demo" ones - would be presented to real visitors as customers' words.

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

* **The product itself.** The homepage hero centres on a large, current
  "Pro"-class phone drawn in CSS (titanium frame, thin bezel, island, side
  keys - no photograph and no maker's name) showing the moment VerifyGH exists
  for: the order screen as a WhatsApp code arrives on a US number. Around it
  float the logos of services on sale today (popular first, from
  `/marketplace/home/`), a wallet card with today's WhatsApp price, and under
  it the real count of services. The hardware keeps its colours in both
  themes; the screen follows the site's. The picker
  below it is the live catalogue - popular first, searchable, each row opening
  that service ready to buy. "How it works" and the payment section show real
  screens as mockups, with live data where the screen shows data (prices, the
  supported networks from `/payments/options/`). The only invented values are
  an example order's number, from the 555 range reserved for fiction, and its
  code.
* **Illustrations** (`components/illustrations.tsx`), for empty states and
  help: 1.5px outlines in `line-strong`, one soft `brand-50` shape, one
  `brand-500` accent. Customer empty states use them (`EmptyState art=`); the
  admin console keeps compact icons.

Every homepage section tells its point with the product, not with icons and
paragraphs:

* **Hero** - a phone receiving a code (the digits fill in one by one), with
  the services on sale today revolving around it on two tilted rings
  (`PhoneOrbit`: logos pass behind the phone on the far side of a ring and in
  front of it on the near side).
* **How it works** is a mini product demo: choose a service from a live grid,
  get a US number, wait while the SMS lands, read the code as it fills in; a
  card beside the phone narrates what just happened.
* **Built for the way you verify** - a two-row marquee of live service logos
  above the service picker.
* **Mobile Money** is a top-up happening: Add funds filled in, the network's
  own PIN prompt (a plain system dialog - not VerifyGH's screen), then
  "Payment received" and the balance counting up - beside a flow diagram
  (Mobile Money -> wallet -> numbers) whose lines carry the money in step.
  Networks, their number prefixes and the quick amounts come from
  `/payments/options/`. No cards: top-ups are Mobile Money only.
* **Pricing** is one live price as a receipt (price, added at checkout
  GH₵ 0.00, taken from your wallet) with the cedi sign set huge behind it and
  today's other prices around it. The provider's cost is not public, so it is
  described, never quantified.
* **Your number, protected** (navy) - your masked number, the number the app
  sees, and a breathing shield between them ringed with the real layers.
* **Your money and account** - an annotated wallet: six numbered markers on
  the screen, each beside the protection that guards that part.
* **Everything you need to verify** - the products that exist (numbers,
  reuse, automatic refunds, favourites), each with its own picture. No voice,
  rentals or public API: they are not offered, so they are not shown.
* **Dashboard** - the app in a laptop from lg, on a phone below it.
* **FAQ** puts the Help screen on a phone with the first questions people ask
  floating around it; tapping one opens its answer in the list beside it.
  Every answer describes what the product does today.

Every phone is `Device` - one titanium-framed, current "Pro"-class phone drawn
in CSS, never a photograph and never named - showing a real VerifyGH screen
with the app's real labels.

Service logos sit in one container everywhere (`ServiceLogo`): the squircle,
a hairline outline, never stretched. Payment networks are named, not shown as
logos - their marks are not ours to use.

## Motion

Fast and functional: 150-200ms, ease-out. Menus fade in; sheets slide up; the
favourite star does one short damped pop; arrows in buttons nudge on hover.
Nothing loops except live status dots and the slow 6s drift of floating
logos, price tags and question bubbles (`animate-float`, on its own element so
it never replaces a positioning transform).

The homepage stories (`useStory`) step on their own only while their section
is on screen, every 3-4s; choosing a step hands control to the reader and
stops the stepping. Screens dissolve (`ScreenStack`: the new screen fades in
over the old, never two half-screens blended). Sections fade up once as they
scroll in (`Reveal`), never content already on screen at load. Under
`prefers-reduced-motion` nothing moves: stories stay put (Mobile Money shows
its outcome), reveals are skipped, and every animation is off.
`prefers-reduced-motion` switches all of it off.

## Copy

Plain and specific. Buttons say what happens: "Pay GH₵ 50.00", "Get this number",
"Add funds" - not "Continue" or "Submit". Errors say what went wrong and whether
money moved: "We couldn't reserve a number. Your balance was not charged."
