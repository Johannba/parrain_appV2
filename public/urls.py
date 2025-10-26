# public/urls.py
from django.urls import path
from . import views

app_name = "public"

urlpatterns = [
   
    path("<slug:slug>/", views.company_presentation, name="company_presentation"),
    path("chuchote/<slug:slug>/register/", views.referrer_register, name="referrer_register"),
    path("<slug:slug>/reset-access/", views.referrer_reset_access, name="referrer_reset_access"),
]
