# accounts/backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

class CaseInsensitiveModelBackend(ModelBackend):
    """
    Auth insensible à la casse pour USERNAME_FIELD (username par défaut).
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None or password is None:
            return None

        field = User.USERNAME_FIELD  # "username" sauf si tu l'as changé
        try:
            user = User._default_manager.get(**{f"{field}__iexact": username})
        except User.DoesNotExist:
            # Anti-oracle de timing
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
