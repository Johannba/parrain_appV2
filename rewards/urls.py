from django.urls import path
from .views import reward_list, reward_update, referral_delete

app_name = "rewards" 

urlpatterns = [
   path("", reward_list, name="list"),
   path("<int:pk>/edit/", reward_update, name="update"),
   path("referrals/<int:pk>/delete/", referral_delete, name="referral_delete"),
]
