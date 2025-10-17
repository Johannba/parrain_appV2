"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.shortcuts import redirect,render
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.db import connection
from django.http import JsonResponse



def healthz(request):
    # ping DB pour un vrai "ready"
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as e:
        return JsonResponse({"status": "error", "db": str(e)}, status=503)
    return JsonResponse({"status": "ok"}, status=200)

# urlpatterns = [
#     path("", root_view, name="root"), 
#     path('admin/', admin.site.urls),
#     path("", include("public.urls")),
#     path('', include(('dashboard.urls', 'dashboard'), namespace='dashboard')),
#     path('accounts/', include('accounts.urls')),
#     path('entreprise/', include('entreprises.urls', namespace='entreprises')),
#     path('rewards/', include(('rewards.urls',"rewards"), namespace='rewards')),
#     path("healthz", healthz, name="healthz"),
#     path("healthz/", healthz, name="healthz-slash"),
# ]
    return JsonResponse({"status": "ok"}, status=200)

def root_view(request):
    if request.user.is_authenticated:
        u = request.user
        # Oriente selon les rôles si tu veux
        if hasattr(u, "is_superadmin") and u.is_superadmin():
            return redirect("dashboard:superadmin_home")
        if (hasattr(u, "is_admin_entreprise") and u.is_admin_entreprise()) or \
           (hasattr(u, "is_operateur") and u.is_operateur()):
            return redirect("dashboard:company_home")
        # Fallback connecté
        return redirect("/dashboard/")
    # Anonyme → page publique ou login
    return render(request, "public/home.html")   # ou: 
    
urlpatterns = [
    path("", root_view, name="root"),
    path("chuchote/", include("public.urls")),
    path("dashboard/", include("dashboard.urls")),   # <— simple et robuste
    path("accounts/", include("accounts.urls")),
    path("entreprise/", include(("entreprises.urls", "entreprises"), namespace="entreprises")),
    path("rewards/", include(("rewards.urls", "rewards"), namespace="rewards")),
    path("admin/", admin.site.urls),

    path("healthz", healthz, name="healthz"),
    path("healthz/", healthz, name="healthz-slash"),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
