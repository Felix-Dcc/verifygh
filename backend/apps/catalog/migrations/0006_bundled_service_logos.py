"""Point existing services at their bundled logos.

Only services with no logo yet are touched, so nothing staff set is
overwritten. The slug list is frozen here (copied from service_icons.json at
the time of writing) so this migration keeps doing what it did.

Also gives OnlineSim's Facebook - slug "3223" - its presentation, which the
0004 backfill missed because it looked for "facebook".
"""

from django.db import migrations

BUNDLED = [
    "3223",
    "adidas",
    "airbnb",
    "alibaba",
    "aliexpress",
    "apple",
    "badoo",
    "baidu",
    "battle_net",
    "binance",
    "blockchain",
    "brex",
    "burgerking",
    "claude",
    "coinbase",
    "deliveroo",
    "dhl",
    "discord",
    "doordash",
    "ebay",
    "facebook",
    "faceit",
    "fedex",
    "foodpanda",
    "freelancer",
    "g2a",
    "github",
    "gitlab",
    "globus",
    "glovo",
    "google",
    "groupme",
    "huawei",
    "icq",
    "instagram",
    "kakaotalk",
    "keybase",
    "kimi",
    "kucoinplay",
    "linemessenger",
    "lyft",
    "mail",
    "mega",
    "naver",
    "netflix",
    "nike",
    "nvidia",
    "odklru",
    "ovhtelecom",
    "perplexity",
    "porkbun",
    "proton",
    "qq",
    "redbubble",
    "reddit",
    "roblox",
    "shell",
    "shopee",
    "signal",
    "snapchat",
    "starbucks",
    "steam",
    "steem",
    "steemit",
    "taobao",
    "telegram",
    "tencentqq",
    "ticketmaster",
    "tiktok",
    "tinder",
    "tradingview",
    "twitch",
    "twitter",
    "uber",
    "ubisoft",
    "vercel",
    "viber",
    "vinted",
    "vkcom",
    "wechat",
    "whatsapp",
    "x",
    "zalo",
    "zillow",
    "zoho",
    "zomato",
]


def apply(apps, schema_editor):
    Service = apps.get_model("catalog", "Service")
    for slug in BUNDLED:
        Service.objects.filter(slug=slug, icon_url="").update(icon_url=f"/service-icons/{slug}.svg")
    Service.objects.filter(slug="3223").update(
        name="Facebook", aliases="fb, meta", category="SOCIAL", is_popular=True, popular_rank=5
    )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0005_service_logos")]

    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
