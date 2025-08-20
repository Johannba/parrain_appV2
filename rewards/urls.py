from django.urls import path
from . import views

app_name = "rewards" 

urlpatterns = [
    path("", views.reward_list, name="list"),
    path("new/", views.reward_create, name="create"),
    path("<int:pk>/edit/", views.reward_update, name="update"),
    path("<int:pk>/delete/", views.reward_delete, name="delete"),
    path("<int:pk>/send/", views.reward_send_email, name="send_email"),
]
