# public/urls.py
from django.urls import path
from . import views

app_name = "public"

urlpatterns = [
    path("<slug:slug>/", views.company_presentation, name="company_presentation"),
    path("<slug:slug>/register/", views.referrer_register, name="referrer_register"),  # <-- fix
    path("<slug:slug>/reset-request/", views.referrer_reset_request, name="referrer_reset_request"),
    path("<slug:slug>/reset/<str:token>/", views.referrer_reset_edit, name="referrer_reset_edit"),
]
