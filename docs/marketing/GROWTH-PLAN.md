# VerifyGH — Growth plan, audit and campaigns

Prepared 17 Oct 2026. Every product claim below was checked against the live site
(getverifygh.com), the public catalogue API and the repository on that date.
**Assumptions are labelled `ASSUMPTION`.** No revenue, margin or conversion figure is
invented; where data is missing it says so and says how to get it.

---

## 0. Read this first: the two things that decide whether marketing pays

1. **Cash collection works, but on a stopgap.** Top-ups run through SENDI (since 8 Oct).
   Withdrawals were blocked on 15 Oct and **go through smoothly again as of 17 Oct**.
   308 top-ups worth **GH₵5,378.25** went through it 8–15 Oct. SENDI is still not on the
   Bank of Ghana licensed list, so it remains a stopgap until Moolre or Paystack is live.
   **Rules:** withdraw the SENDI balance to MoMo often (at least daily while ads run), so
   little cash sits there; if a withdrawal fails again, pause all paid ads the same day.
   Paid tests can start in week 1, within the Lean budget, and move to Moderate only on
   the scorecard's decision rules.
2. **43% of orders end without a code.** From the admin dashboard (17 Oct, see
   "Real numbers" below): 538 delivered, 413 refunded. Customers get their money back
   automatically, but every refund is a disappointed customer and lost revenue.
   **Raising the delivery rate is the biggest growth lever you have, ahead of any ad.**
   Lifting it from 56.5% to 70% on today's demand would add about **GH₵2,070 of revenue
   a month** with no extra spend.

---

## Real numbers (admin dashboard, last 30 days to 17 Oct 2026)

| Metric | Value |
|---|---|
| Revenue | GH₵8,768.63 (GH₵109 of it from rentals) |
| Profit after provider cost | GH₵2,340.73 — **26.7% margin** |
| Orders | 953: **538 delivered (56.5%)**, 413 refunded, 1 failed, 1 in progress |
| Average delivered order | **GH₵16.10** |
| Profit per delivered order | **GH₵4.35** |
| Deposits | GH₵10,558.25 from 601 successful top-ups (average GH₵17.57) |
| Failed payment attempts | **274 (31% of attempts)** |
| Network split | ~73% GH₵7,672.50 · ~27% GH₵2,846.75 · AT GH₵39 |
| Users | 1,005 new, 79% verified their email, 477 active in 30 days |
| Money left in wallets | ~GH₵1,790 (deposits − revenue), owed to customers |

These are all-time numbers too: VerifyGH launched around 30 Sept, so the 30 days and
all-time match. **1,005 sign-ups in about 3 weeks, with no ad budget**, is strong
demand. The new attribution will show where it comes from.

### Delivery by service (estimate)

Estimated as revenue ÷ today's price, so treat as approximate; the Orders page has the
exact figures.

| Service | Orders | Est. delivered | Est. delivery rate | Marketing use |
|---|---|---|---|---|
| WhatsApp | 221 | ~182 | **~82%** | Lead service: most revenue (GH₵4,637), reliable |
| Snapchat | 29 | ~27 | **~93%** | Cheap entry point (GH₵4.50) for first purchases |
| Signal | 83 | ~49 | ~59% | OK |
| Telegram | 220 | ~96 | ~44% | High demand, poor delivery — fix before promoting |
| Instagram | 69 | ~29 | ~42% | Don't promote yet |
| Facebook | 135 | ~46 | **~34%** | Don't promote yet |
| TikTok | 48 | ~14 | **~29%** | Don't promote — and don't use it in demo videos |

### What this changes

1. **Fix delivery first** (product work, not marketing): build a per-service delivery-rate
   view; for services under ~40%, try another provider route, show an honest note, or
   pause them. A visitor whose first order refunds rarely comes back.
2. **Payment failures (31%)**: check Admin > Payments for the reasons, separating
   people who abandon the SENDI page from real errors. Each fixed failure is a
   customer who was ready to pay.
3. **Email verification (21% never verify)**: about 210 accounts can't buy. A reminder
   email at 24 h is cheap to test.
4. **Marketing leads with what works**: WhatsApp, Snapchat, Signal. Demo videos use
   WhatsApp or Snapchat, never TikTok or Facebook until their delivery improves.
5. **Wallet float**: ~GH₵1,790 of customer money sits in wallets. Keep at least that much
   in the provider balance or reachable at all times.

---

## Deliverable 1 — Business and market assessment

### What VerifyGH is (verified)

- US phone numbers to receive one SMS verification code, for **2,342 services** in the
  live catalogue (17 Oct). US is the only country today.
