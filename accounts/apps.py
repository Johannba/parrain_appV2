from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Comptes & Rôles"

    def ready(self):
        # place pour des signaux si besoin
        pass
