# dashboard/urls.py
from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    # Accueils
    path("", views.dashboard_root, name="root"),
    path("superadmin/", views.superadmin_home, name="superadmin_home"),
    path("company/", views.company_home, name="company_home"),

    # Clients – liste / détail
    path("clients/", views.clients_list, name="clients_list"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),


    # Clients – édition & suppression (le form est choisi automatiquement)
    path("clients/<int:pk>/edit/", views.client_update, name="client_update"),
    path("clients/<int:pk>/delete/", views.client_delete, name="client_delete"),
    
  # ✅ Création d'un PARRAIN (écran séparé)
    path("clients/referrers/new/", views.referrer_create, name="referrer_create"),
    
    # Parrainage : création via recherche du parrain + formulaire du filleul
    path("referrals/create/", views.referral_create, name="referral_create"),
     path("clients/referrer/<int:pk>/edit/", views.referrer_update, name="referrer_update"),
      # 🔎 API de recherche de parrains
    path("api/referrers/", views.referrer_lookup, name="referrer_lookup"),

    # Récompenses (manuel + validations)
    path("clients/<int:pk>/rewards/new/", views.reward_create, name="reward_create"),
    path("referrals/<int:referral_id>/validate/", views.validate_referral_and_award, name="validate_referral_and_award"),
    path("referrals/<int:referral_id>/award-referrer/", views.validate_referral_and_award_referrer, name="validate_referral_and_award_referrer"),
]
