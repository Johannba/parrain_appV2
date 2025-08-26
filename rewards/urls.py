# rewards/urls.py
from django.urls import path
from .views import reward_list, reward_update, referral_delete, reward_spin  # + reward_spin

app_name = "rewards"

urlpatterns = [
    path("", reward_list, name="list"),
    path("<int:pk>/edit/", reward_update, name="update"),
    path("referrals/<int:pk>/delete/", referral_delete, name="referral_delete"),
    # NEW: page d’animation de la roue pour une Reward donnée
    path("spin/<int:reward_id>/", reward_spin, name="spin"),
]
