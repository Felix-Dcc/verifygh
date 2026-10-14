from decimal import Decimal

from django.db import migrations, models


def lower_old_default(apps, schema_editor):
    """The programme row already exists in production at the old GH₵5.

    Only a row still at 5.00 is moved: an amount someone chose on purpose stays.
    """
    ReferralProgram = apps.get_model("referrals", "ReferralProgram")
    ReferralProgram.objects.filter(signup_bonus=Decimal("5.00")).update(
        signup_bonus=Decimal("2.00"))


def restore_old_default(apps, schema_editor):
    ReferralProgram = apps.get_model("referrals", "ReferralProgram")
    ReferralProgram.objects.filter(signup_bonus=Decimal("2.00")).update(
        signup_bonus=Decimal("5.00"))


class Migration(migrations.Migration):

    dependencies = [
        ('referrals', '0004_referral_monthly_cap_40'),
    ]

    operations = [
        migrations.AlterField(
            model_name='referralprogram',
            name='signup_bonus',
            field=models.DecimalField(decimal_places=2, default=Decimal('2.00'), max_digits=10),
        ),
        migrations.RunPython(lower_old_default, restore_old_default),
    ]