- Number rentals (multi-day) exist for signed-in users.
- Popular prices today: Instagram, Discord, X GH₵9.00 · Signal GH₵11.50 · TikTok,
  Google/Gmail GH₵13.50 · Facebook GH₵15.50 · Telegram GH₵16.00 · WhatsApp GH₵25.50.
  Cheapest service seen: GH₵4.50 (Airbnb). Prices move with provider cost and the cedi.
- Paid from a prepaid **cedi wallet** topped up with **MTN MoMo, Telecel Cash, AT Money**.
  Top-up GH₵10–2,000. The checkout page adds **1.4%** (GH₵10 costs about GH₵10.14).
- **Automatic full refund** to the wallet if no code arrives before the number expires.
- Free account, email + password or Google; email must be confirmed before buying.
- Referral programme: friend gets GH₵2 promo credit after a GH₵10+ first top-up;
  referrer gets GH₵3 after the friend's first cash-paid number. Promo credit cannot be
  withdrawn. Cap 40 successful referrals/month per user.
- Already measurable: Cloudflare Web Analytics (page views). Not measured until this
  change: which channel a sign-up came from.

### What it does well

- **Pays the way Ghanaians pay.** No card, no crypto, no dollars — the single biggest
  barrier to the global SMS-verification sites, which want a USD card or crypto.
- **Price shown in cedis before buying, nothing added at checkout** (apart from the
  disclosed 1.4% top-up fee).
- **Refunds are automatic.** Informal resellers on WhatsApp/Telegram ask you to trust
  them; VerifyGH refunds by itself. This is the strongest trust message you own.
- **Premium, mobile-first site.** Navy-to-green brand, live product mockups, clear FAQ.
- **Wide catalogue** (2,000+ services) — anything someone needs a code for is probably there.

### Biggest barriers to sales

| Barrier | Evidence | Fix |
|---|---|---|
| Unclear trust: "Who are you?" | No company name, address, phone/WhatsApp support line or social links on the site; no reviews (correctly — none are verified yet) | Add business registration name once the ORC certificate lands (expected 28 Oct); WhatsApp support link; collect real reviews (see referral/review campaign) |
| Site said "Payments processed by Paystack" — untrue since 8 Oct | Homepage payment and privacy sections | **Fixed in this change** |
| Price not visible above the fold | Hero showed no price | **Fixed**: "Numbers from GH₵X" (live) in the hero |
| Sign-up → first purchase has 4 steps (account, confirm email, top up, buy) | Purchase gate in code | Keep (it protects you), but cut friction: see Deliverable 2 |
| WhatsApp, the most-wanted service, is the most expensive (GH₵25.50) | Live catalogue | Lead ads with GH₵9–13.50 services; show WhatsApp price honestly |
| Payment provider is a stopgap | SENDI not BoG-licensed; withdrawals were blocked 15–17 Oct, working again since 17 Oct | Withdraw daily; pause ads if a withdrawal fails; move to Moolre/Paystack when approved |
| Search visibility near zero | No sitemap, no canonical, generic title | **Fixed** basics; landing pages next |

### Most promising customer segments (ranked)

| # | Segment | Need | Why VerifyGH | Objection | Message | Channels | Frequency / value |
|---|---|---|---|---|---|---|---|
| 1 | **Privacy-conscious everyday users** (students, young professionals, 18–34) | Sign up to apps without handing out their personal number; a second number for marketplace/dating/shopping apps | MoMo, cedis, refund | "Is this legit? Will I lose my money?" | "Don't give out your number. Use ours." + refund promise | TikTok, WhatsApp Status, Instagram | 1–3 numbers/quarter; low LTV, large volume |
| 2 | **Online sellers & digital entrepreneurs** | Keep business sign-ups (Google, TikTok Shop, Shopify, Telegram channels) separate from the personal line | Fast, MoMo, many services | Price vs. buying a second SIM | "Your business accounts shouldn't depend on your personal SIM" | TikTok, Instagram, X, Facebook groups for entrepreneurs | 3–10 numbers/quarter; best LTV |
| 3 | **Social media managers & creators** managing client or brand accounts | Verification for brand accounts they set up for clients | Speed, receipts in one dashboard | "Will the platform reject it?" (be honest: some apps reject virtual numbers; refund if no code) | "Set up client accounts without your own number on every one" | LinkedIn, X, Instagram | Repeat, medium |
| 4 | **Developers & QA testers** | Test SMS sign-up flows on real numbers | Real US numbers, pay in cedis, Developer category exists | No API yet (FAQ asks "Do you provide an API?") | "Test your OTP flow on a real number for the price of a snack" | X, LinkedIn, dev WhatsApp/Telegram communities, GDG/university clubs | Low volume today; high if an API ships |
| 5 | Diaspora/returnees needing US services | Access US-number-only apps | US numbers | Small group | — | Later | — |

