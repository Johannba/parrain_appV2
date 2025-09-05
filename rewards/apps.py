# rewards/apps.py
from django.apps import AppConfig

class RewardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rewards"
    verbose_name = "Récompenses"

    def ready(self):
        import rewards.signals  # noqa
