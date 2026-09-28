"""Backfill presentation onto services that already exist.

Clean names, search aliases ("gmail" finds Google), categories, and the
staff-chosen popular list. Only rows that exist are touched, and only the
presentation fields - never prices, availability or anything a sync owns.

The table is copied here rather than imported, so this migration keeps doing
what it did even after apps/catalog/presentation.py changes.
"""

from django.db import migrations

PRESENTATION = {
    "tiktok": ("TikTok", "tik tok", "SOCIAL", 1),
    "whatsapp": ("WhatsApp", "whats app", "MESSAGING", 2),
    "telegram": ("Telegram", "", "MESSAGING", 3),
    "google": ("Google / Gmail", "gmail, youtube", "EMAIL", 4),
    "facebook": ("Facebook", "fb, meta", "SOCIAL", 5),
    "instagram": ("Instagram", "ig, insta", "SOCIAL", 6),
    "discord": ("Discord", "", "MESSAGING", 7),
    "signal": ("Signal", "", "MESSAGING", 8),
    "twitter": ("X (Twitter)", "x, twitter", "SOCIAL", 9),
    "x": ("X (Twitter)", "x, twitter", "SOCIAL", 9),
    "snapchat": ("Snapchat", "snap", "SOCIAL", None),
    "tinder": ("Tinder", "", "SOCIAL", None),
    "linkedin": ("LinkedIn", "", "BUSINESS", None),
    "openai": ("ChatGPT / OpenAI", "chatgpt, openai", "DEVELOPER", None),
    "microsoft": ("Microsoft / Outlook", "outlook, hotmail, live", "EMAIL", None),
    "yahoo": ("Yahoo", "yahoo mail", "EMAIL", None),
    "apple": ("Apple", "icloud, apple id", "OTHER", None),
    "amazon": ("Amazon", "", "SHOPPING", None),
    "steam": ("Steam", "", "GAMING", None),
    "netflix": ("Netflix", "", "OTHER", None),
    "uber": ("Uber", "", "OTHER", None),
    "paypal": ("PayPal", "", "FINANCE", None),
}


def apply(apps, schema_editor):
    Service = apps.get_model("catalog", "Service")
    for slug, (name, aliases, category, rank) in PRESENTATION.items():
        fields = {"name": name, "aliases": aliases, "category": category}
        if rank is not None:
            fields.update(is_popular=True, popular_rank=rank)
        Service.objects.filter(slug=slug).update(**fields)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_marketplace_fields")]

    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