**Focus the first 30 days on 1 and 2.** They are the biggest, they live on TikTok and
WhatsApp, and the product already fits them. Do not use any message about multiple or
replacement accounts, getting around bans, or "beating" a platform's checks — the
Acceptable Use Policy forbids it, platforms reject such ads, and it attracts the
customers most likely to cause chargebacks and abuse.

### Competitive position (to verify with a 30-minute price check)

- **Global SMS-activation sites**: cheaper per number in USD but need a card or crypto
  and English-only USD pricing. VerifyGH wins on payment and cedi pricing.
- **Informal WhatsApp/Telegram resellers**: accept MoMo, but manual, slow, no automatic
  refund, no dashboard. VerifyGH wins on speed, refund and trust.
- `ACTION`: record 5 competitor prices for WhatsApp, TikTok, Google, Telegram in a sheet
  each Monday. I did not fetch competitor prices because they change daily and a stale
  comparison is worse than none. Never name competitors in ads.

---

## Deliverable 2 — Website conversion audit

Journey: Visitor → Landing → Registration → Email confirmation → Top-up → Pick service →
Buy → Code → Repeat.

| # | Finding | Evidence | Impact | Recommendation | Status |
|---|---|---|---|---|---|
| 1 | Inaccurate payment claim ("processed by Paystack") | `payment-section.tsx`, `privacy-section.tsx` | Trust/legal risk | Provider-neutral wording | **Done** |
| 2 | No price, payment or refund reassurance above the fold | Hero only had headline + CTA | Visitors leave before scrolling to pricing | Trust line: from-price, networks, refund | **Done** |
| 3 | No sitemap; robots.txt has no sitemap or rules (Cloudflare content signals only) | `/sitemap.xml` returned 404 | Slower indexing | `sitemap.ts`, `robots.ts` | **Done** |
| 4 | apex and www both serve the homepage with no canonical | both 200, no `<link rel=canonical>` | Split ranking | Canonical on home, /services, /help | **Done** (also add a Cloudflare 301 apex→www — your action) |
| 5 | Generic title/description ("VerifyGH — SMS Verification") | live HTML | Low search click-through | Keyword-led title and description | **Done** |
| 6 | No structured data | none in HTML | No brand knowledge panel signals | Organization + WebSite JSON-LD | **Done** |
| 7 | No acquisition-channel measurement | no UTM capture; User has no source field | Cannot tell which channel pays | First-touch UTM/referrer captured, stored on the sign-up audit entry | **Done** |
| 8 | "Sign up with Google" sits below the whole form and needs the terms box ticked first | `/register` | The fastest path (Google, and the email is already confirmed) is the least visible | Put Google first with the terms checkbox above it | **Needs your approval** — changes how terms consent is collected |
| 9 | Duplicate "X (Twitter)" in Popular list | `/marketplace/home/` returns X twice | Looks careless | Merge the two catalogue entries in Admin > Catalog | **Your action** (catalogue data) |
| 10 | Prices load client-side only | pricing/picker use SWR | Search engines and slow 3G users see skeletons first | Server-render the popular prices on / and /services | Proposed (moderate) |
| 11 | No per-service landing pages | only /services | Misses searches like "US number for WhatsApp verification Ghana" | `/numbers/whatsapp` etc. for the top ~15 services, with live price, honest notes, FAQ | Proposed — biggest SEO opportunity |
| 12 | No visible human support channel besides email | /help | Ghana buyers expect WhatsApp | Add a WhatsApp Business link on /help and the footer | Needs your number |
| 13 | No company identity | footer | Trust | Registered name once ORC certificate arrives | After 28 Oct |
| 14 | First top-up minimum GH₵10 vs WhatsApp GH₵25.50 | payment options | Some first buyers need two top-ups | Suggest the right amount: "WhatsApp costs GH₵25.50 — top up GH₵30" | Proposed (deposit UI, not payment logic) |

Not touched, on purpose: prices, payment logic, wallet, provider integrations.

---

## Deliverable 3 — 30-day plan (18 Oct – 16 Nov 2026)

### Channel priorities

1. **TikTok organic** (primary) — your audience is there and a demo video is the best
   trust-builder you have.
