from django.urls import path
from . import views

app_name = "legal"

urlpatterns = [
    path("contact/", views.contact_view, name="contact"),
    path("mentions-legales/", views.mentions_view, name="mentions"),
    path("cgu/", views.cgu_view, name="cgu"),
    path("politique-de-confidentialite/", views.privacy_view, name="privacy"),
]
