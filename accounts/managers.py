# accounts/managers.py
from django.contrib.auth.models import UserManager as DjangoUserManager

class UserManager(DjangoUserManager):
    def _normalize_ids(self, username=None, email=None):
        return (username or "").strip().lower(), (email or "").strip().lower()

    def create_user(self, username, email=None, password=None, **extra_fields):
        username, email = self._normalize_ids(username, email)
        return super().create_user(username=username, email=email, password=password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        username, email = self._normalize_ids(username, email)
        return super().create_superuser(username=username, email=email, password=password, **extra_fields)