2. **WhatsApp Status + Channel** — free, high-trust, drives repeat purchases.
3. **SEO** — slow, compounding; basics done, landing pages in week 2–3.
4. **Referrals** — the programme exists; promote it to existing buyers.
5. **Instagram Reels / Facebook** — repost TikTok cuts; Facebook groups for entrepreneurs.
6. **X / LinkedIn** — developers and creators, 2–3 posts/week.
7. **Paid**: TikTok Promote / Spark Ads test from week 2 (payouts work again); Google Search
   small test once landing pages exist; Meta last.

### Week by week

| Week | Goal | Work | Target (decide on these) |
|---|---|---|---|
| 1 (18–24 Oct) | Measurement + trust | Deploy this change; set up UTM links (below); WhatsApp support link; merge duplicate X; record 3 real screen recordings of a purchase (your own GH₵9 Instagram/Discord number); post 1 TikTok/day | Baseline: visits/day, sign-ups/day, first-purchase rate |
| 2 (25–31 Oct) | Content engine + first paid test | 7 TikToks (scripts 1–5 + 2 replies to comments); GH₵75–150 TikTok Promote on the best week-1 video, with UTM link; WhatsApp Channel launch; ask the first 20 buyers for a review (no reward for positive reviews) | ≥1 video >5,000 views; sign-ups from `utm_source=tiktok` measurable |
| 3 (1–7 Nov) | Conversion + SEO | Build landing pages for the services that deliver (WhatsApp, Snapchat, Signal; add Telegram once its delivery improves); referral push to buyers; ORC name in footer if certificate arrives | Sign-up → first purchase ≥ 30% (`ASSUMPTION` target; set after week 1 baseline) |
| 4 (8–16 Nov) | Scale what works | If the week-2/3 TikTok test met the CAC ceiling, move to the Moderate budget on that video and channel; otherwise try new creative at Lean spend; review scorecard | CAC below the ceiling in Deliverable 5 |

### Daily routine (45–60 minutes)

- 09:00 check yesterday's numbers (scorecard).
- 1 TikTok (record in batches of 3 on Sunday) → same cut to Reels and WhatsApp Status.
- Reply to every comment within 2 hours; turn the best questions into the next video.
- 1 platform-specific post (calendar below).
- 18:00–21:00 post time for TikTok (`ASSUMPTION` — check TikTok analytics after week 1).

### Advertising test plan

| | TikTok (Spark Ads / Promote) | Google Search | Meta (FB/IG) |
|---|---|---|---|
| Audience/intent | Ghana, 18–34, interests: entrepreneurship, social media, tech | People searching "US number for verification", "virtual number Ghana", "receive SMS online Ghana" | Ghana 18–34, small business interests |
| Objective | Website visits → sign-ups (Promote "website visits") | Clicks to landing pages | Traffic, then conversions once pixel is approved |
| Structure | 1 campaign, 3 ad videos (best organic posts), 1 audience | 1 campaign, 2 ad groups (generic + per-service) | 1 campaign, 2 creatives |
| Destination | `/?utm_source=tiktok&utm_medium=paid&utm_campaign=<name>&utm_content=<video>` | landing page per service | home |
| Conversion event | Sign-up (attribution), then first purchase (from admin data) | same | same |
| Kill rule | After GH₵75 spend: 0 sign-ups → stop that ad | CPC > GH₵3 with no sign-ups after 50 clicks → stop | 2× CAC ceiling with no purchase → stop |
| Scale rule | CAC ≤ ceiling for 2 consecutive weeks → +30% budget/week | same | same |

Your earlier TikTok promotion: **GH₵75.94 for a $4 promotion** (bought via coins).
Treat it as a comparison only. Buy Promote in cedis via card/MoMo where available —
coins add a markup. That GH₵75.94 pays for itself only if it brings about **6 paying
customers who each buy ~3 numbers** at the 35%-margin scenario below.

### Budget scenarios (30 days, cedis)

| | Lean | Moderate | Growth |
|---|---|---|---|
| Paid ads | GH₵150 (one TikTok test) | GH₵600 | GH₵1,500 |
| Test purchases for demo videos | GH₵50 | GH₵80 | GH₵120 |
| Referral promo credit (expected) | ~GH₵50 | ~GH₵150 | ~GH₵400 |
| Creator partnerships | GH₵0 (affiliate only) | GH₵300 (1–2 micro creators) | GH₵800 |
| **Total** | **~GH₵250** | **~GH₵1,130** | **~GH₵2,820** |
| When | Now: first paid test in week 2 | After the Lean test meets the CAC ceiling | Only after Moderate shows CAC < ceiling for 2 weeks |

---

## Deliverable 4 — Ready-to-use campaigns

