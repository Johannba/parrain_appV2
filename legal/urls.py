from django.urls import path
from . import views

app_name = "legal"

urlpatterns = [
    path("mentions-legales/", views.mentions_legales, name="mentions"),
    path("cgu/", views.cgu, name="cgu"),
    path("politique-confidentialite/", views.politique_confidentialite, name="privacy"),
    path("contact/", views.contact, name="contact"),
]
