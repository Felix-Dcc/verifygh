from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CommonConfig(AppConfig):
    name = "apps.common"
    label = "common"

    def ready(self):
        from apps.common.supabase import on_post_migrate

        # Not sender-bound: it must see the last app to migrate, and it skips
        # the rest itself.
        post_migrate.connect(on_post_migrate, dispatch_uid="verifygh.supabase_lockdown")