**Rules for every asset:** real screen recordings only (your own account; blur balance
and email); example codes are fine only when clearly a demo; never fake reviews,
payment screenshots or numbers of customers; never show the 555 example numbers as
real; prices quoted with "today" because they change.

### TikTok — 15 concepts

1. **"Don't give out your number"** — street-style: a friend asks for your number to sign up for something; you say "use ours".
2. **The 60-second purchase** — screen recording, timer on screen, from opening the site to code received.
3. **"What happens if the code never comes?"** — show a real automatic refund in the wallet history.
4. **MoMo, not card** — split screen: foreign site asking for a card vs. MoMo prompt.
5. **Price board** — "What GH₵13.50 gets you" — today's popular prices, one per beat.
6. **Business vs personal number** — seller separating TikTok Shop / Google Business sign-ups from her personal line.
7. **Developer testing OTP** — dev tests a sign-up form with a real US number.
8. **Myth vs fact** — "Is this illegal?" Explain legitimate use and what's forbidden (AUP).
9. **Comment reply series** — answer real questions in video replies.
10. **Day-in-the-life of a social media manager** setting up a client brand account.
11. **"I used my real number for everything and now…"** — spam calls; privacy angle.
12. **Wallet tour** — top up GH₵20, see ledger, refunds, receipts.
13. **"Which apps work?"** — scroll the 2,000+ service catalogue; honest note that some apps refuse virtual numbers and you get refunded if no code comes.
14. **Referral explainer** — "Invite a friend: they get GH₵2, you get GH₵3 in credit — here are the rules."
15. **Founder story** — why you built a Ghanaian way to pay for verification (face to camera, trust).

### Full scripts — the strongest five

**Script 1 — "The 60-second purchase" (demo, 30–40 s)**

| Time | Shot | On-screen text | Voiceover |
|---|---|---|---|
| 0–2s | Phone on desk, timer starts | "Getting a US number with MoMo. Timer on." | "Watch me get a US verification number in under a minute." |
| 2–8s | Screen recording: getverifygh.com → Buy → search "WhatsApp" | "Price in cedis before you buy" | "Pick the app. The price is in cedis — this one's GH₵25.50 today." |
| 8–14s | Tap Buy, number appears | "Number ready" | "Pay from my wallet, and there's my number." |
| 14–24s | Second phone: paste number into the app, request code | — | "Paste it into the app, ask for the code…" |
| 24–32s | Code lands on the order screen | "Code received ✓ 0:31" | "…and it lands right here. 31 seconds." |
| 32–38s | Wallet history with a refund line | "No code? Automatic refund" | "And if a code never comes, the money goes back on its own." |
| end | Logo + URL | "getverifygh.com — pay with MoMo" | "VerifyGH. Link in bio." |

Caption: *US number for verification codes, paid with MoMo. Price in cedis, refund if no code. #Ghana #MoMo #TechGhana*
Service choice: WhatsApp (~82% delivery). Don't film TikTok or Facebook purchases until their delivery rate improves.
CTA: link in bio with `utm_source=tiktok&utm_medium=organic&utm_campaign=demo60`.

**Script 2 — "What if the code never comes?" (trust, 20–25 s)**

| Time | Shot | Text | VO |
|---|---|---|---|
| 0–2s | Face to camera, worried look | "Paid for a number, no code came 😬" | "The fear: you pay, the code never comes." |
| 2–10s | Screen: an order that expired | "Number expired" | "Here's one of mine that expired without a code." |
| 10–16s | Wallet: refund line, same amount | "Full price back — automatically" | "Full price, back in my wallet. I didn't message anyone." |
| 16–22s | Face to camera | "Use it on the next one" | "Spend it on the next number. That's how it should work." |

Caption: *No code, no charge. Refunds happen on their own on VerifyGH.* CTA: "Try it — link in bio."

**Script 3 — "Card? Crypto? No — MoMo." (problem/solution, 15–20 s)**

| Time | Shot | Text | VO |
|---|---|---|---|
| 0–2s | Hand holding phone with a "Card number" field | "Every site wants a dollar card…" | "Every verification site wants a dollar card or crypto." |
| 2–8s | Swipe to VerifyGH top-up: MTN / Telecel / AT | "…pay with MoMo instead" | "Here you top up with MoMo — MTN, Telecel or AT." |
| 8–14s | MoMo approval on phone (hide PIN), wallet credited | "GH₵20 → wallet" | "Approve on your phone, balance is in." |
| 14–18s | Buy screen | "Prices in cedis" | "Then buy numbers in cedis. Simple." |

