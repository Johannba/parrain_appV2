from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_root, name='root'),                  # /dashboard/ -> redirige selon le rôle
    path('superadmin/', views.superadmin_home, name='superadmin_home'),
    path('entreprise/', views.company_home, name='company_home'),
    
       # Clients
    path('clients/', views.clients_list, name='clients_list'),
    path('clients/<int:pk>/', views.client_detail, name='client_detail'),
      path('clients/<int:pk>/rewards/new/', views.reward_create, name='reward_create'),
    path("clients/new/", views.client_create, name="client_create"),
    path("referrals/new/", views.referral_create, name="referral_create")  
]
