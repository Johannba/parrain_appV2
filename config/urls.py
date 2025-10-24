# config/urls.py
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.db import connection
from django.http import JsonResponse

def healthz(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as e:
        return JsonResponse({"status": "error", "db": str(e)}, status=503)
    return JsonResponse({"status": "ok"}, status=200)

def root_view(request):
    # Connecté → dispatch par rôle
    if request.user.is_authenticated:
        u = request.user
        if hasattr(u, "is_superadmin") and u.is_superadmin():
            return redirect("dashboard:superadmin_home")
        if (hasattr(u, "is_admin_entreprise") and u.is_admin_entreprise()) or \
           (hasattr(u, "is_operateur") and u.is_operateur()):
            return redirect("dashboard:company_home")
        return redirect("dashboard:root")

    # Anonyme → envoyer vers le dashboard ;
    # le login_required du dashboard renverra vers /accounts/login/?next=/dashboard/
    try:
        return redirect("dashboard:root")  # si tu as un name de route pour la home dashboard
    except Exception:
        return redirect("/dashboard/")     # fallback simple

urlpatterns = [
    path("", root_view, name="root"),
    path("chuchote/", include("public.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("entreprise/", include(("entreprises.urls", "entreprises"), namespace="entreprises")),
    path("rewards/", include(("rewards.urls", "rewards"), namespace="rewards")),
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("healthz/", healthz, name="healthz-slash"),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