**Script 4 — "Keep your business off your personal line" (entrepreneur, 25–30 s)**

| Time | Shot | Text | VO |
|---|---|---|---|
| 0–3s | Seller packing orders, phone buzzing | "Your personal number is on every business account?" | "If you sell online, your personal number is probably on everything." |
| 3–12s | Screen: Buy → Google / TikTok | "Use a separate number for sign-ups" | "I use a separate number to verify business sign-ups." |
| 12–20s | Code arrives | "Code in seconds" | "Code comes to my dashboard, not my SIM." |
| 20–28s | Orders list | "Every number & receipt in one place" | "Every number and receipt in one place. Paid with MoMo." |

Note for honesty: say "sign-ups", not "accounts you manage forever" — a one-code number
may not be reusable later; rentals are the product for longer use.

**Script 5 — "Myth vs fact" (education, 30 s)**

| Time | Text | VO |
|---|---|---|
| 0–2s | "Are 'verification numbers' a scam?" | "Are these verification numbers a scam? Let's see." |
| 2–9s | "Myth: they never work. Fact: if no code comes, you're refunded." | — |
| 9–16s | "Myth: you need a dollar card. Fact: MoMo." | — |
| 16–24s | "Myth: anything goes. Fact: no fraud, spam or ban evasion — it's in the rules." | "We don't allow fraud, spam or getting around bans. It's for privacy and legit sign-ups." |
| 24–30s | logo, URL | "Questions? Drop them below — I'll answer in a video." |

### Five paid ad variations

1. **Headline:** US number for your verification code — pay with MoMo. **Body:** Price in cedis before you buy. Code lands in your dashboard. No code? Automatic refund. **CTA:** Sign up free.
2. **Headline:** Don't give out your number. Use ours. **Body:** Receive sign-up codes on a US number and keep your personal line private. MTN MoMo, Telecel Cash, AT Money. **CTA:** Get started.
3. **Headline:** No dollar card? No problem. **Body:** Top up in cedis with MoMo, buy a verification number for hundreds of apps. **CTA:** See today's prices.
4. **Headline:** Sellers: keep business sign-ups off your SIM. **Body:** Verify Google, TikTok and more with a separate US number. Pay in cedis. **CTA:** Start free.
5. **Headline (Google Search, 30 chars):** US Number for SMS Codes | Pay in Cedis with MoMo | Refund If No Code Arrives. **Description:** Buy a US verification number for WhatsApp, TikTok, Google and 2,000+ apps. Pay with MoMo.

(Check "2,000+" against the catalogue count before each ad goes live.)

### Ten social posts (platform-specific)

| # | Platform | Hook | Caption / copy | CTA | Asset | Metric |
|---|---|---|---|---|---|---|
| 1 | WhatsApp Status | "Need a code for an app but don't want to give your number?" | Use a US number from VerifyGH. Pay with MoMo. | Tap: getverifygh.com | 15s cut of Script 1 | Link taps (UTM `whatsapp_status`) |
| 2 | WhatsApp Channel | "Today's prices 🇬🇭" | Instagram GH₵9 · TikTok GH₵13.50 · Telegram GH₵16 · WhatsApp GH₵25.50 (today) | Buy now | Price card | Clicks |
| 3 | Instagram Reel | "31 seconds." | Script 1 cut | Link in bio | Reel | Profile visits → link |
| 4 | Instagram carousel | "4 steps to your code" | Choose → Number → Wait → Verify | Save this | 5-slide carousel from the How-it-works section | Saves |
| 5 | Facebook (entrepreneur groups — only where self-promo is allowed) | "How I keep business sign-ups off my personal number" | Story-format post, honest | Comment "link" | Screenshot | Comments, clicks |
| 6 | X | "Built a way to pay for SMS verification in cedis." | Founder thread: why MoMo, how refunds work, what's forbidden | Try it | Thread + screenshots | Profile clicks |
| 7 | X | "Devs in Ghana testing OTP flows:" | Real US numbers, pay with MoMo, from GH₵9 today | Link | Screen recording | Clicks |
| 8 | LinkedIn | "Privacy is a product feature." | Short essay on number privacy for Ghanaian professionals | Visit | Brand graphic | Clicks |
| 9 | Telegram channel | "No code = refund. Here's proof." | Refund screenshot (blur personal data) | Buy | Screenshot | Clicks |
| 10 | TikTok | "Reply to @user: does it work for Telegram?" | Answer honestly with live price | Link in bio | Video reply | Views, sign-ups |

### Three campaign concepts

1. **"Use ours."** (brand, always on) — Your number stays yours. Creative: phone showing a
   US number while the personal number stays blurred. All channels.
