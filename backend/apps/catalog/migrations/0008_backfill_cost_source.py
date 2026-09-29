"""Mark existing provider costs as coming from the provider's API.

Every cost in the catalogue so far arrived through a catalogue sync, so that is
what they are labelled. A zero cost stays NOT_SYNCED - we never knew it, and it
is never sold. The recommended price starts equal to the published one.
"""

from django.db import migrations
from django.db.models import F


def apply(apps, schema_editor):
    ProviderService = apps.get_model("catalog", "ProviderService")
    ProviderService.objects.filter(cost_amount__gt=0).update(cost_source="PROVIDER_API")
    ProviderService.objects.filter(customer_price__isnull=False).update(
        recommended_price=F("customer_price")
    )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0007_cost_source_and_price_review")]

    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
