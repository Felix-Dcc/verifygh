"""Record which providers had already authorised resale when the field arrived.

OnlineSim's support confirmed in writing on 2026-09-27 that its API may be
integrated into third-party software products (docs/PROVIDER_INTEGRATION.md),
so its existing row keeps selling exactly as before. The mock provider is the
development stand-in; production refuses to run it at all. TextVerified's
terms prohibit sharing its numbers with third parties and no authorisation
exists, so it stays unauthorised until staff record one.
"""

from datetime import datetime, UTC

from django.db import migrations

ONLINESIM_REFERENCE = (
    "OnlineSim support chat, 2026-09-27: the API may be integrated into third-party "
    "software products; our account is responsible for our users' actions."
)


def record(apps, schema_editor):
    Provider = apps.get_model("catalog", "Provider")
    Provider.objects.filter(adapter_key="onlinesim").update(
        resale_authorized=True,
        authorization_reference=ONLINESIM_REFERENCE,
        authorized_at=datetime(2026, 9, 27, tzinfo=UTC),
    )
    Provider.objects.filter(adapter_key="mock").update(
        resale_authorized=True,
        authorization_reference="Development mock provider. Production refuses to run it.",
    )


def unrecord(apps, schema_editor):
    Provider = apps.get_model("catalog", "Provider")
    Provider.objects.filter(adapter_key__in=["onlinesim", "mock"]).update(
        resale_authorized=False, authorization_reference="", authorized_at=None,
    )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0009_provider_resale_authorization")]

    operations = [migrations.RunPython(record, unrecord)]
