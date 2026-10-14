from django.db import migrations, models


def raise_old_default(apps, schema_editor):
    """The programme row already exists in production at the old cap of 20.

    Only a row still at 20 is moved: a value someone chose on purpose stays.
    """
    ReferralProgram = apps.get_model("referrals", "ReferralProgram")
    ReferralProgram.objects.filter(max_monthly_successful_referrals=20).update(
        max_monthly_successful_referrals=40)


def restore_old_default(apps, schema_editor):
    ReferralProgram = apps.get_model("referrals", "ReferralProgram")
    ReferralProgram.objects.filter(max_monthly_successful_referrals=40).update(
        max_monthly_successful_referrals=20)


class Migration(migrations.Migration):

    dependencies = [
        ('referrals', '0003_referral_velocity_40'),
    ]

    operations = [
        migrations.AlterField(
            model_name='referralprogram',
            name='max_monthly_successful_referrals',
            field=models.PositiveIntegerField(default=40),
        ),
        migrations.RunPython(raise_old_default, restore_old_default),
    ]
