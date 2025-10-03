# accounts/utils/password_reset.py
from __future__ import annotations

from typing import Optional
from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm


def send_password_reset_if_user_exists(
    request,
    email: str,
    *,
    subject_template: Optional[str] = "registration/password_reset_subject.txt",
    email_template: Optional[str] = "registration/password_reset_email.txt",
    html_email_template: Optional[str] = "registration/password_reset_email.html",
    from_email: Optional[str] = None,
) -> bool:
    """
    Envoie l'e-mail de réinitialisation SEULEMENT si un User actif avec mot de passe utilisable existe.
    Retourne True si l'e-mail a été effectivement tenté (au moins un destinataire).
    Exceptions SMTP non masquées (fail_silently=False) pour débogage.
    """
    email = (email or "").strip()
    if not email:
        return False

    form = PasswordResetForm(data={"email": email})
    if not form.is_valid():
        return False

    recipients = list(form.get_users(email))
    if not recipients:
        return False

    form.save(
        request=request,
        use_https=request.is_secure(),
        from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None),
        subject_template_name=subject_template,
        email_template_name=email_template,
        html_email_template_name=html_email_template,
        fail_silently=False,
    )
    return True
