# Service logos

Every service shows its brand's official logo, or a neutral phone tile - never
a guessed or made-up one. A logo comes from one of three places, in this order:

1. **Uploaded by staff** (Admin > Catalog > a service > Logo). SVG or PNG,
   checked to be inert, served by the API.
2. **Bundled from Simple Icons**, CC0-licensed brand marks drawn as tiles in
   `frontend/public/service-icons/`. `backend/apps/catalog/service_icons.json`
   lists which services use which mark, and `SOURCES.json` records where each
   mark came from. A service gets its tile by its slug, or by its exact name
   when the catalogue sync adds it. Regenerate with
   `node frontend/scripts/generate-service-icons.mjs <simple-icons>`.
3. **Matched in Admin > Logos from Brandfetch**, for the long tail Simple
   Icons does not cover.

## Admin > Logos

The page lists every service on sale that still shows the neutral tile.

1. For each service, the API searches Brandfetch for brands with that name.
   The search is live; Brandfetch's terms don't allow storing results.
2. Each match shows its logo, its website, **Same name** when the names agree
   exactly, and **Claimed by the brand** when the company manages its own
   Brandfetch profile.
3. Pick the right company. If none is right, search for a different name, type
   the company's website (venmo.com), or choose **None of these**.

Every decision is in the audit log (`SERVICE_LOGO_BRAND`, `SERVICE_LOGO_NONE`).
Undo one with `DELETE /api/v1/admin/services/<slug>/brand-logo/`, which puts the
service back in the queue.

Nothing is matched automatically. Names like "Adams", "Circle" or "Neon" belong
to many companies, and a missing logo is better than someone else's.

### How the logo is shown

Brandfetch's terms require its logos to be **loaded from its CDN**. Customers'
browsers fetch them from `cdn.brandfetch.io`, and our servers never download or
store them. The URL asks for the square brand icon at 128 px, with
`fallback/404`. When a brand has no logo, the browser gets a 404 and the app
shows its own neutral tile, never a placeholder letter.

The site's Content-Security-Policy allows that one image origin
(`frontend/src/proxy.ts`). An image cannot run code. The privacy policy
says Brandfetch sees a visitor's IP address and browser, as any image host does.

## Setting up Brandfetch

1. Create a free account at https://developers.brandfetch.com and copy your
   **client ID**.
2. In Railway, on **verifygh** (the API), set `BRANDFETCH_CLIENT_ID`.
3. Open Admin > Logos.

The free plan covers 500,000 searches and 1,000,000 logo loads a month. Its
throughput limits apply per IP: 200 searches and 1,000 logo loads every five
minutes. A page of the queue makes about 20 searches. If Brandfetch says to slow
down, the page says so; wait a few minutes. No attribution is required.

The client ID is part of every logo URL, so it is not a secret. If you replace
it, logos chosen with the old ID keep its URL. Choose them again, or ask for a
one-off update of `icon_url` from `logo_domain`.
