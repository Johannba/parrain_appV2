from django.urls import path
from .views import reward_list, reward_update


app_name = "rewards" 

urlpatterns = [
   path("", reward_list, name="list"),
   path("<int:pk>/edit/", reward_update, name="update"), 
]
