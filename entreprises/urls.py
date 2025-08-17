from django.urls import path
from . import views

app_name = "entreprises"

urlpatterns = [
    path("clients/", views.clients_list, name="clients_list"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),  # si tu as une page détail
]
