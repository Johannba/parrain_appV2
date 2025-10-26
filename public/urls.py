# public/urls.py
from django.urls import path
from . import views

app_name = "public"

urlpatterns = [
   
    path("<slug:slug>/", views.company_presentation, name="company_presentation"),
    path("chuchote/<slug:slug>/register/", views.referrer_register, name="referrer_register"),
     # ✉️ Demande de réinitialisation de profil (envoi du lien)
    path("<slug:slug>/reset-request/", views.referrer_reset_request, name="referrer_reset_request"),
    # 📝 Formulaire de réinitialisation via lien tokenisé
    path("<slug:slug>/reset/<str:token>/", views.referrer_reset_edit, name="referrer_reset_edit"),
]