2. **"No code, no charge."** (trust) — Built on the automatic refund. Show real refund
   lines. Best for retargeting people who signed up but did not buy.
3. **"Sell smart, verify separately"** (entrepreneurs, November run-up to Christmas sales)
   — Separate business sign-ups from personal SIMs. Partner with 2–3 micro-creators who
   sell online (disclose as #ad).

### Three conversion improvements

1. **Done:** hero trust line (from-price, MoMo networks, refund).
2. **Proposed:** per-service landing pages (`/numbers/whatsapp`, `/numbers/tiktok` …):
   live cedi price, "How it works for <service>", honest note that some apps refuse
   virtual numbers and you're refunded, FAQ, CTA to buy. Serves SEO and ads.
3. **Proposed (needs your OK):** Google sign-up first on /register, with the terms
   checkbox above it — one tap, and the email is already confirmed so the buyer skips
   the 6-digit email code.

### Referral campaign proposal — "Bring one friend"

Economics (current settings): friend GH₵2 + referrer GH₵3 = **GH₵5 promo credit** per
successful referral, and only after the friend has topped up **GH₵10 of their own
money** and bought a number with cash. Promo credit can only buy numbers, so its real
cost to you is the **provider cost** of the numbers it buys, not GH₵5:

At the real **26.7% margin**: GH₵5 of credit really costs about **GH₵3.67** (the provider
cost of the numbers it buys), and the friend's first GH₵10 of cash spending earns about
**GH₵2.67**. So each referral is about **−GH₵1.00 on the first cycle** and turns
profitable on the friend's next ~GH₵4 order (one delivered order earns GH₵4.35).
Promote it to customers whose orders deliver, so referred friends get a good first
experience. **Do not raise the rewards** until real margin and repeat rate are known.
Abuse protections already exist (first-deposit gate, monthly cap of 40, risk flags);
watch for many referrals sharing a MoMo number or device.

Campaign: message existing buyers once (in-app banner + email to people who opted in to
marketing — check consent first): "Invite a friend. They get GH₵2, you get GH₵3 after
their first number." Track via referral codes (already attributed).

### Onboarding messages (email/in-app, for later approval)

- **After sign-up, no top-up in 24 h:** "Your account is ready. Top up from GH₵10 with
  MoMo and buy your first number — if the code never comes, it's refunded automatically."
- **After top-up, no purchase in 24 h:** "Your GH₵X is waiting. Today: Instagram GH₵9,
  TikTok GH₵13.50…" (live prices).
- **After first code:** "Done! Star the apps you use most — they get their own row."

---

## Deliverable 5 — Tracking and profitability

### What is tracked now

| Event | Where | Status |
|---|---|---|
| Page views, referrers, countries | Cloudflare Web Analytics | Live |
| Sign-up + channel (utm_source/medium/campaign/content, landing page, referring site) | `AuditLog` action `AUTH_REGISTER`, `metadata.attribution` | **New in this change** (email and Google sign-ups) |
| Email confirmed, top-up initiated/succeeded/failed, order created/code/refund, rental, referral | Existing tables (Payment, Order, Refund, Rental, Referral) | Live |
| Repeat purchase | Derivable from Order per user | Live (query) |

No third-party pixel was added: none sees wallet balances, phone numbers, codes or
emails. If you later add the TikTok/Meta pixel, send only event names and a hashed
order value — never codes, phone numbers or balances — and update the Privacy Policy
and the CSP first.

### UTM convention

`?utm_source=<tiktok|instagram|facebook|whatsapp|x|linkedin|google|creator_name>&utm_medium=<organic|paid|status|channel|referral|bio>&utm_campaign=<yyyymm_theme>&utm_content=<video_or_ad_id>`

Examples:
- TikTok bio: `https://www.getverifygh.com/?utm_source=tiktok&utm_medium=bio&utm_campaign=202610_demo`
- WhatsApp Status: `https://www.getverifygh.com/?utm_source=whatsapp&utm_medium=status&utm_campaign=202610_prices`

### Channel report (run weekly, read-only)

```python
# python manage.py shell
from collections import Counter
from apps.audit.models import AuditLog
from apps.orders.models import Order
signups = AuditLog.objects.filter(action="AUTH_REGISTER", created_at__gte="2026-10-18")
by_user = {e.actor_id: (e.metadata.get("attribution") or {}).get("utm_source", "direct/unknown") for e in signups}
paid = set(Order.objects.filter(user_id__in=by_user, status__in=["CODE_RECEIVED", "COMPLETED"]).values_list("user_id", flat=True))
print("signups", Counter(by_user.values()))
print("buyers ", Counter(src for uid, src in by_user.items() if uid in paid))
```

### Scorecard (fill weekly)

| Metric | Formula | Wk1 | Wk2 | Wk3 | Wk4 |
|---|---|---|---|---|---|
| Visitors | Cloudflare | | | | |
| Sign-ups (by source) | AUTH_REGISTER | | | | |
| Sign-up rate | sign-ups ÷ visitors | | | | |
| Email confirmed rate | confirmed ÷ sign-ups | | | | |
| First top-up rate | depositors ÷ confirmed | | | | |
| First purchase rate | buyers ÷ sign-ups | | | | |
| Average order value | revenue ÷ paid orders | | | | |
| Refund rate | refunded ÷ orders | | | | |
| Gross margin | (price − provider cost) ÷ price | | | | |
| Contribution per order | AOV × margin − refund losses | | | | |
| Repeat rate (30 d) | buyers with ≥2 orders ÷ buyers | | | | |
| Spend by channel | ad + creator + promo credit | | | | |
| CAC by channel | spend ÷ new buyers | | | | |
| ROAS | revenue ÷ ad spend (not profit!) | | | | |
| Contribution ROI | contribution ÷ spend | | | | |

### CAC ceiling (fill in the real margin)

`Max CAC = contribution per order × orders per customer in 60 days`

Profit per delivered order is **GH₵4.35** (real, 30 days). Orders per customer is not on
the dashboard yet, so the right-hand column is still a scenario:

| Delivered orders per new customer in 60 days | Max CAC (break-even) |
|---|---|
| 2 | **GH₵8.70** |
| 3 | **GH₵13.05** |
| 4 | **GH₵17.40** |

Use **GH₵8.70** as the working ceiling until repeat-purchase data exists. Your earlier
GH₵75.94 TikTok promotion breaks even only if it brings about **18 delivered orders**
(roughly 6–9 new paying customers).

### Which campaigns get more budget

- Increase only when **contribution ROI > 1.0 for two weeks in a row** and the payment
  provider pays out.
- Judge on **buyers**, not sign-ups or views. A video with 50k views and 0 buyers loses
  to one with 2k views and 10 buyers.
- A channel with high refund rates (codes not arriving for that service) gets fixed or
  paused, not scaled.

---

## Deliverable 6 — Implementation

### Done in this change (not deployed, not committed)

| Change | Files |
|---|---|
| Removed the untrue "processed by Paystack" claims | `frontend/src/components/marketing/payment-section.tsx`, `privacy-section.tsx` |
| Hero trust line: live from-price, MoMo networks, refund | `frontend/src/components/marketing/hero.tsx` |
| Search title and description written for real searches | `frontend/src/app/layout.tsx` |
| Canonical URLs (home, /services, /help) + descriptions | `frontend/src/app/page.tsx`, `services/layout.tsx`, `help/layout.tsx` |
| Organization + WebSite structured data | `frontend/src/app/page.tsx` |
| `/sitemap.xml` and `/robots.txt` with sitemap and private paths | `frontend/src/app/sitemap.ts`, `robots.ts` |
| First-touch campaign attribution captured in the browser | `frontend/src/components/attribution.tsx`, `providers.tsx`, register page, Google start URL |
| Attribution recorded on the sign-up audit entry (email + Google), cleaned, never blocks sign-up | `backend/apps/accounts/attribution.py`, `serializers.py`, `views.py` |
| Tests | `backend/tests/test_signup_attribution.py`, `test_turnstile_and_google.py` |

### Needs your action or approval

1. Review, commit and deploy (frontend + backend). No database migration.
2. Cloudflare: 301 redirect `getverifygh.com/*` → `https://www.getverifygh.com/$1`.
3. Google Search Console: verify the domain, submit `sitemap.xml`.
4. Admin > Catalog: merge the duplicate "X (Twitter)".
5. Approve: Google-first sign-up layout (#8 in the audit).
6. Approve: per-service landing pages (next build).
7. Provide: WhatsApp Business support number, social handles, company name after ORC.
8. Privacy Policy: one line that we record the campaign link a visitor arrived from.
9. Withdraw the SENDI balance to MoMo daily while ads run; pause ads if a withdrawal fails.
10. Product: per-service delivery-rate view, and fix or pause services under ~40% delivery (TikTok, Facebook, Instagram, Telegram).

### Data still missing

Repeat-purchase rate (how many delivered orders each customer makes) is not on the
dashboard. It decides whether the CAC ceiling is GH₵8.70 or GH₵17.40.
