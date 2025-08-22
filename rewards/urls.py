from django.urls import path
from .views import reward_create, reward_delete, reward_list, reward_update


app_name = "rewards" 

urlpatterns = [
    path("", reward_list, name="list"),
    path("create/", reward_create, name="create"),
    path("<int:pk>/edit/", reward_update, name="update"),
    path("<int:pk>/delete/", reward_delete, name="delete"),

   

]
