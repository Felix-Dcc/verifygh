"""Move uploaded logo bytes out of catalog_service into catalog_service_logo.

Loading services loaded every logo with them; the catalogue rebuild alone pulled
~2,150 images into memory and pushed the API past its 512 MB (27 Nov 2026).

The old column is dropped from the model only. It stays in the database for
now, so the code still running during the deploy keeps working; a later
migration removes it.
"""

from django.db import migrations, models
import django.db.models.deletion


def copy_logos(apps, schema_editor):
    Service = apps.get_model("catalog", "Service")
    ServiceLogo = apps.get_model("catalog", "ServiceLogo")
    rows = (Service.objects.filter(logo_data__isnull=False)
            .values_list("pk", "logo_data").iterator(chunk_size=50))
    for pk, data in rows:
        ServiceLogo.objects.update_or_create(service_id=pk, defaults={"data": bytes(data)})


def copy_back(apps, schema_editor):
    Service = apps.get_model("catalog", "Service")
    ServiceLogo = apps.get_model("catalog", "ServiceLogo")
    for logo in ServiceLogo.objects.iterator(chunk_size=50):
        Service.objects.filter(pk=logo.service_id).update(logo_data=bytes(logo.data))


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0012_service_brand_logo"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceLogo",
            fields=[
                ("service", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                    related_name="uploaded_logo", serialize=False, to="catalog.service")),
                ("data", models.BinaryField()),
            ],
            options={"db_table": "catalog_service_logo"},
        ),
        migrations.RunPython(copy_logos, copy_back),
        # Off the model, still in the table (see the docstring).
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="service", name="logo_data")],
            database_operations=[],
        ),
    ]
