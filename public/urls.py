# public/urls.py
from django.urls import path
from . import views

app_name = "public"

urlpatterns = [
    path("", views.root_view, name="home"),  # ← racine publique
    path("p/<slug:slug>/", views.company_presentation, name="company_presentation"),
    path("p/<slug:slug>/register/", views.referrer_register, name="referrer_register"),
]
