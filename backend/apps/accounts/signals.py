from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import User


@receiver(post_save, sender=User, dispatch_uid="accounts.create_wallet")
def create_wallet_for_user(sender, instance: User, created: bool, **kwargs) -> None:
    """Every account owns exactly one GHS wallet, created with it."""
    if not created:
        return
    from apps.wallet.models import Wallet

    Wallet.objects.get_or_create(user=instance)
