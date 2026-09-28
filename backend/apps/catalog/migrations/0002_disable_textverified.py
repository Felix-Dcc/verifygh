"""Disable the TextVerified provider row.

VerifyGH sources numbers from OnlineSim only. TextVerified refused resale
permission and is no longer in the adapter registry, but production still has
the row created when it was the configured provider - enabled, with no
offerings and a stale "not configured" sync error. Disabled rather than deleted
so the history of what was once configured stays readable.
"""

from django.db import migrations


def disable(apps, schema_editor):
    Provider = apps.get_model("catalog", "Provider")
    Provider.objects.filter(adapter_key="textverified").update(is_enabled=False)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [migrations.RunPython(disable, migrations.RunPython.noop)]
