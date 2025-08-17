from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from accounts.models import User  # pour l’IDE uniquement

@login_required
def dashboard_root(request):
    u = request.user
    if hasattr(u, "is_superadmin") and u.is_superadmin():
        return redirect("dashboard:superadmin_home")
    if hasattr(u, "is_admin_entreprise") and (u.is_admin_entreprise() or u.is_operateur()):
        return redirect("dashboard:company_home")
    # Client (V1 non utilisable) ou autre cas
    raise PermissionDenied("Accès réservé au personnel.")

@login_required
def superadmin_home(request):
    u = request.user
    if not (hasattr(u, "is_superadmin") and u.is_superadmin()):
        raise PermissionDenied("Réservé au Superadmin.")
    # TODO: brancher ici des stats globales si tu veux (context)
    context = {}
    return render(request, "dashboard/superadmin_home.html", context)

@login_required
def company_home(request):
    u = request.user
    if not (hasattr(u, "is_superadmin") and u.is_superadmin()) \
       and not (hasattr(u, "is_admin_entreprise") and u.is_admin_entreprise()) \
       and not (hasattr(u, "is_operateur") and u.is_operateur()):
        raise PermissionDenied("Réservé à l’Admin/Opérateur (ou Superadmin).")

    company = getattr(u, "company", None)
    context = {"company": company}
    return render(request, "dashboard/company_home.html", context)
