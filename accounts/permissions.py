from django.core.exceptions import PermissionDenied

def require_superadmin(user):
    if not user.is_authenticated or not user.is_superadmin():
        raise PermissionDenied("Réservé au Superadmin.")

def require_company_admin_or_superadmin(user):
    if not user.is_authenticated:
        raise PermissionDenied()
    if user.is_superadmin():
        return
    if not user.is_admin_entreprise():
        raise PermissionDenied("Réservé à l’Admin d’entreprise (ou Superadmin).")
