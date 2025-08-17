from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_root, name='root'),                  # /dashboard/ -> redirige selon le rôle
    path('superadmin/', views.superadmin_home, name='superadmin_home'),
    path('entreprise/', views.company_home, name='company_home'),
]
