"""Give existing services the logos added to service_icons.json.

Only services with no logo yet are touched - nothing staff set or uploaded is
overwritten. Matched exactly as apps.catalog.presentation.bundled_icon_url
does: by slug, then by the slug or name as a brand key. The key list is frozen
here so this migration keeps doing what it did.
"""

import re

from django.db import migrations

KEYS = frozenset([
    "3223", "acer", "activision", "adidas", "adp", "aeroplan", "afterpay", "airasia", "airbnb",
    "airchina", "airfrance", "airtable", "alibaba", "aliexpress", "alipay", "americanairlines",
    "americanexpress", "apple", "asus", "atandt", "autodesk", "backblaze", "badoo", "baidu",
    "bandcamp", "bankofamerica", "barclays", "battle.net", "battle_net", "bereal", "bilibili",
    "binance", "bitly", "blockchain", "bluesky", "booking.com", "bose", "brevo", "brex",
    "britishairways", "burgerking", "cashapp", "chase", "chess", "chevrolet", "civo", "claude",
    "cloudways", "clubhouse", "cocacola", "coinbase", "coursera", "crunchyroll", "cursor",
    "deezer", "deliveroo", "dell", "dhl", "discord", "discover", "distrokid", "doordash",
    "dropbox", "duckduckgo", "duolingo", "easyjet", "ebay", "emirates", "epicgames", "etsy",
    "expedia", "facebook", "faceit", "fedex", "figma", "fiverr", "flickr", "foodpanda",
    "freelancer", "g2a", "g2g", "github", "gitlab", "globus", "glovo", "gmail", "gmx",
    "godaddy", "gofundme", "gojek", "google", "googlechat", "grab", "grammarly", "groupme",
    "gusto", "handm", "handshake", "hbomax", "helpscout", "hostinger", "hotelscom", "hsbc",
    "huawei", "humblebundle", "icq", "ikea", "imgur", "indeed", "instacart", "instagram",
    "intuit", "invoiceninja", "ionos", "jetblue", "justeat", "kaggle", "kakao", "kakaotalk",
    "keybase", "kfc", "kick", "kickstarter", "kimi", "klarna", "klm", "klook", "kuaishou",
    "kucoin", "kucoinplay", "leagueoflegends", "lenovo", "line", "linemessenger", "lufthansa",
    "lyft", "mail", "mailcom", "mailgun", "mailru", "mastercard", "mastodon", "mcdonalds",
    "medium", "mega", "meituan", "mercadopago", "meta", "mewe", "miro", "mlb", "moneygram",
    "monzo", "motorola", "n26", "namecheap", "naver", "netflix", "newegg", "nextdoor", "nike",
    "nokia", "notion", "nubank", "nvidia", "odklru", "okcupid", "okta", "okx", "oneplus",
    "onlyfans", "opera", "oppo", "ovhtelecom", "oyo", "paperspace", "patreon", "payoneer",
    "paypal", "peloton", "perplexity", "pinterest", "pixiv", "playstation", "porkbun",
    "postmates", "proton", "protonmail", "qatarairways", "qq", "quickbooks", "quora",
    "rakuten", "razer", "razorpay", "redbubble", "reddit", "revolut", "riotgames", "robinhood",
    "roblox", "rockstargames", "roku", "rumble", "ryanair", "samsung", "shell", "shopee",
    "shopify", "signal", "snapchat", "sony", "soundcloud", "southwestairlines", "spotify",
    "squarespace", "starbucks", "starlingbank", "steam", "steem", "steemit", "stockx",
    "strava", "stripe", "substack", "swiggy", "tacobell", "taobao", "telegram", "tencentqq",
    "tesla", "threads", "ticketmaster", "tidal", "tiktok", "tinder", "tradingview", "trello",
    "trezor", "tripadvisor", "tripcom", "tumblr", "turkishairlines", "twitch", "twitter",
    "uber", "ubereats", "ubisoft", "udemy", "uniqlo", "unitedairlines", "uphold", "upwork",
    "valve", "venmo", "vercel", "verizon", "viber", "vimeo", "vinted", "visa", "vkcom",
    "vodafone", "vonage", "wechat", "weibo", "wellsfargo", "westernunion", "whatsapp", "wise",
    "wix", "wordpress", "x", "xiaomi", "yelp", "youtube", "zalando", "zalo", "zara", "zelle",
    "zendesk", "zillow", "zoho", "zomato", "zoom",
])


def _key(text):
    text = (text or "").lower().replace("&", "and").replace("+", "plus")
    return re.sub(r"[^a-z0-9]", "", text)


def assign(apps, schema_editor):
    Service = apps.get_model("catalog", "Service")
    for service in Service.objects.filter(icon_url="", logo_data__isnull=True).only("id", "slug", "name"):
        for key in (service.slug, _key(service.slug), _key(service.name)):
            if key and key in KEYS:
                Service.objects.filter(pk=service.pk).update(icon_url=f"/service-icons/{key}.svg")
                break


class Migration(migrations.Migration):
    dependencies = [("catalog", "0010_record_resale_authorizations")]
    operations = [migrations.RunPython(assign, migrations.RunPython.noop)]
