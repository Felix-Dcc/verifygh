"""Seed the pricing policy, and keep today's rate as the VerifyGH Pricing FX Rate.

Until now the engine priced with the latest market-rate row, and refused to
price at all once that row was 36 hours old - so a rate typed in by hand
quietly switched the shop off a day and a half later. The rate staff set is a
pricing decision, not a market quote, so it becomes a MANUAL pricing rate that
does not expire. Prices do not change: same rate, same rules.

Where no rate was ever set (a fresh database), nothing is created and the
engine falls back to the market rate, as before.
"""

from django.db import migrations


def apply(apps, schema_editor):
    ExchangeRate = apps.get_model("pricing", "ExchangeRate")
    PricingFXRate = apps.get_model("pricing", "PricingFXRate")
    PricingPolicy = apps.get_model("pricing", "PricingPolicy")

    PricingPolicy.objects.get_or_create(pk=1)
    latest = (ExchangeRate.objects.filter(base_currency="USD", quote_currency="GHS", is_active=True)
              .order_by("-fetched_at", "-id").first())
    if latest is not None:
        PricingFXRate.objects.get_or_create(
            base_currency="USD",
            defaults={"quote_currency": "GHS", "mode": "MANUAL", "manual_rate": latest.rate},
        )


class Migration(migrations.Migration):
    dependencies = [("pricing", "0003_fx_policy_overrides_cost_history")]

    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
